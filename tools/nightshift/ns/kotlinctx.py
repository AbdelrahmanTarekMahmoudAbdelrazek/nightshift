"""Kotlin side of a native PR (no AI). The app's Kotlin/Java code lives in other repos (android-video-editor-module,
java-common, gallerypicker). The PR review keeps a read-only shallow copy of each at its newest sprintNNN branch
(or its main branch), maps the JNI bridge (Kotlin `external fun` -> JNI_* -> MsgLooper message -> engine function) and
lists the Kotlin callers of the native functions the PR changes, with file:line and the code around each call.
Hunters and judges get that list, and may Read/Grep those copies, so a trigger like "undo sends setVideoSpeed" is
checked in real code instead of guessed."""
import os
import re
import subprocess

from . import config

ROOT = os.path.expanduser('~/.nightshift_kotlin')
DEFAULT_REPOS = ['android-video-editor-module', 'java-common', 'gallerypicker']
SRC_EXT = ('.kt', '.java')
SKIP_DIRS = {'build', '.git', '.gradle', 'node_modules', 'intermediates', 'generated'}


def _git(args, cwd=None, timeout=180):
    return subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _remote_base():
    """git@bitbucket.org:mitrotek/ from the native repo's own origin, so the same login is used."""
    url = _git(['remote', 'get-url', 'origin'], cwd=config.REPO).stdout.strip()
    return url.rsplit('/', 1)[0] + '/' if '/' in url else url.rsplit(':', 1)[0] + ':'


def _pick_branch(heads, pinned=None):
    """heads: {branch: sha}. A pinned branch wins; else the highest sprintNNN; else main/master/develop."""
    if pinned and pinned in heads:
        return pinned
    sp = sorted(((int(m.group(1)), b) for b in heads for m in [re.fullmatch(r'sprint[-_]?(\d+)', b, re.I)] if m), reverse=True)
    if sp:
        return sp[0][1]
    return next((b for b in ('main', 'master', 'develop') if b in heads), None)


def _by_date(repo):
    """Sprint branches of one repo, most recently committed first (Bitbucket API, read-only). [] when unavailable."""
    try:
        from . import bitbucket
        import urllib.parse
        c = bitbucket.creds()
        url = (f"{bitbucket.API}/repositories/{c['workspace']}/{repo}/refs/branches?sort=-target.date&pagelen=20&q="
               + urllib.parse.quote('name ~ "sprint"'))
        return [b.get('name', '') for b in (bitbucket._get(url, c=c).get('values') or [])
                if re.fullmatch(r'sprint[-_]?\d+', b.get('name', ''), re.I)]
    except Exception:
        return []


