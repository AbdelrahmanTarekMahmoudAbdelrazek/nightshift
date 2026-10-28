#!/usr/bin/env python3
"""Night Shift "ship it" (26 Oct): turn a finished review or a verified fix into real work items. Every command runs only
because a person clicked a board button (the worker runs it for that job), and every one has --dry to see what would
be sent without sending anything.

  shipit.py check                          what the Bitbucket / Jira tokens can do (reads only)
  shipit.py pr-comments  --pr 3211         PR review -> inline comments on the verified findings + one summary comment
                                           (re-run = Night Shift edits its own comments; fixed findings are marked resolved)
  shipit.py crash-pr     --case <id> [--base CPP-1.25.2]
                                           verified crash/ANR fix -> branch nightshift/<id> pushed + a DRAFT PR with the
                                           cause, the phone A/B result, the repro video and links
  shipit.py jira-create  --case <id> --draft <file.json>
                                           the Jira draft the developer edited on the board -> a real Jira card (Bug),
                                           repro video attached
Never merges, never pushes to an existing branch other than its own nightshift/... branch."""
import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import warnings

warnings.filterwarnings('ignore')                      # old-Python notices from the Google libraries are not job news

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ns import config, bitbucket, bbwrite  # noqa: E402

OUT = os.path.join(HERE, 'out')
REPO = config.REPO


class AlreadyFixed(Exception):
    def __init__(self, how, commits):
        super().__init__(how)
        self.how, self.commits = how, commits


def say(msg):                                          # the worker shows lines starting with ▶ / ✖ in the job log
    print(f'▶ {msg}', flush=True)


def fail(msg):
    print(f'✖ {msg}', flush=True)
    sys.exit(1)


def board_url(cfg):
    pid = (cfg.get('firebase') or {}).get('projectId') or 'nightshift-myzesty'
    return f'https://{pid}.web.app'


def fire_update(coll, doc, data):
    try:
        from ns import fire
        fire.client().collection(coll).document(doc).set(data, merge=True)
    except Exception as e:
        print(f'⚠ board not updated ({str(e)[:160]}); the result is still in out/shipit/', flush=True)


def keep(name, data):
    d = os.path.join(OUT, 'shipit')
    os.makedirs(d, exist_ok=True)
    json.dump(data, open(os.path.join(d, name), 'w'), indent=1, default=str)


# ================================================================== PR review -> Bitbucket comments
SEV = {'blocker': 'Blocker', 'major': 'Major', 'minor': 'Minor', 'suggestion': 'Suggestion'}


def _ftag(f):
    return 'f-' + hashlib.sha1(f"{f.get('file')}|{f.get('title')}".encode()).hexdigest()[:10]


