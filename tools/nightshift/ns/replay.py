"""TURBO step 6 - engine replay. Before the repro author taps through the UI, Claude writes 2-3 short recipes that
call the native engine DIRECTLY (debug build only: LabControl 'jni' -> Player's static engine methods) in the order
the root cause says is fatal. They run side by side on the phone + emulator lanes, ~20-40 s each.

A replay that crashes with every field frame is a LEAD, not the proof:
  - the UI repro author gets the exact fatal order ("make the screen send this"), so it needs fewer rounds;
  - the fix check runs the replay many times in seconds before the slower real-tap runs.
The case is still 'reproduced' only by a real-tap recipe, and the board video is always real taps.

Switched by out/experiment.json {"turbo": {"replay": true}}; absent = this module is never called.
Rollback: tools/nightshift/turbo_rollback.py."""
import ast
import datetime as dt
import json
import os
import re

from . import config, llm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out', 'replay')
AUTO = os.path.join(config.REPO, 'tools', 'stress', 'auto')
PLAYER_REL = 'java-common/src/main/java/com/common/myzesty/videoPlayer/Player.kt'
TRIES = 3
WRITE_SEC = 300
OK_TYPES = {'Int', 'Long', 'Float', 'Double', 'Boolean', 'String'}


def engine_api(limit=260):
    """Player's static engine methods a replay can call: name(params): ret, only primitive / String params."""
    try:
        src = open(os.path.join(config.LAB, PLAYER_REL), encoding='utf-8', errors='replace').read()
    except Exception:
        return ''
    out = []
    for m in re.finditer(r'@JvmStatic\s+external\s+fun\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*([\w<>?]+))?', src, re.S):
        name, params, ret = m.group(1), ' '.join(m.group(2).split()), m.group(3) or 'Unit'
        types = re.findall(r':\s*([\w?]+)', params)
        if all(t.rstrip('?') in OK_TYPES for t in types):
            out.append(f'{name}({params}): {ret}')
        if len(out) >= limit:
            break
    return '\n'.join(out)


def applies(case, expect):
    """Native engine crashes only: the field frames name C++ functions (an ANR or a Java crash has no engine order)."""
    return str(case.get('kind') or '').upper() != 'ANR' and any('::' in e for e in expect)


def _path(k8):
    return os.path.join(AUTO, f'{k8}_replay.py')


def load(case_id):
    try:
        return json.load(open(os.path.join(OUT, f'{case_id}.json')))
    except Exception:
        return None


