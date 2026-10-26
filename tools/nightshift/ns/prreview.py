"""PR review (Night Shift tool 1, no phone): gather open Bitbucket PRs, check each out in its own worktree, classify it
(crash/ANR/behaviour fix, feature, refactor), run the specialist review skills in parallel with Opus, merge them into one
verdict, store it (Firestore prs/<id> + out/pr/<id>.json). Read-only towards Bitbucket and the user's working copy."""
import datetime as dt
import json
import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

from . import config, llm, prvisual, kotlinctx
if not hasattr(config, 'profile'):                 # long-running worker: config.py is not in its per-job reload list;
    import importlib as _il                          # pick up the profile helpers once (LAB survives the reload)
    _il.reload(config)
import importlib
prvisual = importlib.reload(prvisual)          # the worker reloads only this module per job: pick up prvisual changes too
llm = importlib.reload(llm)                    # and llm (run(..., usage=) for real token use)
kotlinctx = importlib.reload(kotlinctx)        # and the Kotlin-side context

OUT = os.path.join(config.REPO, 'tools/nightshift/out/pr')
TREES = os.path.expanduser('~/.nightshift_pr')
# Real Claude plugins (installed in the Claude CLI on the Mac by plugsetup.py):
#   pr-review-toolkit@claude-code-plugins (Anthropic): code-reviewer, silent-failure-hunter, code-simplifier, comment-analyzer...
#   nightshift-review@nightshift (ours, tools/nightshift/claude-plugin): the five specialists below
TOOLKIT = ('/pr-review-toolkit:review-pr all parallel', 'Anthropic pr-review-toolkit')
REVIEWERS = [('nightshift-review:pr-performance', 'performance'), ('nightshift-review:pr-memory', 'memory'),
             ('nightshift-review:pr-architecture', 'placement / SOLID'), ('nightshift-review:pr-lifetime', 'lifetime / concurrency'),
             ('nightshift-review:pr-anr', 'ANR risk')]
PLUGIN_TOOLS = 'Read,Grep,Glob,Skill,Task,Agent,Bash(git diff:*),Bash(git status:*),Bash(git log:*),Bash(git show:*)'
_SEM = threading.Semaphore(6)                       # model calls at once (all PRs together)


def _git(args, cwd=None, timeout=300):
    return subprocess.run(['git'] + args, cwd=cwd or config.REPO, capture_output=True, text=True, timeout=timeout)


def _model(cfg):
    return (cfg.get('llm') or {}).get('model_pr') or 'opus'


def _json(txt):
    """The answer's JSON. Models sometimes add a second, small block after the main one ("here is the corrected s10
    entry"): take the LARGEST valid block as the answer and apply the smaller ones as corrections by id, instead of
    losing the whole answer to the last block."""
    good = []
    for cand in re.findall(r'```json\s*\n(.*?)```', txt or '', re.S):
        try:
            good.append((len(cand), json.loads(cand)))
        except (ValueError, TypeError):
            continue
    if good:
        main = max(good, key=lambda x: x[0])[1]
        if isinstance(main, dict):
            for _, o in good:
                if o is main or not isinstance(o, dict):
                    continue
                fixes = o.get('scenarios') if isinstance(o.get('scenarios'), list) else [o] if o.get('id') else []
                lst = main.get('scenarios') if isinstance(main.get('scenarios'), list) else None
                for fx in fixes:
                    if lst is None or not isinstance(fx, dict) or not fx.get('id'):
                        continue
                    k = next((i for i, x in enumerate(lst) if isinstance(x, dict) and x.get('id') == fx['id']), None)
                    if k is None:
                        lst.append(fx)
                    else:
                        lst[k] = {**lst[k], **fx}
        return main
    try:
        return json.loads(txt or '')
    except (ValueError, TypeError):
        pass
    m2 = re.search(r'(\{.*\})', txt or '', re.S)
    try:
        return json.loads(m2.group(1)) if m2 else {}
    except ValueError:
        return {}


def gitdir(pr):
    """The git folder a PR's commits live in: the native working copy for the main repo (as before), a partial clone
    under ~/.nightshift_pr/repos/<repo> for any other repo of the profile (made on first use, read-only use)."""
    main = config.profile().get('main_repo')
    repo = pr.get('repo') or main
    if not repo or repo == main:
        return config.REPO
    path = os.path.join(TREES, 'repos', repo)
    if not os.path.isdir(os.path.join(path, '.git')):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        url = kotlinctx._remote_base() + repo + '.git'
        r = subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', '--no-tags', url, path],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode:
            raise RuntimeError(f"clone of {repo} failed: {r.stderr.strip()[:200]}")
    return path


def checkout(pr, log):
    """Worktree with the PR head (detached); the user's working copy and branches are never touched."""
    os.makedirs(TREES, exist_ok=True)
    wt = os.path.join(TREES, f"pr-{pr['id']}")
    gd = pr.setdefault('_gitdir', gitdir(pr))
    if pr.get('source') and not pr.get('local'):
        r = _git(['fetch', '--no-tags', 'origin', f"+refs/heads/{pr['source']}:refs/nightshift/pr/{pr['id']}"], cwd=gd, timeout=1800)
        if r.returncode:
            raise RuntimeError(f"git fetch of {pr['source']} failed: {r.stderr.strip()[:200]}")
        if pr.get('dest'):
            _git(['fetch', '--no-tags', 'origin', f"+refs/heads/{pr['dest']}:refs/nightshift/base/{pr['id']}"], cwd=gd, timeout=1800)
    if os.path.isdir(wt):
        r = _git(['checkout', '--detach', '--force', pr['head']], cwd=wt)
    else:
        r = _git(['worktree', 'add', '--detach', '--force', wt, pr['head']], cwd=gd)
    if r.returncode:
        raise RuntimeError(f"worktree for PR {pr['id']} failed: {r.stderr.strip()[:200]}")
    base_ref = pr.get('base') or f"refs/nightshift/base/{pr['id']}"
    mb = _git(['merge-base', base_ref, pr['head']], cwd=gd).stdout.strip()
    if mb:                                           # PR changes = uncommitted changes on top of the merge-base, so the
        _git(['reset', '-q', mb], cwd=wt)            # plugins' `git diff` shows exactly this PR (files stay at PR head)
        new = _git(['ls-files', '--others', '--exclude-standard'], cwd=wt).stdout.split()
        if new:
            _git(['add', '-N', '--'] + new, cwd=wt)
    return wt, mb


def _fs(rec):
    """Firestore cannot hold arrays inside arrays, which the visual review is full of: store those parts as JSON text
    (viewJson, claimsJson, codeJson). The local out/pr/<id>.json keeps the plain structure."""
    def nested(x, inarr=False):                      # an array inside an array anywhere: Firestore rejects the whole save
        if isinstance(x, list):
            return inarr or any(nested(y, True) for y in x)
        if isinstance(x, dict):
            return any(nested(y) for y in x.values())
        return False
    out = {}
    for k, v in rec.items():
        if k in ('view', 'claims', 'code'):
            continue
        if nested(v):                                # never lose a whole review over one field: store it as JSON text
            out[k + 'Json'], v = json.dumps(v, ensure_ascii=False), None
        out[k] = v
    for k in ('view', 'claims', 'code'):
        out[k + 'Json'] = json.dumps(rec[k], ensure_ascii=False) if rec.get(k) else None
    return out


def _board_crashes(db, k=40):
    out = []
    try:
        for d in db.collection('cases').stream():
            c = d.to_dict() or {}
            fr = [f.get('fn', '') if isinstance(f, dict) else str(f) for f in (c.get('frames') or [])][:4]
            out.append({'id': d.id, 'title': (c.get('title') or '')[:120], 'kind': c.get('kind', ''), 'events': c.get('events', 0),
                        'frames': fr})
    except Exception:
        pass
    out.sort(key=lambda x: -(x.get('events') or 0))
    return out[:k]


def _call(skill, prompt, cfg, tag, cwd, tools='Read,Grep,Glob', timeout=1200, meter=None, model=None):
    u = {}
    with _SEM:
        txt = llm.run(skill, prompt, cfg, OUT, tag, tools=tools, cwd=cwd, timeout=timeout, model=model or _model(cfg), usage=u)
    if meter is not None:
        meter.add(u)
    return txt


