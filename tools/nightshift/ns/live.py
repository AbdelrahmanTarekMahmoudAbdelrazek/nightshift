"""TURBO - live repro agent, worker side. Opus writes a short plan from the root cause, the field checkpoints and the
engine replay's proven fatal order; the scenario ns_live (tools/stress/auto/_live_agent.py) then drives the phone one
action at a time with a fast model looking at the screen and the app log after every action. A blind script loses a
whole 7-10 min round to one wrong tap; the live agent corrects it in seconds.

A hit (crash with every field frame, natural actions only) becomes a normal recipe `ns_<k8>_live<n>` that replays the
same actions with the same pauses: the recorded proof run, the fix check and the next Reproduce all use that recipe.
No hit in the attempts -> the classic repro author runs as before.

Switched by out/experiment.json {"turbo": {"live": true}}. Rollback: tools/nightshift/turbo_rollback.py."""
import datetime as dt
import glob
import json
import os
import re

from . import config, llm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out', 'live')
AUTO = os.path.join(config.REPO, 'tools', 'stress', 'auto')
PLAN_SEC = 300


def _phone():
    import subprocess
    try:
        g = lambda k: subprocess.run(['adb', 'shell', 'getprop', k], capture_output=True, text=True, timeout=10).stdout.strip()
        return f'{g("ro.product.manufacturer")} {g("ro.product.model")}, Android {g("ro.build.version.release")}'
    except Exception:
        return 'a real Android phone'


def _plan(worker, ref, case, ctx, cps, expect, smap, rp, k8, history, deny):
    from . import replay as _rp
    prompt = ('# Task\nQA bug reproduction for our own app (MyZesty video editor, debug build on our lab phone, '
              f'{_phone()}). Users hit the crash below; the team needs a reliable reproduction to verify the fix. A fast QA '
              'driver will act ONE step at a time, seeing the screen ids and the app log after each step. Write its PLAN: the '
              'shortest NATURAL path (real user actions and device events only) that reproduces the reported crash.\n'
              f'A run counts only if the crash dump has every one of: {json.dumps(expect)}'
              + (f' (or the stack of a confirmed same-bug family member: '
                 f'{"; ".join(json.dumps(ex) for _c, _t, ex in getattr(worker, "_family", []) or [])})' if getattr(worker, '_family', None) else '')
              + '.\n\n'
              + _rp.hint(rp)
              + (('# ANR background (general Android knowledge, not about this app)\n'
                  'An ANR whose main thread is IDLE in the dump (nativePollOnce / Looper::pollOnce) usually is a timeout of a '
                  'broadcast, service or job that was ALREADY over when the dump was taken, often while the process was in the '
                  'background or cold-starting (no UI). Android\'s ANR guide: for a broadcast receiver with an idle main thread, look for a '
                  'receiver that called goAsync() and whose worker never got to finish() in time (worker pool blocked or slow, or a '
                  'path without finish()); a late stack dump also leaves main idle. Input-dispatch ANRs need a visible window. '
                  'Background triggers you have: '
                  'push (an FCM message arrives, also to a stopped app = cold start), run_jobs, doze, trim_memory, busy_storage (slow '
                  'disk for every thread), stalled_network (a server that never answers, reachable even when the phone is offline); '
                  'slow_phone makes '
                  'this fast lab phone as slow as low-end field phones (timeouts: foreground broadcast 10 s, background broadcast '
                  '60 s, service 20 s; phone makers may stretch them).\n\n')
                 if any(('pollOnce' in str(e) or 'nativePollOnce' in str(e)) for e in expect) else '')
              + f'# Field evidence and root cause\n```json\n{json.dumps(ctx, indent=1, default=str)[:40000]}\n```\n'
              + (f'# Field checkpoints, in order\n```json\n{json.dumps(cps, indent=1)}\n```\n' if cps else '')
              + (f'# Screen map: ids seen on the lab phone with this build\n```\n{smap[:6000]}\n```\n' if smap else '')
              + '# Driver actions\ntap(target id:/text:/textc:/desc:), tap_xy, back, home, resume, rotate(landscape), dark_mode(on), '
                'background(seconds, pressure), open_slideshow(n), slideshow_add_media(n), fresh_video(tag, duration_s), '
                'when_log(pattern regex, then rotate|rotate_back|home|back|dark_on|dark_off|none, timeout), run_jobs (the app\'s '
                'scheduled background jobs run now), push(title, body, data, high_priority: an FCM push arrives), slow_phone(level 0-48: CPU busy loops), stalled_network(on: a URL whose connections hang), kill_bg (the system reclaims the cached app), reclaim_activities(on: low-RAM phone, an activity is destroyed as soon as it leaves the screen while the process lives; a real field condition, allowed in a natural repro; it goes through the Settings app: open_draft first, then switch it on, then resume; never create projects through the gallery with it on), open_draft (the lab test project in the main editor), doze(on), trim_memory(level), idle(seconds), give_up.\n'
                'arm(pattern, then, timeout): the same watch in the BACKGROUND, set BEFORE the action that prints the line '
                '(arm, then open_slideshow): a when_log sent after that action is too late.\n'
                'when_log/arm are how timing races are hit: the driver is slow (seconds per step), they react in ~0.3 s. '
                'Use log patterns you READ in the code (exact Log tag/message), not guesses.\n\n'
              + ('# Earlier live attempts and what the phone did\n' + '\n\n'.join(history[-2:]) + '\n\n' if history else '')
              + 'Read the app code (Read/Grep) for the exact screens and log lines. Answer ONE ```json block:\n'
                '{"goal": "...", "steps": ["1. ...", "2. ..."], "trigger": "the exact moment + the when_log pattern to use", '
                '"log_markers": {"checkpoint 1": "<regex>", ...}, "avoid": ["..."], "max_tries_of_trigger": 3}')
    txt = llm.run('repro-author', prompt, worker.cfg, OUT, f'{k8}.plan{len(history) + 1}', tools='Read,Grep,Glob',
                  cwd=config.LAB, timeout=PLAN_SEC, deny=deny)
    m = re.findall(r'```json\n(.*?)```', txt or '', re.S)
    try:
        return json.loads(m[-1]) if m else None
    except ValueError:
        return None


