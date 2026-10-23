"""Step 4: map stack frames to source in this repo and pull out the code the analysis needs.

Native frames ('Class::method(args) + off') -> definition in app/src/main/cpp (function body by brace matching)
plus its call sites; Java/Kotlin frames ('pkg.Class.method') -> the class file. Deterministic: no model involved.
"""
import os
import re
import subprocess

from . import config

CPP_ROOT = 'app/src/main/cpp'
JAVA_ROOTS = ('android-video-editor-module', 'java-common', 'app/src/main/java', 'gallerypicker', 'overlay_collage')
RE_NATIVE = re.compile(r'^(?:[\w:<>,\s\*&]+\s)?((?:[A-Za-z_]\w*::)+)?([A-Za-z_~]\w*)\s*\(')


import threading as _threading
_tl = _threading.local()    # per analysis thread: the commit the crashing build was made from (ns/source.py); None = working copy


def set_sha(v):
    _tl.sha = v


def sha():
    return getattr(_tl, 'sha', None)


def _rg(pattern, paths, extra=()):
    if sha():
        from . import source
        return source.grep(pattern, sha(), list(paths))
    cmd = ['grep', '-rnE', pattern, *extra, '--include=*.cpp', '--include=*.h', '--include=*.cc', '--include=*.kt', '--include=*.java', *paths]
    try:
        out = subprocess.run(cmd, cwd=config.REPO, capture_output=True, text=True, timeout=180).stdout
    except Exception:                      # busy Mac (gradle build): one more try before giving up
        try:
            out = subprocess.run(cmd, cwd=config.REPO, capture_output=True, text=True, timeout=300).stdout
        except Exception:
            return []
    return [l for l in out.splitlines() if l]


def native_name(func: str):
    f = func.split(' + ')[0].strip()
    while re.search(r'<[^<>]*>', f):              # 'double MsgLooper::Get<double, int>' -> 'double MsgLooper::Get'
        f = re.sub(r'<[^<>]*>', '', f)
    m = re.match(r'^(.*?)\(', f)
    head = m.group(1) if m else f
    head = head.split(' ')[-1]
    parts = head.split('::')
    return (parts[-2] if len(parts) > 1 else None), parts[-1]


def function_body(path, line_no, max_lines=80):
    try:
        if sha():
            from . import source
            lines = source.read(path, sha()).splitlines()
        else:
            lines = open(os.path.join(config.REPO, path), encoding='utf-8', errors='replace').read().splitlines()
    except OSError:
        return ''
    i, depth, started, out = line_no - 1, 0, False, []
    while i < len(lines) and len(out) < max_lines:
        l = lines[i]
        out.append(f'{i + 1:>5}  {l}')
        depth += l.count('{') - l.count('}')
        if '{' in l:
            started = True
        if started and depth <= 0:
            break
        i += 1
    return '\n'.join(out)


def locate_native(func):
    cls, name = native_name(func)
    if not name or name.startswith('__') or name in ('abort', 'raise'):
        return None
    q = rf'\b{cls}::{re.escape(name)}\s*\(' if cls else rf'^[^;]*\b{re.escape(name)}\s*\([^;]*\)\s*(const\s*)?\{{?\s*$'
    defs = [d for d in _rg(q, [CPP_ROOT]) if not d.rstrip().endswith(';') and '.h:' not in d.split(' ')[0] or '{' in d]
    if not defs:
        return {'func': func, 'found': False}
    path, ln = defs[0].split(':')[0], int(defs[0].split(':')[1])
    callers = [c for c in _rg(rf'(->|\.|::|\s){re.escape(name)}\s*\(', [CPP_ROOT]) if not c.startswith(f'{path}:{ln}:')][:15]
    return {'func': func, 'found': True, 'file': path, 'line': ln, 'body': function_body(path, ln),
            'callers': [c[:200] for c in callers]}


def locate_java(func, file_hint=''):
    m = re.match(r'^([\w.$]+)\.([\w$<>]+)$', func.strip())
    if not m:
        return None
    cls = m.group(1).split('.')[-1].split('$')[0]
    hits = [h for h in _rg(rf'(class|object)\s+{cls}\b', list(JAVA_ROOTS))][:3]
    if not hits:
        return {'func': func, 'found': False}
    path, ln = hits[0].split(':')[0], int(hits[0].split(':')[1])
    return {'func': func, 'found': True, 'file': path, 'line': ln, 'body': function_body(path, ln, 40), 'callers': []}


def at_line(func, path, line, before=45, after=12):
    """Code around the exact crash line of a symbolized frame, read at the shipped commit (or the working copy)."""
    path = re.sub(r'^.*?(app/src/|android-video-editor-module/|java-common/)', r'\1', str(path))
    try:
        if sha():
            from . import source
            txt = source.read(path, sha())
        else:
            txt = open(os.path.join(config.REPO, path), encoding='utf-8', errors='replace').read()
    except Exception:
        txt = ''
    lines = txt.splitlines()
    if not lines or line < 1 or line > len(lines):
        return None
    lo, hi = max(1, line - before), min(len(lines), line + after)
    body = '\n'.join(f"{n:>5}{'>' if n == line else ' '} {lines[n - 1]}" for n in range(lo, hi + 1))
    cls, name = native_name(func)
    callers = [c for c in _rg(rf'(->|\.|::|\s){re.escape(name)}\s*\(', [CPP_ROOT])][:8] if name else []
    return {'func': func, 'found': True, 'file': path, 'line': line, 'body': body, 'callers': [c[:200] for c in callers],
            'how': 'exact line from the symbolized frame (> marks the crash line)'}


def locate(frames, native_lib, limit=4):
    out, seen = [], set()
    for f in frames:
        fn = (f.get('func') or '').strip()
        if not fn or fn in seen or fn.startswith('(') or 'unsymbolized' in fn:
            continue
        seen.add(fn)
        r = None
        fl, ln = f.get('file'), f.get('line')
        if not (fl and ln) and f.get('srcline'):              # 'app/src/main/cpp/player/FramesHelper.cpp:169'
            mm = re.match(r'^(.*?):(\d+)', str(f['srcline']))
            fl, ln = (mm.group(1), mm.group(2)) if mm else (fl, ln)
        if fl and ln and (f.get('lib') == native_lib or '::' in fn):
            r = at_line(fn, fl, int(ln))                    # symbolized frame: exact file:line from the build's .so
        if r:
            pass
        elif f.get('lib') == native_lib or '::' in fn:
            r = locate_native(fn)
        elif '.' in fn and ' ' not in fn:
            r = locate_java(fn, f.get('file', ''))
        else:
            r = None
        if r:
            out.append(r)
        if len([x for x in out if x.get('found')]) >= limit:
            break
    return out
