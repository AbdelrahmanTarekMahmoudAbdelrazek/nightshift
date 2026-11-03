"""Night Shift repairs its OWN phone tools (3 Nov), with a test and a human review before teammates get it.

Before: a repro step that failed inside the shared harness (tools/stress/zesty.py), e.g. select_overlay's
"no overlay bar answered a tap", could only be worked around in Night Shift's own recipes; the helper itself stayed
broken for every crash until a person fixed it. Night Shift even diagnosed the cause ("bars only answer while the
overlay panel is open") and could not act on it.

Now:
  1. note(detail, run_dir): every automation error of a lab run is matched to the zesty.py function that raised it
     (by the literal text of its `raise UIError(...)`); recipe-level errors (raised by Night Shift's own scripts) are
     not the harness's fault and are ignored. Counted in out/harness/failures.json.
  2. maybe_repair(worker, ref, key): when one harness function failed the same way >= 3 times (and was not tried in the
     last 24 h, max 2 tries per failure), Claude reads that function, the failing runs (steps, screen dumps) and the
     lab facts, and writes (a) a patch to THAT function only and (b) a short setup-only test scenario that exercises it.
  3. The patch is applied on this Mac, the test runs on the lab phone. Pass -> kept, listed as NOT REVIEWED in
     out/harness/pending.json; fail -> reverted. Nothing is committed or pushed.
  4. kit_build.py ships the last REVIEWED zesty.py while anything is pending, so teammates never get an unreviewed
     change. A person decides:  python3 tools/nightshift/ns/ns/harnessfix.py list | show <id> | approve <id> | reject <id>
"""
import ast
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from ns import config  # noqa: E402

OUT = os.path.join(HERE, 'out', 'harness')
FAIL = os.path.join(OUT, 'failures.json')
PEND = os.path.join(OUT, 'pending.json')
HIST = os.path.join(OUT, 'history.json')
REVIEWED = os.path.join(OUT, 'zesty.reviewed.py')     # the last zesty.py a person approved (exists only while pending)
ZREL = 'tools/stress/zesty.py'
THRESHOLD = 3
# pass-through helpers: they only report what the RECIPE asked for (a log line it expected, an id it named, a fixture
# it chose, an engine call it made, its own time limit), so their errors are the recipe's or the lab state's, not a bug
# in the helper. Repairing them would hide real problems.
NOT_HARNESS = {'require_log', 'wait_log', 'tap', 'wait', 'open_fixture', 'open_draft_id', 'jni', '_deadline_check',
               'start_activity', 'lab'}
MAX_TRIES = 2
LLM_SEC = 900


def _z():
    return os.path.join(config.REPO, ZREL)


