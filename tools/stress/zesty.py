#!/usr/bin/env python3
"""
zesty.py — device + editor driver for the MyZesty stress scenarios.

Finds controls by the app's own AutomationTags (contentDescription, e.g. "ve_tab_split_clip")
and resource-ids (e.g. "videoTrackView", "export"), so no per-device coordinate calibration.
A logcat monitor thread runs during every scenario and turns ANRs / crashes into AppFailure.

Selectors:  "desc:ve_tab_edit"   contentDescription equals
            "id:play"            resource-id ends with ":id/play"
            "text:My Projects"   text equals (case-insensitive)
            "textc:responding"   text contains (case-insensitive)
            a list/tuple of selectors = first one that matches
"""
import os, re, random, shlex, subprocess, threading, time
import xml.etree.ElementTree as ET

PKG = os.environ.get('ZESTY_PKG', 'com.myzesty')
VERBOSE = bool(os.environ.get('ZESTY_VERBOSE'))


# ───────────────────────────── errors ─────────────────────────────

class AppFailure(Exception):
    """The app ANR'd / crashed / died. This is what the suite is hunting for."""
    def __init__(self, kind, line):
        super().__init__(f'{kind}: {line.strip()[:300]}')
        self.kind, self.line = kind, line


class UIError(Exception):
    """The automation could not do a step (element missing, screen unexpected). Not an app bug."""


# ───────────────────────────── adb ─────────────────────────────