def pr_comments(key, cfg, dry=False, max_inline=6, payload=None):
    p = os.path.join(OUT, 'pr', f'{key}.json')
    if not os.path.exists(p):
        fail(f'no Night Shift review for PR {key} on this computer (out/pr/{key}.json): run the review first')
    rec = json.load(open(p))
    repo, num = bitbucket.parse_key(key)
    live = bitbucket.get_pr(num, repo)
    if live.get('state') not in ('OPEN', ''):
        fail(f'PR {key} is {live.get("state")}: nothing posted')
    link = f"{board_url(cfg)}/pr.html?id={key}"
    reviewed, now = str(rec.get('head') or '')[:12], str(live.get('head') or '')[:12]
    stale = bool(reviewed and now and not now.startswith(reviewed[:7]) and not reviewed.startswith(now[:7]))
    fs = [f for f in rec.get('findings') or [] if isinstance(f, dict)]
    ver = [f for f in fs if f.get('tier') == 'verified']
    sus = [f for f in fs if f.get('tier') == 'suspected' and f.get('severity') in ('blocker', 'major')]
    order = {'blocker': 0, 'major': 1, 'minor': 2, 'suggestion': 3}
    ver.sort(key=lambda f: order.get(f.get('severity'), 9))
    lines = bbwrite.diff_lines(bitbucket.pr_diff(num, repo)) if not stale else {}
    existing = bbwrite.comments(repo, num)
    say(f'PR {key}: {len(ver)} verified finding(s), {len(sus)} suspected major/blocker; reviewed at {reviewed or "?"}, PR head {now or "?"}'
        + (' (NEW COMMITS since the review: inline comments skipped, summary only)' if stale else ''))
    results, inline_done, summary_only = [], set(), []
    if payload is not None:                            # exactly what the developer saw (and maybe edited) on the board
        ver = [{'file': str(x.get('file') or ''), 'line': x.get('line'), 'title': str(x.get('title') or ''),
                'severity': str(x.get('severity') or ''), 'body': str(x.get('body') or '')[:20000]}
               for x in (payload.get('comments') or [])[:20] if isinstance(x, dict) and str(x.get('body') or '').strip()]
        for f in ver:
            try:
                f['line'] = int(f['line'])
            except (TypeError, ValueError):
                f['line'] = None
        say(f'posting the {len(ver)} comment(s) and the summary as shown on the board')
    for f in ver:
        tag = _ftag(f)
        path, ln = str(f.get('file') or ''), f.get('line')
        body = f.get('body') or (f"**Night Shift · {SEV.get(f.get('severity'), f.get('severity', ''))} · verified**\n\n"
                f"**{f.get('title', '').strip()}**\n\n{str(f.get('problem') or '').strip()}\n\n"
                + (f"**Suggested fix:** {str(f.get('fix')).strip()}\n\n" if f.get('fix') else '')
                + f"[Proof, replay and the judges' votes on Night Shift →]({link})")
        on_diff = path in lines and isinstance(ln, int) and ln in lines[path]
        if on_diff and len(inline_done) < max_inline:
            act, cid = bbwrite.upsert_comment(repo, num, tag, body, inline=(path, ln), existing=existing, dry=dry)
            inline_done.add(tag)
            results.append({'tag': tag, 'action': act, 'id': cid, 'file': path, 'line': ln})
            say(f'{act}: inline comment on {path}:{ln} ({f.get("severity")})')
        else:
            summary_only.append(f)
    # findings Night Shift commented on before but no longer reports: mark resolved (edit, never delete)
    cur = {_ftag(f) for f in ver}
    for x in existing:
        raw = str((x.get('content') or {}).get('raw') or '')
        m = re.search(r'\[//\]: # \(nightshift-(f-[0-9a-f]{10})\)', raw)
        if m and m.group(1) not in cur and not x.get('deleted') and 'Resolved by a later Night Shift review' not in raw:
            new = ('~~' + raw.split('\n', 1)[0].strip('*') + '~~\n\n**Resolved by a later Night Shift review** (commit '
                   f'{now or "?"}): this finding is no longer reported.')
            act, _ = bbwrite.upsert_comment(repo, num, m.group(1), new, existing=existing, dry=dry)
            say(f'{act}: marked an earlier finding resolved')
    head = {'blocking': 'Blocking issue found', 'changes': 'Changes suggested', 'approve': 'Looks good'}.get(
        str(rec.get('verdict')), str(rec.get('verdict') or '').capitalize())
    s = [f"### Night Shift review: {head}", '', str(rec.get('headline') or '').strip(), '']
    s.append(f"**{len(ver)} verified** · {len(sus)} suspected major/blocker · reviewed commit `{reviewed or '?'}`"
             + (f" (the PR has newer commits: re-run the review)" if stale else ''))
    if summary_only:
        s += ['', '**Verified, outside the changed lines:**'] + [
            f"- **{SEV.get(f.get('severity'), '')}** `{f.get('file')}:{f.get('line')}` — {str(f.get('title') or '').strip()}" for f in summary_only]
    if sus:
        s += ['', '**Worth a look (not proven):**'] + [
            f"- {SEV.get(f.get('severity'), '')} `{f.get('file')}:{f.get('line')}` — {str(f.get('title') or '').strip()}" for f in sus[:5]]
    s += ['', f"[Full review on Night Shift: replays, scenarios, proof →]({link})"]
    text = '\n'.join(s)
    if payload is not None and str(payload.get('summary') or '').strip():
        text = str(payload['summary']).strip()[:30000]
        if summary_only:                               # comments whose line is not part of the PR diff go in the summary
            text += '\n\n**Also verified, outside the changed lines:**\n' + '\n'.join(
                f"- `{f.get('file')}:{f.get('line')}` — {f.get('title')}" for f in summary_only)
    act, cid = bbwrite.upsert_comment(repo, num, 'summary', text, existing=existing, dry=dry)
    say(f'{act}: summary comment')
    res = {'pr': key, 'reviewed': reviewed, 'prHead': now, 'stale': stale, 'inline': results, 'summary': act, 'dry': dry}
    keep(f'pr-{key}.json', res)
    if not dry:
        fire_update('prs', key, {'bbPosted': {'at': _now(), 'inline': len(inline_done), 'summary': act, 'stale': stale,
                                              'url': live.get('url', '')}})
    say(f'done: {len(inline_done)} inline + summary on {live.get("url") or key}' + (' (dry run: nothing sent)' if dry else ''))
    return res


