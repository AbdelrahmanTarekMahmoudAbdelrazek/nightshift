#!/usr/bin/env python3
"""Night Shift repro for Crashlytics 2bc43cd6 / Play 8de37610: SIGSEGV in VisualTimeLine::get_media_starting_time.
Fully automatic: no hands on the phone.

Field story (every event + the team's manual repro): the slideshow screen is torn down and rebuilt while the template
is still loading; the medias are deleted while messages already queued on the MsgLooper still run with the old media
ids -> "media_id bigger than visual objects number" -> null dereference in get_media_starting_time.

Each try:  restart app -> SlideShow -> pick 3-5 medias in the gallery picker -> Done -> wait for the engine to start
adding them (MsgAddVideo/MsgAddImage) -> storm screen recreations for 15 s -> catch the crash -> verdict.
  --trigger rotate   rotation (what the team did by hand on the dev build)
  --trigger uimode   dark mode on/off: a recreation that still happens with rotation locked (production hypothesis)

  python3 tools/stress/repro_slideshow_recreate.py --trigger rotate --tries 5
Logs, UI dumps and screenshots: stress_results/repro_slideshow_<time>/try_N/
"""
import argparse, glob, json, os, queue, random, re, subprocess, sys, threading, time
from datetime import datetime

PKG = os.environ.get('ZESTY_PKG', 'com.myzesty')
ADB = os.environ.get('ADB', 'adb')
LOAD = re.compile(r'MsgAdd(Video|Image)\b')
STALE = re.compile(r'media_id bigger than visual objects|media_id is out of range')
CRASH = re.compile(r'Fatal signal|>>> ' + re.escape(PKG) + r' <<<|FATAL EXCEPTION|ANR in ' + re.escape(PKG))
TARGETS = {   # --target -> text that must be in the lab crash for REPRODUCED
    'native': 'get_media_starting_time',                 # Crashlytics 2bc43cd6 / Play 8de37610 (SIGSEGV)
    'music': 'MusicTracksRepository',                    # Java: Flow exception transparency violated in downloadMusicTrack
}
TARGET = TARGETS['native']
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
MEDIA_DIR = '/sdcard/DCIM/NightShift'
PERMS = ['READ_MEDIA_IMAGES', 'READ_MEDIA_VIDEO', 'READ_MEDIA_VISUAL_USER_SELECTED', 'READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE']
ALLOW = ('permission_allow_button', 'permission_allow_all_button', 'permission_allow_foreground_only_button')
ALLOW_TEXT = re.compile(r'^(Allow( all)?|Allow access to all.*|While using the app|Continue|Grant|OK)$', re.I)


class Stuck(Exception):
    pass


def adb(*a, timeout=30):
    return subprocess.run([ADB, *a], capture_output=True, text=True, timeout=timeout).stdout


def sh(cmd, timeout=30):
    return adb('shell', cmd, timeout=timeout)


# ---------------------------------------------------------------- UI (uiautomator, by resource id / text)

