"""Bitbucket Cloud WRITES for Night Shift (26 Oct): comments on pull requests and draft pull requests for verified
crash / ANR fixes. Only ever called from a board button (a person's click queues the job); nothing here runs on its own.

Token: ~/.config/nightshift/bitbucket_write.json {"email", "token"} when present (a bot account's token is best),
else the same bitbucket.json the PR review reads with. It needs the scopes read:repository, read:pullrequest and
write:pullrequest (Atlassian API token) or "Pull requests: Write" (app password). Branches are pushed with git over the
repo's own remote (the SSH key / credentials this Mac already uses), never with this token.

Safety: comments carry a hidden marker ([//]: # (nightshift-...)) so a re-run EDITS Night Shift's own comments
instead of adding new ones; PRs are always drafts, from a nightshift/... branch, and never merged here."""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import bitbucket

API = 'https://api.bitbucket.org/2.0'
WCFG = os.path.expanduser('~/.config/nightshift/bitbucket_write.json')


class BBError(RuntimeError):
    def __init__(self, status, msg):
        super().__init__(f'Bitbucket {status}: {msg}')
        self.status = status


def creds():
    c = dict(bitbucket.creds())                          # workspace / repo defaults + the read token
    if os.path.exists(WCFG):
        w = json.load(open(WCFG))
        c.update({k: w[k] for k in ('email', 'token') if w.get(k)})
    if c.get('relay') and not os.path.exists(WCFG):
        raise RuntimeError('this computer reads Bitbucket through the board host (no own token): posting needs a token '
                           'with write:pullrequest in ~/.config/nightshift/bitbucket_write.json')
    return c


def _req(method, url, body=None, c=None):
    c = c or creds()
    auth = base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json',
                                          **({'Content-Type': 'application/json'} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode('utf-8', 'replace')
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        txt = e.read().decode('utf-8', 'replace')
        try:
            msg = (json.loads(txt).get('error') or {}).get('message') or txt
        except ValueError:
            msg = txt
        if e.code in (401, 403):
            msg += (' — the Bitbucket token cannot write pull requests. Give Night Shift a token with the scopes '
                    'read:repository, read:pullrequest and write:pullrequest in ~/.config/nightshift/bitbucket_write.json '
                    '{"email": "...", "token": "..."}')
        raise BBError(e.code, msg[:600])


def _paged(url, c, limit=500):
    out = []
    while url and len(out) < limit:
        j = _req('GET', url, c=c)
        out += j.get('values') or []
        url = j.get('next')
    return out


def check(repo=None, c=None):
    """What this token can do, without writing anything: who it is, read access, and the scopes Bitbucket reports."""
    c = c or creds()
    repo = repo or c['repo']
    out = {'workspace': c['workspace'], 'repo': repo, 'write_token_file': os.path.exists(WCFG)}
    auth = base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode()
    req = urllib.request.Request(f"{API}/repositories/{c['workspace']}/{repo}/pullrequests?pagelen=1",
                                 headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out['read_pullrequests'] = True
            out['scopes'] = r.headers.get('X-OAuth-Scopes') or r.headers.get('x-oauth-scopes') or '(not reported for this token type)'
            out['accepted_scopes'] = r.headers.get('X-Accepted-OAuth-Scopes') or ''
    except urllib.error.HTTPError as e:
        out['read_pullrequests'] = False
        out['error'] = f'{e.code} {e.read().decode("utf-8", "replace")[:200]}'
    sc = str(out.get('scopes', '')).lower()
    out['can_write_pullrequests'] = ('pullrequest:write' in sc or 'write:pullrequest' in sc) if 'not reported' not in sc else 'unknown (try one post)'
    return out


# ------------------------------------------------------------------ comments
def marker(tag):
    return f'[//]: # (nightshift-{tag})'


def comments(repo, num, c=None):
    c = c or creds()
    return _paged(f"{API}/repositories/{c['workspace']}/{repo}/pullrequests/{num}/comments?pagelen=100", c)


def find_marked(existing, tag):
    m = marker(tag)
    for x in existing:
        if not x.get('deleted') and m in str((x.get('content') or {}).get('raw') or ''):
            return x
    return None


def upsert_comment(repo, num, tag, raw, inline=None, existing=None, c=None, dry=False):
    """Post the comment, or edit Night Shift's earlier one with the same tag. -> ('created'|'updated'|'same', id)."""
    c = c or creds()
    body_raw = raw.rstrip() + '\n\n' + marker(tag)
    old = find_marked(existing if existing is not None else comments(repo, num, c), tag)
    base = f"{API}/repositories/{c['workspace']}/{repo}/pullrequests/{num}/comments"
    if old:
        if str((old.get('content') or {}).get('raw') or '').strip() == body_raw.strip():
            return 'same', old.get('id')
        if dry:
            return 'would update', old.get('id')
        _req('PUT', f"{base}/{old['id']}", {'content': {'raw': body_raw}}, c)
        return 'updated', old.get('id')
    payload = {'content': {'raw': body_raw}}
    if inline:
        payload['inline'] = {'path': inline[0], 'to': int(inline[1])}
    if dry:
        return 'would create', None
    j = _req('POST', base, payload, c)
    return 'created', j.get('id')


def diff_lines(diff_text):
    """{path: set(new-file line numbers shown in the PR diff)}: only those lines can carry an inline comment."""
    out, path, n = {}, None, 0
    for ln in (diff_text or '').splitlines():
        if ln.startswith('+++ '):
            p = ln[4:].strip()
            path = None if p == '/dev/null' else re.sub(r'^b/', '', p)
            if path:
                out.setdefault(path, set())
            continue
        m = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', ln)
        if m:
            n = int(m.group(1))
            continue
        if path is None or ln.startswith(('diff --git', 'index ', '--- ')):
            continue
        if ln.startswith('+') or ln.startswith(' '):
            out[path].add(n)
            n += 1
        elif ln.startswith('\\'):
            continue
    return out


# ------------------------------------------------------------------ pull requests
def open_pr_for(repo, branch, c=None):
    c = c or creds()
    q = urllib.parse.quote(f'source.branch.name="{branch}" AND state="OPEN"')
    v = _paged(f"{API}/repositories/{c['workspace']}/{repo}/pullrequests?q={q}&pagelen=10", c, limit=10)
    return v[0] if v else None


def create_or_update_pr(repo, src, dst, title, desc, c=None, dry=False):
    """A DRAFT PR from src to dst, or the open one for src updated. -> (action, url, id)."""
    c = c or creds()
    base = f"{API}/repositories/{c['workspace']}/{repo}/pullrequests"
    old = open_pr_for(repo, src, c)
    if old:
        if dry:
            return 'would update', old['links']['html']['href'], old['id']
        _req('PUT', f"{base}/{old['id']}", {'title': title[:250], 'description': desc}, c)
        return 'updated', old['links']['html']['href'], old['id']
    if dry:
        return 'would create', '', None
    j = _req('POST', base, {'title': title[:250], 'description': desc, 'draft': True, 'close_source_branch': True,
                            'source': {'branch': {'name': src}}, 'destination': {'branch': {'name': dst}}}, c)
    if j.get('draft') is False:                        # this Bitbucket ignored the draft flag: say so in the job log
        print('⚠ Bitbucket opened it as a normal PR (draft not supported here): reviewers may be notified', flush=True)
    return 'created', ((j.get('links') or {}).get('html') or {}).get('href', ''), j.get('id')