# ================================================================== verified fix -> branch + draft PR
def _case(cid):
    for kind in ('CRASH', 'ANR'):
        p = os.path.join(OUT, f'{kind}_{cid}_case_file.json')
        if os.path.exists(p):
            return json.load(open(p))
    return {}


def _fix(cid):
    p = os.path.join(OUT, 'fix', f'{cid}.json')
    fx = json.load(open(p)) if os.path.exists(p) else {}
    ho = fx.get('handover') or {}
    body = str(ho.get('pr_body') or '')
    if '```json' in body or body.lstrip().startswith('{'):   # an older hand-over kept the model's raw JSON answer
        try:                                             # raw_decode: the JSON may itself hold ``` code fences
            j, _ = json.JSONDecoder().raw_decode(body[body.index('{'):])
            if isinstance(j, dict):
                fx['handover'] = {**ho, **j}
        except ValueError:
            pass
    return fx


def _git(args, cwd, timeout=600, check=True):
    r = subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f'git {" ".join(args[:4])}: {(r.stderr or r.stdout).strip()[-400:]}')
    return r.stdout.strip()


def _idents(diff_text):
    """The code names a diff changes (identifiers of 4+ characters on its -/+ lines), e.g. Looper, getLooper."""
    words = set()
    for ln in (diff_text or '').splitlines():
        if ln[:1] in '+-' and not ln.startswith(('+++', '---')):
            words |= set(re.findall(r'[A-Za-z_][A-Za-z0-9_]{3,}', ln))
    return words - {'return', 'const', 'static', 'void', 'bool', 'true', 'false', 'std', 'auto', 'else', 'null', 'nullptr',
                    'this', 'override', 'virtual', 'include', 'define', 'LOGE', 'LOGD', 'LOGI', 'shared_ptr', 'unique_ptr'}


