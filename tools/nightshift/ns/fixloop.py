"""Steps 7-10 after a reproduction, with no person in the loop until the hand-over:

7 propose  Claude reads the analysis, the reproduction and the code (Read/Grep) and writes the smallest fix as a diff.
8 verify   Night Shift applies it (plus the repro's debug hooks), builds, installs and re-runs the step that reproduced
           the crash enough times to be meaningful (3x the runs one hit needed, at least 4). Clean = no field frame,
           no other crash, and the automation reached the trigger. Then the working tree is reverted.
9 review   A separate Claude review (skill fix-review) reads the diff like a senior reviewer. Blocking issues go back to 7.
10 hand    PR description, Jira ticket and Slack message drafts are written to the case; a time log row is added.

Up to 3 propose/verify/review rounds. Never commits, pushes or merges: the patch stays in out/patches/ for a person.
"""
import sys
import datetime as dt
import glob
import json
import math
import os
import re
import subprocess

from . import config, fix, llm, runlog

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out')
ROUNDS = 3


def _git(args, timeout=120):
    return subprocess.run(['git', '--no-optional-locks'] + args, cwd=config.LAB, capture_output=True, text=True, timeout=timeout)


def _ctx(case, merged):
    a = (merged or {}).get('analysis') or {}
    return {'id': case['id'], 'kind': case.get('kind'), 'title': case.get('title'),
            'field_frames': [f if isinstance(f, str) else (f.get('func') or f"{f.get('lib')} {f.get('address')}") for f in (case.get('frames') or [])[:25]],
            'analysis': {k: a.get(k) for k in ('summary', 'root_cause', 'trigger', 'fix_direction', 'wait_chains', 'hypotheses', 'evidence', 'source') if a.get(k)},
            'reproduction': {k: case.get(k) for k in ('labMatch', 'reproLevel', 'reproNatural', 'reproRate', 'repro_step', 'repro_dir')},
            **_looper_ctx(case)}


def _looper_ctx(case):
    """Looper-wait ANR (main thread blocked in MsgLooper::Get): the fix must target what made the engine's message
    thread slow, so give the proposer/critic the field busy window, the lab's engine-thread stack and the rule."""
    try:
        from . import author as _au
        if not _au.looper_wait_frames(case):
            return {}
        out = {'looper_wait_rule': _au.LOOPER_RULE}
        bw = _au.busy_window(case)
        if bw:
            out['engine_busy_window_field'] = bw
        if case.get('labBusy'):
            out['engine_thread_at_lab_anr'] = case['labBusy']
        return out
    except Exception:
        return {}


def _lab_dump(case):
    d = case.get('repro_dir') or ''
    d = d if os.path.isabs(d) else os.path.join(config.REPO, d)
    out = ''
    for fn in ('data_app_native_crash.txt', 'data_app_crash.txt', 'anr_trace.txt'):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            txt = open(p, errors='replace').read()
            if fn == 'anr_trace.txt':
                m = re.search(r'"main".*?(?=\n\n)', txt, re.S)
                eng = next((b for b in re.split(r'\n\s*\n', txt) if 'MsgLooper::ProcessMessages' in b
                            and not b.lstrip().startswith('"main"')), '')
                txt = (m.group(0) if m else txt)[:4000] + ('\n\n--- engine message thread (what it was busy doing) ---\n'
                                                          + eng[:3000] if eng else '')
            out += f'--- lab {fn} ---\n' + txt[:8000] + '\n'
    return out


BLIND_DENY = None        # set by the worker for a blind test: paths the proposer/reviewer must not read


def propose(case, merged, cfg, history, n, tag='', angle='', lessons=''):
    prompt = ('# Task\nWrite the smallest safe fix for this crash. It was reproduced on the lab phone; the fix will be '
              'verified by re-running that reproduction and then reviewed. Read the code with Read/Grep first: the '
              'crashing function, its callers and the threads in the wait chain. Fix the cause, not the symptom; keep '
              'behaviour the same otherwise. Do not touch tools/, tests or build files; do not remove debug hooks '
              '(debug.zesty.hook.*). Where the fix drops, skips or short-circuits a call (a guard that returns early), '
              'log ONE line there with the file\'s existing error log macro (e.g. LOGE("<function>: <reason>, call skipped")), '
              'so the lab can see in logcat that the guarded path ran; a silent guard cannot be told apart from a run that never '
              'reached the crash moment, and the fix would stay unverified.\n'
              'IMPORTANT: the diff must apply to the CURRENT working copy (that is what gets built and tested). Line '
              'numbers in the analysis are from the shipped commit and may be shifted, so Read the file as it is now '
              'and copy context lines exactly from it.\n\n'
              f'# Case\n```json\n{json.dumps(_ctx(case, merged), indent=1, default=str)[:30000]}\n```\n{_lab_dump(case)}\n'
              + ('# Previous rounds (fix what they say)\n' + '\n\n'.join(history[-2:]) + '\n\n' if history else '')
              + (lessons or '')
              + (f'# Your angle for this candidate\n{angle}\n\n' if angle else '')
              + '# Answer\nA short "Cause:" paragraph, then ONE unified diff (git format, a/ b/ paths from the repo root) in a ```diff block.')
    ans = llm.run('fix-proposal', prompt, cfg, OUT, f"{case['id']}.fix{n}{tag}", tools='Read,Grep,Glob', cwd=config.LAB, timeout=1500, deny=BLIND_DENY)
    diff = fix.extract_diff(ans or '')
    if not diff:
        return None, ans, 'no diff in the answer'
    diff = fix.match_line_endings(diff, config.LAB)
    files = re.findall(r'^\+\+\+ b/(\S+)', diff, re.M)
    if not files or any(f.startswith(('tools/', '.git')) or f.endswith(('.gradle', '.kts', 'CMakeLists.txt')) for f in files):
        return None, ans, f'the diff must change app code only (got {files})'
    try:                                             # looper-wait ANR: a fix that only touches the wait (JNI/MsgLooper)
        from . import author as _au                  # hides the slow work; it must change the work itself
        added = '\n'.join(l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))
        waitonly = re.search(r'wait_for|wait_until|timeout|Timeout|try_lock|WaitFor\(|GetFor\(|non.?blocking|std::chrono::', added)
        # only a diff that is confined to the wait AND changes how long it waits is a 'timeout fix'; a JNI/MsgLooper change
        # that fixes a real wrong value (e.g. a dropped request answered as 0.0 forever) is a real fix (2026-10-21: the
        # blunt version rejected 6 candidates in a row)
        if _au.looper_wait_frames(case) and waitonly and all(os.path.basename(f) in ('JNI.cpp', 'MsgLooper.h', 'MsgLooper.cpp',
                                                                                    'JNIHelper.cpp', 'JNIHelper.h') for f in files):
            return None, ans, ('looper-wait ANR: the diff only changes the wait (timeout/non-blocking in JNI or MsgLooper); '
                               'fix what made the engine message thread slow instead')
    except Exception:
        pass
    os.makedirs(os.path.join(OUT, 'patches'), exist_ok=True)
    patch = os.path.join(OUT, 'patches', f"{case['id']}{tag}.patch")
    open(patch, 'w', newline='').write(diff)
    # model diffs often have off-by-one hunk counts ("corrupt patch at line N"): let git recount before rejecting
    for flags in ([], ['--recount'], ['--recount', '--ignore-whitespace']):
        chk = _git(['apply', '--check', *flags, patch])
        if not chk.returncode:
            open(patch + '.flags', 'w').write(' '.join(flags))
            return patch, ans, ''
    return None, ans, f'the diff does not apply: {chk.stderr.strip()[:300]}'