def _recipe(k8, n, acts, why, pin='', snap=''):
    """Write the recipe that replays a successful live run (same actions; model think-time pauses capped). pin = the id
    of the project that run used: the replay opens exactly that project (My Projects #0 changes when the test draft is
    remade, and the replay then ran on a project without the field's state - 2026-10-21)."""
    name = f'ns_{k8}_live{n}'
    path = os.path.join(AUTO, f'{k8}_live.py')
    prev = open(path, encoding='utf-8').read() if os.path.exists(path) else f'# Night Shift live-agent recipes for {k8} (turbo)\n'
    import pprint
    body = pprint.pformat([{k: a.get(k) for k in ('do', 'args', 't', 'result')} for a in acts], width=110)   # a Python literal
    code = (f"\n\n@scenario('nightshift', 'auto', 'nodraft')\ndef {name}(ed, r):\n"
            f"    \"\"\"{why[:150].replace(chr(34), chr(39))} (live agent run, replayed)\"\"\"\n"
            + (f"    ed._pin_draft = {pin!r}   # the project the live run reproduced on\n" if pin else '')
            + (f"    ed._pin_snapshot = {snap!r}   # projects restored to the state the live run started from\n" if snap else '')
            + f"    live_replay(ed, {body.replace(chr(10), chr(10) + '    ')})\n")
    open(path, 'w', encoding='utf-8').write(prev.rstrip() + f'\n\n# {dt.datetime.now():%Y-%m-%d %H:%M}' + code)
    return name


