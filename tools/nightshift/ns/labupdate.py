"""After lab work on a crash: rewrite its root cause, confidence and diagrams from what the lab proved (diagnoses,
learned facts, hook runs) and the proposed patch, so the board never shows a root cause older than the lab."""
import glob, json, os, re

from . import config, llm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out')


def _json(txt):
    for chunk in reversed(re.findall(r'```json\n(.*?)```', txt or '', re.S) or re.findall(r'(\{.*\})', txt or '', re.S)):
        try:
            return json.loads(chunk)
        except ValueError:
            continue
    return {}


def run(db, cfg, case_id, log=print, deny=None):
    from . import groups as _g
    k8 = _g.k8(case_id)
    mref = None
    for mid in ('m-' + case_id, 'm-play-' + case_id):
        d = db.collection('merged').document(mid).get()
        if d.exists:
            mref, m = d.reference, d.to_dict() or {}
            break
    if mref is None or not (m.get('analysis') or {}).get('root_cause'):
        log('lab update: no root cause to update yet')
        return None
    c = db.collection('cases').document(case_id).get().to_dict() or {}
    a = m['analysis']
    diags = []
    p = os.path.join(OUT, 'author', f'{k8}.diagnoses.json')
    if os.path.exists(p):
        diags = json.load(open(p))[-6:]
    else:                                         # older runs: the diagnoses are in the job log
        allines = open(os.path.join(OUT, 'jobs.log'), errors='replace').read().splitlines()
        jobs = {m.group(1) for l in allines if _g.label(case_id) in l for m in [re.search(r'\[(\w{8})\]', l)] if m}
        lines = [l.strip() for l in allines if any(f'[{j}]' in l for j in jobs)]   # only this crash's jobs
        rx = re.compile(r'repro author: (DIAGNOSIS|learned about the lab|setup fix|STOP)')
        diags = [l.split('] ', 1)[-1] for l in lines if rx.search(l)][-24:]
    facts = []
    fp = os.path.join(OUT, 'author', 'lab_facts.json')
    if os.path.exists(fp):
        facts = json.load(open(fp))
    hooks = sorted(glob.glob(os.path.join(OUT, 'hooks', f'{k8}_*.diff')))[-2:]
    lab_tl = []                                   # what the app REALLY did in the latest runs (not the summaries)
    try:
        from . import author
        dirs = sorted(glob.glob(os.path.join(config.REPO, 'stress_results', '*', f'ns_{k8}_*'))       # phone
                      + glob.glob(os.path.join(config.REPO, 'stress_results', 'lanes', '*', '*', f'ns_{k8}_*')),  # emulator lanes
                      key=os.path.getmtime)[-6:]
        for d in dirs:
            tl = author.app_timeline(d, cap=400)
            keep = [l for l in tl.splitlines() if re.search(r'STEP|MsgAddVideo|ve_on_(stop|resume|pause)|MsgRefreshScreen|abandoned|EGL_BAD|swapBuffers failed|Fatal|am_kill', l)]
            lab_tl.append(f'## {os.path.basename(d)}\n' + '\n'.join(keep[-45:]))
    except Exception as e:
        lab_tl.append(f'(lab timelines unavailable: {e})')
    runs = sorted({os.path.relpath(x, config.REPO) for x in glob.glob(os.path.join(config.REPO, 'stress_results', '*', f'ns_{k8}_*'))
                   + glob.glob(os.path.join(config.REPO, 'stress_results', 'lanes', '*', '*', f'ns_{k8}_*'))})[-12:]
    looper = ''
    try:                                          # looper-wait ANR: the root cause is what made the message thread slow
        from . import author as _au
        if _au.looper_wait_frames(c or {'kind': m.get('kind'), 'frames': m.get('frames')}):
            looper = ('\n\n# LOOPER-WAIT ANR (read before writing the root cause)\n' + _au.LOOPER_RULE
                      + '\nField: engine messages around the moment the queue went busy: '
                      + json.dumps(_au.busy_window(c), default=str)[:2000]
                      + '\nLab: engine message thread at the lab ANR: ' + (c.get('labBusy') or '(not captured)') + '\n')
    except Exception:
        pass
    led = ledger(case_id, c, k8)
    stage = led['stage']
    prompt = ('# Evidence ledger: what the lab PROVED (read this first)\n```json\n' + json.dumps(led, indent=1, default=str)[:24000] + '\n```\n'
              + RULES.format(stage=stage) + looper + '\n'
              + '# Current root cause (written before the lab)\n```json\n'
              + json.dumps({k: a.get(k) for k in ('summary', 'root_cause', 'trigger', 'confidence', 'fix_direction', 'source',
                                                   'diagram_cause', 'diagram_fix')}, indent=1, default=str)[:20000]
              + '\n```\n# Lab diagnoses / notes for this crash (newest last)\n' + '\n'.join(f'- {json.dumps(x, default=str)[:1500]}' for x in diags)
              + '\n\n# Facts Night Shift learned about the app and lab phone\n' + '\n'.join(f'- {f}' for f in facts)
              + f'\n\n# Repro result\nstatus: {c.get("status")}; attempts: {len(c.get("authorAttempts") or [])}; reproLevel: {c.get("reproLevel")}\n'
              + '# Lab run folders (each has steps.log and logcat.txt.gz; you may Read/Grep them, zcat is not available: '
                'use the diagnoses above for their content)\n' + '\n'.join(runs)
              + '\n\n# Lab app timelines of the latest runs, from the phone log (ground truth: trust these over the summaries above)\n'
              + '\n\n'.join(lab_tl)[:30000]
              + '\n\n# Debug hooks used (repro only, never shipped)\n' + '\n'.join(os.path.relpath(h, config.REPO) for h in hooks)
              + '\n\n# Proposed fix patch (not applied)\n```diff\n' + (c.get('patch') or '(none yet)')[:8000] + '\n```\n')
    # blind test: no git (later fix commits), no lab notes or old results; the caller swaps in the shipped crash files
    tools = 'Read,Grep,Glob' if deny else 'Read,Grep,Glob,Bash(git show:*),Bash(git grep:*),Bash(git -C:*)'
    txt = llm.run('root-cause-update', prompt, cfg, os.path.join(OUT, 'analysis'), f'{mref.id}.labupdate', tools=tools,
                  cwd=config.LAB, timeout=1200, deny=deny)
    u = _json(txt)
    if not u.get('root_cause'):
        log('lab update: no usable answer (root cause unchanged)')
        return None
    new = dict(a)
    for k in ('summary', 'root_cause', 'confidence', 'fix_direction', 'trigger', 'timeline', 'hypotheses', 'evidence',
              'diagram_cause', 'diagram_fix', 'lab_update', 'claims'):
        if u.get(k):
            new[k] = u[k]
    if stage == 'not reproduced':                 # runs that never reached the trigger say nothing about the cause
        if u.get('confidence') and u.get('confidence') != a.get('confidence'):
            log(f'lab update: confidence kept at {a.get("confidence")} (the model said {u.get("confidence")}, but no lab run '
                f'reached the crash, so the lab cannot raise or lower it)')
        new['confidence'] = a.get('confidence')
        u['lab_confirmed'] = False
    else:                                         # a run crashed with every field frame: the trigger IS confirmed
        u['lab_confirmed'] = True
    new['lab_stage'] = stage
    vs = list(a.get('versions') or [])
    if not vs:                                    # v1 = the field-only root cause, kept as it was written
        b = a.get('before_lab') or a
        vs.append({'v': 'v1', 'basis': 'field data (Crashlytics events, shipped code)', 'at': a.get('analysedAt') or '',
                   'confidence': b.get('confidence'), 'summary': str(b.get('summary') or '')[:600],
                   'root_cause': str(b.get('root_cause') or '')[:1500]})
    vname = {'verified': 'v3', 'reproduced': 'v2'}.get(stage, f'v{len(vs)}+lab')
    vs = [x for x in vs if x.get('v') != vname]    # a re-run replaces its own version
    vs.append({'v': vname, 'basis': led['basis'], 'at': __import__('datetime').datetime.now().isoformat(timespec='minutes'),
               'confidence': new.get('confidence'), 'summary': str(new.get('summary') or '')[:600],
               'root_cause': str(new.get('root_cause') or '')[:1500], 'changed': str(u.get('lab_update') or '')[:1200],
               'claims': (u.get('claims') or [])[:14]})
    new['versions'] = vs[-6:]
    new['open_questions'] = u.get('open_questions') or []          # answered questions go away
    new.pop('review', None)                                         # the pre-lab self-check no longer describes this text
    import datetime as _dt
    new['lab_updated_at'] = _dt.datetime.now().isoformat(timespec='minutes')
    new['before_lab'] = a.get('before_lab') or {k: a.get(k) for k in ('summary', 'root_cause', 'confidence')}
    mref.update({'analysis': new})
    db.collection('cases').document(case_id).set({'labConfirmed': bool(u.get('lab_confirmed')), 'labStage': stage}, merge=True)
    log(f'lab update: root cause {vname} ({led["basis"]}); confidence {a.get("confidence")} -> {new.get("confidence")}; '
        f'lab confirmed: {bool(u.get("lab_confirmed"))}): {str(u.get("lab_update", ""))[:260]}')
    return u


