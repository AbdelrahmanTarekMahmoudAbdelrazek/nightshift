"""Real-tap repro FROM the engine repro (28 Oct). The old way made an agent guess its way through the UI from zero;
this one works backwards from what is already proven:

  1. the engine replay knows the exact engine calls that crash,
  2. the FULL field log of the user (all ~400 lines: every engine message and every tap event, not the 25 the case
     file used to keep) shows which tap sent which engine message, in order,
  3. the Kotlin map shows which Kotlin code (button, fragment) sends each engine call.

Claude turns that into a tap script in the scenario harness, with a CHECKPOINT after every tap: the engine message
the field log shows after that tap must appear in the app log (ed.require_log) before the next tap, so a run that
went wrong is caught at the step that went wrong. Three variants per attempt:
  a) FULL   - the user's own path, real taps only;
  b) HYBRID - a prerequisite nobody can tap yet (e.g. the app's clip list drifting from the engine's) is made with a
              lab shortcut (ed.jni / ed.lab), marked `# HYBRID`, and the TRIGGER is always a real tap;
  c) a variant of a) with the timing/slow-phone switches the field warnings call for.
No gallery picker: the project comes from a lab fixture or the lab test draft. Time box: tap_budget_min (default 30).
A hit is registered like any repro (FULL = natural, HYBRID = not natural, named 'hybrid: ...') and gets the video."""
import datetime as dt
import glob
import json
import os
import re

from . import config, llm

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'tapflow')
NOISE = re.compile(r'TIMEOUT|fallback|exceeds frame_duration|glTask drain|AUD split|ev_poll|trim_memory_\d+ ')

def _deny(worker):
    """Blind test: the same read block as the root cause / fix / repro author (.git, lab notes, old results, earlier
    auto scenarios and stress_results of this crash). Normal runs: no block."""
    if not getattr(worker, '_blind', False):
        return None
    import sys
    return list(getattr(sys.modules.get(type(worker).__module__), 'BLIND_READ_DENY', None) or []) or None


SWITCHES = """App screens and how to reach them WITHOUT the gallery picker (match the screen the field events name):
  regular editor (ve_* events): ed.open_fixture(<key>) or ed.open_draft()
  Wizard editor (we_* events, reached in the app ONLY from Quick Cut -> template Edit -> Advanced Edit): ed.open_wizard(n),
    then ed.wizard_select(i), ed.wizard_drag(i, j), ed.wizard_delete(i), ed.wizard_thumbs()
  SlideShow (isSlideShow, no Advanced Edit): ed.open_slideshow(n), ed.slideshow_add_media(n)
  Quick Cut (qc_* events, template page; Edit -> media page -> Advanced Edit = Wizard): ed.open_quickcut(n)
Slow-phone / timing switches you may use (set before the trigger, reset in a finally):
  ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')   playback audio callback ~150 ms slower (field 'AUD callback OVERRUN')
  ed.dev.setprop('debug.zesty.hook.audio_probe', '1')       logs 'NS_PROBE audio_cb' while playback audio really runs
  ed.dev.slow_phone(level)  (0-48, busy CPU loops: a low-end phone; 0 = off)          ed.trim_memory(level)
  ed.background(seconds, pressure=True) / ed.rotate(cycles) / ed.dont_keep_activities(on)
Lab shortcuts (HYBRID prerequisites only, never the trigger): ed.jni('call(args);sleep(ms);...') sends engine calls
directly (the same names the engine replay used); ed.lab(cmd) runs the app's own code for setup (open drafts, add media)."""


def field_timeline(case, cap=170):
    """The user's last minutes: every engine log line and every tap event of the sample event, oldest first."""
    raw = os.path.join(config.REPO, 'tools/nightshift/out/raw', case['id'].split('~')[0], 'events.json')
    lines = []
    try:
        ev = json.load(open(raw))
        ev = ev if isinstance(ev, list) else (ev.get('events') or [])
        e = ev[0] if ev else {}
        for l in e.get('logs') or []:
            lines.append((l.get('logTime') or l.get('timestamp') or '', str(l.get('message') or l.get('text') or '')))
        for b in e.get('breadcrumbs') or []:
            p = b.get('params') or {}
            p = {k: v for k, v in p.items() if k not in ('device_id',)}
            lines.append((b.get('eventTime') or b.get('timestamp') or '', f"[TAP/EVENT] {b.get('title') or b.get('name')} {json.dumps(p)[:160]}"))
    except Exception:
        pass
    if not lines:                                     # older case: whatever the case file kept
        return '\n'.join(reversed([str(x) for x in (case.get('breadcrumbs') or [])]))
    lines.sort()
    src = re.compile(r'^file: (\S+), line: \d+\s+')
    keep = [t[11:23] + ' ' + src.sub(r'[\1] ', m) for t, m in lines if m and not NOISE.search(m)]
    return '\n'.join(keep[-cap:])


