"""Card Issue, phase 2 (Night Shift tool 3): the root cause of a Jira card, reviewed as deeply as a PR.

In:  the card reading (issues, steps, every frame of the screen recording with what it shows) and a read-only
     checkout of the branch to check (native app), plus the app's Kotlin repos (newest sprint, read-only copies).
Out: the same visual review as the PR page: a replay from the video to the code, one scenario per possible root
     cause (proof chain -> line check -> two judges -> tier), QA steps, and the suggested fix as code.
     Saved to out/cards/<KEY>/review.json and Firestore cardreviews/<KEY> (Night Shift's own project only).

Stages: Kotlin side -> card map (Sonnet) -> hunt (3 seats: root cause, user flow, threads) -> merge -> line check
-> 2 judges -> tiers -> replays + fix (card-visual) -> issue status (code) -> chair. Nothing is written to the repos."""
import datetime as dt
import json
import os
import shutil
import re
from concurrent.futures import ThreadPoolExecutor

from . import config, llm, prvisual, kotlinctx, prreview
if not hasattr(config, 'profile'):                 # long-running worker: pick up the profile helpers once
    import importlib as _il
    _il.reload(config)


def _app_name():
    try:
        return config.profile().get('name') or 'the app'
    except Exception:
        return 'the app'

SEATS = [
    ('cause', 'Root cause',
     "## Your seat: root cause\nFor each issue, the main causal chain from the user's last actions before the first BUG "
     "frame to what the BUG frames show, and the line where it goes wrong. Then check 1-3 alternative places and write "
     "the ones you rule out as \"Not the cause\" (safe) scenarios.\n\n" + prreview.ERROR_PATHS),
    ('flows', 'User flow',
     "## Your seat: the user flow in the video\nWalk the video step by step (the steps and the frames). For each user "
     "action, find the code it runs and the state after it, BOTH in the engine (time, speed, selection, what is decoded "
     "or drawn) and in the Kotlin UI (cursor, time label, selected item, panel state, saved project). Find the FIRST "
     "action after which the state is wrong and say which one it is. Follow every exit the video uses: Done/Apply, the "
     "panel's Cancel, the phone's Back button (system Back), undo/redo, Play afterwards, switching clip. A mismatch "
     "between the engine and the UI that the user can see is a cause.\n\n" + prreview.FLOW_EXITS),
    ('threads', 'Threads and lifetime',
     "## Your seat: threads, lifetime and resources\nLook at the path for races (two threads on one object, a check and "
     "a use with no lock between), use after free, locks and waits (who holds what, a wait that must time out), blocking "
     "calls on the UI thread (ANR), leaks that grow, GL context or state problems, and failures stored as ready. "
     "Most important for a crash, a freeze, an ANR or a bug that happens 'sometimes'. For a plain behaviour bug, check "
     "the threads on the path quickly and say so.\n\n" + prreview.ERROR_PATHS),
]
STATUS_WORDS = {'explained': 'Root cause verified', 'likely': 'Likely cause (not proven)', 'unexplained': 'Not explained by the code',
                'server': 'Server content (not the app)', 'gap': 'Feature gap (not built in the app)', 'unchecked': 'No root cause yet'}


def _now():
    return dt.datetime.now().isoformat(timespec='seconds')


def _J(o, n):
    return json.dumps(o, indent=1, ensure_ascii=False)[:n]


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


def judge_names(issues, area=''):
    a = ' '.join([str(area)] + [f"{x.get('kind', '')} {x.get('title', '')} {x.get('actual', '')}" for x in issues]).lower()
    second = ('Threading judge' if re.search(r'crash|anr|freeze|frozen|race|thread|lock|not responding|stuck', a) else
              'Audio judge' if re.search(r'audio|sound|music|volume|voice', a) else
              'Renderer judge' if re.search(r'black|render|preview|effect|colou?r|image|visual|frame|flicker|blur', a) else
              'UI judge')
    return ['Skeptic', second]


