"""Offline triage of a Crashlytics issue from its per-event CSV export.

Input columns (as produced by the console-API pull used for the nativePollOnce report):
  event_id,date_utc,version,build,manufacturer,model,arch,android,uptime_s,crashlytics_sdk,has_thread_dump,
  cause_bucket,n_breadcrumbs,n_native_logs,last_breadcrumb_gap_s,last_event,last_screen,last_native_log,
  is_internal_or_emulator
Everything below is counting; the verdict is a rule over the counts. The model (skills/anr-triage) only writes
the narrative around these numbers and may NOT change them.
"""
import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

ENGINE_BUCKET = 'E_native_engine'
NOT_ENGINE_BUCKETS = ('A_fcm_image_download', 'B_fcm_other', 'C_rn_context_or_js_busy')
RE_NATIVE_LOG = re.compile(r'file:\s*([\w./]+),\s*line:\s*(\d+)\s+(\S+)')


@dataclass
class Triage:
    issue: str
    events: int = 0
    real_users: int = 0
    internal: int = 0
    with_dump: int = 0
    with_breadcrumbs: int = 0
    with_native_logs: int = 0
    versions: Counter = field(default_factory=Counter)
    android: Counter = field(default_factory=Counter)
    manufacturers: Counter = field(default_factory=Counter)
    models: Counter = field(default_factory=Counter)
    buckets: Counter = field(default_factory=Counter)      # over events with a dump
    last_events: Counter = field(default_factory=Counter)
    last_screens: Counter = field(default_factory=Counter)
    native_sites: Counter = field(default_factory=Counter)  # file:function from last_native_log
    uptime_bands: Counter = field(default_factory=Counter)
    per_day: Dict[str, int] = field(default_factory=dict)
    first_date: str = ''
    last_date: str = ''
    verdict: str = ''
    confidence: str = ''
    reasons: List[str] = field(default_factory=list)
    field_fingerprint: str = ''
    sessions_hashed: int = 0


def _band(up):
    try:
        s = int(float(up))
    except (TypeError, ValueError):
        return 'unknown'
    return '<60 s' if s < 60 else '1-10 min' if s < 600 else '10-60 min' if s < 3600 else '1-6 h' if s < 21600 else '>6 h'


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def analyse(csv_path: str, issue: str, editor_screens=(), release_versions=()) -> Triage:
    t = Triage(issue=issue)
    rows = list(csv.DictReader(open(csv_path, encoding='utf-8')))
    if release_versions:
        keep = set(release_versions)
        before = len(rows)
        rows = [r for r in rows if (r.get('version') or '').split('-')[0] in keep]
        t.reasons.append(f'scoped to releases {", ".join(release_versions)}: {len(rows)} of {before} events kept')
    sessions = set()
    for r in rows:
        t.events += 1
        internal = (r.get('is_internal_or_emulator', '') or '').lower() == 'true'
        t.internal += internal
        t.real_users += not internal
        sessions.add(_hash((r.get('event_id') or '').split('_')[0]))  # session part only, hashed; never kept raw
        day = (r.get('date_utc') or '')[:10]
        if day:
            t.per_day[day] = t.per_day.get(day, 0) + 1
        t.versions[r.get('version', '')] += 1
        t.android[r.get('android', '')] += 1
        t.manufacturers[r.get('manufacturer', '')] += 1
        t.models[f"{r.get('manufacturer','')} {r.get('model','')}".strip()] += 1
        t.uptime_bands[_band(r.get('uptime_s'))] += 1
        if (r.get('has_thread_dump', '') or '').lower() == 'true':
            t.with_dump += 1
            for b in (r.get('cause_bucket') or 'NO_DUMP').split(','):
                t.buckets[b.strip()] += 1
        if int(r.get('n_breadcrumbs') or 0) > 0:
            t.with_breadcrumbs += 1
            if r.get('last_event'):
                t.last_events[r['last_event']] += 1
            if r.get('last_screen'):
                t.last_screens[r['last_screen']] += 1
        if int(r.get('n_native_logs') or 0) > 0 or r.get('last_native_log'):
            t.with_native_logs += 1
            m = RE_NATIVE_LOG.search(r.get('last_native_log') or '')
            if m:
                t.native_sites[f'{m.group(1)}:{m.group(3)}'] += 1
    t.sessions_hashed = len(sessions)
    days = sorted(t.per_day)
    t.first_date, t.last_date = (days[0], days[-1]) if days else ('', '')
    _verdict(t, editor_screens)
    return t


def _verdict(t: Triage, editor_screens):
    dumps = t.with_dump
    eng = t.buckets.get(ENGINE_BUCKET, 0)
    not_eng = sum(t.buckets.get(b, 0) for b in NOT_ENGINE_BUCKETS)
    editor_last = sum(c for s, c in t.last_screens.items() if s in editor_screens)
    bc = t.with_breadcrumbs
    if dumps == 0 and bc == 0:
        t.verdict, t.confidence = 'insufficient', 'low'
        t.reasons.append('no thread dumps and no breadcrumbs in the export; pull more events or wait for Android 11-13 dumps')
        return
    eng_share = eng / dumps if dumps else 0
    not_eng_share = not_eng / dumps if dumps else 0
    editor_share = editor_last / bc if bc else 0
    t.reasons.append(f'{dumps} of {t.events} events carry an OS thread dump; {eng} ({eng_share:.0%}) show native-engine threads doing work, '
                     f'{not_eng} ({not_eng_share:.0%}) show the FCM / React Native pipeline')
    if bc:
        t.reasons.append(f'{bc} events carry breadcrumbs; last screen was an editor screen in {editor_last} ({editor_share:.0%})')
    if t.with_native_logs:
        top = t.native_sites.most_common(1)[0] if t.native_sites else ('', 0)
        t.reasons.append(f'{t.with_native_logs} events have native-engine logs; most common last site {top[0]} ({top[1]})')
    if eng_share >= 0.5 or editor_share >= 0.5:
        t.verdict, t.confidence = 'engine', 'high' if dumps >= 20 else 'medium'
    elif eng_share <= 0.1 and (not_eng_share >= 0.3 or editor_share <= 0.1):
        t.verdict, t.confidence = 'not-engine', 'high' if dumps >= 50 else 'medium'
    else:
        t.verdict, t.confidence = 'mixed', 'low'
        t.reasons.append('engine and non-engine evidence both present; split the issue by cause_bucket before reproducing')
    if t.native_sites:
        t.field_fingerprint = '\n'.join(s for s, _ in t.native_sites.most_common(3))


def table(counter: Counter, n=8, total=None):
    total = total or sum(counter.values()) or 1
    return '\n'.join(f'| {k or "(empty)"} | {v} | {v/total:.0%} |' for k, v in counter.most_common(n))