RULES = """# Rules for this update (stage: {stage})
- Only runs in `hits` (crashed with every field frame) and `verify` (the fix's own guard log fired, or a clean A/B) are
  evidence about the cause. Runs in `did_not_reach_trigger` say NOTHING about it: never lower confidence, never call
  something unconfirmed, because of them. Never say the lab did not do X when a hit shows it did (read the hit calls/steps).
- A hit proves the TRIGGER (the steps/state that crash it). Only a verified fix whose guard fired at the crash moment
  proves the MECHANISM. Say which one each claim has.
- `checkpoints.not_needed` = field details the crash happened WITHOUT: they are not part of the trigger.
- Field facts the lab did not explain stay as open questions. With a same-bug family, the root cause must still explain
  EVERY member, or say which it does not.
- Answer with a `claims` list: [{{"claim": "...", "status": "confirmed|not_needed|unproven|refuted", "by": "hit|verify|field"}}],
  and `lab_update`: 2-4 sentences, what changed from the previous version and why.
"""


def ledger(case_id, c, k8):
    """Everything the lab proved for this crash, split into evidence (hits, verify) and runs that are not evidence."""
    out = {'stage': 'not reproduced', 'basis': 'field data + lab runs that did not reach the crash', 'hits': [], 'verify': None,
           'checkpoints': None, 'did_not_reach_trigger': [], 'family': ''}
    hit_dirs = set()
    try:                                          # engine replay hit
        rp = json.load(open(os.path.join(OUT, 'replay', f'{case_id}.json')))
        if rp.get('hits'):
            out['hits'].append({'kind': 'engine replay (direct engine calls)', 'scenario': rp.get('scenario'),
                                'calls': rp.get('calls'), 'why_written': str(rp.get('why') or '')[:600], 'dir': rp.get('dir')})
            hit_dirs.add(rp.get('dir'))
    except Exception:
        pass
    if c.get('repro_dir') or c.get('labMatch'):    # the UI repro that counted
        h = {'kind': 'real UI repro', 'match': c.get('labMatch'), 'rate': c.get('reproRate'), 'dir': c.get('repro_dir')}
        rd = os.path.join(config.REPO, c.get('repro_dir') or '-')
        st = os.path.join(rd, 'steps.log')
        if os.path.exists(st):
            h['steps_tail'] = ''.join(open(st, errors='replace').readlines()[-30:])[-3500:]
        acts = sorted(glob.glob(os.path.join(rd, 'live_actions.json')))
        if acts:
            h['actions'] = json.load(open(acts[-1]))[:30]
        try:
            from .worker import crash_evidence
            _t, fr, fault, thr = crash_evidence(rd)
            h['dump_top'] = [f.get('func') or f.get('lib') for f in (fr or [])[:6]]
            h['fault'] = fault
        except Exception:
            pass
        out['hits'].append(h)
        hit_dirs.add(c.get('repro_dir'))
    if out['hits']:
        out['stage'], out['basis'] = 'reproduced', 'field data + lab hits (the trigger is confirmed)'
    if c.get('fixVerified'):
        out['verify'] = {'note': c.get('fixNote'), 'patch_head': (c.get('patch') or '')[:3000]}
        out['stage'] = 'verified'
        out['basis'] = 'field data + lab hits + a verified fix' + (' whose guard fired at the crash moment'
                                                                    if 'guard' in str(c.get('fixNote') or '') else '')
    try:
        out['checkpoints'] = json.load(open(os.path.join(OUT, 'author', f'{k8}.hit_checkpoints.json')))
    except Exception:
        pass
    try:
        from . import bugfamily
        out['family'] = bugfamily.prompt_block(case_id)
    except Exception:
        pass
    for x in sorted(glob.glob(os.path.join(config.REPO, 'stress_results', '*', f'ns_{k8}_*')), key=os.path.getmtime)[-14:]:
        rel = os.path.relpath(x, config.REPO)
        if rel in hit_dirs:
            continue
        st = os.path.join(x, 'steps.log')
        last = open(st, errors='replace').read().strip().splitlines()[-1:] if os.path.exists(st) else []
        out['did_not_reach_trigger'].append(f'{os.path.basename(x)}: {(last[0] if last else "?")[-140:]}')
    return out


