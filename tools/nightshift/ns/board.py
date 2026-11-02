"""Build the case board data (`out/board.json`) and the static page (`out/board/index.html`).

Step 1 data sources: triage JSONs in out/, the newest `anrsan_findings.md` under stress_results/, runlog.csv.
Step 2 swaps the page's data source for Firestore; the page shape does not change.
"""
import datetime as dt
import glob
import re
import json
import os

from . import anrsan, diagrams, runlog, config
if not hasattr(config, 'profile'):                 # long-running worker: config.py is not in its per-job reload list;
    import importlib as _il                          # pick up the profile helpers once (LAB survives the reload)
    _il.reload(config)

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(HERE, 'out')


def latest_findings(results_dir: str):
    paths = sorted(glob.glob(os.path.join(results_dir, '*', 'anrsan_findings.md')))
    return paths[-1] if paths else None


def build(cfg: dict) -> dict:
    issues = []
    for p in sorted(glob.glob(os.path.join(OUT, '*_case_file.json'))):
        rec = json.load(open(p, encoding='utf-8'))
        rec['id'] = rec.get('issue')
        issues.append(rec)
    findings, run = [], None
    fp = latest_findings(config.repo_path(cfg['lab']['results_dir']))
    if fp:
        run = os.path.basename(os.path.dirname(fp))
        for f in anrsan.parse(fp):
            d = f.to_dict()
            d['mermaid'] = diagrams.root_cause(f)
            d['fingerprint'] = anrsan.fingerprint(f)
            findings.append(d)
    rl_path = config.repo_path(cfg['measurement']['runlog'])
    summary, grand = runlog.summary(rl_path, cfg['measurement'].get('runs_per_month', {}))
    return {
        'generated_at': dt.datetime.now().isoformat(timespec='seconds'),
        'app': cfg['app'], 'integrations': cfg['integrations'],
        'sources': {'crashlytics': 'csv export (BigQuery streaming in step 2)', 'play': 'not connected (step 2)',
                    'lab_run': run},
        'issues': issues, 'findings': findings,
        'runlog': {'rows': runlog.rows(rl_path), 'summary': summary, 'total_hours': grand},
    }


def _fb(cfg: dict) -> dict:
    """The browser config: the board's Firebase settings + the project profile (name, repos) for labels and links."""
    fb = dict(cfg.get('firebase') or {})
    try:
        p = config.profile(cfg)
        fb['profile'] = {'name': p['name'], 'main_repo': p['main_repo'], 'repos': p['repos'], 'review_repos': p['review_repos'],
                         'jira_keys': p['jira_keys'], 'code_packages': p['code_packages']}
    except Exception:
        pass
    return fb


def write(cfg: dict, live: bool = False) -> str:
    data = build(cfg)
    os.makedirs(os.path.join(OUT, 'board'), exist_ok=True)
    json.dump(data, open(os.path.join(OUT, 'board.json'), 'w', encoding='utf-8'), indent=1, default=str)
    tpl = open(os.path.join(HERE, 'board', 'index.html'), encoding='utf-8').read()
    if live:
        fb = cfg.get('firebase') or {}
        missing = [k for k in ('apiKey', 'authDomain', 'projectId', 'appId') if not fb.get(k)]
        if missing:
            raise SystemExit(f'nightshift.yaml firebase: missing {missing} (board/README.md step 4)')
        page = tpl.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg)))
        out_dir = os.path.join(HERE, 'board', 'public')
    else:
        blob = json.dumps(data, default=str).replace('</', '<\\/')
        page = tpl.replace('/*__NS_DATA__*/null', blob)
        out_dir = os.path.join(OUT, 'board')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'index.html')
    open(out, 'w', encoding='utf-8').write(page)
    # 30 Oct: previews of the new look, same code and data: /next.html (board), card2 / audio2 (new detail pages),
    # pr2 (the PR page in the new colors). board/fresh.html holds the colors (palette C) shared by all of them.
    def _rd(nm):
        p_ = os.path.join(HERE, 'board', nm)
        return open(p_, encoding='utf-8').read() if os.path.exists(p_) else ''
    fresh, skin = _rd('fresh.html'), _rd('skin_workspace.html')
    def _fb_page(src):
        return src.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg))) if live else src
    def _wr(nm, src):
        if src and '</body>' in src:
            open(os.path.join(out_dir, nm), 'w', encoding='utf-8').write(src.replace('</body>', fresh + '\n</body>', 1))
    if skin:
        _wr('next.html', page.replace('</body>', skin + '\n</body>', 1))
        # 1 Nov: the new look IS the board now ("/"); the old page stays at /classic.html
        open(os.path.join(out_dir, 'classic.html'), 'w', encoding='utf-8').write(page)
        _wr('index.html', page.replace('</body>', skin + '\n</body>', 1))
    for nm in ('card2.html', 'audio2.html'):
        _wr(nm, _fb_page(_rd(nm)))
    _wr('pr2.html', _fb_page(_rd('pr.html')))
    prp = os.path.join(HERE, 'board', 'pr.html')         # the six-page PR review page (reads prs/<id> from Firestore)
    if os.path.exists(prp):
        pr_page = open(prp, encoding='utf-8').read()
        if live:
            pr_page = pr_page.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg)))
        open(os.path.join(out_dir, 'pr.html'), 'w', encoding='utf-8').write(pr_page)
    adp = os.path.join(HERE, 'board', 'audio.html')      # one Audio Check on its own page (reads audiochecks/<id>)
    if os.path.exists(adp):
        ad_page = open(adp, encoding='utf-8').read()
        if live:
            ad_page = ad_page.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg)))
        open(os.path.join(out_dir, 'audio.html'), 'w', encoding='utf-8').write(ad_page)
    cnp = os.path.join(HERE, 'board', 'connect.html')   # "Connect this computer" (opened by setup.sh)
    if os.path.exists(cnp):
        cn_page = open(cnp, encoding='utf-8').read()
        if live:
            cn_page = cn_page.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg)))
        open(os.path.join(out_dir, 'connect.html'), 'w', encoding='utf-8').write(cn_page)
    cdp = os.path.join(HERE, 'board', 'card.html')       # the card root-cause review page (reads cardreviews/<KEY>)
    if os.path.exists(cdp):
        cd_page = open(cdp, encoding='utf-8').read()
        if live:
            cd_page = cd_page.replace('/*__NS_FIREBASE__*/null', json.dumps(_fb(cfg)))
        open(os.path.join(out_dir, 'card.html'), 'w', encoding='utf-8').write(cd_page)
    # 1 Nov: every page follows the board's light / dark choice (the moon button, saved as ns.theme), not only the OS
    th = re.search(r"<script>\(function\(\)\{var t=null;try\{t=localStorage\.getItem\('ns\.theme'\).*?</script>", page)
    if th:
        for fn_ in os.listdir(out_dir):
            fp_ = os.path.join(out_dir, fn_)
            if fn_.endswith('.html') and fn_ not in ('index.html', 'next.html'):
                src_ = open(fp_, encoding='utf-8').read()
                if "getItem('ns.theme')" not in src_ and '<head>' in src_:
                    open(fp_, 'w', encoding='utf-8').write(src_.replace('<head>', '<head>\n' + th.group(0), 1))
    return out
