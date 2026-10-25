"""Play build or debug build (25 Oct). Some crashes live in parts of the app that only the full app has (templates,
photo editor, tasks, slideshow...): the debug build Night Shift compiles from video_gles3jni cannot show them. Those
are reproduced on the Play internal-test build, installed from the Play Store on the lab phone.

How a crash is sorted, no list to keep up to date:
  1. code check: every frame of OUR code (profile.code_packages) is looked up in the checkout and its modules; a
     class whose package is not there at all -> Play build.
  2. screen check: the last screens Crashlytics recorded (Activities/Fragments) that are not in the checkout -> Play build.
  3. a choice made on the board (case.buildMode = 'play' | 'debug') always wins and is remembered for that package
     (knowledge/build_modes.json), so similar crashes go the same way next time.
"""
import json
import os
import re
import subprocess
import time

from . import config

IDX = os.path.join(config.REPO, 'tools/nightshift/out', 'class_index.json')
LEARNED = os.path.join(config.REPO, 'tools/nightshift/knowledge', 'build_modes.json')
SKIP = {'build', '.git', '.gradle', 'node_modules', 'intermediates', 'generated', 'tools', 'out', 'ios', 'Pods'}
RE_CLS = re.compile(r'\b((?:[a-z][a-z0-9_]*\.){2,}[A-Z][A-Za-z0-9_$]*)')


def _packages(cfg):
    return [p.strip() for p in str(((cfg or {}).get('profile') or {}).get('code_packages') or 'com.myzesty.').split(',') if p.strip()]


