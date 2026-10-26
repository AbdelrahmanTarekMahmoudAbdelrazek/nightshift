"""Daily gathering (step 1: detect): list the crash and ANR issues of the last 3 production releases from
Firebase Crashlytics and Google Play Android vitals, and put them on the case board.

Read-only everywhere: Crashlytics through the Firebase CLI login (GETs only), Play through the user's own Google
login (Play Developer Reporting API, scope playdeveloperreporting, read-only). Nothing is changed in either console.

Writes Firestore (nightshift-myzesty only):
  cases/<crashlytics issue id>      kind, title, sync_* numbers   (full pull/root cause stays on demand: Pull button)
  cases/play-<play issue id>        Play's own cluster, with one sample stack trace
  config/sync                       lastRun, per-source counts and errors (shown on the board)
"""
import datetime as dt
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

from . import crashlytics as cl

PLAY_BASE = 'https://playdeveloperreporting.googleapis.com/v1beta1'
PLAY_SCOPE = 'https://www.googleapis.com/auth/playdeveloperreporting'
KIND = {'FATAL': 'CRASH', 'ANR': 'ANR', 'NON_FATAL': 'NON-FATAL', 'CRASH': 'CRASH', 'APPLICATION_NOT_RESPONDING': 'ANR'}


def _today():
    return dt.datetime.utcnow().strftime('%Y-%m-%d')


# ------------------------------------------------------------------ releases

STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'out', 'releases_state.json')


def _semver(v):
    return tuple(int(x) for x in str(v).split('.'))


def _state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def releases(cfg):
    """The builds in scope, e.g. 1.25.2 (800054890), (800054889)... Returns (live version, display names, version codes).
    app.release_version: a fixed version (e.g. 1.25.1), or "auto": the highest real release Crashlytics has seen
    (x.y.z only; sprint/rc builds are ignored), its newest N builds, plus the previous version's newest builds for
    app.release_overlap_days after the new version first appeared, so its crashes do not vanish overnight."""
    want = str(cfg['app'].get('release_version') or str(cfg['app'].get('release_versions', '')).split(',')[0]).strip()
    n = int(cfg['app'].get('release_builds', 3))
    days = int(cfg['sources'].get('crashlytics_days', 30))
    rep = cl.report(cfg['sources']['crashlytics_app_id'], 'topVersions', days=days, page_size=200)
    found = {}                                       # version code -> (version, display name)
    for g in rep.get('groups', []) or []:
        dn = ((g.get('version') or {}).get('displayName')) or g.get('displayName') or ''
        m = re.fullmatch(r'(\d+\.\d+\.\d+) \((\d+)\)', dn.strip())
        if m:                                        # exact: sprint builds like 1.25.1-rc2 are ignored
            found[int(m.group(2))] = (m.group(1), dn.strip())
    if want.lower() != 'auto':
        codes = sorted((c for c, (v, _) in found.items() if v == want), reverse=True)[:n]
        cfg['app']['_live_version'] = want
        return want, [found[c][1] for c in codes], [str(c) for c in codes]
    vers = sorted({v for v, _ in found.values()}, key=_semver, reverse=True)
    if not vers:
        return 'auto', [], []
    new = vers[0]
    st = _state()
    first = st.setdefault('first_seen', {})
    first.setdefault(new, _today())
    if 'builds_seen' in st:
        seen = set(st['builds_seen'])
    else:                                            # first auto run: the builds Night Shift already has symbols for count as seen
        sy = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'symbols')
        seen = {d for d in (os.listdir(sy) if os.path.isdir(sy) else []) if d.isdigit()}
    codes = sorted((c for c, (v, _) in found.items() if v == new), reverse=True)[:n]
    od = str(cfg['app'].get('release_overlap_days', 7)).strip().lower()
    always = od in ('always', '-1', 'forever')        # keep the previous version for good: always the last 2 releases
    overlap_days = 10 ** 6 if always else int(od or 0)
    age = (dt.date.today() - dt.date.fromisoformat(first[new])).days
    prev = vers[1] if len(vers) > 1 and age < overlap_days else None
    if prev:
        codes += sorted((c for c, (v, _) in found.items() if v == prev), reverse=True)[:int(cfg['app'].get('release_overlap_builds', 2))]
    fresh = [str(c) for c in codes if str(c) not in seen]
    st['builds_seen'] = sorted(seen | {str(c) for c in codes})
    st.update({'live': new, 'overlap': prev, 'overlap_until': ('always' if always else (dt.date.fromisoformat(first[new]) + dt.timedelta(days=overlap_days)).isoformat()) if prev else '',
               'updated': _today()})
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(st, open(STATE, 'w'), indent=1)
    except OSError:
        pass
    cfg['app'].update({'_live_version': new, '_overlap_version': prev, '_overlap_until': st['overlap_until'],
                       '_new_builds': fresh if seen else []})
    return new, [found[c][1] for c in codes], [str(c) for c in codes]


