"""The Kotlin side of a CRASH (28 Oct, no AI). The crash pipeline (root cause, lab update, fix) used to guess the Kotlin
callers ("java-common is missing for this build") while the PR review already had the map. This builds, for one case:
  - the Kotlin/Java code AS SHIPPED in that build: each Kotlin repo at its last commit before the field build's engine
    commit (read-only copy ~/.nightshift_kotlin/<repo>@build), next to the newest sprint copy the fix is written against;
  - the bridge: engine functions on the crash stack and engine messages in the field log (MsgSeekVideo, ...) -> the JNI
    function -> the Kotlin `external fun` -> every Kotlin call site with file:line and the code around it.
The text goes into the prompts; the folders are readable by the model."""
import datetime as dt
import os
import re
import shutil
import subprocess

from . import config, kotlinctx

BUILD_SUFFIX = '@build'


def _short(fn):
    fn = re.sub(r'\(.*$', '', str(fn or ''))
    while re.search(r'<[^<>]*>', fn):
        fn = re.sub(r'<[^<>]*>', '', fn)
    return fn.split('::')[-1].split(' ')[-1].strip()


def engine_names(case, merged):
    names = set()
    for f in (case or {}).get('frames') or []:
        if isinstance(f, dict) and 'MYJNILIB' in str(f.get('lib') or '') and f.get('func'):
            names.add(_short(f['func']))
    for s in (((merged or {}).get('fb') or {}).get('top') or []):
        if 'MYJNILIB' in str(s):
            names.add(_short(str(s).split(' ', 1)[-1]))
    return {n for n in names if len(n) > 3 and not n.startswith(('__', 'operator'))}


def field_messages(case):
    txt = ' '.join(str(x) for x in ((case or {}).get('breadcrumbs') or []))
    return sorted(set(re.findall(r'\b(Msg[A-Z]\w+)', txt)) - {'MsgLooper', 'MsgQueue'})


def _bridge_msgs(native_root, msgs):
    """JNI functions that post one of these looper messages -> their Kotlin names."""
    jni = kotlinctx._read(os.path.join(native_root, 'app/src/main/cpp/JNI/JNI.cpp'))
    reg = dict((j, n) for n, j in re.findall(r'\{\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*\(void\s*\*\)\s*(JNI_\w+)\s*\}', jni))
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'\b(JNI_\w+)\s*\(\s*JNIEnv', jni)]
    out = []
    for k, (pos, jname) in enumerate(starts):
        body = jni[pos:starts[k + 1][0] if k + 1 < len(starts) else len(jni)]
        via = [m for m in msgs if re.search(r'\b' + m + r'\b', body)]
        if via and jname in reg:
            out.append({'kotlin': reg[jname], 'jni': jname, 'via': via, 'calls': []})
    return out


def _build_date(case, cfg):
    try:
        from . import source
        vers = case.get('versions') or case.get('sync_versions') or {}
        hit = [k for k, v in vers.items() if (v or 0) > 0] if isinstance(vers, dict) else []
        top = hit[0] if hit else ''
        m = re.search(r'\((\d+)\)', top)
        pin = (source.ref_for(m.group(1), top.split(' ')[0], cfg) or {}).get('sha') if m else None
        if not pin:
            return None, None
        r = subprocess.run(['git', 'show', '-s', '--format=%cI', pin], cwd=config.REPO, capture_output=True, text=True, timeout=30)
        return (r.stdout.strip() or None), pin
    except Exception:
        return None, None


def at_build(repos, when, log=print):
    """Read-only copies of the Kotlin repos as they were when the field build was made. [{repo, branch, sha, path}]"""
    out = []
    try:
        since = (dt.datetime.fromisoformat(when.replace('Z', '+00:00')) - dt.timedelta(days=90)).date().isoformat()
    except Exception:
        return out
    # 28 Oct: one slow repo held a job for 11 min (sequential fetches, 600 s each). Fetch in parallel with a shorter
    # timeout, and skip a repo for 6 h after it timed out (its newest copy is still used by the caller).
    import json as _json
    import time as _time
    from concurrent.futures import ThreadPoolExecutor
    slow_f = os.path.join(kotlinctx.ROOT, '.at_build_slow.json')
    try:
        slow = _json.load(open(slow_f))
    except Exception:
        slow = {}

    def one(r):
        src = r['path']
        if _time.time() - float(slow.get(r['repo'], 0)) < 6 * 3600:
            return None, f'{r["repo"]}: skipped (fetch timed out in the last 6 h)'
        try:
            f = kotlinctx._git(['fetch', '-q', f'--shallow-since={since}', 'origin', r['branch']], cwd=src, timeout=180)
            if f.returncode and 'no commits selected' in (f.stderr or ''):
                # 2 Nov: a quiet repo (image_editor_java) had no commits in that 90-day window: take its last 50 instead
                f = kotlinctx._git(['fetch', '-q', '--depth', '50', 'origin', r['branch']], cwd=src, timeout=180)
            if f.returncode:
                return None, f'{r["repo"]}: {f.stderr.strip()[:120]}'
            sha = kotlinctx._git(['rev-list', '-1', f'--before={when}', 'FETCH_HEAD'], cwd=src).stdout.strip()
            if not sha:
                return None, None
            dest = src + BUILD_SUFFIX
            mark = os.path.join(dest, '.ns_sha')
            if not (os.path.exists(mark) and open(mark).read().strip() == sha):
                shutil.rmtree(dest, ignore_errors=True)
                os.makedirs(dest, exist_ok=True)
                a = subprocess.run(f'git archive {sha} | tar -x -C "{dest}"', shell=True, cwd=src, capture_output=True,
                                   text=True, timeout=600)
                if a.returncode:
                    return None, f'{r["repo"]}: {a.stderr.strip()[:120]}'
                open(mark, 'w').write(sha)
            return {'repo': r['repo'], 'branch': r['branch'] + ' at build', 'sha': sha[:10], 'path': dest}, None
        except subprocess.TimeoutExpired as e:
            slow[r['repo']] = _time.time()
            return None, f'{r["repo"]}: {str(e)[:120]}'
        except OSError as e:
            return None, f'{r["repo"]}: {str(e)[:120]}'

    with ThreadPoolExecutor(max_workers=max(1, min(6, len(repos)))) as ex:
        for res, msg in ex.map(one, repos):
            if msg:
                log(f'Kotlin at build: {msg}')
            if res:
                out.append(res)
    try:
        _json.dump(slow, open(slow_f, 'w'))
    except Exception:
        pass
    return out