class Device:
    def __init__(self, serial=None):
        self.base = ['adb'] + (['-s', serial] if serial else [])
        self.w, self.h = self._size()

    def adb(self, *args, timeout=60):
        try:
            r = subprocess.run(self.base + list(args), capture_output=True, text=True,
                               timeout=timeout, errors='replace')
            return r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return ''

    def sh(self, cmd, timeout=60):
        return self.adb('shell', cmd, timeout=timeout)

    def _size(self):
        out = self.sh('wm size')
        m = re.findall(r'(\d+)x(\d+)', out)
        return (int(m[-1][0]), int(m[-1][1])) if m else (1080, 2340)

    def tap(self, x, y):
        self.sh(f'input tap {int(x)} {int(y)}')

    def swipe(self, x1, y1, x2, y2, ms):
        self.sh(f'input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}')

    def drag_no_fling(self, x1, y, x2, steps=6, hold=0.35):
        """Finger down, move, hold still, lift: scrolls exactly dx with no fling (Android 11+)."""
        moves = '; '.join(f'input motionevent MOVE {int(x1 + (x2 - x1) * i / steps)} {int(y)}'
                          for i in range(1, steps + 1))
        out = self.sh(f'input motionevent DOWN {int(x1)} {int(y)}; {moves}; sleep {hold}; '
                      f'input motionevent UP {int(x2)} {int(y)}')
        if 'Unknown' in out or 'Error' in out or 'usage' in out.lower():
            self.swipe(x1, y, x2, y, 2500)          # old Android: slow swipe, little fling

    def key(self, code):
        self.sh(f'input keyevent {code}')

    def text(self, s):
        self.sh('input text ' + shlex.quote(s.replace(' ', '%s')))

    def pid(self):
        return self.sh(f'pidof {PKG}').strip().split(' ')[0]

    def marker(self, msg):
        """Logcat marker so ANRSan / engine logs line up with scenario steps: logcat -s ZSTRESS ANRSAN"""
        self.sh('log -t ZSTRESS ' + shlex.quote(msg[:400]))

    def screenshot(self, path):
        try:
            data = subprocess.run(self.base + ['exec-out', 'screencap', '-p'],
                                  capture_output=True, timeout=30).stdout
            if data:
                open(path, 'wb').write(data)
        except Exception:
            pass

    def pixels(self, points):
        """RGB at screen points from one raw screencap (works even when uiautomator can't dump)."""
        try:
            raw = subprocess.run(self.base + ['exec-out', 'screencap'], capture_output=True, timeout=30).stdout
        except Exception:
            return [None] * len(points)
        if len(raw) < 16:
            return [None] * len(points)
        w = int.from_bytes(raw[0:4], 'little')
        h = int.from_bytes(raw[4:8], 'little')
        header = len(raw) - w * h * 4            # 12 bytes (old) or 16 bytes (Android 10+)
        if w <= 0 or h <= 0 or header not in (12, 16):
            return [None] * len(points)
        out = []
        for x, y in points:
            x, y = max(0, min(w - 1, int(x))), max(0, min(h - 1, int(y)))
            o = header + (y * w + x) * 4
            out.append(tuple(raw[o:o + 3]))
        return out

    LAUNCHER = None                                   # 'com.myzesty/...Activity', resolved once per process

    def launch(self):
        """Open the app like the launcher icon. `am start` of the resolved launcher activity (~0.3 s); `monkey` took
        33 s per launch on the realme (it boots a Java VM and waits), so monkey is only the fallback."""
        if Device.LAUNCHER is None:
            out = self.sh(f'cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER {PKG}')
            comp = [l.strip() for l in out.splitlines() if l.strip().startswith(PKG + '/')]
            Device.LAUNCHER = comp[-1] if comp else ''
        if Device.LAUNCHER:
            out = self.sh(f'am start -n {Device.LAUNCHER} -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -f 0x10200000')
            if 'Error' not in out and 'Exception' not in out:
                return
            Device.LAUNCHER = ''
        self.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1')

    def slow_phone(self, level=0):
        """Busy CPU loops (0 = off): this lab phone becomes as slow as the low-end field phones (level 20-45 makes a cold
        start take 10-25 s on the realme). Tagged '# nsload' so restore_env() always clears them."""
        self.sh('pkill -f "# nsload" 2>/dev/null')
        for _ in range(max(0, min(int(level), 48))):
            self.sh('nohup sh -c "while :; do :; done # nsload" >/dev/null 2>&1 &')

    def busy_storage(self, on=True):
        """Another app writing a big file non-stop (slow storage for every thread). Tagged '# nsio'; restore_env clears it."""
        self.sh('pkill -f "# nsio" 2>/dev/null; rm -f /sdcard/Download/ns_io_*.tmp')
        if on:
            for k in range(2):
                self.sh(f'nohup sh -c "while :; do dd if=/dev/zero of=/sdcard/Download/ns_io_{k}.tmp bs=1048576 count=400 '
                        f'conv=fsync 2>/dev/null; rm -f /sdcard/Download/ns_io_{k}.tmp; done # nsio" >/dev/null 2>&1 &')

    STALL = None

    def stalled_server(self, on=True, port=8443):
        """A server that accepts connections and never answers (a stalled CDN / captive network), reachable from the
        phone at https://127.0.0.1:<port>/ through adb reverse even when the phone has no network. Returns the URL."""
        import socket
        if not on:
            self.adb('reverse', '--remove', f'tcp:{port}')
            return ''
        if Device.STALL is None:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind(('127.0.0.1', port))
            except OSError:
                pass                                   # another lab process already serves it
            else:
                srv.listen(64)
                held = []

                def hold():
                    while True:
                        try:
                            c, _ = srv.accept()
                            held.append(c)             # keep it open, send nothing: the client waits for its timeout
                        except OSError:
                            return
                threading.Thread(target=hold, daemon=True).start()
                Device.STALL = srv
        self.adb('reverse', f'tcp:{port}', f'tcp:{port}')
        return f'https://127.0.0.1:{port}/img/{int(time.time())}.jpg'

    def kill_bg(self):
        """Home, then the system reclaims the cached app process (what low memory does); a later push/job = cold start."""
        self.key('KEYCODE_HOME')
        time.sleep(1)
        self.sh(f'am kill {PKG}')
        time.sleep(1)

    def fcm_push(self, title='', body='', data=None, foreground=False, wait=False):
        """A push message arrives: the same broadcast Google Play services delivers, into the app's REAL Firebase
        receiver (debug builds let adb send it; app/src/debug/AndroidManifest.xml). title/body = a notification
        message; data = a data message. Returns the broadcast result line."""
        import uuid
        ex = f'--es google.message_id 0:{uuid.uuid4().hex[:16]} --es from 0 --el google.sent_time {int(time.time() * 1000)} '
        if title or body:
            ex += f'--es gcm.n.e 1 --es gcm.n.title {shlex.quote(title or " ")} --es gcm.n.body {shlex.quote(body or " ")} '
        for k, v in (data or {}).items():
            ex += f'--es {shlex.quote(str(k))} {shlex.quote(str(v))} '
        cmd = (f'am broadcast {"--receiver-foreground " if foreground else ""}-a com.google.android.c2dm.intent.RECEIVE '
               f'-n {PKG}/com.google.firebase.iid.FirebaseInstanceIdReceiver {ex}')
        if wait:                                     # am blocks until the receiver finishes (an ANR = it never does)
            out = self.sh(cmd, timeout=90)
            return (out.strip().splitlines() or ['no answer from the receiver in 90 s'])[-1][:160]
        self.sh(f'rm -f /data/local/tmp/ns_push.txt; nohup sh -c {shlex.quote(cmd)} >/data/local/tmp/ns_push.txt 2>&1 &')
        time.sleep(1.0)                              # like a real push: do not wait for the receiver, only for a refusal
        out = self.sh('cat /data/local/tmp/ns_push.txt 2>/dev/null; logcat -d -t 80 -s ActivityManager:W BroadcastQueue:W | grep -m1 "Permission Denial.*c2dm"')
        if any(k in out for k in ('Security', 'ermission', 'Error', 'Exception')):
            return 'push REFUSED by the system (this build does not accept lab pushes): ' + out.strip()[-120:]
        return 'push sent' + (f' ({out.strip().splitlines()[-1][:80]})' if 'completed' in out else ' (receiver still running)')

    def force_stop(self):
        """Stop the app and make sure it is really gone (a hung ANR process can survive one force-stop)."""
        self.clear_system_dialogs()
        for _ in range(4):
            self.sh(f'am force-stop {PKG}')
            if not self.pid():
                return
            time.sleep(0.5)
        p = self.pid()
        if p:                                      # still alive: kill it (debug build: run-as works)
            self.sh(f'run-as {PKG} kill -9 {p} 2>/dev/null; kill -9 {p} 2>/dev/null')

    def clear_system_dialogs(self):
        """Close any system 'isn't responding' / 'keeps stopping' dialog left from an earlier run (ours or another app's),
        so the next run never starts behind it. Returns how many were closed."""
        n = 0
        for _ in range(4):
            foc = self.sh('dumpsys window | grep -m1 mCurrentFocus', timeout=10)
            if not re.search(r'Application Not Responding|Application Error', foc):
                break
            self.sh('am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS >/dev/null 2>&1')
            time.sleep(0.4)
            foc2 = self.sh('dumpsys window | grep -m1 mCurrentFocus', timeout=10)
            if re.search(r'Application Not Responding|Application Error', foc2):
                self.sh('input keyevent KEYCODE_BACK')    # BACK closes the dialog ("Close app" on most builds)
                time.sleep(0.6)
            n += 1
        return n

    def getprop(self, key):
        return self.sh(f'getprop {key}').strip()

    def setprop(self, key, value):
        self.sh(f'setprop {key} {shlex.quote(value) if value else chr(34) * 2}')

    # ── device environment (Night Shift level 3). The runner calls restore_env() before every run. ──
    def clear_app_cache(self, sub=''):
        """Delete the app's cache (or one sub-folder, e.g. 'music-tracks'): cached content loads instantly and hides load-time races."""
        out = self.sh(f'run-as {PKG} sh -c "rm -rf cache/{sub or "*"}; ls cache"')
        if 'not debuggable' in out or 'unknown package' in out:
            self.sh('pm trim-caches 999G')           # release build: trim every app's cache instead
        return out

    def fresh_video(self, tag='', duration_s=0):
        """Copy a video on the phone to a NEW name (newest in the gallery): the app caches transcodes per source path, so a new path forces a REAL transcode. duration_s=N picks the clip whose length is closest to N seconds (longer clip = longer transcode); 0 = the biggest file."""
        rows = self.sh('content query --uri content://media/external/video/media --projection _data:duration:_size 2>/dev/null')
        clips = []
        for m in re.finditer(r'_data=(\S+?), duration=(\d+|NULL), _size=(\d+)', rows):
            if 'ns_fresh_' in m.group(1) or not re.search(r'\.(mp4|mov|3gp|mkv)$', m.group(1), re.I):
                continue
            clips.append((m.group(1), int(m.group(2)) / 1000 if m.group(2).isdigit() else 0, int(m.group(3))))
        if duration_s and clips:
            src = min(clips, key=lambda c: (abs(c[1] - duration_s), -c[2]))[0]
        elif clips:
            src = max(clips, key=lambda c: c[2])[0]
        else:
            src = self.sh('ls -S /sdcard/DCIM/*/*.mp4 /sdcard/DCIM/*.mp4 /sdcard/Movies/*.mp4 /sdcard/Download/*.mp4 '
                          '2>/dev/null | grep -v ns_fresh_ | head -1').strip()
        if not src:
            raise RuntimeError('no video on the phone to copy (push one to /sdcard/DCIM first)')
        dst = f'/sdcard/DCIM/NightShift/ns_fresh_{int(time.time())}{("_" + tag) if tag else ""}.mp4'
        self.sh(f'mkdir -p /sdcard/DCIM/NightShift; cp {shlex.quote(src)} {dst}; touch {dst}; '
                f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
        time.sleep(2)
        dur = next((c[1] for c in clips if c[0] == src), 0)
        self.log(f'    fresh_video: {src} ({dur:.0f} s) -> {dst}') if hasattr(self, 'log') else None
        return dst

    def video_lengths(self):
        """(path, seconds) of every video on the phone, longest first: pick fresh_video(duration_s=...) from these."""
        rows = self.sh('content query --uri content://media/external/video/media --projection _data:duration 2>/dev/null')
        out = [(m.group(1), int(m.group(2)) / 1000) for m in re.finditer(r'_data=(\S+?), duration=(\d+)', rows) if 'ns_fresh_' not in m.group(1)]
        return sorted(out, key=lambda x: -x[1])

    def clear_app_files(self, sub='outputs'):
        """Hide one folder under the app's files/ (default 'outputs' = old transcodes) for this run: cached work is redone for real. Reversible: restore_env puts the files back before the next run, so drafts keep their clips."""
        return self.sh(f"run-as {PKG} sh -c 'mkdir -p files/.ns_bak/{sub}; mv files/{sub}/* files/.ns_bak/{sub}/ 2>/dev/null; ls files/{sub} 2>/dev/null | wc -l'")

    def network(self, on=True):
        """Wifi + mobile data on/off (off keeps downloads and template loads pending)."""
        self.sh('svc wifi enable; svc data enable' if on else 'svc wifi disable; svc data disable')

    def slow_network(self, kbps=0):
        """Throttle wifi to roughly kbps (0 = no limit); makes downloads and loads take seconds instead of ms."""
        self.sh(f'cmd netpolicy set restrict-background {"true" if kbps else "false"}')
        if kbps:
            self.sh(f'tc qdisc replace dev wlan0 root tbf rate {kbps}kbit burst 16kbit latency 400ms 2>/dev/null')
        else:
            self.sh('tc qdisc del dev wlan0 root 2>/dev/null')

    def dark_mode(self, on=True):
        """System dark mode on/off: recreates visible activities (NOTE: the slideshow, QuickCutActivity, closes and returns to the start screen on it)."""
        self.sh(f'cmd uimode night {"yes" if on else "no"}')

    def rotate(self, landscape=True):
        """Lock the screen to landscape/portrait: a configuration change that recreates the activity."""
        self.sh('settings put system accelerometer_rotation 0')
        self.sh(f'settings put system user_rotation {1 if landscape else 0}')

    def font_scale(self, scale=1.0):
        """System font size (1.0 = normal): another configuration change."""
        self.sh(f'settings put system font_scale {scale}')

    def restore_env(self):
        """Back to normal: network on, no throttle, light mode, portrait, normal font."""
        self.sh('svc wifi enable; svc data enable; cmd netpolicy set restrict-background false; tc qdisc del dev wlan0 root 2>/dev/null; '
                'cmd uimode night no; settings put system user_rotation 0; settings put system font_scale 1.0; '
                'settings put global always_finish_activities 0; dumpsys deviceidle unforce >/dev/null 2>&1; '
                'pkill -f "# nsload" 2>/dev/null; pkill -f "# nsio" 2>/dev/null; rm -f /sdcard/Download/ns_io_*.tmp; '        # slow_phone loops a crashed live run could not stop   # a recipe that left "Don't keep activities" on poisons later runs
                'rm -f /sdcard/DCIM/NightShift/ns_fresh_* 2>/dev/null; '   # copies made by fresh_video in earlier runs
                "content delete --uri content://media/external/video/media --where \"_data LIKE '%ns_fresh_%'\" 2>/dev/null")
        # files hidden by clear_app_files go back, so the test draft keeps its clips
        self.sh(f"run-as {PKG} sh -c 'if [ -d files/.ns_bak ]; then for d in files/.ns_bak/*; do n=$(basename $d); "
                f"mkdir -p files/$n; mv $d/* files/$n/ 2>/dev/null; done; rm -rf files/.ns_bak; fi'")

    def anrsan_loaded(self):
        """True/False = libanrsan.so is/isn't mapped in the running app; None = can't tell."""
        pid = self.pid()
        if not pid:
            return None
        out = self.sh(f'run-as {PKG} cat /proc/{pid}/maps')
        if 'libanrsan' in out:
            return True
        return False if '-xp ' in out or 'r-xp' in out else None


# ───────────────────────────── UI hierarchy ─────────────────────────────

_BOUNDS = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')


class Node:
    __slots__ = ('rid', 'desc', 'text', 'cls', 'pkg', 'clickable', 'enabled', 'b', 'children')

    def __init__(self, e):
        a = e.attrib
        self.rid, self.desc, self.text = a.get('resource-id', ''), a.get('content-desc', ''), a.get('text', '')
        self.cls, self.pkg = a.get('class', ''), a.get('package', '')
        self.clickable = a.get('clickable') == 'true'
        self.enabled = a.get('enabled', 'true') == 'true'
        m = _BOUNDS.match(a.get('bounds', ''))
        self.b = tuple(map(int, m.groups())) if m else (0, 0, 0, 0)
        self.children = []

    @property
    def center(self):
        return ((self.b[0] + self.b[2]) // 2, (self.b[1] + self.b[3]) // 2)

    @property
    def visible(self):
        return self.b[2] - self.b[0] > 2 and self.b[3] - self.b[1] > 2

    def __repr__(self):
        return f'<{self.rid.split("/")[-1] or self.cls.split(".")[-1]} desc={self.desc!r} text={self.text!r} {self.b}>'


def _flatten(sel):
    if isinstance(sel, str):
        yield sel
    else:
        for s in sel:
            yield from _flatten(s)


def _matches(n, sel):
    kind, _, val = sel.partition(':')
    if kind == 'desc':
        return n.desc == val
    if kind == 'id':
        return n.rid.endswith(':id/' + val)
    if kind == 'text':
        return n.text.strip().lower() == val.lower()
    if kind == 'textc':
        return val.lower() in n.text.lower() or val.lower() in n.desc.lower()
    raise ValueError(f'bad selector {sel!r}')


class Screen:
    def __init__(self, xml):
        root = ET.fromstring(xml)
        self.nodes = []

        def walk(e, parent):
            for c in e:
                if c.tag != 'node':             # <window>/<display> wrappers from --windows
                    walk(c, parent)
                    continue
                n = Node(c)
                self.nodes.append(n)
                if parent is not None:
                    parent.children.append(n)
                walk(c, n)
        walk(root, None)

    def find_all(self, sel):
        sels = list(_flatten(sel))
        return [n for s in sels for n in self.nodes if n.visible and _matches(n, s)]

    def find(self, sel):
        r = self.find_all(sel)
        return r[0] if r else None

    def has(self, sel):
        return self.find(sel) is not None

    def items(self, sel):
        """Visible direct children of a list (RecyclerView) — the tappable tiles."""
        n = self.find(sel)
        return [c for c in n.children if c.visible] if n else []

    def summary(self):
        out = []
        for n in self.nodes:
            if not n.visible:
                continue
            bits = [b for b in (n.rid.split('/')[-1] if '/' in n.rid else '',
                                f'desc={n.desc}' if n.desc else '',
                                f'text={n.text[:40]!r}' if n.text else '') if b]
            if bits:
                out.append(f'{n.b}  ' + '  '.join(bits))
        return '\n'.join(out)


def _adb_transport_error(out):
    o = out[:300].lower()
    return any(k in o for k in ('no devices', 'device offline', "device '", 'device not found',
                                'unauthorized', 'cannot connect', 'closed', 'protocol fault'))


SCREEN_MAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'screen_map.json')


class UI:
    def __init__(self, dev):
        self.dev = dev
        self.cache = {}            # selector -> center, for taps while the UI is too busy to dump
        self.last = None

    # waits give up early when the screen is frozen on something else (no loader, nothing changing) for this many
    # seconds; None = wait the full timeout. The runner sets it (--ui-stall) for Night Shift's own scripts.
    stall = None
    # screen map: every id seen on the lab phone, per activity, saved after each run (see save_screen_map)
    seen = {}
    activity, _act_t = '?', 0.0

    def _activity(self):
        if time.time() - UI._act_t > 2:
            out = self.dev.sh('dumpsys window displays | grep -E "mFocusedApp|mCurrentFocus"', timeout=10)   # no early pipe close: no system log noise
            m = re.search(r'([\w.]+)/([\w.$]+)', out or '')
            UI.activity = (m.group(2).split('.')[-1] if m else '?')
            UI._act_t = time.time()
        return UI.activity

    def _record(self, s):
        try:
            act = UI.seen.setdefault(self._activity(), {})
            for n in s.nodes:
                if n.rid and n.visible and (PKG in n.rid or n.pkg == PKG):
                    rid = n.rid.split(':id/')[-1]
                    if rid not in act or (not act[rid] and (n.text or n.desc)):
                        act[rid] = (n.text or n.desc or '')[:40]
        except Exception:
            pass

    tty_ok = True
    # --windows (Android 13+) dumps every window. The editor's bottom menu lives outside the
    # main window, so without it Edit/Effects/Split... are invisible to plain `uiautomator dump`.
    windows = None                 # None = not probed yet

    def _raw(self, flags, timeout):
        flags = (flags + ' ') if flags else ''
        if UI.tty_ok:
            out = self.dev.adb('exec-out', f'uiautomator dump {flags}/dev/tty', timeout=timeout)
            if _adb_transport_error(out):
                return ''                  # phone unplugged / adb restarting: transient, change nothing
            if out and '<?xml' not in out and 'idle' not in out and 'Usage' not in out:
                UI.tty_ok = False          # device without /dev/tty support -> file + cat from now on
            else:
                return out
        return self.dev.sh(f'uiautomator dump {flags}/sdcard/zstress_dump.xml >/dev/null && '
                           'cat /sdcard/zstress_dump.xml', timeout=timeout)

    STATS = {'n': 0, 'secs': 0.0}                     # screen dumps of this run: count and time (speed measurement)

    def dump(self, timeout=15):
        _t0 = time.time()
        try:
            return self._dump(timeout)
        finally:
            UI.STATS['n'] += 1
            UI.STATS['secs'] += time.time() - _t0

    FAST = None                                       # turbo.fast_ui: read the screen from inside the app (LabControl ui)
    FAST_PATH = '/sdcard/Android/data/com.myzesty/files/ns_ui.xml'
    FAST_STATS = {'fast': 0, 'fallback': 0}

    @staticmethod
    def _fast_on():
        if UI.FAST is None:
            try:
                import json as _j
                p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nightshift', 'out', 'experiment.json')
                # the in-app screen READER only reads the view tree: it stays on in the real-tap (ZESTY_LAB=0) video run,
                # where only the state-changing lab shortcuts are off (Android's own dump misses parts of the editor)
                UI.FAST = bool(((_j.load(open(p)) or {}).get('turbo') or {}).get('fast_ui')) and \
                    (Editor.LAB or os.environ.get('ZESTY_LAB_READ', '1') != '0')
            except Exception:
                UI.FAST = False
        return UI.FAST

    def _fast(self, timeout):
        """The app's own view tree via the debug build's LabControl (~0.3 s instead of 1-5 s). None = fall back."""
        nonce = str(int(time.time() * 1000) % 1000000000)
        out = self.dev.sh(f"pidof {PKG} >/dev/null || {{ echo NOPROC; exit 0; }}; "   # never wake a dead app with a screen read
                          f"am broadcast -a com.myzesty.LAB -p {PKG} --es cmd ui --es nonce {nonce} >/dev/null 2>&1; "
                          f"i=0; while [ $i -lt 15 ]; do grep -q 'nonce=\"{nonce}\"' {UI.FAST_PATH} 2>/dev/null && break; "
                          f"sleep 0.08; i=$((i+1)); done; cat {UI.FAST_PATH} 2>/dev/null", timeout=min(timeout, 10))
        if out.strip().startswith('NOPROC'):
            return None
        if f'nonce="{nonce}"' not in out:
            UI.FAST_MISS = getattr(UI, 'FAST_MISS', 0) + 1
            if UI.FAST_MISS >= 4 and not UI.FAST_STATS['fast']:   # a build without the `ui` command: stop asking
                UI.FAST = False
            return None
        UI.FAST_MISS = 0
        if out.lstrip().startswith('NOFRONT'):
            return None
        return out

    def _dump(self, timeout=15):
        if UI._fast_on():
            out = self._fast(timeout)
            if out:
                UI.FAST_STATS['fast'] += 1
                i, j = out.find('<?xml'), out.rfind('>')
                try:
                    return self._keep(Screen(out[i:j + 1]))
                except ET.ParseError:
                    pass
            UI.FAST_STATS['fallback'] += 1
        if UI.windows is None:
            out = self._raw('--windows', timeout)
            if '<?xml' in out:
                UI.windows = True
            else:
                if out and 'idle' not in out and not _adb_transport_error(out):  # a real "unknown option"
                    UI.windows = False
                out = self._raw('', timeout)
        else:
            out = self._raw('--windows' if UI.windows else '', timeout)
        i = out.find('<?xml')
        j = out.rfind('>', 0, out.find('UI hier') if 'UI hier' in out else len(out))
        if i < 0 or j < i:
            return None
        try:
            s = Screen(out[i:j + 1])
        except ET.ParseError:
            return None
        return self._keep(s)

    def _keep(self, s):
        self.last = s
        self._record(s)
        return s

    def wait(self, sel, timeout=15, gone=False, interval=0.4, on_poll=None):
        end = time.time() + timeout
        sig, since = None, time.time()
        while True:
            s = self.dump()
            if on_poll:
                on_poll()
            if s is not None:
                n = s.find(sel)
                if gone and n is None:
                    return s
                if not gone and n is not None:
                    self.cache[str(sel)] = n.center
                    return s
                now_sig = frozenset((x.rid, x.text, x.desc) for x in s.nodes if x.visible)
                busy = any('progress' in (x.cls + x.rid).lower() or 'load' in x.rid.lower() or '%' in x.text for x in s.nodes)
                if now_sig != sig or busy:
                    sig, since = now_sig, time.time()
                elif UI.stall and timeout > UI.stall and time.time() - since > UI.stall:
                    print(f'      (gave up waiting for {sel}: the screen has not changed for {UI.stall:.0f} s and shows no loader)', flush=True)
                    return None
            if time.time() > end:
                return None
            time.sleep(interval)

    def tap(self, sel, timeout=12, on_poll=None):
        s = self.wait(sel, timeout, on_poll=on_poll)
        if s is None:
            if str(sel) in self.cache:          # UI never went idle (playback) -> last known spot
                self.dev.tap(*self.cache[str(sel)])
                return None
            raise UIError(f'not found: {sel}')
        n = s.find(sel)
        self.dev.tap(*n.center)
        return s

    def tap_cached(self, sel):
        if str(sel) not in self.cache:
            return self.tap(sel)
        self.dev.tap(*self.cache[str(sel)])


# ───────────────────── real view tree (dumpsys activity top) ─────────────────────
# The editor's bottom menu (menu_container 1475..2400) is drawn below the window edge that the
# accessibility layer reports (2177), so uiautomator never lists Edit/Effects/Split/... at all.
# `dumpsys activity top` prints the real View tree with frames, which does include them.

_VLINE = re.compile(r'^(\s*)(\S+?)\{[0-9a-f]+ (\S{9}) (\S{8}) (-?\d+),(-?\d+)-(-?\d+),(-?\d+)'
                    r'(?: #[0-9a-f]+)?(?: ([^}\s]+))?\}')


class VNode:
    __slots__ = ('cls', 'id', 'vis', 'b', 'children', 'parent')

    def __init__(self, cls, vid, vis, b, parent):
        self.cls, self.id, self.vis, self.b, self.parent = cls, vid, vis, b, parent
        self.children = []

    @property
    def center(self):
        return ((self.b[0] + self.b[2]) // 2, (self.b[1] + self.b[3]) // 2)

    def has_visible(self, vid):
        return any((c.id.endswith('/' + vid) and c.vis) or c.has_visible(vid) for c in self.children)

    def __repr__(self):
        return f'<{self.cls.split(".")[-1]} {self.id} vis={self.vis} {self.b}>'


def parse_view_tree(text, pkg=PKG):
    """View tree of the top-most activity of `pkg`; absolute frames; vis = visible incl. ancestors."""
    idx = text.rfind(f'ACTIVITY {pkg}/')
    if idx < 0:
        return []
    sect = text[idx:]
    h = sect.find('View Hierarchy:')
    if h < 0:
        return []
    nodes, stack = [], []
    for ln in sect[h:].split('\n')[1:]:
        m = _VLINE.match(ln)
        if not m:
            if ln.strip() and len(ln) - len(ln.lstrip()) <= 4:
                break                                   # end of the hierarchy block
            continue
        ind = len(m.group(1))
        l, t, r, b = map(int, m.group(5, 6, 7, 8))
        while stack and stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1] if stack else None
        ox, oy = (parent.b[0], parent.b[1]) if parent else (0, 0)
        vis = m.group(3)[0] == 'V' and (parent.vis if parent else True)
        n = VNode(m.group(2), m.group(9) or '', vis, (ox + l, oy + t, ox + r, oy + b), parent)
        if parent:
            parent.children.append(n)
        nodes.append(n)
        stack.append((ind, n))
    return nodes


# Order from ListUtil.kt (getMainNav / getClipEdit for a VIDEO clip). Index = position in the bar.
MAIN_MENU = ['edit', 'effects', 'audio', 'presets', 'dehazer', 'text', 'sticker', 'tune', 'freeze',
             'overlay', 'chroma', 'canvas']
CLIP_MENU = ['split', 'volume', 'delete', 'speed', 'reverse', 'denoise', 'extract', 'mask', 'background',
             'opacity', 'flip_h', 'flip_v', 'rotate', 'fit', 'fill', 'duplicate']


class BottomBar:
    def __init__(self, dev):
        self.dev = dev

    def read(self):
        nodes = parse_view_tree(self.dev.sh('dumpsys activity top', timeout=40))
        bar = next((n for n in nodes if n.id.endswith('/bottom_bar') and n.vis
                    and n.cls.endswith('RecyclerView')), None)
        if bar is None:
            return None, [], False
        back = next((c for c in (bar.parent.children if bar.parent else [])
                     if c.id.endswith('/back')), None)
        return bar, [c for c in bar.children if c.vis], bool(back and back.vis)

    def is_main(self):
        bar, items, back = self.read()
        return bar is not None and not back

    def _fling(self, bar, to_start):
        # The system gesture/navigation area (navigationBarBackground 2265..2400 on the A51) eats
        # swipes, and the bar (2231..2400) mostly lies inside it: swipe on the bar's top strip.
        l, t, r, b = bar.b
        y = t + 12
        for _ in range(3):
            if to_start:
                self.dev.swipe(l + 60, y, r - 60, y, 120)
            else:
                self.dev.swipe(r - 60, y, l + 60, y, 120)
            time.sleep(0.25)
        time.sleep(0.6)

    def tap(self, i, n, expect_submenu=None, validate=None):
        """Tap item i of an n-item bar. expect_submenu: True/False = the back button must be shown/hidden."""
        for attempt in range(3):
            bar, items, back = self.read()
            if bar is None or not items:
                raise UIError('bottom bar not found in view tree')
            if expect_submenu is not None and back != expect_submenu:
                raise UIError(f'bottom bar is the {"sub" if back else "main"} menu, expected '
                              f'{"sub" if expect_submenu else "main"}')
            L, R = bar.b[0], min(bar.b[2], self.dev.w)
            first = 0 if abs(items[0].b[0] - bar.b[0]) <= 2 else (
                n - len(items) if abs(items[-1].b[2] - bar.b[2]) <= 2 else None)
            if first is not None:
                if validate:
                    validate(first, items)
                k = i - first
                if 0 <= k < len(items):
                    cx, cy = items[k].center
                    if L + 20 <= cx <= R - 20:
                        self.dev.tap(cx, cy)
                        return
            self._fling(bar, to_start=i < n / 2 if attempt == 0 else attempt == 2)
        # Flings overshoot or land with neither end flush (index unknown): walk the bar in short slow steps from the
        # start, so the first item stays the reference and item i comes into view one step at a time.
        for k in range(10):
            bar, items, back = self.read()
            if bar is None or not items:
                break
            if k == 0:
                self._fling(bar, to_start=True)
                continue
            L, R = bar.b[0], min(bar.b[2], self.dev.w)
            if abs(items[0].b[0] - bar.b[0]) <= 2:
                first = 0
            elif abs(items[-1].b[2] - bar.b[2]) <= 2:
                first = n - len(items)
            else:
                first = getattr(self, '_walk_first', None)
            if first is not None:
                kk = i - first
                if 0 <= kk < len(items) and L + 20 <= items[kk].center[0] <= R - 20:
                    if validate:
                        validate(first, items)
                    self.dev.tap(*items[kk].center)
                    return
            # one slow step to the left by ~2 items (drag, no fling), then re-read
            w = max(60, items[0].b[2] - items[0].b[0])
            l, t, r, b = bar.b
            y = t + 12
            x0 = min(r - 40, l + 3 * w)
            self.dev.swipe(x0, y, x0 - 2 * w, y, 600)
            time.sleep(0.5)
            self._walk_first = None
        ed = getattr(self, 'editor', None)                # label fallback: MAIN_MENU / CLIP_MENU name of item i
        names = MAIN_MENU if n == len(MAIN_MENU) else CLIP_MENU if n == len(CLIP_MENU) else None
        if ed is not None and names and 0 <= i < len(names):
            try:
                ed.tap_tool(names[i])
                return
            except UIError:
                pass
        raise UIError(f'bottom bar item {i}/{n} not reachable')


# ───────────────────────────── logcat monitor ─────────────────────────────

P = re.escape(PKG)
SIGNATURES = [
    ('ANR',   re.compile(rf'am_anr\s*:.*{P}|ANR in {P}\b')),
    ('CRASH', re.compile(rf'am_crash\s*:.*{P}|Process: {P}, PID|Fatal signal \d+.*\({P}\)|>>> {P} <<<')),
    ('DIED',  re.compile(rf'am_proc_died\s*:.*,{P},')),
]
LMK = re.compile(rf'(lowmemorykiller|am_kill).*{P}', re.I)
PROGRESS = 'MsgGetExportingProgress'
PROGRESS_VAL = re.compile(r'MsgGetExportingProgress progress ([0-9.]+)')   # 0..100
ABORT_RX = re.compile(r'\bMsgAbortExport\b')     # MsgLooper.cpp: LOGI("MsgAbortExport") — one per abort
ANRSAN = re.compile(r'==== ANRSAN #\d+ (\w+)')
# Java frames of the field ANR (set by Night Shift when its lab boost is on): a lab-watchdog block holding all of them
# counts as the ANR (near-ANR: the main thread was blocked >= debug.zesty.wd_ms with the field stack)
WD_EXPECT = [e for e in os.environ.get('ZESTY_WD_EXPECT', '').split('|') if e.strip()]
ANRSAN_SERIOUS = {'MAIN_BLOCKED', 'DEADLOCK', 'POSSIBLE_DEADLOCK', 'LOCK_ORDER_INVERSION', 'SELF_DEADLOCK',
                  'MAIN_LOCK_WAIT', 'CRITICAL_JOIN'}


class Monitor:
    """Tails logcat (main/system/crash/events) into a file; flags ANR/crash lines."""

    def __init__(self, dev):
        self.dev = dev
        self.proc = None
        self._wd = None
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.failure = None
        self.notes = []
        self.anrsan = []
        self.progress_n = 0
        self.progress_t = 0.0
        self.progress_val = None
        self.abort_n = 0              # engine-side abort lines seen (proof the abort path really ran)
        self.allow_death = False      # set by force-stop / long background steps

    def start(self, path):
        self.stop()
        self.reset()
        self.dev.adb('logcat', '-b', 'all', '-c')
        self.fh = open(path, 'w', errors='replace')
        self.proc = subprocess.Popen(self.dev.base + ['logcat', '-v', 'threadtime', '-b', 'main,system,crash,events'],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     errors='replace', bufsize=1)
        self.th = threading.Thread(target=self._pump, daemon=True)
        self.th.start()

    def _pump(self):
        for line in self.proc.stdout:
            self.fh.write(line)
            if PROGRESS in line:
                m = PROGRESS_VAL.search(line)
                with self.lock:
                    self.progress_n += 1
                    self.progress_t = time.time()
                    if m:
                        self.progress_val = float(m.group(1))
                continue
            if ' ZWATCHDOG' in line and WD_EXPECT:      # Night Shift lab watchdog (debug builds, debug.zesty.wd_ms)
                if 'MAIN_BLOCKED' in line:
                    self._wd = [line]
                elif self._wd is not None:
                    self._wd.append(line)
                    if 'MAIN_RESUMED' in line or len(self._wd) > 45:
                        blk = ''.join(self._wd)
                        if all(e in blk for e in WD_EXPECT):
                            with self.lock:
                                if self.failure is None:
                                    self.failure = ('ANR', 'lab watchdog: ' + self._wd[0].strip()[-80:] + ' with the field stack')
                        self._wd = None
            m = ANRSAN.search(line)
            if m:
                self.anrsan.append(m.group(1))
            elif ABORT_RX.search(line) and ' ZSTRESS ' not in line and ' ANRSAN ' not in line:
                self.abort_n += 1
            if LMK.search(line) and not self.allow_death:
                self.notes.append('killed by system: ' + line.strip()[:200])
            for kind, rx in SIGNATURES:
                if rx.search(line):
                    with self.lock:
                        if kind == 'DIED' and self.allow_death:
                            pass                               # deliberate force-stop / restart
                        elif kind == 'DIED' and self.notes:
                            self.notes.append('process died after a system kill: ' + line.strip()[:200])
                        elif self.failure is None:
                            self.failure = (kind, line)
                    break

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except Exception:
                self.proc.kill()
            self.th.join(3)
            self.fh.close()
            self.proc = None

    def check(self):
        with self.lock:
            f = self.failure
        if f:
            raise AppFailure(*f)

    def export_quiet_for(self):
        with self.lock:
            return (time.time() - self.progress_t) if self.progress_t else None


# ───────────────────────────── the editor ─────────────────────────────

class T:
    """AutomationTags (java-common/.../AutomationTags.kt) + resource ids used here."""
    # tag first, visible label as fallback (English UI)
    EDIT = ('desc:ve_tab_edit', 'text:Edit')
    EFFECTS = ('desc:ve_tab_effects', 'text:Effects')
    TEXT = ('desc:ve_btn_add_text_entry', 'text:Text')
    STICKER = ('desc:ve_btn_add_sticker_entry', 'text:Sticker', 'text:Stickers')
    TUNE = ('desc:ve_btn_add_tune', 'text:Tune')
    FREEZE = ('desc:ve_tab_freeze', 'text:Freeze')
    AUDIO = ('desc:ve_btn_add_audio_entry', 'text:Audio')
    SPLIT = ('desc:ve_tab_split_clip', 'text:Split')
    DELETE = ('desc:ve_btn_delete_media', 'text:Delete')
    DUPLICATE = ('desc:ve_btn_duplicate_clip', 'text:Duplicate')
    REVERSE = ('desc:ve_btn_reverse_clip', 'text:Reverse')
    SPEED = ('desc:ve_tab_clip_speed', 'text:Speed')
    VOLUME = ('desc:ve_tab_clip_volume', 'text:Volume')
    TRIM = ('desc:ve_tab_trim_clip', 'text:Trim')
    FLIP_H, ROTATE = ('desc:ve_btn_flip_horizontal', 'text:Flip'), ('desc:ve_btn_rotate_clip', 'text:Rotate')
    # signs that a sub-panel is open (Back closes it instead of leaving the editor)
    SUBPANEL = ('id:back_icon', 'id:back', 'id:done', 'id:cancel', 'id:header', 'id:cancel_effects')
    FX_ADD_MORE, FX_BACK = 'desc:ve_btn_add_more_effect', 'desc:ve_btn_effects_back'
    STICKER_APPLY, TEXT_INPUT, TEXT_APPLY = 'desc:ve_btn_apply_sticker', 'desc:ve_input_text_area', 'desc:ve_btn_apply_text'
    TUNE_BRIGHT, TUNE_DONE = 'desc:ve_tune_brightness', 'desc:ve_tune_done_button'
    FREEZE_APPLY = 'desc:ve_btn_freeze_apply'
    DRAFT_FIRST = 'desc:ve_thumb_draft_first'
    TRACK, PLAY, TIME, TOTAL = 'id:videoTrackView', 'id:play', 'id:time', 'id:total_time'
    UNDO, REDO, EXPORT, LOADER = 'id:undo', 'id:redo', 'id:export', 'id:loader'
    DONE, CANCEL = 'id:done', 'id:cancel'
    EFFECT_LIST, STICKER_LIST, SPEED_BAR, INTENSITY_BAR = 'id:effect_list', 'id:stickers_recycler', 'id:speed_bar', 'id:intensity_bar'
    X_PROGRESS = ('id:percLabel', 'id:ring_progress', 'id:progress_container')
    X_CANCEL, X_WARN_CANCEL, X_WARN_RESUME = 'id:cancel_button', 'id:cancel_button_warn', 'id:resume_button_warn'
    ANR_DIALOG = ('textc:isn\'t responding', 'textc:not responding')
    # "You are using Premium features" sheet on Export (premium_popup_new.xml)
    PREMIUM = ('id:pro_btn', 'id:export_without_pro_feature_btn', 'textc:using premium features')
    PREMIUM_EXPORT = 'id:export_without_pro_feature_btn'
    # popups that can sit on top of the editor / home screen (rating, celebration, promo)
    DISMISS = ('text:Not now', 'text:Later', 'text:No thanks', 'text:Skip', 'text:Maybe later', 'text:Got it',
               'text:Start Creating', 'textc:start creating')   # first-run "Wizard Editor" intro after a fresh install
    # cold start lands on MainActivity (debug menu): REVAMP UI -> BaseVideoEditorActivity -> My Projects tab
    HOME_TO_PROJECTS = ('id:btn_revamped_ui', 'text:REVAMP UI', 'text:My Projects', 'textc:my projects',
                        'text:Drafts')


def parse_clock(s):
    try:
        v = 0.0
        for p in s.strip().split(':'):
            v = v * 60 + float(p)
        return v
    except ValueError:
        return None


class Editor:
    def __init__(self, dev, ui, mon, log):
        self.dev, self.ui, self.mon, self.log = dev, ui, mon, log
        self.rng = random.Random()
        self.bar = BottomBar(dev)
        self.bar.editor = self                            # lets the bar fall back to tapping a tool by its label
        self.track = None          # videoTrackView bounds, cached once per draft open
        self.baseline_total = None # draft length the first time we saw it (drift check)
        self.artifact_dir = None   # current scenario folder (set by the runner)
        self.edited = False        # did this scenario call an edit action since the draft opened

    # ── plumbing ──
    deadline = None                # wall-clock limit for the current scenario (None = none)

    def _deadline_check(self):
        if self.deadline and time.time() > self.deadline:
            self.deadline = None       # let reset/recovery run
            raise UIError('scenario time limit reached')

    def step(self, name):
        self.mon.check()
        self._deadline_check()
        self.log(f'  · {name}')
        self.dev.marker(name)

    def check(self):
        self.mon.check()

    def idle(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.mon.check()
            self._deadline_check()
            time.sleep(min(0.5, max(0.0, end - time.time())))

    def settle(self, seconds=6):
        """Late-ANR window. A no-op key goes to the focused window: if main is wedged,
        input dispatch times out and the system raises the ANR we are watching for."""
        self.step(f'settle {seconds}s')
        for _ in range(max(1, int(seconds // 2))):
            self.dev.key('KEYCODE_F12')
            self.idle(2)
        self.mon.check()

    def screen(self):
        s = self.ui.dump()
        if s is not None and s.has(T.ANR_DIALOG):
            raise AppFailure('ANR', 'system "isn\'t responding" dialog on screen')
        return s

    def in_editor(self, s):
        # Export and undo/redo are hidden while a sub-menu (clip tools) is open; timeline + play are not.
        return s is not None and s.has(T.TRACK) and s.has(T.PLAY)

    # ── bottom menu: uiautomator if it can see it, else the real view tree ──
    MENU_SEL = {'edit': 'EDIT', 'effects': 'EFFECTS', 'text': 'TEXT', 'sticker': 'STICKER', 'tune': 'TUNE',
                'freeze': 'FREEZE', 'audio': 'AUDIO', 'split': 'SPLIT', 'delete': 'DELETE',
                'duplicate': 'DUPLICATE', 'reverse': 'REVERSE', 'speed': 'SPEED', 'volume': 'VOLUME',
                'flip_h': 'FLIP_H', 'rotate': 'ROTATE'}

    def _validate_clip(self, first, items):
        # DeNoise (index 5) is the only AI-credit tool: its crown proves the bar is the video clip menu,
        # so an index never lands on Delete when we meant Split.
        k = 5 - first
        if 0 <= k < len(items) and not items[k].has_visible('crownIcon'):
            raise UIError('clip menu layout differs from ListUtil.getClipEdit (image clip selected?)')

    def menu_tap(self, name):
        s = self.screen()
        sel = getattr(T, self.MENU_SEL[name]) if name in self.MENU_SEL else None
        if sel and s is not None and s.has(sel):
            self.dev.tap(*s.find(sel).center)
            return
        if name in MAIN_MENU:
            self.bar.tap(MAIN_MENU.index(name), len(MAIN_MENU), expect_submenu=False)
        else:
            self.bar.tap(CLIP_MENU.index(name), len(CLIP_MENU), expect_submenu=True,
                         validate=self._validate_clip)

    # ── opening the project ──
    MEDIA_PERMS = ('READ_MEDIA_VIDEO', 'READ_MEDIA_IMAGES', 'READ_MEDIA_AUDIO', 'READ_EXTERNAL_STORAGE',
                   'WRITE_EXTERNAL_STORAGE', 'POST_NOTIFICATIONS', 'CAMERA', 'RECORD_AUDIO')

    def grant_permissions(self):
        """A reinstall or a revoke leaves the app asking for media access ('Turn on'); grant it like a user would."""
        for p in self.MEDIA_PERMS:
            self.dev.sh(f'pm grant {PKG} android.permission.{p} 2>/dev/null')

    LAB = os.environ.get('ZESTY_LAB', '1') != '0'      # debug-build lab control (app/src/debug LabControl); ZESTY_LAB=0 = taps only

    FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nightshift', 'out', 'author', 'fixtures.json')

    def serial(self):
        b = self.dev.base
        return b[b.index('-s') + 1] if '-s' in b else (os.environ.get('ANDROID_SERIAL') or
                                                        self.dev.adb('get-serialno', timeout=10).strip())

    def drafts(self, timeout=20):
        """My Projects as [{'index', 'id', 'name', 'videos', 'images'}] (debug build lab control)."""
        t0 = self.dev.sh("date +'%m-%d %H:%M:%S.000'").strip()
        self.dev.sh(f'am broadcast -a com.myzesty.LAB -p {PKG} --es cmd drafts')
        end = time.time() + timeout
        while time.time() < end:
            out = self.dev.sh(f"logcat -d -s ZestyLab -T '{t0}'", timeout=20)
            if 'LAB ok drafts' in out:
                rows = []
                for m in re.finditer(r'LAB draft (\d+) id=(\S+) name=(.*?) videos=(\d+) images=(\d+)', out):
                    rows.append({'index': int(m.group(1)), 'id': m.group(2), 'name': m.group(3).strip(),
                                 'videos': int(m.group(4)), 'images': int(m.group(5))})
                return rows
            time.sleep(0.3)
        return []

    def open_draft_id(self, draft_id, timeout=60):
        """Open the project with this id (a lab fixture) like a tap in My Projects; waits for the editor."""
        self.step(f'open project {draft_id[:8]}')
        self.grant_permissions()
        t0 = self.dev.sh("date +'%m-%d %H:%M:%S.000'").strip()
        self.dev.sh(f'am broadcast -a com.myzesty.LAB -p {PKG} --es cmd open_draft_id --es id {shlex.quote(draft_id)}')
        end = time.time() + timeout
        while time.time() < end:
            out = self.dev.sh(f"logcat -d -s ZestyLab -T '{t0}'", timeout=20)
            if 'LAB fail open_draft_id' in out:
                raise UIError('fixture project is gone: ' + out.split('LAB fail open_draft_id', 1)[1][:120].strip())
            if 'LAB ok open_draft_id' in out and self.in_editor(self.screen()):
                return True
            time.sleep(0.5)
        raise UIError(f'project {draft_id[:8]} did not open in {timeout} s')

    # ── project snapshots: lab runs SAVE their edits into the project (2026-10-21: a speed apply saved into the 5-freeze
    # fixture made it crash on every later load). A fixture / pinned project is restored from its snapshot before use.
    def snapshot_app_db(self, tag):
        """Copy the app's project database (My Projects) to files/ns_snap/<tag> inside the app (debug build: run-as)."""
        tag = re.sub(r'[^\w.-]', '_', tag)
        out = self.dev.sh(f"run-as {PKG} sh -c 'mkdir -p files/ns_snap/{tag} && rm -rf files/ns_snap/{tag}/databases "
                          f"&& cp -r databases files/ns_snap/{tag}/ && ls files/ns_snap/{tag}/databases | wc -l'", timeout=60)
        ok = out.strip().splitlines()[-1].strip().isdigit() if out.strip() else False
        self.log(f'    project snapshot "{tag}" ' + ('saved' if ok else f'FAILED: {out.strip()[:120]}'))
        return ok

    def restore_app_db(self, tag):
        """Put the project database back exactly as it was when the snapshot was taken (app stopped first)."""
        tag = re.sub(r'[^\w.-]', '_', tag)
        have = self.dev.sh(f"run-as {PKG} sh -c 'ls files/ns_snap/{tag}/databases 2>/dev/null | wc -l'", timeout=30).strip()
        if not have.isdigit() or int(have) == 0:
            self.log(f'    no project snapshot "{tag}" on this device')
            return False
        self.mon.allow_death = True
        self.dev.force_stop()
        self.dev.sh(f"run-as {PKG} sh -c 'rm -rf databases && cp -r files/ns_snap/{tag}/databases ./'", timeout=60)
        self.dev.launch()
        self._wait_app_focus(8)
        self.mon.allow_death = False
        self.log(f'    projects restored from snapshot "{tag}"')
        return True

    def tap_tool(self, name, tries=10):
        """Tap a bottom-bar tool by its NAME (e.g. 'freeze', 'speed', 'split'): finds the tile whose label text or
        automation tag (desc ve_tab_<name> / ve_btn_..._<name>...) matches, scrolling the bar step by step until it is
        on screen. Works whatever the bar's item count or padding (index-based taps missed 'Freeze' on the realme)."""
        name = name.lower().replace('_', ' ')
        key = name.replace(' ', '_')
        self.step(f'tool: {name}')
        last_sig, direction = None, -1                  # -1: drag left (reveals items on the right) first
        for k in range(tries):
            s = self.screen()
            bar = s.find('id:bottom_bar') if s is not None else None
            if bar is None:
                raise UIError('bottom bar not found')
            L, T_, R, B = bar.b
            hit = None
            for n in s.nodes:
                if not n.visible or not (T_ - 4 <= n.center[1] <= B + 4):
                    continue
                if n.text.strip().lower() == name or (n.desc and (n.desc.lower().endswith('_' + key)
                                                                   or ('_' + key + '_') in n.desc.lower())):
                    hit = n
                    break
            if hit is not None and L + 20 <= hit.center[0] <= R - 20 and hit.b[2] - hit.b[0] > 20:
                self.dev.tap(*hit.center)
                return True
            sig = tuple(sorted(n.text for n in s.nodes if n.text and T_ <= n.center[1] <= B))
            if sig == last_sig:                         # the bar did not move: we hit an end, go the other way
                direction = -direction
            last_sig = sig
            y = T_ + 12                                  # the bar's top strip (its lower part lies in the gesture area)
            w = max(80, (R - L) // 5)
            x0 = (L + R) // 2
            if hit is not None:                          # partly visible: bring it in by the right amount
                direction = -1 if hit.center[0] > (L + R) // 2 else 1
            self.dev.swipe(x0, y, x0 + direction * 2 * w, y, 600)
            time.sleep(0.6)
        raise UIError(f'tool "{name}" not found in the bottom bar')

    def fixture_begin(self):
        """Call FIRST in a lab-fixture builder: remembers which projects exist, so save_fixture finds the new one."""
        rows = self.drafts()
        self._fx_before = {d['id'] for d in rows}
        if rows:                                   # the normal test draft (My Projects #0 now): recipes of OTHER crashes keep
            import json as _j                      # opening exactly this one, even when a fixture becomes the newest project
            try:
                data = _j.load(open(self.FIXTURES))
            except Exception:
                data = {}
            td = data.setdefault('_test_draft', {})
            if not td.get(self.serial()):
                td[self.serial()] = rows[0]['id']
                os.makedirs(os.path.dirname(self.FIXTURES), exist_ok=True)
                _j.dump(data, open(self.FIXTURES + '.tmp', 'w'), indent=1)
                os.replace(self.FIXTURES + '.tmp', self.FIXTURES)
        return len(self._fx_before)

    def _test_draft_id(self):
        try:
            import json as _j
            return ((_j.load(open(self.FIXTURES)).get('_test_draft') or {}).get(self.serial()) or '')
        except Exception:
            return ''

    def save_fixture(self, key, what):
        """Call LAST in a lab-fixture builder, after every ed.require_log check passed: leaves the editor (the app saves
        the project) and records it as this crash's fixture on THIS device, so every later recipe starts from it with
        ed.open_fixture(key) instead of rebuilding it."""
        try:
            self.leave_editor()
        except UIError as e:
            self.log(f'    (leave editor: {e})')
        time.sleep(1.5)
        rows = self.drafts()
        new = [d for d in rows if d['id'] not in getattr(self, '_fx_before', set())]
        pick = new[0] if new else (rows[0] if rows else None)
        if not pick:
            raise UIError('save_fixture: no project found in My Projects')
        import json as _j
        try:
            data = _j.load(open(self.FIXTURES))
        except Exception:
            data = {}
        data.setdefault(key, {})[self.serial()] = {'id': pick['id'], 'what': what[:400], 'videos': pick['videos'],
                                                   'images': pick['images'], 'at': time.strftime('%Y-%m-%d %H:%M')}
        os.makedirs(os.path.dirname(self.FIXTURES), exist_ok=True)
        tmp = self.FIXTURES + '.tmp'
        _j.dump(data, open(tmp, 'w'), indent=1)
        os.replace(tmp, self.FIXTURES)
        self.log(f'    lab fixture saved: "{key}" on {self.serial()} = project {pick["id"][:8]} ({pick["videos"]} videos): {what[:120]}')
        if self.snapshot_app_db(f'fx_{key}'):            # every later recipe starts from this exact state
            data[key][self.serial()]['snapshot'] = f'fx_{key}'
            _j.dump(data, open(tmp, 'w'), indent=1)
            os.replace(tmp, self.FIXTURES)
        self.dev.marker(f'NSFIXTURE saved {key} {pick["id"]}')
        return pick['id']

    def open_fixture(self, key, timeout=60):
        """Open the lab fixture project Night Shift built for this crash on THIS device (tools/nightshift/out/author/
        fixtures.json). Returns its description. UIError when this device has none yet."""
        try:
            import json as _j
            allfx = _j.load(open(self.FIXTURES))
            fx = (allfx.get(key) or {}).get(self.serial()) or {}
            if not fx.get('id') and re.fullmatch(r'[0-9a-f]{8}(-[0-9a-f-]+)?', key or ''):
                # 2026-10-21: recipes passed a fixture DRAFT ID ('617a5fe5') instead of the crash key: find the fixture
                # that holds that draft and use THIS device's copy of it (ids differ per device)
                for k_, devs in allfx.items():
                    if isinstance(devs, dict) and any(isinstance(v, dict) and str(v.get('id', '')).startswith(key)
                                                      for v in devs.values()):
                        fx = devs.get(self.serial()) or {}
                        if fx.get('id'):
                            self.log(f'    open_fixture("{key}"): that is a draft id; using fixture "{k_}" on this device')
                            break
        except Exception:
            fx = {}
        if not fx.get('id'):
            raise UIError(f'no lab fixture project "{key}" on {self.serial()} yet')
        if fx.get('snapshot'):                            # undo whatever earlier runs saved into it
            self.restore_app_db(fx['snapshot'])
        self.open_draft_id(fx['id'], timeout)
        self.log(f'    lab fixture: {fx.get("what", "")[:160]}')
        return fx.get('what', '')

    def lab(self, cmd, timeout=25, **extras):
        """SETUP shortcut through the debug build's lab control: runs inside the app the same code a tap runs (same
        Activity, same extras, same picker result) and waits for its 'LAB ok/fail' log line. True on ok. Never use it
        for the crash trigger itself; a run that only crashes with shortcuts is confirmed again with real taps."""
        if not Editor.LAB:
            return False
        t0 = self.dev.sh("date +'%m-%d %H:%M:%S.000'").strip()
        ex = ' '.join(f'--ei {k} {int(v)}' for k, v in extras.items())
        self.dev.sh(f'am broadcast -a com.myzesty.LAB -p {PKG} --es cmd {cmd} {ex}')
        end = time.time() + timeout
        while time.time() < end:
            out = self.dev.sh(f"logcat -d -s ZestyLab -T '{t0}'", timeout=20)
            for line in out.splitlines():
                if f'LAB ok {cmd}' in line:
                    self.log('    lab control: ' + line.split('LAB ', 1)[1][:160])
                    return True
                if f'LAB fail {cmd}' in line:
                    self.log('    lab control FAILED (using taps): ' + line.split('LAB ', 1)[1][:160])
                    return False
            time.sleep(0.3)
        self.log(f'    lab control: no answer to {cmd} in {timeout} s (not a debug build with LabControl?); using taps')
        return False

    def jni(self, calls, thread='bg', repeat=1, timeout=30):
        """ENGINE REPLAY (Night Shift turbo, debug build only): call Player's static engine methods directly, in order,
        e.g. ed.jni('destroyPlayer();createPlayer();getMediaStartingTime(0,1)'). sleep(ms) waits between calls.
        Returns the list of 'name(args) -> result' lines, or None when the app died (a crash is raised by the
        monitor as AppFailure, like any crash). A replay is a lead and a fast fix check; the proof is a real-tap run."""
        if "'" in calls:
            raise UIError("jni: no single quotes in the calls")
        repeat = max(int(repeat), int(os.environ.get('ZESTY_JNI_REPEAT') or 1))   # turbo fix check: many replays, one session
        t0 = self.dev.sh("date +'%m-%d %H:%M:%S.000'").strip()
        self.step(f'engine replay: {calls[:120]}' + (f' x{repeat}' if repeat > 1 else ''))
        self.dev.sh(f"am broadcast -a com.myzesty.LAB -p {PKG} --es cmd jni --es calls '{calls}' --es thread {thread} --ei repeat {int(repeat)}")
        end, seen = time.time() + timeout + 2 * repeat, []
        while time.time() < end:
            out = self.dev.sh(f"logcat -d -s ZestyLab -T '{t0}'", timeout=20)
            seen = [l.split('LAB step jni ', 1)[1].strip() for l in out.splitlines() if 'LAB step jni ' in l and ' -> ' in l]
            if 'LAB ok jni' in out:
                for s in seen[-6:]:
                    self.log('    ' + s[:160])
                return seen
            if 'LAB fail jni' in out:
                msg = next(l for l in out.splitlines() if 'LAB fail jni' in l).split('LAB fail jni', 1)[1]
                self.log('    engine replay refused: ' + msg[:200])
                raise UIError('engine replay refused' + msg[:200])
            try:
                self.mon.check()                      # the app crashed mid-replay: AppFailure, dumps collected
            except AppFailure:
                raise
            time.sleep(0.3)
        self.mon.check()
        self.log(f'    engine replay: no answer in {timeout} s (last calls: {seen[-2:]})')
        return None

    def remake_test_draft(self):
        """Lab upkeep: a new test draft becomes the FIRST item in My Projects (the old one lost a clip file)."""
        self.step('lab upkeep: new test draft')
        self.mon.allow_death = True
        self.dev.force_stop()
        self.dev.launch()
        time.sleep(4)
        self.mon.allow_death = False
        for _ in range(20):
            s = self.screen()
            if s is not None and s.has(('textc:new project',)):
                break
            if s is not None and s.has(T.HOME_TO_PROJECTS):
                self.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
            elif s is not None and s.has(T.DISMISS):
                self.dev.tap(*s.find(T.DISMISS).center)
            time.sleep(2)
        self.create_draft()
        self.idle(5)
        self.dev.key('KEYCODE_BACK')                  # leave the editor: the project is saved as the newest draft
        self.idle(4)

    def _draft_broken(self):
        """The app closed itself while loading draft #0 because a clip file of it is gone (DraftManager.applyMedia NPE)."""
        out = self.dev.sh('logcat -d -s System.err:W CrashReport:E | grep -m1 "DraftManager.applyMedia"', timeout=20)   # log cleared at run start
        return 'DraftManager.applyMedia' in out

    def open_draft(self, timeout=180):
        self.step('open draft')
        self.grant_permissions()
        if Editor.LAB and getattr(self, '_pin_snapshot', ''):   # a pinned project comes back exactly as the hit run had it
            self.restore_app_db(self._pin_snapshot)
        td = (getattr(self, '_pin_draft', '') or self._test_draft_id()) if Editor.LAB else ''
        if td:                                        # the recorded test draft by id: lab fixtures never replace it as #0
            self.dev.sh(f'am broadcast -a com.myzesty.LAB -p {PKG} --es cmd open_draft_id --es id {shlex.quote(td)}')
        else:
            self.lab('open_draft', index=0)           # instant when available; the loop below confirms the editor (or taps)
        end = time.time() + timeout
        tapped_draft = False
        empty_since, created = None, False
        healed = False
        while time.time() < end:
            if not healed and not created and self._draft_broken():
                healed = True                          # seen on the realme: draft #0 used a lab clip that was cleaned up
                self.log('    test draft is broken (one of its clip files is gone; the app closed itself): making a new one')
                self.mon.allow_death = True            # the app's own exit lands a moment AFTER the stack trace: wait for it
                for _ in range(8):
                    if not self.dev.sh('pidof ' + PKG, timeout=10).strip():
                        break
                    time.sleep(0.5)
                time.sleep(1)
                with self.mon.lock:                    # that exit is the broken draft, not a crash: do not fail the run on it
                    f = self.mon.failure
                    if f and f[0] == 'DIED':
                        self.mon.failure = None
                        self.mon.notes.append('broken test draft, app closed itself (not counted): ' + str(f[1]).strip()[:160])
                self.dev.sh('logcat -c')
                self.remake_test_draft()
                try:                                   # the new test draft replaces the recorded one
                    import json as _j
                    data = _j.load(open(self.FIXTURES))
                    rows = self.drafts()
                    if rows and self.serial() in (data.get('_test_draft') or {}):
                        data['_test_draft'][self.serial()] = rows[0]['id']
                        _j.dump(data, open(self.FIXTURES + '.tmp', 'w'), indent=1)
                        os.replace(self.FIXTURES + '.tmp', self.FIXTURES)
                except Exception:
                    pass
                self.lab('open_draft', index=0)
                end = max(end, time.time() + 120)
                continue
            s = self.screen()
            # a fresh install has no drafts: after ~12 s on an empty My Projects, make one (New Project tab -> picker)
            if s is not None and not created and not self.in_editor(s) and not s.has(T.DRAFT_FIRST) \
                    and s.has(('textc:my projects', 'textc:new project')):
                empty_since = empty_since or time.time()
                if time.time() - empty_since > 12:
                    created = True
                    self.create_draft()
                    end = max(end, time.time() + 120)
                    continue
            if self.in_editor(s):
                if s.has(T.LOADER):
                    time.sleep(1)
                    continue
                self.track = s.find(T.TRACK).b
                for k in ('PLAY', 'UNDO', 'REDO', 'EXPORT', 'TRACK'):
                    n = s.find(getattr(T, k))
                    if n:
                        self.ui.cache[getattr(T, k)] = n.center
                self.idle(1.5)
                self.edited = False            # fresh editor = empty undo history
                return
            if s is not None and s.has(('id:turn_on', 'id:permission_allow_button', 'id:permission_allow_all_button')):
                self.grant_permissions()                 # in-app 'Turn on' sheet or the system Allow dialog
                n = s.find(('id:permission_allow_all_button', 'id:permission_allow_button', 'id:turn_on'))
                self.dev.tap(*n.center)
                time.sleep(2)
                continue
            if s is not None and not self.in_editor(s) and s.has('id:full_editor'):
                self.dev.tap(*s.find('id:full_editor').center)   # wizard editor -> Full Editor
                time.sleep(3)
                continue
            if s is not None:
                if s.has(T.DRAFT_FIRST) and (not tapped_draft or time.time() - tapped_draft > 10):
                    self.dev.tap(*s.find(T.DRAFT_FIRST).center)
                    tapped_draft = time.time()
                elif s.has(T.DISMISS):
                    self.dev.tap(*s.find(T.DISMISS).center)
                elif s.has(T.HOME_TO_PROJECTS) and not s.has(T.DRAFT_FIRST):
                    self.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
                elif tapped_draft and not s.has(T.DRAFT_FIRST):
                    pass                                    # draft loading
                elif s.find_all('id:back_icon') or s.find_all('id:close_base_view'):
                    pass
            time.sleep(1)
        raise UIError('could not reach the editor; open your test draft manually once, '
                      'or run "scenarios.py probe" on the home screen and add its entry to T.HOME_TO_PROJECTS')

    def create_draft(self):
        """Fresh install, no drafts: New Project tab -> gallery picker -> first video -> confirm -> editor (saved as the
        first draft in My Projects). The newest video on the phone is used."""
        self.step('no draft on this install: creating one (New Project -> first video)')
        if not self.ui.tap(('textc:new project',), timeout=10):
            raise UIError('no drafts and no "New Project" tab on this screen')
        s = self.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
        if s is None:
            raise UIError('New Project did not open the gallery picker')
        if s.has('id:video_tab'):
            self.ui.tap('id:video_tab', timeout=5)
            self.idle(1)
            s = self.ui.wait('id:gridrl', timeout=10) or s
        items = s.find_all('id:gridrl')
        if not items:
            raise UIError('the gallery has no videos: push one to /sdcard/DCIM first')
        k = int(os.environ.get('ZESTY_PICK_TILE') or 0)   # Audio Check: the tile its test clip is on (newest = 0)
        if k >= len(items):
            raise UIError(f'gallery tile {k} is not on screen ({len(items)} tiles shown)')
        if k:
            items = sorted(items, key=lambda e: (e.center[1] // 40, e.center[0]))   # reading order: rows, then columns
            self.log(f'    picking gallery tile {k} (the test clip)')
        self.dev.tap(*items[k].center)
        self.idle(1)
        self._picker_confirm()
        end = time.time() + 150                  # transcode of a long clip
        while time.time() < end:
            sc = self.screen()
            if sc is not None and self.in_editor(sc) and not sc.has(T.LOADER):
                self.log('    draft created')
                return
            if sc is not None and sc.has(T.DISMISS):             # first-run intro dialogs on top of the editor
                self.dev.tap(*sc.find(T.DISMISS).center)
                time.sleep(2)
                continue
            if sc is not None and sc.has('id:full_editor'):     # new projects open in the wizard editor first
                self.log('    wizard editor: switching to Full Editor')
                self.dev.tap(*sc.find('id:full_editor').center)
                time.sleep(3)
                continue
            time.sleep(2)
        raise UIError('the new project did not open in the editor')

    def open_slideshow(self, n=3, wait=180):
        """Cold start -> SlideShow -> pick n clips -> Done; returns once the slideshow screen is up (ids: add_video = add media, rvMedias = clip strip, play, seekBar, export, back)."""
        self.step(f'open SlideShow with {n} clip(s)')
        self.grant_permissions()
        self.mon.allow_death = True                  # our own force-stop is not a crash
        self.dev.force_stop()
        time.sleep(1.5)
        self.dev.launch()
        time.sleep(3)
        self.mon.allow_death = False
        if self.lab('open_slideshow', n=max(1, n), timeout=30):
            self.log(f'    slideshow: {max(1, n)} clip(s) handed to the picker result (lab control)')
        else:
            if not self.ui.tap(('id:btnSlideShow', 'textc:slideshow', 'textc:slide show'), timeout=30):
                raise UIError('no SlideShow button on the start screen after a cold start')
            s = self.ui.wait(('id:select_cover', 'id:gridrl'), timeout=30)
            if s is None:
                raise UIError('SlideShow did not open its gallery picker')
            tiles = s.find_all('id:select_cover') or s.find_all('id:gridrl')
            if not tiles:
                raise UIError('the SlideShow picker shows no media: push some to /sdcard/DCIM first')
            for t in tiles[:max(1, n)]:
                self.dev.tap(*t.center)
                time.sleep(0.5)
            self._picker_confirm()
            self.log(f'    slideshow: {min(n, len(tiles))} clip(s) picked, Done tapped')
        if wait and self.ui.wait(('id:rvMedias', 'id:add_video'), timeout=wait) is None:
            raise UIError(f'the slideshow screen (ids rvMedias / add_video) did not appear within {wait} s')
        return self.screen()

    # ── slideshow (QuickCutActivity) building blocks: tested on the lab phone, use them instead of raw taps ──
    def slideshow_deselect(self):
        """Clear the clip selection in the slideshow strip (with a clip selected, the + button DELETES it instead of adding)."""
        s = self.screen()
        strip = s.find('id:rvMedias') if s is not None else None
        y = (strip.b[3] + 90) if strip is not None else int(self.dev.h * 0.92)
        self.dev.tap(self.dev.w // 2, min(y, self.dev.h - 120))       # empty area of the media panel = root click
        time.sleep(0.6)

    def slideshow_media_count(self):
        """How many clips the slideshow strip shows (thumbnails inside rvMedias)."""
        s = self.screen()
        strip = s.find('id:rvMedias') if s is not None else None
        if strip is None:
            return -1
        x1, y1, x2, y2 = strip.b
        return sum(1 for n in s.nodes if n.rid.endswith(':id/imageView') and n.visible
                   and n.b[0] >= x1 - 2 and n.b[2] <= x2 + 300 and n.b[1] >= y1 - 2 and n.b[3] <= y2 + 2)

    def slideshow_add_media(self, n=1, wait=0):
        """Slideshow + -> gallery -> pick the n newest clips -> Done (ss_media_add_btn; MsgAddVideo per clip). wait>0: block until the strip grows."""
        self.step(f'slideshow: add {n} clip(s)')
        before = self.slideshow_media_count()
        for attempt in range(2):
            self.slideshow_deselect()
            if not self.ui.tap('id:add_video', timeout=10):
                raise UIError('slideshow + (id add_video) not on screen')
            s = self.ui.wait(('id:select_cover', 'id:gridrl'), timeout=8)
            if s is not None:
                break
            self.log('    + did not open the picker (a clip was selected?): deselecting and retrying')
        else:
            raise UIError('slideshow + (id add_video) did not open the gallery picker twice')
        tiles = s.find_all('id:select_cover') or s.find_all('id:gridrl')
        for t in tiles[:max(1, n)]:
            self.dev.tap(*t.center)
            time.sleep(0.5)
        self._picker_confirm()
        self.log(f'    slideshow: {min(n, len(tiles))} clip(s) added (strip had {before})')
        if wait:
            end = time.time() + wait
            while time.time() < end:
                if self.slideshow_media_count() > before:
                    return True
                time.sleep(2)
            return False
        return True

    def slideshow_toggle_play(self):
        """Play/pause in the slideshow preview (ss_play_pause_btn)."""
        try:
            return self.ui.tap('id:play', timeout=5)
        except UIError:
            return False

    def leave_editor(self):
        """Back out to My Projects (editor saves on exit)."""
        self.step('leave editor')
        for _ in range(6):
            s = self.screen()
            if s is not None and not self.in_editor(s) and s.has(T.DRAFT_FIRST):
                return
            self.dev.key('KEYCODE_BACK')
            self.idle(1.2)
        raise UIError('did not get back to My Projects')

    def recover(self):
        self.log('  ↺ recover: force-stop + reopen draft')
        self.mon.allow_death = True
        self.dev.force_stop()
        time.sleep(1.5)
        self.dev.launch()
        time.sleep(3)
        self.open_draft()
        self.mon.allow_death = False

    # ── navigation inside the editor ──
    def main_nav(self):
        """Back to the top-level bottom menu. Back is pressed only when a sub-menu/panel is
        provably open: at the top level Back leaves the editor."""
        for _ in range(4):
            s = self.screen()
            if s is not None and s.has(T.PREMIUM) and s.has('id:close_btn'):
                self.log('    closing premium sheet')               # left over from an export attempt
                self.dev.tap(*s.find('id:close_btn').center)
                self.idle(1)
                continue
            if s is not None and s.has('id:react_container') and s.has('id:btn_done') and s.has('id:cancel'):
                # a full-screen React Native panel (stickers / text…) on top of the editor, often left blank after
                # the app returns from the background: close it, the editor is underneath
                self.log('    closing a panel left open on top of the editor (react_container)')
                c = [n for n in s.find_all('id:cancel')] if hasattr(s, 'find_all') else [s.find('id:cancel')]
                self.dev.tap(*c[-1].center)
                self.idle(1.2)
                continue
            if s is not None and s.has(T.EDIT):
                return s
            if (s is not None and s.has(T.UNDO) and s.has(T.EXPORT) and s.has(T.TRACK)
                    and not s.has(T.SUBPANEL)):
                return s                                   # header + undo, no panel open -> main menu
            if s is not None and not self.in_editor(s) and s.has(T.DRAFT_FIRST):
                self.open_draft()
                continue
            bar, items, back = self.bar.read()
            if bar is not None and not back:
                return s                                   # main menu (invisible to uiautomator)
            if not (back or (s is not None and (s.has(T.SUBPANEL) or s.has(T.SPLIT)))):
                raise UIError('neither the main menu nor a sub-menu is visible')
            self.dev.key('KEYCODE_BACK')
            self.idle(0.8)
        raise UIError('main menu not reachable')

    def in_clip_tools(self):
        s = self.screen()
        if s is not None and s.has(T.SPLIT):
            return True
        bar, items, back = self.bar.read()
        if not back:
            return False
        try:
            self._validate_clip(0 if abs(items[0].b[0] - bar.b[0]) <= 2 else 99, items)
            return True
        except UIError:
            return False

    def clip_tools(self):
        if self.in_clip_tools():
            return
        self.main_nav()
        self.menu_tap('edit')
        self.idle(1)
        if not self.in_clip_tools():
            raise UIError('clip tools did not open after tapping Edit')

    def clip_tool(self, name, label=None):
        self.step(label or name)
        self.clip_tools()
        self.menu_tap(name)
        self.idle(0.8)
        self.wait_loader()

    def wait_loader(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            s = self.screen()
            if s is None or not s.has(T.LOADER):
                return
            self.idle(0.5)

    # ── playback ──
    def read_time(self):
        s = self.screen()
        n = s.find(T.TIME) if s else None
        tot = s.find(T.TOTAL) if s else None
        return (parse_clock(n.text) if n else None), (parse_clock(tot.text) if tot else None)

    def is_playing(self):
        a, _ = self.read_time()
        time.sleep(1.2)
        b, _ = self.read_time()
        return a is not None and b is not None and b != a

    def toggle_play(self):
        self.step('play/pause')
        self.ui.tap_cached(T.PLAY)
        self.idle(0.3)

    def set_playing(self, on):
        if self.is_playing() != on:
            self.toggle_play()
            self.idle(0.5)

    # ── seeking (timeline is a HorizontalScrollView; content left = later) ──
    def _track_y(self):
        if not self.track:
            s = self.screen()
            n = s.find(T.TRACK) if s else None
            if not n:
                raise UIError('timeline not visible')
            self.track = n.b
        l, t, r, b = self.track
        return l, r, t + (b - t) // 5      # the clip strip (track view 1475..2177 -> y≈1615)

    def seek_swipe(self, frac, ms):
        """frac in [-1,1] of the track width; negative = forward in time."""
        l, r, y = self._track_y()
        w = r - l
        cx = l + int(w * 0.45)               # shifted left: the add-media '+' sits at the right edge
        if abs(frac) < 0.3:                  # a short swipe registers as a tap (selects / opens things)
            frac = 0.3 if frac >= 0 else -0.3
        dx = int(frac * w * 0.45)
        self.dev.swipe(cx - dx // 2, y, cx + dx // 2, y, ms)

    def seek_storm(self, n=30, min_ms=30, max_ms=220, pause=(0.0, 0.25)):
        self.step(f'seek storm x{n}')
        for i in range(n):
            self.seek_swipe(self.rng.uniform(-1, 1), self.rng.randint(min_ms, max_ms))
            if i % 5 == 4:
                self.mon.check()
            time.sleep(self.rng.uniform(*pause))

    def seek_start(self):
        self.step('seek to start')
        for _ in range(4):
            self.seek_swipe(1.0, 80)
            time.sleep(0.25)
        self.idle(0.8)

    def seek_end(self):
        self.step('seek to end')
        for _ in range(4):
            self.seek_swipe(-1.0, 80)
            time.sleep(0.25)
        self.idle(0.8)

    def seek_to(self, frac, tol=1.0):
        """Seek to frac of total duration using the playhead clock (1 s resolution) as feedback.
        The timeline's px-per-second is learned once and reused, so later seeks take 1-2 drags."""
        self.step(f'seek to {frac:.2f}')
        l, r, y = self._track_y()
        cx = l + int((r - l) * 0.45)
        cur, tot = self.read_time()
        if cur is None or not tot:
            raise UIError('cannot read time/total_time')
        target = max(0.0, min(tot - 0.5, frac * tot))
        pps = getattr(self, 'pps', None)
        still = 0
        for _ in range(8):
            err = target - cur
            if abs(err) <= tol:
                return cur
            if still >= 2 or getattr(self, '_drag_dead', False):
                self._drag_dead = True                    # this session: drags do not seek, go straight to play
                return self._seek_by_play(target, cur, tot)
            dx = -err * pps if pps else (-400 if err > 0 else 400)
            dx = max(-(r - l) * 0.65, min((r - l) * 0.65, dx))   # stays within ~12%..78% of width
            self.dev.drag_no_fling(cx - dx / 2, y, cx + dx / 2)
            time.sleep(0.3)
            new, _ = self.read_time()
            if new is None:
                break
            moved = abs(new - cur)
            still = still + 1 if moved == 0 else 0      # 2026-10-21: drags on the clip strip stopped moving the playhead
            if moved >= 2 and abs(dx) > 50:                  # enough signal over the 1 s rounding
                est = abs(dx) / moved
                pps = est if pps is None else 0.5 * pps + 0.5 * est
                self.pps = pps
            cur = new
        return cur

    def _seek_by_play(self, target, cur, tot):
        """Fallback when timeline drags do not move the playhead: (jump to the start if the target is behind,) play for
        exactly the remaining time by the wall clock, pause. Screen dumps take 1-3 s, so polling the clock overshot."""
        self.log(f'    timeline drag does not move the playhead: playing from {cur} s to {target:.1f} s instead')
        if target < cur - 0.5:
            s = self.screen()
            n = s.find('id:previous_button') if s is not None else None
            if n is None:
                raise UIError(f'seek back failed: playhead at {cur} s, target {target:.1f} s, no jump-to-start button')
            self.dev.tap(*n.center)
            self.idle(1.0)
            cur, _ = self.read_time()
            cur = cur or 0.0
        self.toggle_play()
        t0 = time.time()
        while time.time() - t0 < max(0.0, target - cur - 0.25):
            time.sleep(0.05)
        self.toggle_play()
        self.idle(0.6)
        now, _ = self.read_time()
        self.log(f'    playhead now {now} s (target {target:.1f} s)')
        if now is None or abs(now - target) > 2.5:
            raise UIError(f'seek by play missed: playhead {now} s, target {target:.1f} s')
        return now

    # ── edit actions ──
    def split(self, strict=False):
        """strict: the split MUST reach the engine (MsgSplitVideo), else one retry by the tool's label, then UIError.
        2026-10-21: the index tap silently did nothing and the Audio Check exported an unsplit clip (bogus 4/5)."""
        mark = self.log_mark()
        self.clip_tool('split')
        if not strict or self.wait_log(r'MsgSplitVideo: media_layer', 8, since=mark):
            return
        now, _ = self.read_time()
        self.log(f'    split did not reach the engine (playhead {now} s): tapping Split again')
        try:                                     # the clip bar is not in the UI dump (below its window): index tap
            self.clip_tool('split')
        except UIError:
            self.tap_tool('split')
        if not self.wait_log(r'MsgSplitVideo: media_layer', 10, since=mark):
            raise UIError('split did not reach the engine (no MsgSplitVideo)')

    def split_at(self, frac, strict=False):
        self.seek_to(frac)
        self.split(strict)

    def delete_clip(self):
        self.clip_tool('delete', 'delete clip')

    def duplicate_clip(self):
        self.clip_tool('duplicate', 'duplicate clip')

    def reverse_clip(self):
        self.clip_tool('reverse', 'reverse clip')
        self.wait_loader(180)

    def flip_or_rotate(self):
        # Rotate (index 12) is reachable by scrolling the bar to its end. Flip H (10) sits mid-bar,
        # which neither the start nor the end window shows on a 1080-px screen, so it is not used.
        s = self.screen()
        if s is not None and s.has(T.FLIP_H) and self.rng.random() < 0.5:
            self.clip_tool('flip_h', 'flip clip')          # only when uiautomator can see it
        else:
            self.clip_tool('rotate', 'rotate clip')

    def _drag_bar_and_done(self, bar, name):
        s = self.ui.wait(bar, timeout=8)
        if s is not None:
            l, t, r, b = s.find(bar).b
            y = (t + b) // 2
            x0 = (l + r) // 2
            self.dev.swipe(x0, y, self.rng.randint(l + 10, r - 10), y, self.rng.randint(150, 600))
            self.idle(0.6)
        else:
            self.log(f'    ({name}: bar {bar} not found, applying as is)')
        s = self.screen()
        if s is not None and s.has(T.DONE):
            self.dev.tap(*s.find(T.DONE).center)
        else:
            self.dev.key('KEYCODE_BACK')
        self.idle(0.8)
        self.wait_loader()

    def change_speed(self):
        self.clip_tool('speed')
        self._drag_bar_and_done(T.SPEED_BAR, 'speed')

    def change_volume(self):
        self.clip_tool('volume')
        self._drag_bar_and_done(('id:seekbar', 'id:seekBar'), 'volume')

    def undo(self, n=1, gap=(0.05, 0.3)):
        self.step(f'undo x{n}')
        self.main_nav()
        for _ in range(n):
            self.ui.tap_cached(T.UNDO)
            time.sleep(self.rng.uniform(*gap))
        self.mon.check()

    def redo(self, n=1, gap=(0.05, 0.3)):
        self.step(f'redo x{n}')
        self.main_nav()
        for _ in range(n):
            self.ui.tap_cached(T.REDO)
            time.sleep(self.rng.uniform(*gap))
        self.mon.check()

    def effects_browse(self, n=15, apply=True, gap=(0.1, 0.8)):
        self.step(f'effects browse x{n} apply={apply}')
        self.main_nav()
        self.menu_tap('effects')
        s = self.ui.wait((T.EFFECT_LIST, T.FX_ADD_MORE), timeout=10)
        if s is None:
            raise UIError('effects panel did not open')
        if not s.has(T.EFFECT_LIST):
            self.dev.tap(*s.find(T.FX_ADD_MORE).center)
            s = self.ui.wait(T.EFFECT_LIST, timeout=10)
            if s is None:
                raise UIError('effect list did not open')
        tiles = [c.center for c in s.items(T.EFFECT_LIST)]
        if not tiles:
            raise UIError('effect list is empty (offline?)')
        for i in range(n):
            self.dev.tap(*self.rng.choice(tiles))
            time.sleep(self.rng.uniform(*gap))
            if i % 4 == 3:
                self.mon.check()
        self.idle(1)
        s = self.screen()
        if apply and s is not None and s.has(T.DONE):
            self.dev.tap(*s.find(T.DONE).center)
        elif s is not None and s.has(T.FX_BACK):
            self.dev.tap(*s.find(T.FX_BACK).center)
        else:
            self.dev.key('KEYCODE_BACK')
        self.idle(1)

    def add_sticker(self):
        self.step('add sticker')
        self.main_nav()
        self.menu_tap('sticker')
        s = self.ui.wait(T.STICKER_LIST, timeout=12)
        tiles = s.items(T.STICKER_LIST) if s else []
        if not tiles:
            self.dev.key('KEYCODE_BACK')
            raise UIError('sticker list empty (offline?)')
        self.dev.tap(*self.rng.choice(tiles[:6]).center)
        self.idle(2)
        s = self.screen()
        n = s.find((T.STICKER_APPLY, T.DONE)) if s else None
        if n:
            self.dev.tap(*n.center)
        self.idle(1)

    def add_media(self, fail_decode=False, pick=0):
        """Add one clip through the editor's "+" (id addVideo) and the gallery picker.
        fail_decode=True arms the debug-only engine hook debug.zesty.hook.fail_add_video, so add_video fails the way
        it did on the field device in Crashlytics 2bc43cd6 (AMediaCodec_configure -10000). Needs a debug build."""
        self.step('add media' + (' (decode fails)' if fail_decode else ''))
        if fail_decode:
            self.dev.setprop('debug.zesty.hook.fail_add_video', '1')
        try:
            if not self.ui.tap(('id:add_video', 'id:addVideo'), timeout=10):
                raise UIError('add media button (id add_video) not found')
            s = self.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
            if s is None:
                raise UIError('gallery picker did not open')
            if s.has('id:video_tab'):
                self.ui.tap('id:video_tab', timeout=5)
                self.idle(1)
                s = self.ui.wait('id:gridrl', timeout=10) or s
            items = s.find_all('id:gridrl')
            if not items:
                raise UIError('no media items in the picker (gallery empty?)')
            self.dev.tap(*items[min(pick, len(items) - 1)].center)
            self.idle(1)
            self._picker_confirm()
            self.idle(4)                       # engine add + transcode + Kotlin follow-up calls
            self.edited = True
        finally:
            if fail_decode:
                self.dev.setprop('debug.zesty.hook.fail_add_video', '0')

    _CONFIRM_ID = re.compile(r'(done|next|import|confirm|apply|select_?btn|btn_?select|ok|tick|check|proceed|continue|add_?btn|btn_?add)$', re.I)
    _CONFIRM_TXT = {'done', 'next', 'add', 'import', 'ok', 'select', 'apply', 'continue', 'confirm',
                    'تم', 'التالي', 'إضافة', 'اضافة', 'موافق', 'استيراد'}

    def _screen_size(self):
        if not getattr(self, '_wh', None):
            m = re.findall(r'(\d+)x(\d+)', self.dev.sh('wm size') or '')
            self._wh = tuple(map(int, m[-1])) if m else (10**5, 10**5)   # last = override size if set
        return self._wh

    def _picker_confirm(self, timeout=12):
        """Press the gallery picker's confirm button. Its id/position differs between builds and phones
        (on some phones id:done is laid out off-screen), so look for any on-screen confirm-like control and,
        if none is found, save what the picker shows so the next run can be fixed without guessing."""
        end = time.time() + timeout
        s = None
        while time.time() < end:
            s = self.ui.dump()
            if s is not None and not isinstance(s, Screen):
                s = Screen(s) if '<?xml' in s else None
            if s is not None:
                W, H = self._screen_size()
                cands = []
                for n in s.nodes:
                    if not n.visible or not n.enabled:
                        continue
                    cx, cy = n.center
                    if not (0 <= cx < W and 0 <= cy < H):
                        continue                      # laid out off-screen: tapping there does nothing
                    rid = n.rid.split('/')[-1]
                    txt = (n.text or n.desc or '').strip().lower()
                    if (rid and self._CONFIRM_ID.search(rid)) or txt in self._CONFIRM_TXT or re.match(r'^(done|next|add|import)\b', txt):
                        cands.append(n)
                if cands:
                    self.dev.tap(*cands[0].center)
                    self.step(f'picker confirm: {cands[0]!r}')
                    return
                # uiautomator reports this picker's window ~220px short on some phones (immersive mode), so the
                # DONE row under selected_media_list is missing from the dump although it is drawn on screen
                # (bottom-right, ~100px above the screen edge). Tap where it is drawn.
                cut = max((n.b[3] for n in s.nodes if n.visible), default=H) < H * 0.93   # the dump stops short of the screen
                if s.has('id:selected_media_list') or s.has('id:bottom_container') or (cut and s.has('id:mediaList')):
                    # DONE is drawn bottom-right at ~86% / ~95.5% of the screen on every phone seen (A51 1080x2400,
                    # realme RMX3263 720x1600)
                    self.dev.tap(int(W * 0.86), int(H * 0.955))
                    self.idle(1.5)
                    s2 = self.ui.dump()
                    if s2 is None or not s2.has('id:mediaList'):
                        self.step('picker confirm: tapped DONE at its drawn position (missing from the UI dump)')
                        return
            time.sleep(1)
        try:
            d = getattr(self, 'artifact_dir', None)
            if d:
                os.makedirs(d, exist_ok=True)
                if s is not None:
                    open(os.path.join(d, 'picker_screen.txt'), 'w').write(s.summary())
                self.dev.screenshot(os.path.join(d, 'picker_screen.png'))
        except Exception:
            pass
        raise UIError('picker confirm button not found on screen (saved picker_screen.txt/.png in the run folder)')

    def add_text(self, txt='stress test'):
        self.step('add text')
        self.main_nav()
        self.menu_tap('text')
        s = self.ui.wait((T.TEXT_INPUT, 'id:editTextArea'), timeout=10)
        if s is None:
            raise UIError('text editor did not open')
        self.dev.tap(*s.find((T.TEXT_INPUT, 'id:editTextArea')).center)
        self.dev.text(txt)
        self.idle(0.5)
        self.ui.tap((T.TEXT_APPLY, T.DONE), timeout=6)
        self.idle(1)

    def tune(self):
        self.step('tune')
        self.main_nav()
        self.menu_tap('tune')
        self.ui.tap(T.TUNE_BRIGHT, timeout=8)
        s = self.ui.wait(T.INTENSITY_BAR, timeout=6)
        if s is not None:
            l, t, r, b = s.find(T.INTENSITY_BAR).b
            y = (t + b) // 2
            for _ in range(4):
                self.dev.swipe(self.rng.randint(l, r), y, self.rng.randint(l, r), y, self.rng.randint(80, 400))
        self.ui.tap((T.TUNE_DONE, T.DONE), timeout=6)
        self.idle(1)

    def freeze(self):
        self.step('freeze frame')
        self.main_nav()
        self.menu_tap('freeze')
        self.idle(1)
        s = self.screen()
        n = s.find((T.FREEZE_APPLY, T.DONE)) if s else None
        if n:
            self.dev.tap(*n.center)
        self.idle(1.5)
        self.wait_loader()

    # ── export ──
    def export_start(self):
        self.step('export start')
        s = self.screen()
        if s is not None and not s.has(T.EXPORT):
            self.main_nav()
        self.ui.tap(T.EXPORT)
        end = time.time() + 30
        premium_taps = 0
        while time.time() < end:
            self.mon.check()
            if self.mon.progress_n:
                return
            s = self.screen()
            if s is not None and s.has(T.X_PROGRESS):
                return
            if s is not None and s.has(T.PREMIUM) and premium_taps < 3:
                self.tap_premium_export(s)
                premium_taps += 1
                end = time.time() + 30
            time.sleep(0.5)
        raise UIError('export did not start (no progress UI / MsgGetExportingProgress)')

    def tap_premium_export(self, s):
        """Premium-features sheet: choose "Export with watermark". The button sits below the 2177-px
        edge uiautomator can see; it is 50dp tall, 12dp under pro_btn (also 50dp): center =
        pro_btn.bottom + 0.74 * pro_btn.height."""
        self.log('    premium sheet → export with watermark')
        n = s.find(T.PREMIUM_EXPORT)
        if n is not None:
            self.dev.tap(*n.center)
        else:
            pro = s.find('id:pro_btn')
            if pro is None:
                raise UIError('premium sheet without pro_btn')
            l, t, r, b = pro.b
            self.dev.tap((l + r) // 2, int(b + 0.74 * (b - t)))
        self.idle(1.5)

    def export_progress(self):
        s = self.screen()
        if (s is None or not s.has('id:percLabel')) and self.export_running() and self.mon.progress_val is not None:
            return int(self.mon.progress_val), s
        n = s.find('id:percLabel') if s else None
        if n and n.text.strip().endswith('%'):
            try:
                return int(n.text.strip()[:-1]), s
            except ValueError:
                pass
        return None, s

    def wait_export_percent(self, pct, timeout=600):
        self.step(f'wait export ≥{pct}%')
        end = time.time() + timeout
        self._stall_pct = None
        misses = 0
        while time.time() < end:
            p, s = self.export_progress()
            if p is not None and p >= pct:
                return p
            if s is not None and s.has(T.X_PROGRESS):
                self._stall_check(s)
                misses = 0
            elif s is not None and s.has(T.PREMIUM):
                self.tap_premium_export(s)
            elif self.export_running():
                misses = 0
            elif s is not None:
                # one dump without the dialog proves nothing (sheet closing, transition); finished =
                # dialog gone twice in a row AND the engine stopped polling progress for 4 s
                misses += 1
                q = self.mon.export_quiet_for()
                if misses >= 2 and q is not None and q >= 4:
                    raise UIError(f'export finished before reaching {pct}%')
            self.idle(0.5)
        raise UIError(f'export never reached {pct}%')

    def export_wait_done(self, timeout=900):
        """Done = export dialog gone and engine stopped polling progress for 4 s."""
        self.step('export wait done')
        end = time.time() + timeout
        self._stall_pct = None
        while time.time() < end:
            self.idle(1)
            q = self.mon.export_quiet_for()
            if q is not None and q < 4:
                continue
            s = self.screen()
            if s is not None and s.has(T.X_PROGRESS):
                self._stall_check(s)
                continue
            if s is None and (q is None or q < 8):
                continue
            self.log('    export finished')
            self.back_to_editor()
            return
        raise UIError('export did not finish in time')

    EXPORT_STALL_S = int(os.environ.get('ZESTY_EXPORT_STALL_S', 90))

    def _stall_check(self, s):
        """Raise EXPORT_STUCK if the export percent hasn't moved for EXPORT_STALL_S."""
        n = s.find('id:percLabel') if s is not None else None
        pct = n.text.strip() if n else None
        now = time.time()
        if pct is None or pct != getattr(self, '_stall_pct', None):
            self._stall_pct, self._stall_t = pct, now
            return
        if now - self._stall_t > self.EXPORT_STALL_S:
            self._stall_pct = None
            raise AppFailure('EXPORT_STUCK', f'export frozen at {pct} for {self.EXPORT_STALL_S}s')

    def back_to_editor(self, tries=6, export_wait=900):
        end = time.time() + export_wait
        self._stall_pct = None
        n = 0
        while n < tries:
            s = self.screen()
            if s is not None and s.has(T.X_PROGRESS):
                self._stall_check(s)
            if s is not None and s.has(T.X_WARN_CANCEL) and s.has(T.X_WARN_RESUME) and time.time() < end:
                self.dev.tap(*s.find(T.X_WARN_RESUME).center)   # stray cancel warning: keep exporting
                self.idle(1)
                continue
            if ((s is not None and s.has(T.X_PROGRESS)) or self.export_running()) and time.time() < end:
                self.idle(2)                 # exporting (screen often undumpable): Back would open cancel
                continue
            if self.in_editor(s) and not (s.has(T.X_PROGRESS) or s.has(T.X_WARN_CANCEL)):
                self.idle(1)
                return
            n += 1
            if s is not None and s.has(T.DISMISS):
                self.dev.tap(*s.find(T.DISMISS).center)
            else:
                self.dev.key('KEYCODE_BACK')         # share screen / celebration dialog
            self.idle(1.5)
        s = self.screen()
        if s is not None and s.has(T.DRAFT_FIRST):
            self.open_draft()
            return
        raise UIError('could not return to the editor after export')

    def export_full(self):
        self.export_start()
        self.export_wait_done()

    def export_abort(self, after_s=None, at_pct=None, resume=False):
        self.export_start()
        if at_pct is not None:
            try:
                self.wait_export_percent(at_pct)
            except UIError as e:
                if 'finished before' not in str(e):
                    raise
                self.log(f'    ({e}: nothing to cancel)')
                self.back_to_editor()
                return
        else:
            self.idle(after_s if after_s is not None else self.rng.uniform(0.5, 3))
        self.cancel_export(resume=resume)

    # Export dialog Cancel (CardView above the 50sdp ad banner) and the confirm sheet's Cancel/Resume
    # sit at/below the 2177-px edge uiautomator reports, so they are often invisible to it.
    WARN_DY = int(os.environ.get('ZESTY_WARN_DY', 128))        # warn_body.bottom -> button row centre
    WARN_X = (float(os.environ.get('ZESTY_WARN_CANCEL_X', 0.29)), float(os.environ.get('ZESTY_WARN_RESUME_X', 0.71)))

    def cancel_export(self, resume=False):
        """Cancel the running export (or open the warning and Resume). Returns True if the engine aborted."""
        self.step('export cancel' + (' → resume' if resume else ' → confirm abort'))
        s = self.screen()
        if s is not None and s.has(T.X_CANCEL):
            self.dev.tap(*s.find(T.X_CANCEL).center)
        elif (s is not None and s.has(T.X_PROGRESS)) or self.export_running():
            return self._warn_blind(resume)   # screen undumpable during export: pixels + logcat
        else:
            self.log('    (export dialog gone — export already finished, nothing to cancel)')
            self.back_to_editor()
            return False
        warn_sel = (T.X_WARN_CANCEL, T.X_WARN_RESUME, 'id:warn_body', 'id:warn_header')
        s = self.ui.wait(warn_sel, timeout=5)
        if s is None:
            # The sheet opened over the still-animating export dialog, so uiautomator can't dump it.
            # Tap blind and let logcat confirm (MsgAbortExport / progress resuming).
            return self._warn_blind(resume)
        aborts_before = self.mon.abort_n
        for attempt in range(3):
            self._tap_warn(s, 'resume' if resume else 'cancel', attempt)
            self.idle(1.5)
            s = self.screen()
            if s is None or not s.has(warn_sel):
                break
        else:
            raise UIError('cancel warning still open after 3 taps (button position wrong?)')
        if resume:
            self.export_wait_done()
            return False
        t0 = time.time()
        gone = self.ui.wait(T.X_PROGRESS, timeout=60, gone=True, on_poll=self.mon.check)
        took = time.time() - t0
        engine = self.mon.abort_n > aborts_before
        self.log(f'    abort took {took:.1f}s · engine abort seen in logcat: {"yes" if engine else "NO"}')
        if gone is None:
            raise UIError('export dialog still up 60 s after confirming abort')
        if not engine and s is not None and s.has(T.X_PROGRESS):
            raise UIError('confirmed abort but export kept running (tapped Resume by mistake?)')
        self.back_to_editor()
        return engine

    # "Cancel Exporting?" sheet, measured on a 1080x2400 screenshot: Cancel (red) centre (306, 2289),
    # Resume (dark) centre (773, 2290). Stored as fractions of the screen so other sizes scale.
    WARN_CANCEL = (0.283, 0.954)
    WARN_RESUME = (0.716, 0.954)
    # Export dialog's own Cancel: grey card (94,94,96) on the near-black dialog (25,25,27), measured at
    # y 2224..2331, x 337..741 on a 1080x2400 A51 (no ad banner in this build). Found by colour first.
    EXPORT_CANCEL_FALLBACK = (0.5, 0.949)

    def find_export_cancel(self):
        """Scan a column of one screenshot for the grey Cancel card; return its centre or None."""
        w, h = self.dev.w, self.dev.h
        x = int(w * 0.37)
        ys = list(range(int(h * 0.70), h, 3))
        px = self.dev.pixels([(x, y) for y in ys])
        runs, start = [], None
        for y, p in zip(ys, px):
            grey = p is not None and 70 < p[0] < 130 and abs(p[0] - p[1]) < 12 and abs(p[1] - p[2]) < 12
            if grey and start is None:
                start = y
            elif not grey and start is not None:
                runs.append((start, y - 3))
                start = None
        if start is not None:
            runs.append((start, ys[-1]))
        runs = [r for r in runs if r[1] - r[0] >= 40]          # a button, not a text stroke
        if not runs:
            return None
        top, bot = runs[-1]                                     # lowest grey block = Cancel
        return int(w * 0.5), (top + bot) // 2

    def _xy(self, frac):
        return int(self.dev.w * frac[0]), int(self.dev.h * frac[1])

    def warn_open(self):
        """Pixel test: the sheet's Cancel button is solid red; nothing red sits there otherwise."""
        (px,) = self.dev.pixels([self._xy(self.WARN_CANCEL)])
        if px is None:
            return None
        r, g, b = px
        return r > 180 and g < 140 and b < 140

    def _open_warn_sheet(self):
        """Back first (cheap); then the dialog's own grey Cancel card, located by colour."""
        self.dev.key('KEYCODE_BACK')
        self.idle(1.5)
        if self.warn_open():
            self.log('    cancel sheet opened by Back')
            return True
        for attempt in range(3):
            if not self.export_running():
                return False
            xy = self.find_export_cancel() or self._xy(self.EXPORT_CANCEL_FALLBACK)
            self.log(f'    tapping export Cancel card at {xy}')
            self.dev.tap(*xy)
            self.idle(1.5)
            if self.warn_open():
                return True
        return False

    def _warn_blind(self, resume):
        which = 'resume' if resume else 'cancel'
        aborts_before = self.mon.abort_n
        if not self.warn_open() and not self._open_warn_sheet():
            if not self.export_running():
                self.log('    (export finished before the cancel sheet opened)')
                self.back_to_editor()
                return False
            self.dev.screenshot(os.path.join(self.artifact_dir or '.', 'cancel_sheet_missing.png'))
            raise UIError('could not open the "Cancel Exporting?" sheet (Back and Cancel card both failed)')
        x, y = self._xy(self.WARN_RESUME if resume else self.WARN_CANCEL)
        self.log(f'    sheet open (red Cancel seen) → tapping {which} at ({x}, {y})')
        self.dev.tap(x, y)
        t0 = time.time()
        while time.time() - t0 < 8:
            self.idle(0.5)
            if not resume and self.mon.abort_n > aborts_before:
                self.log(f'    engine abort seen in logcat: yes (MsgAbortExport) after {time.time() - t0:.1f}s')
                self.back_to_editor()
                return True
            if resume and self.warn_open() is False and self.export_running(within=1.5):
                self.log('    sheet closed, export progressing — resumed')
                self.export_wait_done()
                return False
        raise UIError(f'tapped {which} on the cancel sheet but nothing happened (no MsgAbortExport / no progress)')

    def export_running(self, within=4):
        """The export progress ring animates, so uiautomator often can't dump the screen during an
        export. The engine's MsgGetExportingProgress lines in logcat are the reliable signal."""
        q = self.mon.export_quiet_for()
        return q is not None and q < within

    def _tap_warn(self, s, which, attempt=0):
        sel = T.X_WARN_CANCEL if which == 'cancel' else T.X_WARN_RESUME
        n = s.find(sel)
        if n is not None:
            self.dev.tap(*n.center)
            return
        body = s.find(('id:warn_body', 'id:warn_header'))
        if body is None:
            raise UIError('cancel warning: neither buttons nor text visible')
        x = int(self.dev.w * self.WARN_X[0 if which == 'cancel' else 1])
        y = body.b[3] + self.WARN_DY + (0, 40, -40)[attempt % 3]
        self.log(f'    warning buttons hidden → tapping {which} at ({x}, {y})')
        self.dev.tap(x, y)

    # ── lifecycle / system ──
    def background(self, seconds=10, pressure=False):
        self.step(f'background {seconds}s pressure={pressure}')
        self.mon.allow_death = seconds >= 30 or pressure
        self.dev.key('KEYCODE_HOME')
        if pressure:
            self.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
            time.sleep(2)
            self.dev.sh(f'am send-trim-memory {PKG} COMPLETE')
        self.idle(seconds)
        self.dev.launch()
        self.idle(3)
        if self.dev.pid() == '':
            self.log('    app was killed in background (system), reopening')
            self.dev.launch()
            self.idle(3)
        self.open_draft()
        self.mon.allow_death = False

    def kill_bg(self):
        """Home, then the system reclaims the cached app process; the death is expected (not a crash) until the app is
        opened again (ed.dev.launch() / open_draft)."""
        self.step('app to background, process reclaimed by the system')
        self.mon.allow_death = True
        self.dev.kill_bg()

    def trim_memory(self, level=None):
        level = level or self.rng.choice(['RUNNING_LOW', 'RUNNING_CRITICAL', 'UI_HIDDEN', 'MODERATE'])
        self.step(f'trim-memory {level}')
        self.dev.sh(f'am send-trim-memory {PKG} {level}')
        self.idle(0.5)

    def rotate(self, cycles=1):
        self.step(f'rotate x{cycles}')
        acc = self.dev.sh('settings get system accelerometer_rotation').strip() or '1'
        self.dev.sh('settings put system accelerometer_rotation 0')
        try:
            for _ in range(cycles):
                self.dev.sh('settings put system user_rotation 1')
                self.idle(1.5)
                self.dev.sh('settings put system user_rotation 0')
                self.idle(1.5)
        finally:
            self.dev.sh(f'settings put system accelerometer_rotation {acc}')
        self.track = None

    def log_mark(self):
        """Device time now; pass it as since= to wait_log/rotate_when BEFORE the action that will produce the line."""
        return self.dev.sh("date +'%m-%d %H:%M:%S.000'").strip()

    def wait_log(self, pattern, timeout=20, since=None):
        """Event wait: block until a logcat line matches the regex (instead of a fixed sleep). Returns the line, or '' on timeout."""
        t0 = since or self.log_mark()
        end = time.time() + timeout
        while time.time() < end:
            self.mon.check()
            out = self.dev.sh(f"logcat -d -T '{t0}' -e {shlex.quote(pattern)}", timeout=20)
            for line in out.splitlines():
                if 'ZSTRESS' in line or ' adbd ' in line or 'adbd    :' in line:
                    continue              # the harness's own step markers quote the pattern: never match those
                if re.search(pattern, line):
                    return line
            time.sleep(0.2)
        return ''

    def require_log(self, pattern, timeout=20, since=None, why=''):
        """Field precondition/checkpoint: block until a logcat line matches the regex; if it never shows, STOP the run as a
        setup error (UIError), so a run that skipped the field's path never counts as a clean "no crash" run."""
        since = since or self.log_mark()
        line = self.wait_log(pattern, timeout, since)
        if not line:
            # 2026-10-21: a checkpoint gate stopped a run whose main thread was already hung (the ANR came seconds
            # later and landed on the NEXT run). If the lab main-thread watch says main is stuck, let the ANR surface.
            hung = self.wait_log(r'LAB MAINSTACK begin', 1, since)
            if hung:
                self.log(f'    checkpoint /{pattern[:60]}/ not seen, but the main thread is hung: waiting for the ANR')
                self.idle(15)                      # the monitor raises AppFailure (ANR) here if it comes
            raise UIError(f'checkpoint not reached: /{pattern}/ not in the log within {timeout} s' + (f' ({why})' if why else ''))
        return line

    def rotate_when(self, pattern, timeout=30, since=None, back_after=1.5):
        """Real configuration change fired the moment an app log line matches (e.g. MsgAddVideo): lands inside a window a fixed sleep misses."""
        self.step(f'rotate when the log shows /{pattern}/')
        acc = self.dev.sh('settings get system accelerometer_rotation').strip() or '1'
        self.dev.sh('settings put system accelerometer_rotation 0')
        try:
            line = self.wait_log(pattern, timeout, since)
            if not line:
                self.log(f'    /{pattern}/ not seen in {timeout} s: no rotation')
                return ''
            self.dev.sh('settings put system user_rotation 1')
            self.log('    rotated on: ' + line[-140:])
            self.idle(back_after)
            self.dev.sh('settings put system user_rotation 0')
            self.idle(1)
            return line
        finally:
            self.dev.sh(f'settings put system accelerometer_rotation {acc}')
            self.track = None

    def _dka_ui(self, on=True, tries=2):
        # (lab test, not yet in the recipe API) Switch "Don't keep activities" through the Settings app, which is the
        # only path that also tells ActivityManager (setAlwaysFinish). `settings put` alone writes the value but on the
        # lab phone it is not applied. The value is first set to the opposite so the switch shows it, then tapped.
        want = '1' if on else '0'
        w, h = self._screen_size()
        for attempt in range(tries):
            self.dev.sh('settings put global development_settings_enabled 1')
            self.dev.sh(f'settings put global always_finish_activities {1 - int(want)}')
            self.dev.sh('am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS')
            time.sleep(2.5)
            row = None
            for _ in range(30):
                sc = self.ui.dump()
                row = sc.find(('textc:keep activities',)) if sc is not None else None
                if row is not None and row.b[3] < h * 0.92:
                    break
                row = None
                self.dev.swipe(w // 2, int(h * 0.78), w // 2, int(h * 0.38), 250)
                time.sleep(0.6)
            if row is not None:
                self.dev.tap(*row.center)
                time.sleep(1.2)
            ok = self.dev.sh('settings get global always_finish_activities').strip() == want
            self.dev.key('KEYCODE_BACK')
            time.sleep(0.8)
            self.step(f"Don't keep activities {'ON' if on else 'OFF'} via the Settings app: {'ok' if ok else 'FAILED'}"
                      f"{'' if row is not None else ' (row not found)'}")
            if ok:
                return True
        return False

    def dont_keep_activities(self, on=True):
        """'Don't keep activities' via settings put: may NOT take effect on the lab phone, so check wm_on_destroy_called in the log.
        On the Galaxy A51 (Android 13) the value was written but a backgrounded activity only reached onStop. restore_env turns it off."""
        self.step(f"Don't keep activities {'ON' if on else 'OFF'}")
        self.dev.sh(f'settings put global always_finish_activities {1 if on else 0}')

    def screen_off_on(self, off_s=3):
        self.step(f'screen off {off_s}s')
        self.dev.key('KEYCODE_SLEEP')
        self.idle(off_s)
        self.dev.key('KEYCODE_WAKEUP')
        self.idle(1)
        self.dev.sh('wm dismiss-keyguard')
        self.idle(1.5)

    def restart_fresh(self):
        """Save the draft (leave the editor), then a new app process: ANRSan reports each issue once
        per process, so a fresh process gives every scenario its complete report set."""
        self.step('fresh app process')
        tm, t = [], time.time()
        # A system "isn't responding" dialog left by the previous run means that app process is still hung: close the
        # dialog and kill the process FIRST, before any screen read (the screen read would report the old ANR as this
        # run's failure - 2026-10-21: a 20 s 'repro video' of the previous run's dialog).
        if self.dev.clear_system_dialogs():
            self.mon.allow_death = True
            self.dev.force_stop()
            time.sleep(0.5)
            with self.mon.lock:                        # whatever the monitor saw of that old ANR is not this run's
                self.mon.failure = None
            self.dev.sh('logcat -c')
            self.log('    the previous run left the app hung (system dialog on screen): closed it and stopped the app')
        s = self.screen() if self.dev.pid() else None   # app not running (crashed / stopped): nothing to leave, no dump
        tm.append(f'screen {time.time() - t:.1f}'); t = time.time()
        if self.in_editor(s):
            # Leaving the PREVIOUS run's editor belongs to that run, not this one: if the app dies while saving it (e.g.
            # 2026-10-21: DraftManager.saveDraft NPE because Player.saveDraft() returned null after the engine was gone),
            # note it as a separate app bug and do not fail THIS run with it (it failed two fix checks in a row).
            self.mon.allow_death = True
            try:
                self.leave_editor()
            except UIError as e:
                self.log(f'    (could not leave editor cleanly: {e})')
            time.sleep(0.5)
            with self.mon.lock:
                f = self.mon.failure
                if f and f[0] in ('DIED', 'CRASH'):
                    self.mon.failure = None
                    self.mon.notes.append('app died while leaving the previous run\'s editor (not counted for this run; '
                                          'a separate app bug): ' + str(f[1]).strip()[:200])
                    self.log('    the app died while leaving the previous run\'s editor (not this run\'s failure; noted)')
            tm.append(f'leave {time.time() - t:.1f}'); t = time.time()
        self.mon.allow_death = True
        closed = self.dev.clear_system_dialogs()
        if closed:
            self.log(f'    closed {closed} leftover system dialog(s) (isn\'t responding / keeps stopping)')
        self.dev.force_stop()
        self.dev.sh(f'run-as {PKG} sh -c ": > files/anrsan.log"')   # logcat has it all; don't let it grow
        tm.append(f'stop {time.time() - t:.1f}'); t = time.time()
        time.sleep(0.5)
        self.dev.launch()
        tm.append(f'launch {time.time() - t:.1f}'); t = time.time()
        if not self._wait_app_focus(6):                 # event wait (was a fixed 1 s + 4 s)
            if self.dev.clear_system_dialogs():         # a dialog from before stole the focus: close it, launch again
                self.dev.launch()
                self._wait_app_focus(6)
        tm.append(f'focus {time.time() - t:.1f}')
        self.log('    fresh timing: ' + ', '.join(tm))
        self.mon.allow_death = False
        self.track = None

    def _wait_app_focus(self, timeout=6):
        """Return as soon as one of our windows has focus (polled every 0.25 s), plus a short settle; at most timeout."""
        end = time.time() + timeout
        while time.time() < end:
            out = self.dev.sh('dumpsys window | grep -m1 mCurrentFocus', timeout=10)
            if PKG + '/' in out:
                time.sleep(0.8)
                return True
            time.sleep(0.25)
        return False

    def force_stop_reopen(self):
        self.step('force-stop + reopen')
        self.recover()

    # ── keep the test draft pristine across runs ──
    def undo_enabled(self):
        s = self.screen()
        n = s.find(T.UNDO) if s else None
        return None if n is None else bool(n.enabled)

    def reset_edits(self, max_taps=120):
        """Undo until the Undo button reports disabled. History is lost when the editor is
        reopened, so scenarios that reopen can't be fully reset — check_drift() flags that.

        If the scenario made NO edits but Undo is enabled, something in the app pushed an undo
        entry by itself (seen after an export abort: one undo trimmed clip 0 and deleted clip 1).
        That is reported as an app bug and Undo is NOT pressed, so the test draft survives.
        Returns a note string for that case, else None."""
        self.step('reset: undo to start')
        self.set_playing(False)
        self.main_nav()
        if not self.edited:
            if self.undo_enabled():
                self.step('! Undo is enabled although this scenario made no edits — not pressing it')
                if self.artifact_dir:
                    self.dev.screenshot(os.path.join(self.artifact_dir, 'undo_without_edits.png'))
                return ('UNDO_WITHOUT_EDITS: Undo became enabled with no edits made '
                        f'(engine aborts this run: {self.mon.abort_n}) — Undo not pressed')
            return None
        taps = 0
        while taps < max_taps:
            s = self.screen()
            n = s.find(T.UNDO) if s else None
            if n is None or not n.enabled:
                break
            for _ in range(8):
                self.dev.tap(*n.center)
                time.sleep(0.12)
            taps += 8
            self.idle(0.6)
        self.wait_loader()
        return None

    def check_drift(self):
        _, tot = self.read_time()
        if tot is None:
            return None
        if self.baseline_total is None:
            self.baseline_total = tot
            return None
        if abs(tot - self.baseline_total) > max(2.0, 0.15 * self.baseline_total):
            return f'draft length drifted {self.baseline_total:.0f}s → {tot:.0f}s (restore your test draft)'
        return None


# Any of these changes the timeline, so reset_edits() may press Undo afterwards.
def _marks_edit(fn):
    def w(self, *a, **k):
        self.edited = True
        return fn(self, *a, **k)
    w.__name__, w.__doc__ = fn.__name__, fn.__doc__
    return w

for _m in ('split', 'split_at', 'delete_clip', 'duplicate_clip', 'reverse_clip', 'flip_or_rotate',
           'change_speed', 'change_volume', 'undo', 'redo', 'effects_browse', 'add_sticker',
           'add_text', 'tune', 'freeze'):
    if hasattr(Editor, _m):
        setattr(Editor, _m, _marks_edit(getattr(Editor, _m)))


def save_screen_map(path=SCREEN_MAP):
    """Merge the ids this run saw into tools/stress/screen_map.json: {activity: {id: sample text}}. Night Shift's
    repro author reads it, so its scripts use ids that exist on the lab phone instead of guessing from layouts."""
    import json
    if not UI.seen:
        return
    try:
        old = json.load(open(path)) if os.path.exists(path) else {}
    except Exception:
        old = {}
    for act, ids in UI.seen.items():
        cur = old.setdefault(act, {})
        for k, v in ids.items():
            if k not in cur or (v and not cur[k]):
                cur[k] = v
    tmp = path + '.tmp'
    json.dump(old, open(tmp, 'w'), indent=1, sort_keys=True)
    os.replace(tmp, path)


class Recorder:
    """Screen video of one run (adb screenrecord). The phone caps a recording at 3 min, so it records 170 s segments
    in a loop and keeps the last two: the crash is always in them. Used only for the extra video run after a repro."""
    SEG = 170

    def __init__(self, dev):
        self.dev, self.stop_ev, self.segs, self.th = dev, threading.Event(), [], None
        b = dev.base
        self.serial = b[b.index('-s') + 1] if '-s' in b else os.environ.get('ANDROID_SERIAL', '')
        # Emulator: record on the HOST with the emulator console ('emu screenrecord'). It encodes on the Mac, so it does not
        # use the guest's video encoder and cannot change the app's codec timing; the phone keeps adb screenrecord.
        self.host = self.serial.startswith('emulator-')
        if self.host:
            import tempfile
            self.hdir = tempfile.mkdtemp(prefix='ns_rec_')

    def _loop_host(self):
        i = 0
        while not self.stop_ev.is_set():
            name = os.path.join(self.hdir, f'ns_rec_{i % 3}.webm')
            if os.path.exists(name):
                os.remove(name)
            self.segs.append((name, time.time()))
            self.segs = self.segs[-2:]
            self.dev.adb('emu', 'screenrecord', 'start', '--time-limit', str(self.SEG), name, timeout=20)
            t_end = time.time() + self.SEG + 2
            while time.time() < t_end and not self.stop_ev.is_set():
                time.sleep(0.3)
            if not self.stop_ev.is_set():
                self.dev.adb('emu', 'screenrecord', 'stop', timeout=20)
            i += 1

    def _loop(self):
        if self.host:
            return self._loop_host()
        i = 0
        while not self.stop_ev.is_set():
            name = f'/sdcard/ns_rec_{i % 3}.mp4'
            self.segs.append((name, time.time()))
            self.segs = self.segs[-2:]
            self.proc = subprocess.Popen(self.dev.base + ['shell', 'screenrecord', '--bit-rate', '1500000', '--size', '720x1600',
                                                          '--time-limit', str(self.SEG), name],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            while self.proc.poll() is None and not self.stop_ev.is_set():
                time.sleep(0.3)
            i += 1

    def start(self):
        self.dev.sh(('' if self.host else 'rm -f /sdcard/ns_rec_*.mp4; ') + 'settings put system show_touches 1')   # taps show as dots
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()
        time.sleep(1.0)

    def stop(self, keep_dir=None):
        """Stop; with keep_dir, pull the kept segments there and return [(local path, start time)]."""
        self.stop_ev.set()
        if self.host:
            self.dev.adb('emu', 'screenrecord', 'stop', timeout=20)
            if self.th:
                self.th.join(timeout=15)
            time.sleep(2.0)
            out = []
            if keep_dir:
                import shutil
                ff = shutil.which('ffmpeg') or next((c for c in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(c)), None)
                for k, (name, t0) in enumerate(self.segs):
                    if not (os.path.exists(name) and os.path.getsize(name) > 10000):
                        continue
                    dst = os.path.join(keep_dir, f'repro_video_{k + 1}.mp4')
                    if ff:
                        for codec in (['-c:v', 'libx264', '-preset', 'veryfast'], ['-c:v', 'mpeg4', '-q:v', '4']):
                            subprocess.run([ff, '-y', '-loglevel', 'error', '-i', name, *codec, '-pix_fmt', 'yuv420p', '-an', dst],
                                           timeout=300)
                            if os.path.exists(dst) and os.path.getsize(dst) > 10000:
                                break
                    if os.path.exists(dst) and os.path.getsize(dst) > 10000:
                        out.append((dst, t0))
                    else:                                  # no ffmpeg: keep the emulator's webm as it is
                        dst = os.path.join(keep_dir, f'repro_video_{k + 1}.webm')
                        shutil.copy(name, dst)
                        out.append((dst, t0))
            self.dev.sh('settings put system show_touches 0')
            return out
        self.dev.sh('pkill -INT screenrecord')          # SIGINT: screenrecord finishes the mp4 cleanly
        if self.th:
            self.th.join(timeout=15)
        time.sleep(1.5)
        out = []
        if keep_dir:
            for k, (name, t0) in enumerate(self.segs):
                dst = os.path.join(keep_dir, f'repro_video_{k + 1}.mp4')
                self.dev.adb('pull', name, dst, timeout=120)
                if os.path.exists(dst) and os.path.getsize(dst) > 10000:
                    out.append((dst, t0))
        self.dev.sh('rm -f /sdcard/ns_rec_*.mp4; settings put system show_touches 0')
        return out
