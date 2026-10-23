"""Free ingestion #2: Google Play Developer Reporting API (vitals.errors.issues.search) -> Play's view of ANR/crash clusters.

Needs: a service account linked in Play Console (Users and permissions -> invite the SA email, 'View app information'),
the Reporting API enabled on its Google Cloud project, and `pip3 install google-auth`. Key path in $PLAY_SA.
Freshness is hours (Play's own latency); the board shows it as "as of".
"""
import json
import os
import urllib.parse
import urllib.request

SCOPE = 'https://www.googleapis.com/auth/playdeveloperreporting'
BASE = 'https://playdeveloperreporting.googleapis.com/v1beta1'


def _token():
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests
    except ImportError as e:
        raise SystemExit('pip3 install google-auth requests') from e
    key = os.environ.get('PLAY_SA')
    if not key or not os.path.exists(key):
        raise SystemExit('PLAY_SA must point at the Play service-account key')
    creds = service_account.Credentials.from_service_account_file(key, scopes=[SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def search_issues(package: str, days: int = 7, page_size: int = 50):
    """Return Play error issues (ANR + crash clusters) for the last `days`."""
    import datetime as dt
    end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    params = {
        'pageSize': page_size,
        'interval.startTime.year': start.year, 'interval.startTime.month': start.month, 'interval.startTime.day': start.day,
        'interval.startTime.hours': start.hour, 'interval.startTime.timeZone.id': 'UTC',
        'interval.endTime.year': end.year, 'interval.endTime.month': end.month, 'interval.endTime.day': end.day,
        'interval.endTime.hours': end.hour, 'interval.endTime.timeZone.id': 'UTC',
    }
    url = f'{BASE}/apps/{package}/errorIssues:search?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {_token()}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get('errorIssues', [])


def upsert_play(db, issues, package):
    from firebase_admin import firestore
    n = 0
    for it in issues:
        iid = it.get('name', '').split('/')[-1]
        db.collection('play_issues').document(iid).set({
            'id': iid, 'type': it.get('type'), 'cause': it.get('cause'), 'location': it.get('location'),
            'errorReportCount': it.get('errorReportCount'), 'distinctUsers': it.get('distinctUsers'),
            'firstOsVersion': it.get('firstOsVersion'), 'lastOsVersion': it.get('lastOsVersion'),
            'firstAppVersion': it.get('firstAppVersion'), 'lastAppVersion': it.get('lastAppVersion'),
            'issueUri': it.get('issueUri'), 'package': package, 'updatedAt': firestore.SERVER_TIMESTAMP}, merge=True)
        n += 1
    db.collection('config').document('board').set({'playAsOf': firestore.SERVER_TIMESTAMP}, merge=True)
    return n