class Stages:
    """Time and real model usage of every review stage, for the 'How it was reviewed' table on the PR page. Usage is
    what the Claude CLI reports for each call (all turns, including the files the model read), summed per stage."""
    KEYS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')

    def __init__(self, t0):
        self.t0, self.rows, self.cur, self.lock = t0, [], None, threading.Lock()
        self.total = {'tokens': 0, 'cost_usd': 0.0, 'calls': 0}

    def _t(self, t):
        return '%d:%02d' % divmod(int((t - self.t0).total_seconds()), 60)

    def start(self, name, who, cls=''):
        self.end()
        self.cur = {'name': name, 'who': who, 'a': dt.datetime.now(), 'tok': 0, 'cost': 0.0, 'calls': 0, 'cls': cls, 'result': ''}

    def add(self, u):
        with self.lock:
            if self.cur is not None and u:
                self.cur['tok'] += sum(int(u.get(k) or 0) for k in self.KEYS)
                self.cur['cost'] += float(u.get('cost_usd') or 0)
                self.cur['calls'] += int(u.get('calls') or 0)

    def end(self, result=None):
        c = self.cur
        if c is None:
            return
        if result is not None:
            c['result'] = str(result)[:200]
        b = dt.datetime.now()
        tok = ('%dk' % max(1, round(c['tok'] / 1000))) if c['tok'] else '–'
        if c['cost']:
            tok += ' · $%.2f' % c['cost']
        self.rows.append({'name': c['name'], 'who': c['who'],
                          'when': self._t(c['a']) + ('' if (b - c['a']).total_seconds() < 2 else '–' + self._t(b)),
                          'tokens': tok, 'result': c['result'], 'cls': c['cls'], 'tok': c['tok'], 'cost': round(c['cost'], 4)})
        self.total['tokens'] += c['tok']
        self.total['cost_usd'] += c['cost']
        self.total['calls'] += c['calls']
        self.cur = None

    def mark(self, name, who, result, cls=''):
        self.rows.append({'name': name, 'who': who, 'when': self._t(dt.datetime.now()), 'tokens': '–', 'result': result, 'cls': cls})


def _judge_names(cls):
    a = ' '.join([str(cls.get('type', ''))] + [str(x) for x in cls.get('areas') or []]).lower()
    second = ('Threading judge' if re.search(r'thread|race|lock|mutex|concurren|anr', a) else
              'Audio judge' if 'audio' in a else 'Renderer judge' if re.search(r'\bgl\b|render|shader|gpu|frame', a) else
              'UI judge' if re.search(r'kotlin|\bui\b|activity|fragment|view', a) else 'Code judge')
    return ['Skeptic', second]


def _feedback_notes(db, k=25):
    """What reviewers answered on earlier findings (Decide page, saved to prs/<id>/feedback). 'Not a problem' answers
    are shown to the hunters and judges as past false alarms, so the same noise is not raised again."""
    out = []
    try:
        for d in db.collection('prs').stream():
            for f in d.reference.collection('feedback').stream():
                x = f.to_dict() or {}
                if x.get('decision') in ('no', 'agree'):
                    out.append({'pr': d.id, 'decision': 'not a problem' if x['decision'] == 'no' else 'agreed',
                                'title': str(x.get('title') or '')[:140], 'where': str(x.get('where') or '')[:60],
                                'tier': x.get('tier') or '', 'note': str(x.get('text') or '')[:200]})
    except Exception:
        pass
    no = [x for x in out if x['decision'] == 'not a problem'][:k]
    return no + [x for x in out if x['decision'] == 'agreed'][:max(0, k - len(no))]


def _prev(pr):
    """The last saved review of this PR (plain JSON, out/pr/<id>.json), or None."""
    f = os.path.join(OUT, f"{pr['id']}.json")
    try:
        rec = json.load(open(f))
        return rec if rec.get('stage') == 'reviewed' and rec.get('head') and rec.get('view') else None
    except (OSError, ValueError):
        return None


def _incremental(pr, prev, files, log):
    """New commits on a PR that was already reviewed: which of this PR's files did they change? None = full review."""
    if not prev or prev.get('head') == pr['head'] or pr.get('local'):
        return None
    old = prev['head']
    gd = pr.get('_gitdir') or config.REPO
    if _git(['merge-base', '--is-ancestor', old, pr['head']], cwd=gd).returncode != 0:
        log(f"PR #{pr['id']}: the branch was rewritten since {old[:10]}: full review")
        return None
    names = set(_git(['diff', '--name-only', old, pr['head']], cwd=gd).stdout.split())
    commits = _git(['log', '--format=%h %s', f"{old}..{pr['head']}"], cwd=gd).stdout.splitlines()
    changed = sorted(names & set(files))
    log(f"PR #{pr['id']}: {len(commits)} new commit(s) since {old[:10]}; {len(changed)} of this PR's files changed")
    return {'old': old, 'changed': changed, 'commits': commits}


def _carry(prev, pr, mb, files, wt, diff, desc, inc, st, t0, log):
    """New commits that touch none of the PR's files (e.g. merges from the base): keep the review, re-check its lines."""
    rec = dict(prev)
    view = rec.get('view') or {}
    st.start('Code-path check', 'no AI')
    n = prvisual.pathcheck(view, wt, diff, why_prefix='After the new commits: ')
    st.end(f"{n} cited line(s) re-checked")
    try:
        rec['code'] = prvisual.build({}, wt, diff, [])[1]
    except Exception:
        pass
    rec.update({'head': pr['head'], 'mergeBase': mb, 'view': view, 'stage': 'reviewed', 'early': False,
                'commits': [{'hash': c['hash'][:10], 'message': (c.get('message') or '').splitlines()[0][:160] if c.get('message') else ''}
                            for c in pr.get('commits') or []][:30] or rec.get('commits'),
                'since': f"{len(inc['commits'])} new commit(s) since the review at {inc['old'][:10]} ({', '.join(c.split()[0] for c in inc['commits'][:3])}). "
                         "They change no line in this PR's files, so nothing was re-reviewed.",
                'stages': (prev.get('stages') or []) + st.rows})
    os.makedirs(OUT, exist_ok=True)
    json.dump(rec, open(os.path.join(OUT, f"{pr['id']}.json"), 'w'), indent=1)
    log(f"PR #{pr['id']}: new commits touch none of its files: review kept ({n} line(s) re-checked)")
    return rec


def _merge_prev(prev, view, inc):
    """Re-review of new commits: the earlier scenarios, hunks and paths stay (their lines are re-checked next); the new
    ones are added with ids that cannot clash. Hunks of files that changed carry a note."""
    pv = json.loads(json.dumps(prev.get('view') or {}))
    ren = {}
    for x in view.get('scenarios') or []:
        ren[x['id']] = 'n' + x['id']
        x['id'] = ren[x['id']]
        x['new'] = True
    hren = {}
    for h in view.get('hunks') or []:
        hren[h['id']] = 'n-' + h['id']
        h['id'] = hren[h['id']]
        h['note'] = ('New commit: ' + h.get('note', '')).strip()
        h['links'] = [[ren.get(l[0], l[0])] + list(l[1:]) for l in h.get('links') or []]
    changed = {c.split('/')[-1] for c in inc['changed']}
    for h in pv.get('hunks') or []:
        if str(h.get('file', '')).split(' ')[0] in changed:
            h['note'] = f"Lines as of {inc['old'][:10]}; this file changed since. " + h.get('note', '')
    off = len(prev.get('findings') or [])
    for x in view.get('scenarios') or []:
        pass                                          # findings were merged before pr-visual ran, indexes already match
    for p in view.get('paths') or []:
        p['cov'] = ren.get(p.get('cov'), p.get('cov'))
    out = dict(pv)
    out['scenarios'] = (pv.get('scenarios') or []) + (view.get('scenarios') or [])
    out['hunks'] = (pv.get('hunks') or []) + (view.get('hunks') or [])
    out['paths'] = (pv.get('paths') or []) + (view.get('paths') or [])
    out['order'] = (pv.get('order') or []) + [dict(o, hunk=hren.get(o.get('hunk'), o.get('hunk'))) for o in view.get('order') or []]
    out['finding_links'] = (pv.get('finding_links') or []) + [dict(l, scenario=ren.get(l.get('scenario'), l.get('scenario')),
                                                                  hunk=hren.get(l.get('hunk'), l.get('hunk')))
                                                             for l in view.get('finding_links') or [] if l.get('finding', -1) >= off]
    out['files'] = view.get('files') or pv.get('files')
    out['dropped'] = pv.get('dropped') or []
    for k in ('tldr', 'ready', 'heads', 'before', 'adds'):
        if view.get(k):
            out[k] = view[k]
    return out


