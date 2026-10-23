#!/usr/bin/env python3
"""Night Shift CLI.

  sentinel.py runlog add --flow triage --issue <id> --engineer AT --mode before --minutes 310 [--review 0] [--outcome ..]
  sentinel.py runlog summary
  sentinel.py triage --events <issue.csv> --issue <crashlytics-id> [--kind ANR|CRASH] [--llm]
  sentinel.py diagram --findings <anrsan_findings.md> --id F008 [--fix "0=join with 2 s deadline" --fix "1=checks abort flag"] [--verified]
  sentinel.py diagram --findings <anrsan_findings.md> --all --html
  sentinel.py match --evidence "MsgLooper::~MsgLooper" --evidence "video_editing_cancel"
  sentinel.py pull <issue-id|console-link> [--llm] [--publish]    (steps 1-5, read-only Crashlytics API)
  sentinel.py fix <issue-id>                                        (step 8: patch proposal, never commits)
  sentinel.py board [--live]                               (static page from out/, or board/public for Firebase Hosting)
  sentinel.py publish | worker [--dry] | staff add <email> | ingest slack|play     (Firestore, worker credentials)
  sentinel.py sync [--only crashlytics|play]               (daily gathering: crash + ANR lists of the last 3 releases)
  sentinel.py play-login                                   (one time: link your Play Console Google login, read-only)
  sentinel.py guard --base <branch> --head <branch>        (Phase 2: prints the plan, does not run)

Stdlib only. Nothing here writes to Jira, Slack or Bitbucket yet; outputs land in tools/nightshift/out/.
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ns import config, runlog, anrsan, diagrams, triage, match, llm, board, case as casemod  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')


def _fill(tpl: str, values: dict) -> str:
    for k, v in values.items():
        tpl = tpl.replace('{{' + k + '}}', str(v))
    return tpl


def cmd_runlog(a, cfg):
    path = config.repo_path(cfg['measurement']['runlog'])
    if a.sub == 'add':
        runlog.add(path, a.flow, a.issue, a.engineer, a.mode, a.minutes, a.review, a.outcome or '', a.notes or '', a.date)
        print(f'logged: {a.mode} {a.flow} {a.issue} {a.minutes}+{a.review} min -> {path}')
    else:
        out, grand = runlog.summary(path, cfg['measurement'].get('runs_per_month', {}))
        print(runlog.format_summary(out, grand))


def cmd_triage(a, cfg):
    screens = [s.strip() for s in str(cfg['app'].get('editor_screens', '')).split(',') if s.strip()]
    releases = [] if a.all_versions else [v.strip() for v in str(cfg['app'].get('release_versions', '')).split(',') if v.strip()]
    if [v.lower() for v in releases] == ['auto']:     # follow the board: the live version (+ the previous one during a rollout)
        try:
            st = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'releases_state.json')))
            releases = [x for x in (st.get('live'), st.get('overlap')) if x]
        except Exception:
            releases = []
    t = triage.analyse(a.events, a.issue, screens, releases)
    scen = match.load_scenarios(config.repo_path(cfg['lab']['stress_runner']))
    evidence = list(t.native_sites) + list(t.last_events) + list(t.last_screens)
    ranked = match.rank(scen, match.evidence_tags(evidence)) if t.verdict in ('engine', 'mixed') else []
    if t.verdict == 'not-engine':
        repro = 'Not scheduled: the dumps point outside the engine. Hand the case to the owning team with this file.'
    elif t.verdict == 'insufficient':
        repro = 'Not scheduled: no dumps or breadcrumbs yet. Re-run triage when Android 11-13 devices report, or widen the date range.'
    elif ranked:
        repro = 'Run on an ANRSan build, fresh process per scenario, then merge findings and match fingerprints:\n\n' + '\n'.join(
            f'- `python3 tools/stress/scenarios.py run {name} --repeat 3`  (score {sc}, tags {", ".join(tags)})' for sc, name, tags in ranked) + \
            '\n- `python3 tools/stress/anrsan_findings.py stress_results` then `sentinel.py diagram --findings <...>/anrsan_findings.md --id <F>`'
    else:
        repro = 'No scenario matches the evidence. Draft a new one with skills/scenario-match from the breadcrumbs below, review it, add it to tools/stress/scenarios.py.'
    nxt = {
        'engine': '1. Reproduce (above). 2. If a lab chain fingerprint matches the field sites, open MZ ticket with this file + root-cause diagram. 3. Patch, replay same seed, attach solution diagram only if clean.',
        'not-engine': '1. File to the owning team (FCM / RN / SDK) with the bucket table. 2. Add a Crashlytics custom key so the next issue self-classifies. 3. Close for the engine team.',
        'mixed': '1. Split the export by cause_bucket and run triage per split. 2. Treat the E_native_engine slice as its own issue.',
        'insufficient': '1. Wait for more events or request dumps. 2. Re-run.',
    }[t.verdict]
    data = dict(
        kind=a.kind, issue=t.issue, package=cfg['app']['package'], first_date=t.first_date, last_date=t.last_date,
        events=t.events, real_users=t.real_users, internal=t.internal, with_dump=t.with_dump, with_breadcrumbs=t.with_breadcrumbs,
        with_native_logs=t.with_native_logs, csv=os.path.relpath(a.events, config.REPO), today=dt.date.today().isoformat(),
        verdict_word={'engine': 'ENGINE: the native video engine is implicated', 'not-engine': 'NOT THE ENGINE',
                      'mixed': 'MIXED: split before reproducing', 'insufficient': 'INSUFFICIENT DATA'}[t.verdict],
        confidence=t.confidence, reasons='\n'.join(f'- {r}' for r in t.reasons), sessions=t.sessions_hashed,
        versions_inline=', '.join(f'{k} ({v})' for k, v in t.versions.most_common(6)),
        android_inline=', '.join(f'{k}: {v}' for k, v in t.android.most_common(8)),
        uptime_inline=', '.join(f'{k}: {v}' for k, v in t.uptime_bands.most_common()),
        buckets_table=triage.table(t.buckets, 10, t.with_dump) or '| (none) | 0 | 0% |',
        last_events_table=triage.table(t.last_events, 10, t.with_breadcrumbs) or '| (none) | 0 | 0% |',
        last_screens_table=triage.table(t.last_screens, 8, t.with_breadcrumbs) or '| (none) | 0 | 0% |',
        models_table=triage.table(t.models, 10, t.events), field_fingerprint=t.field_fingerprint or '(no native-engine log sites)',
        repro_plan=repro, next_steps=nxt, runlog_hint=f'sentinel.py runlog add --flow triage --issue {t.issue} --mode after --minutes 0 --review <min>',
    )
    narrative = ''
    if a.llm:
        facts = json.dumps({k: v for k, v in data.items() if k not in ('repro_plan', 'next_steps', 'runlog_hint')}, indent=1, ensure_ascii=False)
        narrative = llm.run('anr-triage', f'Write the narrative paragraphs for this case file. Facts (do not alter any number):\n{facts}', cfg, OUT, f'{a.issue}.triage')
    data['narrative'] = narrative
    md = _fill(open(os.path.join(HERE, 'templates', 'case_file.md'), encoding='utf-8').read(), data)
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f'{a.kind}_{a.issue}_case_file.md')
    open(out, 'w', encoding='utf-8').write(md)
    rec = {k: (dict(v) if hasattr(v, 'most_common') else v) for k, v in t.__dict__.items()}
    rec.update(kind=a.kind, csv=data['csv'], generated=data['today'], case_file=os.path.basename(out),
               scenarios=[{'score': sc, 'name': n, 'tags': tg} for sc, n, tg in ranked], repro_plan=repro, next_steps=nxt,
               narrative=narrative, status='triaged')
    json.dump(rec, open(out.replace('.md', '.json'), 'w'), indent=1, default=str)
    print(f'verdict: {t.verdict} ({t.confidence}); {t.events} events, {t.with_dump} dumps')
    for r in t.reasons:
        print('  -', r)
    print(f'case file: {out}')


def cmd_diagram(a, cfg):
    fs = anrsan.parse(a.findings)
    targets = fs if a.all else [anrsan.get(fs, a.id)]
    os.makedirs(OUT, exist_ok=True)
    blocks = []
    for f in targets:
        rc = diagrams.root_cause(f)
        blocks.append(rc)
        p = os.path.join(OUT, f'{f.id}_root_cause.mmd')
        open(p, 'w', encoding='utf-8').write(rc + '\n')
        if not a.all:
            print(rc)
            print(f'\nfingerprint:\n{anrsan.fingerprint(f)}\n-> {p}')
        if a.fix:
            changes = {}
            for item in a.fix:
                k, _, v = item.partition('=')
                changes[int(k)] = v
            sol = diagrams.solution(f, changes, a.verified)
            blocks.append(sol)
            ps = os.path.join(OUT, f'{f.id}_solution.mmd')
            open(ps, 'w', encoding='utf-8').write(sol + '\n')
            print(f'\n{sol}\n-> {ps}')
    if a.all:
        print(f'{len(targets)} root-cause diagrams written to {OUT}')
    if a.html:
        ph = os.path.join(OUT, 'diagrams.html' if a.all else f'{targets[0].id}.html')
        open(ph, 'w', encoding='utf-8').write(diagrams.html_page(blocks, 'Night Shift · ' + ('all findings' if a.all else targets[0].id)))
        print(f'preview: {ph}')


def cmd_match(a, cfg):
    scen = match.load_scenarios(config.repo_path(cfg['lab']['stress_runner']))
    scores = match.evidence_tags(a.evidence)
    print('tag scores:', scores)
    for sc, name, tags in match.rank(scen, scores, a.top):
        print(f'  {sc:>2}  {name:<36} {", ".join(tags)}')


def cmd_pull(a, cfg):
    rec = casemod.build(a.issue, cfg, use_llm=a.llm)
    out = casemod.write(rec)
    print(f"{rec['kind']} {rec['id']}: {rec.get('title')} — {rec.get('subtitle') or ''}")
    print(f"verdict: {rec['verdict']} ({rec['confidence']}); {rec['events']} events, {rec['real_users']} users; versions {', '.join(rec['versions'])}")
    for r in rec['reasons']:
        print('  -', r)
    for c in rec['code']:
        print(f"  code: {c['func'][:70]} -> {c.get('file')}:{c.get('line')}" if c.get('found') else f"  code: {c['func'][:70]} -> not found in repo")
    print('  scenarios:', ', '.join(s['name'] for s in rec['scenarios']) or 'none matched')
    print(f'case file: {out}\nraw API responses: tools/nightshift/out/raw/{rec["id"]}/')
    if a.publish:
        from ns import fire
        print('published:', fire.publish(fire.client(), board.build(cfg)))


def cmd_fix(a, cfg):
    from ns import fix
    import glob
    paths = glob.glob(os.path.join(OUT, f'*_{a.issue}_case_file.json'))
    if not paths:
        raise SystemExit(f'no case for {a.issue}; run: sentinel.py pull {a.issue}')
    rec = json.load(open(paths[0]))
    patch, answer, status = fix.propose(rec, cfg)
    print(answer[:3000])
    print(f'\npatch: {patch or "none"} — {status}')


def cmd_symbols(a, cfg):
    from ns import symbolize
    if a.sub == 'add':
        m = symbolize.add(a.src, a.version_code, cfg['app']['native_lib'], version_name=a.version_name)
        print(f"stored {m['lib']} for build {m['version_code']}: BuildId {m['build_id']}, {m['functions']} functions from {m['table']}")
    else:
        import glob
        for meta in sorted(glob.glob(os.path.join(symbolize.STORE, '*', 'meta.json'))):
            m = json.load(open(meta)); print(f"{m['version_code']:>12}  {m['build_id']}  {m['table']:<8} {m['functions']:>6} fns  {m['source']}")


def cmd_board(a, cfg):
    out = board.write(cfg, live=a.live)
    if a.live:
        print(f'live board built: {out}\ndeploy with:  cd tools/nightshift/board && firebase deploy --only hosting,firestore')
    else:
        print(f'board: {out}\nopen it with:  open {os.path.relpath(out, config.REPO)}')


def cmd_publish(a, cfg):
    from ns import fire
    db = fire.client()
    counts = fire.publish(db, board.build(cfg))
    print(f'published to Firestore: {counts}')


def cmd_worker(a, cfg):
    from ns import fire, worker
    worker.Worker(fire.client(), cfg, dry=a.dry).serve()


def cmd_sync(a, cfg):
    from ns import fire, sync
    st = sync.run(fire.client(), cfg, sources=(a.only,) if a.only else ('crashlytics', 'play'))
    bad = [k for k in ('crashlytics', 'play') if isinstance(st.get(k), dict) and not st[k].get('ok')]
    if bad:
        sys.exit(1)


def cmd_analyse(a, cfg):
    from ns import fire, analyse
    analyse.run_all(fire.client(), cfg, limit=a.limit, force=a.force)


def cmd_symbols_fetch(a, cfg):
    from ns import symbols_auto
    for vc in a.codes:
        symbols_auto.fetch(cfg, vc, a.version_name)


def cmd_merge(a, cfg):
    from ns import fire, merge
    merge.build(fire.client(), cfg)


def cmd_play_login(a, cfg):
    from ns import sync
    sync.play_login()


def cmd_staff(a, cfg):
    from ns import fire
    db = fire.client()
    email = a.email.lower()
    if a.sub == 'add':
        db.collection('staff').document(email).set({'addedAt': dt.datetime.now().isoformat(timespec='seconds'), 'note': a.note or ''})
        print(f'allowlisted {email}')
    else:
        db.collection('staff').document(email).delete()
        print(f'removed {email}')


def cmd_ingest(a, cfg):
    from ns import fire
    db = fire.client()
    if a.source == 'slack':
        from ns import ingest_slack
        ch = cfg['integrations'].get('crashlytics_alert_channel_id')
        if not ch:
            raise SystemExit('set integrations.crashlytics_alert_channel_id in nightshift.yaml')
        alerts = ingest_slack.fetch_alerts(ch)
        print(f'{len(alerts)} Crashlytics alert messages; new cases: {ingest_slack.upsert_cases(db, alerts, cfg["app"]["package"])}')
    else:
        from ns import ingest_play
        issues = ingest_play.search_issues(cfg['app']['package'], a.days)
        print(f'{len(issues)} Play error issues; upserted {ingest_play.upsert_play(db, issues, cfg["app"]["package"])}')


def cmd_guard(a, cfg):
    print('Guard (Phase 2) would run on the self-hosted runner:')
    print(f"  1. git diff {a.base}...{a.head} -- {cfg['app']['engine_paths']}   (skip if empty)")
    print(f"  2. {cfg['lab']['anrsan_install']}")
    print('  3. bash tools/infer/run_infer.sh')
    print("  4. python3 tools/stress/scenarios.py run --tag <tags of touched files> --repeat 2")
    print('  5. python3 tools/stress/anrsan_findings.py stress_results  -> diff fingerprints vs base')
    print('  6. skills/threading-review -> PR comment; skills/changelog -> release note line')


def main(argv=None):
    p = argparse.ArgumentParser(prog='sentinel.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--config', default=None)
    sp = p.add_subparsers(dest='cmd', required=True)

    r = sp.add_parser('runlog'); rs = r.add_subparsers(dest='sub', required=True)
    ra = rs.add_parser('add')
    ra.add_argument('--flow', required=True, choices=runlog.FLOWS); ra.add_argument('--issue', required=True)
    ra.add_argument('--engineer', required=True); ra.add_argument('--mode', required=True, choices=['before', 'after'])
    ra.add_argument('--minutes', type=int, required=True); ra.add_argument('--review', type=int, default=0)
    ra.add_argument('--outcome'); ra.add_argument('--notes'); ra.add_argument('--date')
    rs.add_parser('summary')

    t = sp.add_parser('triage'); t.add_argument('--events', required=True); t.add_argument('--issue', required=True)
    t.add_argument('--kind', default='ANR', choices=['ANR', 'CRASH']); t.add_argument('--llm', action='store_true')
    t.add_argument('--all-versions', action='store_true', help='ignore app.release_versions scoping')

    d = sp.add_parser('diagram'); d.add_argument('--findings', required=True); d.add_argument('--id'); d.add_argument('--all', action='store_true')
    d.add_argument('--fix', action='append', help='"<chain idx>=<new behaviour from the patch>"'); d.add_argument('--verified', action='store_true')
    d.add_argument('--html', action='store_true')

    m = sp.add_parser('match'); m.add_argument('--evidence', action='append', required=True); m.add_argument('--top', type=int, default=5)
    pl = sp.add_parser('pull', help='steps 1-5 for one Crashlytics issue (read-only): pull, classify, locate code, match scenarios, case file')
    pl.add_argument('issue', help='issue id or console link'); pl.add_argument('--llm', action='store_true'); pl.add_argument('--publish', action='store_true')
    sy = sp.add_parser('symbols', help='native symbol store per versionCode'); sys_ = sy.add_subparsers(dest='sub', required=True)
    sa = sys_.add_parser('add'); sa.add_argument('src', help='.aab, .apk, unstripped .so, or a build dir'); sa.add_argument('--version-code', required=True); sa.add_argument('--version-name')
    sys_.add_parser('list')
    fx = sp.add_parser('fix', help='step 8: propose a patch for a pulled case (never commits)'); fx.add_argument('issue')
    bd = sp.add_parser('board', help='export out/board.json and the case board page'); bd.add_argument('--live', action='store_true', help='build board/public for Firebase Hosting (reads Firestore)')
    sp.add_parser('publish', help='mirror out/ data into Firestore (worker credentials)')
    wk = sp.add_parser('worker', help='listen for queued jobs in Firestore and run them on this Mac'); wk.add_argument('--dry', action='store_true')
    st = sp.add_parser('staff'); sts = st.add_subparsers(dest='sub', required=True)
    for n in ('add', 'remove'):
        x = sts.add_parser(n); x.add_argument('email'); x.add_argument('--note')
    ig = sp.add_parser('ingest'); ig.add_argument('source', choices=['slack', 'play']); ig.add_argument('--days', type=int, default=7)
    sn = sp.add_parser('sync', help='gather crash + ANR issues of the last 3 releases (Crashlytics + Play) onto the board')
    sn.add_argument('--only', choices=['crashlytics', 'play'])
    an = sp.add_parser('analyse', help='root cause + diagrams for every problem on the board (no code changes)')
    an.add_argument('--limit', type=int); an.add_argument('--force', action='store_true')
    sf = sp.add_parser('symbols-fetch', help='download a build\'s native library from Google Play into the symbol store')
    sf.add_argument('codes', nargs='+'); sf.add_argument('--version-name')
    sp.add_parser('merge', help='pair the same problem across Google Play and Crashlytics (uses the last sync)')
    sp.add_parser('play-login', help='one time: link your Google login for Play vitals (read-only)')
    g = sp.add_parser('guard'); g.add_argument('--base', default='CPP-1.25.2'); g.add_argument('--head', default='HEAD')

    a = p.parse_args(argv)
    cfg = config.load(a.config)
    ser = str((cfg.get('lab') or {}).get('phone_serial') or '').strip()
    if ser and not os.environ.get('ANDROID_SERIAL'):
        # every adb / gradle install started from here (worker, sync, merge, local tasks) goes to the lab phone only;
        # AGP's install tasks honour ANDROID_SERIAL too. An explicit ANDROID_SERIAL (an emulator lane, a51repro) is kept.
        os.environ['ANDROID_SERIAL'] = ser
    {'runlog': cmd_runlog, 'triage': cmd_triage, 'diagram': cmd_diagram, 'match': cmd_match, 'guard': cmd_guard,
     'board': cmd_board, 'pull': cmd_pull, 'fix': cmd_fix, 'symbols': cmd_symbols, 'publish': cmd_publish, 'worker': cmd_worker,
     'staff': cmd_staff, 'ingest': cmd_ingest, 'sync': cmd_sync, 'play-login': cmd_play_login, 'merge': cmd_merge, 'analyse': cmd_analyse, 'symbols-fetch': cmd_symbols_fetch}[a.cmd](a, cfg)


if __name__ == '__main__':
    main()