def sync(cfg, log=print):
    """Bring every Kotlin repo to its newest sprint branch (shallow, detached, read-only use). Returns
    [{repo, branch, sha, path}] for the repos that could be fetched; a repo that fails is skipped with a log line."""
    pc = (cfg.get('pr_review') or {})
    try:                                              # the profile's other repos (nightshift.yaml profile.repos after the main one)
        prof_repos = config.profile(cfg)['repos'][1:]
    except Exception:
        prof_repos = []
    repos = pc.get('kotlin_repos') or prof_repos or DEFAULT_REPOS
    pinned = pc.get('kotlin_branch') or None
    base = pc.get('kotlin_remote') or _remote_base()
    os.makedirs(ROOT, exist_ok=True)
    out = []
    # "the current sprint" = the sprint branch with the newest commit in the main editor repo (not the highest number:
    # a later sprint branch can exist before work moves to it); the other repos use that same sprint when they have it
    anchor = None if pinned else next(iter(_by_date(repos[0])), None)
    if anchor:
        log(f'Kotlin: current sprint = {anchor} (newest commit in {repos[0]})')
    for name in repos:
        path = os.path.join(ROOT, name)
        url = base + name + '.git'
        try:
            r = _git(['ls-remote', '--heads', url], timeout=60)
            if r.returncode:
                log(f'Kotlin: {name}: cannot list branches ({r.stderr.strip()[:120]})')
                continue
            heads = {l.split('refs/heads/', 1)[1]: l.split()[0] for l in r.stdout.splitlines() if 'refs/heads/' in l}
            br = _pick_branch(heads, pinned or anchor)
            if not pinned and anchor and br != anchor:     # this repo has no such sprint: its own most recent one
                br = next((b for b in _by_date(name) if b in heads), None) or _pick_branch(heads)
            if not br:
                log(f'Kotlin: {name}: no sprint or main branch')
                continue
            if not os.path.isdir(os.path.join(path, '.git')):
                os.makedirs(path, exist_ok=True)
                _git(['init', '-q'], cwd=path)
                _git(['remote', 'add', 'origin', url], cwd=path)
            have = _git(['rev-parse', 'HEAD'], cwd=path).stdout.strip()
            if have != heads[br]:
                f = _git(['fetch', '-q', '--depth', '1', 'origin', heads[br]], cwd=path, timeout=600)
                if f.returncode:
                    f = _git(['fetch', '-q', '--depth', '1', 'origin', br], cwd=path, timeout=600)
                if f.returncode:
                    log(f'Kotlin: {name}: fetch of {br} failed ({f.stderr.strip()[:120]})')
                    continue
                _git(['checkout', '-q', '--detach', '--force', 'FETCH_HEAD'], cwd=path)
            out.append({'repo': name, 'branch': br, 'sha': heads[br][:10], 'path': path})
        except (subprocess.TimeoutExpired, OSError) as e:
            log(f'Kotlin: {name}: {str(e)[:120]}')
    return out


def _sources(paths):
    for root in paths:
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for fn in files:
                if fn.endswith(SRC_EXT):
                    yield os.path.join(d, fn)


def _read(p):
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def changed_functions(diff, cmap=None):
    """Names of the native functions the PR touches: from hunk headers and the change map (name and callers)."""
    names = set()
    for h in re.findall(r'^@@[^@]*@@\s*(.*)$', diff or '', re.M):
        m = re.search(r'(\w+)\s*\(', h)
        if m:
            names.add(m.group(1))
    for f in (cmap or {}).get('functions') or []:
        if isinstance(f, dict):
            for s in [f.get('name') or ''] + [str(c) for c in f.get('callers') or []]:
                s2 = s.split('::')[-1]
                m = re.findall(r'(\w+)\s*\(', s2) or re.findall(r'(\w+)\s*$', s2.strip())
                if m:
                    names.add(m[-1])
    return {n for n in names if len(n) > 3 and n not in ('if', 'for', 'while', 'switch', 'return', 'sizeof')}


def bridge(native_root, fnames):
    """Native side: which looper messages and JNI functions reach the changed functions, and their Kotlin names."""
    cpp = os.path.join(native_root, 'app/src/main/cpp')
    looper = _read(os.path.join(cpp, 'player/MsgLooper.cpp'))
    jni = _read(os.path.join(cpp, 'JNI/JNI.cpp'))
    call = re.compile(r'\b(' + '|'.join(map(re.escape, sorted(fnames))) + r')\s*\(') if fnames else None
    msgs = {}                                         # MsgX -> engine functions it calls
    if call:
        parts = re.split(r'(?=functions\[(Msg\w+)\]\s*=)', looper)
        for i in range(1, len(parts), 2):
            body = parts[i + 1] if i + 1 < len(parts) else ''
            hit = set(call.findall(body))
            if hit:
                msgs[parts[i]] = hit
    reg = dict((j, n) for n, j in re.findall(r'\{\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*\(void\s*\*\)\s*(JNI_\w+)\s*\}', jni))
    out = []                                          # [{kotlin, jni, via, calls}]
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'\b(JNI_\w+)\s*\(\s*JNIEnv', jni)]
    for k, (pos, jname) in enumerate(starts):
        body = jni[pos:starts[k + 1][0] if k + 1 < len(starts) else len(jni)]
        via = [m for m in msgs if re.search(r'\b' + m + r'\b', body)]
        direct = set(call.findall(body)) if call else set()
        if (via or direct) and jname in reg:
            out.append({'kotlin': reg[jname], 'jni': jname, 'via': via,
                        'calls': sorted(set().union(*[msgs[m] for m in via]) | direct)})
    return out