REPLAY_EXAMPLE = '{"title": "The removed overlay stays selected", "cols": [["Overlay add", "OverlayManager.addOverlay()"], ["selectedOverlayKey", "current selection"], ["Editor toolbar", "Volume / Speed buttons"]], "modes": {"bug": "This PR", "fix": "Suggested fix"}, "bug": {"bars": [{"col": 1, "from": 0, "to": 4, "cls": "bar-risk", "text": "points at an overlay that no longer exists", "end": "never cleared"}], "steps": [{"from": 0, "to": 1, "label": "selectedOverlayKey = key", "c": "ink", "m": "addOverlay() OverlayManager.kt:535", "cap": "The user adds a video overlay. The new overlay is selected right away, before the engine has accepted it."}, {"from": 0, "to": 0, "label": "engine.addVideo() → −1", "c": "risk", "m": "OverlayManager.kt:551", "chips": ["result = −1 (failed)"], "cap": "The engine refuses the video and returns −1."}, {"from": 0, "to": 0, "label": "removeItem(key)", "c": "ink", "m": "OverlayManager.kt:556", "tag": {"col": 0, "text": "overlay removed from the list", "c": "ok"}, "cap": "The new error block removes the overlay from the list, but it does not touch the selection set in step 1."}, {"from": 2, "to": 1, "label": "tap Volume → read selection", "c": "ink", "m": "editor toolbar", "cap": "The user taps Volume. The toolbar asks which overlay is selected and gets the removed key."}, {"from": 1, "to": 2, "label": "findItemByKey(key) → null", "c": "bad", "ret": true, "m": "OverlayManager.kt:2418", "tag": {"col": 2, "text": "button does nothing, no error shown", "c": "bad"}, "cap": "The lookup finds nothing, so updateVolume() silently returns. The user taps and nothing happens."}]}, "fix": {"bars": [], "steps": [{"from": 0, "to": 1, "label": "selectedOverlayKey = null", "c": "ok", "m": "next to removeItem() :556", "cap": "In the same block that removes the failed overlay, also clear the selection."}, {"from": 2, "to": 1, "label": "tap Volume → read selection", "c": "ink", "cap": "The toolbar asks which overlay is selected."}, {"from": 1, "to": 2, "label": "null → nothing selected", "c": "ok", "ret": true, "tag": {"col": 2, "text": "toolbar hidden, no ghost selection", "c": "ok"}, "cap": "Nothing is selected, so the toolbar hides instead of acting on an overlay that is gone."}]}, "fixCode": {"file": "OverlayManager.kt", "line": 556, "diff": "      removeItem(key)\\n+     if (selectedOverlayKey == key) selectedOverlayKey = null", "note": "Clear the selection in the same block that removes the failed overlay."}}'   # from a sample PR that is not in any test, so no answer leaks
REPLAY_RULES = (
    "## How every replay must look (the reviewer reads these instead of the code)\n"
    "A replay is a STORY a developer understands by pressing Play once: who acts, what each call RETURNS, what each "
    "thread holds or waits for, the exact moment it goes wrong, and what the user gets. Be concrete, never vague.\n"
    "- Columns (3-4): the real actors: threads, the shared object/lock/queue they fight over, the component, the GPU. "
    "Give a shared object (a future, a lock, a cache, a list) its OWN column when the story is about who touches it. "
    "Column = [plain name, function or variable underneath].\n"
    "- 5-9 steps a mode. Step 1 starts from what the user or app does. ONE action per step. label = the real call as "
    "written in the code (\"isReady() && wait_for(0)\", \"lock(m) → busy, waits\"), max 44 chars. m = function :line plus "
    "the reason it runs (\"only when the cache is cold :412\").\n"
    "- Show return values: after a check whose answer matters, add a return step (ret=true, arrow back to the caller) "
    "whose label is the value (\"true · ready\"), or chips with the values (\"count = 0\").\n"
    "- State changes on a shared object get a tag on that object's column (\"cache now EMPTY · isValid() == false\").\n"
    "- Crash/exception steps: crash=true and crashText = exactly what fails (\"CRASH · pop() on an empty queue\"); "
    "the m says why the caller still did it (\"its check in step 2 is out of date\").\n"
    "- Locks and waits are bars (max 3 a mode): bar-hold on the lock's column (or the holder) from the step it is taken to "
    "the step it is released, text = \"held by <who> :<take> → :<release>\"; bar-wait on the thread that waits "
    "(text = \"<who> waits for <what>\", end = \"gets the lock\"); bar-risk for an unprotected window "
    "(\"checked at :X, used at :Y, no lock between\"). Show unlock / release as its own return step.\n"
    "- Pipelines/passes: number every pass (\"pass 1 · Blur\"), say what it reads and writes (chip \"frame A → B\"), show "
    "that the result feeds the next pass; when work is batched, show each item being COLLECTED (chip \"queued, not run\") and "
    "then the one step that applies them all (\"pass 3 · all queued items at once\"). End with a tag that counts "
    "(\"5 effects = 5 passes\", \"2 passes instead of 5\"). If the ORDER changes, say old order vs new order.\n"
    "- cap = 1-2 full plain sentences shown ABOVE the diagram: what happens in this step AND why it matters. Never a "
    "fragment like \"X runs right away\": write \"Blur is not batched, so it runs now as its own pass, before the "
    "batched effects are applied. Before this PR it ran after them.\" The last step's cap states the outcome for the user.\n"
    "- Tags (max 4 a mode, max 60 chars) mark: a missing guard (c=risk), a state change, the failure (c=bad) or the "
    "safe outcome (c=ok). Chips (max 2, short values).\n"
    "- Verified/Suspected with a clear fix: a fix mode (\"Suggested fix\") with the same columns, ok-coloured, AND "
    "\"fixCode\": {\"file\": path, \"line\": n, \"diff\": \"- old line\\n+ new line\", \"note\": one sentence} on the "
    "scenario: the smallest real change, 3-15 lines, using the exact names and lines in the code (lines starting with "
    "'- ' removed, '+ ' added, '  ' context). If the right fix is in the Kotlin app (the scenario's bad step is a "
    "Kotlin exit that forgets to sync), put the fix THERE: file = the Kotlin path from the Kotlin side, with real Kotlin "
    "names you opened. Check boundaries: for the last item or an exact end, does your comparison need <= or <? "
    "No fixCode when you are not sure of the fix.\n"
    "- Safe: KEEP IT SHORT: one mode (\"Why it holds\"), 3-4 steps, one-sentence captions, no bars; the guarding "
    "step c=ok with a tag.\n"
    "- The main flow follows the same rules: Before / With this PR, both modes complete enough to compare. In With "
    "this PR, a step that shows a problem one of the scenarios is about gets \"sc\": \"<that scenario id>\" and c=bad "
    "(risk if only suspected), with the problem in its tag (\"order changed: Blur now runs first\"). Never colour a "
    "problem ok. The main flow tells the PR's own story: at most 2 such side-issue steps, never the last step; the LAST "
    "step is what the PR is meant to achieve for the user (\"the new overlay shows at once, no blank frame\").\n"
    "- What the user gets (a crash, a frozen or wrong picture, a sound) is a step ON the lane where it appears (from == to: a mark "
    "there with the tag), never an arrow back to a caller that receives nothing.\n"
    "This is the target style (from another review; copy the style, never the content):\n```json\n" + REPLAY_EXAMPLE + "\n```\n\n")


ERROR_PATHS = (
    "## Error-path checklist (do every item for every NEW or CHANGED failure path in the diff)\n"
    "Include every timeout, try_lock failure, wait_for that returns not-ready and early return that the changed code "
    "now reaches, new or old: after it, what state does the code carry on with (a flag reset, a second worker started, "
    "an object freed while still in use)? And does the waiter itself hold a lock the awaited task needs (then the "
    "timeout is forced whenever the task is in that section; cite both lines)?\n"
    "Waits done while holding a lock (wait_for, get, join, a condition wait): follow the calls of the task being waited "
    "for at least two levels deep, with Read/Grep. If it needs that same lock anywhere, the wait times out because of the "
    "code, not because a device is slow: treat the timeout branch as a normal path and say which lock and which line.\n"
    "For each call that can fail (shader compile/link, allocation, file/codec open, glCheckFramebufferStatus, a JNI call, "
    "a lookup that can miss): 1) what happens on failure: is it only logged? 2) is any state still marked ready, valid, "
    "cached or done afterwards (a flag set to true, an id stored in a map, a cache entry kept)? 3) does it ever retry or "
    "recover, or does the broken state stay for the session? 4) what does the user see then? Any 'stored broken, no "
    "recovery' is a finding WITH its own scenario, even if the failure is rare.\n"
    "Also, for every change in ORDER (of passes, calls, events): find where the order comes from (defaults, slot tables, "
    "Kotlin) with Grep and say which concrete inputs change, with file:line.\n\n")


SEATS = [('bugs', 'Bugs, error paths, lifetime and threading', ['pr-review-general', 'pr-silent-failure', 'pr-lifetime']),
         ('flows', 'User flows: every way in and out of the changed code', ['pr-userflows']),
         ('rest', 'Performance, memory, ANR and design', ['pr-performance', 'pr-memory', 'pr-anr', 'pr-architecture', 'pr-simplify'])]


def _seats(diff):
    """Always 3 seats: bugs (Opus), user flows with every exit (Opus), everything else (Sonnet)."""
    return SEATS


FLOW_EXITS = (
    "## Exit checklist (do every item)\n"
    "For every flow in the Kotlin call sites above: Done/Apply, Cancel/Back (system back and the panel's cancel), leaving "
    "the screen (onDetach/onPause/switching tool), undo/redo after, play after. At each exit compare the engine state "
    "with the Kotlin state (cursor, time label, selection). A mismatch the user can see is a scenario.\n\n")