def brief(doc, note=''):
    """Everything the models need from the card reading, as text."""
    card = doc.get('card') or {}
    issues = [{k: x.get(k) for k in ('n', 'title', 'kind', 'expected', 'actual', 'steps', 'crash', 'video', 'from', 'to',
                                      'bug_frames', 'ref_frames', 'compare', 'reference') if x.get(k) not in (None, '', [], {})}
              for x in doc.get('issues') or []]
    refv = {v.get('v'): (v.get('app') or 'reference') for v in doc.get('videos') or [] if v.get('role') == 'reference'}
    vids = '\n'.join(f"- video {v.get('v')}: {v.get('app') or ''} · {v.get('name', '')} · {v.get('seconds', '?')} s · {v.get('role', '')} · {v.get('what', '')}"
                     for v in doc.get('videos') or [])
    fr = '\n'.join(f"{f.get('i'):>3} v{f.get('v', 1)} {f.get('t', '')} {('REF ' + refv[f.get('v', 1)] + ' ') if f.get('v', 1) in refv else ''}{'BUG ' if f.get('bug') else ''}"
                   f"{('#' + str(f.get('issue')) + ' ') if f.get('issue') else ''}[{f.get('screen', '')}] {f.get('note', '')}"
                   for f in key_frames(doc))
    com = '\n'.join(f"- {str(c.get('created', ''))[:10]} {c.get('author', '')}: {str(c.get('text', ''))[:350]}" for c in (card.get('comments') or [])[-12:])
    return (f"# Jira card {card.get('key', doc.get('key'))} · {card.get('type', '')} · {card.get('title', '')}\n\n"
            + (f"## Developer's note (trust it)\n{note}\n\n" if note else '')
            + f"## Description\n{str(card.get('description') or '(empty)')[:4000]}\n\n"
            + (f"## Comments (latest)\n{com}\n\n" if com else '')
            + (f"## Videos\n{vids}\n\n" if vids else '')
            + (f"## Reference video\nVideo {', '.join(f'{k} ({a})' for k, a in refv.items())} shows the RIGHT behaviour from another "
               "app or build (frames marked REF). It is the expected result only: never its code, never a step.\n\n" if refv else '')
            + f"## Issues the card reading found (from the text and the video)\n```json\n{_J(issues, 14000)}\n```\n\n"
            + ("## The video, frame by frame (i, video, time, BUG = the bug shows here, #n = issue, [screen], what is visible)\n"
               f"```\n{fr[:16000]}\n```\n\n" if fr else "## Video\nThis card has no screen recording: work from the text.\n\n"))


def key_frames(doc, around=6, cap=82):
    """The frames the models need: each issue's bug frames and the frames just before and after them (the user's last
    actions), without 'No change' frames. The page still shows every frame."""
    frames = doc.get('frames') or []
    hot = set()
    for x in doc.get('issues') or []:
        for b in (x.get('bug_frames') or []) + [((x.get('crash') or {}).get(k)) for k in ('last_normal_frame', 'first_bad_frame')]:
            try:
                hot.add(int(b))
            except (TypeError, ValueError):
                pass
    hot |= {f.get('i') for f in frames if f.get('bug') or f.get('issue')}
    refv = {v.get('v') for v in doc.get('videos') or [] if v.get('role') == 'reference'}
    refi = set()                                   # a reference video (e.g. CapCut): its expected-result frames, max 12
    for x in doc.get('issues') or []:
        for b in x.get('ref_frames') or []:
            try:
                refi |= {int(b) - 1, int(b), int(b) + 1}
            except (TypeError, ValueError):
                pass
    rf = [f for f in frames if f.get('v', 1) in refv]
    rkeep = [f for f in rf if f.get('i') in refi] or [f for f in rf if not str(f.get('note') or '').lower().startswith(('no change', 'still ', 'same '))]
    rkeep = rkeep[:12]
    keep = []
    for f in frames:
        i = f.get('i') or 0
        near = any(abs(i - h) <= around for h in hot)
        boring = str(f.get('note') or '').strip().lower().startswith(('no change', 'still ', 'same '))
        if (near and not boring) or i in hot:
            keep.append(f)
    if not keep:
        keep = [f for f in frames if not str(f.get('note') or '').lower().startswith('no change')]
    rid = {f.get('i') for f in rkeep}
    keep = rkeep + [f for f in keep if f.get('i') not in rid and f.get('v', 1) not in refv]
    keep.sort(key=lambda f: f.get('i') or 0)
    return keep[:cap]


def kotlin_text(paths, label, wt, names):
    """The Kotlin side of the native functions the map found: JNI bridge and Kotlin call sites (no model)."""
    if not paths:
        return '## Kotlin side\nNo Kotlin repo could be read for this review: Kotlin callers cannot be checked.\n\n'
    br = kotlinctx.bridge(wt, {n.split('::')[-1] for n in names if n}) if names else []
    blocks = []
    for b in br[:6]:
        decl, calls = kotlinctx.callers(paths, b['kotlin'])
        blocks.append(f"### Kotlin `{b['kotlin']}` -> {b['jni']}" + (f" -> {', '.join(b['via'])}" if b['via'] else '')
                      + f" -> {', '.join(b['calls'])}\nDeclared: {', '.join(decl) or 'not found'}\n"
                      + ('\n'.join(f"Call at {c['at']}:\n```\n{c['code']}\n```" for c in calls[:3]) or 'No Kotlin call site found.'))
    return ("## Kotlin side (the app's UI code; read-only copies, newest sprint branch)\n"
            f"Repos: {label}\nYou may Read/Grep them at: {', '.join(paths)}\n"
            "A Kotlin caller with file:line is evidence; a caller you cannot find there does not exist.\n\n"
            + ('\n\n'.join(blocks) if blocks else 'No JNI bridge found yet for the mapped native functions: Grep the Kotlin repos.')
            + '\n\n')[:16000]


