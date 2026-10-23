"""Steps 1-5 for one issue: pull (read-only) -> collect -> classify -> locate code -> match scenarios -> case file.

Output: out/<KIND>_<issue>_case_file.{md,json}, the same record shape the board and worker already use.
"""
import datetime as dt
import json
import os
from collections import Counter

from . import crashlytics, locate, match, config, llm, symbolize, groups

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(HERE, 'out')


def _kind(issue):
    et = (issue.get('errorType') or '').upper()
    return 'ANR' if 'ANR' in et else 'CRASH'


def classify(frames, native_lib):
    top = next((f for f in frames if f.get('func') or f.get('lib')), {})
    eng = [f for f in frames if f.get('lib') == native_lib]
    if top.get('lib') == native_lib:
        return 'engine', 'high', f"crashed thread's top frame is in {native_lib}: {top.get('func') or top.get('address')}"
    if eng:
        return 'engine', 'medium', f'{len(eng)} {native_lib} frames on the crashed thread under {top.get("lib") or "a framework frame"}'
    return 'not-engine', 'medium', f"no {native_lib} frames on the crashed thread (top: {top.get('lib')} {top.get('func')})"


def build(issue_ref, cfg, use_llm=False):
    src = cfg['sources']
    app_id, days, n = src['crashlytics_app_id'], int(src.get('crashlytics_days', 30)), int(src.get('events_per_issue', 20))
    from . import sync
    releases = sync.releases(cfg)[1] or [sync.live_version(cfg)]   # newest builds of the live version (+ the previous one during a rollout)
    native_lib = cfg['app']['native_lib']
    card = str(issue_ref).strip()
    iss_id, card_fp = groups.split(card)            # '<issue>~<fp8>' = one stack group (card) of a mixed issue
    iid = iss_id if card_fp else crashlytics.issue_id_from(card)
    card = card if card_fp else iid
    raw = os.path.join(OUT, 'raw', iid)
    iss, versions, vrep, events, devrep, osrep = crashlytics.pull(app_id, iid, releases, days, n, raw)

    # name the frames we can (symbol store per versionCode), then split the issue into its real distinct crashes
    symbolized = 0
    for e in events:
        _, did = symbolize.symbolize_frames(e['frames'], e.get('version_code'), native_lib, (e.get('version') or '').split(' ')[0])
        symbolized += did and any(f.get('func') for f in e['frames'] if f.get('lib') == native_lib)
    def sig(e):
        eng = [f for f in e['frames'] if f.get('lib') == native_lib][:3]
        return ' | '.join((f['func'].split(' + ')[0] if f.get('func') else f"0x{int(f.get('address') or 0):x}") for f in eng) or (e.get('signal') or '?')
    all_events = events
    if not groups.load(iid).get('groups'):          # never synced since stack groups exist: register now (local copy)
        groups.assign(iid, all_events, native_lib=native_lib)
    events, scope = groups.card_events(card, all_events, native_lib)
    split_card = len(groups.load(iid).get('groups') or []) > 1
    clusters = {}
    for e in events:
        clusters.setdefault(sig(e), []).append(e)
    sgroups = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
    sample_pool = sgroups[0][1] if sgroups else events
    sample = next((e for e in sample_pool if any(f.get('func') for f in e['frames'])), sample_pool[0] if sample_pool else {'frames': [], 'logs': []})
    frames = sample.get('frames', [])
    verdict, confidence, why = classify(frames, native_lib) if frames else ('insufficient', 'low', 'no event with a stack in the selected releases')
    # read the code AS SHIPPED: the commit the sample's build was made from (same rule as the root cause), never the
    # working copy: file:line comes from that build's own .so, so the code shown at that line must be that build's code
    src_ref, prev_sha = None, locate.sha()
    try:
        from . import source
        src_ref = source.ref_for(sample.get('version_code'), (sample.get('version') or '').split(' ')[0] or None, cfg)
    except Exception:
        src_ref = None
    locate.set_sha(src_ref['sha'] if src_ref else None)
    try:
        code = locate.locate(frames, native_lib) if frames else []
    finally:
        locate.set_sha(prev_sha)
    found = [c for c in code if c.get('found')]

    scen = match.load_scenarios(config.repo_path(cfg['lab']['stress_runner']))
    # evidence = the last ~25 log lines before the crash in THIS stack group only (the trigger is in the final seconds)
    evidence = [l for e in sample_pool for l in e.get('logs', [])[:25]] + [f.get('func', '') for f in frames]
    ranked = match.rank(scen, match.evidence_tags(evidence), top=5) if verdict == 'engine' else []

    vcounts = crashlytics.counts(vrep, 'version')
    vcounts = {k: v for k, v in vcounts.items() if k in versions} or vcounts
    issue_events = sum(vcounts.values()) or len(all_events)
    if split_card:                                   # this card is one bug of a mixed issue: its own sampled numbers only
        vcounts = dict(Counter(e.get('version') or '?' for e in events))
    sig = Counter((e.get('signal') or '?') for e in events)
    reasons = [why,
               f"{sum(vcounts.values()) or len(events)} events in {', '.join(versions) or 'all versions'} (last {days} days); {len(events)} sampled",
               f"crashed in {found[0]['file']}:{found[0]['line']}" if found else 'crash site not located in this repo (unsymbolized or third-party)']
    reasons.append(f"code read as shipped: {src_ref['ref']} @ {src_ref['sha'][:10]} (the commit build {sample.get('version_code')} was made from)"
                   if src_ref else 'code read from the working copy: the commit this build was made from is not known (add app.source_refs)')
    if scope:
        reasons.append(f'{scope}; Crashlytics grouped them only because the frames are unsymbolized. Repro target, root cause and '
                       f'fix are for THIS stack only')
    if len(sgroups) > 1:
        reasons.append(f'{len(sgroups)} slightly different stacks inside this card; case built on the largest ({len(sgroups[0][1])} events)')
    missing = sorted({e.get('version_code') for e in events if not symbolize.resolve(e.get('version_code'), (e.get('version') or '').split(' ')[0], native_lib)[0]} - {None})
    assumed = sorted({e.get('version_code') for e in events if any(f.get('assumed_lib') for f in e['frames'])})
    if assumed:
        reasons.append(f"builds {', '.join(assumed)} symbolized with the 1.25.1 library of another build (same version name); add their own APK to confirm")
    if missing:
        reasons.append(f"no symbols in the store for build(s) {', '.join(missing)}: add the release libMYJNILIB26.so with `sentinel.py symbols add <aab|apk|so> --version-code <code>`")
    rec = {
        'source_ref': src_ref or {}, 'issue': card, 'id': card, 'crashlytics_issue': iid, 'card_title': groups.card_title(card) if split_card else '',
        'issue_events': issue_events, 'kind': _kind(iss), 'title': iss.get('title') or iss.get('issueTitle'),
        'subtitle': iss.get('subtitle') or iss.get('issueSubtitle'), 'signal': sig.most_common(1)[0][0] if sig else '',
        'console_url': f"https://console.firebase.google.com/project/{cfg['app'].get('firebase_project','myzesty-1be4d')}/crashlytics/app/android:{cfg['app']['package']}/issues/{iid}",
        'events': sum(vcounts.values()) or len(events), 'real_users': crashlytics.users(vrep), 'internal': 0,
        'with_dump': sum(1 for e in events if e['frames']), 'with_breadcrumbs': sum(1 for e in events if e['logs']),
        'with_native_logs': sum(1 for e in events if any('file:' in l for l in e['logs'])),
        'versions': vcounts, 'android': crashlytics.counts(osrep, 'operatingSystem'), 'models': crashlytics.counts(devrep, 'device'),
        'manufacturers': {}, 'buckets': {'E_native_engine': 1} if verdict == 'engine' else {}, 'last_events': {}, 'last_screens': {},
        'native_sites': {f"{c['file']}:{c['line']}": 1 for c in found}, 'uptime_bands': {}, 'per_day': {},
        'first_date': min((e['time'] or '' for e in events), default='')[:10], 'last_date': max((e['time'] or '' for e in events), default='')[:10],
        'verdict': verdict, 'confidence': confidence, 'reasons': reasons,
        'field_fingerprint': '\n'.join(f['func'].split(' + ')[0] for f in frames if f.get('lib') == native_lib and f.get('func'))[:2000],
        'sessions_hashed': len(events), 'csv': '', 'generated': dt.date.today().isoformat(), 'source': 'crashlytics-api (read-only, Firebase CLI login)',
        'frames': frames, 'breadcrumbs': sample.get('logs', [])[:25], 'sample_event': {k: sample.get(k) for k in ('time', 'version', 'device', 'os', 'process_state', 'signal', 'subtitle')},
        'stack_groups': [{'signature': g.get('stack3') or g['key'], 'key': g['key'], 'card': g['card'], 'mine': g['card'] == card, 'newStack': g.get('newStack', False),
                          'events': len(v), 'versions': sorted({x.get('version') or '?' for x in v}), 'devices': sorted({x.get('device') or '?' for x in v})}
                         for g in (groups.load(iid).get('groups') or []) for v in [[e for e in all_events if groups.key_of(e['frames'], native_lib) == g['key']]]]
                        or [{'signature': k, 'events': len(v), 'versions': sorted({x.get('version') for x in v}), 'devices': sorted({x.get('device') for x in v})} for k, v in sgroups],
        'code': code, 'scenarios': [{'score': sc, 'name': nm, 'tags': tg} for sc, nm, tg in ranked], 'status': 'triaged',
    }
    if split_card:                                   # device/OS split of THIS bug (the issue-wide reports mix bugs)
        rec['models'] = dict(Counter(e.get('device') or '?' for e in events))
        rec['android'] = dict(Counter(e.get('os') or '?' for e in events))
        rec['users_scope'] = 'Crashlytics issue (all its crashes)'
    rec['repro_plan'] = (('Run on the ANRSan/debug build, fresh process per scenario; crashes are caught as native crash dumps, ANRs as ANRSan chains:\n\n' +
                          '\n'.join(f"- `python3 tools/stress/scenarios.py run {s['name']} --repeat 3` (score {s['score']}, tags {', '.join(s['tags'])})" for s in rec['scenarios']))
                         if rec['scenarios'] else 'No scenario matches the evidence yet: draft one from the breadcrumbs (skills/scenario-match) and review it.') if verdict == 'engine' else \
        'Not scheduled: the crashed thread is outside the engine. Hand to the owning team with this file.'
    rec['next_steps'] = {'engine': '1. Reproduce. 2. Propose fix (sentinel.py fix). 3. Verify by replaying the same seed. 4. Draft PR + MZ ticket.',
                         'not-engine': '1. File to the owning team. 2. Close for the engine team.',
                         'insufficient': '1. Widen the window or wait for events in the selected releases.'}.get(verdict, '')
    rec['narrative'] = ''
    if use_llm and verdict == 'engine' and found:
        ctx = {k: rec[k] for k in ('title', 'subtitle', 'signal', 'frames', 'breadcrumbs', 'sample_event', 'versions', 'models')}
        ctx['code'] = [{k: c.get(k) for k in ('func', 'file', 'line', 'body', 'callers')} for c in found]
        rec['narrative'] = llm.run('root-cause', 'Find the root cause. Facts (do not change any number):\n' + json.dumps(ctx, indent=1, default=str), cfg, OUT, f'{iid}.rootcause')
    return rec


