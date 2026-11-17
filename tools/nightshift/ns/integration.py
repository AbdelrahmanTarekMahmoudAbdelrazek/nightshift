"""Waiting for integration (26 Oct).

A native PR often needs a matching change in another repo: a JNI function added or its signature changed in JNI.cpp
must be DECLARED in Kotlin (java-common Player.kt `external fun`) and CALLED with the new arguments (the editor module,
java-common, gallerypicker...). Merged alone, the native side breaks the app (RegisterNatives fails for the whole table)
or the module stops compiling. PR Review used to say "nothing added breaks it" while the only caller still passed 5
arguments for 8 (#3211).

For each such change Night Shift keeps one item, integrations/<id>, shown on the board as "Waiting for integration":
  INT-3211-1  restoreTextLayers 5 -> 8 parameters
    java-common      declaration  found in PR #609 (branch text-animation-keyframe-based)
    android-video-editor-module  caller  MISSING (TextEngineExtensions.kt:709 still passes 5)
Where the other side lives is found WITHOUT the PR description: the function name is searched in the open PRs, the
branches with the same Jira key or branch name, and the most recently updated branches of every Kotlin repo; the
sprint branch tells whether it is merged. Re-checked on every PR review of that PR and every morning (sync).
Read-only everywhere: nothing is written to Bitbucket or Slack.
"""
import datetime as dt
import os
import re
import subprocess

from . import kotlinctx

RE_JNI_PARAM = re.compile(r'\[*(?:L[^;]+;|[ZBCSIJFD])')
STATUS_ORDER = ['missing', 'wrong', 'branch', 'pr', 'merged', 'not-needed']


def nparams(sig):
    return len(RE_JNI_PARAM.findall((sig or '()').split(')')[0][1:]))


def contract_changes(head_src, base_src):
    """JNI table entries this PR adds, changes or removes. -> [{name, kind, old, new}]"""
    th, tb = kotlinctx._table_any(head_src) or [], kotlinctx._table_any(base_src) or []   # incl. optional natives
    hd, bd = {}, {}
    for n, s in th:
        hd.setdefault(n, set()).add(s)
    for n, s in tb:
        bd.setdefault(n, set()).add(s)
    out = []
    for n in sorted(set(hd) | set(bd)):
        new, old = hd.get(n, set()), bd.get(n, set())
        if new == old:
            continue
        out.append({'name': n, 'kind': 'added' if not old else 'removed' if not new else 'changed',
                    'old': sorted(old)[0] if old else '', 'new': sorted(new)[0] if new else ''})
    return out


# ------------------------------------------------------------------ reading Kotlin/Java at one ref

def _git(args, cwd, timeout=300):
    return kotlinctx._git(args, cwd=cwd, timeout=timeout)


def _is_main(repo):
    from . import config
    try:
        return repo == config.profile()['main_repo']
    except Exception:
        return False


def _depth(repo):
    # the native repo is the local checkout (full history): never fetch shallow into it, that would make it shallow
    return [] if _is_main(repo) else ['--depth', '1']


def _clone(repo):
    if _is_main(repo):                               # 12 Nov: Kotlin PR -> native side reads the local checkout's objects
        from . import config
        return config.REPO
    path = os.path.join(kotlinctx.ROOT, f'int-{repo}')            # bare-ish cache for integration lookups only
    if not os.path.isdir(os.path.join(path, '.git')):
        os.makedirs(path, exist_ok=True)
        _git(['init', '-q'], cwd=path)
    return path


_FETCHED = {}          # (repo, ref) -> (time, sha): one fetch per ref per review, not one per changed function
_CANDS = {}            # (repo, pr id) -> (time, refs)


def _fetch(repo, ref):
    """Commit of `ref` (branch name) fetched shallowly into the cache. -> sha or None"""
    import time as _t
    hit = _FETCHED.get((repo, ref))
    if hit and _t.time() - hit[0] < 1800:
        return hit[1]
    sha = _fetch_now(repo, ref)
    _FETCHED[(repo, ref)] = (_t.time(), sha)
    return sha


def _fetch_now(repo, ref):
    path = _clone(repo)
    url = kotlinctx._remote_base() + repo + '.git'
    safe = re.sub(r'[^A-Za-z0-9._/-]', '_', ref)
    r = _git(['fetch', '-q'] + _depth(repo) + ['--no-tags', url, f'+refs/heads/{ref}:refs/int/{safe}'], cwd=path, timeout=600)
    if r.returncode:
        return None
    return _git(['rev-parse', f'refs/int/{safe}'], cwd=path).stdout.strip() or None