def _insert_hook(path, hunks):
    """Place a hook's added lines into a file the fix already changed: each hunk is pure insertion; its added block
    goes right after the context lines that precede it (falling back to the lines that follow), matched uniquely
    and ignoring line endings. Returns the new bytes or None."""
    raw = open(path, 'rb').read()
    nl = b'\r\n' if b'\r\n' in raw[:65536] else b'\n'
    lines = raw.decode('utf-8', 'replace').replace('\r\n', '\n').split('\n')
    for h in hunks:
        if any(t == '-' for t, _ in h):
            return None                              # a hook that removes lines is not merged automatically
        k = next(i for i, (t, _) in enumerate(h) if t == '+')
        pre = [x for t, x in h[:k] if t == ' ']
        add = [x for t, x in h if t == '+']
        post = [x for t, x in h[k + len(add):] if t == ' ']
        at = None
        for n in range(len(pre), 0, -1):             # longest unique run of the preceding context
            ctx = pre[-n:]
            hits = [i for i in range(len(lines) - n + 1) if [l.rstrip() for l in lines[i:i + n]] == [c.rstrip() for c in ctx]]
            if len(hits) == 1:
                at = hits[0] + n
                break
            if len(hits) > 1 and n == len(pre):
                break
        if at is None and post:
            n = len(post)
            hits = [i for i in range(len(lines) - n + 1) if [l.rstrip() for l in lines[i:i + n]] == [c.rstrip() for c in post]]
            at = hits[0] if len(hits) == 1 else None
        if at is None:
            return None
        lines[at:at] = add
    return '\n'.join(lines).encode('utf-8').replace(b'\n', nl) if nl != b'\n' else '\n'.join(lines).encode('utf-8')


def _hunks(patch):
    """{path: [hunk, ...]} with each hunk a list of (type, text), type in ' +-'."""
    out, cur, h = {}, None, None
    for l in open(patch, errors='replace').read().replace('\r\n', '\n').split('\n'):
        if l.startswith('+++ b/'):
            cur = os.path.join(config.LAB, l[6:].strip())
            out.setdefault(cur, [])
        elif l.startswith('--- ') or l.startswith('diff --git') or l.startswith('index '):
            continue
        elif l.startswith('@@') and cur:
            h = []
            out[cur].append(h)
        elif h is not None and l[:1] in (' ', '+', '-'):
            h.append((l[0], l[1:]))
    return out


def _merge_apply(patches):
    """The fix and a repro hook touch the same lines (the hook sits at the top of the crashing JNI call, the fix
    rewrites its first line): apply the fix strictly, then each hook strictly where it fits and by its context
    elsewhere (hooks only add lines). patches = [fix] + hooks. Returns ({path: original bytes}, '') with the files
    changed, or (None, why) with the tree untouched."""
    fix_p, hooks = patches[0], patches[1:]
    hk = {h: _hunks(h) for h in hooks}
    files = set(_hunks(fix_p)) | {f for d in hk.values() for f in d}
    orig = {f: open(f, 'rb').read() for f in files if os.path.exists(f)}

    def restore():
        for f, d in orig.items():
            open(f, 'wb').write(d)
    try:
        fl = open(fix_p + '.flags').read().split() if os.path.exists(fix_p + '.flags') else []
        r = _git(['apply', *fl, fix_p])
        if r.returncode:
            restore()
            return None, f'the fix does not apply on its own: {r.stderr[:120]}'
        fixed = set(_hunks(fix_p))
        for h in hooks:
            for f, hunks in hk[h].items():
                if f not in fixed:
                    continue                         # placed below by git apply
                new = _insert_hook(f, hunks)
                if new is None:
                    restore()
                    return None, f'{os.path.basename(f)}: the hook has no unique place in the fixed file'
                open(f, 'wb').write(new)
            rest = [f for f in hk[h] if f not in fixed]
            if rest:
                fh = open(h + '.flags').read().split() if os.path.exists(h + '.flags') else []
                inc = [a for f in rest for a in ('--include', os.path.relpath(f, config.LAB))]
                r = _git(['apply', *fh, *inc, h])
                if r.returncode:
                    restore()
                    return None, f'{os.path.basename(h)}: {r.stderr[:120]}'
        return orig, ''
    except Exception as e:
        restore()
        return None, str(e)[:120]


def _crash_frames(dirs, per=12, most=2):
    """Top frames of the crash dumps in these lab run folders (native backtrace or Java stack), distinct stacks only."""
    stacks = []
    for d in dirs:
        for sub in sorted(glob.glob(os.path.join(d, '*'))) + [d]:
            lf = os.path.join(sub, 'logcat.txt')
            if not os.path.isfile(lf):
                continue
            fr = []
            for l in open(lf, errors='replace'):
                m = re.search(r' F DEBUG   : +#(\d+) pc \S+ +\S+ \((.+?)(\+\d+)?\)', l)
                if m:
                    fr.append(f'#{m.group(1)} {m.group(2)[:110]}')
                elif re.search(r' E AndroidRuntime: (FATAL|\S+Exception|\s+at )', l):
                    fr.append(l.split('AndroidRuntime:', 1)[1].strip()[:140])
                elif re.search(r' W System\.err: +([\w.$]+(Exception|Error)\b|\s*at com\.(video|myzesty|common|picker)\.)', l) \
                        and not re.search(r'cronet|okhttp|ssl|socket|UnknownHost|Timeout|ttnet', l, re.I):
                    fr.append(l.split('System.err:', 1)[1].strip()[:140])   # the app's CrashCatcher prints here
                if len(fr) >= per:
                    break
            # the crash itself first: a native backtrace, else the FATAL Java stack; System.err noise (network
            # timeouts etc.) only when nothing else is there
            nat = [f for f in fr if f.startswith('#')]
            fatal = [f for f in fr if not f.startswith('#')]
            st = '\n'.join(nat or fatal)
            if st and st not in stacks:
                stacks.append(st)
            if len(stacks) >= most:
                return '\n\n'.join(stacks)
    return '\n\n'.join(stacks)