def _fix_commits(wt, files, patch='', days=120):
    """Commits on the base that already fixed the same code: they touched the fix's files AND changed the same code
    names the verified fix changes. Best match first; unrelated fixes in the same files are left out."""
    if not files:
        return []
    want = _idents(patch)
    out = _git(['log', f'--since={days}.days', '--no-merges', '--format=%h|%ad|%an|%s', '--date=short', 'HEAD', '--'] + files,
               wt, check=False)
    rows = []
    for ln in out.splitlines()[:40]:
        h, d, a, subj = (ln.split('|', 3) + ['', '', '', ''])[:4]
        got = _idents(_git(['show', '--format=', h, '--'] + files, wt, check=False))
        common = want & got
        if len(common) < 3:                            # shares too little code with the fix: not the same fix
            continue
        pr = _git(['log', '--merges', '--ancestry-path', '--reverse', '--format=%s', f'{h}..HEAD', '--grep=pull request #'],
                  wt, check=False).splitlines()
        m = re.search(r'pull request #(\d+)', pr[0]) if pr else None
        rows.append({'sha': h, 'date': d, 'author': a, 'subject': subj[:140], 'pr': int(m.group(1)) if m else None,
                     'score': len(common), 'shared': sorted(common)[:8]})
    if not rows:
        return []
    by_pr = {}
    for r in rows:                                     # the PR that shares the most code with the fix wins
        by_pr[r['pr']] = by_pr.get(r['pr'], 0) + r['score']
    best = max(by_pr, key=by_pr.get)
    return sorted([r for r in rows if r['pr'] == best], key=lambda r: -r['score'])


def _repo_slug(cwd):
    url = _git(['remote', 'get-url', 'origin'], cwd)
    m = re.search(r'bitbucket\.org[:/]([^/]+)/([^/.]+?)(?:\.git)?$', url)
    if not m:
        raise RuntimeError(f'origin is not a Bitbucket repo: {url}')
    return m.group(1), m.group(2)