def index(max_age=6 * 3600, root_dir=None, cache=None):
    """{package dirs: [...], classes: [...]} of every .kt/.java under the checkout (cached for 6 h)."""
    root_dir, cache = root_dir or config.REPO, cache or IDX
    try:
        if time.time() - os.path.getmtime(cache) < max_age:
            return json.load(open(cache))
    except (OSError, ValueError):
        pass
    pk, cl = set(), set()
    for root, dirs, files in os.walk(root_dir, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.')]
        m = re.search(r'/src/[^/]+/(?:java|kotlin)/(.+)$', root)
        if not m:
            continue
        pkg = m.group(1).replace('/', '.')
        src = [f for f in files if f.endswith(('.kt', '.java'))]
        if src:
            pk.add(pkg)
            cl.update(f'{pkg}.{os.path.splitext(f)[0]}' for f in src)
    out = {'packages': sorted(pk), 'classes': sorted(cl), 'at': time.time()}
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        json.dump(out, open(cache, 'w'))
    except OSError:
        pass
    return out


def _ours(text, pk):
    """Our classes named in a stack/title text: 'com.ai.myzesty.templates.X.method' -> 'com.ai.myzesty.templates.X'."""
    out = []
    for m in RE_CLS.finditer(str(text or '')):
        c = m.group(1).split('$')[0]
        if any(c.startswith(p) or ('.' + p) in ('.' + c) for p in pk) or '.myzesty.' in c:
            if c not in out:
                out.append(c)
    return out


def missing(cls, idx):
    """True when the class's package is not in the checkout at all (no source folder for it in any module)."""
    pkg = cls.rsplit('.', 1)[0]
    pks = idx.get('packages') or []
    return not (pkg in pks or any(p.startswith(pkg + '.') for p in pks))


def _learned():
    try:
        return json.load(open(LEARNED))
    except (OSError, ValueError):
        return {}


def remember(case_id, mode, classes):
    """A board choice for one crash also sorts later crashes of the same packages."""
    d = _learned()
    for c in classes:
        d[c.rsplit('.', 1)[0]] = {'mode': mode, 'from': case_id, 'at': time.strftime('%Y-%m-%d')}
    try:
        os.makedirs(os.path.dirname(LEARNED), exist_ok=True)
        json.dump(d, open(LEARNED, 'w'), indent=1, sort_keys=True)
    except OSError:
        pass


def decide(case, merged, cfg):
    """-> {'mode': 'debug'|'fullsrc'|'play', 'why': str, 'classes': [...]}. A full-app crash is built from source when
    this computer has a myzesty_mobile checkout (fullsrc, fix verified), else the real app from Google (play)."""
    d = _decide(case, merged, cfg)
    if d['mode'] == 'play':
        from . import fulllab
        src = fulllab.checkout(cfg)
        if src:
            d = {**d, 'mode': 'fullsrc', 'why': d['why'] + f'; built from your myzesty_mobile ({src})'}
    return d


def _decide(case, merged, cfg):
    pk = _packages(cfg)
    texts = [case.get('title'), case.get('subtitle'), case.get('stack')]
    for f in case.get('frames') or []:
        texts.append(f.get('func') if isinstance(f, dict) else f)
    fb, pl = (merged or {}).get('fb') or {}, (merged or {}).get('play') or {}
    texts += list(fb.get('top') or []) + list(fb.get('java') or []) + [fb.get('title'), pl.get('stack'), pl.get('cause')]
    classes = []
    for t in texts:
        for c in _ours(t, pk):
            if c not in classes:
                classes.append(c)
    screens = []
    for s in (case.get('last_screens') or []):
        s = s if isinstance(s, str) else (s.get('screen') or s.get('name') or '')
        screens += [c for c in _ours(s, pk) if c not in screens]
    chosen = str(case.get('buildMode') or '').lower()
    if chosen in ('play', 'debug'):
        return {'mode': chosen, 'why': 'chosen on the board', 'classes': classes}
    lr = _learned()
    for c in classes + screens:
        p = c.rsplit('.', 1)[0]
        hit = next((v for k, v in lr.items() if p == k or p.startswith(k + '.')), None)
        if hit:
            return {'mode': hit['mode'], 'why': f'{p} was set to the {hit["mode"]} build on the board (crash {hit["from"][:12]})', 'classes': classes}
    idx = index()
    gone = [c for c in classes if missing(c, idx)]
    if gone:
        return {'mode': 'play', 'why': f'{gone[0].split(".")[-1]} ({gone[0].rsplit(".", 1)[0]}) is not in video_gles3jni: only the full Play app has it',
                'classes': classes}
    gone = [c for c in screens if missing(c, idx)]
    if gone:
        return {'mode': 'play', 'why': f'the crash happened after the screen {gone[0].split(".")[-1]}, which only the full Play app has',
                'classes': classes}
    return {'mode': 'debug', 'why': 'all of its code is in video_gles3jni', 'classes': classes}


# ------------------------------------------------------------------ the Play build on the lab phone

def _sh(*a, timeout=60):
    r = subprocess.run(['adb', *a], capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def installed(pkg):
    """-> {'installed', 'play' (installed by the Play Store, not debuggable), 'version'}"""
    d = _sh('shell', 'dumpsys', 'package', pkg, timeout=60)
    if f'Package [{pkg}]' not in d:
        return {'installed': False, 'play': False, 'version': ''}
    inst = re.search(r'installerPackageName=(\S+)', d)
    ver = re.search(r'versionCode=(\d+)', d)
    flags = re.search(r'pkgFlags=\[([^\]]*)\]', d)
    debuggable = 'DEBUGGABLE' in (flags.group(1) if flags else '')
    return {'installed': True, 'play': bool(inst and inst.group(1) == 'com.android.vending') and not debuggable,
            'version': ver.group(1) if ver else ''}


def _tap_play_button():
    """Tap Install / Update on the Play Store page if it is showing (uiautomator dump of the screen)."""
    _sh('shell', 'uiautomator', 'dump', '/sdcard/ns_ui.xml', timeout=30)
    x = _sh('shell', 'cat', '/sdcard/ns_ui.xml', timeout=30)
    for label in ('Update', 'Install', 'تحديث', 'تثبيت'):
        m = re.search(r'text="' + re.escape(label) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x) or \
            re.search(r'content-desc="' + re.escape(label) + r'"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x)
        if m:
            a, b, c, d = map(int, m.groups())
            _sh('shell', 'input', 'tap', str((a + c) // 2), str((b + d) // 2))
            return label
    return None


def ensure_play_build(pkg, log=print, wait_min=15):
    """The Play internal-test build on the lab phone. A debug build is signed differently, so it is uninstalled first
    (this clears the app's data on the LAB phone). Then the Play Store page opens and Install/Update is tapped."""
    st = installed(pkg)
    if st['play']:
        log(f'lab phone: the Play build is installed (version {st["version"]})')
    else:
        if st['installed']:
            log('lab phone: it has the debug build; uninstalling it so the Play build can install (clears the app data on the lab phone)')
            _sh('uninstall', pkg, timeout=120)
        log('lab phone: opening the app in the Play Store (the phone\'s Google account must be an internal tester)')
    _sh('shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', f'market://details?id={pkg}', timeout=30)
    t0, tapped = time.time(), None
    while time.time() - t0 < wait_min * 60:
        time.sleep(6)
        now = installed(pkg)
        if now['play'] and (not st['play'] or now['version'] != st['version'] or tapped is None and time.time() - t0 > 20):
            if now['version'] == st['version'] and st['play']:
                log('lab phone: the Play build is already the newest one')
            else:
                log(f'lab phone: Play build {now["version"]} installed')
            _sh('shell', 'input', 'keyevent', 'KEYCODE_HOME')
            return now
        if not tapped or time.time() - t0 > 60 and int(time.time() - t0) % 60 < 7:
            tapped = _tap_play_button() or tapped
            if tapped:
                log(f'lab phone: tapped "{tapped}" in the Play Store; waiting for the download')
    raise RuntimeError('the Play build did not install in 15 min: on the lab phone open the Play Store, check the Google '
                       'account is an internal tester of MyZesty and tap Install, then press Start again')


# ------------------------------------------------------------------ the exact field build from Google (26 Oct)

APKS = os.path.expanduser('~/.nightshift_apks')     # downloaded signed universal APKs, one per build (outside the repo)


def field_build(case, merged=None):
    """The build the crash came from: the case's build with the most events ('1.25.1 (800054871)' -> '800054871')."""
    vers = case.get('versions') or case.get('sync_versions') or {}
    best = max(((k, v) for k, v in vers.items() if re.search(r'\d{6,}', k)), key=lambda kv: kv[1] or 0, default=(None, 0))[0]
    if not best:
        pb = (merged or {}).get('perBuild') or {}
        best = max(pb, key=lambda b: (pb[b].get('fb') or 0) + (pb[b].get('play') or 0), default=None)
    m = re.search(r'(\d{6,})', str(best or ''))
    return m.group(1) if m else None


def download_apk(cfg, vc, log=print):
    """The signed universal APK of build vc (Play Console > App bundle explorer > Downloads, through the Play API).
    Kept in ~/.nightshift_apks/ so each build is downloaded once."""
    from . import symbols_auto as sa
    import urllib.parse
    os.makedirs(APKS, exist_ok=True)
    dst = os.path.join(APKS, f'{vc}-universal.apk')
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
        return dst
    pkg = cfg['app']['package']
    tok = sa._token()
    gen = sa._get(f'{sa.API}/applications/{pkg}/generatedApks/{vc}', tok)
    did = next(((g.get('generatedUniversalApk') or {}).get('downloadId') for g in gen.get('generatedApks', []) or []
                if (g.get('generatedUniversalApk') or {}).get('downloadId')), None)
    if not did:
        raise RuntimeError(f'Google Play has no universal APK for build {vc}')
    log(f'lab phone: downloading the real app of build {vc} from Google Play (once; about 300 MB)')
    url = f'{sa.API}/applications/{pkg}/generatedApks/{vc}/downloads/{urllib.parse.quote(did, safe="")}:download?alt=media'
    r = sa._get(url, tok, raw=True)
    with open(dst + '.part', 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(dst + '.part', dst)
    return dst


def ensure_exact_build(cfg, vc, log=print):
    """The real app of build vc on the lab phone. Another build (our debug build, or a newer/older real one) is
    uninstalled first: different signature or a downgrade (clears the app data on the LAB phone)."""
    pkg = cfg['app']['package']
    st = installed(pkg)
    d = _sh('shell', 'dumpsys', 'package', pkg, timeout=60)
    debuggable = 'DEBUGGABLE' in ''.join(re.findall(r'pkgFlags=\[([^\]]*)\]', d))
    if st['installed'] and st['version'] == str(vc) and not debuggable:
        log(f'lab phone: the real app of build {vc} is installed')
        return st
    apk = download_apk(cfg, vc, log)
    if st['installed']:
        log(f"lab phone: it has {'our debug build' if debuggable else 'build ' + st['version']}; uninstalling it for build {vc} "
            '(clears the app data on the lab phone)')
        _sh('uninstall', pkg, timeout=120)
    out = _sh('install', apk, timeout=900)
    if 'Success' not in out:
        raise RuntimeError(f'the real app of build {vc} did not install: {" ".join(out.split())[-200:]}')
    log(f'lab phone: real app of build {vc} installed (exactly what users have)')
    return installed(pkg)