def render(rec):
    L = [f"# {rec['kind']} `{rec['id']}` — case file", '',
         f"**{rec.get('title') or ''}** — {rec.get('subtitle') or ''}", '',
         f"{rec['events']} events, {rec['real_users']} users in {', '.join(rec['versions']) or 'the window'}; {rec['first_date']} – {rec['last_date']}. "
         f"Source: {rec['source']}. Generated {rec['generated']}. [Open in Crashlytics]({rec['console_url']})", '',
         '## Verdict', '', f"**{rec['verdict'].upper()}** (confidence {rec['confidence']})", '', *[f'- {r}' for r in rec['reasons']], '',
         '## Distinct stacks in this issue', '', '| Events | Top engine frames | Versions | Devices |', '|---|---|---|---|',
         *[f"| {g['events']} | `{g['signature']}` | {', '.join(g['versions'])} | {', '.join(g['devices'])} |" for g in rec.get('stack_groups', [])], '',
         '## Crashed thread (sample event)', '', '```', *[f"{i:>2}  {f.get('lib',''):<20} {f.get('func') or ('0x%x' % int(f['address']) if f.get('address') else '')}{'   ' + f['srcline'] if f.get('srcline') else ''}" for i, f in enumerate(rec['frames'][:25])], '```', '']
    for c in [c for c in rec['code'] if c.get('found')]:
        L += [f"## Code: `{c['func'].split(' + ')[0]}` — {c['file']}:{c['line']}", '', '```cpp', c.get('body', ''), '```', '',
              f"Called from {len(c.get('callers', []))} places" + (':' if c.get('callers') else '.'), '', *[f'- `{x}`' for x in c.get('callers', [])[:10]], '']
    if rec.get('narrative'):
        L += ['## Root cause (agent analysis, review before acting)', '', rec['narrative'], '']
    L += ['## Breadcrumbs before the crash (newest first)', '', '```', *rec['breadcrumbs'], '```', '',
          '## Reproduction plan', '', rec['repro_plan'], '', '## Next steps', '', rec['next_steps'], '']
    return '\n'.join(L)


def write(rec):
    os.makedirs(OUT, exist_ok=True)
    base = os.path.join(OUT, f"{rec['kind']}_{rec['id']}_case_file")
    rec['case_file'] = os.path.basename(base) + '.md'
    json.dump(rec, open(base + '.json', 'w', encoding='utf-8'), indent=1, default=str)
    open(base + '.md', 'w', encoding='utf-8').write(render(rec))
    return base + '.md'