def run(worker, ref, case, merged, rp=None):
    """-> hit dict (like the repro author's) or None."""
    from . import author
    os.makedirs(OUT, exist_ok=True)
    key = case['id']
    from . import groups as _g
    k8 = _g.k8(key)
    analysis = (merged or {}).get('analysis') or {}
    expect = author.expect_frames(case, analysis)
    if not expect:
        return None
    tb = worker._turbo()
    tries = int(tb.get('live_tries') or 2)
    ctx, _know = author._ctx(case, merged)
    smap = author.screen_map(worker, ref)
    deny = None
    if getattr(worker, '_blind', False):
        deny = [f'{t}({p})' for t in ('Read', 'Grep', 'Glob')
                for p in ('./.git/**', './**/.git/**', './tools/nightshift/**', './stress_results/**', './tools/stress/auto/**',
                          './*.md', './docs/**', './.idea/**', './_to_delete/**', './Claude outputs/**', './bugreport/**',
                          './anr_his_fix/**', './**/*.cpp.*', './**/*.h.*', './**/*.kt.*', './**/*.java.*', './**/*.orig',
                          './**/*.rej', './**/*.bak', './**/*.before-hook')]
    cpp = os.path.join(author.OUT, f'{k8}.checkpoints.json')
    cps = json.load(open(cpp)) if os.path.exists(cpp) else author.make_checkpoints(worker, ref, ctx, k8, deny)
    t0 = dt.datetime.now()
    history = []
    for n in range(1, tries + 1):
        worker.log(ref, f'live agent: attempt {n}: Opus writes the plan')
        plan = _plan(worker, ref, case, ctx, cps, expect, smap, rp, k8, history, deny)
        if not plan:
            worker.log(ref, 'live agent: no usable plan; the classic repro author takes over')
            return None
        pp = os.path.abspath(os.path.join(OUT, f'{k8}.plan{n}.json'))
        json.dump(plan, open(pp, 'w'), indent=1)
        worker.log(ref, f'live agent: plan: {str(plan.get("goal", ""))[:160]} | trigger: {str(plan.get("trigger", ""))[:140]}')
        snap = f'live_{k8}_{n}'
        env = (f'ZESTY_LIVE_PLAN={pp} ZESTY_LIVE_SNAP={snap} ZESTY_LIVE_MODEL={tb.get("live_driver") or "haiku"} '
               f'ZESTY_LIVE_MAX_S={int(tb.get("live_max_s") or 420)} ')
        res = worker._ladder_step(ref, {'scenario': 'ns_live', 'repeat': 1, 'name': 'ns_live', 'env': env, 'phone_only': True,
                                        'max_s': int(tb.get('live_max_s') or 420) + 60}, expect)
        dirs = res.get('dirs') or []
        logs = sorted(glob.glob(os.path.join(dirs[-1], '*', 'live_actions.json'))) if dirs else []
        acts = json.load(open(logs[-1])) if logs else []
        worker.log(ref, f'live agent: attempt {n}: {len(acts)} actions; ' + ((f"CRASHED as a same-bug family member ({res['family_hit']}), not this card's exact frames" if res.get('family_hit')
                                                                               else 'CRASHED with every field frame') if res.get('hits')
                                                                             else f'{res.get("result")}; {res.get("why", "")}'))
        if res.get('hits') and acts:
            pin = ''
            for st_ in sorted(glob.glob(os.path.join(dirs[-1], '*', 'steps.log'))):
                ids = re.findall(r'lab control: ok open_draft\S* index=\d+ id=([0-9a-f-]{8,})', open(st_, errors='replace').read())
                pin = ids[-1] if ids else pin
            win = _recipe(k8, n, acts, str(plan.get('goal', 'live agent repro')), pin, snap)
            if pin:
                worker.log(ref, f'live agent: the recipe opens the same project the live run used ({pin[:8]})')
            step = {'level': 3, 'name': f'{win}: {str(plan.get("goal", ""))[:150]}', 'scenario': win, 'repeat': 2,
                    'natural': True, 'author': True, 'stat_runs': 1, 'stat_hits': 1}
            author.register(key, step, expect)
            mins = round((dt.datetime.now() - t0).total_seconds() / 60, 1)
            worker.log(ref, f'live agent: REPRODUCED naturally in {mins} min ({len(acts)} actions); recipe {win} registered')
            hit = dict(res, level=3, name=step['name'], scenario=win, natural=True, author=True)
            hit.pop('dirs', None)
            return hit
        tl = author.app_timeline(glob.glob(os.path.join(dirs[-1], '*'))[-1], cap=80) if dirs and glob.glob(os.path.join(dirs[-1], '*')) else ''
        mainst = ''
        for tr in sorted(glob.glob(os.path.join(dirs[-1], '*', 'anr_trace.txt'))) if dirs else []:
            m_ = re.search(r'"main"[^\n]*\n(?:[^\n]+\n){0,30}', open(tr, errors='replace').read())
            if m_:                                   # an ANR happened: what was the MAIN thread doing at the dump?
                mainst = '\n'.join(l for l in m_.group(0).splitlines() if l.strip().startswith(('at ', '"main"', '- ')))[:1500]
        history.append(f'## live attempt {n}\nplan: {json.dumps(plan)[:2500]}\n'
                       + (f'main thread in the lab ANR dump (compare with the field):\n{mainst}\n' if mainst else '')
                       + 'actions:\n'
                       + '\n'.join(f'- {a.get("do")} {json.dumps(a.get("args", {}))} -> {a.get("result", "")}' for a in acts[-30:])
                       + f'\nresult: {res.get("result")}; {res.get("why", "")}\napp timeline:\n{tl[:5000]}')
    worker.log(ref, f'live agent: no natural repro in {tries} attempts; the classic repro author takes over')
    return None