def _prefetch(repo, refs):
    """4 Nov: one `git fetch` for all candidate refs of a repo instead of one per ref (25 refs x 3 repos one by one
    took 14 of the 25 minutes of a PR review). Falls back to one by one if the batch fails (a ref deleted meanwhile)."""
    import time as _t
    todo = [r for r in refs if not (_FETCHED.get((repo, r)) and _t.time() - _FETCHED[(repo, r)][0] < 1800)]
    if not todo:
        return
    path = _clone(repo)
    url = kotlinctx._remote_base() + repo + '.git'
    safe = {r: re.sub(r'[^A-Za-z0-9._/-]', '_', r) for r in todo}
    res = _git(['fetch', '-q'] + _depth(repo) + ['--no-tags', url] + [f'+refs/heads/{r}:refs/int/{safe[r]}' for r in todo],
               cwd=path, timeout=900)
    if res.returncode:
        return                                       # _fetch() then goes one by one
    for r in todo:
        sha = _git(['rev-parse', '--verify', '-q', f'refs/int/{safe[r]}'], cwd=path).stdout.strip() or None
        _FETCHED[(repo, r)] = (_t.time(), sha)


# 12 Nov (PR #3226, 23 native functions + 2 map keys): every term used to cost one `git grep` per ref per repo, then
# one `git show` per file (23 x 25 refs x 3 repos ~ 1700 greps). Now prepare() names every term of the review once and
# each (repo, ref) is grepped ONCE for all of them; file texts are cached too.
_TERMS = {}            # repo -> terms of the current review
_IDX = {}              # (repo, sha, terms) -> {term: [files]}
_SHOW = {}             # (repo, sha, file) -> text
NATIVE_GLOBS = ['*.cpp', '*.cc', '*.h', '*.hpp']
KOTLIN_GLOBS = ['*.kt', '*.java']


def _globs(repo):
    from . import config
    try:
        main = config.profile()['main_repo']
    except Exception:
        main = 'video_gles3jni'
    return NATIVE_GLOBS if repo == main else KOTLIN_GLOBS


def set_terms(repos, terms):
    for r in repos:
        _TERMS[r] = set(_TERMS.get(r) or ()) | {t for t in terms if t}


def _index(repo, sha):
    terms = tuple(sorted(_TERMS.get(repo) or ()))
    k = (repo, sha, terms)
    if k in _IDX:
        return _IDX[k]
    idx = {}
    if terms:
        args = ['grep', '-I', '-w', '-F', '-l'] + [a for t in terms for a in ('-e', t)] + [sha, '--'] + _globs(repo)
        files = [l.split(':', 1)[1] for l in _git(args, cwd=_clone(repo), timeout=300).stdout.splitlines() if ':' in l]
        for f in files[:400]:
            txt = _text(repo, sha, f)
            for t in terms:
                if re.search(r'(?<![\w$])' + re.escape(t) + r'(?![\w$])', txt):
                    idx.setdefault(t, []).append(f)
    _IDX[k] = idx
    return idx


def _text(repo, sha, f):
    k = (repo, sha, f)
    if k not in _SHOW:
        _SHOW[k] = _git(['show', f'{sha}:{f}'], cwd=_clone(repo)).stdout
    return _SHOW[k]


def _files_with(repo, sha, name):
    if name in (_TERMS.get(repo) or ()):
        return {f: _text(repo, sha, f) for f in _index(repo, sha).get(name, [])[:40]}
    path = _clone(repo)
    r = _git(['grep', '-l', '-w', name, sha, '--'] + _globs(repo), cwd=path, timeout=120)
    files = [l.split(':', 1)[1] for l in r.stdout.splitlines() if ':' in l]
    return {f: _text(repo, sha, f) for f in files[:40]}


def _strip_comments(s):
    s = re.sub(r'/\*.*?\*/', lambda c: '\n' * c.group(0).count('\n'), s, flags=re.S)
    s = re.sub(r'//[^\n]*', '', s)
    # type arguments (HashMap<String, String>, mapOf<A, B>()): their commas are not parameter separators
    g = re.compile(r'(?<=[\w?])<[\w\s,.?*]*>')
    while True:
        t = g.sub(lambda c: '\n' * c.group(0).count('\n'), s)
        if t == s:
            return s
        s = t


def _args(s, i):
    """Top-level arguments of the call whose '(' is at s[i]. -> (count, end index)"""
    depth, n, cur, j = 0, 0, '', i
    while j < len(s):
        ch = s[j]
        if ch in '([{':
            depth += 1
            if depth == 1:
                j += 1
                continue
        elif ch in ')]}':
            depth -= 1
            if depth == 0:
                return n + (1 if cur.strip() else 0), j
        elif ch in '"\'':                                  # skip string literals
            q = ch
            j += 1
            while j < len(s) and s[j] != q:
                j += 2 if s[j] == '\\' else 1
        if depth == 1 and ch == ',':
            n += 1
            cur = ''
        elif depth >= 1:
            cur += ch
        j += 1
    return n, j


