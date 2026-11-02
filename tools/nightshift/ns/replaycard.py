"""Engine repro card (28 Oct): everything the board's "Engine repro" panel shows, saved on cases/<id>.engineReplay.
  - steps: the engine calls the replay script sent, in order, with each call's result (from the run's steps.log),
  - script: the replay scenario (Python) with its explanation,
  - stack: the lab crash backtrace (tombstone) with file:line from the lab build's unstripped engine library,
    next to the field frames it had to match.
No AI. Called by replay.py on a hit; `python3 tools/nightshift/replaycard.py <case id>` fills it for an older hit."""
import glob
import gzip
import json
import os
import re
import subprocess

from . import config

AUTO = os.path.join(config.REPO, 'tools', 'stress', 'auto')


def _logcat(d):
    for n in ('logcat.txt', 'logcat.txt.gz'):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            try:
                return (gzip.open(p, 'rt', errors='replace') if n.endswith('.gz') else open(p, errors='replace')).read()
            except OSError:
                pass
    return ''


def _steps(d):
    p = os.path.join(d, 'steps.log')
    if not os.path.isfile(p):
        return []
    out, seen = [], set()
    for l in open(p, errors='replace'):
        l = l.rstrip()
        m = re.match(r'(\d\d:\d\d:\d\d)\s+(.*)$', l)
        if not m:
            continue
        t, txt = m.groups()
        txt = txt.strip()
        if txt.startswith('· engine replay:'):
            out.append({'t': t, 'kind': 'send', 'text': txt.split(':', 1)[1].strip()})
        elif re.match(r'^\w+\(.*\) -> ', txt):
            if txt not in seen:                      # the lab prints the results so far after every call: keep each once
                seen.add(txt)
                out.append({'t': t, 'kind': 'result', 'text': txt})
        elif txt.startswith(('✖', 'FAIL', '■', '· open draft', '· fresh app')) or 'CRASH' in txt:
            out.append({'t': t, 'kind': 'crash' if ('CRASH' in txt or txt.startswith('✖')) else 'info', 'text': txt[:300]})
    return out[:80]


def _bid(path):
    try:
        from . import symbolize
        cls = next(getattr(symbolize, n) for n in dir(symbolize) if isinstance(getattr(symbolize, n), type)
                   and hasattr(getattr(symbolize, n), 'build_id'))
        return (cls(path).build_id() or '').lower()
    except Exception:
        return ''


def _lib(want_bid=''):
    """The lab build's unstripped engine library whose BuildId is the crashed one (else None: no file:line rather
    than wrong lines from another build). Also kept per BuildId under out/replay/libs/ so later cards still match."""
    pats = ['app/build/intermediates/merged_native_libs/*/out/lib/arm64-v8a/libMYJNILIB26.so',
            'app/build/intermediates/merged_native_libs/*/*/out/lib/arm64-v8a/libMYJNILIB26.so',
            'app/build/intermediates/cxx/*/*/obj/arm64-v8a/libMYJNILIB26.so',
            'app/build/intermediates/cxx/*/obj/arm64-v8a/libMYJNILIB26.so']
    hits = []
    for root in {config.LAB, config.REPO}:
        for p in pats:
            hits += glob.glob(os.path.join(root, p))
    keep = os.path.join(config.REPO, 'tools/nightshift/out/replay/libs')
    if want_bid and os.path.isfile(os.path.join(keep, want_bid + '.so')):
        return os.path.join(keep, want_bid + '.so')
    for h in sorted(hits, key=os.path.getmtime, reverse=True):
        if not want_bid or _bid(h) == want_bid:
            if want_bid:
                try:
                    import shutil
                    os.makedirs(keep, exist_ok=True)
                    shutil.copyfile(h, os.path.join(keep, want_bid + '.so'))
                except OSError:
                    pass
            return h
    return None


def _a2l():
    try:
        from . import symbolize
        return symbolize._addr2line()
    except Exception:
        return None


