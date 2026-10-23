"""Does the Java/Kotlin code we read for a build match what is inside that build's APK?

The native side is matched by JNI symbols (ns/source.py). For Java we read the submodules at the commits the engine
commit pins, which is an assumption until checked: this module opens the APK's classes*.dex, lists every class (and its
methods) in our own packages, and compares them with the classes declared in the source at the shipped commit.
Pure Python DEX reader, no Android SDK needed. Result cached in symbols/<versionCode>/java_check.json.
"""
import json
import os
import re
import struct
import zipfile

from . import config, locate, source

HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = os.path.join(HERE, '..', 'symbols')
GENERATED = re.compile(r'(^R$|^BuildConfig$|Binding(Impl)?$|_Factory$|_Impl$|^Hilt_|^Dagger|Directions$|Args$|_HiltModules|'
                       r'^ComposableSingletons|_MembersInjector$|_GeneratedInjector$|BR$|DataBinderMapperImpl|_Provide)')


def _uleb(d, o):
    r = s = 0
    while True:
        b = d[o]; o += 1
        r |= (b & 0x7f) << s
        if b < 0x80:
            return r, o
        s += 7


def dex_classes(d):
    """{ 'com.x.Foo': {'methods'} } for classes DEFINED in this dex (class_defs), methods from method_ids."""
    u = lambda o: struct.unpack_from('<I', d, o)[0]
    s_n, s_o, t_n, t_o = u(0x38), u(0x3C), u(0x40), u(0x44)
    m_n, m_o, c_n, c_o = u(0x58), u(0x5C), u(0x60), u(0x64)

    def string(i):
        off = u(s_o + 4 * i)
        _, p = _uleb(d, off)
        e = d.index(b'\0', p)
        return d[p:e].decode('utf-8', 'replace')
    types = [u(t_o + 4 * i) for i in range(t_n)]
    defined = {u(c_o + 32 * i) for i in range(c_n)}
    out = {}
    for ti in defined:
        desc = string(types[ti])
        if desc.startswith('L') and desc.endswith(';'):
            out.setdefault(desc[1:-1].replace('/', '.'), set())
    for i in range(m_n):
        cls, _, name = struct.unpack_from('<HHI', d, m_o + 8 * i)
        if cls in defined:
            desc = string(types[cls])
            out.setdefault(desc[1:-1].replace('/', '.'), set()).add(string(name))
    return out


def apk_classes(apk):
    cls = {}
    with zipfile.ZipFile(apk) as z:
        for n in z.namelist():
            if re.match(r'classes\d*\.dex$', n):
                for k, v in dex_classes(z.read(n)).items():
                    cls.setdefault(k, set()).update(v)
    return cls


def source_classes(sha):
    """{'com.x.Foo': 'path'} for top-level classes/objects/interfaces declared at the shipped commit."""
    lines = source.grep(r'^package |^\s*(public |internal |private |abstract |open |final |data |sealed |enum |annotation |inner |value )*'
                        r'(class|interface|object|enum) [A-Z]', sha, list(locate.JAVA_ROOTS), includes=('*.kt', '*.java'))
    pkg, out = {}, {}
    for l in lines:
        path, _, rest = l.split(':', 2)
        m = re.match(r'\s*package\s+([\w.]+)', rest)
        if m:
            pkg[path] = m.group(1)
    for l in lines:
        path, _, rest = l.split(':', 2)
        m = re.search(r'\b(class|interface|object|enum)\s+([A-Z]\w*)', rest)
        if m and path in pkg and rest[:1] not in (' ', '\t'):     # top level only; nested ones are Outer$Inner in the dex
            out.setdefault(f'{pkg[path]}.{m.group(2)}', path)
    return out, set(pkg.values())