def declarations(texts, name):
    """[(n params, 'file:line')] of `external fun name(` / `native ... name(`."""
    out = []
    for f, t in texts.items():
        s = _strip_comments(t)
        for m in re.finditer(r'(?:external\s+fun|\bnative\b[^;(]*?)\s+' + re.escape(name) + r'\s*\(', s):
            n, _ = _args(s, m.end() - 1)
            out.append((n, f'{f}:{s.count(chr(10), 0, m.start()) + 1}'))
    return out


def calls(texts, name):
    """[(n args, 'file:line')] of calls to name( that are not its declaration."""
    out = []
    for f, t in texts.items():
        s = _strip_comments(t)
        for m in re.finditer(r'(?<![\w$])' + re.escape(name) + r'\s*\(', s):
            before = s[max(0, m.start() - 40):m.start()]
            if re.search(r'(fun|native[^;(]*)\s*$', before):
                continue
            n, _ = _args(s, m.end() - 1)
            out.append((n, f'{f}:{s.count(chr(10), 0, m.start()) + 1}'))
    return out


# ------------------------------------------------------------------ where the other side lives

def _candidates(repo, pr, log):
    import time as _t
    k = (repo, str((pr or {}).get('id')))
    hit = _CANDS.get(k)
    if hit and _t.time() - hit[0] < 1800:
        return hit[1]
    refs = _candidates_now(repo, pr, log)
    _CANDS[k] = (_t.time(), refs)
    return refs


def _candidates_now(repo, pr, log):
    """Refs worth looking at in `repo`: the sprint (merged), open PRs, branches with the same Jira key or branch name,
    the most recently updated ones. -> [(kind, ref, label)]"""
    from . import bitbucket
    import urllib.parse
    c = bitbucket.creds()
    out = []
    sprint = next(iter(kotlinctx._by_date(repo)), None)
    if sprint:
        out.append(('merged', sprint, sprint))
    try:
        for p in bitbucket.open_prs(repo=repo, main=repo):
            out.append(('pr', p['source'], f"PR #{p['num']} by {p['author']} ({p['source']})"))
    except Exception as e:
        log(f'integration: {repo}: open PRs not readable ({str(e)[:100]})')
    keys = set(re.findall(r'\b[A-Z][A-Z0-9]{1,9}-\d+\b', f"{pr.get('source', '')} {pr.get('title', '')}"))
    names = {pr.get('source', '')} | keys
    for q in [n for n in names if n][:4]:
        try:
            url = f"{bitbucket.API}/repositories/{c['workspace']}/{repo}/refs/branches?pagelen=20&q=" + urllib.parse.quote(f'name ~ "{q}"')
            for b in bitbucket._get(url, c=c).get('values') or []:
                out.append(('branch', b['name'], f"branch {b['name']}"))
        except Exception:
            pass
    try:                                            # 12 Nov: every branch touched in the last 30 days (was: newest 15;
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()   # object-fx fell off)
        url = f"{bitbucket.API}/repositories/{c['workspace']}/{repo}/refs/branches?sort=-target.date&pagelen=50"
        for b in bitbucket._get(url, c=c).get('values') or []:
            if str((b.get('target') or {}).get('date') or '') >= since[:19] or len(out) < 15:
                out.append(('branch', b['name'], f"branch {b['name']}"))
    except Exception:
        pass
    seen, uniq = set(), []
    for k, ref, label in out:                       # a ref keeps its best kind (merged > pr > branch)
        if ref and ref not in seen:
            seen.add(ref)
            uniq.append((k, ref, label))
    return uniq[:60]


def _rank(st):
    return STATUS_ORDER.index(st) if st in STATUS_ORDER else 0


def _jni_repos(cfg, repos):
    """29 Oct: only the repos that can call the engine's JNI (the image app, its editor module and the AI tools have
    their own native code): nightshift.yaml pr_review.integration_repos, else every profile repo."""
    want = [x.strip() for x in str(((cfg or {}).get('pr_review') or {}).get('integration_repos') or '').split(',') if x.strip()]
    return [r for r in repos if r in want] if want else repos