class Review:
    def __init__(self, doc, branch, commit, wt, cfg, out_dir, log=print, note='', progress=None):
        self.doc, self.branch, self.commit, self.wt = doc, branch, commit, wt
        self.cfg, self.out, self.log, self.note = dict(cfg), out_dir, log, note
        self.progress = progress or (lambda s: None)
        self.key = doc.get('key') or (doc.get('card') or {}).get('key') or 'card'
        self.t0 = dt.datetime.now()
        self.st = prreview.Stages(self.t0)
        self.model = (cfg.get('llm') or {}).get('model_card') or 'opus'
        self.small = (cfg.get('llm') or {}).get('model_card_small') or 'sonnet'
        self.block = [f'{t}(/{config.REPO.strip("/")}/**)' for t in ('Read', 'Grep', 'Glob')] + ['Bash', 'WebFetch', 'WebSearch']

    def call(self, skill, prompt, tag, model=None, timeout=1800, tools='Read,Grep,Glob'):
        u = {}
        txt = llm.run(skill, prompt, self.cfg, self.out, f'review.{tag}', tools=tools, cwd=self.wt, timeout=timeout,
                      model=model or self.model, block=self.block, usage=u)
        self.st.add(u)
        if not (txt or '').strip():                       # an empty answer: a dead login stops the review at once
            ef = os.path.join(self.out, f'review.{tag}.error.txt')
            err = open(ef).read() if os.path.exists(ef) else ''
            if 'authenticate' in err or 'login' in err.lower():
                raise RuntimeError('the Claude CLI on the lab Mac is not logged in (session expired): run claude, then /login')
        return txt

    # ---------------------------------------------------------------- stages
    def kotlin(self):
        self.st.start('Kotlin side', 'no AI')
        paths, label, res = [], '', 'no Kotlin repo reachable'
        try:
            repos = kotlinctx.sync(self.cfg, self.log)
            paths = [r['path'] for r in repos]
            label = ' · '.join(f"{r['repo']} {r['branch']}@{r['sha'][:7]}" for r in repos)
            res = label or res
        except Exception as e:
            res = f'skipped ({str(e)[:120]})'
        if paths:
            self.cfg['_add_dirs'] = paths                 # every model call may Read/Grep the Kotlin copies
            prvisual.EXTRA_ROOTS[:] = paths               # Kotlin file:line refs pass the line check and count as judge evidence
            prvisual._EXTRA_IDX = None
        self.st.end(res)
        return paths, label

    def run(self):
        doc, issues = self.doc, self.doc.get('issues') or []
        brief_txt = brief(doc, self.note)
        head = (f"# Root-cause review of Jira card {self.key} in branch {self.branch} (commit {self.commit[:10]})\n"
                "You are in a read-only checkout of that branch (the native app). Read, Grep and Glob only.\n\n")
        self.progress('reading the Kotlin side')
        kpaths, klabel = self.kotlin()
        try:                                              # effects, frames, transitions... the card names: fetched read-only
            from . import servercontent
            self.st.start('Server content', 'no AI')
            smd, sdir = servercontent.collect(doc, self.key, log=self.log,
                                              endpoints=(self.cfg.get('server_content') or {}).get('endpoints'))
            if sdir:                                    # the video frames around each bug, as images next to the thumbnails
                pub = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'board', 'public')
                want = sorted({int(b) + d for x in issues for b in (x.get('bug_frames') or []) if str(b).isdigit() for d in (-2, 0, 2)})[:12]
                byi = {f.get('i'): f for f in doc.get('frames') or []}
                vf = []
                for i in want:
                    f = byi.get(i) or {}
                    src = os.path.join(pub, str(f.get('url') or '').lstrip('/'))
                    if f.get('url') and os.path.exists(src):
                        dst = os.path.join(sdir, f"video_frame_{i:03d}.jpg")
                        shutil.copyfile(src, dst)
                        vf.append(f"`{dst}` (frame {i}, {f.get('t', '')}{', BUG' if f.get('bug') else ''})")
                if vf:
                    smd += ("## Video frames of the bug (open with Read to compare with the thumbnails above)\n"
                            + '\n'.join('- ' + v for v in vf) + '\n\n')
            att = [p for p in (doc.pop('_attach', None) or []) if os.path.exists(p)]
            if att:                                     # code or text files someone attached to the card
                smd += ("## Files attached to the Jira card (by QA or a developer; read them, cite their lines like code)\n"
                        + '\n'.join(f'- `{p}`' for p in att) + '\nThey may be a proposed fix or the expected version of a server file: '
                        'compare them with what the app and the server use now, and say so when they would fix it.\n\n')
                sdir = sdir or os.path.dirname(os.path.dirname(att[0]))
            if sdir:
                brief_txt += smd
                self.cfg['_add_dirs'] = list(self.cfg.get('_add_dirs') or []) + [sdir]
                prvisual.EXTRA_ROOTS[:] = list(prvisual.EXTRA_ROOTS) + [sdir]
                prvisual._EXTRA_IDX = None
            self.st.end(f"{smd.count(chr(10) + '- ')} item(s) fetched read-only" if sdir else 'not needed (the card names no server item)')
        except Exception as e:
            self.log(f'server content skipped ({str(e)[:150]})')
            self.st.end(f'skipped ({str(e)[:80]})')

        self.progress('mapping the card to the code')
        self.st.start('Card map', self.small.capitalize())
        cmap = _json(self.call('card-map', head + brief_txt + kotlin_text(kpaths, klabel, self.wt, []), 'map',
                               model=self.small, timeout=1200))
        names = [str(f.get('name') or '') for f in cmap.get('functions') or [] if isinstance(f, dict)]
        names += [str(n) for x in cmap.get('issues') or [] if isinstance(x, dict) for n in x.get('native') or []]
        self.st.end(f"{len(cmap.get('functions') or [])} function(s) · {len(cmap.get('issues') or [])} issue(s) mapped" if cmap else 'no answer')
        ktext = kotlin_text(kpaths, klabel, self.wt, names)
        pack = ''
        try:
            pack = prvisual.code_pack(self.wt, '', {'functions': [f for f in cmap.get('functions') or [] if isinstance(f, dict)]}, cap=20000)
        except Exception as e:
            self.log(f'code pack skipped ({str(e)[:120]})')
        common = (head + brief_txt + ktext
                  + (f"## Card map (where each issue lives; facts with file:line)\n```json\n{_J(cmap, 16000)}\n```\n\n" if cmap else '')
                  + (f"## The code you need (read once for you from this checkout; line numbers are real)\n```\n{pack}\n```\n\n" if pack else ''))

        crashy = any(re.search(r'crash|anr|freez|frozen|not responding|stuck|hang', f"{x.get('kind', '')} {x.get('title', '')} {x.get('actual', '')}".lower())
                     for x in issues)
        seats = [s for s in SEATS if s[0] != 'threads' or crashy]
        self.progress(f'hunting the root cause ({len(seats)} seats)')
        self.st.start(f"Hunt ({len(seats)} seats: " + ', '.join(f"{k} {self.small if k == 'threads' else self.model}" for k, _, _ in seats) + ')',
                      ' + '.join(sorted({(self.small if k == 'threads' else self.model).capitalize() for k, _, _ in seats})))
        res = {}
        budget = ("\n## Budget\nOpen about 25 files or ranges at most, then answer. The map and the code above usually "
                  "contain the path: read further only to prove a step or check an alternative.\n")

        def seat(s):
            key, name, focus = s
            # the user-flow walk reads the most: a tighter budget and a 12-minute limit (if it runs over, the review
            # goes on with the other hunters instead of waiting)
            bud = budget.replace('about 25 files', 'about 15 files') if key == 'flows' else budget
            try:
                txt = self.call('card-hunt', common + focus + bud, f'seat-{key}', model=self.small if key == 'threads' else self.model,
                                timeout=720 if key == 'flows' else 2100)
            except RuntimeError:
                raise
            except Exception as e:
                self.log(f'seat {key} failed ({str(e)[:120]}); going on without it')
                txt = ''
            if key == 'flows' and not (txt or '').strip().startswith(('{', '`')) and 'scenarios' not in (txt or ''):
                self.log('user-flow hunter ran over 12 min or gave no answer; going on with the other hunters')
            return key, name, _json(txt)
        with ThreadPoolExecutor(len(seats)) as ex:
            for key, name, a in ex.map(seat, seats):
                fs = [dict(f, categories=[name]) for f in a.get('findings') or [] if isinstance(f, dict)]
                scs = [dict(x, id=f'{key}-{k + 1}', **{'from': [name]}) for k, x in enumerate(a.get('scenarios') or [])
                       if isinstance(x, dict) and x.get('title')]
                res[name] = {'findings': fs, 'scenarios': scs, 'summary': str(a.get('summary') or '')[:900]}
        hunted = [x for v in res.values() for x in v['scenarios']]
        allf = [f for v in res.values() for f in v['findings']]
        self.st.end(f"{len(allf)} root cause(s) and {len(hunted)} scenario(s) from {sum(1 for v in res.values() if v['scenarios'] or v['findings'])} seat(s)")

        self.progress('merging')
        self.st.start('Merge', self.model.capitalize())
        syn = _json(self.call('card-merge', head + brief_txt + "## What the hunters returned\n```json\n"
                              + _J({k: {'findings': v['findings'], 'scenarios': v['scenarios']} for k, v in res.items()}, 80000)
                              + '\n```\n', 'merge', timeout=1200, tools=''))
        findings = [f for f in syn.get('findings') or [] if isinstance(f, dict)] or allf
        given = [x for x in syn.get('scenarios') or [] if isinstance(x, dict) and x.get('title')]
        if not given and hunted:                          # merge failed: keep the hunters' own scenarios, unlinked
            given = [dict(x, finding=None) for x in hunted]
        for k, x in enumerate(given):
            x['id'] = str(x.get('id') or f's{k + 1}')
        self.st.end(f'{len(findings)} root cause(s) · {len(given)} scenario(s)')
        meta = {x['id']: {'issue': self._int(x.get('issue')), 'frames': self._frames(x.get('frames'))} for x in given}

        view = None
        try:
            view, _ = prvisual.build({}, self.wt, '', findings[:40], given=given)
        except Exception as e:
            self.log(f'scenarios could not be built ({str(e)[:160]})')
        # the expert judge is chosen per issue (a black preview gets the Renderer judge even when the same card also has
        # an ANR for the Threading judge): an expert asked about another field only says "unsure"
        dom_of = {x.get('n'): judge_names([x])[1] for x in issues}
        experts = sorted(set(dom_of.values())) or [judge_names(issues, (doc.get('analysis') or {}).get('area', ''))[1]]
        names_j = ['Skeptic'] + experts
        if view is not None:
            self.st.start('Code-path check', 'no AI')
            nd = len(view.get('dropped') or [])
            n = prvisual.pathcheck(view, self.wt, '')
            need = prvisual.check_findings(findings, view, self.wt, '')
            self.st.end(f"{n} cited line(s) checked · {len(view.get('dropped') or []) - nd} scenario(s) dropped (line did not match)"
                        f" · {len(need)} unlinked root cause(s) for the judges")
            self._attach(view, meta)
            self.progress('two judges are checking each cause')
            frame_note = {f.get('i'): f"frame {f.get('i')} ({f.get('t', '')}): {f.get('note', '')}" for f in doc.get('frames') or []}
            items = [{'id': x['id'], 'kind_of_item': 'scenario', 'issue': x.get('issue'), 'title': x.get('title'), 'q': x.get('q'),
                      'claim': x.get('verdict'), 'kind': x.get('kind', ''), 'why': x.get('why'),
                      'explains': [frame_note[i] for i in (x.get('frames') or []) if i in frame_note][:8],
                      'proof': [{'line': q[0], 'text': q[1]} for q in (x.get('proof') or {}).get('steps') or []]}
                     for x in view.get('scenarios') or []]
            items += [{'id': 'f%d' % i, 'kind_of_item': 'finding', 'issue': findings[i].get('issue'), 'title': findings[i].get('title'),
                       'claim': 'suspected', 'severity': findings[i].get('severity'), 'problem': findings[i].get('problem'),
                       'proof': [{'line': findings[i].get('check'), 'text': findings[i].get('evidence')}]} for i in need]
            self.st.start(f'Challenge ({len(names_j)} judges)', self.model.capitalize())
            votes = {}
            if items:
                def judge(name):
                    role = ("Try hard to refute each item; confirm only what the code forces and the video shows.\n\n" if name == 'Skeptic'
                            else f"Judge as a {name.replace(' judge', '').lower()} expert.\n\n")
                    mine = items if name == 'Skeptic' else [x for x in items if x.get('claim') != 'safe'
                                                            and (len(experts) == 1 or dom_of.get(x.get('issue'), experts[0]) == name)]
                    if not mine:
                        return name, {}
                    txt = self.call('card-judge', f"# Your role: {name}\n{role}" + head + brief_txt + ktext
                                    + "## Items (unsigned)\n```json\n" + _J(mine, 50000) + '\n```\n'
                                    + "\n## Budget\nOpen about 15 files or ranges at most, then vote.\n", f"judge-{name.split()[0].lower()}", timeout=1800)
                    return name, {v.get('id'): v for v in (_json(txt).get('votes') or []) if isinstance(v, dict)}
                with ThreadPoolExecutor(len(names_j)) as ex:
                    for name, v in ex.map(judge, names_j):
                        if v and name == 'Skeptic':
                            votes[name] = v
                        elif v:                    # all experts count as ONE second judge, each on its own issues
                            for k, vv in v.items():
                                votes.setdefault('Expert judge', {})[k] = dict(vv, note=f"[{name}] {vv.get('note') or vv.get('why') or ''}".strip())
            judged = [n_ for n_ in ('Skeptic', 'Expert judge') if n_ in votes]
            before = {x['id'] for x in view.get('scenarios') or []}
            prvisual.tiers(view, votes, judged, self.wt, '', findings)
            for s in view.get('scenarios') or []:      # a risk split out of a "Not the cause" item: a side finding, shown once
                if str(s.get('title', '')).startswith('Still open in'):
                    s['title'] = 'Side finding (not this card\'s cause): ' + str(s.get('title', '')).split('": ', 1)[-1][:120]
            prvisual.finding_tiers(findings, view, votes, judged, self.wt, '')
            self._attach(view, meta)
            sc = view.get('scenarios') or []
            self.st.end(f"{sum(1 for x in sc if x['verdict'] == 'verified')} verified · {sum(1 for x in sc if x['verdict'] == 'suspected')} suspected · "
                        f"{sum(1 for x in sc if x['verdict'] == 'safe')} ruled out · {len(before - {x['id'] for x in sc})} dropped"
                        + ('' if votes or not items else ' (the judges did not answer)'))

            self.progress('drawing the replays and the suggested fix')
            self.st.start('Replays + fix', self.model.capitalize())
            keep = list(sc)
            try:
                vis = _json(self.call('card-visual', head + brief_txt + ktext + prreview.REPLAY_RULES
                                      + "## Scenarios after the judges (give each one a replay; do not change them)\n```json\n"
                                      + _J([{'id': x['id'], 'issue': x.get('issue'), 'frames': x.get('frames'), 'title': x.get('title'),
                                             'q': x.get('q'), 'tier': x.get('verdict'), 'kind': x.get('kind'), 'why': x.get('why'),
                                             'proof': [{'line': q[0], 'text': q[1]} for q in (x.get('proof') or {}).get('steps') or []]}
                                            for x in keep if x.get('verdict') != 'safe'], 30000)
                                      + "\n```\n\n## Root causes (0-based index)\n```json\n"
                                      + _J([{'i': i, 'issue': f.get('issue'), 'title': f.get('title'), 'file': f.get('file'),
                                             'line': f.get('line'), 'tier': f.get('tier')} for i, f in enumerate(findings[:40])], 12000)
                                      + '\n```\n', 'visual', timeout=1800))
                dropped = view.get('dropped') or []
                view2, _ = prvisual.build(vis or {}, self.wt, '', findings[:40], given=keep)
                view2['dropped'] = dropped
                for k in ('tldr', 'before', 'adds', 'heads'):
                    if (vis or {}).get(k):
                        view2[k] = vis[k]
                clean_view(view2)
                view = view2
                self._attach(view, meta)
            except Exception as e:
                self.log(f'replays failed ({str(e)[:160]}); scenarios keep their proof chain as the replay')
            self.st.end(f"{len(keep)} replay(s) · {sum(1 for x in view.get('scenarios') or [] if x.get('fixCode'))} suggested fix(es)")
        else:
            for f in findings:
                f['tier'] = 'unchecked'

        nfr = len(doc.get('frames') or [])
        self._frames_ok(view, nfr)
        status = self.issue_status(view, findings, issues)
        if view is not None:
            view['ready'] = self.ready_cards(status)
            view['issues'] = status
        verdict = ('server' if status and all(s['status'] in ('explained', 'server') for s in status) and any(s['status'] == 'server' for s in status) else
                   'explained' if status and all(s['status'] == 'explained' for s in status) else
                   'partly' if any(s['status'] == 'explained' for s in status) else
                   'likely' if any(s['status'] == 'likely' for s in status) else 'unexplained')

        self.progress('writing the summary')
        self.st.start('Chair', self.small.capitalize())
        chair = _json(self.call('card-chair', head + f"## Issues\n```json\n{_J([{k: x.get(k) for k in ('n', 'title', 'kind')} for x in issues], 4000)}\n```\n\n"
                                + "## Issue status (set by code)\n```json\n" + _J(status, 6000) + '\n```\n\n'
                                + "## Checked results\n```json\n" + _J([{'id': x['id'], 'issue': x.get('issue'), 'title': x.get('title'),
                                                                         'tier': x.get('verdict'), 'severity': x.get('severity'),
                                                                         'fix': bool(x.get('fixCode')),
                                                                         'fix_at': (f"{(x.get('fixCode') or {}).get('file', '')}:{(x.get('fixCode') or {}).get('line', '')}"
                                                                                    if x.get('fixCode') else ''),
                                                                         'fix_note': (x.get('fixCode') or {}).get('note', ''), 'why': x.get('why')}
                                                                        for x in (view or {}).get('scenarios') or []], 20000) + '\n```\n',
                                'chair', model=self.small, timeout=600, tools=''))
        self.st.end('summary written' if chair else 'no answer')
        n_ex = sum(1 for s in status if s['status'] == 'explained')
        rec = {'key': self.key, 'id': self.key, 'title': (doc.get('card') or {}).get('title', ''), 'url': (doc.get('card') or {}).get('url', ''),
               'type': (doc.get('card') or {}).get('type', ''), 'branch': self.branch, 'head': self.commit, 'commit': self.commit[:10],
               'kotlin': klabel, 'verdict': verdict, 'stage': 'reviewed', 'early': False,
               'headline': chair.get('headline') or (view or {}).get('tldr') or f'Root cause verified for {n_ex} of {len(status)} issue(s).',
               'summary': chair.get('summary') or '', 'next': [str(x) for x in chair.get('next') or []][:6],
               'qa': [str(x) for x in chair.get('qa') or []][:8],
               'issueLines': {str(x.get('n')): str(x.get('line') or '') for x in chair.get('issues') or [] if isinstance(x, dict)},
               'issues': status, 'findings': findings[:40], 'view': view, 'reviewedAt': _now(),
               'minutes': round((dt.datetime.now() - self.t0).total_seconds() / 60, 1)}
        self.st.end()
        rec['stages'] = self.st.rows
        rec['usage'] = {'tokens': self.st.total['tokens'], 'cost_usd': round(self.st.total['cost_usd'], 2), 'calls': self.st.total['calls']}
        rec['how'] = (f"{rec['minutes']} min · {rec['usage']['tokens'] // 1000}k tokens · ${rec['usage']['cost_usd']:.2f} · "
                      f"3 hunters, line check, judges: {', '.join(names_j)}")
        self.save(rec)
        self.log(f"card review {self.key}: {verdict} · {n_ex}/{len(status)} issue(s) verified · {rec['how']}")
        return rec

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _frames(v):
        out = []
        for x in v or []:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out[:20]

    def _attach(self, view, meta):
        """prvisual keeps only the PR fields of a scenario: put the card's issue and frames back (split ones inherit)."""
        for s in (view or {}).get('scenarios') or []:
            m = meta.get(s['id']) or meta.get(re.sub(r'r$', '', s['id'])) or {}
            if m.get('issue') is not None:
                s['issue'] = m['issue']
            if m.get('frames'):
                s['frames'] = m['frames']

    @staticmethod
    def _frames_ok(view, nfr):
        """A frame number must exist in the card's video; anything else is removed (the page links frames to steps)."""
        if not view:
            return
        for rp in [view.get('flow')] + list(view.get('scenarios') or []):
            for k in ('bug', 'fix'):
                for s in ((rp or {}).get(k) or {}).get('steps') or []:
                    try:
                        f = int(s.get('frame'))
                    except (TypeError, ValueError):
                        s.pop('frame', None)
                        continue
                    if 1 <= f <= nfr:
                        s['frame'] = f
                    else:
                        s.pop('frame', None)
        for s in view.get('scenarios') or []:
            s['frames'] = [f for f in s.get('frames') or [] if 1 <= f <= nfr]

    @staticmethod
    def issue_status(view, findings, issues):
        """Per issue, set by code: explained = a Verified cause scenario; gap = a Verified "Not built in MyZesty" scenario
        (the expected behaviour, e.g. from a CapCut reference, does not exist in the code); likely = only Suspected; else
        unexplained."""
        out = []
        scs = (view or {}).get('scenarios') or []
        for x in issues:
            n = x.get('n')
            mine = [s for s in scs if s.get('issue') == n and not str(s.get('title', '')).startswith('Side finding')]
            ver = [s for s in mine if s.get('verdict') == 'verified']
            sus = [s for s in mine if s.get('verdict') == 'suspected' and not str(s.get('title', '')).startswith('Not explained')]
            fv = [f for f in findings if f.get('issue') == n and f.get('tier') == 'verified']
            st = 'explained' if ver or fv else 'likely' if sus else 'unexplained'
            best = (ver or sus or [None])[0]
            if st == 'explained' and best and str(best.get('title', '')).lower().startswith('not built in'):
                st = 'gap'
            if best and re.match(r'(server content|not in the app code)', str(best.get('title', '')).lower()):
                st = 'server'                               # the cause is in content the app downloads (shader, image, item data)
            out.append({'n': n, 'title': x.get('title', ''), 'kind': x.get('kind', ''), 'status': st,
                        'scenario': best['id'] if best else None, 'fix': bool(best and best.get('fixCode')),
                        'proven': bool(best and best.get('verdict') == 'verified'),
                        'frames': (best or {}).get('frames') or x.get('bug_frames') or [],
                        'ruledOut': sum(1 for s in mine if s.get('verdict') == 'safe')})
            out[-1]['refFrames'] = [int(b) for b in x.get('ref_frames') or [] if str(b).isdigit()][:4]
        return out

    @staticmethod
    def ready_cards(status):
        """'Is it explained?' cards, one per issue, coloured by code (never by a model)."""
        out = []
        for s in status:
            kind = {'explained': 'bad', 'server': 'bad', 'gap': 'bad', 'likely': 'maybe', 'unexplained': 'maybe'}.get(s['status'], 'maybe')
            text = (('Both judges confirmed the cause in the code.' + (' A suggested fix is attached.' if s['fix'] else ''))
                    if s['status'] == 'explained' else
                    ('The cause is in content the app downloads (shader, image or item data), not in the app code.'
                     + (' Proven from the downloaded file.' if s.get('proven') else ' Not proven.')) if s['status'] == 'server' else
                    f"The expected behaviour is not built in {_app_name()} (feature gap)." if s['status'] == 'gap' else
                    'A possible cause was found, but it is not proven (timing, a device, or a trigger outside the code).'
                    if s['status'] == 'likely' else 'No cause in this branch survived the checks. It may be a server, an asset or a device issue.')
            c = {'kind': kind, 'title': f"Issue {s['n']} · {STATUS_WORDS.get(s['status'], s['status'])}", 'text': text}
            if s.get('scenario'):
                c['sc'] = s['scenario']
            out.append(c)
        return out

    def _db(self):
        try:
            from . import fire
            return fire.client()
        except Exception:
            return None

    def save_early(self, view, findings):
        db = self._db()
        if db is None:
            return
        try:
            rec = {'key': self.key, 'id': self.key, 'branch': self.branch, 'head': self.commit, 'stage': 'reviewing', 'early': True,
                   'title': (self.doc.get('card') or {}).get('title', ''), 'view': view, 'findings': findings[:40],
                   'stages': self.st.rows, 'reviewedAt': _now()}
            db.collection('cardreviews').document(self.key).set(prreview._fs(rec))
        except Exception as e:
            self.log(f'early look not saved ({str(e)[:120]})')

    def save(self, rec):
        os.makedirs(self.out, exist_ok=True)
        json.dump(rec, open(os.path.join(self.out, 'review.json'), 'w'), indent=1, ensure_ascii=False)
        db = self._db()
        if db is None:
            return
        try:
            db.collection('cardreviews').document(self.key).set(prreview._fs(rec))
        except Exception as e:
            self.log(f'review not saved to Firestore ({str(e)[:160]})')