HUNT_FORMAT = (
    "\n\n## How to answer (overrides any other answer format)\n"
    "End with ONE ```json block: {\"summary\": \"\", \"findings\": [{\"severity\": \"blocker|major|minor|suggestion\", "
    "\"confidence\": 0, \"file\": \"path\", \"line\": 0, \"title\": \"\", \"problem\": \"\", \"fix\": \"\", "
    "\"evidence\": \"the code on that line, copied exactly\"}], \"scenarios\": [{\"title\": \"what if ...\", \"q\": \"the question\", "
    "\"claim\": \"verified|suspected|safe\", \"kind\": \"always|timing|condition\", \"finding\": index in YOUR findings or null, "
    "\"why\": [[\"bad|ok|risk|plain\", \"label\", \"text\"]], \"proof\": [{\"file\": \"\", \"line\": 0, \"code\": \"copied exactly\", "
    "\"text\": \"what this step shows\"}, {\"text\": \"a step that is not code\"}], \"pre_existing\": false, \"repro\": {\"setup\": \"\", \"steps\": [\"\"], "
    "\"expected\": \"\", \"actual\": \"\"}}]}\n"
    "repro is for QA, who test by hand in the app and do not read code or logs: setup = the project to start from "
    "(\"a project with 3 video clips on the main track\"), steps = 3-7 numbered user actions in the app's words (tap, "
    "select, drag, undo; never function names), expected = what should happen, actual = what this PR makes happen (for a "
    "safe scenario: the same as expected, it is a check). If a user cannot trigger it directly (a GPU failure, a race), "
    "give the closest steps and say so in setup (\"rare: may need many tries\" / \"needs a device where ... \").\n"
    "Every finding whose outcome users can see or feel (the picture or sound changes, a crash, a freeze, data loss, a leak "
    "that grows) ALSO gets its own scenario with finding = its index; never fold two different outcomes into one finding. "
    "Every finding and every proof step that cites a line must quote that line's code exactly: a script checks each one "
    "and DROPS what does not match. A scenario is a concrete \"what if\" with the chain from a user action or thread to "
    "the outcome. claim: verified = the code forces it; suspected = possible, not provable from code; safe = you checked "
    "it holds; a GOOD outcome (fewer passes, a bug that is now fixed) is safe, never verified. kind: always = every time this "
    "path runs; timing = only with a certain thread interleaving (never say always for a race); condition = only if "
    "something else happens first (a compile fails, a file is missing): say what in why. Speed, memory, battery and image effects are unmeasured: say so, do not claim them. "
    "CALLERS: the change map lists every caller of each changed function (draft restore, undo, looper messages, export). "
    "For each caller in a different state than the one the PR is about (another playhead, playing, restoring a draft), "
    "check what the new code does there; a different outcome is its own scenario.")


