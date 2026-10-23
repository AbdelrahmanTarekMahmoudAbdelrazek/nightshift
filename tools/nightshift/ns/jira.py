"""Read-only Jira Cloud access for the Card Issue tool: one card's fields, description, comments and attachments.
Token in ~/.config/nightshift/jira.json: {"base_url": "https://<org>.atlassian.net", "email", "token"}.
A classic API token works on the site URL; a scoped token (read:jira-work, read:jira-user) works through
api.atlassian.com, which this module falls back to by itself. Nothing here writes to Jira."""
import base64
import json
import os
import re
import urllib.error
import urllib.request

CFG = os.path.expanduser('~/.config/nightshift/jira.json')
KEY_RE = re.compile(r'\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b')


BB = os.path.expanduser('~/.config/nightshift/bitbucket.json')


def creds():
    """jira.json if present; else the Atlassian token already saved for Bitbucket (one token can cover both) plus
    sources.jira_base_url from nightshift.yaml."""
    if os.path.exists(CFG):
        c = json.load(open(CFG))
    elif os.path.exists(BB):
        b = json.load(open(BB))
        from . import config
        cf = config.load(); url = ((cf.get('integrations') or {}).get('jira_base_url') or (cf.get('sources') or {}).get('jira_base_url') or '').strip()
        if not url:
            raise RuntimeError('Jira site unknown: set integrations.jira_base_url in nightshift.yaml (https://<org>.atlassian.net)')
        c = {'base_url': url, 'email': b.get('email', ''), 'token': b.get('token', '')}
    else:
        raise RuntimeError('no Atlassian token on the Mac (~/.config/nightshift/bitbucket.json or jira.json)')
    for k in ('base_url', 'email', 'token'):
        if not c.get(k):
            raise RuntimeError(f'jira.json has no "{k}"')
    c['base_url'] = c['base_url'].rstrip('/')
    return c


def card_key(text):
    m = KEY_RE.search(str(text or '').upper())
    if not m:
        try:
            from . import config as _c
            ex = _c.profile()['jira_keys'][0]
        except Exception:
            ex = 'MZ'
        raise RuntimeError(f'no Jira key (like {ex}-1234) in {text!r}')
    return m.group(1)


def _req(url, c, raw=False):
    auth = base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode()
    r = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}', 'Accept': '*/*' if raw else 'application/json'})
    with urllib.request.urlopen(r, timeout=120) as resp:
        body = resp.read()
    return body if raw else json.loads(body.decode('utf-8', 'replace'))


def _get_issue(c, path):
    """Try the site URL (classic token), then api.atlassian.com/ex/jira/<cloudId> (scoped token)."""
    tried = []
    for root in [c['base_url'] + '/rest/api/3', None]:
        if root is None:
            try:
                cloud = json.loads(urllib.request.urlopen(c['base_url'] + '/_edge/tenant_info', timeout=30).read())['cloudId']
            except Exception as e:
                tried.append(f'cloud id lookup failed ({e})')
                break
            root = f'https://api.atlassian.com/ex/jira/{cloud}/rest/api/3'
        try:
            return _req(root + path, c), root
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403, 404):
                raise
            tried.append(f'{root.split("/rest")[0]} -> {e.code}')
    raise RuntimeError('Jira refused the Atlassian token (' + '; '.join(tried) + '). The token needs Jira read access: '
                       'a classic API token, or a scoped one with read:jira-work. 404 can also mean this account cannot see the card.')


def adf_text(n, depth=0):
    """Atlassian Document Format -> plain text (paragraphs, lists, code, mentions)."""
    if n is None:
        return ''
    if isinstance(n, str):
        return n
    if isinstance(n, list):
        return ''.join(adf_text(x, depth) for x in n)
    t = n.get('type')
    kids = adf_text(n.get('content'), depth + (1 if t in ('bulletList', 'orderedList') else 0))
    if t == 'text':
        return n.get('text', '')
    if t in ('mention', 'emoji'):
        return (n.get('attrs') or {}).get('text', '')
    if t == 'hardBreak':
        return '\n'
    if t in ('paragraph', 'heading', 'codeBlock', 'blockquote'):
        return kids.strip('\n') + '\n\n'
    if t == 'listItem':
        return '  ' * max(0, depth - 1) + '- ' + kids.strip() + '\n'
    if t in ('mediaSingle', 'mediaGroup', 'media'):
        return '[attachment]\n'
    return kids


def get_card(text):
    c = creds()
    key = card_key(text)
    j, root = _get_issue(c, f'/issue/{key}?fields=summary,description,issuetype,priority,status,reporter,created,environment,attachment,comment,labels,components,fixVersions,versions&expand=renderedFields')
    f = j.get('fields') or {}
    desc = adf_text(f.get('description')) if isinstance(f.get('description'), dict) else (f.get('description') or '')
    env = adf_text(f.get('environment')) if isinstance(f.get('environment'), dict) else (f.get('environment') or '')
    comments = [{'author': (x.get('author') or {}).get('displayName', ''), 'created': x.get('created', ''),
                 'text': adf_text(x.get('body')) if isinstance(x.get('body'), dict) else str(x.get('body') or '')}
                for x in ((f.get('comment') or {}).get('comments') or [])][-8:]
    att = [{'id': a.get('id'), 'name': a.get('filename', ''), 'mime': a.get('mimeType', ''), 'size': a.get('size', 0),
            'url': a.get('content', '')} for a in (f.get('attachment') or [])]
    return {'key': key, 'url': f"{c['base_url']}/browse/{key}", 'title': f.get('summary', ''),
            'type': (f.get('issuetype') or {}).get('name', ''), 'priority': (f.get('priority') or {}).get('name', ''),
            'status': (f.get('status') or {}).get('name', ''), 'reporter': (f.get('reporter') or {}).get('displayName', ''),
            'created': f.get('created', ''), 'labels': f.get('labels') or [],
            'versions': [v.get('name') for v in (f.get('versions') or [])], 'components': [v.get('name') for v in (f.get('components') or [])],
            'apiRoot': root, 'description': desc.strip()[:20000], 'environment': env.strip()[:4000], 'comments': comments, 'attachments': att}


def download(att, path, root=None):
    """Attachment bytes; through the same API root that read the card (works for classic and scoped tokens)."""
    c = creds()
    url = f"{root}/attachment/content/{att['id']}" if root and att.get('id') else att['url']
    data = _req(url, c, raw=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return len(data)