def quick_repro(db, case_id, hit, log=print):
    """Right after a repro (no LLM, instant): the panel shows v2 = the lab-confirmed trigger. The full rewrite comes
    at the end of the job (v2 text, or v3 when a fix is verified)."""
    for mid in ('m-' + case_id, 'm-play-' + case_id):
        d = db.collection('merged').document(mid).get()
        if d.exists:
            break
    else:
        return
    a = (d.to_dict() or {}).get('analysis') or {}
    if not a.get('root_cause'):
        return
    import datetime as _dt
    vs = list(a.get('versions') or [])
    if not vs:
        vs.append({'v': 'v1', 'basis': 'field data (Crashlytics events, shipped code)', 'at': a.get('analysedAt') or '',
                   'confidence': a.get('confidence'), 'summary': str(a.get('summary') or '')[:600],
                   'root_cause': str(a.get('root_cause') or '')[:1500]})
    trig = {'at': _dt.datetime.now().isoformat(timespec='minutes'), 'match': str(hit.get('labMatch') or hit.get('name') or '')[:400],
            'scenario': hit.get('scenario'), 'rate': f"{hit.get('hits')}/{hit.get('runs')}", 'dir': hit.get('dir')}
    vs = [x for x in vs if x.get('v') != 'v2']
    vs.append({'v': 'v2', 'basis': 'lab hit: the trigger is confirmed (root cause text is rewritten at the end of the job)',
               'at': trig['at'], 'confidence': a.get('confidence'), 'changed': 'Reproduced in the lab: ' + trig['match']})
    d.reference.update({'analysis.lab_trigger': trig, 'analysis.versions': vs[-6:], 'analysis.lab_stage': 'reproduced'})
    log(f'root cause v2 on the board: trigger confirmed by the lab ({trig["match"][:120]})')
