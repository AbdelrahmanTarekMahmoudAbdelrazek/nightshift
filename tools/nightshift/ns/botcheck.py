"""Is this crash from real users at all?  (12 Nov, Crashlytics ff832bfc: UCropActivity)

The usual source is Google's own automated testing of each Play release (app review / pre-launch crawlers): it opens
every registered screen cold, on test devices whose profile does not match real hardware.

Two checks, both cheap, run by Start right after the pull and before any lab work:

1. field_bot(events): reports from automated test devices (most likely Google's Play testing) instead of people. Signs, per event:
   - a spoofed device: the model says one phone, the build says another (a "OnePlus8Pro" whose board is the
     Pixel 4a `sunfish`, or whose product is a Huawei `HRY-LX1TRU`);
   - a stack frame that cannot exist on the claimed Android (Dalvik `Method.invokeNative` on Android 5+);
   and for the issue as a whole: many installs, each crashing once, on very few device models.
2. activity_reach(events): the crash is "Unable to start activity <X>" and, in the SHIPPED APK, X is not exported
   and no app code starts it. Then no user tap can open X: whatever opened it was injected (an automated tester,
   e.g. Google's Play testing), and a lab repro that forces X open proves nothing.

Both return {'verdict': 'bot' | 'unreachable' | 'real' | 'unknown', 'why': text, ...}. They only read files.
"""
import collections
import glob
import os
import re
import subprocess

from . import config

GOOGLE_BOARDS = {'sunfish', 'redfin', 'bramble', 'barbet', 'coral', 'flame', 'bonito', 'sargo', 'blueline', 'crosshatch',
                 'oriole', 'raven', 'bluejay', 'panther', 'cheetah', 'lynx', 'tangorpro', 'felix', 'shiba', 'husky',
                 'akita', 'tokay', 'caiman', 'komodo', 'comet', 'tegu', 'walleye', 'taimen', 'marlin', 'sailfish',
                 'goldfish', 'goldfish_arm64', 'ranchu'}
# product / model code families -> maker (only the clear ones; anything else is "can't tell", never "spoofed")
MAKER_CODES = [(r'^(IN|HD|KB|LE|GM|NE|PHB|MT|DN)\d{4}', 'oneplus'), (r'^[A-Z]{3}-(L|AL|TL|LX|N|AN)\w*\d', 'huawei'),
               (r'^SM-[A-Z]\d', 'samsung'), (r'^(M\d{4}|2\d{3}[A-Z0-9]{4,})', 'xiaomi'), (r'^RMX\d', 'realme'),
               (r'^CPH\d', 'oppo'), (r'^V\d{4}', 'vivo'), (r'^Pixel', 'google')]
MAKER_WORDS = {'oneplus': 'oneplus', 'huawei': 'huawei', 'honor': 'huawei', 'samsung': 'samsung', 'xiaomi': 'xiaomi',
               'redmi': 'xiaomi', 'poco': 'xiaomi', 'realme': 'realme', 'oppo': 'oppo', 'vivo': 'vivo', 'google': 'google',
               'pixel': 'google'}


def _maker_of(s):
    s = str(s or '').strip()
    for pat, mk in MAKER_CODES:
        if re.match(pat, s):
            return mk
    low = s.lower()
    return next((mk for w, mk in MAKER_WORDS.items() if low.startswith(w)), '')


def _os_major(e):
    m = re.search(r'(\d+)', str((e.get('operatingSystem') or {}).get('displayVersion') or ''))
    return int(m.group(1)) if m else 0


def _frames(e):
    return [f for ex in (e.get('exceptions') or []) for f in (ex.get('frames') or [])] + \
           [f for t in (e.get('threads') or []) if t.get('crashed') for f in (t.get('frames') or [])]