def review_one(cfg, pr, crashes, log, notes=None, early=None, prev=None):
    """notes: past reviewer answers (feedback). early: callback(partial rec) for the early look on the board.
    prev: the last saved review of this PR (out/pr/<id>.json), for a re-review of only the new commits.
    Flow: change map (Sonnet) -> hunters return findings + scenarios with proof -> merge -> replays -> line check (no AI)
    -> early look -> 2 judges on scenarios and unlinked findings -> tiers -> description check -> chair -> verdict (code)."""
    t0 = dt.datetime.now()
    st = Stages(t0)
    st.start('Intake', 'no AI')
    wt, mb = checkout(pr, log)
    diff = pr.get('diff') or _git(['diff', f'{mb}..{pr["head"]}'], cwd=pr.get('_gitdir')).stdout
    files = re.findall(r'^diff --git a/(\S+)', diff, re.M)
    stat = _git(['diff', '--stat', f'{mb}..{pr["head"]}'], cwd=pr.get('_gitdir')).stdout[-3000:]
    head = (f"# Pull request #{pr.get('num', pr['id'])}{' in repo ' + pr['repo'] if pr.get('repo') and str(pr.get('num')) != str(pr['id']) else ''}: {pr.get('title','')}\nAuthor: {pr.get('author','')}\n"
            f"Branch: {pr.get('source','')} -> {pr.get('dest','')}\nHead: {pr['head'][:12]}  merge-base: {mb[:12]}\n\n")
    rest = ("## Commits\n"
            + '\n'.join(f"- {c['hash'][:10]} {c['message'].splitlines()[0] if c['message'] else ''}" for c in pr.get('commits') or [])
            + f"\n\n## Files changed\n```\n{stat}\n```\n")
    desc = (pr.get('description') or '').strip()
    # Blind first: everything before the description check sees only the code, never the author's description.
    meta = head + "## Description\n(withheld: blind review, judge the code only)\n\n" + rest
    meta_full = head + f"## Description\n{desc or '(none)'}\n\n" + rest
    dtext = f"## Diff\n```diff\n{diff[:60000]}\n```\n" + ('(diff truncated: read the files for the rest)\n' if len(diff) > 60000 else '')
    tag = f"pr{pr['id']}.{pr['head'][:8]}"
    fbtext = ('## What reviewers answered on earlier findings (weigh it; the code decides)\n```json\n'
              + json.dumps(notes, indent=0)[:6000] + '\n```\n\n') if notes else ''
    st.end(f"{len(files)} file(s); description {'locked away' if desc else 'none'}")
    inc = _incremental(pr, prev, files, log)
    if inc is not None and not inc['changed']:          # new commits, but none touches this PR's files
        return _carry(prev, pr, mb, files, wt, diff, desc, inc, st, t0, log)
    focus = ''
    if inc is not None:
        focus = (f"## Re-review: only the new commits\nThe PR was reviewed at {inc['old'][:10]}. Review ONLY what changed since "
                 f"then: `git diff {inc['old'][:12]} {pr['head'][:12]}` (files: {', '.join(inc['changed'][:20])}). "
                 "Do not repeat earlier findings:\n" + '\n'.join('- ' + str(f.get('title', ''))[:120] for f in (prev.get('findings') or [])[:30])
                 + '\n\n')

    st.start('Classify', 'Opus')
    cls = _json(_call('pr-classify', meta + dtext[:25000] + '\n## Crashes and ANRs on the Night Shift board\n```json\n'
                      + json.dumps(crashes, indent=0)[:12000] + '\n```\n', cfg, tag + '.classify', wt, tools='', timeout=600, meter=st))
    log(f"PR #{pr['id']}: {cls.get('type','?')} ({cls.get('confidence','?')}%) - {str(cls.get('reason',''))[:120]}")
    st.end(f"{cls.get('type', '?')} ({cls.get('confidence', '?')}%)")

    ktext, klabel = '', ''
    if (cfg.get('pr_review') or {}).get('kotlin', True):   # the app's Kotlin repos: who calls this native code
        st.start('Kotlin context', 'no AI')
        try:
            linked = []                              # 23 Oct: Kotlin PRs this one ships with (links in the description;
            try:                                     # only the link is used, the text stays hidden from the reviewers)
                from . import bitbucket
                prof = config.profile(cfg)
                for repo, num in kotlinctx.linked_prs(desc, [r for r in prof['repos'] if r != (pr.get('repo') or prof['main_repo'])]).items():
                    try:
                        lp = bitbucket.get_pr(num, repo=repo, main=prof['main_repo'])
                        linked.append(kotlinctx.checkout_linked(repo, lp, log))
                        log(f"PR #{pr['id']}: reviewed against {repo} PR #{num} ({lp.get('source')}@{lp.get('head', '')[:7]}), linked in the description")
                    except Exception as e:
                        log(f"PR #{pr['id']}: linked {repo} PR #{num} not usable ({str(e)[:140]}); the sprint copy is used")
            except Exception as e:
                log(f"PR #{pr['id']}: linked PRs skipped ({str(e)[:120]})")
            ktext, kdirs, klabel, kres = kotlinctx.context(cfg, diff, None, log, linked=linked)
            try:                                     # JNI table vs Kotlin declarations, head against base (no AI)
                jf = 'app/src/main/cpp/JNI/JNI.cpp'
                if jf in files and kdirs:
                    jt, jp, jres = kotlinctx.jni_check(_git(['show', f"{pr['head']}:{jf}"], cwd=pr.get('_gitdir')).stdout,
                                                       _git(['show', f"{mb}:{jf}"], cwd=pr.get('_gitdir')).stdout, kdirs, klabel)
                    ktext = jt + ktext
                    kres = f"{kres} · {jres}"
                    log(f"PR #{pr['id']}: {jres}" + (''.join('\n    ' + x for x in jp[:6]) if jp else ''))
            except Exception as e:
                log(f"PR #{pr['id']}: JNI table check skipped ({str(e)[:120]})")
            if kdirs:
                cfg = dict(cfg, _add_dirs=kdirs)     # every model call below may Read/Grep the Kotlin copies too
                prvisual.EXTRA_ROOTS[:] = kdirs       # and Kotlin file:line refs pass the code-path check and judge evidence
        except Exception as e:
            kres = f'skipped ({str(e)[:120]})'
        st.end(kres)

    st.start('Change map', 'Sonnet')                 # callers, threads, shared state, entry points: given to every hunter
    cmap = _json(_call('pr-changemap', meta + focus + ktext + dtext, cfg, tag + '.changemap', wt, tools='Read,Grep,Glob', timeout=900,
                       meter=st, model=(cfg.get('llm') or {}).get('model_map') or 'sonnet'))
    cmtext = (('## Change map (facts: callers, threads, shared state, entry points)\n```json\n' + json.dumps(cmap, indent=0)[:20000]
               + '\n```\n\n') if cmap else '') + ktext
    st.end(f"{len(cmap.get('functions') or [])} changed function(s) · {len(cmap.get('paths') or [])} user path(s)" if cmap else 'no answer')

    pack = prvisual.code_pack(wt, diff, cmap)
    # Common part first and identical for every seat (the CLI caches it); the seat's own guides come last.
    common = (meta + f"## Classification\n{json.dumps(cls)}\n\n" + cmtext
              + (f"## The code you need (read once for you from the PR head; line numbers are real)\n```\n{pack}\n```\n\n" if pack else '')
              + focus + fbtext + dtext)
    if str(cls.get('type') or '') in ('crash_fix', 'anr_fix'):   # a crash/ANR fix is judged on whether the path is now safe
        common += ("## Scope for this crash/ANR fix\n"
                   "A problem on the same lock, future, queue or thread path that the diff changes is IN SCOPE even if it "
                   "existed before, when it can still cause a crash, a hang or a corrupt state. Report it as a scenario with "
                   "\"pre_existing\": true. Problems elsewhere that existed before stay out of scope.\n\n")
    seats = _seats(diff)
    res, hunted = {}, []
    hmodel = (cfg.get('llm') or {}).get('model_hunt') or 'sonnet'
    bmodel = (cfg.get('llm') or {}).get('model_hunt_bugs') or 'opus'     # bugs / error paths / lifetime: the subtle ones
    smodel = lambda key: bmodel if key in ('bugs', 'flows') else hmodel   # the two seats that find behaviour bugs: Opus
    who = ' + '.join(sorted({smodel(k).capitalize() for k, _, _ in seats}))
    st.start(f"Hunt ({len(seats)} seats: " + ', '.join(f"{k} {smodel(k)}" for k, _, _ in seats) + ")" if inc is None
             else f"Hunt: new commits only ({len(seats)} seats)", who, '' if inc is None else 'rerun')

    def seat(se):
        key, name, guides = se
        check = ERROR_PATHS if key == 'bugs' else FLOW_EXITS if key == 'flows' else ''
        txt = _call('', common + f"\n\n# Your seat: {name}\n{check}The PR's changes are the uncommitted changes in this working folder; "
                    "the diff and the code above are usually enough. Open other files (Read, Grep) only to check a caller, a thread "
                    "or a lifetime the code above does not show.\n\n" + '\n\n'.join(llm.skill_text(g) for g in guides) + HUNT_FORMAT,
                    cfg, f"{tag}.seat-{key}", wt, tools='Read,Grep,Glob', timeout=1500, meter=st, model=smodel(key))
        return key, name, guides, txt
    with ThreadPoolExecutor(len(seats)) as ex:
        for key, cat, guides, txt in ex.map(seat, seats):
            a_ = _json(txt)
            fs = [x for x in (a_.get('findings') or []) if isinstance(x, dict) and (x.get('confidence') or 0) >= 60]
            for x in fs:
                x['category'] = cat
            scs = [x for x in (a_.get('scenarios') or []) if isinstance(x, dict) and x.get('title')]
            for k, x in enumerate(scs):
                x['id'], x['from'] = f"{key}-{k + 1}", [cat]
            hunted += scs
            res[cat] = {'summary': str(a_.get('summary') or '')[:900], 'findings': fs, 'scenarios': scs, 'skill': '+'.join(guides),
                        'plugin': 'nightshift skills (' + ', '.join(guides) + ')', 'skill_used': bool(txt), 'answered': bool((txt or '').strip())}
    pc = cfg.get('pr_review') or {}
    if prev and prev.get('head') == pr['head'] and pc.get('carry_forward', True) and not pc.get('_no_carry'):
        old_sc = []                                  # same code reviewed again: earlier problems are re-judged, never just lost
        for x in (prev.get('view') or {}).get('scenarios') or []:
            if x.get('verdict') not in ('verified', 'suspected'):
                continue
            pf = []
            for stp in (x.get('proof') or {}).get('steps') or []:
                ref = stp[0] if stp and isinstance(stp[0], str) and ':' in stp[0] else ''
                pf.append({'file': ref.rsplit(':', 1)[0], 'line': int(ref.rsplit(':', 1)[1]) if ref.rsplit(':', 1)[-1].isdigit() else 0,
                           'code': stp[3] if len(stp) > 3 else '', 'text': stp[1] if len(stp) > 1 else ''} if ref else {'text': stp[1] if len(stp) > 1 else ''})
            old_sc.append({'id': f"prev-{len(old_sc) + 1}", 'title': x.get('title'), 'q': x.get('q'), 'claim': x.get('verdict'),
                           'kind': x.get('kind'), 'why': x.get('why'), 'proof': pf, 'repro': x.get('repro'), 'from': ['previous review']})
        if old_sc:
            res['previous review of this same code'] = {'summary': 'Scenarios a previous run found; keep each unless the code shows otherwise',
                                                        'findings': [], 'scenarios': old_sc, 'skill': '', 'plugin': '', 'skill_used': False, 'answered': True}
            hunted += old_sc
            log(f"PR #{pr['id']}: {len(old_sc)} scenario(s) from the previous run go back to the judges")
    allf = [f for v in res.values() for f in v['findings']]
    st.end(f"{len(allf)} finding(s) and {len(hunted)} scenario(s) from {sum(1 for v in res.values() if v['answered'])} hunter(s)")

    st.start('Merge', 'Opus')
    syn = _json(_call('pr-synthesis', meta + f"## Classification\n{json.dumps(cls)}\n\n## What the hunters returned\n```json\n"
                      + json.dumps({k: {'findings': v['findings'], 'scenarios': v['scenarios']} for k, v in res.items()}, indent=1)[:70000]
                      + '\n```\n', cfg, tag + '.synthesis', wt, timeout=900, meter=st))
    findings = [f for f in (syn.get('findings') or []) if isinstance(f, dict)] or sorted(allf, key=lambda f: (
        ['blocker', 'major', 'minor', 'suggestion'].index(f.get('severity')) if f.get('severity') in ['blocker', 'major', 'minor', 'suggestion'] else 9,
        -(f.get('confidence') or 0)))
    given = [x for x in (syn.get('scenarios') or []) if isinstance(x, dict) and x.get('title')]
    if not given and hunted:                         # merge failed: keep the hunters' own scenarios, unlinked
        given = [dict(x, finding=None) for x in hunted]
    for k, x in enumerate(given):
        x['id'] = str(x.get('id') or f's{k + 1}')
    crashfix = str(cls.get('type') or '') in ('crash_fix', 'anr_fix')
    refs = lambda x: {f"{q.get('file')}:{q.get('line')}" for q in x.get('proof') or [] if isinstance(q, dict) and q.get('file') and q.get('line')}
    pre_refs = [refs(h) for h in hunted if h.get('pre_existing')] if crashfix else []
    for x in given:
        if not crashfix:
            x.pop('pre_existing', None)               # the "existed before, still open" scope is for crash/ANR fixes only
        elif not x.get('pre_existing') and pre_refs:  # the merge dropped a hunter's flag: restore it by the shared proof lines
            r = refs(x)
            if r and any(len(r & q) >= min(2, len(r), len(q)) for q in pre_refs):
                x['pre_existing'] = True
    st.end(f"{len(findings)} finding(s) · {len(given)} scenario(s)")
    if inc is not None:                              # earlier findings first; new ones after; remap the new scenarios
        old_f = list(prev.get('findings') or [])
        idx = {f.get('title'): i for i, f in enumerate(old_f)}
        remap = {}
        for j, f in enumerate(findings):
            if f.get('title') in idx:
                remap[j] = idx[f['title']]
            else:
                remap[j] = len(old_f)
                old_f.append(f)
        findings = old_f
        for x in given:
            x['finding'] = remap.get(x.get('finding')) if isinstance(x.get('finding'), int) else None

    view, code, claims = None, None, None
    try:                                             # scenarios as the hunters wrote them; replays are drawn after the judges
        view, code = prvisual.build({}, wt, diff, findings[:60], given=given)
    except Exception as e:
        log(f"PR #{pr['id']}: scenarios could not be built ({str(e)[:160]})")
    if view is not None and inc is not None:
        view = _merge_prev(prev, view, inc)

    names = _judge_names(cls)
    if view is not None:
        st.start('Code-path check', 'no AI')
        nd = len(view.get('dropped') or [])
        n = prvisual.pathcheck(view, wt, diff, why_prefix='' if inc is None else 'After the new commits: ')
        need = prvisual.check_findings(findings, view, wt, diff)
        unchecked = sum(1 for f in findings if f.get('tier') == 'unchecked')
        st.end(f"{n} scenario line(s) + {len(need)} finding line(s) matched · {len(view.get('dropped') or []) - nd} dropped "
               f"(line did not match) · {unchecked} finding(s) unchecked (no quoted line)")
        if early:                                     # early look: scenarios on the board before the judges
            try:
                st.mark('Early look', 'board', f"{len(view.get('scenarios') or [])} scenario(s) shown, not judged yet", 'early')
                early({'id': str(pr['id']), 'head': pr['head'], 'stage': 'reviewing', 'early': True, 'view': view, 'code': code,
                       'findings': findings[:60], 'title': pr.get('title', ''), 'type': cls.get('type', 'unknown'), 'stages': st.rows})
            except Exception as e:
                log(f"PR #{pr['id']}: early look not saved ({str(e)[:100]})")
        todo = [x for x in view.get('scenarios') or [] if not (x.get('proof') or {}).get('judged')]
        items = [{'id': x['id'], 'kind_of_item': 'scenario', 'title': x.get('title'), 'q': x.get('q'), 'claim': x.get('verdict'),
                  'hunter_severity': (findings[x['finding']].get('severity') if isinstance(x.get('finding'), int) and x['finding'] < len(findings) else None),
                  'kind': x.get('kind', ''), 'why': x.get('why'), 'pre_existing': bool(x.get('pre_existing')),
                  'proof': [{'line': q[0], 'text': q[1]} for q in (x.get('proof') or {}).get('steps') or []]} for x in todo]
        items += [{'id': 'f%d' % i, 'kind_of_item': 'finding', 'title': findings[i].get('title'), 'claim': 'suspected',
                   'severity': findings[i].get('severity'), 'problem': findings[i].get('problem'),
                   'proof': [{'line': findings[i].get('check'), 'text': findings[i].get('evidence')}]} for i in need]
        st.start(f"Challenge ({len(names)} judges)", 'Opus')
        votes = {}
        if items:
            def judge(name):
                role = ("Try hard to refute each item; confirm only what the code forces.\n\n" if name == 'Skeptic'
                        else f"Judge as a {name.replace(' judge', '').lower()} expert.\n\n")
                txt = _call('pr-judge', f"# Your role: {name}\n{role}" + meta + f"## Classification\n{json.dumps(cls)}\n\n" + cmtext + fbtext
                            + "## Items (unsigned)\n```json\n" + json.dumps(items, indent=1)[:50000] + '\n```\n\n' + dtext,
                            cfg, f"{tag}.judge-{name.split()[0].lower()}", wt, tools='Read,Grep,Glob', timeout=1500, meter=st)
                return name, {v.get('id'): v for v in (_json(txt).get('votes') or []) if isinstance(v, dict)}
            with ThreadPoolExecutor(len(names)) as ex:
                for name, v in ex.map(judge, names):
                    if v:
                        votes[name] = v
        before = {x['id'] for x in view.get('scenarios') or []}
        judged = [n for n in names if n in votes]
        prvisual.tiers(view, votes, judged, wt, diff, findings)
        prvisual.finding_tiers(findings, view, votes, judged, wt, diff)
        sc = view.get('scenarios') or []
        ft = [f.get('tier') for f in findings]
        st.end(f"scenarios: {sum(1 for x in sc if x['verdict'] == 'verified')} verified · {sum(1 for x in sc if x['verdict'] == 'suspected')} suspected · "
               f"{sum(1 for x in sc if x['verdict'] == 'safe')} safe · {len(before - {x['id'] for x in sc})} dropped; findings: "
               f"{ft.count('verified')} verified · {ft.count('suspected')} suspected · {ft.count('unchecked')} unchecked · {ft.count('dropped')} dropped"
               + ('' if votes or not items else ' (the judges did not answer)'))
        keep = list(view.get('scenarios') or [])   # every surviving scenario gets a drawn replay (Safe ones too)
        st.start('Replays + page', (cfg.get('llm') or {}).get('model_visual', 'opus').capitalize())
        try:                                         # replays for Verified/Suspected only; Safe ones keep their proof chain
            vis = _json(_call('pr-visual', meta + f"## Classification\n{json.dumps(cls)}\n\n" + cmtext + focus
                              + REPLAY_RULES + "## Scenarios (give each one a replay; do not change them)\n```json\n"
                              + json.dumps([{'id': x['id'], 'title': x.get('title'), 'q': x.get('q'), 'tier': x.get('verdict'), 'kind': x.get('kind'),
                                             'why': x.get('why'), 'proof': [{'line': q[0], 'text': q[1]} for q in (x.get('proof') or {}).get('steps') or []]}
                                            for x in keep], indent=1)[:30000]
                              + "\n```\n\n## Merged findings (0-based index)\n```json\n" + json.dumps(
                                  [{'i': i, 'title': f.get('title'), 'file': f.get('file'), 'line': f.get('line'), 'tier': f.get('tier')}
                                   for i, f in enumerate(findings[:40])], indent=1)[:20000] + '\n```\n\n' + dtext,
                              cfg, tag + '.visual', wt, tools='Read,Grep,Glob', timeout=1500, meter=st,
                              model=(cfg.get('llm') or {}).get('model_visual') or 'opus'))
            dropped = view.get('dropped') or []
            view2, code2 = prvisual.build(vis or {}, wt, diff, findings[:60], given=view.get('scenarios') or [])
            view2['dropped'] = dropped
            view, code = view2, code2 or code
        except Exception as e:
            log(f"PR #{pr['id']}: replays failed ({str(e)[:160]}); scenarios keep their proof chain as the replay")
        st.end(f"{len(keep)} replay(s) drawn")
    else:                                             # nothing could be built: nothing is checked, so nothing can block
        for f in findings:
            f['tier'] = 'unchecked'
        log(f"PR #{pr['id']}: no scenarios could be built: every finding is unchecked")

    if desc and view:                                # now read the description and check each claim against the code
        try:
            blind = {'tldr': view.get('tldr'), 'scenarios': [{'id': x['id'], 'title': x['title'], 'verdict': x['verdict']}
                                                             for x in view.get('scenarios') or []],
                     'findings': [{'title': f.get('title'), 'file': f.get('file'), 'line': f.get('line'), 'tier': f.get('tier')}
                                  for f in findings[:30] if not f.get('dropped')]}
            st.start('Description check', 'Opus')
            claims = _json(_call('pr-claims', meta_full + ktext + "## Blind review\n```json\n" + json.dumps(blind, indent=1) + '\n```\n\n'
                                 + dtext, cfg, tag + '.claims', wt, tools='Read,Grep,Glob', timeout=900, meter=st)) or None
            st.end(f"{len((claims or {}).get('claims') or [])} claim(s)")
            if claims:
                cl = claims.get('claims') or []
                log(f"PR #{pr['id']}: description checked: {len(cl)} claim(s), "
                    f"{sum(1 for c in cl if c.get('verdict') not in ('ok', 'unmeasured'))} not fully true, "
                    f"{sum(1 for c in cl if c.get('verdict') == 'unmeasured')} unmeasured")
        except Exception as e:
            log(f"PR #{pr['id']}: description check failed ({str(e)[:160]})")
    elif not desc:
        log(f"PR #{pr['id']}: no description: code-only review")

    # Verdict is code, not a model: only a Verified finding or scenario can block.
    live_f = [f for f in findings if not f.get('dropped')]
    tiers_now = [x.get('verdict') for x in (view or {}).get('scenarios') or []] + [f.get('tier') for f in live_f]
    # Only a Verified major/blocker counts: a true but minor point ("unused member") never forces "changes".
    heavy = [f for i, f in enumerate(live_f) if f.get('tier') == 'verified' and f.get('severity') in ('blocker', 'major')]
    if any(f.get('severity') == 'blocker' and not f.get('pre_existing') for f in heavy):   # an old problem never blocks: changes
        verdict = 'blocking'
    elif heavy or any(x.get('verdict') == 'verified' and x.get('severity') in ('blocker', 'major')   # linked or not
                      for x in (view or {}).get('scenarios') or []):
        verdict = 'changes'
    else:
        verdict = 'approve'
    st.start('Chair', 'Opus')                        # summary + line comments from the final tiers; cannot change them
    chair = _json(_call('pr-chair', meta + f"## Classification\n{json.dumps(cls)}\n\n## Verdict (set by code)\n{verdict}\n\n"
                        + "## Checked results\n```json\n" + json.dumps({
                            'scenarios': [{'id': x['id'], 'title': x.get('title'), 'tier': x.get('verdict'), 'kind': x.get('kind', ''),
                                           'finding': x.get('finding'), 'why': x.get('why')} for x in (view or {}).get('scenarios') or []],
                            'findings': [{'index': i, 'tier': f.get('tier'), 'severity': f.get('severity'), 'title': f.get('title'),
                                          'file': f.get('file'), 'line': f.get('line'), 'problem': f.get('problem'), 'fix': f.get('fix')}
                                         for i, f in enumerate(findings[:40]) if not f.get('dropped')],
                            'description_check': (claims or {}).get('verdict_line', '')}, indent=1)[:40000] + '\n```\n',
                        cfg, tag + '.chair', wt, tools='', timeout=600, meter=st))
    st.end(f"verdict {verdict} (set by code)")
    st.end()
    if view is not None and chair.get('comments'):  # the chair's comments go on the Decide page
        cm = {c.get('finding'): str(c.get('comment') or '') for c in chair.get('comments') or [] if isinstance(c, dict)}
        for l in view.get('finding_links') or []:
            if cm.get(l.get('finding')):
                l['comment'] = cm[l['finding']]
        have = {l.get('finding') for l in view.get('finding_links') or []}
        for k, c in cm.items():
            if isinstance(k, int) and k not in have and c:
                view.setdefault('finding_links', []).append({'finding': k, 'scenario': None, 'hunk': None, 'comment': c})
    since = ''
    if inc is not None:
        since = (f"{len(inc['commits'])} new commit(s) since the review at {inc['old'][:10]}: only their changes were re-reviewed "
                 f"({', '.join(x.split('/')[-1] for x in inc['changed'][:6])}).")
    stages = ((prev or {}).get('stages') or []) + st.rows if inc is not None else st.rows
    sev = [f.get('severity') for f in live_f]
    mins = round((dt.datetime.now() - t0).total_seconds() / 60, 1)
    rec = {'id': str(pr['id']), 'repo': pr.get('repo', ''), 'num': str(pr.get('num', pr['id'])),
           'title': pr.get('title', ''), 'author': pr.get('author', ''), 'url': pr.get('url', ''),
           'source': pr.get('source', ''), 'dest': pr.get('dest', ''), 'head': pr['head'], 'mergeBase': mb,
           'files': files[:200], 'nFiles': len(files), 'type': cls.get('type', 'unknown'), 'typeConfidence': cls.get('confidence'),
           'typeReason': cls.get('reason', ''), 'jira': cls.get('jira', ''), 'linkedIssue': cls.get('linked_issue', ''),
           'risk': cls.get('risk', ''), 'areas': cls.get('areas') or [], 'verdict': verdict,
           'headline': chair.get('headline') or syn.get('headline', ''), 'summary': chair.get('summary') or syn.get('summary', ''),
           'fixComplete': ('partial' if any(x.get('verdict') == 'verified' and x.get('pre_existing') and x.get('severity') in ('blocker', 'major')
                                            for x in (view or {}).get('scenarios') or [])
                           else chair.get('fix_complete') or syn.get('fix_complete', 'n/a')),
           'good': chair.get('good') or syn.get('good') or [], 'findings': findings[:60],
           'counts': {s_: sev.count(s_) for s_ in ('blocker', 'major', 'minor', 'suggestion')},
           'tiers': {t_: [f.get('tier') for f in findings].count(t_) for t_ in ('verified', 'suspected', 'unchecked', 'dropped')},
           'byCategory': {k: len(v['findings']) for k, v in res.items()},
           'plugins': ['pr-review-toolkit@claude-code-plugins', 'nightshift-review@nightshift'],
           'skills': [{'name': v['skill'], 'plugin': v['plugin'], 'area': k, 'used': v['skill_used'], 'answered': v['answered'],
                       'summary': v['summary'], 'findings': v['findings'][:20], 'scenarios': len(v['scenarios'])} for k, v in res.items()],
           'reviewedAt': dt.datetime.now().isoformat(timespec='seconds'), 'minutes': mins, 'model': _model(cfg), 'stage': 'reviewed',
           'view': view, 'claims': claims, 'code': code, 'description': desc[:6000], 'blind': True, 'changeMap': bool(cmap),
           'stages': stages, 'since': since, 'early': False,
           'usage': {'tokens': st.total['tokens'], 'cost_usd': round(st.total['cost_usd'], 2), 'calls': st.total['calls']},
           'kotlin': klabel,
           'how': f"blind first · {'Kotlin side · ' if klabel else ''}change map · hunters · code-path check · judges · description last · chair · {round(mins)} min"
                  + (f" · {round(st.total['tokens'] / 1000)}k tokens" if st.total['tokens'] else '')
                  + (f" · ${st.total['cost_usd']:.2f}" if st.total['cost_usd'] else ''),
           'added': bool(pr.get('added')), 'draft': bool(pr.get('draft')), 'state': pr.get('state', ''),
           'commits': [{'hash': c['hash'][:10], 'message': (c.get('message') or '').splitlines()[0][:160] if c.get('message') else ''}
                       for c in pr.get('commits') or []][:30]}
    os.makedirs(OUT, exist_ok=True)
    json.dump(rec, open(os.path.join(OUT, f"{pr['id']}.json"), 'w'), indent=1)
    log(f"PR #{pr['id']}: {verdict} - {len(live_f)} finding(s): {rec['tiers']['verified']} verified, {rec['tiers']['suspected']} suspected, "
        f"{rec['tiers']['unchecked']} unchecked, {rec['tiers']['dropped']} dropped · {mins} min"
        + (f" · {round(st.total['tokens'] / 1000)}k tokens · ${st.total['cost_usd']:.2f}" if st.total['tokens'] else ''))
    return rec