def live_version(cfg):
    """The live production version (resolved when release_version is auto)."""
    v = (cfg.get('app') or {}).get('_live_version') or str((cfg.get('app') or {}).get('release_version') or '')
    return '' if v.lower() == 'auto' else v


# ------------------------------------------------------------------ Crashlytics

def _metric(g):
    m = g.get('metrics') or [{}]
    m = m[0] if isinstance(m, list) else m
    return int(m.get('eventsCount') or 0), int(m.get('impactedUsersCount') or m.get('usersCount') or 0)


def crashlytics_issues(cfg, names, top=50, log=print):
    app = cfg['sources']['crashlytics_app_id']
    days = int(cfg['sources'].get('crashlytics_days', 30))
    out = {}
    for etype in ('FATAL', 'ANR'):
        base = cl._interval(days) + [('page_size', top)] + [('filter.version.display_names', n) for n in names]
        try:
            rep = cl._get(f'{cl._base(app)}/reports/topIssues', base + [('filter.issue.error_types', etype)])
        except SystemExit as e:                      # API without the type filter: list all, keep this type
            log(f'  type filter not accepted ({str(e)[:100]}); filtering locally')
            rep = cl._get(f'{cl._base(app)}/reports/topIssues', base)
            etype_filtered = False
        else:
            etype_filtered = True
        groups, tokn, pages = list(rep.get('groups', []) or []), rep.get('nextPageToken'), 1
        while tokn and pages < 20:                   # follow every page, not just the first 50
            more = cl._get(f'{cl._base(app)}/reports/topIssues', base + ([('filter.issue.error_types', etype)] if etype_filtered else [])
                           + [('page_token', tokn)])
            groups += more.get('groups', []) or []
            tokn, pages = more.get('nextPageToken'), pages + 1
        for g in groups:
            iss = g.get('issue') or {}
            if iss.get('errorType') and iss.get('errorType') != etype:
                continue
            iid = iss.get('id') or ''
            if not re.fullmatch(r'[0-9a-f]{32}', iid):
                continue
            ev, us = _metric(g)
            et = iss.get('errorType') or etype
            out[iid] = {'id': iid, 'kind': KIND.get(et, et), 'title': iss.get('title', ''), 'subtitle': iss.get('subtitle', ''),
                        'events': ev, 'users': us, 'console_url': iss.get('uri', ''),
                        'first_seen': iss.get('firstSeenVersion', ''), 'last_seen': iss.get('lastSeenVersion', ''),
                        'signals': [s.get('signal') for s in iss.get('signals', []) if s.get('signal')]}
        log(f'Crashlytics {etype}: {sum(1 for r in out.values() if r["kind"] == KIND[etype])} issues')
    # per-issue version split, restricted to the 3 releases (one small GET each)
    fails = 0
    for iid, r in out.items():
        if fails >= 3:
            r['versions'] = {}
            continue
        try:                                         # same call the pull uses (issue filter only), split kept to our builds
            vrep = cl.report(app, 'topVersions', issue=iid, days=days, page_size=50)
            r['versions'] = {k: v for k, v in cl.counts(vrep, 'version').items() if k in names}
        except SystemExit as e:
            r['versions'] = {}
            fails += 1
            log(f'  versions for {iid[:8]} failed: {str(e)[:300]}' + ('; skipping the rest' if fails >= 3 else ''))
    # an issue with no events in our builds does not belong on the list
    rows = [r for r in out.values() if r['versions'] or fails >= 3]
    if len(rows) < len(out):
        log(f'  {len(out) - len(rows)} issues dropped: no events in {", ".join(names)}')
    return rows