def event_signs(e):
    """The bot signs one event shows (empty list = looks like a real phone)."""
    signs = []
    dev = e.get('device') or {}
    ck = e.get('customKeys') or {}
    model, maker = str(dev.get('model') or ''), str(dev.get('manufacturer') or '')
    want = _maker_of(maker) or _maker_of(model)
    hw, prod = str(ck.get('hw') or '').lower(), str(ck.get('product') or '')
    if hw in GOOGLE_BOARDS and want and want != 'google':
        signs.append(f'{model} says {want} but runs on the Google board "{hw}" (a test device, not a real {want} phone)')
    pm = _maker_of(prod)
    if pm and want and pm != want:
        signs.append(f'{model} ({want}) reports the {pm} product code "{prod}"')
    fp = str(ck.get('fingerprint') or '')
    fpm = _maker_of(fp.split('/')[0]) if fp else ''
    if fpm and want and fpm != want:
        signs.append(f'build fingerprint is from {fpm}, device says {want}')
    if _os_major(e) >= 5 and any('invokeNative' in str(f.get('symbol') or '') for f in _frames(e)):
        signs.append(f'Dalvik frame Method.invokeNative on Android {_os_major(e)} (it does not exist after Android 4.4)')
    return signs


def field_bot(events, min_events=8, share=0.8):
    evs = [e for e in (events or []) if isinstance(e, dict)]
    if len(evs) < min_events:
        return {'verdict': 'unknown', 'why': f'only {len(evs)} reports: too few to judge'}
    marked = [(e, event_signs(e)) for e in evs]
    bad = [s for _, s in marked if s]
    models = collections.Counter(str((e.get('device') or {}).get('model') or '?') for e in evs)
    installs = collections.Counter(str(e.get('installationUuid') or '') for e in evs if e.get('installationUuid'))
    once = sum(1 for n in installs.values() if n == 1) / max(1, len(installs))
    few_models = len(models) <= 3 and len(evs) >= 10
    frac = len(bad) / len(evs)
    sign_count = collections.Counter(re.sub(r'"[^"]*"|\b\w+\d\w*\b', '…', s) for ss in bad for s in ss)
    top = [s for s, _ in sign_count.most_common(3)]
    example = next((ss for ss in bad), [])
    res = {'n': len(evs), 'flagged': len(bad), 'share': round(frac, 2), 'models': dict(models.most_common(5)),
           'installs': len(installs), 'once_per_install': round(once, 2), 'signs': example[:3], 'kinds': top}
    if frac >= share and (few_models or once >= 0.8):
        res['verdict'] = 'bot'
        res['why'] = (f'{len(bad)} of {len(evs)} reports come from test devices whose profile does not match the hardware ({"; ".join(example[:2])}); '
                      f'{len(models)} model(s) only ({", ".join(models)}), {round(once * 100)}% of installs crash once. '
                      f'These look like automated test devices (most likely Google testing the Play release), not people using the app')
    else:
        res['verdict'] = 'real' if frac < 0.3 else 'unknown'
        res['why'] = f'{len(bad)} of {len(evs)} reports look spoofed'
    return res


# ---------------------------------------------------------------- 2. can a user open the crashing screen at all?
def crashed_activity(events):
    for e in events or []:
        for ex in e.get('exceptions') or []:
            m = re.search(r'Unable to start activity ComponentInfo\{[\w.]+/([\w.$]+)\}',
                          str(ex.get('exceptionMessage') or ex.get('subtitle') or ''))
            if m:
                return m.group(1), str((e.get('version') or {}).get('buildVersion') or '')
    return None, None


def _tool(name):
    sdk = config.android_sdk()
    c = sorted(glob.glob(os.path.join(sdk, 'build-tools', '*', name)))
    return c[-1] if c else None


def manifest_entry(apk, cls):
    """(declared, exported) for activity cls in the APK's manifest, via aapt2. None when aapt2 is missing."""
    aapt = _tool('aapt2')
    if not aapt:
        return None
    out = subprocess.run([aapt, 'dump', 'xmltree', '--file', 'AndroidManifest.xml', apk], capture_output=True,
                         text=True, timeout=120).stdout
    blocks = re.split(r'\n\s*E: (?=activity|activity-alias|service|receiver|provider)', out)
    for b in blocks:
        if not b.startswith('activity'):
            continue
        name = re.search(r'android:name\(0x01010003\)="([^"]+)"', b)
        if not name or name.group(1) != cls:
            continue
        exp = re.search(r'android:exported\(0x01010010\)=\(type 0x12\)(0x\w+)', b)
        has_filter = 'E: intent-filter' in b
        exported = (exp.group(1) != '0x0') if exp else has_filter
        return True, exported
    return False, False


