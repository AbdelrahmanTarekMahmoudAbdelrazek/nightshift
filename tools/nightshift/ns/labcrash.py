"""Lab crash evidence for the crash window: the native crash dump of a lab run, parsed and symbolized against the
EXACT build that ran on the phone (matched by GNU BuildId), and the repro video published to the board.

    lab = parse(run_dir)            # signal, cause, fault addr, device, app, frames [{n, pc, lib, func, off, buildId}]
    symbolize(lab)                  # fills func / src (file:line) for our library from the local unstripped .so
    publish_video(case_id, mp4)     # -> {'url', 'vtt', 'steps'} served by Firebase Hosting (board/public/v/<token>/)
"""
import glob
import hashlib
import os
import re
import shutil
import struct
import subprocess

from . import config, symbolize as sym

FRAME = re.compile(r'#(\d+)\s+pc\s+([0-9a-f]+)\s+(\S+?)(?:\s+\((.+?)\))?(?:\s+\(BuildId:\s*([0-9a-f]+)\))?\s*$')


def parse(run_dir):
    """The native crash of a lab run (dropbox data_app_native_crash / tombstone text). None when there is none."""
    txt = ''
    for fn in ('data_app_native_crash.txt', 'tombstone.txt'):
        p = os.path.join(run_dir, fn)
        if os.path.exists(p):
            txt = open(p, errors='replace').read()
            break
    if not txt:
        return None
    g = lambda rx: (re.search(rx, txt, re.M) or [None, ''])[1].strip()
    out = {'signal': g(r'^signal (.+?), fault addr'), 'fault': g(r'fault addr (0x[0-9a-f]+)'), 'cause': g(r'^Cause: (.+)$'),
           'device': g(r"^Build fingerprint: '([^/']+/[^/']+)"), 'app': g(r'^Package: (.+)$'), 'time': g(r'^Timestamp: (.+)$'),
           'thread': g(r'^pid: .*?name: (\S+)'), 'frames': []}
    for ln in txt.split('backtrace:', 1)[-1].splitlines():
        m = FRAME.search(ln.strip())
        if not m:
            if out['frames'] and ln.strip() and not ln.startswith(' '):
                break
            continue
        n, pc, path, sym_off, bid = m.groups()
        if sym_off and sym_off.startswith('BuildId:'):          # '(BuildId: x)' alone: no symbol on this frame
            bid, sym_off = sym_off.split(':', 1)[1].strip(), None
        lib = path.split('!', 1)[1] if '!' in path else os.path.basename(path)
        func, off = '', None
        if sym_off:
            mm = re.match(r'(.+)\+(\d+)$', sym_off)
            func, off = (mm.group(1), int(mm.group(2))) if mm else (sym_off, None)
        out['frames'].append({'n': int(n), 'pc': pc, 'lib': lib, 'func': func, 'off': off, 'buildId': bid or ''})
    out['buildId'] = next((f['buildId'] for f in out['frames'] if f['lib'].startswith('libMYJNILIB26') and f['buildId']), '')
    return out


def build_id(path):
    """GNU build-id of an ELF file (the .note.gnu.build-id descriptor), hex."""
    try:
        data = open(path, 'rb').read()
    except OSError:
        return ''
    i = data.find(struct.pack('<III', 4, 20, 3) + b'GNU\x00')
    return data[i + 16:i + 36].hex() if i >= 0 else ''


def find_lib(bid, lib='libMYJNILIB26.so'):
    """The unstripped library of the build that ran on the phone (local build outputs), matched by BuildId."""
    pats = [f'app/build/intermediates/cxx/*/*/obj/arm64-v8a/{lib}',
            f'app/build/intermediates/merged_native_libs/*/*/out/lib/arm64-v8a/{lib}']
    cands = sorted({p for pat in pats for p in glob.glob(os.path.join(config.REPO, pat))}, key=os.path.getmtime, reverse=True)
    for p in cands:
        if build_id(p) == bid:
            return p
    return None


