"""R8/ProGuard mapping (ReTrace) for Java/Kotlin crashes (29 Oct).

Put a build's mapping file at tools/nightshift/symbols/<version_code>/mapping.txt (Play Console -> App bundle explorer
-> the version -> Downloads -> "ReTrace mapping file"). Then obfuscated names in a crash (e.g. 'method y4.d.d,
parameter table' or 'y4.d.d(Unknown Source)') are turned back into the real class and method for the root cause.
"""
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}


def mapping_path(version_code):
    return os.path.join(HERE, 'symbols', str(version_code or ''), 'mapping.txt')


def load(version_code):
    """-> {obf_class: (orig_class, {obf_method: [orig signatures]})} or {} when there is no mapping for the build."""
    p = mapping_path(version_code)
    if not os.path.exists(p):
        return {}
    key = (p, os.path.getmtime(p))
    if key in _cache:
        return _cache[key]
    out, cur = {}, None
    cls_re = re.compile(r'^(\S+) -> (\S+):$')
    met_re = re.compile(r'^\s+(?:\d+:\d+:)?(\S+) ([\w$<>]+)\(([^)]*)\)(?::\d+(?::\d+)?)? -> ([\w$<>]+)$')
    with open(p, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('#'):
                continue
            m = cls_re.match(line.rstrip('\n'))
            if m:
                cur = (m.group(1), {})
                out[m.group(2)] = cur
                continue
            if cur is None:
                continue
            m = met_re.match(line.rstrip('\n'))
            if m:
                sig = f'{m.group(1)} {m.group(2)}({m.group(3)})'
                lst = cur[1].setdefault(m.group(4), [])
                if sig not in lst:
                    lst.append(sig)
    _cache.clear()
    _cache[key] = out
    return out


def explain(texts, version_code):
    """Obfuscated 'cls.method' names found in the texts -> ['y4.d.d = com.x.RealmWrapper.getAll(String, String)', ...].
    Empty when there is no mapping file for the build (the caller then says so)."""
    mp = load(version_code)
    if not mp:
        return []
    found = []
    for t in texts:
        for tok in re.findall(r'\b([a-zA-Z_$][\w$]*(?:\.[\w$]+)+)\b', str(t or '')):
            parts = tok.split('.')
            for cut in (len(parts) - 1, len(parts)):          # 'pkg.Cls.method' and plain 'pkg.Cls'
                cls, meth = '.'.join(parts[:cut]), (parts[cut] if cut < len(parts) else None)
                if cls in mp:
                    orig, methods = mp[cls]
                    if meth and meth in methods:
                        line = f'{tok} = {orig}.' + ' | '.join(s.split(' ', 1)[1] for s in methods[meth][:4])
                    elif not meth:
                        line = f'{tok} = {orig}'
                    else:
                        continue
                    if line not in found:
                        found.append(line)
                    break
    return found[:30]


def import_from(src, version_code, log=print):
    """Copy the R8 mapping out of a Play .aab (BUNDLE-METADATA/com.android.tools.build.obfuscation/proguard.map) or take
    a plain mapping.txt. -> path or None. Never overwrites an existing mapping for the build."""
    import shutil
    import zipfile
    dst = mapping_path(version_code)
    if os.path.exists(dst):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + '.tmp'
    if str(src).endswith('.txt'):
        shutil.copyfile(src, tmp)
    else:
        with zipfile.ZipFile(src) as z:
            member = next((m for m in z.namelist() if m.endswith('com.android.tools.build.obfuscation/proguard.map')), None)
            if not member:
                log(f'retrace: no mapping inside {os.path.basename(src)}')
                return None
            with z.open(member) as fi, open(tmp, 'wb') as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
    os.replace(tmp, dst)
    log(f'retrace: Java/Kotlin mapping for {version_code} imported from {os.path.basename(src)}')
    return dst


def auto_import(version_codes, log=print):
    """Each sync: for builds without a mapping, look in Downloads for <vc>*.aab or *mapping*<vc>*.txt."""
    import glob
    for vc in version_codes:
        if os.path.exists(mapping_path(vc)):
            continue
        for pat in (f'~/Downloads/{vc}*.aab', f'~/Downloads/*{vc}*.aab', f'~/Downloads/*mapping*{vc}*.txt'):
            for f in glob.glob(os.path.expanduser(pat)):
                try:
                    if import_from(f, vc, log):
                        break
                except Exception as e:
                    log(f'retrace: {os.path.basename(f)} not usable for {vc}: {str(e)[:150]}')
            if os.path.exists(mapping_path(vc)):
                break