def _engine_block(rp):
    if not rp:
        return '(no engine replay hit for this crash)'
    steps = '\n'.join(f"  {s.get('kind')}: {s.get('text')}" for s in (rp.get('steps') or [])[:40])
    code = ((rp.get('script') or {}).get('code') or '')[:4000]
    return (f"Engine replay {rp.get('scenario')} crashed with every field frame ({rp.get('hits')}/{rp.get('runs')}).\n"
            f"Why: {rp.get('why', '')}\nSteps it sent:\n{steps}\n```python\n{code}\n```")


def _prompt(case, merged, rp, ctx, api, examples, smap, kmap, facts, history, k8, n):
    return ('# Task: reproduce this crash on the lab phone with REAL TAPS, working backwards from the engine repro\n'
            'The engine replay below already crashed the field way by sending engine calls directly. Your job: make the '
            'app SEND THOSE SAME engine calls through its own UI. For each engine call of the replay, find the tap that '
            'sends it: in the FIELD TIMELINE (a [TAP/EVENT] line right before the engine message) and in the KOTLIN MAP '
            '(which Kotlin code / button calls it). Before writing steps, find in the Kotlin code (Read/Grep the folders '
            'of the map) HOW the bad state can arise (e.g. how the app\'s clip list can drift from the engine\'s), and turn '
            'that into steps.\n\n'
            '# Write ONE python module with exactly three scenario functions (decorator `@scenario(\'nightshift\', \'auto\', '
            f'\'tapflow\'[, \'nodraft\'])`, signature `(ed, r)`; add \'nodraft\' when the scenario opens its own screen first '
            '(ed.open_wizard / ed.open_slideshow / ed.open_fixture), otherwise the runner opens the test draft before it), '
            f'named tf_{k8}_{n}_a, tf_{k8}_{n}_b, tf_{k8}_{n}_c:\n'
            '  a) FULL: the user\'s own path, real taps only (docstring starts with "FULL:")\n'
            '  b) HYBRID: any prerequisite you cannot tap yet is made with a lab shortcut, each such line marked `# HYBRID`; '
            'the TRIGGER (the tap whose engine message crashes) is ALWAYS a real tap (docstring starts with "HYBRID:")\n'
            '  c) FULL or HYBRID variant with the timing / slow-phone switches the field warnings call for\n'
            'RULES: (1) after EVERY tap, call ed.require_log(<regex of the engine message the field log shows after that '
            'tap>, timeout=..., why=\'<step>\') so a wrong step stops the run at once; (2) never use the gallery picker: start '
            'from ed.open_fixture(<key>) or ed.open_draft(); add media with tested building blocks only; (3) use only '
            'methods of the harness API below, ids/texts from the screen map; (4) keep each function under ~60 lines; '
            '(5) do not catch the crash: the monitor reports it.\n'
            'LAUNCH / LIFECYCLE CRASHES (29 Oct): when the root cause or the stack says the crash happens while a screen is '
            'CREATED, LAUNCHED or RESTORED (performLaunchActivity, onCreate/onRestoreInstanceState in the stack, a missing '
            'or null intent extra or argument, process death, a deep link or notification) rather than after a tap, do NOT '
            'start with tap scenarios. Write instead: a) LIFECYCLE: reach that screen with real taps, then '
            'ed.restore_from_recents() (process death + Android restores the screen); b) DIRECT LAUNCH: '
            'ed.start_activity(<the activity>, extras=\'\') with NO extras, and once more with each extra empty (it works for '
            'non-exported screens too: the full-app lab build has a lab door, no root needed); '
            'c) ed.dont_keep_activities(True), open the screen, leave it (home / another app) and come back, then '
            'ed.dont_keep_activities(False) in a finally. Say in the plan which launch path the field evidence points to.\n\n'
            "SCREENS BEHIND FLOWS THE LAB CANNOT REPLAY (29 Oct): when the field user reached the crashing screen through a first-run / onboarding / login / paywall / notification / share-intent flow, do not tap through that flow. Grep the app for the code that starts that screen (startActivity / Intent(... , <Screen>::class.java) / putExtra) and open it directly with ed.start_activity('<full.Activity.Class>', extras='--es key \"value\" --ei count 3', expect_crash=False) using the SAME extras that code passes (raw am extras: --es string, --ei int, --ez boolean), then do the field's taps from there. It works for non-exported screens in the full-app lab build (lab door, no root). If one run fails to reach a screen by taps because of such a flow, switch to the direct launch in the next recipe; never repeat the same tap path.\n\n"
            f'# ENGINE REPRO (proven)\n{_engine_block(rp)}\n\n'
            f'# FIELD TIMELINE (the user, oldest first; [TAP/EVENT] = a tap or screen event; [File.cpp] = engine log)\n```\n{field_timeline(case)}\n```\n\n'
            f'{kmap}\n'
            f'# HARNESS API\n```\n{api}\n```\n# Examples of working scenarios\n```python\n{examples[:9000]}\n```\n'
            f'# SCREEN MAP (ids and texts per screen)\n{smap}\n\n{SWITCHES}\n{_hooklib()}\n\n'
            + ('# Facts about the lab phone and app\n' + '\n'.join(f'- {f}' for f in facts[-25:]) + '\n\n' if facts else '')
            + (f'# Case context\n```json\n{json.dumps(ctx, default=str)[:12000]}\n```\n')
            + ('# Earlier attempts (fix exactly what they say)\n' + '\n\n'.join(history[-2:]) + '\n\n' if history else '')
            + '# Answer: a one-paragraph plan, then the module in ONE ```python block.')