def callers(paths, kname, cap=12, ctx=6):
    """Kotlin/Java declarations and call sites of one bridged name, with the lines around each call."""
    decl, calls = [], []
    pat = re.compile(r'\b' + re.escape(kname) + r'\s*\(')
    for p in _sources(paths):
        txt = _read(p)
        if kname not in txt:
            continue
        lines = txt.split('\n')
        for i, l in enumerate(lines):
            if not pat.search(l):
                continue
            s = l.strip()
            if s.startswith(('//', '*', '/*')):
                continue
            rel = p
            for r in paths:
                if p.startswith(r):
                    rel = os.path.basename(r) + '/' + os.path.relpath(p, r)
            if re.search(r'\b(external\s+fun|native\b)', l):
                decl.append(f'{rel}:{i + 1}')
            elif len(calls) < cap:
                a, b = max(0, i - ctx), min(len(lines), i + ctx + 1)
                calls.append({'at': f'{rel}:{i + 1}', 'code': '\n'.join(f'{n + 1:>5}  {lines[n]}' for n in range(a, b))})
    return decl, calls


def context(cfg, diff, cmap=None, log=print, linked=None):
    """(prompt text, readable dirs, label for the page, result line for the stages table).
    linked: copies of PRs in the Kotlin repos that this PR ships with (checkout_linked); they replace the sprint copy."""
    repos = sync(cfg, log)
    for L in linked or []:
        repos = [r for r in repos if r['repo'] != L['repo']] + [L]
    if not repos:
        return '', [], '', 'no Kotlin repo reachable'
    paths = [r['path'] for r in repos]
    label = ' · '.join(f"{r['repo']} {r['branch']}@{r['sha'][:7]}" for r in repos)
    br = bridge(config.REPO, changed_functions(diff, cmap))
    blocks, ncalls = [], 0
    for b in br[:8]:
        decl, calls = callers(paths, b['kotlin'])
        ncalls += len(calls)
        blocks.append(f"### Kotlin `{b['kotlin']}` -> {b['jni']}" + (f" -> {', '.join(b['via'])}" if b['via'] else '')
                      + f" -> {', '.join(b['calls'])}\nDeclared: {', '.join(decl) or 'not found'}\n"
                      + ('\n'.join(f"Call at {c['at']}:\n```\n{c['code']}\n```" for c in calls) or 'No Kotlin call site found.'))
    text = ("## Kotlin side (the app code that calls this native code; read-only copies: newest sprint branch, or the PR "
            "this one ships with when its description links one)\n"
            f"Repos: {label}\nYou may Read/Grep them at: {', '.join(paths)}\n"
            "Use them to check triggers (undo, the speed panel, draft restore, the timeline cursor): a Kotlin caller with "
            "file:line is evidence; a caller you cannot find there does not exist.\n\n"
            + ('\n\n'.join(blocks) if blocks else 'No JNI entry point of this app reaches the changed native functions.') + '\n\n')
    return text[:30000], paths, label, f"{len(br)} JNI bridge(s) · {ncalls} Kotlin call site(s) · {label}"


# ---- 23 Oct: linked Kotlin PRs + a JNI table check (no AI) ----------------------------------------------------------
LINK_RE = re.compile(r'bitbucket\.org/([\w.-]+)/([\w.-]+)/pull-requests/(\d+)')


def linked_prs(text, repos):
    """PRs in the app's other repos that a PR description links ("ship with java-common #609"): {repo: number}."""
    out = {}
    for ws, repo, num in LINK_RE.findall(text or ''):
        if repo in repos and repo not in out:
            out[repo] = int(num)
    return out