def clean_view(v):
    """The model's summary boxes in the shapes the page expects (a string snippet once broke the whole page)."""
    def strl(x, n):
        if isinstance(x, list):
            return [str(i)[:200] for i in x if i not in (None, '')][:n]
        return [l[:200] for l in str(x).split('\n') if l.strip()][:n] if x else []
    for k in ('tldr', 'heads'):
        if k in v and not isinstance(v[k], str):
            v[k] = str(v[k] or '')
    b = v.get('before')
    if b is not None:
        b = b if isinstance(b, dict) else {'text': str(b)}
        b['mini'] = [[str(c)[:60] for c in (m if isinstance(m, list) else [m])][:3] for m in (b.get('mini') or []) if m][:4]
        b['text'], b['title'] = str(b.get('text') or ''), str(b.get('title') or '')
        v['before'] = b
    a = v.get('adds')
    if a is not None:
        a = a if isinstance(a, dict) else {'text': str(a)}
        a['snippet'] = strl(a.get('snippet'), 3)
        a['text'], a['title'] = str(a.get('text') or ''), str(a.get('title') or '')
        v['adds'] = a
    return v


def legacy_rootcause(rec):
    """The old one-box root cause on the Card Issue tab, filled from the review (so old views keep working)."""
    view = rec.get('view') or {}
    by = {s['id']: s for s in view.get('scenarios') or []}
    out = []
    for st in rec.get('issues') or []:
        s = by.get(st.get('scenario')) or {}
        files = [{'path': p[0].rsplit(':', 1)[0], 'lines': p[0].rsplit(':', 1)[1], 'why': p[1][:160]}
                 for p in (s.get('proof') or {}).get('steps') or [] if p and p[0] and ':' in p[0]][:6]
        out.append({'n': st.get('n'), 'root_cause': s.get('title') or STATUS_WORDS.get(st['status'], st['status']),
                    'mechanism': ' '.join(w[2] for w in s.get('why') or [] if len(w) > 2)[:600],
                    'files': files, 'fix_direction': (s.get('fixCode') or {}).get('note', ''),
                    'fixCode': {k: (s.get('fixCode') or {}).get(k) for k in ('file', 'line', 'diff', 'note')} if s.get('fixCode') else None,
                    'tier': s.get('verdict'), 'judges': '; '.join(f"{j[0]} {j[1]}" for j in (s.get('proof') or {}).get('judges') or []),
                    'confidence': {'explained': 0.9, 'server': 0.9 if st.get('proven') else 0.5, 'gap': 0.8, 'likely': 0.5}.get(st['status'], 0.1),
                    'confirm_by': '',
                    'not_in_code': st['status'] == 'unexplained', 'status': st['status']})
    return {'branch': rec.get('branch'), 'commit': rec.get('commit'), 'issues': out, 'skillUsed': True, 'review': True}


def summary_for_card(rec):
    """Small, Firestore-safe summary on cards/<KEY> (the full review lives in cardreviews/<KEY>)."""
    return {'verdict': rec.get('verdict'), 'headline': str(rec.get('headline') or '')[:400], 'branch': rec.get('branch'),
            'commit': rec.get('commit'), 'reviewedAt': rec.get('reviewedAt'), 'minutes': rec.get('minutes'),
            'cost': (rec.get('usage') or {}).get('cost_usd'),
            'issues': [{'n': s.get('n'), 'status': s.get('status'), 'title': str(s.get('title') or '')[:140], 'fix': bool(s.get('fix'))}
                       for s in rec.get('issues') or []]}