def symbolize(lab):
    """Function + file:line for every frame in our library, from the matching local .so (no guessing by version)."""
    if not lab or not lab.get('buildId'):
        return lab
    so = find_lib(lab['buildId'])
    a2l = sym._addr2line()
    lab['symbols'] = {'buildId': lab['buildId'], 'lib': os.path.relpath(so, config.REPO) if so else None,
                      'tool': os.path.basename(a2l) if a2l else None}
    if not so or not a2l:
        return lab
    ours = [f for f in lab['frames'] if f['lib'].startswith('libMYJNILIB26')]
    try:
        # -i: the whole inline chain per address. Its LAST entry is the real (outermost) function, the one the field
        # stack names; the first entry inside our own sources (app/src/...) is the most useful file:line.
        res = subprocess.run([a2l, '-a', '-C', '-f', '-i', '-e', so] + ['0x' + f['pc'] for f in ours], capture_output=True, text=True, timeout=60)
        chains, cur = [], None
        rows = res.stdout.splitlines()
        k = 0
        while k < len(rows):
            if rows[k].startswith('0x'):
                cur = []
                chains.append(cur)
                k += 1
                continue
            if cur is not None and k + 1 < len(rows):
                cur.append((rows[k].strip(), re.sub(r' \(discriminator \d+\)', '', rows[k + 1].strip())))
            k += 2
        for f, ch in zip(ours, chains):
            ch = [(fn, src) for fn, src in ch if fn and fn != '??']
            if not ch:
                continue
            if not f['func']:
                f['func'] = ch[-1][0]
            mine = [src for _, src in ch if '/app/src/' in src or src.startswith('app/src/')]
            if mine:
                f['src'] = re.sub(r'^.*?(app/src/)', r'\1', mine[0])
            if len(ch) > 1:
                f['inlined'] = [fn for fn, _ in ch[:-1]][:4]
    except Exception as e:
        lab['symbols']['error'] = str(e)[:120]
    return lab


def _vtt(srt_text):
    out = ['WEBVTT', '']
    for block in srt_text.strip().split('\n\n'):
        rows = block.splitlines()
        if len(rows) >= 3 and '-->' in rows[1]:
            out += [rows[1].replace(',', '.'), *rows[2:], '']
    return '\n'.join(out)


def steps_from_srt(srt_text):
    steps = []
    for block in srt_text.strip().split('\n\n'):
        rows = block.splitlines()
        if len(rows) >= 3 and '-->' in rows[1]:
            h, m, s = rows[1].split('-->')[0].strip().replace(',', '.').split(':')
            steps.append({'t': round(int(h) * 3600 + int(m) * 60 + float(s), 2), 'text': ' '.join(rows[2:])[:120]})
    return steps


def publish_video(case_id, mp4, crash_t=None):
    """Copy the repro video (+ captions) into the board's hosting folder under an unguessable path. The next hosting
    deploy serves it at /v/<token>/repro.mp4. Returns the fields the crash window needs."""
    tok = hashlib.sha256(f'{case_id}:{os.path.getmtime(mp4)}:{os.path.getsize(mp4)}'.encode()).hexdigest()[:20]
    dst = os.path.join(config.REPO, 'tools', 'nightshift', 'board', 'public', 'v', tok)
    os.makedirs(dst, exist_ok=True)
    shutil.copyfile(mp4, os.path.join(dst, 'repro.mp4'))
    srt = mp4[:-4] + '.srt'
    steps = []
    if os.path.exists(srt):
        s = open(srt, errors='replace').read()
        steps = steps_from_srt(s)
        open(os.path.join(dst, 'repro.vtt'), 'w').write(_vtt(s))
    if crash_t is not None:
        steps.append({'t': round(crash_t, 2), 'text': 'CRASH', 'crash': True})
    return {'reproVideoUrl': f'/v/{tok}/repro.mp4', 'reproVideoVtt': f'/v/{tok}/repro.vtt' if os.path.exists(srt) else '',
            'reproSteps': steps}