ANGLES = [('A', 'Defend at the crash site: the smallest check where the bad value or state is used, logging the skipped call.'),
          ('B', 'Remove the cause: fix the lifetime, ownership or state change that lets the bad value exist (who clears, frees '
                'or desyncs it, and when), so no caller can hit it.'),
          ('C', 'Fix the contract between layers: the side that sends the bad request (Java/Kotlin or JNI boundary) must not '
                'send it, and the receiving side must still fail safely.')]


def tournament(worker, ref, case, merged, cfg, history, n, lessons=''):
    """Chrome-style fix tournament: 3 candidates from different angles in parallel, a critic picks one and a code review
    runs BEFORE the lab (one revision if it blocks), so the slow phone time goes to the best candidate only."""
    import shutil
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        futs = {k: ex.submit(propose, case, merged, cfg, history, n, f'.{k}', a, lessons) for k, a in ANGLES}
    cands = {k: f.result() for k, f in futs.items()}
    ok = {k: c for k, c in cands.items() if c[0]}
    worker.log(ref, '  tournament: ' + '; '.join(f'{k} ' + ('applies' if c[0] else f'rejected ({c[2][:60]})') for k, c in cands.items()))
    if not ok:
        return None, (cands['A'][1] or ''), 'no candidate applies: ' + ' | '.join(c[2][:120] for c in cands.values())
    pick, why = next(iter(ok)), 'only candidate that applies'
    if len(ok) > 1:
        diffs = '\n\n'.join(f'## Candidate {k}\n```diff\n{open(c[0], errors="replace").read()[:9000]}\n```' for k, c in ok.items())
        prompt = ('# Pick the best crash fix. Read the code (Read/Grep) where needed. Judge: fixes the root cause below (not '
                  'only the symptom), no new crash path, thread safety, behaviour for users, smallest blast radius, and that '
                  'it logs when it skips work.\n\n'
                  f'# Case\n```json\n{json.dumps(_ctx(case, merged), indent=1, default=str)[:15000]}\n```\n{diffs}\n'
                  '# Answer: ONLY a ```json block: {"pick": "A|B|C", "why": "...", "ranking": ["A","B","C"]}')
        ans = llm.run('fix-review', prompt, cfg, OUT, f"{case['id']}.critic{n}", tools='Read,Grep,Glob', cwd=config.LAB,
                      timeout=900, deny=BLIND_DENY)
        m = re.findall(r'```json\n(.*?)```', ans or '', re.S)
        try:
            j = json.loads(m[-1] if m else ans)
            if j.get('pick') in ok:
                pick, why = j['pick'], str(j.get('why', ''))[:200]
        except (ValueError, TypeError):
            why = 'critic answer unreadable: first candidate that applies'
    worker.log(ref, f'  critic picked {pick}: {why}')
    chosen = ok[pick]
    if getattr(worker, '_spec_build', False):
        # SPEED (early fix): build the picked fix WHILE the pre-lab review reads it. The APK cache is keyed on the code,
        # so the replay check that applies the same patch later installs this APK (~20 s) instead of compiling (~3.5 min).
        import threading as _th

        def _spec(p=chosen[0]):
            fl = open(p + '.flags').read().split() if os.path.exists(p + '.flags') else []
            try:
                if _git(['apply', *fl, p]).returncode:
                    return
                try:
                    worker.log(ref, '  speculative build: compiling the picked fix while the review reads it')
                    worker.install_app(ref)
                finally:
                    _git(['apply', '-R', *fl, p])
            except Exception as e:
                worker.log(ref, f'  speculative build skipped: {str(e)[:120]}')
        worker._spec_th = _th.Thread(target=_spec, daemon=True)
        worker._spec_th.start()
    rev = review(case, merged, cfg, chosen[0], f'{n}.pre')
    if rev.get('blocking'):
        worker.log(ref, f"  pre-lab review: {len(rev['blocking'])} blocking -> one revision before the lab")
        h2 = history + [f'## round {n} candidate {pick} (not tested yet)\n```diff\n{open(chosen[0], errors="replace").read()[:6000]}'
                        f'\n```\nCode review asked for changes before testing:\n' + json.dumps(rev['blocking'], indent=1)[:4000]]
        if getattr(worker, '_spec_th', None) is not None:   # the speculative build has the old pick applied: let it finish
            worker._spec_th.join(2400)
            worker._spec_th = None
        r2 = propose(case, merged, cfg, h2, n, f'.{pick}r', dict(ANGLES)[pick], lessons)
        if r2[0]:
            chosen = r2
            worker.log(ref, '  revision applies: it goes to the lab')
        else:
            worker.log(ref, f'  revision rejected ({r2[2][:80]}): the reviewed candidate goes to the lab')
    else:
        worker.log(ref, f"  pre-lab review: {rev.get('verdict')} (no blocking issue)")
    final = os.path.join(OUT, 'patches', f"{case['id']}.patch")
    shutil.copyfile(chosen[0], final)
    if os.path.exists(chosen[0] + '.flags'):
        shutil.copyfile(chosen[0] + '.flags', final + '.flags')
    elif os.path.exists(final + '.flags'):
        os.remove(final + '.flags')
    return final, chosen[1], ''