def check(change, repos, pr, log=print):
    """Look for the Kotlin side of one change in every repo. -> {repo: {'declaration': part, 'caller': part}}"""
    name, want = change['name'], nparams(change['new'])
    old = nparams(change['old']) if change['old'] else None
    parts = {}
    from concurrent.futures import ThreadPoolExecutor   # 4 Nov: every repo's refs fetched at once, repos in parallel
    with ThreadPoolExecutor(max_workers=max(1, len(repos))) as ex:
        list(ex.map(lambda r: _prefetch(r, [ref for _k, ref, _l in _candidates(r, pr, log)]), repos))
    for repo in repos:
        decl = {'status': 'missing', 'where': '', 'at': '', 'note': ''}
        call = {'status': 'missing', 'where': '', 'at': '', 'note': ''}
        seen_any = False
        for kind, ref, label in _candidates(repo, pr, log):
            sha = _fetch(repo, ref)
            if not sha:
                continue
            texts = _files_with(repo, sha, name)
            if not texts:
                continue
            seen_any = True
            for role, items, part in (('declaration', declarations(texts, name), decl), ('caller', calls(texts, name), call)):
                if not items:
                    continue
                good = [it for it in items if change['kind'] == 'removed' or it[0] == want]
                bad = [it for it in items if change['kind'] != 'removed' and it[0] != want]
                if change['kind'] == 'removed':
                    st = 'wrong'                         # still declared / called after the native side removed it
                    note = f"still uses {name} at {items[0][1]} (removed natively)"
                elif bad and not good:
                    st = 'wrong'
                    note = f"{bad[0][1]} passes {bad[0][0]}, the native side takes {want}"
                else:
                    st = kind
                    note = f"{good[0][1]} ({good[0][0]} parameters)" + (f"; still {bad[0][0]} at {bad[0][1]}" if bad else '')
                    if bad:
                        st = 'wrong'
                if _rank(st) > _rank(part['status']) or (part['status'] == 'missing'):
                    part.update(status=st, where=label, at=(good or bad or items)[0][1], note=note, ref=ref)
        if change['kind'] == 'removed':
            for part in (decl, call):
                if part['status'] == 'missing':
                    part.update(status='not-needed', note='nothing uses it any more')
        if not seen_any and repo != 'java-common':
            call.update(status='not-needed', note=f'{repo} does not use {name}')
            decl.update(status='not-needed', note='declared in java-common')
        if repo != 'java-common' and decl['status'] in ('missing',):
            decl.update(status='not-needed', note='declarations live in java-common')
        if change['kind'] == 'changed' and call['status'] == 'missing':
            call.update(status='not-needed', note='no caller in this repo')
        if change['kind'] == 'added' and call['status'] == 'missing':
            call['note'] = 'nothing calls it yet (the new feature stays unused; not breaking)'
        parts[repo] = {'declaration': decl, 'caller': call}
    # 12 Nov (PR #3226): the declaration lives in java-common, the caller in the editor module (Kotlin). One caller in
    # ANY repo is enough: the other repos' empty caller slot is "not needed", not "nothing calls it yet".
    callers = [(r, p['caller']) for r, p in parts.items() if p['caller']['status'] not in ('missing', 'not-needed', 'wrong')]
    if callers and change['kind'] != 'removed':
        r0, c0 = callers[0]
        for repo, p in parts.items():
            if p['caller']['status'] == 'missing':
                p['caller'].update(status='not-needed', note=f"called from {r0} ({c0.get('at') or c0.get('where')})")
    for repo, p in parts.items():
        decl, call = p['declaration'], p['caller']
        log(f"integration: {name} in {repo}: declaration {decl['status']}, caller {call['status']}"
            + (f" ({call['note'][:90]})" if call['note'] else ''))
    return parts


def _overall(change, parts):
    need = []
    for repo, p in parts.items():
        need.append(p['declaration']['status'])
        if not (change['kind'] == 'added' and p['caller']['status'] == 'missing'):
            need.append(p['caller']['status'])
    need = [s for s in need if s != 'not-needed']
    if not need:
        return 'ready'
    if any(s in ('missing', 'wrong') for s in need):
        return 'waiting'
    return 'merged' if all(s == 'merged' for s in need) else 'ready'


def withdraw(db, pr, keep=(), log=print):
    """4 Nov: a later commit of the PR dropped a native contract change (PR #3222 removed setOverlayMaskShapeParams):
    its integrations/ item must not keep saying 'waiting for integration'. -> number withdrawn"""
    from firebase_admin import firestore
    db = db or firestore.client()
    n = 0
    for d in db.collection('integrations').where('prKey', '==', str(pr['id'])).stream():
        x = d.to_dict() or {}
        if x.get('name') not in keep and x.get('status') not in ('merged', 'withdrawn'):
            d.reference.set({'status': 'withdrawn', 'note': f"no longer in the PR at {str(pr.get('head', ''))[:8]}",
                             'checkedAt': firestore.SERVER_TIMESTAMP}, merge=True)
            n += 1
    if n:
        log(f"PR #{pr['id']}: {n} integration item(s) withdrawn (the PR no longer changes that native function)")
    return n


