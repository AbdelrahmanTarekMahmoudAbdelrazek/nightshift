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
    th, tb = kotlinctx._table(head_src) or [], kotlinctx._table(base_src) or []
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


def _clone(repo):
    path = os.path.join(kotlinctx.ROOT, f'int-{repo}')            # bare-ish cache for integration lookups only
    if not os.path.isdir(os.path.join(path, '.git')):
        os.makedirs(path, exist_ok=True)
        _git(['init', '-q'], cwd=path)
    return path


def _fetch(repo, ref):
    """Commit of `ref` (branch name) fetched shallowly into the cache. -> sha or None"""
    path = _clone(repo)
    url = kotlinctx._remote_base() + repo + '.git'
    safe = re.sub(r'[^A-Za-z0-9._/-]', '_', ref)
    r = _git(['fetch', '-q', '--depth', '1', '--no-tags', url, f'+refs/heads/{ref}:refs/int/{safe}'], cwd=path, timeout=600)
    if r.returncode:
        return None
    return _git(['rev-parse', f'refs/int/{safe}'], cwd=path).stdout.strip() or None


def _files_with(repo, sha, name):
    path = _clone(repo)
    r = _git(['grep', '-l', '-w', name, sha, '--', '*.kt', '*.java'], cwd=path, timeout=120)
    files = [l.split(':', 1)[1] for l in r.stdout.splitlines() if ':' in l]
    return {f: _git(['show', f'{sha}:{f}'], cwd=path).stdout for f in files[:40]}


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
    try:
        url = f"{bitbucket.API}/repositories/{c['workspace']}/{repo}/refs/branches?sort=-target.date&pagelen=15"
        for b in bitbucket._get(url, c=c).get('values') or []:
            out.append(('branch', b['name'], f"branch {b['name']}"))
    except Exception:
        pass
    seen, uniq = set(), []
    for k, ref, label in out:                       # a ref keeps its best kind (merged > pr > branch)
        if ref and ref not in seen:
            seen.add(ref)
            uniq.append((k, ref, label))
    return uniq[:25]


def _rank(st):
    return STATUS_ORDER.index(st) if st in STATUS_ORDER else 0


def check(change, repos, pr, log=print):
    """Look for the Kotlin side of one change in every repo. -> {repo: {'declaration': part, 'caller': part}}"""
    name, want = change['name'], nparams(change['new'])
    old = nparams(change['old']) if change['old'] else None
    parts = {}
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


def track(db, pr, head_src, base_src, cfg, log=print):
    """PR Review hook: one integrations/<id> item per contract change of this native PR. -> lines for the reviewers"""
    from firebase_admin import firestore
    changes = contract_changes(head_src, base_src)
    if not changes:
        return []
    db = db or firestore.client()
    from . import config
    prof = config.profile(cfg)
    repos = [r for r in prof['repos'] if r != (pr.get('repo') or prof['main_repo'])]
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
        repos = [r for r in prof['repos'] if r != x.get('repo')]
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