# ------------------------------------------------------------------ Google Play (user's own login, read-only)

PLAY_CLIENT = os.path.expanduser('~/.config/nightshift/play-oauth-client.json')   # Desktop OAuth client of nightshift-myzesty
PLAY_TOKEN = os.path.expanduser('~/.config/nightshift/play-token.json')           # your read-only refresh token (stays on this Mac)


def play_token():
    """Access token for Play vitals from your own Google login on this Mac (read-only scope)."""
    try:
        import google.auth.transport.requests
    except ImportError as e:
        raise RuntimeError('pip3 install google-auth google-auth-oauthlib') from e
    if os.path.exists(PLAY_TOKEN):
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_file(PLAY_TOKEN)            # the scopes the user granted
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token, None                      # the client belongs to nightshift-myzesty, where the API is on
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=[PLAY_SCOPE])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token, getattr(creds, 'quota_project_id', None)
    except Exception as e:
        raise RuntimeError('Google Play is not linked yet. On the Mac run: python3 tools/nightshift/sentinel.py play-login') from e


def _play_get(path, params, tok, quota):
    url = f'{PLAY_BASE}/{path}?' + urllib.parse.urlencode(params, doseq=True)
    h = {'Authorization': f'Bearer {tok}'}
    if quota:
        h['x-goog-user-project'] = quota
    import time
    for attempt in range(3):                       # Play sometimes answers 503 / 429 for a moment: wait and retry
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f'Play API {e.code} on {path}: {e.read().decode()[:400]}')
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):       # flaky Wi-Fi: reset / TLS timeout
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def _play_interval(days):
    end = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
    start = end - dt.timedelta(days=days)
    p = []
    for k, t in (('startTime', start), ('endTime', end)):
        p += [(f'interval.{k}.year', t.year), (f'interval.{k}.month', t.month), (f'interval.{k}.day', t.day),
              (f'interval.{k}.hours', t.hour), (f'interval.{k}.timeZone.id', 'UTC')]
    return p


def _console_link(cfg, ptype, pid):
    dev, app = cfg['sources'].get('play_developer_id'), cfg['sources'].get('play_app_id')
    if not (dev and app):
        return ''
    return f"https://play.google.com/console/u/0/developers/{dev}/app/{app}/vitals/{'anrs' if ptype == 'ANR' else 'crashes'}/{pid}/details?days=28"