def track(db, pr, head_src, base_src, cfg, log=print):
    """PR Review hook: one integrations/<id> item per contract change of this native PR. -> lines for the reviewers"""
    from firebase_admin import firestore
    changes = contract_changes(head_src, base_src)
    if not changes:
        return []
    db = db or firestore.client()
    from . import config
    prof = config.profile(cfg)
    repos = _jni_repos(cfg, [r for r in prof['repos'] if r != (pr.get('repo') or prof['main_repo'])])
    lines = []
    for i, ch in enumerate(changes, 1):
        parts = check(ch, repos, pr, log)
        doc_id = f"{pr.get('repo') or prof['main_repo']}-{pr.get('num', pr['id'])}-{ch['name']}"
        status = _overall(ch, parts)
        what = {'added': f"new native function {ch['name']} ({nparams(ch['new'])} parameters)",
                'changed': f"{ch['name']}: {nparams(ch['old'])} -> {nparams(ch['new'])} parameters",
                'removed': f"{ch['name']} removed natively"}[ch['kind']]
        db.collection('integrations').document(doc_id).set({
            'id': f"INT-{pr.get('num', pr['id'])}-{i}", 'pr': str(pr.get('num', pr['id'])), 'repo': pr.get('repo') or prof['main_repo'],
            'prKey': str(pr['id']), 'prTitle': pr.get('title', ''), 'author': pr.get('author', ''), 'prUrl': pr.get('url', ''),
            'name': ch['name'], 'kind': ch['kind'], 'old': ch['old'], 'new': ch['new'], 'what': what,
            'parts': parts, 'status': status, 'checkedAt': firestore.SERVER_TIMESTAMP}, merge=True)
        miss = [f"{r} {role}: {p[role]['status']} ({p[role]['note'] or p[role]['where']})"
                for r, p in parts.items() for role in ('declaration', 'caller') if p[role]['status'] in ('missing', 'wrong')]
        lines.append(f"INT-{pr.get('num', pr['id'])}-{i} {what}: " + ('; '.join(miss) if miss else 'Kotlin side found')
                     + f" -> {status}")
        log(f"PR #{pr['id']}: integration {lines[-1]}")
    return lines


def seed(db, cfg, log=print):
    """Every morning: reviewed native PRs whose head is in the local repo get their items too (no model, no review
    rerun), so PRs reviewed before this feature existed show up. -> number of PRs looked at"""
    from . import config
    prof = config.profile(cfg)
    main = prof['main_repo']
    jf = 'app/src/main/cpp/JNI/JNI.cpp'
    n = 0
    for d in db.collection('prs').stream():
        x = d.to_dict() or {}
        if (x.get('repo') or main) != main or not x.get('head') or x.get('state') in ('MERGED', 'DECLINED'):
            continue
        head, base = str(x['head']), str(x.get('mergeBase') or '')
        g = lambda ref: subprocess.run(['git', '-C', config.REPO, 'show', f'{ref}:{jf}'], capture_output=True, text=True, timeout=60)
        h = g(head)
        if h.returncode and x.get('source'):          # reviewed on someone else's computer: fetch its branch here once
            subprocess.run(['git', '-C', config.REPO, 'fetch', '--no-tags', kotlinctx._remote_base() + main + '.git',
                            f"+refs/heads/{x['source']}:refs/nightshift/pr/{d.id}"], capture_output=True, text=True, timeout=1800)
            h = g(head)
        if h.returncode or not base:
            continue
        b = g(base)
        if b.returncode or not contract_changes(h.stdout, b.stdout):
            continue
        pr = {'id': d.id, 'num': x.get('num') or d.id, 'repo': main, 'title': x.get('title', ''), 'author': x.get('author', ''),
              'url': x.get('url', ''), 'source': x.get('source', '')}
        try:
            track(db, pr, h.stdout, b.stdout, cfg, log=lambda t: None)
            n += 1
        except Exception as e:
            log(f'integration: PR #{d.id} not seeded ({str(e)[:120]})')
    if n:
        log(f'integration: {n} reviewed PR(s) checked for their Kotlin/Java side')
    return n