def nodes():
    xml = sh('uiautomator dump /sdcard/ns_dump.xml >/dev/null 2>&1; cat /sdcard/ns_dump.xml', timeout=40)
    out = []
    for n in re.findall(r'<node [^>]*>', xml):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', n))
        b = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', a.get('bounds', ''))
        if b:
            x1, y1, x2, y2 = map(int, b.groups())
            a['xy'] = ((x1 + x2) // 2, (y1 + y2) // 2)
            a['area'] = (x2 - x1) * (y2 - y1)
            a['rid'] = a.get('resource-id', '').split('/')[-1]
            out.append(a)
    return out, xml


def tap(n):
    sh(f'input tap {n["xy"][0]} {n["xy"][1]}')


def find(ns, rid=None, text=None):
    return [n for n in ns if n.get('area', 0) > 0 and ((rid and n['rid'] == rid) or (text and re.search(text, n.get('text', ''), re.I)))]


def handle_permission(ns):
    """System or in-app permission prompt on screen? Allow it. Returns True if something was tapped."""
    for n in ns:
        if n['rid'] in ALLOW or (n.get('clickable') == 'true' and ALLOW_TEXT.match(n.get('text', '').strip())):
            tap(n)
            return True
    return False


def wait_for(pred, what, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        ns, xml = nodes()
        if handle_permission(ns):
            time.sleep(1)
            continue
        hit = pred(ns)
        if hit:
            return hit, ns
        time.sleep(0.8)
    raise Stuck(what)


# ---------------------------------------------------------------- setup

def ensure_media():
    """Fresh, SHORT test media at the top of the gallery (newest first): 3 screenshots made on the phone itself
    (images need no transcoding) and 3 copies of the repo's ~30 s clip. Long clips make transcoding take minutes."""
    sh(f'mkdir -p {MEDIA_DIR}; rm -f {MEDIA_DIR}/ns_clip_*.mov 2>/dev/null')
    clip = os.path.join(REPO, 'repro_assets', 'silent_noaudio.mp4')
    files = []
    for i in range(3):
        f = f'{MEDIA_DIR}/ns_img_{i + 1}.png'
        sh(f'screencap -p {f}'); files.append(f)
    for i in range(3):
        f = f'{MEDIA_DIR}/ns_clip_{i + 1}.mp4'
        if os.path.exists(clip) and not sh(f'ls {f} 2>/dev/null').strip():
            adb('push', clip, f, timeout=120)
        files.append(f)
    for f in files:
        sh(f'touch {f}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{f} >/dev/null 2>&1')
    time.sleep(2)
    return len(files)


def short_tiles(ns, max_s=45):
    """Picker tiles whose clip is <= max_s seconds (or images: no duration label), in grid order."""
    covers = find(ns, 'select_cover')
    labels = [(n, n.get('text', '')) for n in find(ns, 'durationLabel')]
    out = []
    for c in covers:
        x1, y1 = c['xy'][0] - 170, c['xy'][1] - 170
        lab = next((t for n, t in labels if abs(n['xy'][1] - (c['xy'][1] + 120)) < 120 and abs(n['xy'][0] - c['xy'][0]) < 175), None)
        if lab is None:
            out.append(c)
        else:
            m = re.match(r'(\d+):(\d+)', lab)
            if m and int(m[1]) * 60 + int(m[2]) <= max_s:
                out.append(c)
    return out


def clear_music_cache():
    """The template's music is downloaded once, then cached in cache/music-tracks; delete it so every try downloads
    again (the music crash needs the download running while the screen is rebuilt)."""
    out = sh(f'run-as {PKG} sh -c "rm -rf cache/music-tracks; ls cache"')
    if 'not debuggable' in out or 'Unknown package' in out:
        sh('pm trim-caches 999G')                         # release builds: clear every app cache instead


def grant():
    for p in PERMS:
        sh(f'pm grant {PKG} android.permission.{p} 2>/dev/null')


class Logcat:
    def __init__(self, path):
        adb('logcat', '-c')
        self.f = open(path, 'w')
        self.p = subprocess.Popen([ADB, 'logcat', '-v', 'time', '-b', 'main,system,crash'], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, errors='replace')
        self.q, self.lines = queue.Queue(), []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for l in self.p.stdout:
            self.f.write(l); self.lines.append(l); self.q.put(l)

    def wait(self, rx, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                l = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            if rx.search(l):
                return l
        return None

    def stop(self):
        time.sleep(1.5)
        self.p.terminate(); self.f.close()


def crash_summary(lines):
    """One line saying what crashed: native frame #00, or Java exception + first app frame."""
    for i, l in enumerate(lines):
        if re.search(r'#00 pc ', l):
            return 'native: ' + l.split('#00 pc ', 1)[1].strip()[:220]
    for i, l in enumerate(lines):
        if 'Recorded exception' in l or 'FATAL EXCEPTION' in l:
            exc = next((x for x in lines[i + 1:i + 8] if re.search(r'(Exception|Error)\b', x) and 'Message error' not in x), '')
            frame = next((x for x in lines[i + 1:i + 60] if 'at com.myzesty' in x and 'CrashCatcher' not in x), '')
            exc = exc.split('): ', 1)[-1].strip()
            return 'java: ' + exc[:160] + (' @ ' + frame.strip().split('at ', 1)[-1][:120] if frame else '')
    return ''


def recreate(trigger, state):
    if trigger == 'rotate':
        sh(f'settings put system user_rotation {1 if state else 0}')
    else:
        sh(f'cmd uimode night {"yes" if state else "no"}')


# ---------------------------------------------------------------- one try

def screen_size():
    m = re.search(r'(\d+)x(\d+)', sh('wm size').splitlines()[-1] if sh('wm size').strip() else '')
    return (int(m[1]), int(m[2])) if m else (1080, 2400)


def picker_open(ns):
    return bool(find(ns, 'select_cover'))


def tap_done():
    """DONE sits at the bottom right of the picker. The app draws behind the navigation bar, so on some phones the
    accessibility dump reports DONE with empty bounds although it is on screen. Use the dump when it has real bounds,
    otherwise tap the DONE position (right edge, bottom band) and confirm the picker closed."""
    time.sleep(1.0)                                  # bottom bar slides in after the first pick
    ns, _ = nodes()
    hit = find(ns, 'done') or find(ns, 'done_label') or find(ns, None, r'^(done|import)$')
    if hit:
        tap(hit[0]); time.sleep(2.5)
        if not picker_open(nodes()[0]):
            return
    w, h = screen_size()
    for fy in (0.957, 0.945, 0.968, 0.93):          # measured on the SM-A515F: DONE centre at 86% x, 95.7% y
        sh(f'input tap {int(w * 0.86)} {int(h * fy)}')
        time.sleep(2.5)
        if not picker_open(nodes()[0]):
            return
    raise Stuck('Done button in the picker (tapped the dump position and the bottom-right band, picker still open)')


def drive_to_loading(r, log, d, offline=False):
    sh(f'am force-stop {PKG}')
    sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1')
    btn, _ = wait_for(lambda ns: find(ns, 'btnSlideShow', r'^slide ?show$'), 'SlideShow button on the home screen', 30)
    tap(btn[0]); print('  tapped SlideShow')
    covers, ns = wait_for(lambda ns: find(ns, 'select_cover'), 'gallery picker with media', 30)
    covers = short_tiles(ns) or covers
    n = min(len(covers), r.randint(3, 5))
    for c in covers[:n]:
        tap(c); time.sleep(0.5)
    print(f'  picked {n} medias')
    tap_done()
    if offline:
        sh('svc wifi disable; svc data disable')
        print('  wifi + data off (no music download)')
    print('  tapped Done: transcoding, then the template loads')
    hit = log.wait(LOAD, 150)
    if not hit:
        raise Stuck('template never started loading (no MsgAddVideo/MsgAddImage within 150 s)')
    return LOAD.search(hit).group(0)


def one_try(n, args, out, r):
    d = os.path.join(out, f'try_{n}')
    os.makedirs(d, exist_ok=True)
    log = Logcat(os.path.join(d, 'logcat.txt'))
    res = {'try': n, 'trigger': args.trigger}
    acc = sh('settings get system accelerometer_rotation').strip() or '1'
    night = sh('cmd uimode night').strip()
    if args.target == 'music':
        clear_music_cache()
    try:
        first = drive_to_loading(r, log, d, args.offline)
        print(f'  engine started adding medias ({first}): storming {args.trigger} for {args.storm:.0f} s')
        if args.trigger == 'rotate':
            sh('settings put system accelerometer_rotation 0')
        t0, flips, crash, state = time.time(), 0, None, True
        while time.time() - t0 < args.storm:
            recreate(args.trigger, state); state = not state; flips += 1
            crash = log.wait(CRASH, r.uniform(0.3, 0.9))
            if crash:
                break
        crash = crash or log.wait(CRASH, 6)
        res.update({'recreations': flips, 'seconds': round(time.time() - t0, 1)})
    except Stuck as e:
        crash = None
        res['verdict'], res['stuck_at'] = 'UI STUCK', str(e)
        open(os.path.join(d, 'ui_dump.xml'), 'w').write(nodes()[1])
        subprocess.run(f'{ADB} exec-out screencap -p > "{os.path.join(d, "stuck.png")}"', shell=True)
    finally:
        if args.offline:
            sh('svc wifi enable; svc data enable')
        recreate(args.trigger, False)
        sh(f'settings put system accelerometer_rotation {acc}')
        if args.trigger == 'uimode':
            sh('cmd uimode night ' + ('yes' if 'yes' in night else 'no'))
        log.stop()
    text = ''.join(log.lines)
    res['stale_media_id_errors'] = len(STALE.findall(text))
    res['backtrace'] = [l.rstrip() for l in log.lines if re.search(r'#\d\d pc |signal \d+ |Cause:|Abort message', l)][:20]
    if 'verdict' not in res:
        res['target'] = TARGET
        res['verdict'] = 'REPRODUCED' if crash and TARGET in text else ('OTHER CRASH' if crash else 'NO CRASH')
        res['crash_line'] = (crash or '').strip()[:300]
        res['crash'] = crash_summary(log.lines) if crash else ''
    json.dump(res, open(os.path.join(d, 'result.json'), 'w'), indent=1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trigger', choices=['rotate', 'uimode'], default='rotate')
    ap.add_argument('--tries', type=int, default=5)
    ap.add_argument('--storm', type=float, default=15)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--target', choices=sorted(TARGETS), default='native',
                    help='native = SIGSEGV in get_media_starting_time; music = Java crash in MusicTracksRepository')
    ap.add_argument('--offline', action='store_true', help='wifi + data off after Done, so the template music download '
                    'cannot crash first (MusicTracksRepository); restored after each try')
    ap.add_argument('--keep-going', action='store_true', help='do every try even after it reproduces (to measure the rate)')
    args = ap.parse_args()
    global TARGET
    TARGET = TARGETS[args.target]
    if args.target == 'music' and args.offline:
        sys.exit('--target music needs the network: the crash happens while the template music downloads')
    seed = args.seed if args.seed is not None else random.randint(1, 999999)
    r = random.Random(seed)
    devs = [l.split()[0] for l in adb('devices').splitlines()[1:] if l.strip().endswith('device')]
    if not devs:
        sys.exit('no phone: plug it in with USB debugging on, accept the prompt, then check `adb devices`')
    ver = re.search(r'versionName=(\S+)', sh(f'dumpsys package {PKG}'))
    if not ver:
        sys.exit(f'{PKG} is not installed: build and install the debug app first')
    print(f'phone {sh("getprop ro.product.model").strip()}  Android {sh("getprop ro.build.version.release").strip()}  '
          f'{PKG} {ver.group(1)}  seed {seed}')
    grant()
    print(f'test media in the gallery: {ensure_media()} clips in {MEDIA_DIR}')
    out = os.path.join(REPO, 'stress_results', 'repro_slideshow_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)
    results = []
    for n in range(1, args.tries + 1):
        print(f'\ntry {n}/{args.tries} ({args.trigger}, target {args.target})')
        res = one_try(n, args, out, r)
        results.append(res)
        print(f'  => {res["verdict"]}' + (f' at: {res["stuck_at"]}' if res.get('stuck_at') else '') +
              f'  recreations={res.get("recreations", 0)}  stale media-id errors={res["stale_media_id_errors"]}')
        if res.get('crash'):
            print('     crash: ' + res['crash'])
        for l in [b for b in res['backtrace'] if '#0' in b][:6]:
            print('     ' + l[-170:])
        if res['verdict'] == 'REPRODUCED' and not args.keep_going:
            break
        if res['verdict'] == 'UI STUCK' and n >= 2 and all(x['verdict'] == 'UI STUCK' for x in results):
            print('  stuck twice in a row: stopping (see ui_dump.xml / stuck.png)')
            break
    rep = sum(1 for x in results if x['verdict'] == 'REPRODUCED')
    json.dump({'seed': seed, 'trigger': args.trigger, 'reproduced': rep, 'tries': len(results), 'results': results},
              open(os.path.join(out, 'summary.json'), 'w'), indent=1)
    print(f'\nlogs: {out}')
    print('VERDICT:', f'REPRODUCED ({rep}/{len(results)} tries, seed {seed})' if rep else
          ('precursor only (stale media-id errors, no crash)' if any(x['stale_media_id_errors'] for x in results) else 'not reproduced'))
    sys.exit(0 if rep else 1)


if __name__ == '__main__':
    main()