def play_issues(cfg, codes, top=50, log=print):
    pkg = cfg['app']['package']
    days = 28                                        # same window as Play Console's Crashes and ANRs page
    tok, quota = play_token()
    vfilter = ' OR '.join(f'versionCode = {c}' for c in codes)
    out = []
    for ptype in ('CRASH', 'ANR'):
        flt = f'errorIssueType = {ptype}' + (f' AND ({vfilter})' if vfilter else '')
        try:
            res = _play_get(f'apps/{pkg}/errorIssues:search', _play_interval(days) + [('filter', flt), ('pageSize', top)], tok, quota)
        except RuntimeError as e:
            if ' 400 ' not in f' {e} ' and 'Play API 400' not in str(e):
                raise
            log(f'  version filter not accepted ({str(e)[:120]}); listing {ptype} for all versions')
            res = _play_get(f'apps/{pkg}/errorIssues:search', _play_interval(days) + [('filter', f'errorIssueType = {ptype}'),
                                                                                     ('pageSize', top)], tok, quota)
        n = 0
        items, tokn, pages = list(res.get('errorIssues', []) or []), res.get('nextPageToken'), 1
        while tokn and pages < 20:                   # follow every page
            more = _play_get(f'apps/{pkg}/errorIssues:search', _play_interval(days) + [('filter', flt), ('pageSize', top),
                                                                                      ('pageToken', tokn)], tok, quota)
            items += more.get('errorIssues', []) or []
            tokn, pages = more.get('nextPageToken'), pages + 1
        for it in items:
            pid = it.get('name', '').split('/')[-1]
            if not pid:
                continue
            n += 1
            out.append({'id': f'play-{pid}', 'play_name': it.get('name'), 'kind': KIND.get(it.get('type'), it.get('type') or ptype),
                        'title': it.get('cause', ''), 'subtitle': it.get('location', ''),
                        'events': int(it.get('errorReportCount') or 0), 'users': int(it.get('distinctUsers') or 0),
                        'last_report': it.get('lastErrorReportTime', ''),
                        'console_url': it.get('issueUri') or _console_link(cfg, ptype, pid),
                        'versions': {'all listed builds': int(it.get('errorReportCount') or 0)}})
        log(f'Google Play {ptype}: {n} issues')
    byid = {r['id']: r for r in out}                 # exact per-build counts: one search per build and type
    for code in codes:
        for ptype in ('CRASH', 'ANR'):
            q = _play_interval(days) + [('filter', f'errorIssueType = {ptype} AND versionCode = {code}'), ('pageSize', top)]
            found, tokn, pages = [], None, 0
            try:                                     # follow every page: one build can have more than 50 ANR clusters
                while pages == 0 or (tokn and pages < 20):
                    res = _play_get(f'apps/{pkg}/errorIssues:search', q + ([('pageToken', tokn)] if tokn else []), tok, quota)
                    found += res.get('errorIssues', []) or []
                    tokn, pages = res.get('nextPageToken'), pages + 1
            except RuntimeError as e:
                log(f'  per-build {code} {ptype}: {str(e)[:120]}')
                if not found:
                    continue
            for it in found:
                r = byid.get('play-' + it.get('name', '').split('/')[-1])
                if r is not None:
                    r.setdefault('per_build', {})[str(code)] = int(it.get('errorReportCount') or 0)
    for r in out:
        if r.get('per_build'):
            r['versions'] = r['per_build']
    for r in out:                                    # one sample stack trace per Play cluster
        try:
            pid = r['id'][5:]
            rep = _play_get(f'apps/{pkg}/errorReports:search',
                            _play_interval(days) + [('filter', f'errorIssueId = {pid}'), ('pageSize', 1)], tok, quota)
            s = (rep.get('errorReports') or [{}])[0]
            r['stack'] = (s.get('reportText') or '')[:8000]
            dm = (s.get('deviceModel') or {})
            r['sample_device'] = dm.get('marketingName') or dm.get('deviceId', {}).get('buildDevice', '') if isinstance(dm, dict) else ''
            r['sample_version'] = (s.get('appVersion') or {}).get('versionCode', '')
        except Exception as e:
            r['stack'] = ''
            log(f'  sample for {r["id"]} failed: {str(e)[:120]}')
    return out


# ------------------------------------------------------------------ Firestore

SYNC_FIELDS = ['src', 'sync_run', 'sync_at', 'sync_events', 'sync_users', 'sync_versions', 'title', 'subtitle', 'console_url', 'signals',
               'first_seen', 'last_seen', 'play_name', 'last_report', 'stack', 'sample_device', 'sample_version']


def write(db, rows, source, run_id=''):
    """Merge listing rows into cases. A case that was already pulled keeps its analysis; only sync_* fields change."""
    from firebase_admin import firestore
    refs = [db.collection('cases').document(r['id']) for r in rows]
    existing = {s.id: (s.to_dict() or {}) for s in db.get_all(refs)} if refs else {}
    batch, n, new = db.batch(), 0, 0
    for r, ref in zip(rows, refs):
        old = existing.get(r['id']) or {}
        doc = {'id': r['id'], 'src': source, 'sync_run': run_id, 'sync_at': firestore.SERVER_TIMESTAMP, 'sync_events': r['events'],
               'sync_users': r['users'], 'sync_versions': r.get('versions') or {}}
        for k in ('title', 'subtitle', 'console_url', 'signals', 'first_seen', 'last_seen', 'play_name', 'last_report',
                  'stack', 'sample_device', 'sample_version'):
            if r.get(k) not in (None, '', []):
                doc[k] = r[k]
        fields = list(doc)
        if not old.get('verdict') or old.get('verdict') in ('new', 'pending'):     # never pulled: fill the table columns too
            doc.update({'kind': r['kind'], 'verdict': 'new', 'confidence': '', 'events': r['events'], 'real_users': r['users'],
                        'versions': r.get('versions') or {}, 'status': old.get('status') or 'new',
                        'last_date': (r.get('last_report') or '')[:10]})
            fields += ['kind', 'verdict', 'confidence', 'events', 'real_users', 'versions', 'status', 'last_date']
            if not old:
                new += 1
        batch.set(ref, doc, merge=fields)            # listed fields replaced whole (no stale map keys), others kept
        n += 1
        if n >= 400:
            batch.commit(); batch, n = db.batch(), 0
    if n:
        batch.commit()
    return new