def crash_pr(cid, cfg, base=None, dry=False, payload=None):
    if not re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', cid):
        fail(f'bad case id {cid!r}')
    fx, case = _fix(cid), _case(cid)
    status = str(fx.get('status') or '')
    if not status.startswith('fix-verified'):
        fail(f'no fix verified on the phone for {cid} (status: {status or "none"}): run "Propose + verify fix" first')
    patch = fx.get('patch') or ''
    if not patch.strip():
        fail('the verified fix has no patch text')
    base = base or (cfg.get('lab') or {}).get('base_branch') or 'development'
    if not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', base):
        fail(f'bad base branch {base!r}')
    ws, repo = _repo_slug(REPO)
    branch = 'nightshift/' + ('anr' if case.get('kind') == 'ANR' else 'crash') + '-' + cid.replace('~', '-')[:41]
    kind = 'ANR' if case.get('kind') == 'ANR' else 'Crash'
    title = str((fx.get('handover') or {}).get('pr_title') or f"Fix {kind.lower()}: {case.get('title', '')} ({case.get('subtitle', '')})").strip()[:200]
    if payload and str(payload.get('summary') or '').strip():
        title = str(payload['summary']).strip()[:200]
    say(f'{kind} {cid[:8]}: verified fix ({status}) -> {branch} on {ws}/{repo}, draft PR into {base}')
    wt = tempfile.mkdtemp(prefix='ns_pr_')
    shutil.rmtree(wt)
    files = sorted(set(re.findall(r'^\+\+\+ b/(\S+)', patch, re.M)))
    already, sha = None, ''
    try:
        _git(['fetch', '--no-tags', 'origin', f'+refs/heads/{base}:refs/nightshift/base/{base}'], REPO)
        _git(['worktree', 'add', '--detach', wt, f'refs/nightshift/base/{base}'], REPO)
        pf = os.path.join(wt, '.ns_fix.patch')
        open(pf, 'w').write(patch if patch.endswith('\n') else patch + '\n')
        applied = False
        for extra in ([], ['--ignore-whitespace'], ['--3way']):
            if subprocess.run(['git', 'apply', '--check'] + extra + [pf], cwd=wt, capture_output=True).returncode == 0:
                _git(['apply'] + extra + [pf], wt)
                applied = True
                say('patch applied on ' + base + (f' ({extra[0]})' if extra else ''))
                break
        same = not applied and subprocess.run(['git', 'apply', '--reverse', '--check', '--ignore-whitespace', pf], cwd=wt,
                                              capture_output=True).returncode == 0
        os.remove(pf)
        if same:
            raise AlreadyFixed(f'the same change is already on {base}', [])
        if not applied:
            fixes = _fix_commits(wt, files, patch)
            if fixes:
                raise AlreadyFixed(f'{base} already has a fix in the same code', fixes)
            raise RuntimeError(f'the verified patch does not apply on the latest {base}: the code changed since; re-run the fix')
        _git(['add', '-A'] + files, wt)
        msg = f"{title}\n\nNight Shift case {cid}\n{board_url(cfg)}/#problems/m-{cid}\n\nVerified on the lab phone: {str(fx.get('note') or '')[:400]}"
        who = os.environ.get('NS_REQUESTED_BY') or 'nightshift@localhost'
        _git(['-c', 'user.name=Night Shift', '-c', f'user.email={who}', 'commit', '-q', '-m', msg], wt)
        sha = _git(['rev-parse', 'HEAD'], wt)
        if dry:
            say(f'dry run: would push {sha[:10]} to {branch} (not pushed)')
        else:
            _git(['push', '-q', '--force-with-lease', 'origin', f'HEAD:refs/heads/{branch}'], wt, timeout=900)
            say(f'pushed {sha[:10]} to {branch}')
    except AlreadyFixed as e:
        already = e
    finally:
        subprocess.run(['git', 'worktree', 'remove', '--force', wt], cwd=REPO, capture_output=True)
        subprocess.run(['git', 'worktree', 'prune'], cwd=REPO, capture_output=True)
    if already is not None:
        prs = sorted({c['pr'] for c in already.commits if c.get('pr')})
        shas = ', '.join(c['sha'][:7] for c in already.commits)
        by = (f"PR #{prs[0]}" if len(prs) == 1 else 'PRs ' + ', '.join('#' + str(p) for p in prs)) if prs else ''
        say(f"ALREADY FIXED on {base}" + (f" by {by}" if by else '') + (f" (commits {shas})" if shas else ' (same change)')
            + ': no new PR needed.')
        say('If Crashlytics still shows this crash in builds made after these commits, run "Propose + verify fix" again.')
        res = {'case': cid, 'base': base, 'state': 'already-fixed', 'how': already.how, 'commits': already.commits, 'prs': prs}
        keep(f'crash-{cid}.json', res)
        if not dry:
            fire_update('cases', cid, {'fixPr': {'state': 'already-fixed', 'base': base, 'how': already.how,
                                                 'commits': already.commits[:6], 'prs': prs, 'at': _now()}})
        return res
    desc = pr_description(cid, case, fx, cfg, files)
    if payload and str(payload.get('description') or '').strip():   # the text the developer saw (and maybe edited)
        desc = str(payload['description']).strip()[:30000]
    act, url, prid = bbwrite.create_or_update_pr(repo, branch, base, title, desc, dry=dry)
    say(f'{act} draft PR {url or ""}')
    res = {'case': cid, 'branch': branch, 'base': base, 'sha': sha, 'pr': url, 'prId': prid, 'action': act, 'dry': dry}
    keep(f'crash-{cid}.json', res)
    if not dry:
        fire_update('cases', cid, {'fixPr': {'url': url, 'branch': branch, 'base': base, 'sha': sha[:12], 'at': _now()}})
    return res


def pr_description(cid, case, fx, cfg, files):
    b = board_url(cfg)
    kind = 'ANR' if case.get('kind') == 'ANR' else 'Crash'
    ho = fx.get('handover') or {}
    vid = case.get('reproVideoUrl') or ''
    rows = [f"## {kind}: {case.get('title', '')}", '',
            f"**What users hit:** {case.get('subtitle') or case.get('title', '')} — {case.get('events', '?')} events, "
            f"{case.get('real_users', '?')} users, versions {', '.join(case.get('versions') or []) or '?'}.", '']
    if ho.get('pr_body'):
        rows += [str(ho['pr_body']).strip(), '']
    rows += ['### Proof', f"- **Verified on the lab phone:** {str(fx.get('note') or '').strip()}"]
    if vid:
        rows.append(f"- **Repro video (before the fix):** {b}{vid}")
    rows += [f"- **Night Shift case:** {b}/#problems/m-{cid}"]
    if case.get('console_url'):
        rows.append(f"- **Crashlytics:** {case['console_url']}")
    rv = fx.get('review') or {}
    if rv.get('verdict'):
        rows.append(f"- **Night Shift code review of this patch:** {rv.get('verdict')} — {str(rv.get('summary') or '')[:300]}")
    rows += ['', '### Files', *[f"- `{f}`" for f in files], '',
             '_Draft opened by Night Shift from a fix verified A/B on the lab phone. A person reviews and merges it._']
    return '\n'.join(rows)[:30000]


