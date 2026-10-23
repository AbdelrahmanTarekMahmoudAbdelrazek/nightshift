"""Read-only Bitbucket Cloud access for PR review: open PRs, their commits and diff. Token in
~/.config/nightshift/bitbucket.json: {"email", "token", "workspace", "repo"} (API token with read:repository and
read:pullrequest scopes). Nothing here writes to Bitbucket."""
import base64
import json
import os
import urllib.parse
import urllib.request

CFG = os.path.expanduser('~/.config/nightshift/bitbucket.json')
API = 'https://api.bitbucket.org/2.0'


def creds():
    if not os.path.exists(CFG):
        raise RuntimeError('no Bitbucket token: create ~/.config/nightshift/bitbucket.json (see the PR Review page)')
    c = json.load(open(CFG))
    for k in ('email', 'token'):
        if not c.get(k):
            raise RuntimeError(f'bitbucket.json has no "{k}"')
    c.setdefault('workspace', 'mitrotek')
    c.setdefault('repo', 'video_gles3jni')
    return c


def _get(url, raw=False, c=None):
    c = c or creds()
    auth = base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode()
    req = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}', 'Accept': 'application/json' if not raw else 'text/plain'})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode('utf-8', 'replace')
    return body if raw else json.loads(body)


def _paged(url, c, limit=200):
    out = []
    while url and len(out) < limit:
        j = _get(url, c=c)
        out += j.get('values') or []
        url = j.get('next')
    return out


def key(repo, num, main=None):
    """Board / file key of a PR: the plain number for the main repo (as before), '<repo>-<number>' for the others."""
    return str(num) if not repo or repo == (main or creds()['repo']) else f'{repo}-{num}'


def parse_key(k, main=None):
    """'512' -> (main repo, 512); 'android-video-editor-module-512' -> ('android-video-editor-module', 512)."""
    k = str(k).strip()
    if '-' in k and k.rsplit('-', 1)[1].isdigit():
        return k.rsplit('-', 1)[0], int(k.rsplit('-', 1)[1])
    return (main or creds()['repo']), int(k)


def _row(p, repo=None, main=None):
    repo = repo or ((p.get('destination') or {}).get('repository') or {}).get('name') or None
    return {'id': key(repo, p['id'], main), 'num': p['id'], 'repo': repo or main or '', 'title': p.get('title', ''), 'description': (p.get('description') or '')[:8000],
            'author': (p.get('author') or {}).get('display_name', ''),
            'source': ((p.get('source') or {}).get('branch') or {}).get('name', ''),
            'dest': ((p.get('destination') or {}).get('branch') or {}).get('name', ''),
            'head': ((p.get('source') or {}).get('commit') or {}).get('hash', ''),
            'dest_commit': ((p.get('destination') or {}).get('commit') or {}).get('hash', ''),
            'updated': p.get('updated_on', ''), 'created': p.get('created_on', ''),
            'url': ((p.get('links') or {}).get('html') or {}).get('href', ''),
            'comments': p.get('comment_count', 0), 'state': p.get('state', ''), 'draft': bool(p.get('draft'))}


def open_prs(repo=None, main=None):
    c = creds()
    repo = repo or c['repo']
    main = main or c['repo']
    base = f"{API}/repositories/{c['workspace']}/{repo}/pullrequests"
    return [_row(p, repo, main) for p in _paged(base + '?state=OPEN&pagelen=50', c)]


def open_prs_all(repos=None, main=None, log=print):
    """Open PRs of every repo in the profile's review list (main repo keys stay plain numbers). A repo that cannot be
    read is skipped with a log line, so one missing permission never stops the others."""
    c = creds()
    main = main or c['repo']
    out = []
    for r in (repos or [main]):
        try:
            rows = open_prs(r, main)
            out += rows
            if r != main:
                log(f'Bitbucket: {r}: {len(rows)} open PR(s)')
        except Exception as e:
            log(f'Bitbucket: {r}: cannot read PRs ({str(e)[:120]})')
            if r == main:
                raise
    return out


def get_pr(pr_id, repo=None, main=None):
    """One PR by number or key, whatever its state or age (for PRs added to the board by link)."""
    c = creds()
    main = main or c['repo']
    if repo is None:
        repo, pr_id = parse_key(pr_id, main)
    return _row(_get(f"{API}/repositories/{c['workspace']}/{repo}/pullrequests/{int(pr_id)}", c=c), repo, main)


def pr_commits(pr_id, repo=None):
    c = creds()
    url = f"{API}/repositories/{c['workspace']}/{repo or c['repo']}/pullrequests/{pr_id}/commits?pagelen=50"
    return [{'hash': x['hash'], 'message': (x.get('message') or '')[:300], 'date': x.get('date', '')} for x in _paged(url, c)]


def pr_diff(pr_id, repo=None):
    c = creds()
    return _get(f"{API}/repositories/{c['workspace']}/{repo or c['repo']}/pullrequests/{pr_id}/diff", raw=True, c=c)


def branches(limit=40, query=None):
    """Most recently updated branches (or those whose name contains `query`): name, last commit. Read-only."""
    c = creds()
    url = f"{API}/repositories/{c['workspace']}/{c['repo']}/refs/branches?sort=-target.date&pagelen=50"
    if query:
        url += '&q=' + urllib.parse.quote(f'name ~ "{query}"')
    out = []
    for b in _paged(url, c, limit=limit)[:limit]:
        t = b.get('target') or {}
        out.append({'name': b.get('name', ''), 'hash': (t.get('hash') or '')[:10], 'date': t.get('date', ''),
                    'author': ((t.get('author') or {}).get('user') or {}).get('display_name') or (t.get('author') or {}).get('raw', '').split('<')[0].strip(),
                    'message': (t.get('message') or '').strip().splitlines()[0][:120] if t.get('message') else ''})
    return out