def verify(worker, ref, case, patch):
    """Apply patch + repro hooks, build, install, re-run the reproducing step N times, revert. -> (ok, note, res)"""
    step = dict(case.get('repro_step') or {})
    if not step:
        return False, 'no reproducing step recorded on the case', {}
    hits, runs = map(int, (str(case.get('reproRate') or '1/1').split('/') + ['1'])[:2])
    # 3x the runs one crash needed; a rate seen in fewer than 3 runs is a guess, so then at least 8 clean runs
    need = min(12, max(8 if runs < 3 else 4, math.ceil(3 * runs / max(1, hits))))
    tb = worker._turbo() if hasattr(worker, '_turbo') else {}
    if tb.get('verify_conf'):
        # TURBO idea 2: as many clean runs as the measured hit rate needs for the confidence asked (default 95%).
        # Hit rate = the repro runs plus the recorded proof run, Laplace-smoothed so 1/1 is not taken as 100%.
        h2, n2 = hits + (1 if case.get('reproVideo') else 0), runs + (1 if case.get('reproVideo') else 0)
        p = (h2 + 1) / (n2 + 2)
        conf = float(tb.get('verify_conf'))
        need = min(12, max(int(tb.get('verify_min') or 3), math.ceil(math.log(1 - conf) / math.log(1 - p))))
        worker.log(ref, f'verify (turbo): hit rate about {p:.0%} ({h2}/{n2} runs); {need} clean runs give {conf:.0%} confidence '
                        f'(every checkpoint must still be reached)')
    hooks = [os.path.join(config.REPO, step['hook_patch'])] if step.get('hook_patch') else []
    applied, merged_files = [], {}
    try:
        for p in [patch] + hooks:
            fl = open(p + '.flags').read().split() if os.path.exists(p + '.flags') else []
            r = _git(['apply', *fl, p])
            if r.returncode:
                if hooks and applied == [patch]:     # the hook touches the lines the fix changed: merge the two
                    for q in reversed(applied):
                        fq = open(q + '.flags').read().split() if os.path.exists(q + '.flags') else []
                        _git(['apply', '-R', *fq, q])
                    applied = []
                    saved, why = _merge_apply([patch] + hooks)
                    if saved is None:
                        return False, f'could not apply {os.path.basename(p)} with the fix (3-way merge: {why})', {}
                    merged_files.update(saved)
                    worker.log(ref, f'verify: fix and repro hook touch the same lines; fix applied, hook placed by its context ({", ".join(sorted(os.path.basename(k) for k in saved))})')
                    break
                return False, f'could not apply {os.path.basename(p)}: {r.stderr[:200]}', {}
            applied.append(p)
        worker.log(ref, f'verify: fix applied (+{len(hooks)} repro hook); building')
        if worker.install_app(ref):
            import re as _re
            errs = [l.strip() for l in (getattr(worker, '_last_errors', None) or getattr(worker, '_last_tail', []))
                    if _re.search(r'\berror:|^e: |unresolved reference', l)]
            errs = list(dict.fromkeys(errs))[:12]      # the proposer must SEE the compiler errors (2026-10-21: the
            return False, ('the app does not build with this fix. Compiler errors:\n' + '\n'.join(errs)   # same error twice)
                           if errs else 'the app does not build with this fix (see the build errors in the job log)'), {}
        total = {'runs': 0, 'hits': 0, 'fails': 0, 'errors': 0, 'why': '', 'known_other': 0, 'others': [], 'truncated': 0,
                 'trunc_excused': 0}
        known_ok = (worker.cfg.get('lab') or {}).get('verify_known_other_ok', True)
        expect = list((((worker.cfg.get('lab') or {}).get('repros') or {}).get(case['id']) or {}).get('expect') or [])
        if not expect:                               # this card's own registered repro (exact id) before any name match
            try:
                expect = list((json.load(open(os.path.join(config.REPO, 'tools/nightshift/lab_repros.json'))).get(case['id']) or {}).get('expect') or [])
            except Exception:
                expect = []
        if not expect:
            key, spec = worker._registered(case)
            expect = list((spec or {}).get('expect') or [])
        if not expect:                               # registered during THIS job (not in the loaded config yet): the
            from . import author                     # same frames the repro was judged by; never 'any crash counts'
            try:
                reg = json.load(open(os.path.join(config.REPO, 'tools/nightshift/lab_repros.json')))
                expect = list((reg.get(case['id']) or {}).get('expect') or [])
            except Exception:
                expect = []
            expect = expect or author.expect_frames(case, (worker._merged(case) or {}).get('analysis') or {})
        worker.log(ref, f'verify: a run fails the fix only if its dump shows: {", ".join(expect) or "(nothing to match: any crash counts)"}'
                   + ''.join(f' - or the stack of same-bug family member {t_} ({", ".join(ex_)})' for _c, t_, ex_ in (getattr(worker, '_family', None) or [])))
        rdir = os.path.join(config.REPO, worker.cfg['lab']['results_dir'])
        new_dirs = []
        rp = None
        if tb.get('replay'):
            from . import replay as _rp
            rp = getattr(worker, '_replay', None) or _rp.load(case['id'])
        if rp and rp.get('scenario') and patch.endswith('.early.patch'):
            worker.log(ref, 'verify (turbo): this patch already passed the engine replay; straight to the real-tap runs')
        elif rp and rp.get('scenario'):
            # TURBO step 6: the engine replay on the FIXED build first, many times on every device (seconds each). A replay
            # that still crashes the field way rejects the fix in about a minute, before the slow real-tap runs.
            nrp = int(tb.get('replay_verify_runs') or 9)
            worker.log(ref, f'verify (turbo): engine replay {rp["scenario"]} on the fixed build first ({nrp} replays per app session)')
            # one app session per device, the replay calls repeated nrp times inside it (ZESTY_JNI_REPEAT): ~1 min, not
            # nrp app restarts. An unfixed build dies on the first replay, so a hit still shows at once.
            ndev = 1 + len(getattr(worker, '_lane_serials', None) or [])
            r0 = worker._ladder_step(ref, {'scenario': rp['scenario'], 'repeat': ndev, 'name': rp['scenario'], 'fast': True,
                                           'env': f'ZESTY_JNI_REPEAT={nrp} '}, expect)
            if r0.get('hits'):
                return False, f"the engine replay still crashes the field way with the fix: {r0['hits']}/{r0['runs']} replays", \
                    dict(r0, dirs=r0.get('dirs') or [])
            worker.log(ref, f"verify (turbo): engine replay clean {r0.get('runs', 0) - r0.get('errors', 0)}/{r0.get('runs', 0)}"
                            + (f"; {r0.get('fails')} other crash(es) in the replay (not counted: a replay is artificial)" if r0.get('fails') else '')
                            + '; now the real-tap runs')
        if getattr(worker, '_lanes', None) and getattr(worker._lanes, 'serials', None):
            import time as _t                         # the lanes get the fixed APK in the background: let them join first
            for _ in range(30):
                if getattr(worker, '_lane_serials', None):
                    break
                _t.sleep(3)
        for chunk in range(6):
            if total['runs'] >= need:
                break
            before = set(glob.glob(os.path.join(rdir, '*')))
            st = dict(step)
            # first 2 runs on their own: a fix that still crashes is rejected ~12 min sooner; a clean fix gets every run
            want = min(2, need - total['runs']) if chunk == 0 else need - total['runs']
            if st.get('cmd'):
                st['cmd'] = re.sub(r'--tries \d+', f"--tries {want}", st['cmd'])
                st.setdefault('name', 'repro script')
            else:
                st['repeat'] = want
            res = worker._ladder_step(ref, st, expect)
            new_dirs += res.get('dirs') or sorted(set(glob.glob(os.path.join(rdir, '*'))) - before)
            for k in ('runs', 'hits', 'fails', 'errors', 'known_other', 'truncated'):
                total[k] += res.get(k) or 0
            total['others'] += res.get('others') or []
            total['why'] = res.get('why') or total['why']
            tr = res.get('truncated') or 0
            if tr and not total['trunc_excused'] and not res.get('hits'):
                # a cut-short dump (no app frame) can't tell which bug it was: re-run those runs once instead of failing
                total['trunc_excused'] = tr
                need += tr
                worker.log(ref, f"verify: {tr} run(s) crashed with a cut-short dump ({res['others'][0]['label'][:120] if res.get('others') else '?'}): "
                                f"can't tell which bug, re-running {tr} run(s) once")
            unknown = (res.get('fails') or 0) - (res.get('hits') or 0) - ((res.get('known_other') or 0) if known_ok else 0) \
                - (tr if total['trunc_excused'] == tr and total['truncated'] == tr else 0)
            if res.get('hits') or unknown > 0:
                break
            for o in res.get('others') or []:            # a known OTHER card's bug: logged, the runs go on
                worker.log(ref, f"verify: another known bug crashed one run: {o['title']} ({o['label'][:140]}); "
                                f"not this fix's crash (lab.verify_known_other_ok); {o['dir']}")
        total['dirs'] = new_dirs
    finally:
        for p in reversed(applied):
            fl = open(p + '.flags').read().split() if os.path.exists(p + '.flags') else []
            _git(['apply', '-R', *fl, p])
        for path, data in merged_files.items():      # merged files: put the exact original bytes back
            open(path, 'wb').write(data)
    if total['hits']:
        return False, f"still crashes the field way with the fix: {total['hits']}/{total['runs']} runs", total
    unknown = total['fails'] - total['hits'] - (total.get('known_other', 0) if known_ok else 0) - total.get('trunc_excused', 0)
    if unknown > 0:
        return False, f"no field crash, but another crash/ANR appeared in {total['fails']}/{total['runs']} runs: {total['why']}", total
    if total['fails']:                               # only known OTHER bugs crashed: the field crash never came back
        kn = sorted({o['title'] for o in total['others'] if o.get('title')})
        worker.log(ref, f"verify: {total['fails']} run(s) crashed without the field frames"
                        + (f"; known other bug(s): {'; '.join(kn)}" if kn else '')
                        + (f"; {total['trunc_excused']} cut-short dump(s), clean on the re-run" if total.get('trunc_excused') else '')
                        + "; the field crash never appeared, so they do not reject this fix")
    rescued = _guard_runs_without_crash(patch, new_dirs) if total['errors'] else 0
    if rescued:                                      # automation tripped AFTER the trigger: the guard ran and nothing crashed
        worker.log(ref, f'verify: {rescued} run(s) ended in an automation error after the fix\'s guard ran with no crash; counted as clean')
        total['errors'] = max(0, total['errors'] - rescued)
    if total['runs'] - total['errors'] < need:
        return False, f"inconclusive: the automation reached the trigger in only {total['runs'] - total['errors']}/{need} runs", total
    hits = _guard_hits(patch, new_dirs)               # the fix's own guard log fired: the crash moment came and was handled
    if hits:
        n_runs, sample = hits
        worker.log(ref, f'verify: the fix\'s guard logged in {n_runs}/{total["runs"]} runs with no crash, e.g. "{sample[:120]}"')
        reached, why = True, f'the fix\'s guard ran in {n_runs}/{total["runs"]} clean runs ("{sample[:100]}")'
    else:
        reached, why = _trigger_reached(worker, ref, case, new_dirs, total)
    total['trigger'] = {'reached': reached, 'why': why}
    if not reached:
        return False, f"inconclusive: {total['runs']} clean runs, but the fixed build did not reach the crash moment: {why}", total
    return True, (f"A/B: the unfixed build crashed in {case.get('reproRate')} runs; with the fix {total['runs']}/{total['runs']} "
                  f"runs were clean and the crash moment was reached: {why}"), total


