"""Read-only Crashlytics client (steps 1-2: detect + collect).

Uses the same API and the same login as the Firebase CLI on this Mac (`firebase login`), so it needs no new
credentials and changes nothing in the Firebase project: every call here is a GET.
  issue   GET /v1alpha/projects/{num}/apps/{app}/issues/{id}
  events  GET /v1alpha/projects/{num}/apps/{app}/events?filter.issue.id=..&filter.version.display_names=..
  reports GET /v1alpha/projects/{num}/apps/{app}/reports/{topVersions|topAndroidDevices|topOperatingSystems|topIssues}
Raw responses are saved under out/raw/<issue>/ so the parser can be checked against what the API really returned.
"""
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request

ORIGIN = 'https://firebasecrashlytics.googleapis.com/v1alpha'
CLI_CLIENT_ID = '563584335869-fgrhgmd47bqnekij5i8b5pr03ho849e6.apps.googleusercontent.com'   # public Firebase CLI OAuth client
CLI_CLIENT_SECRET = 'j9iVZfS8kkCEFUPaAeJV0sAi'                                              # (installed-app secret, not confidential)
CONFIGSTORE = os.path.expanduser('~/.config/configstore/firebase-tools.json')
RE_ISSUE = re.compile(r'issues/([0-9a-f]{32})')


def issue_id_from(s: str) -> str:
    m = RE_ISSUE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r'[0-9a-f]{32}', s.strip()):
        return s.strip()
    raise SystemExit(f'not a Crashlytics issue id or link: {s}')


_token = None


_token_at = 0.0


def token(force=False) -> str:
    """Access token from the Firebase CLI refresh token. Access tokens live 1 hour: refresh after 45 min (a long
    sync used to keep one token for hours and every call after the first hour failed with 401)."""
    global _token, _token_at
    import time
    if _token and not force and time.time() - _token_at < 45 * 60:
        return _token
    if not os.path.exists(CONFIGSTORE):
        raise SystemExit('Firebase CLI is not logged in on this machine (run: firebase login)')
    tok = json.load(open(CONFIGSTORE)).get('tokens', {})
    rt = tok.get('refresh_token')
    if not rt:
        raise SystemExit('no refresh token in the Firebase CLI config; run: firebase login --reauth')
    body = urllib.parse.urlencode({'client_id': CLI_CLIENT_ID, 'client_secret': CLI_CLIENT_SECRET,
                                   'refresh_token': rt, 'grant_type': 'refresh_token'}).encode()
    with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=body), timeout=30) as r:
        _token = json.load(r)['access_token']
    _token_at = __import__('time').time()
    return _token


def _get(path, params=None):
    q = urllib.parse.urlencode(params or [], doseq=True)
    url = f'{ORIGIN}{path}' + (f'?{q}' if q else '')
    import time
    refreshed = False
    for attempt in range(5):
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token()}', 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and not refreshed:
                refreshed = True
                token(force=True)
                continue                                  # token expired: refresh once and retry
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            body = ' '.join(e.read().decode(errors='replace').split())
            raise SystemExit(f'Crashlytics API {e.code} on {path.split("/")[-1]}: {body[:400]}')
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:   # flaky Wi-Fi: reset / TLS timeout
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def _base(app_id):
    return f"/projects/{app_id.split(':')[1]}/apps/{app_id}"


def _interval(days):
    end = dt.datetime.utcnow().replace(microsecond=0)
    return [('filter.interval.start_time', (end - dt.timedelta(days=days)).isoformat() + 'Z'),
            ('filter.interval.end_time', end.isoformat() + 'Z')]


def get_issue(app_id, issue):
    return _get(f'{_base(app_id)}/issues/{issue}')


def report(app_id, name, issue=None, versions=None, days=30, page_size=25):
    p = _interval(days) + [('page_size', page_size)]
    if issue:
        p.append(('filter.issue.id', issue))
    for v in versions or []:
        p.append(('filter.version.display_names', v))
    return _get(f'{_base(app_id)}/reports/{name}', p)


def list_events(app_id, issue, versions=None, days=30, page_size=20):
    p = _interval(days) + [('filter.issue.id', issue), ('page_size', page_size)]
    for v in versions or []:
        p.append(('filter.version.display_names', v))
    return _get(f'{_base(app_id)}/events', p).get('events', [])


def release_display_names(app_id, issue, releases, days):
    """Version display names (e.g. '1.25.1 (800054867)') for this issue, restricted to the configured releases."""
    rep = report(app_id, 'topVersions', issue=issue, days=days, page_size=50)
    names = []
    for g in rep.get('groups', []):
        dn = ((g.get('version') or {}).get('displayName')) or g.get('displayName') or ''
        if dn and (not releases or dn in releases or (dn.split(' ')[0] in releases and '-' not in dn.split(' ')[0])):
            names.append(dn)
    return names, rep