def checkout_linked(repo, pr, log=print):
    """A read-only shallow copy of another repo's PR head, in its OWN folder (~/.nightshift_kotlin/<repo>@pr<n>), so
    parallel reviews that use the sprint copy of the same repo are never disturbed. pr = bitbucket row (num, source, head)."""
    path = os.path.join(ROOT, f"{repo}@pr{pr['num']}")
    url = _remote_base() + repo + '.git'
    if not os.path.isdir(os.path.join(path, '.git')):
        os.makedirs(path, exist_ok=True)
        _git(['init', '-q'], cwd=path)
        _git(['remote', 'add', 'origin', url], cwd=path)
    if _git(['rev-parse', 'HEAD'], cwd=path).stdout.strip() != pr['head']:
        f = _git(['fetch', '-q', '--depth', '1', 'origin', pr['head']], cwd=path, timeout=600)
        if f.returncode:
            f = _git(['fetch', '-q', '--depth', '1', 'origin', pr['source']], cwd=path, timeout=600)
        if f.returncode:
            raise RuntimeError(f"fetch of {repo} PR #{pr['num']} ({pr['source']}) failed: {f.stderr.strip()[:120]}")
        _git(['checkout', '-q', '--detach', '--force', 'FETCH_HEAD'], cwd=path)
    return {'repo': repo, 'branch': f"PR #{pr['num']} {pr['source']}", 'sha': pr['head'][:10], 'path': path, 'linked': True}


_KT2JNI = {'Int': 'I', 'Long': 'J', 'Float': 'F', 'Double': 'D', 'Boolean': 'Z', 'Byte': 'B', 'Short': 'S', 'Char': 'C',
           'Unit': 'V', 'String': 'Ljava/lang/String;', 'IntArray': '[I', 'LongArray': '[J', 'FloatArray': '[F',
           'DoubleArray': '[D', 'BooleanArray': '[Z', 'ByteArray': '[B', 'ShortArray': '[S', 'CharArray': '[C',
           'Any': 'Ljava/lang/Object;', 'HashMap': 'Ljava/util/HashMap;', 'Map': 'Ljava/util/Map;', 'List': 'Ljava/util/List;',
           'ArrayList': 'Ljava/util/ArrayList;', 'Pair': 'Lkotlin/Pair;', 'Bitmap': 'Landroid/graphics/Bitmap;',
           'Surface': 'Landroid/view/Surface;', 'ByteBuffer': 'Ljava/nio/ByteBuffer;'}


def _split_top(s):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch in '<(':
            depth += 1
        elif ch in '>)':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out if x.strip()]


def _kt_type(t):
    """'Array<HashMap<String, FloatArray>>?' -> '[Ljava/util/HashMap;'; None when the type is not known here."""
    t = re.sub(r'@\w+(\([^)]*\))?\s*', '', t).strip().rstrip('?').strip()
    if t.startswith('Array<') and t.endswith('>'):
        inner = _kt_type(t[6:-1].split('<', 1)[0] if '<' in t[6:-1] and not t[6:-1].startswith('Array<') else t[6:-1])
        return None if inner is None else '[' + inner
    base = t.split('<', 1)[0].strip().split('.')[-1]
    return _KT2JNI.get(base)