def _guard_hits(patch, dirs):
    """Objective proof that a clean run reached the crash moment: the log lines the FIX added (its LOGE/LOGW/Log.e
    messages in early-return guards) appear in the fixed build's logcat. Returns (runs with a hit, sample line) or None."""
    import gzip
    pats = []
    for l in open(patch, errors='replace').read().replace('\r\n', '\n').split('\n'):
        if not l.startswith('+') or l.startswith('+++'):
            continue
        m = re.search(r'\b(?:LOG[EWIDV]|TRACE|Log\.[ewidv]|__android_log_print)\s*\([^"]*"([^"]{8,})"', l)
        if not m:
            continue
        parts = [re.escape(x) for x in re.split(r'%[-+ #0-9.]*[a-zA-Z]+|\$\{?\w+\}?', m.group(1)) if len(x.strip()) >= 4]
        if parts:
            pats.append(re.compile('.*'.join(parts)))
    if not pats:
        return None
    runs, sample = 0, ''
    for d in dirs:
        for sub in sorted(glob.glob(os.path.join(d, '*'))):
            for lf in glob.glob(os.path.join(sub, 'logcat.txt*')):
                try:
                    op = gzip.open if lf.endswith('.gz') else open
                    with op(lf, 'rt', errors='replace') as fh:
                        hit = next((ln.strip() for ln in fh if any(p.search(ln) for p in pats)), '')
                except Exception:
                    hit = ''
                if hit:
                    runs += 1
                    sample = sample or hit.split(': ', 1)[-1]
                    break
    return (runs, sample) if runs else None


def _guard_runs_without_crash(patch, dirs):
    """Runs (subfolders) whose log shows the fix's guard line and no crash at all."""
    import gzip
    hit = _guard_hits(patch, [])  # compile check only
    pats = []
    for l in open(patch, errors='replace').read().replace('\r\n', '\n').split('\n'):
        m = re.search(r'\b(?:LOG[EWIDV]|TRACE|Log\.[ewidv]|__android_log_print)\s*\([^"]*"([^"]{8,})"', l) if l.startswith('+') else None
        if m:
            parts = [re.escape(x) for x in re.split(r'%[-+ #0-9.]*[a-zA-Z]+|\$\{?\w+\}?', m.group(1)) if len(x.strip()) >= 4]
            if parts:
                pats.append(re.compile('.*'.join(parts)))
    n = 0
    for d in dirs:
        for sub in sorted(glob.glob(os.path.join(d, '*'))):
            g = crash = False
            for lf in glob.glob(os.path.join(sub, 'logcat.txt*')):
                op = gzip.open if lf.endswith('.gz') else open
                with op(lf, 'rt', errors='replace') as fh:
                    for ln in fh:
                        if ' adbd ' in ln or 'ZSTRESS' in ln:
                            continue
                        if 'Fatal signal' in ln or 'FATAL EXCEPTION' in ln:
                            crash = True
                        elif pats and any(p.search(ln) for p in pats):
                            g = True
            if g and not crash and not glob.glob(os.path.join(sub, 'data_app_*crash*')):
                n += 1
    return n