# ---------------------------------------------------------------- normalisation (defensive: field names vary by platform)

def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def frames_of(thread):
    out = []
    for f in thread.get('frames', []) or []:
        sym = f.get('symbol') or f.get('function') or ''
        lib = f.get('library') or f.get('owner') or f.get('module') or ''
        fil = f.get('file') or ''
        line = f.get('line')
        out.append({'lib': os.path.basename(lib) if lib else '', 'func': sym if sym and not str(sym).isdigit() else '', 'file': fil, 'line': line,
                    'offset': f.get('offset'), 'address': f.get('address'), 'blamed': bool(f.get('blamed'))})
    return out


def crashed_thread(event):
    """The thread that crashed: prefer explicit crashed/blamed flags; fall back to exceptions[0] or the first thread."""
    threads = event.get('threads') or []
    for t in threads:
        if t.get('crashed') or t.get('blamed') or t.get('crashing'):
            return t
    exc = event.get('exceptions') or []
    if exc:
        return exc[0] if exc[0].get('frames') else (exc[-1] if exc[-1].get('frames') else exc[0])
    errs = event.get('errors') or []
    if errs:
        return errs[0]
    return threads[0] if threads else {}


def logs_of(event):
    lines = []
    for l in event.get('logs') or []:
        msg = l.get('message') or l.get('text') or ''
        ts = l.get('logTime') or l.get('timestamp') or ''
        lines.append(f"{ts[11:23] if len(ts) > 19 else ts} {msg}".strip())
    for b in event.get('breadcrumbs') or []:
        title = b.get('title') or b.get('name') or ''
        ts = b.get('eventTime') or b.get('timestamp') or ''
        params = b.get('params') or {}
        lines.append(f"{ts[11:23] if len(ts) > 19 else ts} [event] {title} {json.dumps(params) if params else ''}".strip())
    return sorted(lines, reverse=True)


def summarise_event(e):
    t = crashed_thread(e)
    dev = e.get('device') or {}
    osv = e.get('operatingSystem') or {}
    ver = e.get('version') or {}
    return {
        'name': e.get('name'), 'time': e.get('eventTime') or e.get('receivedTime'),
        'version': ver.get('displayName') or ver.get('displayVersion'), 'version_code': ver.get('buildVersion'),
        'device': ' '.join(x for x in [dev.get('manufacturer'), dev.get('marketingName') or dev.get('model')] if x),
        'os': osv.get('displayName') or osv.get('displayVersion'),
        'process_state': e.get('processState'), 'signal': (t.get('title') or t.get('exceptionType') or t.get('signal') or ''),
        'subtitle': t.get('subtitle') or t.get('exceptionMessage') or t.get('reason') or '',
        'frames': frames_of(t), 'logs': logs_of(e), 'keys': {k.get('key'): k.get('value') for k in (e.get('customKeys') or []) if isinstance(k, dict)},
    }


def pull(app_id, issue, releases, days=30, n_events=20, raw_dir=None):
    iss = get_issue(app_id, issue)
    versions, vrep = release_display_names(app_id, issue, releases, days)
    events = list_events(app_id, issue, versions or None, days, n_events) if (versions or not releases) else []
    devices = report(app_id, 'topAndroidDevices', issue=issue, versions=versions, days=days)
    oses = report(app_id, 'topOperatingSystems', issue=issue, versions=versions, days=days)
    if raw_dir:
        os.makedirs(raw_dir, exist_ok=True)
        for name, obj in [('issue', iss), ('topVersions', vrep), ('events', events), ('devices', devices), ('os', oses)]:
            json.dump(obj, open(os.path.join(raw_dir, f'{name}.json'), 'w'), indent=1)
    return iss, versions, vrep, [summarise_event(e) for e in events], devices, oses


def counts(rep, key):
    out = {}
    for g in rep.get('groups', []) or []:
        dn = ((g.get(key) or {}).get('displayName')) or g.get('displayName') or '?'
        m = g.get('metrics') or [{}]
        m = m[0] if isinstance(m, list) else m
        out[dn] = int(m.get('eventsCount') or m.get('events') or 0)
    return out


def users(rep):
    tot = 0
    for g in rep.get('groups', []) or []:
        m = g.get('metrics') or [{}]
        m = m[0] if isinstance(m, list) else m
        tot += int(m.get('impactedUsersCount') or m.get('users') or 0)
    return tot