def crash_context(cfg, case, merged, log=print):
    """(prompt text, readable paths). Empty text when no Kotlin repo is reachable."""
    try:
        repos = kotlinctx.sync(cfg, log)
    except Exception as e:
        log(f'Kotlin map: repos not reachable ({str(e)[:120]})')
        return '', []
    if not repos:
        return '', []
    when, pin = _build_date(case or {}, cfg)
    built = at_build(repos, when, log) if when else []
    scan = built or repos                                 # call sites as shipped when available
    names, msgs = engine_names(case, merged), field_messages(case)
    br = kotlinctx.bridge(config.REPO, names) if names else []
    seen = {b['jni'] for b in br}
    br += [b for b in _bridge_msgs(config.REPO, msgs) if b['jni'] not in seen]
    blocks = []
    for b in br[:10]:
        decl, calls = kotlinctx.callers([r['path'] for r in scan], b['kotlin'], cap=8)
        blocks.append(f"### Kotlin `{b['kotlin']}` -> {b['jni']}" + (f" -> {', '.join(b['via'])}" if b['via'] else '')
                      + (f" -> {', '.join(b['calls'])}" if b['calls'] else '')
                      + f"\nDeclared: {', '.join(decl) or 'not found'}\n"
                      + ('\n'.join(f"Call at {c['at']}:\n```\n{c['code']}\n```" for c in calls) or 'No Kotlin call site found.'))
    paths = [r['path'] for r in built] + [r['path'] for r in repos]
    lab = [os.path.join(config.LAB, r['repo']) for r in repos if os.path.isdir(os.path.join(config.LAB, r['repo']))]
    text = ('# Kotlin side of this crash (Night Shift map, no AI: check it, do not guess)\n'
            + (f"Kotlin AS SHIPPED in this build (each repo at its last commit before the field engine commit {pin[:10] if pin else '?'}, "
               f"{when or '?'}): " + ', '.join(f"{r['path']} ({r['sha']})" for r in built) + '\n' if built else
               'Kotlin as shipped: not available (field commit unknown); the call sites below are from the newest sprint.\n')
            + 'Newest sprint copies (what a fix changes today): ' + ', '.join(f"{r['path']} ({r['repo']} {r['branch']}@{r['sha'][:7]})" for r in repos) + '\n'
            + (f"Module folders in the lab working copy (fix diffs use these paths, e.g. b/{os.path.basename(lab[0])}/src/...): "
               + ', '.join(lab) + '\n' if lab else '')
            + 'You may Read/Grep every folder above. A Kotlin caller with file:line is evidence; java-common and the other '
              'modules are NOT missing: they are here. They are SEPARATE git repos: `git show <engine commit>:java-common/...` in '
              'video_gles3jni finds nothing, so never conclude "java-common is missing"; read the folders above instead.\n'
            + f"Engine functions on the crash stack: {', '.join(sorted(names)) or '-'}; engine messages in the field log: {', '.join(msgs) or '-'}\n\n"
            + ('\n\n'.join(blocks) if blocks else 'No JNI entry point reaches these engine functions or messages.') + '\n\n')
    return text[:30000], paths


_MEMO = {}


def cached(cfg, case, merged, log=print, ttl=1800):
    """crash_context once per case per half hour (the 3 tournament candidates and the critic share it)."""
    import time
    k = str((case or {}).get('id') or (merged or {}).get('id') or '')
    hit = _MEMO.get(k)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        v = crash_context(cfg, case or {}, merged or {}, log)
    except Exception as e:
        log(f'Kotlin map skipped: {str(e)[:160]}')
        v = ('', [])
    _MEMO[k] = (time.time(), v)
    return v


def owner_of(merged):
    return str(((merged or {}).get('analysis') or {}).get('owner') or '')


KOTLIN_RULE = ('OWNER = app-java (the Kotlin/Java app made the wrong call). Your diff MUST contain the Kotlin/Java fix of '
               'that call (the cause), at the caller shown in the Kotlin map with file:line, in the module folder of the '
               'lab working copy (b/<module>/src/...). Add the engine guard too (one check + LOGE, defence in depth) so the '
               'native side stops crashing even if a wrong call comes again; it is the extra safety net, not the fix. An '
               'engine-only diff is incomplete for this case. Rules for the Kotlin part: (1) never add a NEW blocking engine call on '
               'the UI thread to check state (a looper Get / wait with no timeout is an ANR risk): use '
               'state the Kotlin side already keeps, or keep it in sync from the results the engine already returns; '
               '(2) fix the SOURCE of the wrong value (where the app-side state first goes out of step with the engine) or guard '
               'EVERY caller of the wrong call: Grep all call sites, a guard in one caller is not enough.\n')