def _trigger_reached(worker, ref, case, dirs, res):
    """A clean run proves a fix only if it got to the crash moment. Same check as the repro author's diagnosis: the
    field checkpoints (written once per crash) against the fixed build's app timeline."""
    from . import author
    from . import groups as _g
    k8 = _g.k8(case['id'])
    try:
        merged = worker._merged(case)
        ctx, _ = author._ctx(case, merged)
        cpp = os.path.join(author.OUT, f'{k8}.checkpoints.json')
        cps = json.load(open(cpp)) if os.path.exists(cpp) else author.make_checkpoints(worker, ref, ctx, k8, BLIND_DENY)
        if not cps:
            return False, 'no field checkpoints to check against'
        hit = author.hit_checkpoints(worker, ref, case, ctx, cps, k8, BLIND_DENY)    # what the crashing run itself needed
        name = f'verify_{dt.datetime.now():%H%M%S}'
        d = author.diagnose(worker, ref, ctx, cps, k8, name, [(name, dict(res, result='clean with the fix'), dirs)], deny=BLIND_DENY) or {}
    except Exception as e:
        return False, f'trigger check failed: {str(e)[:160]}'
    if d.get('all_reached'):
        worker.log(ref, 'verify: trigger reached on the fixed build (every field checkpoint) and no crash')
        return True, 'checkpoints ' + ', '.join(str(c.get('id')) for c in cps) + ' reached'
    ids = [str(c.get('id')) for c in cps]
    reached = {str(x) for x in (d.get('reached') or [])}
    if ids and str(d.get('first_missed')) == ids[-1] and set(ids[:-1]) <= reached:
        # the last checkpoint is the crash itself: on a FIXED build it must not happen; everything before it did
        worker.log(ref, f'verify: every checkpoint before the crash was reached ({", ".join(ids[:-1])}) and the crash ({ids[-1]}) did not happen')
        return True, f'checkpoints {", ".join(ids[:-1])} reached; the crash step {ids[-1]} did not happen'
    if hit and hit.get('reached') is not None and ids:
        # the bar is what the UNFIXED crashing run reached, not the field guess: a field checkpoint the crash itself
        # did without is not needed to prove the fix
        need = [i for i in ids[:-1] if i in {str(x) for x in hit['reached']}]
        skip = [i for i in ids[:-1] if i not in need]
        if need and set(need) <= reached:
            worker.log(ref, f'verify: every checkpoint the crashing run reached ({", ".join(need)}) was reached on the fixed build '
                            f'and it did not crash' + (f'; not needed by the crash itself: {", ".join(skip)}' if skip else ''))
            return True, (f'checkpoints {", ".join(need)} reached (the ones the unfixed crashing run reached); no crash'
                          + (f'; {", ".join(skip)} not needed by the crash' if skip else ''))
    return False, f"checkpoint {d.get('first_missed')} not reached: {str(d.get('why', ''))[:200]}"


def review(case, merged, cfg, patch, n):
    diff = open(patch, errors='replace').read()[:30000]
    prompt = ('# Review this crash fix like a senior reviewer of this codebase. Read the changed files and their callers '
              '(Read/Grep). Check: does it fix the root cause below; thread safety and lock order; leaks/double frees; '
              'behaviour changes for users; error paths; style of the surrounding code.\n\n'
              f'# Case\n```json\n{json.dumps(_ctx(case, merged), indent=1, default=str)[:20000]}\n```\n'
              f'# Diff\n```diff\n{diff}\n```\n'
              '# Answer: ONLY a ```json block: {"verdict": "approve" | "changes", "summary": "...", '
              '"issues": [{"severity": "blocker|major|minor", "file": "...", "line": 0, "problem": "...", "fix": "..."}]}')
    ans = llm.run('fix-review', prompt, cfg, OUT, f"{case['id']}.review{n}", tools='Read,Grep,Glob', cwd=config.LAB, timeout=1200, deny=BLIND_DENY)
    m = re.findall(r'```json\n(.*?)```', ans or '', re.S)
    try:
        r = json.loads(m[-1] if m else ans)
    except (ValueError, TypeError):
        return {'verdict': 'unknown', 'summary': 'review answer was not JSON', 'issues': []}
    r['blocking'] = [i for i in r.get('issues') or [] if i.get('severity') in ('blocker', 'major')]
    return r


def handover(case, merged, cfg, patch, note, rev):
    diff = open(patch, errors='replace').read()[:20000]
    prompt = ('Write the hand-over for a verified crash fix. Plain, specific, no hype. Answer ONLY a ```json block: '
              '{"pr_title": "...", "pr_body": "markdown: problem, root cause, fix, how it was verified (lab runs), risks", '
              '"jira_summary": "...", "jira_description": "...", "slack_message": "3-4 lines for the team channel"}\n\n'
              f'Case: {json.dumps(_ctx(case, merged), default=str)[:15000]}\nVerification: {note}\n'
              + (f'Repro video (mention it in the PR, Jira and Slack text): {case.get("reproVideo")}\n' if case.get('reproVideo') else '')
              + f'Review: {json.dumps(rev, default=str)[:4000]}\nDiff:\n{diff}')
    ans = llm.run('changelog', prompt, cfg, OUT, f"{case['id']}.handover", model=(cfg.get('llm') or {}).get('model_handover') or '')
    m = re.findall(r'```json\n(.*?)```', ans or '', re.S)
    try:
        return json.loads(m[-1] if m else ans)
    except (ValueError, TypeError):
        return {'pr_body': ans or ''}


def _save(case_id, data):
    """Every fix outcome also goes to out/fix/<case>.json, so nothing depends on the board document alone."""
    try:
        d = os.path.join(OUT, 'fix')
        os.makedirs(d, exist_ok=True)
        json.dump(data, open(os.path.join(d, f'{case_id}.json'), 'w'), indent=1, default=str)
        p = os.path.join(OUT, 'patches', f'{case_id}.patch')
        if data.get('patch') and os.path.isdir(os.path.dirname(p)):
            open(os.path.join(d, f'{case_id}.{data.get("status", "x")}.patch'), 'w').write(data['patch'])
    except Exception:
        pass


def _experiment():
    """out/experiment.json: {"tournament": true, "lessons": true} switches the night experiments on (absent = classic loop)."""
    try:
        return json.load(open(os.path.join(OUT, 'experiment.json')))
    except Exception:
        return {}


