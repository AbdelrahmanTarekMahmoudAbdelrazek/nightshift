"""Read the source AS SHIPPED, not the working copy.

The production build does not stamp a commit (Crashlytics buildStamp: NO_SUPPORTED_VCS_FOUND) and the engine repo has
no release tags, so the commit is chosen by evidence: for a build, compare the JNI functions its own
libMYJNILIB26.so exports (symbol store) with the JNI functions defined on each candidate release branch; the branch
whose code matches the shipped binary best wins. nightshift.yaml app.source_refs can pin it by hand
(version name or version code -> git ref). The choice is cached in symbols/<versionCode>/meta.json.

All reads go through git (git grep / git show <commit>:<path>), so a dirty working tree or a newer branch checked out
never changes what the analysis sees.
"""
import json
import os
import re
import subprocess

from . import config

HERE = os.path.dirname(os.path.abspath(__file__))
SYMS = os.path.join(HERE, '..', 'symbols')
GIT = ['git', '--no-optional-locks']
_cache = {}


def _git(*args, timeout=180):
    try:
        r = subprocess.run(GIT + list(args), cwd=config.REPO, capture_output=True, text=True, timeout=timeout, errors='replace')
        return r.stdout if r.returncode in (0, 1) else ''
    except Exception:
        return ''