def _working_copy_classes():
    """Top-level classes declared in today's files (all Java roots), as package.Name."""
    out = set()
    for root in locate.JAVA_ROOTS:
        base = os.path.join(config.REPO, root)
        for d, _, fs in os.walk(base):
            if '/build/' in d + '/' or '/.git' in d:
                continue
            for f in fs:
                if not f.endswith(('.kt', '.java')):
                    continue
                try:
                    txt = open(os.path.join(d, f), encoding='utf-8', errors='replace').read()
                except OSError:
                    continue
                m = re.search(r'^package\s+([\w.]+)', txt, re.M)
                if not m:
                    continue
                for n in re.findall(r'^(?:[a-z]+ )*(?:class|interface|object|enum) ([A-Z]\w*)', txt, re.M):
                    out.add(f'{m.group(1)}.{n}')
    return out


def find_apk(version_code, meta=None):
    """The stored path may be from another machine: also look in Downloads."""
    import glob
    if meta is None:
        mp = os.path.join(SYMS, str(version_code), 'meta.json')
        meta = json.load(open(mp)) if os.path.exists(mp) else {}
    cands = [meta.get('source') or ''] + glob.glob(os.path.expanduser(f'~/Downloads/{version_code}*.apk')) + \
        glob.glob(os.path.expanduser(f'~/mnt/Downloads/{version_code}*.apk'))
    return next((c for c in cands if c.endswith('.apk') and os.path.exists(c)), None)


def check(version_code, apk=None, sha=None, force=False):
    d = os.path.join(SYMS, str(version_code))
    cache = os.path.join(d, 'java_check.json')
    if os.path.exists(cache) and not force:
        return json.load(open(cache))
    meta = json.load(open(os.path.join(d, 'meta.json'))) if os.path.exists(os.path.join(d, 'meta.json')) else {}
    apk = apk or find_apk(version_code, meta)
    if not apk or not os.path.exists(apk) or not apk.endswith('.apk'):
        return {'verdict': 'unknown', 'why': 'APK file for this build not found on the Mac'}
    if not sha:
        ref = source.ref_for(version_code, meta.get('version_name'))
        sha = (ref or {}).get('sha')
    if not sha:
        return {'verdict': 'unknown', 'why': 'no shipped commit identified for this build'}
    src, pkgs = source_classes(sha)
    apk_all = apk_classes(apk)
    ours = {k: v for k, v in apk_all.items() if k.rsplit('.', 1)[0] in pkgs}
    top = {}
    for k, v in ours.items():
        name = k.rsplit('.', 1)[-1].split('$')[0]
        pk = k.rsplit('.', 1)[0]
        if GENERATED.search(name):
            continue
        top.setdefault(f'{pk}.{name}', set()).update(v)
    short = sum(1 for k in top if len(k.rsplit('.', 1)[-1]) <= 2)
    if top and short / len(top) > 0.3:
        res = {'verdict': 'minified', 'why': f'{short}/{len(top)} class names are 1-2 letters (R8): needs mapping.txt to compare'}
    else:
        apk_only = sorted(k for k in top if k not in src)
        # an APK class missing at the commit but present in today's code = the build has code the commit does not
        # (wrong commit, or Java built from another branch). Missing everywhere = another repo (host app) or generated.
        here = _working_copy_classes()
        newer = [k for k in apk_only if k in here]
        foreign = [k for k in apk_only if k not in here]
        judged = len(top) - len(foreign)
        both = judged - len(newer)
        rate = both / max(1, judged)
        verdict = 'match' if rate >= 0.98 else 'close' if rate >= 0.93 else 'mismatch'
        res = {'verdict': verdict, 'judged': judged, 'matched': both, 'rate': round(rate, 3),
               'not_at_commit': newer[:40], 'not_at_commit_n': len(newer), 'other_repo_n': len(foreign),
               'other_repo': foreign[:15], 'unused_in_source_n': len([k for k in src if k not in top]),
               'packages': len(pkgs), 'sha': sha,
               'why': (f'{both}/{judged} app classes in the APK are declared at the shipped commit'
                       + (f'; {len(newer)} exist only in newer/other code, so this build is not exactly that commit for Java'
                          if newer else '')
                       + (f'; {len(foreign)} come from outside this repo (host app or generated)' if foreign else ''))}
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(cache, 'w'), indent=1)
    return res