def code_launchers(apk, cls, limit=40):
    """Methods outside cls that name it, and whether they (or the methods calling them) start an activity.
    dexdump on the dex files that mention cls. Returns {'refs': [...], 'starts': [...]} or None (no dexdump)."""
    import zipfile
    dexdump = _tool('dexdump')
    if not dexdump:
        return None
    desc = 'L' + cls.replace('.', '/') + ';'
    own = desc[:-1]
    refs, starts = [], []
    tmp = os.path.join(config.REPO, 'tools/nightshift/out/botcheck_dex')
    os.makedirs(tmp, exist_ok=True)
    with zipfile.ZipFile(apk) as z:
        for n in [n for n in z.namelist() if re.match(r'classes\d*\.dex$', n)]:
            raw = z.read(n)
            if desc.encode() not in raw:
                continue
            p = os.path.join(tmp, n)
            open(p, 'wb').write(raw)
            proc = subprocess.Popen([dexdump, '-d', p], stdout=subprocess.PIPE, text=True, errors='replace')
            meth, body_ref, body_start = '', False, False

            def flush():
                if meth and body_ref and not meth.startswith(own):
                    refs.append(meth)
                    if body_start:
                        starts.append(meth)
            for line in proc.stdout:
                m = re.match(r'[0-9a-f]{6}:\s+\|\[[0-9a-f]+\] (\S+)', line)
                if m:
                    flush()
                    meth, body_ref, body_start = m.group(1), False, False
                    continue
                if desc in line and ('const-class' in line or 'new-instance' in line or 'invoke' in line):
                    body_ref = True
                if re.search(r'startActivit(y|yForResult|ies)\b|ActivityResultLauncher;\.launch', line):
                    body_start = True
            flush()
            proc.wait()
            try:
                os.remove(p)
            except OSError:
                pass
    return {'refs': refs[:limit], 'starts': starts[:limit]}


def activity_reach(events, log=print):
    cls, vc = crashed_activity(events)
    if not cls:
        return {'verdict': 'unknown', 'why': 'not an activity-launch crash'}
    try:
        from . import apkjava
        apk = apkjava.find_apk(vc)
    except Exception:
        apk = None
    if not apk:
        return {'verdict': 'unknown', 'activity': cls,
                'why': f'shipped APK {vc} not on this Mac (put {vc}.apk in Downloads to check who can open {cls.split(".")[-1]})'}
    try:
        me = manifest_entry(apk, cls)
        code = code_launchers(apk, cls)
    except Exception as e:
        return {'verdict': 'unknown', 'activity': cls, 'why': f'APK check failed: {str(e)[:150]}'}
    if me is None or code is None:
        return {'verdict': 'unknown', 'activity': cls, 'why': 'aapt2 / dexdump not found in the Android SDK build-tools'}
    declared, exported = me
    res = {'activity': cls, 'apk': os.path.basename(apk), 'declared': declared, 'exported': exported,
           'refs': code['refs'][:8], 'starts': code['starts'][:8]}
    short = cls.split('.')[-1]
    if exported:
        res.update(verdict='real', why=f'{short} is exported: other apps and links can open it')
    elif code['starts']:
        res.update(verdict='real', why=f'{short} is started from app code: {", ".join(code["starts"][:3])}')
    elif code['refs']:
        # named, but the method that names it starts nothing itself: one level up is checked by the reader (log)
        res.update(verdict='unreachable?', why=f'{short} is not exported and the code that names it ({", ".join(code["refs"][:3])}) '
                                              f'starts no activity: likely only used for its intent extras')
    else:
        res.update(verdict='unreachable', why=f'{short} is {"declared" if declared else "NOT declared"} in the manifest, not '
                                              f'exported, and no app code starts it: no user tap can open it')
    return res


def judge(events, log=print):
    """Both checks; the overall call Start acts on."""
    fb = field_bot(events)
    try:
        ar = activity_reach(events, log)
    except Exception as e:
        ar = {'verdict': 'unknown', 'why': str(e)[:150]}
    stop = (fb['verdict'] == 'bot' or ar['verdict'] == 'unreachable'
            or (ar['verdict'] == 'unreachable?' and fb.get('share', 0) >= 0.5))
    return {'stop': stop, 'bot': fb, 'reach': ar,
            'summary': ' · '.join(x['why'] for x in (fb, ar) if x.get('verdict') not in ('unknown',))}