def kotlin_externals(paths, cls_file='Player.kt'):
    """{name: [(jni signature or None, n params, 'file:line')]} for every `external fun` in the app's Kotlin copies."""
    out = {}
    for p in _sources(paths):
        if not p.endswith('.kt') or (cls_file and not p.endswith(cls_file)):
            continue
        s = _read(p)
        s = re.sub(r'/\*.*?\*/', lambda c: '\n' * c.group(0).count('\n'), s, flags=re.S)   # block comments, same line count
        s = re.sub(r'//[^\n]*', '', s)
        for m in re.finditer(r'external\s+fun\s+(\w+)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)[ \t]*(?::[ \t]*([\w<>,.?\[\] \t]+?))?[ \t]*(?=[;\n]|//|$)', s):
            name, params, ret = m.group(1), m.group(2), (m.group(3) or 'Unit').strip()
            params = re.sub(r'/\*.*?\*/', ' ', re.sub(r'//[^\n]*', ' ', params), flags=re.S)   # comments between parameters
            ps = [x.split(':', 1)[1].split('=')[0] for x in _split_top(params) if ':' in x]
            js = [_kt_type(x) for x in ps]
            rt = _kt_type(ret)
            sig = None if None in js or rt is None else '(' + ''.join(js) + ')' + rt
            line = s.count('\n', 0, m.start()) + 1
            out.setdefault(name, []).append((sig, len(ps), f"{os.path.relpath(p, ROOT)}:{line}"))
    return out


def _table(src):
    m = re.search(r'JNINativeMethod\s+allMethods\[\]\s*=\s*\{(.*?)\n\};', src or '', re.S)
    return re.findall(r'\{\s*"(\w+)"\s*,\s*"([^"]+)"', m.group(1)) if m else None


def _mismatches(table, kt):
    problems = []
    for name, sig in table:
        decls = kt.get(name)
        nparams = len(re.findall(r'\[*(?:L[^;]+;|[ZBCSIJFD])', sig.split(')')[0][1:]))
        if not decls:
            problems.append(f"`{name}{sig}` is registered natively but no Kotlin `external fun {name}` exists")
            continue
        if any(d[0] == sig for d in decls):
            continue
        known = [d for d in decls if d[0]]
        if known:
            problems.append(f"`{name}`: native registers `{sig}`, Kotlin declares " + ', '.join(f"`{d[0]}` at {d[2]}" for d in known))
        elif not any(d[1] == nparams for d in decls):
            problems.append(f"`{name}`: native takes {nparams} parameter(s), Kotlin declares "
                            + ', '.join(f"{d[1]} at {d[2]}" for d in decls))
    return problems


def jni_check(head_src, base_src, paths, labels=''):
    """The native method table (JNI.cpp allMethods) of the PR head against the Kotlin declarations, compared with the
    same check on the PR's base: only mismatches the PR ADDS are its problem (the base may already differ from the
    Kotlin copy used, e.g. when the newest sprint branch is not the one that ships with this native branch).
    One missing or mismatched entry makes RegisterNatives fail and the library does not load.
    Returns (prompt text, [new problem lines], result line)."""
    th = _table(head_src)
    if th is None:
        return '', [], 'no native method table in this PR'
    kt = kotlin_externals(paths)
    new_p = _mismatches(th, kt)
    tb = _table(base_src)
    old_p = _mismatches(tb, kt) if tb is not None else []
    added = [x for x in new_p if x not in old_p]
    res = (f"JNI table: {len(th)} native methods vs Kotlin ({labels or 'copies'}): "
           + (f"{len(added)} mismatch(es) added by this PR" if added else 'nothing added by this PR breaks it')
           + (f"; {len(old_p)} already on the base" if old_p else ''))
    text = ("## JNI table check (code, not a model)\nEvery entry of the native table `allMethods` (JNI.cpp) must match a "
            "Kotlin `external fun` with the same JNI signature, or RegisterNatives fails and the native library does not load. "
            f"Kotlin checked: {labels or ', '.join(os.path.relpath(p, ROOT) for p in paths)}.\n"
            + ('Mismatches this PR ADDS (the Kotlin side must change in the same release):\n'
               + '\n'.join('- ' + x for x in added) if added else '- this PR adds no mismatch')
            + (f"\nThe PR's BASE already has {len(old_p)} mismatch(es) with these Kotlin copies (so these copies are not the "
               "Kotlin that ships with this native branch; do not blame this PR for them): "
               + ', '.join(x.split('`')[1].split('(')[0] for x in old_p[:12]) if old_p else '')
            + '\n\n')
    return text, added, res