def _jni_in_so(vc):
    so = os.path.join(SYMS, str(vc), 'libMYJNILIB26.so')
    if not os.path.exists(so):
        return set()
    try:
        out = subprocess.run(['nm', '-D', '--defined-only', so], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return set()
    return {l.split()[-1] for l in out.splitlines() if re.search(r'\s(JNI_|Java_)\w+$', l)}


def _jni_in_ref(ref):
    # no \b: macOS git uses the system ERE, which has no word boundary (it silently matched nothing on the lab Mac)
    out = _git('grep', '-hoE', r'(JNI_[A-Za-z0-9_]+|Java_[A-Za-z0-9_]+)[[:space:]]*\(', ref, '--',
               'app/src/main/cpp/*.cpp', 'app/src/main/cpp/**/*.cpp')
    return {re.sub(r'\s*\($', '', l) for l in out.splitlines() if l}


def candidates(wide=False):
    """Release branches (CPP-x.y[.z]); wide=True: every branch updated in the last 120 days (a release can be cut from a
    feature branch, e.g. 1.25.2 shipped the AI background removal before it reached CPP-1.25.2)."""
    if not wide:
        out = _git('for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/', 'refs/heads/')
        return sorted({r for r in out.split() if re.search(r'(^|/)CPP-\d+\.\d+(\.\d+)?$', r)})
    import time
    out = _git('for-each-ref', '--format=%(refname:short) %(committerdate:unix)', 'refs/remotes/origin/')
    cut = time.time() - 120 * 86400
    return sorted({ln.split()[0] for ln in out.splitlines() if len(ln.split()) == 2 and int(ln.split()[1]) >= cut and not ln.endswith('/HEAD')})


def _so_strings(vc):
    so = os.path.join(SYMS, str(vc), 'libMYJNILIB26.so')
    try:
        return subprocess.run(['strings', '-n', '12', so], capture_output=True, text=True, timeout=60, errors='replace').stdout
    except Exception:
        return ''


def _log_absent(ref, blob):
    """How many of a branch's engine log strings are NOT in the shipped .so (fewer = closer to what shipped)."""
    out = _git('grep', '-hoE', r'LOG[EIWDV]?[[:space:]]*\([[:space:]]*"[^"%\\]{14,}', ref, '--', 'app/src/main/cpp', timeout=120)
    lits = {re.sub(r'^LOG[EIWDV]?\s*\(\s*"', '', l).strip() for l in out.splitlines()}
    lits = {l for l in lits if len(l) >= 14}
    return sum(1 for l in lits if l not in blob), len(lits)


_LOG_RX = re.compile(r'^\+.*\bLOG[EIWDV]?\s*\(\s*"([^"]*)"')


def _markers(commit):
    """Log format strings a commit ADDS to the engine (C++); used to tell whether a build contains it."""
    diff = _git('diff', '-U0', f'{commit}^1', commit, '--', 'app/src/main/cpp', timeout=60)
    out = set()
    for line in diff.splitlines():
        m = _LOG_RX.match(line)
        if m:
            lit = re.split(r'%|\\', m.group(1))[0].strip()
            if len(lit) >= 14:
                out.add(lit)
    return out


def pin_by_markers(vc, ref, depth=150):
    """A branch tip moves after a release. Walk the branch back (first parent) and find the newest commit whose added
    log strings are all inside the shipped .so: commits whose strings are all missing were not in the build.
    Returns (sha, evidence) or (None, why)."""
    so = os.path.join(SYMS, str(vc), 'libMYJNILIB26.so')
    if not os.path.exists(so) or not ref:
        return None, 'no shipped .so or ref'
    blob = open(so, 'rb').read()
    chain = _git('rev-list', '--first-parent', f'-n{depth}', ref, '--', 'app/src/main/cpp').split()
    status = []                                   # newest first: (sha, True=in / False=out / None=no markers)
    for c in chain:
        mk = _markers(c)
        if not mk:
            status.append((c, None, 0, 0))
            continue
        hit = sum(1 for x in mk if x.encode() in blob)
        r = hit / len(mk)                         # a few strings can exist before the commit: judge by the share
        status.append((c, True if r >= 0.5 else False if r <= 0.15 else None, hit, len(mk)))
    newest_in = next((i for i, st in enumerate(status) if st[1] is True), None)
    if newest_in is None:
        return None, 'no commit with log strings found in the .so'
    outs = [i for i in range(newest_in) if status[i][1] is False]
    if not outs:
        return _git('rev-parse', ref).strip(), f'branch tip: every newer commit with log strings is in the .so'
    oldest_out = max(outs)                        # first commit (oldest) that the build does NOT contain
    base = _git('rev-parse', f'{status[oldest_out][0]}^1').strip()
    miss = status[oldest_out]
    return base, (f'{len(outs)} newer commit(s) on {ref} are NOT in the build (e.g. {miss[0][:10]}: 0/{miss[3]} of its log strings '
                  f'in the .so); newest commit whose strings are present: {status[newest_in][0][:10]} ({status[newest_in][2]}/{status[newest_in][3]})')


def _match_score(blob, sha, n=6):
    """How well the history just below a commit matches the shipped .so: mean share of present log strings over the
    first n older commits that add any (1.0 = everything there)."""
    chain = _git('rev-list', '--first-parent', '-n40', sha, '--', 'app/src/main/cpp').split()
    rs = []
    for c in chain:
        mk = _markers(c)
        if mk:
            rs.append(sum(1 for x in mk if x.encode() in blob) / len(mk))
        if len(rs) >= n:
            break
    return sum(rs) / len(rs) if rs else 0.0


def _judged(blob, ref, depth=60):
    """(in_commits, out_commits) on a branch's first-parent history, by the share of each commit's log strings in the .so."""
    ins, outs = [], []
    for c in _git('rev-list', '--first-parent', f'-n{depth}', ref, '--', 'app/src/main/cpp').split():
        mk = _markers(c)
        if not mk:
            continue
        r = sum(1 for x in mk if x.encode() in blob) / len(mk)
        (ins if r >= 0.5 else outs if r <= 0.15 else []).append(c)
    return ins, outs


def _tree_strings(commit):
    """{literal: (macro, file)} for every engine log call at a commit (LOGE("...%d") -> 'LOGE')."""
    out = {}
    txt = _git('grep', '-o', '-E', r'[A-Z_]*LOG[A-Z_]*[[:space:]]*\([[:space:]]*"[^"]*"', commit, '--', 'app/src/main/cpp', timeout=60)
    for l in txt.splitlines():
        m = re.match(r'[0-9a-f]+:([^:]+):([A-Z_]*LOG[A-Z_]*)\s*\(\s*"([^"]*)"', l)
        if m:
            lit = re.split(r'%|\\', m.group(3))[0].strip()
            if len(lit) >= 14:
                out[lit] = (m.group(2), m.group(1))
    return out


def best_pin(vc, version_name=None, per_ref=20):
    """The commit a build was made from. Candidates: the recent history of every branch of the release line. Two
    candidates are compared only on the engine log strings that DIFFER between their trees: the one whose own strings
    are in the shipped .so (and whose rival's are not) is closer to the build. King of the hill; newer wins a tie.
    (Release builds compile some log calls out, so strings common to both sides prove nothing and are ignored.)"""
    so = os.path.join(SYMS, str(vc), 'libMYJNILIB26.so')
    if not os.path.exists(so):
        return None, 'no shipped .so'
    blob = open(so, 'rb').read()
    line = '.'.join(str(version_name or '').split('.')[:2])          # 1.25.1 -> 1.25
    refs = [r for r in _git('for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/').split()
            if line and re.search(rf'(CPP|sync|release)[-/]?{re.escape(line)}', r, re.I)]
    cands = []
    for r in refs:
        for c in _git('rev-list', '--first-parent', f'-n{per_ref}', r, '--', 'app/src/main/cpp').split():
            if c not in cands:
                cands.append(c)
    if not cands:
        return None, 'no branch of this release line found'
    strings = {}
    def S(c):
        if c not in strings:
            strings[c] = _tree_strings(c)
        return strings[c]
    inso = lambda xs: sum(1 for x in xs if x.encode() in blob)
    # which log macros survive in this release build (others are compiled out and prove nothing)
    allm, allf = {}, {}
    for c in cands[:3]:
        for lit, (mac, f) in S(c).items():
            hit = lit.encode() in blob
            allm.setdefault(mac, []).append(hit)
            allf.setdefault(f, []).append(hit)
    kept = {m for m, v in allm.items() if len(v) >= 5 and sum(v) / len(v) >= 0.3}
    built = {f for f, v in allf.items() if sum(v) / len(v) >= 0.5}      # files compiled into this .so
    K = lambda c: {x for x, (m, f) in S(c).items() if m in kept and f in built}
    king, note = cands[0], ''
    for c in cands[1:]:
        a, b = K(king), K(c)
        ua, ub = a - b, b - a
        sk = inso(ua) + (len(ub) - inso(ub))      # king's own strings present + rival's own strings absent
        sc = inso(ub) + (len(ua) - inso(ua))
        newer = _git('log', '-1', '--format=%ct', c).strip() > _git('log', '-1', '--format=%ct', king).strip()
        if sc > sk or (sc == sk and newer):
            king, note = c, f'{inso(ub)}/{len(ub)} of its own strings in the .so vs {inso(ua)}/{len(ua)} for the previous best'
    branch = next((r for r in refs if subprocess.run(GIT + ['merge-base', '--is-ancestor', king, r], cwd=config.REPO).returncode == 0), '')
    return king, f'{branch}: {note} (compared {len(cands)} commits on {len(refs)} branches by the log strings that differ; macros kept in release: {", ".join(sorted(kept))})'


def ref_for(version_code, version_name=None, cfg=None):
    """git commit sha the build was made from (best evidence), or None -> fall back to the working copy."""
    vc = str(version_code or '')
    if vc in _cache:
        return _cache[vc]
    cfg = cfg or config.load()
    pinned = ((cfg.get('app') or {}).get('source_refs') or {})
    ref = pinned.get(vc) or pinned.get(str(version_name or ''))
    meta_p = os.path.join(SYMS, vc, 'meta.json')
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    if not ref and meta.get('source_ref'):
        ref = meta['source_ref']
    if not ref:
        shipped = _jni_in_so(vc)
        best = None
        if shipped:
            for r in candidates():
                code = _jni_in_ref(r)
                if not code:
                    continue
                score = (len(shipped - code), len(code - shipped))   # missing from code matters most
                if best is None or score < best[0]:
                    best = (score, r)
        if shipped and (not best or best[0][0] > 0):    # no release branch has every JNI function: look wider
            blob = _so_strings(vc)
            wide = []
            for r in candidates(wide=True):
                code = _jni_in_ref(r)
                if code and not (shipped - code):
                    wide.append((len(code - shipped), _log_absent(r, blob)[0], r))
            if wide:
                wide.sort()
                best = ((0, wide[0][0]), wide[0][2])
        if best and best[0][0] == 0:
            ref = best[1]
            if os.path.isdir(os.path.dirname(meta_p)):
                meta.update({'source_ref': ref, 'source_ref_evidence': f'JNI symbols: {best[0][0]} missing, {best[0][1]} extra'})
                json.dump(meta, open(meta_p, 'w'), indent=1)
    if ref and not re.fullmatch(r'[0-9a-f]{40}', ref) and not meta.get('source_pinned'):
        pin, why = best_pin(vc, version_name or meta.get('version_name'))   # a branch name is a moving target
        shipped_jni = _jni_in_so(vc)
        if pin and shipped_jni and (shipped_jni - _jni_in_ref(pin)):   # that commit lacks functions the build exports: not it
            why0 = f'{pin[:10]} rejected: it lacks {len(shipped_jni - _jni_in_ref(pin))} JNI functions the build has'
            pin, why = pin_by_markers(vc, ref)
            why = f'{why0}; {why}'
        if not pin:
            pin, why = pin_by_markers(vc, ref)
        if pin and shipped_jni and (shipped_jni - _jni_in_ref(pin)):
            pin, why = None, f'no commit on {ref} has every JNI function of the build'
        if pin and os.path.isdir(os.path.dirname(meta_p)):
            meta.update({'source_ref': pin, 'source_branch': ref, 'source_pinned': why})
            json.dump(meta, open(meta_p, 'w'), indent=1)
            ref = pin
    sha = _git('rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}').strip() if ref else ''
    _cache[vc] = {'ref': ref, 'sha': sha} if sha else None
    return _cache[vc]


def _git_in(sub, *args, timeout=180):
    try:
        r = subprocess.run(GIT + ['-C', os.path.join(config.REPO, sub)] + list(args), cwd=config.REPO,
                           capture_output=True, text=True, timeout=timeout, errors='replace')
        return r.stdout if r.returncode in (0, 1) else None
    except Exception:
        return None


_subs = {}


def submodule_pin(sub, sha):
    """Commit the engine commit pins for a submodule (Java lives in submodules), if that object is available here."""
    key = (sub, sha)
    if key not in _subs:
        line = _git('ls-tree', sha, sub).split()
        pin = line[2] if len(line) >= 3 and line[1] == 'commit' else None
        ok = pin and (_git_in(sub, 'cat-file', '-t', pin) or '').strip() == 'commit'
        if pin and not ok:
            # the pinned commit was never fetched here (e.g. java-common): fetch just that object from origin.
            # Only .git objects change; the checked-out files and branches stay as they are.
            _git_in(sub, 'fetch', '--quiet', 'origin', pin, timeout=120)
            ok = (_git_in(sub, 'cat-file', '-t', pin) or '').strip() == 'commit'
            if not ok:                              # Bitbucket refuses a bare SHA ("not our ref"): fetch all branches
                _git_in(sub, 'fetch', '--quiet', 'origin', '+refs/heads/*:refs/remotes/origin/*', timeout=300)
                ok = (_git_in(sub, 'cat-file', '-t', pin) or '').strip() == 'commit'
        if pin and not ok:                          # never pushed: closest existing commit, chosen against the APK
            fb = _fallback().get(f'{sub}@{sha}')
            if fb and (_git_in(sub, 'cat-file', '-t', fb['commit']) or '').strip() == 'commit':
                pin, ok = fb['commit'], True
        _subs[key] = pin if ok else None
    return _subs[key]


def _fallback():
    p = os.path.join(SYMS, 'sub_fallback.json')
    try:
        return json.load(open(p)) if os.path.exists(p) else {}
    except ValueError:
        return {}


def _split(path, sha):
    """'android-video-editor-module/src/..' -> ('android-video-editor-module', pinned commit, 'src/..') or main repo."""
    head = path.split('/', 1)[0]
    pin = submodule_pin(head, sha) if '/' in path or os.path.isdir(os.path.join(config.REPO, head)) else None
    if pin:
        return head, pin, path.split('/', 1)[1] if '/' in path else ''
    return None, sha, path


def _posix(pattern):
    """git grep -E on the Mac uses the system (BSD) regex, which has no \\s or \\b: a pattern with them matched
    nothing there (it worked on Linux), so frames without a file:line (JNI, templates) never got their code."""
    p = pattern.replace(r'\s', '[[:space:]]').replace(r'\S', '[^[:space:]]').replace(r'\w', '[[:alnum:]_]')
    return p.replace(r'\b', '([^[:alnum:]_]|^)', 1).replace(r'\b', '')   # leading word edge kept, inner ones dropped


def grep(pattern, sha, paths, includes=('*.cpp', '*.h', '*.cc', '*.kt', '*.java')):
    """git grep at the shipped commit (and at the pinned commit inside submodules) -> 'path:line:text' lines."""
    pattern = _posix(pattern)
    out = []
    for p in paths:
        sub, commit, rest = _split(p.rstrip('/'), sha)
        base = (rest + '/') if rest else ''
        specs = [f'{base}*{inc[1:]}' for inc in includes]
        if sub:
            txt = _git_in(sub, 'grep', '-nE', pattern, commit, '--', *specs)
            if txt is None:
                continue
            out += [f'{sub}/{l[len(commit) + 1:]}' for l in txt.splitlines() if l.startswith(commit + ':')]
        else:
            if os.path.isdir(os.path.join(config.REPO, p)) and not _git('ls-tree', sha, p).strip():
                continue                                    # path not in this commit (e.g. submodule not available)
            txt = _git('grep', '-nE', pattern, commit, '--', *specs)
            out += [l[len(commit) + 1:] for l in txt.splitlines() if l.startswith(commit + ':')]
    return out


def read(path, sha):
    sub, commit, rest = _split(path, sha)
    if sub:
        return _git_in(sub, 'show', f'{commit}:{rest}') or ''
    return _git('show', f'{commit}:{path}')


def _web(url):
    m = re.search(r'bitbucket\.org[:/]([^/]+)/([^/.]+)', url or '')
    return f'https://bitbucket.org/{m.group(1)}/{m.group(2)}/src/' if m else ''


def describe(sha, ref=None):
    """For the analysis + board: which commits were read, and their Bitbucket base URLs."""
    urls = {}
    gm = os.path.join(config.REPO, '.gitmodules')
    if os.path.exists(gm):
        cur = None
        for l in open(gm):
            m = re.match(r'\s*path\s*=\s*(\S+)', l)
            if m:
                cur = m.group(1)
            m = re.match(r'\s*url\s*=\s*(\S+)', l)
            if m and cur:
                urls.setdefault(cur, _web(m.group(1)))
    pins = {s: submodule_pin(s, sha) for s in ('android-video-editor-module', 'java-common', 'gallerypicker', 'overlay_collage')}
    web = {'': f'https://bitbucket.org/mitrotek/video_gles3jni/src/{sha}/'}
    for k, v in pins.items():
        if v and urls.get(k):
            web[k] = urls[k] + v + '/'
    fb = {k: v for k, v in _fallback().items() if k.endswith('@' + sha) and pins.get(k.split('@')[0]) == v.get('commit')}
    return {'ref': ref, 'engine': sha, 'submodules': {k: v for k, v in pins.items() if v},
            'missing': [k for k, v in pins.items() if not v], 'web': web,
            'fallback': {k.split('@')[0]: {x: v.get(x) for x in ('commit', 'branch', 'match', 'why')} for k, v in fb.items()}}