def recheck(db, cfg, log=print):
    """Every morning (sync): re-check every item that is not merged yet. The PR's own sources are not needed."""
    from firebase_admin import firestore
    from . import config
    prof = config.profile(cfg)
    try:
        seed(db, cfg, log)
    except Exception as e:
        log(f'integration: seeding skipped ({str(e)[:120]})')
    n = 0
    for d in db.collection('integrations').stream():
        x = d.to_dict() or {}
        if x.get('status') == 'merged':
            continue
        t = x.get('checkedAt')
        if t and hasattr(t, 'timestamp') and dt.datetime.now(dt.timezone.utc).timestamp() - t.timestamp() < 3600:
            continue                                   # just checked (seeded a minute ago)
        repos = _jni_repos(cfg, [r for r in prof['repos'] if r != x.get('repo')])
        pr = {'id': x.get('prKey'), 'num': x.get('pr'), 'source': '', 'title': x.get('prTitle', '')}
        ch = {k: x.get(k, '') for k in ('name', 'kind', 'old', 'new')}
        try:
            parts = check(ch, repos, pr, log=lambda t: None)
            d.reference.set({'parts': parts, 'status': _overall(ch, parts), 'checkedAt': firestore.SERVER_TIMESTAMP}, merge=True)
            n += 1
        except Exception as e:
            log(f"integration: {x.get('id')} not re-checked ({str(e)[:120]})")
    if n:
        log(f'integration: {n} item(s) waiting for integration re-checked')
    return n


KEY_RE = re.compile(r'(?:value_of|count|find|at|get_value|has_key)\s*\(\s*"([A-Za-z_][\w]{1,40})"')


def map_keys(diff):
    """4 Nov (PR #3222, 2nd commit): string keys the native side starts reading from a parameter map
    (value_of("sizeX"), parameters.count("cornerRadius")). -> sorted new keys"""
    add_, rem = set(), set()
    cur = ''
    for l in (diff or '').splitlines():
        if l.startswith('+++ '):
            cur = l[6:] if l.startswith('+++ b/') else ''
            continue
        if not cur.endswith(('.cpp', '.h', '.hpp', '.cc')):
            continue
        if l.startswith('+') and not l.startswith('+++'):
            add_ |= set(KEY_RE.findall(l))
        elif l.startswith('-') and not l.startswith('---'):
            rem |= set(KEY_RE.findall(l))
    return sorted(add_ - rem)


def track_keys(db, pr, diff, cfg, log=print):
    """New map keys read natively -> one integrations/ item: which Kotlin repo SENDS them (a put("key", ...) on the
    sprint, an open PR or a branch). Missing = the feature cannot be used from the app yet: waiting for integration,
    not a bug of this PR. -> (lines for the reviewers, item name or '')"""
    keys = map_keys(diff)
    if not keys:
        return [], ''
    from firebase_admin import firestore
    from . import config
    db = db or firestore.client()
    prof = config.profile(cfg)
    repos = _jni_repos(cfg, [r for r in prof['repos'] if r != (pr.get('repo') or prof['main_repo'])])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(repos))) as ex:
        list(ex.map(lambda r: _prefetch(r, [ref for _k, ref, _l in _candidates(r, pr, log)]), repos))
    parts, found = {}, set()
    for repo in repos:
        call = {'status': 'missing', 'where': '', 'at': '', 'note': ''}
        for kind, ref, label in _candidates(repo, pr, log):
            sha = _fetch(repo, ref)
            if not sha:
                continue
            hit = []
            for k in keys:
                for f, txt in _files_with(repo, sha, k).items():
                    # 12 Nov (PR #3226): Kotlin sends keys in many shapes, not only put("k", v): "k" to v (mapOf /
                    # hashMapOf), map["k"] = v, or as a plain argument (passBackgroundEffectParameter(id, "k", v, layer)).
                    # Any use of the exact string literal in code (comments stripped) counts as sending it.
                    m = re.search(r'"' + re.escape(k) + r'"', _strip_comments(txt))
                    if m:
                        hit.append((k, f"{f}:{txt.count(chr(10), 0, m.start()) + 1}"))
                        break
            found |= {k for k, _ in hit}          # 12 Nov: every ref counts (objTrackEveryFrame was only on object-fx,
            if hit and (_rank(kind) > _rank(call['status']) or call['status'] == 'missing'):   # a second 'pr' ref)
                got = {h for h, _ in hit}
                call.update(status=kind, where=label, at=hit[0][1], ref=ref,
                            note=f"sends {', '.join(sorted(got))}" + ('' if len(got) == len(keys) else
                                 f"; NOT {', '.join(k for k in keys if k not in got)}"))
        if call['status'] == 'missing':
            call['note'] = 'nothing sends these keys yet: the feature cannot be used from the app'
        parts[repo] = {'declaration': {'status': 'not-needed', 'where': '', 'at': '', 'note': 'map keys need no declaration'},
                       'caller': call}
    name = 'map keys ' + ', '.join(keys)
    missing = [k for k in keys if k not in found]
    status = 'waiting' if missing else 'ready'
    doc_id = f"{pr.get('repo') or prof['main_repo']}-{pr.get('num', pr['id'])}-keys"
    what = f"native code now reads map key(s) {', '.join(keys)}"
    db.collection('integrations').document(doc_id).set({
        'id': f"INT-{pr.get('num', pr['id'])}-K", 'pr': str(pr.get('num', pr['id'])), 'repo': pr.get('repo') or prof['main_repo'],
        'prKey': str(pr['id']), 'prTitle': pr.get('title', ''), 'author': pr.get('author', ''), 'prUrl': pr.get('url', ''),
        'name': name, 'kind': 'keys', 'old': '', 'new': ', '.join(keys), 'what': what,
        'parts': parts, 'status': status, 'checkedAt': firestore.SERVER_TIMESTAMP}, merge=True)
    line = (f"INT-{pr.get('num', pr['id'])}-K {what}: "
            + (f"no Kotlin repo sends {', '.join(missing)} yet (sprint, open PRs, recent branches checked) -> waiting for "
               "integration (background tracking only, not shown to the reviewers)." if missing
               else 'every key is sent by the Kotlin side')
            + f" -> {status}")
    log(f"PR #{pr['id']}: integration {line}")
    return [line], name