def run(worker, ref, case, merged, rp=None):
    """-> hit dict (author format) or None."""
    from . import author
    tb = worker._turbo() or {}
    budget = float(tb.get('tap_budget_min') or 30)
    tries = int(tb.get('tap_tries') or 3)
    os.makedirs(OUT, exist_ok=True)
    from . import groups as _g
    k8 = _g.k8(case['id'])
    analysis = (merged or {}).get('analysis') or {}
    expect = author.expect_frames(case, analysis)
    if not expect:
        return None
    ctx, _ = author._ctx(case, merged)
    api, examples, _other = author.harness_api()
    smap = author.screen_map(worker, ref)
    try:
        from . import kotlinmap
        kmap = kotlinmap.cached(worker.cfg, case, merged, lambda t: worker.log(ref, t))[0]
    except Exception:
        kmap = ''
    facts = author.lab_facts()
    # 1 Nov: the project this crash needs, built ONCE as a lab fixture before the tap scripts (they opened another
    # crash's fixture that no longer existed and every run stopped in 8 s on the developer menu)
    try:
        if not author._fixtures(k8):
            cps = author.make_checkpoints(worker, ref, ctx, k8, _deny(worker))
            what = author.build_fixture(worker, ref, case, ctx, cps, k8, api, smap, expect, _deny(worker))
            if what:
                worker.log(ref, f'tap repro: lab fixture "{k8}" for this crash: {what[:160]}')
    except Exception as e:
        worker.log(ref, f'tap repro: fixture build skipped: {str(e)[:160]}')
    live = author.live_fixtures()
    facts = facts + ['LAB FIXTURES THAT EXIST NOW (ed.open_fixture accepts ONLY these keys): '
                     + ('; '.join(f'"{k}" = {w}' for k, w in live.items()) if live else 'none')
                     + (f'. "{k8}" is the project THIS crash needs: start from it.' if k8 in live else
                        '. None was built for this crash: start from ed.open_draft() and build what the field had with '
                        'the harness building blocks (HYBRID may use ed.jni(...) for that setup).')]
    t0 = dt.datetime.now()
    history, attempts = [], []
    rd = os.path.join(config.REPO, worker.cfg['lab']['results_dir'])
    for n in range(1, tries + 1):
        if (dt.datetime.now() - t0).total_seconds() > budget * 60:
            worker.log(ref, f'tap repro: time box of {budget:.0f} min reached')
            break
        worker.log(ref, f'tap repro: attempt {n}: tap script from the engine repro + the full field log (FULL / HYBRID / timing)')
        ans = llm.run('repro-author', _prompt(case, merged, rp, ctx, api, examples, smap, kmap, facts, history, k8, n),
                      worker.cfg, OUT, f'{k8}.tap{n}', tools='Read,Grep,Glob', cwd=config.REPO, timeout=1200,
                      deny=_deny(worker))
        m = re.findall(r'```python\n(.*?)```', ans or '', re.S)
        if not m:
            history.append(f'## attempt {n}: no python block in the answer')
            continue
        code = m[-1]
        names = re.findall(r'^def (tf_\w+)\(ed, r\)', code, re.M)
        if not names:
            history.append(f'## attempt {n}: no tf_* scenario functions found')
            continue
        bad = next((nm for nm in names if author._check_code(code, nm)), None)
        if bad:
            history.append(f'## attempt {n}: code check failed for {bad}: {author._check_code(code, bad)}')
            continue
        path = os.path.join(author.AUTO, f'{k8}_tap.py')
        head = f'# Night Shift tap repros for {case["id"]} (from the engine repro + full field log)\n'
        prev = open(path).read() if os.path.exists(path) else head
        open(path, 'w').write(prev + f'\n\n# {dt.datetime.now():%Y-%m-%d %H:%M} attempt {n}\n' + code.strip() + '\n')
        plan = (ans or '').split('```python')[0].strip()[:600]
        worker.log(ref, f'tap repro: plan: {plan}')
        tried = []
        for nm in names:
            if (dt.datetime.now() - t0).total_seconds() > budget * 60:
                break
            before = set(glob.glob(os.path.join(rd, '*')))
            r1 = worker._ladder_step(ref, {'scenario': nm, 'repeat': 1, 'name': nm, 'fast': True}, expect)
            got = sorted(set(glob.glob(os.path.join(rd, '*'))) - before)
            doc = (re.search(rf'def {nm}\(ed, r\):\s+"""(.*?)"""', code, re.S) or [None, ''])[1].strip()
            hybrid = doc.upper().startswith('HYBRID') or '# HYBRID' in (re.search(rf'def {nm}\(ed, r\):.*?(?=\ndef |\Z)', code, re.S) or [''])[0]
            worker.log(ref, f'tap repro: {nm} ({"HYBRID" if hybrid else "FULL"}): {r1.get("result")} ({r1.get("hits")}/{r1.get("runs")})'
                       + (f'; {r1["why"]}' if r1.get('why') else ''))
            tried.append((nm, r1, got, hybrid, doc))
            if r1.get('hits'):
                res = dict(r1, scenario=nm, level=2 if not hybrid else 4, natural=not hybrid, author=True, tapflow=True,
                           name=(('hybrid: ' if hybrid else '') + f'{nm}: {doc.splitlines()[0] if doc else "tap repro"}')[:200])
                attempts.append(res)
                step = {'level': res['level'], 'name': res['name'], 'scenario': nm, 'repeat': 2, 'natural': res['natural'],
                        'author': True, 'stat_runs': int(res.get('runs') or 1), 'stat_hits': int(res.get('hits') or 1)}
                author.register(case['id'], step, expect)
                worker.log(ref, f'tap repro: REPRODUCED with {"a HYBRID setup + real-tap trigger" if hybrid else "real taps only"} '
                                f'in {(dt.datetime.now() - t0).total_seconds() / 60:.1f} min ({nm}); registered for this crash')
                try:
                    worker.db.collection('cases').document(case['id']).set(
                        {'tapRepro': {'scenario': nm, 'hybrid': hybrid, 'doc': doc[:400], 'minutes': round((dt.datetime.now() - t0).total_seconds() / 60, 1)}},
                        merge=True)
                except Exception:
                    pass
                return author._finish(worker, ref, case, attempts, res)
            attempts.append(dict(r1, scenario=nm, level=2 if not hybrid else 4, natural=not hybrid, author=True,
                                 name=(('hybrid: ' if hybrid else '') + nm)[:200]))
        fb = '\n\n'.join(f'### {nm} ({"HYBRID" if hy else "FULL"}): {r1.get("result")}; {r1.get("why") or ""}\n'
                         + author._feedback(got[0] if got else '') for nm, r1, got, hy, _d in tried)
        history.append(f'## attempt {n}\n```python\n{code[:7000]}\n```\nWhat the lab phone did:\n{fb[:14000]}')
    author._finish(worker, ref, case, attempts, None)
    worker.log(ref, f'tap repro: no real-tap repro in {(dt.datetime.now() - t0).total_seconds() / 60:.0f} min')
    return None


def _hooklib():
    """Every ready-made hook in hooklib/ (2 Nov), not only the two listed in SWITCHES."""
    try:
        from . import author as _a
        hc = _a.hook_catalog()
        return ('All ready-made hooks in this build (hook-assisted when used):\n' + hc) if hc else ''
    except Exception:
        return ''