# ── submodule commit that is missing upstream: pick the closest commit that exists, proven against the APK ──
FALLBACK = os.path.join(SYMS, 'sub_fallback.json')
DECL = r'^(public |internal |private |abstract |open |final |data |sealed |enum |annotation |value )*(class|interface|object|enum) [A-Z]|^package '


def _classes_in(sub, commit):
    txt = source._git_in(sub, 'grep', '-nE', DECL, commit, '--', '*.kt', '*.java') or ''
    pkg, decl = {}, []
    for l in txt.splitlines():
        parts = l.split(':', 3)
        if len(parts) < 4:
            continue
        _, path, _, rest = parts
        m = re.match(r'\s*package\s+([\w.]+)', rest)
        if m:
            pkg[path] = m.group(1)
        else:
            m = re.search(r'\b(class|interface|object|enum)\s+([A-Z]\w*)', rest)
            if m:
                decl.append((path, m.group(2)))
    return {f'{pkg[p]}.{n}' for p, n in decl if p in pkg}, set(pkg.values())


def best_submodule_commit(sub, engine_sha, apk, log=print):
    """The engine commit pins a submodule commit that is not on the remote. Score the submodule's commits from 30 days
    before to 3 days after the engine commit by how many of the APK's classes (in that submodule's packages) they
    declare, minus classes they have that the APK does not; ties go to the commit closest in time. Cached."""
    cache = json.load(open(FALLBACK)) if os.path.exists(FALLBACK) else {}
    key = f'{sub}@{engine_sha}'
    if key in cache:
        return cache[key]
    when = int((source._git('show', '-s', '--format=%ct', engine_sha) or '0').strip() or 0)
    if not when or not apk or not os.path.exists(apk):
        return None
    revs = (source._git_in(sub, 'rev-list', '--all', f'--since={when - 30 * 86400}', f'--until={when + 3 * 86400}',
                           '--format=%ct', timeout=120) or '').split('\n')
    cands = []
    for i in range(0, len(revs) - 1, 2):                       # "commit <sha>" then "<time>"
        if revs[i].startswith('commit ') and revs[i + 1].strip().isdigit():
            cands.append((revs[i].split()[1], int(revs[i + 1])))
    cands = sorted(cands, key=lambda c: abs(c[1] - when))[:250]
    if not cands:
        return None
    apk_cls = {k.split('$')[0] for k in apk_classes(apk)}
    best = None
    for sha, t in cands:
        cls, pkgs = _classes_in(sub, sha)
        mine = {k for k in apk_cls if k.rsplit('.', 1)[0] in pkgs and not GENERATED.search(k.rsplit('.', 1)[-1])}
        if not mine:
            continue
        hit = len(mine & cls)
        extra = len(cls - apk_cls)
        score = hit / len(mine) - 0.2 * extra / max(1, len(cls))
        cand = (score, -abs(t - when), sha, hit, len(mine), extra)
        if best is None or cand > best:
            best = cand
    if not best:
        return None
    score, dt_neg, sha, hit, n, extra = best
    branches = (source._git_in(sub, 'branch', '-r', '--contains', sha, timeout=60) or '').split()
    pref = re.compile(r'(regression|release|master|main|develop|development|pro_dev)', re.I)
    branches = sorted((b for b in branches if b != '->' and not b.endswith('HEAD')), key=lambda b: (not pref.search(b), len(b)))
    res = {'commit': sha, 'match': round(hit / max(1, n), 3), 'apk_classes': n, 'extra': extra,
           'days_from_engine': round(-dt_neg / 86400, 1), 'branch': (branches[0] if branches else ''),
           'why': f'exact pinned commit is not on the remote; closest existing commit {sha[:8]}'
                  f'{" (" + branches[0] + ")" if branches else ""} declares {hit}/{n} of the APK classes in {sub}'}
    cache[key] = res
    json.dump(cache, open(FALLBACK, 'w'), indent=1)
    log(f'source: {res["why"]}')
    return res