class _Meter:
    def __init__(self):
        self.cost, self.tok = 0.0, 0

    def add(self, u):
        self.cost += float((u or {}).get('cost_usd') or 0)
        self.tok += sum(int((u or {}).get(k) or 0) for k in Stages.KEYS)


def redraw(db, cfg, arg, log=print):
    """Redraw ONE diagram of a saved review: the main flow or one scenario, with the developer's note on what was unclear.
    arg = '<pr id>|<flow or scenario id>|<note>'. Only that diagram (and its suggested-fix code) changes; findings,
    tiers, severities and the verdict stay exactly as reviewed. The old diagram is kept in out/pr/<id>.redraw-*.json."""
    pid, target, note = (str(arg).split('|', 2) + ['', ''])[:3]
    pid, target, note = pid.strip(), target.strip(), note.strip()[:700]
    path = os.path.join(OUT, f'{pid}.json')
    if not re.fullmatch(r'\d{1,6}', pid) or not os.path.exists(path):
        raise RuntimeError(f'redraw: no saved review for PR #{pid}')
    rec = json.load(open(path))
    view = rec.get('view') or {}
    scs = view.get('scenarios') or []
    sc = next((x for x in scs if x.get('id') == target), None)
    cur = view.get('flow') if target == 'flow' else sc
    if not cur:
        raise RuntimeError(f'redraw: PR #{pid} has no diagram "{target}"')
    log(f"PR #{pid}: redrawing {'the main flow' if target == 'flow' else 'scenario ' + target}"
        + (f' · developer note: {note[:160]}' if note else ' (no note)'))
    rp = {'id': pid, 'head': rec['head'], 'local': True, 'repo': rec.get('repo') or ''}
    wt, mb = checkout(rp, log)
    diff = _git(['diff', f'{mb}..{rec["head"]}'], cwd=rp.get('_gitdir')).stdout
    dtext = f"## Diff\n```diff\n{diff[:60000]}\n```\n" + ('(diff truncated: read the files for the rest)\n' if len(diff) > 60000 else '')
    old = {k: cur.get(k) for k in ('cols', 'modes', 'bug', 'fix', 'fixCode') if cur.get(k) is not None}
    safe = sc is not None and sc.get('verdict') == 'safe'
    if sc is None:
        what = ("the MAIN FLOW: Before / With this PR. In With this PR, a step that shows one of the scenarios' problems "
                "gets \"sc\" and c=bad (risk if suspected).\n### Scenarios on this PR\n```json\n"
                + json.dumps([{'id': x['id'], 'title': x.get('title'), 'tier': x.get('verdict')} for x in scs], indent=1) + '\n```\n')
    else:
        what = ("ONE SCENARIO's replay. Its facts are fixed (tier, why, proof, judges): do not change them, explain them better.\n"
                "### The scenario\n```json\n" + json.dumps(dict({k: sc.get(k) for k in ('id', 'title', 'q', 'verdict', 'kind', 'severity', 'why')},
                                                              proof=(sc.get('proof') or {}).get('steps')), indent=1)[:12000] + '\n```\n')
    shape = ('{"cols": [...], "modes": {"bug": "...", "fix": "..."}, "bug": {"bars": [...], "steps": [...]}, "fix": {...}'
             + ('' if sc is None or safe else ', "fixCode": {"file", "line", "diff", "note"}') + '}')
    prompt = (f"# Pull request #{pid}: {rec.get('title', '')}\nAuthor: {rec.get('author', '')}\n"
              f"Branch: {rec.get('source', '')} -> {rec.get('dest', '')}\nHead: {str(rec['head'])[:12]}\n\n"
              + REPLAY_RULES + "## Your job: redraw " + what
              + "\n### The current diagram (a developer did not understand it)\n```json\n" + json.dumps(old, ensure_ascii=False)[:20000] + '\n```\n'
              + (f"### What the developer says was unclear (answer exactly this)\n{note}\n\n" if note else
                 "### The developer gave no note: make it clearer, more concrete and easier to follow.\n\n")
              + "Read the code (Read, Grep) and get every function, value and line right. Keep the same story and facts; "
              "change how it is told: better steps, return values, locks, passes, captions.\n\n" + dtext
              + f"\nAnswer with ONE ```json block: {shape}\n")
    m = _Meter()
    ans = _json(_call('', prompt, cfg, f"pr{pid}.{str(rec['head'])[:8]}.redraw-{target}", wt, tools='Read,Grep,Glob',
                      timeout=900, meter=m, model=(cfg.get('llm') or {}).get('model_visual') or 'opus'))
    src = prvisual.Src(wt, prvisual.parse_diff(diff))
    hids = {h.get('id') for h in view.get('hunks') or [] if isinstance(h, dict)}
    modes = ({'bug': 'Before', 'fix': 'With this PR'} if sc is None else
             {'bug': 'Why it holds', 'fix': 'Suggested fix'} if safe else {'bug': 'This PR', 'fix': 'Suggested fix'})
    r = prvisual._replay(src, ans, hids, modes) if isinstance(ans, dict) else None
    if not r:
        raise RuntimeError(f'redraw: the model gave no usable diagram (${m.cost:.2f}); the old one stays')
    for k in ('cols', 'modes', 'bug', 'fix'):
        cur.pop(k, None)
    cur.update(r)
    if sc is not None and not safe:
        fc = prvisual._fix_code(ans.get('fixCode'))
        if fc:
            cur['fixCode'] = fc
    prvisual.link_sc(view.get('flow') or {}, scs)
    now = dt.datetime.now().isoformat(timespec='seconds')
    with open(os.path.join(OUT, f"{pid}.redraw-{target}-{now.replace(':', '')}.json"), 'w') as fh:
        json.dump({'target': target, 'note': note, 'old': old}, fh, ensure_ascii=False, indent=1)
    rec['view'] = view
    rec['redrawAt'] = now
    rec['redraws'] = (rec.get('redraws') or [])[-19:] + [{'target': target, 'note': note[:200], 'at': now, 'cost': round(m.cost, 3)}]
    with open(path, 'w') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
    if db is not None:
        db.collection('prs').document(pid).update({'viewJson': json.dumps(view, ensure_ascii=False), 'redrawAt': now,
                                                   'redraws': rec['redraws'], 'redrawTarget': target})
    log(f"PR #{pid}: {'main flow' if target == 'flow' else 'scenario ' + target} redrawn · {m.tok // 1000}k tokens · ${m.cost:.2f}")
    return [pid]


