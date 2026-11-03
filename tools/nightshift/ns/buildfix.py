"""Lab build self-repair (3 Nov).

The release recipe builds video_gles3jni with its Kotlin modules switched to the commits the shipped app used. Parts of
video_gles3jni that do NOT switch with them (the lab app's own screens, plain library folders, Gradle files) can then
fail to compile: 3 Nov it was React Native in java-common, then colorpicker, then the lab's music screen. Each time a
person read the compile errors and wrote a small lab-only patch. Now Night Shift does that itself:

  1. the compile errors (every `e: file:` / `error:` line) go to Claude with read access to the lab folder;
  2. Claude answers with a unified diff that makes it COMPILE, changing as little as possible;
  3. the diff may NOT touch C/C++ (the engine stays exactly what the users ran) and may not change what a release
     Kotlin file DOES (only stand-ins, missing imports/ids, Gradle lines, or the lab app's own screens);
  4. the diff is applied in the lab folder and the build runs again (max 2 repairs per job);
  5. a diff that made the build pass is kept in out/labcompat/<folder>.diff and applied again on every later build of
     that folder (the folder is reset to its commits before each build). Lab folder only, never a working copy.
"""
import datetime as dt
import os
import re
import subprocess

from . import config

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, 'out', 'labcompat')
MAX_PER_JOB = 2
LLM_SEC = 900
NO_TOUCH = re.compile(r'\.(c|cc|cpp|cxx|h|hh|hpp|S|cmake)$|(^|/)CMakeLists\.txt$|(^|/)app/src/main/cpp/', re.I)


def errors_from(lines):
    """Every compile error line, plus the lines right after gradle's '* What went wrong:' (that header alone says
    nothing: 3 Nov the first self-repair got only the header and had nothing to work from)."""
    out, seen = [], set()
    lines = [re.sub(r'\x1b\[[0-9;]*m', '', str(l)).rstrip() for l in lines or []]
    for i, l in enumerate(lines):
        pick = []
        if ('e: file:' in l or l.lstrip().startswith('e: ') or ': error:' in l or 'Unresolved reference' in l
                or 'cannot find symbol' in l or 'A problem occurred' in l or 'Execution failed for task' in l
                or 'Manifest merger failed' in l or 'AAPT: error' in l or 'Could not resolve' in l):
            pick = [l]
        elif 'What went wrong' in l:
            pick = [x for x in lines[i + 1:i + 8] if x.strip() and not x.startswith('* Try')]
        for x in pick:
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out[:150]


def _patch(wt, diff, dry):
    a = ['patch', '-p1', '--forward', '--batch', '-d', wt] + (['--dry-run'] if dry else [])
    r = subprocess.run(a, input=diff, capture_output=True, text=True, timeout=120)
    return r.returncode == 0, (r.stdout + r.stderr)[-600:]


def reapply(wt, log=print):
    """Every kept repair for this lab folder, again after the folder was reset (idempotent: --forward)."""
    p = os.path.join(OUT, os.path.basename(wt.rstrip('/')) + '.diff')
    if not os.path.exists(p):
        return
    diff = open(p, encoding='utf-8', errors='replace').read()
    ok, msg = _patch(wt, diff, dry=False)
    log(f'lab build: kept build repairs re-applied ({os.path.relpath(p, HERE)})' if ok or 'Reversed' in msg else
        f'lab build: a kept build repair no longer applies ({msg[-160:]}); the build will say if it is still needed')


def try_fix(worker, ref, wt, lines, what):
    """-> True when a repair was applied (build again), False when not."""
    n = getattr(worker, '_buildfix_n', 0)
    if n >= MAX_PER_JOB:
        return False
    worker._buildfix_n = n + 1
    errs = errors_from(lines)
    if not errs:
        worker.log(ref, 'build self-repair: no compile error lines to work from; skipped')
        return False
    rid = f'b{int(dt.datetime.now().timestamp())}'
    worker.log(ref, f'build self-repair ({n + 1}/{MAX_PER_JOB}): {len(errs)} compile error line(s); asking Claude for a lab-only patch')
    prompt = (
        'You repair a LAB build so it compiles. The folder (your working directory) is a throw-away lab copy of '
        f'video_gles3jni: {what}. It must build the code the users ran, so:\n'
        '- NEVER change C/C++ (anything under app/src/main/cpp, *.cpp, *.h, CMake).\n'
        '- Do not change what a release Kotlin/Java file DOES. Allowed: add a missing import, a tiny stand-in class or '
        'resource id the release code expects, a Gradle line, or adapt the LAB APP\'S OWN screens '
        '(app/src/main/java, app/src/main/res: a test harness, not the users\' code) to the release modules; deleting a '
        'lab-app screen file that is not used by the editor is allowed.\n'
        '- Smallest change that makes ALL the errors below go away. Read the files first (Read/Grep/Glob).\n\n'
        'Answer with ONE ```diff block: a unified diff with paths a/<path> b/<path> relative to the folder '
        '(new files: --- /dev/null). Then 1-3 sentences: what was wrong and why the patch is safe.\n\n'
        '# Compile errors\n```\n' + '\n'.join(errs) + '\n```\n')
    try:
        from . import llm
        txt = llm.run('lab-buildfix', prompt, worker.cfg, OUT, rid, tools='Read,Grep,Glob', cwd=wt, timeout=LLM_SEC)
    except Exception as e:
        worker.log(ref, f'build self-repair: no answer ({str(e)[:120]})')
        return False
    diff = (re.findall(r'```diff\n(.*?)```', txt or '', re.S) or [''])[0]
    if not diff.strip():
        worker.log(ref, 'build self-repair: the answer had no patch; nothing changed')
        return False
    diff = diff if diff.endswith('\n') else diff + '\n'
    files = sorted(set(re.findall(r'^\+\+\+ b/(\S+)', diff, re.M)) | set(re.findall(r'^--- a/(\S+)', diff, re.M)))
    bad = [f for f in files if NO_TOUCH.search(f)]
    if bad or not files:
        worker.log(ref, f'build self-repair: patch rejected, it touches engine code {bad}' if bad else
                        'build self-repair: patch names no files; rejected')
        return False
    ok, msg = _patch(wt, diff, dry=True)
    if not ok:
        worker.log(ref, f'build self-repair: patch does not apply ({msg[-200:]}); nothing changed')
        return False
    _patch(wt, diff, dry=False)
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, f'{rid}.diff'), 'w').write(diff)
    worker._buildfix_pending = (wt, rid, diff, files)
    why = re.sub(r'```.*?```', '', txt or '', flags=re.S).strip().replace('\n', ' ')[:300]
    worker.log(ref, f'build self-repair: patch {rid} applied in the lab folder ({", ".join(files)[:300]}): {why}; building again')
    return True


def built_ok(worker, ref):
    """Call after a build succeeded: keep the pending repair for this lab folder."""
    p_ = getattr(worker, '_buildfix_pending', None)
    if not p_:
        return
    wt, rid, diff, files = p_
    worker._buildfix_pending = None
    os.makedirs(OUT, exist_ok=True)
    keep = os.path.join(OUT, os.path.basename(wt.rstrip('/')) + '.diff')
    with open(keep, 'a') as f:
        f.write(diff)
    worker.log(ref, f'build self-repair KEPT ({rid}): the lab build compiles with it; kept for this folder in '
                    f'{os.path.relpath(keep, HERE)} (lab only; files: {", ".join(files)[:200]})')
