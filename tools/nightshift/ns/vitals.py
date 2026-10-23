"""Release statistics for the dashboard: Google Play Android vitals per build (read-only).

  crashRateMetricSet / anrRateMetricSet :query  -> daily crash rate, user-perceived crash rate, ANR rates, users
  per versionCode, last 28 days, for every build Crashlytics saw in the window (all releases, not only the 3 builds
  in scope). Stored compactly in Firestore config/vitals; config/releases lists releases -> builds -> events.
"""
import datetime as dt
import json
import re
import urllib.request

from . import crashlytics as cl
from . import sync

TZ = 'America/Los_Angeles'          # Play's daily aggregation is in Pacific time


def _post(path, body, tok, quota):
    req = urllib.request.Request(f'{sync.PLAY_BASE}/{path}', data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json',
                                          **({'x-goog-user-project': quota} if quota else {})})
    import time
    for i in range(3):                                   # flaky Wi-Fi / Play 5xx: wait and retry
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 2:
                time.sleep(5 * (i + 1)); continue
            raise RuntimeError(f'Play API {e.code} on {path}: {" ".join(e.read().decode(errors="replace").split())[:300]}')
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            if i < 2:
                time.sleep(5 * (i + 1)); continue
            raise


def _latest_day(metric_set, pkg, tok, quota):
    info = sync._play_get(f'apps/{pkg}/{metric_set}', [], tok, quota)
    for f in (info.get('freshnessInfo') or {}).get('freshnesses', []) or []:
        if f.get('aggregationPeriod') == 'DAILY':
            t = f.get('latestEndTime') or {}
            return dt.date(t['year'], t['month'], t['day'])
    return dt.date.today() - dt.timedelta(days=2)


def _query(metric_set, metrics, pkg, codes, tok, quota, days=28):
    end = _latest_day(metric_set, pkg, tok, quota)
    start = end - dt.timedelta(days=days)
    ts = lambda d: {'year': d.year, 'month': d.month, 'day': d.day, 'timeZone': {'id': TZ}}
    body = {'timelineSpec': {'aggregationPeriod': 'DAILY', 'startTime': ts(start), 'endTime': ts(end)},
            'dimensions': ['versionCode'], 'metrics': metrics, 'pageSize': 100000}
    if codes:
        body['filter'] = ' OR '.join(f'versionCode = {c}' for c in codes)
    out, page = {}, None
    while True:
        if page:
            body['pageToken'] = page
        res = _post(f'apps/{pkg}/{metric_set}:query', body, tok, quota)
        for r in res.get('rows', []) or []:
            st = r.get('startTime') or {}
            day = '%04d-%02d-%02d' % (st.get('year', 0), st.get('month', 0), st.get('day', 0))
            code = next((str(d.get('stringValue') or d.get('int64Value') or '') for d in r.get('dimensions', [])
                         if d.get('dimension') == 'versionCode'), '')
            vals = {}
            for m in r.get('metrics', []) or []:
                v = (m.get('decimalValue') or {}).get('value')
                vals[m.get('metric')] = float(v) if v not in (None, '') else None
            out.setdefault(code, {})[day] = [vals.get(k) for k in metrics]
        page = res.get('nextPageToken')
        if not page:
            break
    return out, str(end)


def releases_map(cfg, days=30):
    """All builds Crashlytics saw in the window, grouped by release: {version: [{code, display, events}]}."""
    rep = cl.report(cfg['sources']['crashlytics_app_id'], 'topVersions', days=days, page_size=200)
    rel = {}
    for g in rep.get('groups', []) or []:
        dn = (((g.get('version') or {}).get('displayName')) or g.get('displayName') or '').strip()
        m = re.fullmatch(r'(\S+) \((\d+)\)', dn)
        if not m or '-' in m.group(1):              # production releases only (no -sprint / -productionInternal)
            continue
        mt = g.get('metrics') or [{}]
        mt = mt[0] if isinstance(mt, list) else mt
        rel.setdefault(m.group(1), []).append({'code': m.group(2), 'display': dn, 'events': int(mt.get('eventsCount') or 0),
                                               'users': int(mt.get('impactedUsersCount') or 0)})
    for v in rel.values():
        v.sort(key=lambda b: -int(b['code']))
    return rel


def build(db, cfg, log=print):
    from firebase_admin import firestore
    pkg = cfg['app']['package']
    rel = releases_map(cfg)
    order = sorted(rel, key=lambda v: [int(x) if x.isdigit() else 0 for x in re.split(r'[.-]', v)], reverse=True)
    codes = [b['code'] for v in order[:6] for b in rel[v]][:60]          # newest 6 releases, at most 60 builds
    tok, quota = sync.play_token()
    crash, crash_end = _query('crashRateMetricSet', ['crashRate', 'userPerceivedCrashRate', 'distinctUsers'], pkg, codes, tok, quota)
    anr, anr_end = _query('anrRateMetricSet', ['anrRate', 'userPerceivedAnrRate', 'distinctUsers'], pkg, codes, tok, quota)
    db.collection('config').document('vitals').set({'crash': json.dumps(crash), 'anr': json.dumps(anr), 'crashEnd': crash_end,
                                                    'anrEnd': anr_end, 'updatedAt': firestore.SERVER_TIMESTAMP})
    db.collection('config').document('releases').set({'releases': [{'version': v, 'builds': rel[v]} for v in order[:12]],
                                                      'updatedAt': firestore.SERVER_TIMESTAMP})
    log(f'vitals: {len(order)} releases, {len(codes)} builds; daily crash/ANR rates up to {crash_end}')
    try:
        tr = trends(cfg, log=log)
        db.collection('config').document('trends').set({'data': json.dumps(tr), 'updatedAt': firestore.SERVER_TIMESTAMP})
    except Exception as e:                       # the board falls back to vitals only
        log(f'trends: FAILED {str(e)[:200]}')
    return {'releases': len(order), 'builds': len(codes)}