def run(db, cfg, log=print, only=None, local=None, force=False, parallel=3, stop=None):
    """Review all open PRs (or `only` one id). local=(base, head, title) reviews two local commits instead (testing).
    only = '<id>|<flow or scenario id>|<note>' redraws one diagram of that PR's saved review instead (see redraw)."""
    if only and '|' in str(only):
        return redraw(db, cfg, only, log)
    from . import bitbucket
    if local:
        base, head, title = local
        h = _git(['rev-parse', head]).stdout.strip()
        prs = [{'id': f'local-{h[:8]}', 'title': title, 'head': h, 'base': base, 'source': '', 'dest': base, 'local': True,
                'commits': [{'hash': l.split(' ', 1)[0], 'message': l.split(' ', 1)[-1]} for l in
                            _git(['log', '--oneline', f'{base}..{h}']).stdout.splitlines()]}]
    else:
        prof = config.profile(cfg)
        prs = bitbucket.open_prs_all(prof['review_repos'], prof['main_repo'], log=log)
        since = str(((cfg.get('pr_review') or {}).get('since')) or '2026-09-01')
        n_all = len(prs)
        prs = [p for p in prs if (p.get('created') or '') >= since]     # only PRs opened since this date (ISO compare)
        log(f'Bitbucket: {n_all} open PR(s); {len(prs)} opened since {since} will be reviewed')
        scope = list(prs)                            # every in-scope PR, even when only one is reviewed now
        if only:
            prs = [p for p in prs if str(p['id']) == str(only)]
            if not prs:                              # added by link: older than `since` or not open -> fetch it directly
                try:
                    p = bitbucket.get_pr(only, main=config.profile(cfg)['main_repo'])
                    p['added'] = True
                    prs = [p]
                    scope.append(p)
                    log(f"PR #{only}: added by link ({p.get('state', '?')}, opened {str(p.get('created', ''))[:10]})")
                except Exception as e:
                    log(f"PR #{only}: could not read it from Bitbucket ({str(e)[:160]})")
            force = True                             # asked for one PR by number: always review it again
    try:                                             # rows a stopped run left at 'reviewing', or now out of scope
        keep = {str(p['id']) for p in (scope if only and not local else prs)}
        for d in db.collection('prs').stream():
            x = d.to_dict() or {}
            if not local and not x.get('added') and (x.get('stage') == 'reviewing' or d.id not in keep) and not str(d.id).startswith('local-'):
                d.reference.delete()
    except Exception as e:
        log(f'PR review: could not tidy old rows ({str(e)[:100]})')
    try:                                             # self-heal: put back a missing row from its saved local copy (same head)
        have = {d.id for d in db.collection('prs').stream()}
        for p in (scope if only and not local else prs):
            f = os.path.join(OUT, f"{p['id']}.json")
            if str(p['id']) not in have and os.path.exists(f):
                rec = json.load(open(f))
                if rec.get('head') == p['head'] and rec.get('stage') == 'reviewed':
                    db.collection('prs').document(str(p['id'])).set(_fs(rec))
                    log(f"PR #{p['id']}: board row restored from the saved review")
    except Exception as e:
        log(f'PR review: could not restore rows ({str(e)[:100]})')
    todo = []
    for p in prs:
        if stop and stop():
            break
        old = None
        try:
            d = db.collection('prs').document(str(p['id'])).get()
            old = d.to_dict() if d.exists else None
        except Exception:
            pass
        if old and old.get('head') == p['head'] and old.get('stage') == 'reviewed' and not force:
            log(f"PR #{p['id']}: unchanged since the last review, skipped")
            continue
        if not p.get('local'):
            try:
                p['commits'] = bitbucket.pr_commits(p.get('num', p['id']), p.get('repo') or None)
                p['diff'] = bitbucket.pr_diff(p.get('num', p['id']), p.get('repo') or None)
            except Exception as e:
                log(f"PR #{p['id']}: could not read commits/diff from Bitbucket ({str(e)[:120]}); using git")
        try:
            db.collection('prs').document(str(p['id'])).set({'id': str(p['id']), 'title': p.get('title', ''), 'head': p['head'],
                                                             'url': p.get('url', ''), 'author': p.get('author', ''),
                                                             'source': p.get('source', ''), 'dest': p.get('dest', ''),
                                                             'repo': p.get('repo', ''), 'num': str(p.get('num', p['id'])),
                                                             'added': bool(p.get('added')), 'stage': 'reviewing'}, merge=True)
        except Exception:
            pass
        todo.append(p)
    crashes = _board_crashes(db)
    # Earlier Decide answers are NOT shown to reviews unless pr_review.feedback_notes is on: every run starts clean.
    notes = _feedback_notes(db) if (cfg.get('pr_review') or {}).get('feedback_notes', False) is True else []
    log(f"PR review: {len(notes)} earlier reviewer answer(s) passed to the hunters and judges" if notes
        else "PR review: earlier reviewer answers not used (every review starts clean)")
    done = []

    def go(p):
        if stop and stop():
            return None
        try:
            def early(part):
                db.collection('prs').document(str(p['id'])).set(_fs(part), merge=True)
            rec = review_one(cfg, p, crashes, log, notes=notes, early=early, prev=None if force and not p.get('rereview') else _prev(p))
        except Exception as e:
            log(f"PR #{p['id']}: review failed: {str(e)[:200]}")
            rec = {'id': str(p['id']), 'title': p.get('title', ''), 'head': p['head'], 'stage': 'failed', 'error': str(e)[:300]}
        try:
            db.collection('prs').document(str(p['id'])).set(_fs(rec), merge=True)
        except Exception as e:
            try:                                     # most likely the 1 MB row limit: keep the review, drop the whole diff
                db.collection('prs').document(str(p['id'])).set({**_fs(rec), 'codeJson': None, 'codeCut': True}, merge=True)
                log(f"PR #{p['id']}: saved without the whole-PR diff ({str(e)[:100]})")
            except Exception as e2:
                log(f"PR #{p['id']}: not saved to the board ({str(e2)[:100]})")
        return rec
    with ThreadPoolExecutor(max(1, parallel)) as ex:
        done = [r for r in ex.map(go, todo) if r]
    log(f"PR review done: {len(done)} reviewed, {len(prs) - len(todo)} unchanged")
    return done