# ================================================================== Jira draft -> real card
def _adf(text):
    """Plain text with '- ' / '1. ' lists and URLs -> Atlassian Document Format."""
    def inline(s):
        out, pos = [], 0
        for m in re.finditer(r'https?://[^\s)>\]]+', s):
            if m.start() > pos:
                out.append({'type': 'text', 'text': s[pos:m.start()]})
            out.append({'type': 'text', 'text': m.group(0), 'marks': [{'type': 'link', 'attrs': {'href': m.group(0)}}]})
            pos = m.end()
        if pos < len(s):
            out.append({'type': 'text', 'text': s[pos:]})
        return out or [{'type': 'text', 'text': ' '}]
    content, lst = [], None
    for raw in (text or '').splitlines():
        ln = raw.rstrip()
        mb, mo = re.match(r'^\s*[-*•] (.*)', ln), re.match(r'^\s*\d+[.)] (.*)', ln)
        if mb or mo:
            t = 'bulletList' if mb else 'orderedList'
            if not lst or lst['type'] != t:
                lst = {'type': t, 'content': []}
                content.append(lst)
            lst['content'].append({'type': 'listItem', 'content': [{'type': 'paragraph', 'content': inline((mb or mo).group(1))}]})
            continue
        lst = None
        if not ln.strip():
            continue
        if ln.endswith(':') and len(ln) < 60:
            content.append({'type': 'heading', 'attrs': {'level': 3}, 'content': inline(ln.rstrip(':'))})
        else:
            content.append({'type': 'paragraph', 'content': inline(ln)})
    return {'type': 'doc', 'version': 1, 'content': content or [{'type': 'paragraph', 'content': inline(' ')}]}