def _load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def _save(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    json.dump(data, open(tmp, 'w'), indent=1, default=str)
    os.replace(tmp, p)


def _now():
    return dt.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _raises(src=None):
    """[(literal prefix of the error text, function name)] for every `raise UIError/RuntimeError(...)` in zesty.py."""
    src = src if src is not None else open(_z(), encoding='utf-8').read()
    tree = ast.parse(src)
    out = []

    def lit(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            s = ''
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    s += v.value
                else:
                    break
            return s
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return lit(node.left)
        return ''

    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(ch, ch.name)
                continue
            if isinstance(ch, ast.Raise) and isinstance(ch.exc, ast.Call) and ch.exc.args:
                name = getattr(ch.exc.func, 'id', '') or getattr(ch.exc.func, 'attr', '')
                if name in ('UIError', 'RuntimeError', 'AppFailure'):
                    t = lit(ch.exc.args[0]).strip()
                    if len(t) >= 10 and fn:
                        out.append((t, fn))
            walk(ch, fn)
    walk(tree, '')
    return out


def _sig(fn, text):
    return fn + ': ' + re.sub(r'\s+', ' ', re.sub(r'\d+', 'N', text))[:60].strip()


def note(detail, run_dir=''):
    """Count one automation error of a lab run if it was raised by the harness (zesty.py). Cheap; never raises."""
    try:
        d = re.sub(r'^.*?automation did not reach the trigger in \d+/\d+ runs:\s*', '', str(detail or '')).strip()
        d = re.sub(r'^(UIError|RuntimeError|AppFailure):\s*', '', d)
        if not d:
            return None
        best = None
        for t, fn in _raises():
            if d.startswith(t[:50]) and (best is None or len(t) > len(best[0])):
                best = (t, fn)
        if not best or best[1] in NOT_HARNESS:
            return None                              # raised by a recipe of Night Shift's own, or a pass-through check
        sig = _sig(best[1], best[0])
        f = _load(FAIL, {})
        e = f.setdefault(sig, {'fn': best[1], 'text': best[0], 'count': 0, 'dirs': [], 'first': _now()})
        e['count'] += 1
        e['last'] = _now()
        e['example'] = d[:300]
        if run_dir and run_dir not in e['dirs']:
            e['dirs'] = (e['dirs'] + [run_dir])[-6:]
        _save(FAIL, f)
        return sig
    except Exception:
        return None


def _fn_source(name, src):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == name:
                    return node.name, ast.get_source_segment(src, f) or ''
        if isinstance(node, ast.FunctionDef) and node.name == name and node.col_offset == 0:
            return '', ast.get_source_segment(src, node) or ''
    return '', ''


def _changed_functions(before, after):
    """Names of functions whose source changed or that are new (to keep a patch inside its target)."""
    def fns(src):
        out = {}
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[node.name] = ast.get_source_segment(src, node)
        return out
    a, b = fns(before), fns(after)
    return {n for n in b if a.get(n) != b[n]} | {n for n in a if n not in b}


def _run_evidence(dirs):
    parts = []
    for d in dirs[-3:]:
        subs = [d] + sorted(x for x in glob.glob(os.path.join(d, '*')) if os.path.isdir(x))
        for x in subs[:2]:
            for name, cap in (('steps.log', 3000), ('screen.txt', 4000), ('picker_screen.txt', 3000)):
                p = os.path.join(x, name)
                if os.path.exists(p):
                    t = open(p, errors='replace').read()
                    parts.append(f'### {os.path.relpath(p, config.REPO)}\n```\n{t[-cap:]}\n```')
    return '\n'.join(parts)[:16000]


def _facts():
    try:
        from ns import author
        return '\n'.join(f'- {x}' for x in author.lab_facts()[-40:])
    except Exception:
        return ''


def pending():
    return _load(PEND, [])


def maybe_repair(worker, ref, key='', log=None):
    """Called between repro attempts. Repairs at most ONE harness function per call. -> True when a fix was kept."""
    log = log or (lambda t: worker.log(ref, t))
    if str(((worker.cfg.get('lab') or {}).get('harness_selffix', True))).lower() in ('false', 'no', '0'):
        return False
    f = _load(FAIL, {})
    hist = _load(HIST, {})
    now = time.time()
    cands = []
    for sig, e in f.items():
        h = hist.get(sig) or {}
        if e.get('count', 0) < THRESHOLD or h.get('tries', 0) >= MAX_TRIES or h.get('kept'):
            continue
        if now - float(h.get('at_ts', 0)) < 24 * 3600 and h.get('tries'):
            continue
        if any(p.get('fn') == e['fn'] for p in pending()):
            continue                                  # one unreviewed change per function at a time
        cands.append((e['count'], sig, e))
    if not cands:
        return False
    _, sig, e = max(cands)
    fn = e['fn']
    zp = _z()
    before = open(zp, encoding='utf-8').read()
    cls, body = _fn_source(fn, before)
    if not body:
        return False
    rid = f"h{int(now)}"
    hist[sig] = {'tries': (hist.get(sig) or {}).get('tries', 0) + 1, 'at_ts': now, 'id': rid}
    _save(HIST, hist)
    log(f'harness self-fix: {cls + "." if cls else ""}{fn}() in tools/stress/zesty.py failed the same way {e["count"]} times '
        f'("{e["example"][:120]}"); writing a fix and a test for it (try {hist[sig]["tries"]}/{MAX_TRIES})')
    test_name = f'ns_harness_test_{rid}'
    prompt = (
        '# Job: repair ONE function of the lab phone harness (Night Shift test automation, not the app)\n'
        f'File: {ZREL}. Function: {cls + "." if cls else ""}{fn}(). It failed the SAME way {e["count"]} times in real lab runs:\n'
        f'  "{e["example"]}"\n'
        'Read the function, the code around it and the evidence below. Find WHY it fails on this app build and phone, then '
        'fix it so it does what its docstring promises, the way a real user would do it on the screen.\n'
        'RULES:\n'
        f'- Change ONLY {fn}() (you may add ONE new private helper method right after it, name starting with "_"). Keep '
        'its signature, return value and meaning. Do not touch any other function.\n'
        '- Prefer real taps / long-presses on what the screen shows, and confirm success with the app\'s own log event or '
        'the screen, as the function already does. A lab-control shortcut (self.lab(...)) is allowed ONLY as the last '
        'fallback for SETUP, and must log that it used it.\n'
        '- Keep it fast (no sleeps longer than needed) and robust on both phones (realme RMX3263 720x1600, Samsung A51).\n'
        f'Answer with exactly two blocks:\n'
        f'1. ```diff``` a unified diff against {ZREL} (paths a/{ZREL} b/{ZREL}), small and exact.\n'
        f'2. ```python``` ONE test scenario, `@scenario(\'nightshift\', \'harnesstest\')` `def {test_name}(ed, r):` with a '
        'one-line docstring. It must reach and run the repaired step on its own (open a project / fixture, open the '
        'needed tool, call the function) and raise UIError if the step does not work. It must NOT try to crash the app '
        'and must finish in under 120 s. Use only ed / time / r.\n\n'
        f'# The function now\n```python\n{body[:9000]}\n```\n\n'
        f'# Evidence from the failing runs (steps, what the screen showed)\n{_run_evidence(e.get("dirs") or [])}\n\n'
        f'# What Night Shift learned about this lab so far\n{_facts()[:6000]}\n')
    try:
        from ns import llm
        txt = llm.run('harness-fix', prompt, worker.cfg, OUT, f'{rid}.{fn}', tools='Read,Grep,Glob', cwd=config.REPO,
                      timeout=LLM_SEC)
    except Exception as ex:
        log(f'harness self-fix: no answer ({str(ex)[:120]})')
        return False
    diff = (re.findall(r'```diff\n(.*?)```', txt or '', re.S) or [''])[0]
    code = (re.findall(r'```python\n(.*?)```', txt or '', re.S) or [''])[0]
    if not diff.strip() or f'def {test_name}(' not in code:
        log('harness self-fix: the answer had no usable patch or test; nothing changed')
        return False
    dp = os.path.join(OUT, f'{rid}.diff')
    os.makedirs(OUT, exist_ok=True)
    open(dp, 'w').write(diff if diff.endswith('\n') else diff + '\n')
    files = set(re.findall(r'^\+\+\+ b/(\S+)', diff, re.M))
    if files != {ZREL}:
        log(f'harness self-fix: the patch touches {sorted(files)} (only {ZREL} is allowed); nothing changed')
        return False
    chk = subprocess.run(['git', 'apply', '--check', '--recount', dp], cwd=config.REPO, capture_output=True, text=True)
    if chk.returncode:
        log(f'harness self-fix: the patch does not apply: {chk.stderr.strip()[:160]}; nothing changed')
        return False
    backup = os.path.join(OUT, f'{rid}.zesty.before.py')
    shutil.copy2(zp, backup)
    first_pending = not pending() and not os.path.exists(REVIEWED)
    subprocess.run(['git', 'apply', '--recount', dp], cwd=config.REPO, capture_output=True, text=True)
    after = open(zp, encoding='utf-8').read()

    def revert(why):
        shutil.copy2(backup, zp)
        log(f'harness self-fix: {why}; reverted, zesty.py is back as it was')
    try:
        ast.parse(after)
    except SyntaxError as ex:
        revert(f'the patched file does not parse ({ex})')
        return False
    changed = _changed_functions(before, after)
    extra = {n for n in changed if n != fn and not n.startswith('_')}
    if fn not in changed or extra:
        revert(f'the patch changed {sorted(changed)} (allowed: {fn} and one new private helper)')
        return False
    tp = os.path.join(config.REPO, 'tools', 'stress', 'auto', f'harnesstest_{rid}.py')
    open(tp, 'w', encoding='utf-8').write(f'# Night Shift harness self-fix test for {fn}() ({rid}); removed after the test\n'
                                         + code.strip() + '\n')
    ok, why = False, ''
    try:
        res = worker._ladder_step(ref, {'scenario': test_name, 'repeat': 1, 'name': test_name, 'fast': True,
                                        'phone_only': True, 'setup': True}, [])
        ok = bool(res.get('runs')) and not res.get('errors') and not res.get('fails')
        why = res.get('why') or res.get('result') or ''
    except Exception as ex:
        why = str(ex)[:200]
    finally:
        try:
            shutil.move(tp, os.path.join(OUT, f'{rid}.test.py'))
        except Exception:
            pass
    if not ok:
        revert(f'the test on the phone did not pass ({why[:160]})')
        return False
    if first_pending:
        shutil.copy2(backup, REVIEWED)               # what teammates keep getting until a person approves
    pend = pending()
    pend.append({'id': rid, 'fn': fn, 'class': cls, 'sig': sig, 'at': _now(), 'diff': os.path.relpath(dp, HERE),
                 'test': os.path.relpath(os.path.join(OUT, f'{rid}.test.py'), HERE), 'failures': e['count'],
                 'example': e['example'], 'job': getattr(ref, 'id', ''), 'key': key})
    _save(PEND, pend)
    hist[sig]['kept'] = rid
    _save(HIST, hist)
    log(f'harness self-fix KEPT ({rid}): {fn}() patched and its test passed on the phone. NOT reviewed: only this Mac uses '
        f'it; teammates get it after "python3 tools/nightshift/ns/harnessfix.py approve {rid}"')
    return True


# ------------------------------------------------------------------ review (a person, on the lab Mac)
def _cli():
    a = sys.argv[1:]
    if not a or a[0] == 'list':
        p = pending()
        if not p:
            print('no unreviewed harness fixes')
        for x in p:
            print(f"{x['id']}  {x['at']}  {x.get('class') + '.' if x.get('class') else ''}{x['fn']}()  after {x['failures']} "
                  f"failures: {x['example'][:90]}\n      diff: tools/nightshift/{x['diff']}   test: tools/nightshift/{x['test']}")
        return
    cmd, rid = a[0], (a[1] if len(a) > 1 else '')
    p = pending()
    x = next((y for y in p if y['id'] == rid), None)
    if cmd in ('show', 'approve', 'reject') and not x:
        sys.exit(f'no pending harness fix {rid!r} (see: harnessfix.py list)')
    dp = os.path.join(HERE, x['diff']) if x else ''
    if cmd == 'show':
        print(open(dp).read())
        return
    if cmd == 'approve':
        if os.path.exists(REVIEWED):                  # the reviewed copy gets this patch too
            tmp = os.path.join(OUT, 'review_tmp')
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(os.path.join(tmp, os.path.dirname(ZREL)))
            shutil.copy2(REVIEWED, os.path.join(tmp, ZREL))
            r = subprocess.run(['git', 'apply', '--recount', os.path.abspath(dp)], cwd=tmp,
                               capture_output=True, text=True)
            if r.returncode:
                sys.exit(f'could not apply to the reviewed copy: {r.stderr.strip()[:200]}')
            shutil.copy2(os.path.join(tmp, ZREL), REVIEWED)
            shutil.rmtree(tmp, ignore_errors=True)
        p = [y for y in p if y['id'] != rid]
        _save(PEND, p)
        if not p and os.path.exists(REVIEWED):
            os.remove(REVIEWED)                       # nothing pending: zesty.py itself is the reviewed version
        print(f'approved {rid}: it goes to teammates with the next kit_build.py + push')
        return
    if cmd == 'reject':
        r = subprocess.run(['git', 'apply', '-R', '--recount', dp], cwd=config.REPO, capture_output=True, text=True)
        if r.returncode:
            sys.exit(f'could not undo the patch in zesty.py: {r.stderr.strip()[:200]} (undo it by hand, then run reject again)')
        p = [y for y in p if y['id'] != rid]
        _save(PEND, p)
        if not p and os.path.exists(REVIEWED):
            os.remove(REVIEWED)
        print(f'rejected {rid}: zesty.py no longer has it')
        return
    sys.exit('usage: ns/harnessfix.py list | show <id> | approve <id> | reject <id>')


if __name__ == '__main__':
    _cli()