def run(worker, ref, case, merged):
    """-> dict(scenario, calls, hits, runs, dir, why) of the first replay that crashed with every field frame, or None."""
    from . import author
    os.makedirs(OUT, exist_ok=True)
    key = case['id']
    from . import groups as _g
    k8 = _g.k8(key)
    analysis = (merged or {}).get('analysis') or {}
    expect = author.expect_frames(case, analysis)
    if not expect or not applies(case, expect):
        worker.log(ref, 'engine replay: not an engine (C++) crash; skipped')
        return None
    api = engine_api()
    if not api:
        worker.log(ref, 'engine replay: Player.kt engine methods not found; skipped')
        return None
    ctx, _know = author._ctx(case, merged)
    deny = None
    if getattr(worker, '_blind', False):
        deny = [f'{t}({p})' for t in ('Read', 'Grep', 'Glob')
                for p in ('./.git/**', './**/.git/**', './tools/nightshift/**', './stress_results/**', './tools/stress/auto/**',
                          './*.md', './docs/**', './.idea/**', './_to_delete/**', './Claude outputs/**', './bugreport/**',
                          './anr_his_fix/**', './**/*.cpp.*', './**/*.h.*', './**/*.kt.*', './**/*.java.*', './**/*.orig',
                          './**/*.rej', './**/*.bak', './**/*.before-hook')]
    path = _path(k8)
    if os.path.exists(path):                       # a new run starts clean; the old file stays in out/replay
        os.replace(path, os.path.join(OUT, f'{k8}_replay.{dt.datetime.now():%Y%m%d-%H%M%S}.py'))
    t0 = dt.datetime.now()
    history = []
    worker.log(ref, f'engine replay: Claude writes direct engine calls for {_g.label(key)}; a run counts only if the dump shows: {", ".join(expect)}')
    for n in range(1, TRIES + 1):
        name = f'ns_{k8}_rp{n}'
        prompt = (
            f'# Task\nWrite the FAILING REGRESSION TEST for a bug in our own app (MyZesty video editor; our debug build on our own '
            f'lab phone; nothing leaves the lab). Test-first: the test must fail (the app stops with the field error) on '
            f'today\'s build and pass once the fix lands; without it the fix cannot be verified. Users hit the '
            f'crash below; to confirm the root cause and test the fix, write 2 or 3 ENGINE REPLAY recipes `{name}_a`, `{name}_b` '
            f'(and `{name}_c`) that reproduce it by calling our native engine DIRECTLY, in the order the root cause names. Each recipe tests a '
            f'DIFFERENT hypothesis of the engine state / call order.\n'
            f'A run counts ONLY if the crash dump contains every one of: {json.dumps(expect)}'
            + (f' (or the stack of a confirmed same-bug family member: '
               f'{"; ".join(json.dumps(ex) for _c, _t, ex in getattr(worker, "_family", []) or [])})' if getattr(worker, '_family', None) else '')
            + '.\n\n'
            f'# How a replay works (debug build)\n'
            f'ed.jni("call1(args);call2(args);sleep(50);call3(args)", thread="bg"|"main", repeat=1) sends the calls to the '
            f'running app, which invokes Player\'s static engine methods by name, in order, on a background thread '
            f'(thread="main": the UI thread). Pass EVERY parameter (Kotlin defaults do not apply), literals only '
            f'(ints, longs, floats, true/false, strings without quotes or commas). sleep(ms) waits. It returns the result '
            f'lines; if the app crashes, the runner records the crash (do not catch AppFailure).\n'
            f'Setup before the calls: the fastest real app state the crash needs, with the lab shortcuts '
            f'(ed.open_slideshow(n) for a slideshow; the default runner opens the first draft in the editor unless the '
            f'recipe is decorated \'nodraft\'). Keep each recipe under 60 s. After the calls, ed.idle(5).\n'
            f'No code changes, no hooks. Read the JNI side (app/src/main/cpp/JNI/JNI.cpp) and the engine to know what each '
            f'call does and which thread runs it (a Get through MsgLooper is synchronous).\n\n'
            f'# Engine methods you can call (Player.kt)\n```\n{api}\n```\n\n'
            f'# Root cause and field evidence\n```json\n{json.dumps({"analysis": analysis, "field": ctx}, indent=1, default=str)[:45000]}\n```\n\n'
            + (f'# Your previous replays and what the lab did\n' + '\n\n'.join(history[-2:]) + '\n\n' if history else '')
            + f'# Answer format\n1. ONE ```python``` block: `def {name}_a(ed, r):` ... each decorated '
            f'`@scenario(\'nightshift\', \'auto\', \'replay\'[, \'nodraft\'])` with a one-line docstring; use only ed / time / r.\n'
            f'2. ```json``` {{"why": "one sentence: the fatal order you replay"}}\nKeep it short.')
        worker.log(ref, f'engine replay: attempt {n}: asking Claude for {name}')
        txt = llm.run('repro-author', prompt, worker.cfg, OUT, f'{k8}.rp{n}', tools='Read,Grep,Glob', cwd=config.LAB,
                      timeout=WRITE_SEC, deny=deny)
        code, _diff, meta = author._blocks(txt or '')
        names = []
        if code:
            try:
                defined = {f.name for f in ast.parse(code).body if isinstance(f, ast.FunctionDef)}
            except SyntaxError:
                defined = set()
            names = [f'{name}_{x}' for x in 'abcd' if f'{name}_{x}' in defined]
        err = (author._check_code(code, names[0]) if names else f'the code must define {name}_a(ed, r)') if code else 'no python block'
        if not err and 'ed.jni(' not in code:
            err = 'a replay recipe must call ed.jni(...)'
        if err == 'no python block':                 # the model stopped short of the test: say what it is for
            err = ('no python block. The previous answer gave fix advice instead of the test. The fix needs this failing '
                   'test first: answer ONLY in the required format (python block + json); the fix is written in a later step')
        if err:
            history.append(f'## {name}: rejected before running: {err}')
            worker.log(ref, f'engine replay: {name} rejected: {err}')
            continue
        prev = open(path, encoding='utf-8').read() if os.path.exists(path) else f'# Night Shift engine replays for {key} (turbo)\n'
        open(path, 'w', encoding='utf-8').write(prev.rstrip() + f'\n\n\n# {dt.datetime.now():%Y-%m-%d %H:%M} attempt {n}\n{code.strip()}\n')
        sts = [{'scenario': nm, 'repeat': 1, 'name': nm, 'fast': True} for nm in names]
        lanes = list(getattr(worker, '_lane_serials', None) or [])
        results = []
        while sts:                                  # one recipe per device at a time
            group, sts = sts[:1 + len(lanes)], sts[1 + len(lanes):]
            rs = worker._ladder_multi(ref, group, expect) if lanes else \
                [dict(worker._ladder_step(ref, group[0], expect))]
            for st, r1 in zip(group, rs):
                results.append((st['scenario'], r1))
                worker.log(ref, f'engine replay: {st["scenario"]}: {(("CRASHED as same-bug family member " + str(r1["family_hit"]) + ", not the exact field frames") if r1.get("family_hit") else "CRASHED with every field frame") if r1.get("hits") else r1.get("result")}'
                           + (f'; {r1["why"]}' if r1.get('why') and not r1.get('hits') else ''))
            hit = next(((nm, r1) for nm, r1 in results if r1.get('hits')), None)
            if hit:
                break
        hit = next(((nm, r1) for nm, r1 in results if r1.get('hits')), None)
        if hit:
            nm, r1 = hit
            calls = re.findall(r'ed\.jni\(\s*[\'"]([^\'"]+)', code[code.find(f'def {nm}('):])[:3]
            rp = {'scenario': nm, 'calls': calls, 'why': meta.get('why', ''), 'hits': r1.get('hits'), 'runs': r1.get('runs'),
                  'dir': r1.get('dir', ''), 'expect': expect, 'minutes': round((dt.datetime.now() - t0).total_seconds() / 60, 1)}
            json.dump(rp, open(os.path.join(OUT, f'{key}.json'), 'w'), indent=1)
            try:
                worker.db.collection('cases').document(key).set({'engineReplay': rp}, merge=True)
            except Exception:
                pass
            worker.log(ref, f'ENGINE REPLAY HIT in {rp["minutes"]} min: {nm}: {" | ".join(calls)[:200]} (a lead, not the proof: '
                            f'the real-tap repro comes next)')
            return rp
        fb = '\n'.join(f'- {nm}: {r1.get("result")}; {r1.get("why", "")}\n'
                       + author._feedback((r1.get('dirs') or [''])[-1])[:2500] for nm, r1 in results)
        history.append(f'## {name}\n```python\n{code.strip()[:4000]}\n```\n{fb}')
    worker.log(ref, f'engine replay: no replay crashed with every field frame in {TRIES} attempts; the UI repro author goes on as usual')
    return None


def hint(rp):
    """The fatal order a replay proved, for the UI repro author's prompt."""
    if not rp:
        return ''
    return ('# ENGINE REPLAY RESULT (turbo): calling the engine directly in this order crashed with every field frame\n'
            f'Replay {rp["scenario"]}: {" | ".join(rp.get("calls") or [])}\nWhy: {rp.get("why", "")}\n'
            'Your recipes must make the REAL app send this order through the UI (real taps / real device events), '
            'not call ed.jni: a replay is a lead, the repro must be natural.\n\n')