def _jira_req(method, path, body=None, files=None, c=None):
    from ns import jira
    c = c or jira.creds()
    auth = base64.b64encode(f"{c['email']}:{c['token']}".encode()).decode()
    roots = [c['base_url'] + '/rest/api/3']
    try:
        cloud = json.loads(urllib.request.urlopen(c['base_url'] + '/_edge/tenant_info', timeout=30).read())['cloudId']
        roots.append(f'https://api.atlassian.com/ex/jira/{cloud}/rest/api/3')
    except Exception:
        pass
    last = None
    for root in roots:
        hdr = {'Authorization': f'Basic {auth}', 'Accept': 'application/json'}
        if files:
            bnd = uuid.uuid4().hex
            data = b''
            for name, blob, ctype in files:
                data += (f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n').encode() + blob + b'\r\n'
            data += f'--{bnd}--\r\n'.encode()
            hdr.update({'Content-Type': f'multipart/form-data; boundary={bnd}', 'X-Atlassian-Token': 'no-check'})
        else:
            data = json.dumps(body).encode() if body is not None else None
            if data:
                hdr['Content-Type'] = 'application/json'
        try:
            with urllib.request.urlopen(urllib.request.Request(root + path, data=data, method=method, headers=hdr), timeout=300) as r:
                t = r.read().decode('utf-8', 'replace')
                return json.loads(t) if t.strip() else {}
        except urllib.error.HTTPError as e:
            last = f'{e.code} {e.read().decode("utf-8", "replace")[:400]}'
            if e.code not in (401, 403, 404):
                break
    raise RuntimeError(f'Jira refused ({last}). Creating cards needs a token with write:jira-work (classic API token, '
                       'or scoped with write:jira-work) in ~/.config/nightshift/jira.json')


def jira_create(cid, cfg, draft_file, dry=False):
    d = json.load(open(draft_file))
    summary, desc = str(d.get('summary') or '').strip()[:250], str(d.get('description') or '').strip()
    if not summary or not desc:
        fail('the Jira draft has no summary or description')
    case = _case(cid) if re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', cid) else {}
    proj = str((cfg.get('integrations') or {}).get('jira_project') or 'MZ')
    fields = {'project': {'key': proj}, 'summary': summary, 'issuetype': {'name': str(d.get('type') or 'Bug')},
              'description': _adf(desc), 'labels': ['nightshift', 'anr' if case.get('kind') == 'ANR' else 'crash']}
    vid = case.get('reproVideoUrl') or ''
    vpath = os.path.join(HERE, 'board', 'public', vid.lstrip('/')) if vid else ''
    say(f'Jira {proj}: "{summary[:80]}"' + (f' + repro video {os.path.basename(vpath)}' if vpath and os.path.exists(vpath) else ' (no repro video on this computer)'))
    if dry:
        keep(f'jira-{cid}.dry.json', fields)
        say('dry run: nothing sent to Jira (payload in out/shipit/)')
        return {'dry': True}
    j = _jira_req('POST', '/issue', {'fields': fields})
    key = j.get('key')
    say(f'created {key}')
    if vpath and os.path.exists(vpath) and os.path.getsize(vpath) < 90_000_000:
        try:
            _jira_req('POST', f'/issue/{key}/attachments', files=[(f'repro_{cid[:8]}.mp4', open(vpath, 'rb').read(),
                                                                   mimetypes.guess_type(vpath)[0] or 'video/mp4')])
            say('repro video attached')
        except Exception as e:
            print(f'⚠ video not attached ({str(e)[:200]})', flush=True)
    from ns import jira
    url = f"{jira.creds()['base_url']}/browse/{key}"
    keep(f'jira-{cid}.json', {'key': key, 'url': url})
    if case:
        fire_update('cases', cid, {'jira': {'key': key, 'url': url, 'at': _now()}})
    return {'key': key, 'url': url}


def _now():
    import datetime as dt
    return dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('check')
    a = sp.add_parser('pr-comments'); a.add_argument('--pr', required=True); a.add_argument('--dry', action='store_true'); a.add_argument('--payload')
    b = sp.add_parser('crash-pr'); b.add_argument('--case', required=True); b.add_argument('--base'); b.add_argument('--dry', action='store_true'); b.add_argument('--payload')
    j = sp.add_parser('jira-create'); j.add_argument('--case', required=True); j.add_argument('--draft', required=True); j.add_argument('--dry', action='store_true')
    a_ = ap.parse_args()
    cfg = config.load()
    try:
        if a_.cmd == 'check':
            print(json.dumps(bbwrite.check(), indent=1))
            try:
                from ns import jira
                c = jira.creds()
                print(json.dumps({'jira_site': c['base_url'], 'jira_token_file': os.path.exists(jira.CFG),
                                  'note': 'Jira write access is only known on the first create (needs write:jira-work)'}, indent=1))
            except Exception as e:
                print(f'jira: {e}')
        elif a_.cmd == 'pr-comments':
            pr_comments(a_.pr, cfg, dry=a_.dry, payload=json.load(open(a_.payload)) if a_.payload else None)
        elif a_.cmd == 'crash-pr':
            crash_pr(a_.case, cfg, base=a_.base, dry=a_.dry, payload=json.load(open(a_.payload)) if a_.payload else None)
        elif a_.cmd == 'jira-create':
            jira_create(a_.case, cfg, a_.draft, dry=a_.dry)
    except (bbwrite.BBError, RuntimeError) as e:
        fail(str(e))


if __name__ == '__main__':
    main()