def run(worker, ref, case, merged, first_patch=None):
    t0 = dt.datetime.now()
    import importlib                                # the trigger check uses author's timeline code: always the current one
    from . import author as _author
    importlib.reload(_author)
    global BLIND_DENY
    if getattr(worker, '_blind', False):            # blind test (any entry point): proposer and reviewer get the read block
        BLIND_DENY = list(getattr(sys.modules.get(type(worker).__module__), 'BLIND_READ_DENY', None) or BLIND_DENY or [])
        worker.log(ref, f'blind fix: proposer and reviewer read with the read block ({len(BLIND_DENY)} rules: .git, lab notes, old results, stray source copies)')
        if not BLIND_DENY:
            raise RuntimeError('blind fix: no read block available, a result would not be blind')
    else:
        BLIND_DENY = None
    from . import llm as _llm
    if not _llm.claude_ok():
        worker.log(ref, 'fix stage skipped: the Claude CLI on the lab Mac cannot run (login expired?). Run `claude` then /login.')
        return None
    history, rounds = [], []
    used_lessons = set()
    tested, best = 0, None                          # best = a lab-verified patch the review still wanted changed
    for n in range(1, ROUNDS + 4):                  # format slips (no diff / corrupt patch) do not use up a lab round
        if tested >= ROUNDS:
            break
        worker.log(ref, f'step 7 propose (round {n}): Claude reads the analysis, the reproduction and the code')
        exp = _experiment()
        lessons_txt = ''
        if exp.get('lessons'):
            from . import lessons as _ls
            lessons_txt, used = _ls.prompt_block(case, kinds=('fix', 'review', 'tooling'), exclude_case=case['id'])
            used_lessons.update(used)
            if used:
                worker.log(ref, f'  lessons from other crashes given to the proposer: {len(used)}')
        if first_patch and n == 1 and os.path.exists(first_patch):
            # TURBO: the fix the engine replay already verified gets the real-tap check first
            patch, ans, err = first_patch, '(early fix, verified by the engine replay)', ''
            worker.log(ref, '  the early fix (engine-replay verified) goes to the real-tap check')
        elif exp.get('tournament'):
            patch, ans, err = tournament(worker, ref, case, merged, worker.cfg, history, n, lessons_txt)
        else:
            patch, ans, err = propose(case, merged, worker.cfg, history, n, lessons=lessons_txt)
        if err:
            worker.log(ref, f'  rejected: {err}')
            history.append(f'## round {n}: rejected before testing: {err}. Answer again with ONE complete unified diff '
                           f'in a ```diff block (git format, every hunk header and context line intact).')
            rounds.append({'round': n, 'result': 'rejected', 'note': err})
            continue
        tested += 1
        worker.log(ref, f'step 8 verify (round {n}): rebuild with the fix and re-run the reproduction')
        ok, note, res = verify(worker, ref, case, patch)
        worker.log(ref, f'  {"VERIFIED" if ok else "not verified"}: {note}')
        diff = open(patch, errors='replace').read()
        try:                                          # every round's full diff stays (the history keeps only 6000 chars)
            os.makedirs(os.path.join(OUT, 'fix'), exist_ok=True)
            open(os.path.join(OUT, 'fix', f"{case['id']}.round{n}.patch"), 'w').write(diff)
        except Exception:
            pass
        if not ok:
            frames = _crash_frames((res or {}).get('dirs') or [])
            if frames:
                worker.log(ref, f'  crash on the fixed build: {frames.splitlines()[0][:160]}')
            history.append(f'## round {n}\n```diff\n{diff[:6000]}\n```\nLab result: {note}'
                           + (f'\nWhere the FIXED build crashed (top frames of its dumps; fix this path too):\n```\n{frames}\n```' if frames else ''))
            rounds.append({'round': n, 'result': 'failed', 'note': note})
            continue
        worker.log(ref, f'step 9 review (round {n}): independent code review')
        rev = review(case, merged, worker.cfg, patch, n)
        worker.log(ref, f"  review: {rev.get('verdict')}; {len(rev.get('blocking') or [])} blocking; {rev.get('summary', '')[:200]}")
        rounds.append({'round': n, 'result': 'verified', 'note': note, 'review': rev.get('verdict')})
        if rev.get('blocking'):
            best = {'diff': diff, 'note': note, 'review': rev, 'answer': ans}
            history.append(f'## round {n}\n```diff\n{diff[:6000]}\n```\nLab: verified. Review asked for changes:\n'
                           + json.dumps(rev['blocking'], indent=1)[:4000])
            continue
        worker.log(ref, 'step 10 hand-over: PR / Jira / Slack drafts')
        ho = handover(case, merged, worker.cfg, patch, note, rev)
        mins = round((dt.datetime.now() - t0).total_seconds() / 60)
        _save(case['id'], {'status': 'fix-verified', 'patch': diff, 'note': note, 'review': rev, 'handover': ho, 'rounds': rounds})
        worker.db.collection('cases').document(case['id']).set({
            'status': 'fix-verified', 'patch': diff[:20000], 'fixVerified': True, 'fixNote': note,
            'fixAnswer': (ans or '')[:6000], 'review': rev, 'handover': ho, 'fixRounds': rounds,
            'fixMinutes': mins}, merge=True)
        try:
            rl = config.repo_path(worker.cfg['measurement']['runlog'])
            runlog.add(rl, 'guard', case['id'], 'Night Shift', 'after', mins, 0, 'fix verified + reviewed',
                       f"{case.get('title', '')[:60]}; review {rev.get('verdict')}")
        except Exception as e:
            worker.log(ref, f'  time log not written: {e}')
        if used_lessons:
            from . import lessons as _ls
            _ls.credit(used_lessons, True)
        worker.log(ref, f'DONE: fix verified, reviewed ({rev.get("verdict")}) and handed over in {mins} min; '
                        f'patch in tools/nightshift/out/patches/{case["id"]}.patch (not committed)')
        return True
    if used_lessons:
        from . import lessons as _ls
        _ls.credit(used_lessons, False)
    if best:                                        # lab-clean but the reviewer wanted changes: keep it for a person
        _save(case['id'], {'status': 'fix-verified-review-changes', 'patch': best['diff'], 'note': best['note'],
                           'review': best['review'], 'rounds': rounds})
        worker.db.collection('cases').document(case['id']).set({
            'status': 'fix-verified-review-changes', 'patch': best['diff'][:20000], 'fixVerified': True,
            'fixNote': best['note'] + ' · code review asked for changes (see review)', 'review': best['review'],
            'fixAnswer': (best['answer'] or '')[:6000], 'fixRounds': rounds,
            'fixMinutes': round((dt.datetime.now() - t0).total_seconds() / 60)}, merge=True)
        worker.log(ref, 'a lab-verified patch exists but the review asked for changes; kept on the case for a person')
        return False
    _save(case['id'], {'status': 'fix-failed', 'rounds': rounds, 'history': history})
    worker.db.collection('cases').document(case['id']).set({'status': 'fix-failed', 'fixVerified': False, 'fixRounds': rounds,
                                                           'fixNote': rounds[-1]['note'] if rounds else 'no rounds'}, merge=True)
    worker.log(ref, f'no verified fix after {tested} lab rounds; the case shows what each round tried')
    return False


