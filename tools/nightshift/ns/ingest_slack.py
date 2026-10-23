"""Free ingestion #1: Crashlytics -> Slack alerts (built-in integration) -> this poller -> case stubs in Firestore.

Needs a Slack bot token with channels:history + channels:read in $SLACK_BOT_TOKEN and the alert channel id in
nightshift.yaml (integrations.crashlytics_alert_channel_id). Stdlib only.
"""
import json
import os
import re
import urllib.parse
import urllib.request

RE_ISSUE = re.compile(r'crashlytics/app/[^/\s]+/issues/([0-9a-f]{32})')
RE_KIND = re.compile(r'\b(ANR|crash|fatal|non-fatal)\b', re.I)


def _api(method, **params):
    tok = os.environ.get('SLACK_BOT_TOKEN')
    if not tok:
        raise SystemExit('SLACK_BOT_TOKEN not set')
    req = urllib.request.Request(f'https://slack.com/api/{method}?' + urllib.parse.urlencode(params),
                                 headers={'Authorization': f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if not data.get('ok'):
        raise RuntimeError(f'slack {method}: {data.get("error")}')
    return data


def fetch_alerts(channel_id: str, oldest: str = '0', limit: int = 200):
    """Return [{issue_id, kind, title, ts, text, permalink}] for Crashlytics alert messages in the channel."""
    out = []
    for m in _api('conversations.history', channel=channel_id, oldest=oldest, limit=limit).get('messages', []):
        text = m.get('text', '') + ' ' + json.dumps(m.get('attachments', []) + m.get('blocks', []))
        ids = set(RE_ISSUE.findall(text))
        if not ids:
            continue
        kind = 'ANR' if re.search(r'\bANR\b', text) else 'CRASH'
        title = (m.get('attachments') or [{}])[0].get('title') or m.get('text', '')[:120]
        for iid in ids:
            out.append({'issue_id': iid, 'kind': kind, 'title': title, 'ts': m.get('ts'), 'text': m.get('text', '')[:500]})
    return out


def upsert_cases(db, alerts, package):
    """Create a stub case per new issue id, status 'new', so it appears on the board and can be triaged."""
    from firebase_admin import firestore
    n = 0
    for a in alerts:
        ref = db.collection('cases').document(a['issue_id'])
        if ref.get().exists:
            continue
        ref.set({'id': a['issue_id'], 'kind': a['kind'], 'title': a['title'], 'status': 'new', 'source': 'crashlytics-slack-alert',
                 'package': package, 'verdict': 'pending', 'confidence': '', 'events': None, 'firstSeenAlert': a['ts'],
                 'updatedAt': firestore.SERVER_TIMESTAMP})
        n += 1
    return n