def stack(d, field_top=None):
    txt = _logcat(d)
    sig = next((l.split(' F libc    : ', 1)[1].strip() for l in txt.splitlines() if ' F libc    : Fatal signal' in l), '')
    cause = next((l.split('F DEBUG   : ', 1)[1].strip() for l in txt.splitlines() if 'F DEBUG   : Cause:' in l), '')
    frames = []
    for l in txt.splitlines():
        m = re.search(r' F DEBUG   : +#(\d+) pc ([0-9a-f]+) +(\S+)(.*)$', l)
        if not m:
            continue
        n, pc, lib, rest = m.groups()
        rest = re.sub(r'\(offset 0x[0-9a-f]+\)|\(BuildId: \w+\)', '', rest).strip()
        fn = rest[1:-1] if rest.startswith('(') and rest.endswith(')') else ''
        frames.append({'n': int(n), 'pc': pc, 'lib': lib.split('!')[-1].split('/')[-1], 'func': re.sub(r'\+\d+$', '', fn or ''),
                       'srcline': ''})
        if len(frames) >= 30:
            break
    bid = (re.search(r'libMYJNILIB26\.so.*?\(BuildId: (\w+)\)', txt) or [None, ''])[1].lower()
    lib, a2l = _lib(bid), _a2l()
    eng = [f for f in frames if f['lib'] == 'libMYJNILIB26.so']
    if lib and a2l and eng:
        for f in eng:                               # -i: inlined frames too; keep the first line in OUR code (not libc++)
            try:
                r = subprocess.run([a2l, '-f', '-C', '-i', '-e', lib, '0x' + f['pc']], capture_output=True, text=True, timeout=30)
            except (subprocess.TimeoutExpired, OSError):
                continue
            ls = [x.strip() for x in r.stdout.splitlines()]
            pairs = list(zip(ls[0::2], ls[1::2]))
            ours = [(fn, src) for fn, src in pairs if '/app/src/main/cpp/' in src]
            if ours:
                fn, src = ours[0]
                f['srcline'] = re.sub(r'^.*?/app/src/main/cpp/', '', src).split(' (')[0]
                if not f['func'] and fn != '??':
                    f['func'] = fn
    return {'signal': sig[:240], 'cause': cause[:200], 'frames': frames, 'field': list(field_top or [])[:12]}


def script(scenario):
    for p in sorted(glob.glob(os.path.join(AUTO, '*_replay*.py')), key=os.path.getmtime, reverse=True):
        src = open(p, errors='replace').read()
        m = re.search(r'(?ms)^(@scenario[^\n]*\n)?def ' + re.escape(scenario) + r'\(.*?(?=^@scenario|^def |\Z)', src)
        if m:
            code = m.group(0).rstrip()
            doc = (re.search(r'"""(.*?)"""', code, re.S) or [None, ''])[1].strip()
            return {'file': os.path.relpath(p, config.REPO), 'code': code[:6000], 'doc': doc[:600]}
    return {}


def card(rp, field_top=None):
    d = os.path.join(config.REPO, rp.get('dir') or '')
    out = {'steps': _steps(d), 'stack': stack(d, field_top), 'script': script(rp.get('scenario') or '')}
    shot = os.path.join(d, 'fail.png')
    out['screenshot'] = os.path.relpath(shot, config.REPO) if os.path.isfile(shot) else ''
    return out


def save(db, cid, rp, field_top=None, log=print):
    c = card(rp, field_top)
    rp2 = dict(rp, **c)
    try:
        db.collection('cases').document(cid).set({'engineReplay': json.loads(json.dumps(rp2, default=str))}, merge=True)
        log(f'engine repro card: {len(c["steps"])} steps, {len(c["stack"]["frames"])} crash frames'
            + (f' ({sum(1 for f in c["stack"]["frames"] if f["srcline"])} with file:line)' if c['stack']['frames'] else ''))
    except Exception as e:
        log(f'engine repro card not saved: {str(e)[:160]}')
    return rp2


if __name__ == '__main__':
    import sys
    import warnings
    warnings.filterwarnings('ignore')
    from . import fire
    db = fire.client()
    rdir = os.path.join(config.REPO, 'tools/nightshift/out/replay')
    ids = ([os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(rdir, '*.json')))] if sys.argv[1:] == ['--all']
           else [a.strip() for a in sys.argv[1:]])
    for cid in ids:                               # every engine replay hit so far (or the ones named)
        rp = json.load(open(os.path.join(rdir, f'{cid}.json')))
        m = {}
        for p_ in ('m-', 'm-play-'):
            m = db.collection('merged').document(p_ + cid).get().to_dict() or {}
            if m:
                break
        print(cid[:12], end=': ')
        save(db, cid, rp, ((m.get('fb') or {}).get('top') or []))