def run(db, cfg, log=print, sources=('crashlytics', 'play'), analyse=True, stop=None):
    from firebase_admin import firestore
    status = {'startedAt': dt.datetime.now().isoformat(timespec='seconds'), 'day': _today()}
    run_id = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    try:                                             # labels left behind by a job that died ('reproduce-running')
        running = {(d.to_dict() or {}).get('issue') for d in db.collection('jobs').where('status', '==', 'running').stream()}
        for d in db.collection('cases').stream():
            st = str((d.to_dict() or {}).get('status', ''))
            if st.endswith('-running') and d.id not in running:
                d.reference.update({'status': 'triaged'})
    except Exception:
        pass
    want, names, codes = releases(cfg)
    status['releases'] = names
    try:                                             # generic symbols: every build in scope gets its own .so
        import importlib
        from . import symbols_auto
        importlib.reload(symbols_auto)
        byver = {}                                   # each build with its own version name (1.25.2 and, in the overlap, 1.25.1)
        for nm, vc in zip(names, codes):
            byver.setdefault(nm.split(' ')[0], []).append(vc)
        res = {'have': [], 'added': [], 'failed': [], 'debug': []}
        for vn, vcs in byver.items():
            r = symbols_auto.ensure(cfg, vcs, vn, log=log)
            for k in res:
                res[k] += r.get(k) or []
        status['symbols'] = res
        status['release'] = {'version': want, 'mode': 'auto' if str(cfg['app'].get('release_version', '')).lower() == 'auto' else 'fixed',
                             'overlap': cfg['app'].get('_overlap_version') or '', 'overlapUntil': cfg['app'].get('_overlap_until') or '',
                             'newBuilds': cfg['app'].get('_new_builds') or [],
                             'noDebug': [vc for vc in codes if vc not in (res.get('debug') or [])],
                             'noSymbols': res.get('failed') or []}
        try:                                         # no .aab for a new build: queue one rebuild per binary (BuildId), once
            st = _state()
            tried = st.get('rebuild') or {}
            from . import symbolize as _sy
            groups = {}
            for vc in status['release']['noDebug']:
                if vc in tried:
                    continue
                mp = os.path.join(_sy.STORE, vc, 'meta.json')
                if os.path.exists(mp):
                    groups.setdefault(json.load(open(mp)).get('build_id') or vc, []).append(vc)
            if groups and str(cfg['app'].get('symbols_rebuild', 'true')).lower() not in ('false', 'no', '0'):
                from firebase_admin import firestore as _fs
                for bid, vcs in groups.items():
                    db.collection('jobs').add({'action': 'symbols-rebuild', 'issue': ','.join(sorted(vcs, reverse=True)),
                                               'requestedBy': 'Night Shift (new release, no .aab)', 'status': 'queued',
                                               'queuedAt': _fs.SERVER_TIMESTAMP})
                    for vc in vcs:
                        tried[vc] = {'queued': _today()}
                    log(f"symbols: queued a rebuild of {', '.join(vcs)} for file:line (keeps it only if identical to the Google Play build)")
                st['rebuild'] = tried
                json.dump(st, open(STATE, 'w'), indent=1)
        except Exception as e:
            log(f'symbols: rebuild not queued ({str(e)[:150]})')
        if status['release']['newBuilds']:
            log(f"releases: new build(s) {', '.join(status['release']['newBuilds'])}: symbols fetched from Google Play"
                + (f"; full debug symbols missing for {', '.join(status['release']['noDebug'])} (put <code>.aab in Downloads)" if status['release']['noDebug'] else ''))
    except BaseException as e:
        log(f'symbols: skipped ({str(e)[:200]})')
    log(f'releases: {", ".join(names) or "(none found: check app.release_version)"}')
    if not names:
        raise RuntimeError(f'no builds of {want} found in Crashlytics')
    for src, fn, arg in (('crashlytics', crashlytics_issues, names), ('play', play_issues, codes)):
        if src not in sources:
            continue
        try:
            rows = fn(cfg, arg, log=log)
            new = write(db, rows, src, run_id)
            status[src] = {'ok': True, 'run': run_id, 'issues': len(rows), 'new': new,
                           'crashes': sum(1 for r in rows if r['kind'] == 'CRASH'), 'anrs': sum(1 for r in rows if r['kind'] == 'ANR')}
            log(f'{src}: {len(rows)} issues on the board ({new} new)')
        except Exception as e:                       # one source failing must not hide the other
            status[src] = {'ok': False, 'error': str(e)[:400]}
            log(f'{src}: FAILED {str(e)[:300]}')
    db.collection('config').document('sync').set(dict(status, updatedAt=firestore.SERVER_TIMESTAMP))
    import importlib
    try:                                             # pair the same problem across Play and Firebase
        from . import merge
        from . import timeline as _tl
        importlib.reload(_tl)
        importlib.reload(merge)
        status['merged'] = merge.build(db, cfg, log=log)
    except BaseException as e:
        status['merged'] = {'error': str(e)[:300]}
        log(f'merge: FAILED {str(e)[:300]}')
    try:                                             # board host: every build's symbols to the team's GitHub (teammates download once)
        from . import symbolize as _sy, symshare
        importlib.reload(symshare)
        if _sy._host_here():
            symshare.publish_all(db, codes, log=log, cfg=cfg)
    except BaseException as e:
        log(f'symbols: sharing on GitHub skipped ({str(e)[:200]})')
    try:                                             # PRs waiting for their Kotlin/Java side: look again every morning
        from . import integration
        importlib.reload(integration)
        integration.recheck(db, cfg, log=log)
    except BaseException as e:
        log(f'integration re-check skipped ({str(e)[:200]})')
    try:                                             # new clusters of a known problem (often an old, fixed bug): link them
        from . import analyse as _an
        importlib.reload(_an)
        _rows, _f, fol = _an.link_families(db, log=log)
        status['linked'] = len(fol)
    except BaseException as e:
        log(f'linking related crashes: FAILED {str(e)[:200]}')
    try:                                             # release statistics: crash/ANR rates per build (Play vitals)
        from . import vitals
        importlib.reload(vitals)
        status['vitals'] = vitals.build(db, cfg, log=log)
    except BaseException as e:
        log(f'vitals: FAILED {str(e)[:300]}')
    db.collection('config').document('sync').set(dict(status, updatedAt=firestore.SERVER_TIMESTAMP))
    if stop and stop():
        log('sync: cancelled from the board before the root-cause step')
        analyse = False
    if analyse:                                      # root cause + diagrams for every new/changed problem
        try:
            from . import analyse as an, timeline, threads, source, review, locate, crashlytics
            for mod in (crashlytics, source, locate, timeline, threads, review, an):   # dependencies first
                importlib.reload(mod)
            status['analysis'] = an.run_all(db, cfg, log=log, stop=stop)
        except BaseException as e:
            status['analysis'] = {'error': str(e)[:300]}
            log(f'analysis: FAILED {str(e)[:300]}')
    status['finishedAt'] = dt.datetime.now().isoformat(timespec='seconds')
    db.collection('config').document('sync').set(dict(status, updatedAt=firestore.SERVER_TIMESTAMP))
    return status


def play_login():
    """One time: sign in with the Google account that opens Play Console; grants only the read-only Play reporting scope."""
    if not os.path.exists(PLAY_CLIENT):
        raise SystemExit(f'missing {PLAY_CLIENT}: download the Desktop OAuth client JSON of your Night Shift board project there (see SOP).')
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit('run first:  pip3 install google-auth-oauthlib')
    print('A browser opens: sign in with the Google account you use for Play Console and click Allow (Play reports + build downloads for symbols).')
    flow = InstalledAppFlow.from_client_secrets_file(PLAY_CLIENT, scopes=[PLAY_SCOPE, 'https://www.googleapis.com/auth/androidpublisher'])
    creds = flow.run_local_server(port=0, prompt='consent', access_type='offline')
    os.makedirs(os.path.dirname(PLAY_TOKEN), exist_ok=True)
    with open(PLAY_TOKEN, 'w') as f:
        f.write(creds.to_json())
    os.chmod(PLAY_TOKEN, 0o600)
    print(f'Linked. Token saved to {PLAY_TOKEN} (read-only Play reporting). Test: python3 tools/nightshift/sentinel.py sync --only play')