# ------------------------------------------------------------------ 12 Nov: which PR / branch goes with which, both ways

KT_KEY_RE = re.compile(r'"([A-Za-z_]\w{1,40})"\s+to\b|\[\s*"([A-Za-z_]\w{1,40})"\s*\]\s*=|put\w*\(\s*"([A-Za-z_]\w{1,40})"'
                       r'|Parameter\w*\([^()\n]*?"([A-Za-z_]\w{1,40})"')


def prepare(pr, head_src, base_src, diff, cfg, log=print):
    """Native PR: name every term of the review once (new / changed / removed JNI functions + new map keys) so each
    candidate ref of each Kotlin repo is grepped once. -> (names, keys, repos)"""
    from . import config
    prof = config.profile(cfg)
    repos = _jni_repos(cfg, [r for r in prof['repos'] if r != (pr.get('repo') or prof['main_repo'])])
    names = [c['name'] for c in contract_changes(head_src or '', base_src or '')] if head_src else []
    keys = map_keys(diff)
    set_terms(repos, names + keys)
    return names, keys, repos


def _best_refs(repo, pr, terms, log, top=12):
    """Candidate refs of `repo` ranked by how many of `terms` they use. -> [(score, kind, ref, label, hits)]"""
    cands = _candidates(repo, pr, log)
    _prefetch(repo, [ref for _k, ref, _l in cands])
    set_terms([repo], terms)
    out = []
    for kind, ref, label in cands:
        sha = _fetch(repo, ref)
        if not sha:
            continue
        idx = _index(repo, sha)
        hits = [t for t in terms if idx.get(t)]
        if hits:
            out.append((len(hits), kind, ref, label, hits))
    order = {'pr': 0, 'branch': 1, 'merged': 2}
    out.sort(key=lambda x: (-x[0], order.get(x[1], 3)))
    return out[:top]


def linked_work(pr, terms, repos, log=print):
    """Native PR -> the Kotlin PR/branch that implements its side: the ref using the most of the PR's new terms.
    -> (lines, {repo: best}) ; best = {'ref','label','kind','used','of','missing'}"""
    terms = sorted(set(t for t in terms if t))
    if not terms:
        return [], {}
    lines, best = [], {}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, len(repos))) as ex:
        res = dict(zip(repos, ex.map(lambda r: _best_refs(r, pr, terms, log), repos)))
    covered = {t for repo in repos for x in (res.get(repo) or []) for t in x[4]}
    where = {}                                      # a term only found off the best ref: say where
    for repo in repos:
        for x in (res.get(repo) or [])[1:]:
            for t in x[4]:
                if not res[repo] or t not in res[repo][0][4]:
                    where.setdefault(t, f"{repo} {x[3]}")
    for repo in repos:
        if not res.get(repo):
            continue
        sc, kind, ref, label, hits = res[repo][0]
        best[repo] = {'ref': ref, 'label': label, 'kind': kind, 'used': sc, 'of': len(terms), 'hits': hits[:40]}
        alt = '; next: ' + ', '.join(f"{l} ({s})" for s, _k, _r, l, _h in res[repo][1:3]) if len(res[repo]) > 1 else ''
        lines.append(f"{repo}: {label} uses {sc}/{len(terms)} of this PR's native names/keys{alt}")
    other = {t: w for t, w in where.items() if not any(t in b['hits'] for b in best.values())}
    if other:
        lines.append('only on other refs: ' + '; '.join(f'{t} in {w}' for t, w in list(other.items())[:12]))
    miss = [t for t in terms if t not in covered]
    if miss:
        lines.append(f"used by no Kotlin ref found: {', '.join(miss[:20])}")
    pnum = pr.get('num', pr.get('id'))
    log(f"PR #{pnum}: linked Kotlin work: " + (' | '.join(lines) if lines else 'none found'))
    return lines, best