_DU_REPORT = []          # the report that worked for distinct users (cached per run), or ['none']


def _distinct_users(cl, app, p, log):
    """Users across all issues counted once, the console's "Users N" header. A person sits on one device and one
    OS version, so grouping by device (or OS) gives distinct users; returns None when the API refuses both."""
    names = _DU_REPORT[:1] or ['topAndroidDevices', 'topOperatingSystems']
    if names == ['none']:
        return None
    for rpt in names:
        try:
            rep = cl._get(f'{cl._base(app)}/reports/{rpt}', p)
        except BaseException as e:
            log(f'trends: {rpt} not usable for distinct users ({str(e)[:120]})')
            continue
        if not _DU_REPORT:
            _DU_REPORT.append(rpt)
            log(f'trends: distinct users from {rpt}')
        return sum(sync._metric(g)[1] for g in rep.get('groups', []) or [])
    _DU_REPORT[:] = ['none']
    return None


def trends(cfg, days=30, log=print):
    """Daily Crashlytics events + impacted users per issue for the builds in scope, the way the Firebase console
    shows them: days in the console's time zone (app.timezone, default Africa/Cairo), today as a partial day, plus
    the console's period totals (Crashes N / Users N for the last 7 and 30 days, and the period before) from
    topVersions. The Crashlytics API has no time-series endpoint, so topIssues is asked once per day and per type."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(str((cfg.get('app') or {}).get('timezone') or 'Africa/Cairo'))
    app = cfg['sources']['crashlytics_app_id']
    _, names, _ = sync.releases(cfg)
    vf = [('filter.version.display_names', n) for n in names]
    now = dt.datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    z = lambda t: t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    out = {'days': [], 'issues': {}, 'total': {'FATAL': [], 'ANR': []}, 'users': {'FATAL': [], 'ANR': []}, 'builds': names,
           'tz': str(tz), 'asof': now.isoformat(timespec='minutes'), 'periods': {}}
    for k in range(days - 1, -1, -1):
        start = today - dt.timedelta(days=k)
        end = min(start + dt.timedelta(days=1), now)
        out['days'].append(start.strftime('%Y-%m-%d'))
        for et in ('FATAL', 'ANR'):
            p = [('filter.interval.start_time', z(start)), ('filter.interval.end_time', z(end)), ('page_size', 200),
                 ('filter.issue.error_types', et)] + vf
            try:
                rep = cl._get(f'{cl._base(app)}/reports/topIssues', p)
            except BaseException as e:
                raise RuntimeError(f'Crashlytics topIssues for {start:%Y-%m-%d} {et}: {str(e)[:200]}')
            te = tu = 0
            for g in rep.get('groups', []) or []:
                iid = ((g.get('issue') or {}).get('id')) or ''
                ev, us = sync._metric(g)
                if iid:
                    out['issues'].setdefault(iid, [[0, 0] for _ in range(days)])[days - 1 - k] = [ev, us]
                te += ev
                tu += us
            out['total'][et].append(te)
            out['users'][et].append(tu)
    # the console compares with the n-1 full days before the window (7d: Oct 2-8 vs Sep 26-Oct 1)
    _DU_REPORT.clear()
    for n in (7, 30):                                # the console's "Crashes 15 · Users 11 · -64.3%" header
        for label, s0, e0 in (('cur', today - dt.timedelta(days=n - 1), now), ('prev', today - dt.timedelta(days=2 * n - 2), today - dt.timedelta(days=n - 1))):
            for et in ('FATAL', 'ANR'):
                p = [('filter.interval.start_time', z(s0)), ('filter.interval.end_time', z(e0)), ('page_size', 200),
                     ('filter.issue.error_types', et)] + vf
                try:
                    rep = cl._get(f'{cl._base(app)}/reports/topIssues', p)   # topVersions rejects the type filter (400)
                except BaseException as e:            # the helper raises SystemExit on API errors: never kill the job
                    log(f'trends: period totals not available ({str(e)[:160]})')
                    out['periods'] = {}
                    return out
                ev = us = 0
                for g in rep.get('groups', []) or []:
                    a, b = sync._metric(g)
                    ev += a
                    us += b
                du = _distinct_users(cl, app, p, log)       # summing users per issue counts a person twice
                out['periods'].setdefault(str(n), {}).setdefault(label, {})[et] = [ev, du if du is not None else us]
    log(f"trends: {days} days x {len(out['issues'])} issues ({out['tz']}) for {', '.join(names)}; "
        f"7d crashes {out['periods']['7']['cur']['FATAL']} / 30d {out['periods']['30']['cur']['FATAL']}")
    return out