def draft_unverified(worker, ref, case, merged):
    """Play-build crash (25 Oct): the Play build cannot be rebuilt with a fix, so the fix is proposed against
    video_gles3jni's code where it lives, reviewed, and handed over as NOT verified on the phone."""
    from . import llm as _llm
    if not _llm.claude_ok():
        worker.log(ref, 'fix stage skipped: the Claude CLI on this computer cannot run (login expired?)')
        return None
    history, note = [], 'NOT verified on the phone: this crash only happens in the full Play app, which cannot be rebuilt with the fix'
    for n in range(1, 4):
        worker.log(ref, f'step 7 propose (round {n}): Claude reads the analysis, the Play-build reproduction and the code')
        patch, ans, err = propose(case, merged, worker.cfg, history, n)
        if err:
            worker.log(ref, f'  rejected: {err}')
            history.append(f'## round {n}: rejected: {err}. Answer again with ONE complete unified diff in a ```diff block.')
            continue
        worker.log(ref, f'step 9 review (round {n}): independent code review (no phone check possible on the Play build)')
        rev = review(case, merged, worker.cfg, patch, n)
        worker.log(ref, f"  review: {rev.get('verdict')}; {len(rev.get('blocking') or [])} blocking; {rev.get('summary', '')[:200]}")
        diff = open(patch, errors='replace').read()
        if rev.get('blocking') and n < 3:
            history.append(f'## round {n}\n```diff\n{diff[:6000]}\n```\nReview asked for changes:\n' + json.dumps(rev['blocking'], indent=1)[:4000])
            continue
        ho = handover(case, merged, worker.cfg, patch, note, rev)
        _save(case['id'], {'status': 'fix-drafted', 'patch': diff, 'note': note, 'review': rev, 'handover': ho})
        worker.db.collection('cases').document(case['id']).set({
            'status': 'fix-drafted', 'patch': diff[:20000], 'fixVerified': False, 'fixNote': note, 'review': rev,
            'handover': ho, 'fixAnswer': (ans or '')[:6000]}, merge=True)
        worker.log(ref, f'DONE: fix drafted and reviewed ({rev.get("verdict")}), NOT verified on the phone (Play build); '
                        f'patch in tools/nightshift/out/patches/{case["id"]}.patch (not committed)')
        return True
    worker.log(ref, 'no usable fix draft after 3 rounds')
    return False


def _blind_setup(worker, ref):
    global BLIND_DENY
    if getattr(worker, '_blind', False):
        BLIND_DENY = list(getattr(sys.modules.get(type(worker).__module__), 'BLIND_READ_DENY', None) or BLIND_DENY or [])
        if not BLIND_DENY:
            raise RuntimeError('blind fix: no read block available, a result would not be blind')
    else:
        BLIND_DENY = None


def verify_replay(worker, ref, case, patch, rp, expect, nrp=9):
    """TURBO: build the fix and run only the engine replay on it (nrp replays in one app session per device).
    -> (ok, note, res). The patch is reverted afterwards; the build cache keeps the fixed APK for the later real-tap check."""
    applied, res = [], {}
    th = getattr(worker, '_spec_th', None)
    if th is not None:                               # the speculative build must be done before this patch is applied
        th.join(2400)
        worker._spec_th = None
    try:
        fl = open(patch + '.flags').read().split() if os.path.exists(patch + '.flags') else []
        r = _git(['apply', *fl, patch])
        if r.returncode:
            return False, f'the fix does not apply: {r.stderr[:200]}', {}
        applied.append(patch)
        worker.log(ref, 'early fix: building the fixed app for the engine replay check')
        if worker.install_app(ref):
            return False, 'the app does not build with this fix', {}
        ndev = 1 + len(getattr(worker, '_lane_serials', None) or [])
        res = worker._ladder_step(ref, {'scenario': rp['scenario'], 'repeat': ndev, 'name': rp['scenario'], 'fast': True,
                                        'env': f'ZESTY_JNI_REPEAT={nrp} '}, expect)
    finally:
        for p_ in reversed(applied):
            fl = open(p_ + '.flags').read().split() if os.path.exists(p_ + '.flags') else []
            _git(['apply', '-R', *fl, p_])
    if res.get('hits'):
        return False, f"the engine replay still crashes the field way with the fix ({res['hits']}/{res['runs']})", res
    clean = (res.get('runs') or 0) - (res.get('errors') or 0)
    if clean < 1:
        return False, f"inconclusive: the replay did not run on the fixed build ({res.get('why', '')})", res
    g = _guard_hits(patch, res.get('dirs') or [])
    why = f"the fix's guard logged in {g[0]} replay session(s)" if g else 'no guard line seen (the replay ran clean)'
    return True, f'engine replay clean on the fixed build: {clean} session(s) x {nrp} replays; {why}', res


def early(worker, ref, case, merged, rp):
    """TURBO 'fix on replay': right after an engine replay hit, write + pick a fix (tournament) and check it with the
    replay only. Returns the kept patch path (verified by the replay) or None. The real-tap repro, the real-tap check
    of THIS patch, the review and the hand-over still come after (fixloop.run(first_patch=...))."""
    import shutil
    from . import author as _author
    from . import llm as _llm
    t0 = dt.datetime.now()
    _blind_setup(worker, ref)
    if not _llm.claude_ok():
        worker.log(ref, 'early fix skipped: the Claude CLI cannot run (login expired?)')
        return None
    c2 = dict(case, repro_dir=rp.get('dir') or '', reproRate='1/1')
    expect = rp.get('expect') or _author.expect_frames(case, (merged or {}).get('analysis') or {})
    history = []
    for n in (1, 2):
        worker.log(ref, f'EARLY FIX (turbo) round {n}: 3 fixes written from the root cause + the engine replay crash')
        worker._spec_build = bool((worker._turbo() or {}).get('spec_build', True))
        try:
            patch, ans, err = tournament(worker, ref, c2, merged, worker.cfg, history, f'e{n}')
        finally:
            worker._spec_build = False
        if err and getattr(worker, '_spec_th', None) is not None:
            worker._spec_th.join(2400)
            worker._spec_th = None
        if err:
            worker.log(ref, f'  early fix rejected: {err}')
            history.append(f'## early round {n}: rejected before testing: {err}')
            continue
        ok, note, res = verify_replay(worker, ref, c2, patch, rp, expect,
                                      int((worker._turbo() or {}).get('replay_verify_runs') or 9))
        worker.log(ref, f'  early fix {"REPLAY-VERIFIED" if ok else "not verified"}: {note}')
        if ok:
            keep = os.path.join(OUT, 'patches', f"{case['id']}.early.patch")
            shutil.copyfile(patch, keep)
            if os.path.exists(patch + '.flags'):
                shutil.copyfile(patch + '.flags', keep + '.flags')
            mins = round((dt.datetime.now() - t0).total_seconds() / 60, 1)
            try:
                worker.db.collection('cases').document(case['id']).set({'earlyFix': {
                    'note': note, 'patch': open(keep, errors='replace').read()[:20000], 'minutes': mins,
                    'status': 'replay-verified; real-tap check pending'}}, merge=True)
            except Exception:
                pass
            worker.log(ref, f'FIX READY (engine-replay verified) in {mins} min of fix work; the real-tap repro and check come next')
            return keep
        frames = _crash_frames((res or {}).get('dirs') or [])
        history.append(f'## early round {n}\n```diff\n{open(patch, errors="replace").read()[:6000]}\n```\nReplay result: {note}'
                       + (f'\nWhere the FIXED build crashed:\n```\n{frames}\n```' if frames else ''))
    return None