def kotlin_terms(diff):
    """Kotlin PR diff -> (natives it declares or newly calls, map keys it newly sends)."""
    nat, keys = set(), set()
    for l in (diff or '').splitlines():
        if not l.startswith('+') or l.startswith('+++'):
            continue
        nat |= set(re.findall(r'external\s+fun\s+(\w+)', l)) | set(re.findall(r'\bnative\b[^;(]*?\s(\w+)\s*\(', l))
        nat |= set(re.findall(r'\bPlayer\.(\w+)\s*\(', l))
        for g in KT_KEY_RE.findall(l):
            keys |= {x for x in g if x}
    return sorted(nat), sorted(keys)


def native_for_kotlin(kpr, cfg, log=print):
    """Kotlin PR -> the native PR/branch it needs: refs of the main repo whose C++ has its new natives (JNI table) and
    keys (value_of("k")). Names no native ref has = an UnsatisfiedLinkError / a key nobody reads.
    -> {'native': [...], 'keys': [...], 'best': [...], 'missing': [...]} """
    from . import bitbucket, config
    prof = config.profile(cfg)
    main = prof['main_repo']
    diff = bitbucket.pr_diff(kpr['num'], repo=kpr['repo'])
    nat, keys = kotlin_terms(diff)
    # 16 Nov: only what is NEW for the native side counts. Player.x() calls of natives the release code already has
    # matched every native branch ("PR #320 -> #3224 (72/72)") and made each Kotlin PR take minutes.
    try:
        _jni = subprocess.run(['git', '-C', config.REPO, 'show', 'HEAD:app/src/main/cpp/JNI/JNI.cpp'],
                              capture_output=True, text=True, timeout=60).stdout
        have = {n for n, _s in (kotlinctx._table_any(_jni) or [])}
        nat = [n for n in nat if n not in have]
        _cpp = subprocess.run(['git', '-C', config.REPO, 'grep', '-h', '-o', '-E', r'"[A-Za-z_][A-Za-z0-9_]{1,40}"', 'HEAD',
                               '--', 'app/src/main/cpp/player', 'app/src/main/cpp/video'], capture_output=True, text=True,
                              timeout=120).stdout
        known_keys = {x.strip('"') for x in _cpp.split()}
        keys = [k for k in keys if k not in known_keys]
    except Exception as e:
        log(f"{kpr['repo']} PR #{kpr['num']}: native baseline not read ({str(e)[:80]}); all names checked")
    terms = nat + keys
    if not terms:
        return {'native': [], 'keys': [], 'best': [], 'missing': []}
    best = _best_refs(main, kpr, terms, log)
    found = set(t for b in best for t in b[4])
    declared = set(re.findall(r'^\+.*?(?:external\s+fun|\bnative\b[^;(]*?)\s+(\w+)\s*\(', diff or '', re.M))
    res = {'native': nat, 'keys': keys, 'missing': [t for t in terms if t not in found and (t in declared or t in keys)],
           'best': [{'label': l, 'ref': r, 'kind': k, 'used': s, 'of': len(terms)} for s, k, r, l, _h in best]}
    log(f"{kpr['repo']} PR #{kpr['num']}: native side: "
        + (', '.join(f"{b['label']} ({b['used']}/{b['of']})" for b in res['best']) or 'none found')
        + (f"; no native ref has {', '.join(res['missing'][:12])}" if res['missing'] else ''))
    return res


def link_kotlin_prs(db, cfg, log=print):
    """Every morning (sync): each open Kotlin PR -> its native PR/branch, saved on prlinks/<repo>-<num>."""
    from firebase_admin import firestore
    from . import bitbucket, config
    prof = config.profile(cfg)
    n = 0
    for repo in _jni_repos(cfg, [r for r in prof['repos'] if r != prof['main_repo']]):
        try:
            prs = bitbucket.open_prs(repo=repo, main=prof['main_repo'])
        except Exception as e:
            log(f'prlink: {repo}: open PRs not readable ({str(e)[:100]})')
            continue
        for kp in prs:
            try:
                r = native_for_kotlin(kp, cfg, log)
            except Exception as e:
                log(f"prlink: {repo} PR #{kp['num']} skipped ({str(e)[:120]})")
                continue
            if not (r['native'] or r['keys']):
                continue
            (db or firestore.client()).collection('prlinks').document(f"{repo}-{kp['num']}").set({
                'repo': repo, 'pr': str(kp['num']), 'title': kp.get('title', ''), 'author': kp.get('author', ''),
                'url': kp.get('url', ''), 'source': kp.get('source', ''), **r, 'checkedAt': firestore.SERVER_TIMESTAMP}, merge=True)
            n += 1
    log(f'prlink: {n} Kotlin PR(s) linked to their native side')
    return n
