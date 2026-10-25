"""Night Shift repro author: writes, runs and fixes its own lab reproduction scripts.

When a Reproduce click finds no registered repro for a crash (or the registered ladder fails), the worker calls
author.run(). For each ladder level (2 real user flow -> 3 environment -> 4 timing -> 5 debug hook) Claude writes a
scenario for tools/stress/scenarios.py, Night Shift runs it on the lab phone, reads what happened (UI stuck, other
crash, no crash, wrong frames) and gives that back to Claude, which fixes the script. It stops at the first run whose
lab dump has every field frame and registers that step in lab_repros.json so the next click starts from it.

Level 5 may add a C++/Java debug hook (default OFF, switched by a debug.zesty.hook.* system property). The hook patch is
applied for the build and reverted right after; it is never committed. Nothing here touches git history.
"""
import ast
import datetime as dt
import glob
import json
import os
import re
import sys
import subprocess

from . import config, llm
if not hasattr(config, 'profile'):                 # long-running worker: config.py is not in its per-job reload list;
    import importlib as _il                          # pick up the profile helpers once (LAB survives the reload)
    _il.reload(config)

try:                                                   # project profile (nightshift.yaml): app package + our code packages
    _PROF = config.profile()
except Exception:
    _PROF = {'package': 'com.myzesty', 'code_packages': ['com.video.', 'com.common.', 'com.myzesty.']}
_PKG = _PROF['package']
_PKG_RX = re.escape(_PKG)
_CODE_PKGS = tuple(_PROF['code_packages'])

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'out', 'author')
AUTO = os.path.join(config.REPO, 'tools', 'stress', 'auto')
HOOKS = os.path.join(HERE, '..', 'out', 'hooks')
SIDE = os.path.join(HERE, '..', 'lab_repros.json')

LEVELS = [
    (2, 'real user flow', 'Do what the field user did, at human speed, with the media/flow the evidence points to. No hooks, no special device state.'),
    (3, 'environment', 'Same flow plus the device conditions the evidence suggests (ed.dev has clear_app_cache, network, slow_network, dark_mode, rotate, font_scale; the lab phone has warm caches and fast wifi, so anything the field user waited for loads instantly here unless you clear the cache or cut/slow the network): memory pressure (ed.dev.sh("am send-trim-memory ...")), backgrounding, camera or another codec user, rotation/dark mode/config change, offline network, low storage, slow storage.'),
    (4, 'timing', 'Push the race: repeat the risky action quickly, storm it, or hit the exact window the timeline shows (e.g. during load/transcode/export/teardown). Still no code changes.'),
    (5, 'debug hook', 'Real triggers failed. Add the smallest debug hook to the app code that forces the field condition you are sure of (e.g. a decoder that never returns, a null from a lookup, a slow teardown). Guard it with a system property debug.zesty.hook.<name> (default off; read it like app/src/main/cpp/utils/EngineDebug.h does) and switch it on from the scenario with ed.dev.setprop(..., "1"), off in a finally.'),
]
TRIES_PER_LEVEL = 3
BUDGET_MIN = 170
AUTHOR_SEC = 360        # Claude writing one recipe (one retry at 2x if it times out)
DIAG_SEC = 240          # diagnosis of a miss
CHECKPOINT_SEC = 300    # field checkpoints (once per crash)
LEVEL_MIN = 40          # per natural level, so L5 (hook) is always reached inside the budget


def _short(fn):
    fn = re.sub(r'\s*\+\s*\d+$', '', str(fn or '')).strip()
    while re.search(r'<[^<>]*>', fn):                      # drop template args: Set<unsigned long> -> Set
        fn = re.sub(r'<[^<>]*>', '', fn)
    fn = re.sub(r'\(.*$', '', fn)
    return fn.split(' ')[-1]


def _with_case_file(case):
    """The Firestore case may lack frames/breadcrumbs/kind; the analysis case file (out/*_<id>_case_file.json) has them."""
    case = dict(case or {})
    if case.get('frames') and case.get('breadcrumbs') and case.get('kind'):
        return case
    try:
        cid = case.get('id') or ''
        cf = next(iter(glob.glob(os.path.join(HERE, '..', 'out', f'*_{cid}_case_file.json')))) if cid else None
        if cf:
            cj = json.load(open(cf))
            for k in ('frames', 'breadcrumbs', 'kind', 'title'):
                if not case.get(k) and cj.get(k):
                    case[k] = cj[k]
    except Exception:
        pass
    return case


# Message-queue plumbing: every JNI call that waits on the engine's message thread has these frames, so they never
# tell one ANR from another (a getMediaDuration ANR matched a freezeProgress card on 2026-10-20 because of them).
LOOPER_PLUMBING = ('Message::GetResult', 'MsgLooper::Get', 'MsgLooper::WaitFor', 'Message::Wait', 'MsgLooper::Set',
                   'MsgLooper::Send', 'Message::SetResult')


def looper_wait_frames(case):
    """ANR whose main thread is blocked in MsgLooper::Get: the match must be the main thread's OWN entry into the
    engine (the JNI_* function) plus its first app Java frame, both on the main thread ('MAIN:'). Returns [] for any
    other case."""
    case = _with_case_file(case)
    frames = case.get('frames') or []
    names = [_short(f.get('func') if isinstance(f, dict) else f) for f in frames]
    if str(case.get('kind') or '').upper() != 'ANR' or not any(n in LOOPER_PLUMBING for n in names):
        return []
    jni = next((n for n in names if n.startswith(('JNI_', 'Java_'))), '')
    # the Java native method that enters that JNI function (e.g. Player.freezeProgress(Native method)): phone dumps of a
    # JIT/OSR-compiled main thread often show only the Java side, so either one counts ('a|b' = any of them)
    jwrap = next(((f.get('func') if isinstance(f, dict) else str(f)) for f in frames
                  if 'Native method' in str((f.get('file') if isinstance(f, dict) else '') or '')
                  and '$Companion' not in str(f.get('func') if isinstance(f, dict) else f)), '')
    if jni and jwrap:
        jni = f'{jni}|{jwrap}' 
    app = ''
    for f in frames:
        fn = (f.get('func') if isinstance(f, dict) else str(f)) or ''
        fn = re.sub(r'\$default$', '', fn.strip())
        if fn.startswith(_CODE_PKGS) and '$Companion' not in fn \
                and not fn.endswith(('.freezeProgress', 'Native method')) and '.' in fn and '::' not in fn:
            if any(fn.endswith('.' + x) for x in ('invokeSuspend', 'resumeWith', 'run', 'invoke', 'onMessageEvent')):
                continue
            app = fn
            break
    return [f'MAIN:{x}' for x in (jni, app) if x]


def busy_window(case):
    """Field side of a looper-wait ANR: which engine message made the message thread slow. Breadcrumbs (newest first
    in the case) log 'WaitFor TIMEOUT ... Queue busy' when a caller gave up waiting; the engine messages handled just
    before that are the suspects, and the last messages before the ANR are the ones still in flight."""
    case = _with_case_file(case)
    bc = [str(b) for b in (case.get('breadcrumbs') or [])]
    if not bc:
        return {}
    ts = lambda b: (re.match(r'(\d\d:\d\d:\d\d\.\d+)', b) or [None, ''])[1]
    chron = sorted(bc, key=ts)                       # oldest first
    msg = lambda b: next((m for m in re.findall(r'\b(Msg[A-Z]\w+)', b) if m != 'MsgLooper'), '')
    out = {}
    busy = [i for i, b in enumerate(chron) if re.search(r'TIMEOUT|Queue busy|status: timeout', b)]
    if busy:
        i = busy[0]
        before = [(ts(b), msg(b)) for b in chron[:i] if msg(b) and 'TIMEOUT' not in b][-4:]
        out['first_busy_at'] = ts(chron[i])
        out['busy_line'] = chron[i][:200]
        out['handled_just_before'] = [f'{t} {m}' for t, m in before]
        out['suspect'] = before[-1][1] if before else ''
    out['last_engine_messages'] = [f'{ts(b)} {msg(b)}' for b in chron if msg(b)][-6:]
    return out


def engine_busy(trace_text):
    """Lab side of a looper-wait ANR: the engine's message thread (the one running MsgLooper::ProcessMessages) at the
    moment of the ANR, as 'A <- B <- C' of its app frames (top first). This is WHAT MADE IT SLOW; '' if not found."""
    for blk in re.split(r'\n\s*\n', trace_text or ''):
        if 'MsgLooper::ProcessMessages' not in blk or blk.lstrip().startswith('"main"'):
            continue
        fr = []
        for ln in blk.splitlines():
            m = re.search(r'\((?:[^()]*?\s)?([A-Za-z_][\w:<>, ]*::~?\w+|AMediaCodec_\w+|\w+::\w+)\+\d+\)', ln)
            if m:
                f = _short(m.group(1))
                if f and f not in fr and not f.startswith(('std::', 'android::')):
                    fr.append(f)
            if 'MsgLooper::ProcessMessages' in ln:
                break
        if fr:
            return ' <- '.join(fr[:6])
    return ''


LOOPER_RULE = ("This is a LOOPER-WAIT ANR: the main thread is only the victim, blocked in MsgLooper::Get while the engine's "
               "message thread is busy. The root cause is WHAT MADE THE MESSAGE THREAD SLOW (see engine_busy_window and "
               "the lab's engine-thread stack). Adding a timeout to Get, making the call non-blocking, or skipping the wait "
               "only hides it: never propose that as the fix. Fix the slow work itself (skip it when nothing changed, do "
               "only the part that changed, cache it, or move it off the message thread).")


def expect_frames(case, analysis=None):
    """Frames a lab dump must contain to count as THE field crash. ANR: the main thread's app frames plus the frames of
    the wait chain; crash: the top named app frames."""
    looper_wait = looper_wait_frames(case)
    if looper_wait:                                  # main thread waits on the engine's message thread: the generic
        return looper_wait                           # MsgLooper::Get/Message::GetResult frames match ANY such ANR
    ex = []
    for f in (case.get('frames') or []):
        fn = f.get('func') if isinstance(f, dict) else f
        lib = (f.get('lib') if isinstance(f, dict) else '') or ''
        fn = _short(fn)
        if not fn or fn.startswith(('__', 'std::', 'art::', 'android.', 'com.android.', 'dalvik.', 'libcore.', 'java.',
                                    'javax.', 'sun.', 'kotlin.', 'kotlinx.', 'libc', 'pthread_', 'android::')) \
                or 'libc.so' in lib or 'libutils.so' in lib:   # android::Looper::pollOnce etc. sit in EVERY idle thread
            continue
        if fn not in ex:
            ex.append(fn)
        if len(ex) >= 2:
            break
    # Java crash whose dump starts in the framework (the throwing app method is only in the issue title, the exception
    # in the subtitle): match the app method and the exception class, never generic frames like ZygoteInit.main
    title = (case.get('title') or '').strip()
    framework = ('android.', 'androidx.', 'com.android.', 'com.google.android.', 'dalvik.', 'libcore.', 'java.', 'javax.',
                 'sun.', 'kotlin.', 'kotlinx.')
    if (re.fullmatch(r'[a-z]\w*(\.\w+)+\.[\w$]+', title) and not title.startswith(framework) and title not in ex
            and not any(isinstance(f, str) and title in f for f in (case.get('frames') or []))):
        ex.insert(0, title)
        m = re.match(r'([a-z][\w.]*\.[A-Z]\w*(?:Exception|Error))', case.get('subtitle') or '')
        if m and m.group(1) not in ex:
            ex.insert(1, m.group(1))
    def _as_list(x):                                 # the analysis may give a dict or a string where a list is usual
        return x if isinstance(x, list) else list(x.values()) if isinstance(x, dict) else [x] if x else []
    for ch in _as_list((analysis or {}).get('wait_chains'))[:1]:
        ch = ch if isinstance(ch, dict) else {'links': _as_list(ch)}
        for link in _as_list(ch.get('links') or ch.get('chain'))[:3]:
            fn = _short(link.get('frame') if isinstance(link, dict) else link)
            if fn and fn not in ex and '::' in fn:
                ex.append(fn)
    if not ex and str(case.get('kind') or '').upper() == 'ANR' and 'nativePollOnce' in (case.get('title') or '') + json.dumps(case.get('frames') or []):
        # an ANR whose main thread is IDLE in its looper (no app frame anywhere): the match is the ANR itself plus the
        # idle main thread; 'MAIN:' = must be in the main thread's own stack of the ANR dump, not in any thread
        return [f'ANR in {_PKG}', 'MAIN:android.os.MessageQueue.nativePollOnce']
    if not ex:
        ex = art_abort_pattern(case)
    return ex[:4]


def art_abort_pattern(case):
    """A field stack with no symbols at all, shaped libc -> libart -> libbase (LogMessage) -> ART, is ART's own fatal
    abort (JNI error, failed CHECK). The lab tombstone names those frames, so the run must show the same abort path.
    Weaker than a frame match: the board says so (pattern match)."""
    libs = [((f.get('lib') if isinstance(f, dict) else '') or '') for f in (case.get('frames') or [])][:6]
    named = [f for f in (case.get('frames') or []) if isinstance(f, dict) and f.get('func')]
    sig = ' '.join(filter(None, [case.get('subtitle') or '', case.get('title') or '']))
    if not named and 'SIGABRT' in sig and libs[:1] == ['libc.so'] and 'libart.so' in libs[:4] and 'libbase.so' in libs[:5]:
        return ['SIGABRT', 'art::Runtime::Abort', 'LogMessage']
    return []


def deny_check(worker, ref, deny):
    """Blind tests only: plant a secret word in every blocked place, ask Claude (same tools, same block list) to read
    and grep for it. If it can, the block is not enforced and the test would not be blind."""
    import secrets
    tok = 'NSCANARY' + secrets.token_hex(6)
    spots = ['tools/nightshift/out/ns_canary.txt', 'ns_canary_root.md', 'stress_results/ns_canary.txt',
             'tools/stress/auto/ns_canary.txt', '.idea/ns_canary.txt',
             'app/src/main/cpp/player/MsgLooper.cpp.nscanary', 'app/src/main/cpp/player/.fuse_hidden_nscanary']   # stray source copies
    made = []
    for sp in spots:
        fp = os.path.join(config.REPO, sp)
        if os.path.isdir(os.path.dirname(fp)):
            open(fp, 'w').write(f'secret {tok}\n')
            made.append(sp)
    try:
        txt = llm.run('repro-author', 'Permissions self-test. Use Read on each of these files and print what they '
                      f'contain: {", ".join(made)}. Then Grep the whole repository for the word NSCANARY and print every '
                      'match. If a tool is refused, say REFUSED for it. Do nothing else.',
                      worker.cfg, OUT, 'deny_check', tools='Read,Grep,Glob', cwd=config.LAB, timeout=300, deny=deny) or ''
    finally:
        for sp in made:
            try:
                os.remove(os.path.join(config.REPO, sp))
            except OSError:
                pass
    if not txt.strip():
        return False, 'no answer from the self-test'
    return tok not in txt, [sp for sp in made if tok in txt][:3] or 'a planted file'


def field_signatures(ctx, limit=25):
    """Error lines the field instances printed before the crash, as word sequences (numbers, ids and paths dropped).
    Seeing one in a lab log without the crash = a near miss: the recipe reached the broken state, the race just lost."""
    out = []
    for i in ((ctx.get('every_field_instance') or {}).get('instances')) or []:
        for ln in (i.get('timeline_last_lines') or '').splitlines():
            if not re.search(r'\bERROR\b|exception|failed|bigger than', ln, re.I):
                continue
            msg = re.sub(r'^.*?line:\s*\d+\s*', '', ln)
            words = re.findall(r'[A-Za-z_]{3,}', msg)[:7]
            sig = ' '.join(words).lower()
            if len(words) >= 3 and sig not in out:
                out.append(sig)
    return out[:limit]


def _near_miss(run_dirs, sigs):
    """First field error signature found in the lab logcat of these runs, or ''."""
    import gzip
    if not sigs:
        return ''
    for d in run_dirs:
        for lf in glob.glob(os.path.join(d, '*', 'logcat.txt*')):
            try:
                op = gzip.open if lf.endswith('.gz') else open
                with op(lf, 'rt', errors='replace') as fh:
                    for ln in fh:
                        if 'error' not in ln.lower() and 'fail' not in ln.lower() and 'bigger' not in ln.lower():
                            continue
                        norm = ' '.join(re.findall(r'[A-Za-z_]{3,}', ln)).lower()
                        for sg in sigs:
                            if sg in norm:
                                return sg[:80]
            except Exception:
                continue
    return ''


def start_level(ctx):
    """Where to start the ladder, from the field reports themselves. When the reports show the screen was torn down or
    recreated, or something was downloading/transcoding at the crash, the plain user flow on a lab phone with warm
    caches and fast wifi almost never hits it: start at level 3 (environment) instead of spending level 2's time."""
    inst = ((ctx.get('every_field_instance') or {}).get('instances')) or []
    why = []
    rec = sum(1 for i in inst if (i.get('facts') or {}).get('recreate_in_last_20s'))
    tear = sum(1 for i in inst if (i.get('facts') or {}).get('teardown_in_last_20s'))
    if rec:
        why.append(f'{rec} report(s) show the screen recreated in the last 20 s')
    if tear:
        why.append(f'{tear} report(s) show a teardown in the last 20 s')
    tl = ' '.join((i.get('timeline_last_lines') or '')[-4000:] for i in inst).lower()
    for w, label in (('download', 'a download'), ('transcod', 'a transcode'), ('configurationchanged', 'a configuration change')):
        if w in tl:
            why.append(f'{label} in progress before the crash')
    return (3, '; '.join(why)) if why else (2, '')


def ui_fingerprint():
    """What decides where buttons are: every layout/menu/navigation/values xml and AndroidManifest in the app and its
    UI modules (path + size + mtime). C++ files, hooks and Kotlin logic do not change the map."""
    import hashlib
    h = hashlib.sha1()
    for mod in ('app', 'android-video-editor-module', 'java-common', 'android/java-common', 'gallerypicker', 'crop',
                'overlay_collage', 'videotrimmerlib', 'colorpicker'):
        base = os.path.join(config.LAB, mod, 'src', 'main')
        if not os.path.isdir(base):
            continue
        for d, dirs, fs in os.walk(base):
            dirs[:] = sorted(x for x in dirs if x not in ('cpp', 'java', 'kotlin', 'assets', 'jniLibs', 'build'))
            for f in sorted(fs):
                if f.endswith('.xml'):
                    fp = os.path.join(d, f)
                    st = os.stat(fp)
                    h.update(f'{os.path.relpath(fp, config.LAB)}:{st.st_size}:{int(st.st_mtime)}'.encode())
    return h.hexdigest()[:16]


def screen_map(worker, ref, limit=9000):
    """The real ids per screen on the lab phone. Built by the map_screens walk once per build (about 2 min) and
    grown by every run after that."""
    p = os.path.join(config.REPO, 'tools', 'stress', 'screen_map.json')
    stamp = os.path.join(config.REPO, 'tools', 'nightshift', 'out', 'last_install')
    try:
        small = len(json.load(open(p))) < 3            # an interrupted walk: map again
    except Exception:
        small = True
    fp_now, fpp = ui_fingerprint(), p + '.fp'
    fp_old = open(fpp).read().strip() if os.path.exists(fpp) else ''
    # re-map only when the SCREENS changed (layouts, menus, manifest), not on every reinstall: a C++ swap, a hook or a fix
    # rebuilds the app but leaves every button where it was (saves the ~3-6 min walk on most jobs)
    if small or fp_now != fp_old:
        worker.log(ref, 'repro author: mapping the app screens once for this UI version (real ids, so scripts do not guess)')
        worker.run_cmd(ref, f'{sys.executable} tools/stress/scenarios.py run map_screens --repeat 1 --fresh on', 900)
        try:
            if len(json.load(open(p))) >= 3:
                open(fpp, 'w').write(fp_now)
        except Exception:
            pass
    else:
        worker.log(ref, 'repro author: screen map reused (the app screens have not changed since it was made)')
    try:
        m = json.load(open(p))
    except Exception:
        return ''
    lines = []
    for act in sorted(m, key=lambda a: -len(m[a])):
        ids = ', '.join(f'{k}' + (f'="{v}"' if v else '') for k, v in sorted(m[act].items()))
        lines.append(f'{act}: {ids}')
    return '\n'.join(lines)[:limit]


def harness_api():
    """What a scenario may call: Editor methods (first docstring line), T tags, scenario helpers and examples."""
    z = open(os.path.join(config.REPO, 'tools/stress/zesty.py'), encoding='utf-8').read()
    tree = ast.parse(z)
    lines = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in ('Editor', 'Device', 'UI'):
            lines.append(f'class {node.name}:')
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and not f.name.startswith('_'):
                    args = ', '.join(a.arg for a in f.args.args[1:])
                    doc = (ast.get_docstring(f) or '').strip().split('\n')[0][:140]
                    lines.append(f'    {f.name}({args})' + (f'  # {doc}' if doc else ''))
        if isinstance(node, ast.ClassDef) and node.name == 'T':
            lines.append('class T (UI tags):  ' + ', '.join(t.id for st in node.body if isinstance(st, ast.Assign) for t in st.targets if hasattr(t, 'id')))
    sc = open(os.path.join(config.REPO, 'tools/stress/scenarios.py'), encoding='utf-8').read()
    m = re.search(r'# ═+ NIGHT SHIFT REPROS ═+(.*?)\n# ═+ NIGHT SHIFT AUTO', sc, re.S)
    examples = (m.group(1) if m else '')[:14000]
    other = '\n'.join(f'{a}: {b}' for a, b in re.findall(r"@scenario\([^)]*\)\ndef (\w+)\(ed, r\):\n\s+\"\"\"([^\n]*)", sc))
    return '\n'.join(lines), examples, other


def _ctx(case, merged):
    a = (merged or {}).get('analysis') or {}
    keep = {k: a.get(k) for k in ('summary', 'root_cause', 'trigger', 'timeline', 'hypotheses', 'fix_direction', 'repro_plan',
                                    'wait_chains', 'evidence', 'source') if a.get(k)}
    frames = []
    for f in (case.get('frames') or [])[:30]:
        frames.append(f if isinstance(f, str) else (f.get('func') or f"{f.get('lib')} {f.get('address')}"))
    inst = (merged or {}).get('instanceSummary') or {}
    devices = [{k: r.get(k) for k in ('phone', 'android', 'src', 'build')} for r in ((merged or {}).get('instances') or [])[:12]]
    know = ''
    kd = os.path.join(HERE, '..', 'knowledge')
    hay = json.dumps(keep, default=str) + ' '.join(map(str, frames))
    for f in glob.glob(os.path.join(kd, '*.md')):
        stem = os.path.basename(f)[:-3]
        if stem != 'README' and any(w in hay for w in stem.split('_') if len(w) > 5):
            know += f'\n--- knowledge/{stem}.md ---\n' + open(f, encoding='utf-8').read()[:5000]
    ctx = {'kind': case.get('kind') or (merged or {}).get('kind'), 'title': case.get('title'), 'field_frames': frames,
           'analysis': keep, 'instances': inst, 'devices': devices}
    try:                                              # confirmed same-bug family: its members' field events + shared context
        from . import bugfamily as _bf
        fam = _bf.prompt_block(case.get('id') or '')
        if fam:
            ctx['same_bug_family'] = fam
    except Exception:
        pass
    inst_all = _all_instances(merged)
    if inst_all:
        ctx['every_field_instance'] = inst_all
    else:
        ctx['breadcrumbs_tail'] = (case.get('breadcrumbs') or [])[-40:]
    if looper_wait_frames(case):
        bw = busy_window(case)
        if bw:
            ctx['engine_busy_window'] = bw
        ctx['looper_wait_rule'] = LOOPER_RULE
    return ctx, know


def _all_instances(merged, tail=45):
    """Every sampled field instance of this problem (all Firebase events, the Play sample, and every related
    cluster), each with its facts and the last lines of its breadcrumb timeline. A repro must fit all of them."""
    try:
        from . import analyse
        f = json.load(open(analyse.field_file((merged or {}).get('id') or '')))
    except Exception:
        return None

    def one(e, src):
        tl = (e.get('timeline_oldest_first') or '').splitlines()
        return {'source': src, 'time': e.get('time'), 'device': e.get('device'), 'os': e.get('os'), 'version': e.get('version'),
                'facts': e.get('facts'), 'timeline_last_lines': '\n'.join(tl[-tail:])}
    out = [one(e, 'firebase') for e in f.get('firebase_events') or []]
    for r in f.get('related_reports') or []:
        out += [one(e, f"firebase (related cluster {r.get('cluster', '')[:14]})") for e in r.get('events') or []]
        if r.get('play_sample_stack'):
            out.append({'source': f"play (related cluster {r.get('cluster', '')[:14]})", 'devices': r.get('devices'),
                        'stack_top': r['play_sample_stack'][:1500], **({'wait_chain': r['wait_chain']} if r.get('wait_chain') else {})})
    gp = f.get('google_play') or {}
    if gp.get('sample_stack'):
        out.append({'source': 'play', 'devices': gp.get('devices'), 'stack_top': gp['sample_stack'][:1500]})
    return {'count': len(out), 'shared_across_events_final_20s': f.get('shared_across_events_final_20s'),
            'wait_chains': f.get('wait_chains'), 'instances': out} if out else None


TL_APP = re.compile(r'AnalyticsManager: Event|MsgLooper\.cpp|[Tt]ranscod|surface(Created|Destroyed)|EGL|eglSwap|onTrimMemory|'
                    r'BufferQueue has been abandoned|dequeueBuffer|queueBuffer: BufferQueue|EGL_BAD|swapBuffers failed|'
                    r'VideoEngine|MediaTranscoder|FATAL EXCEPTION|Fatal signal|DEBUG   :|ZestyHook|wm_on_(create|resume|pause|stop|destroy)_called|'
                    r'AppCompatDelegate: .*ComponentInfo|\bat (?!android\.)[\w.$]+Activity\.onCreate\(|'
                    r'\.(cpp|h)\s*: .*(ERROR|dropped|skipped|no player|null)')   # a fix that drops a late call logs it here
TL_SYS = re.compile(r'(am_kill|Killing |Start proc|ANR in|am_proc_died|Process .* died|ActivityTaskManager: START|Displayed |'
                    r'wm_create_activity|wm_restart_activity).*' + _PKG_RX + r'|' + _PKG_RX + r'.*(died|killed)')


def app_timeline(run_dir, cap=140):
    """The app's own story of a lab run from logcat: lifecycle/analytics events, engine messages, transcodes, surfaces,
    kills and crashes of OUR process, interleaved with the recipe's steps (ZSTRESS), with times."""
    import gzip
    raw = []
    for lf in sorted(glob.glob(os.path.join(run_dir, 'logcat.txt*'))):
        try:
            op = gzip.open if lf.endswith('.gz') else open
            with op(lf, 'rt', errors='replace') as fh:
                raw += fh.readlines()
        except Exception:
            pass
    rx = re.compile(r'^\d\d-\d\d (\d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+\d+\s+\w\s+(.*)$')
    pids = {m.group(2) for m in map(rx.match, raw) if m and re.search(r'AnalyticsManager: Event|MsgLooper\.cpp', m.group(3))}
    pids |= set(re.findall(r'Start proc (\d+):' + _PKG_RX + r'[/ ]', ''.join(raw)))   # short-lived processes log no engine lines
    lines = []
    for l in raw:
        m = rx.match(l.rstrip())
        if not m:
            continue
        tm, pid, msg = m.groups()
        if 'ZSTRESS' in msg and 'adbd service' not in msg:
            t = f'{tm} >>> STEP {msg.split(":", 1)[-1].strip()}'
        elif pid in pids and TL_APP.search(msg):
            t = f'{tm} {msg}'
        elif TL_SYS.search(msg):
            t = f'{tm} [system] {msg}'
        else:
            continue
        t = re.sub(r'\| type: activity_life_cycle \| device_id: \S*', '', t)
        t = re.sub(r'\[SurfaceView\[.*?(\w+Activity)\].*?\(id:[^)]*\) ', r'[\1 surface] ', t)   # long BufferQueue prefixes
        t = re.sub(r'(device_id[":= ]+)[0-9a-f]{8,}', r'\1…', t).rstrip()[:220]
        if not lines or lines[-1] != t:
            lines.append(t)
    return '\n'.join(_fit_timeline(lines, cap))


TL_KEY = re.compile(r'>>> STEP|wm_on_|START |Displayed|wm_create|wm_restart|Fatal|FATAL|DEBUG   :|ZestyHook|died|killed|'
                    r'am_kill|ANR|Destroy|~MsgLooper|AnalyticsManager: Event|ComponentInfo|onCreate\(|dropped|skipped|no player')


def _fit_timeline(lines, cap):
    """Shorten a timeline without losing the story: first fold runs of repeated lines (same text once numbers are
    dropped) into one line with a count, then keep every key line (steps, lifecycle, engine teardown, crash) and drop
    filler evenly. The old head/tail cut lost the middle, where a looping race recipe does its work."""
    if len(lines) <= cap:
        return lines
    out, prev, n = [], None, 0
    tpl = lambda s: re.sub(r'\d+', '#', s.split(' ', 1)[-1])
    for l in lines + [None]:
        k = tpl(l) if l is not None else None
        if k is not None and k == prev and not TL_KEY.search(l):
            n += 1
            continue
        if n:
            out[-1] += f'  (+{n} more like this)'
        if l is not None:
            out.append(l)
        prev, n = k, 0
    if len(out) <= cap:
        return out
    key = [i for i, l in enumerate(out) if TL_KEY.search(l)]
    if len(key) >= cap:                              # still too many: key lines only, evenly thinned
        step = len(key) / cap
        keep = {key[int(j * step)] for j in range(cap)} | set(key[-10:])
    else:
        rest = [i for i in range(len(out)) if i not in set(key)]
        room = cap - len(key)
        step = len(rest) / room if room else 0
        keep = set(key) | ({rest[int(j * step)] for j in range(room)} if room else set())
    res, gap = [], 0
    for i, l in enumerate(out):
        if i in keep:
            if gap >= 5:
                res.append(f'… {gap} filler lines …')
            res.append(l)
            gap = 0
        else:
            gap += 1
    if gap:
        res.append(f'… {gap} filler lines …')
    return res


def _feedback(res_dir):
    """What the lab run did, for the next attempt: status line, last steps, screen on UI errors, crash/ANR head."""
    if not res_dir or not os.path.isdir(res_dir):
        return '(no result folder: the scenario runner did not start; check the code compiles and the name is right)'
    out = []
    for sub in sorted(glob.glob(os.path.join(res_dir, '*')))[:3]:
        if not os.path.isdir(sub):
            continue
        out.append(f'### run {os.path.basename(sub)}')
        st = os.path.join(sub, 'steps.log')
        if os.path.exists(st):
            out.append('steps.log (tail):\n' + ''.join(open(st, errors='replace').readlines()[-30:]))
        tl = app_timeline(sub, cap=90)
        if tl:
            out.append('app timeline from logcat (what the app REALLY did; ZSTRESS = your steps):\n' + tl)
        for fn, n in (('screen.txt', 60), ('data_app_native_crash.txt', 45), ('data_app_crash.txt', 45), ('anr_trace.txt', 0)):
            p = os.path.join(sub, fn)
            if not os.path.exists(p):
                continue
            txt = open(p, errors='replace').read()
            if fn == 'anr_trace.txt':                      # main thread is what matters
                m = re.search(r'"main".*?(?=\n\n)', txt, re.S)
                txt = (m.group(0) if m else txt)[:5000]
            else:
                txt = '\n'.join(txt.splitlines()[:n])
            out.append(f'{fn}:\n{txt}')
    return '\n'.join(out)[:24000] or '(empty result folder)'


def _blocks(txt):
    code = re.findall(r'```python\n(.*?)```', txt, re.S)
    diff = re.findall(r'```diff\n(.*?)```', txt, re.S)
    meta = re.findall(r'```json\n(.*?)```', txt, re.S)
    try:
        meta = json.loads(meta[-1]) if meta else {}
    except ValueError:
        meta = {}
    return (code[-1] if code else ''), (diff[-1] if diff else ''), meta


def _check_code(code, name):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f'SyntaxError line {e.lineno}: {e.msg}'
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not any(f.name == name for f in fns):
        return f'the code must define def {name}(ed, r)'
    if re.search(r'\b(subprocess|os\.system|shutil\.rmtree|os\.remove|git )', code):
        return 'scenarios must drive the phone through ed / ed.dev only (no subprocess, file deletes or git)'
    return ''


def _check_hook(diff):
    files = re.findall(r'^\+\+\+ b/(\S+)', diff, re.M)
    if not files:
        return 'the hook diff has no files (use a unified diff with a/ b/ paths from the repo root)'
    bad = [f for f in files if not re.match(r'(app/src/main/(cpp|java)|android-video-editor-module/src/main)/', f)]
    if bad:
        return f'hooks may only touch app code, not {bad}'
    if 'debug.zesty.hook.' not in diff:
        return 'the hook must be switched by a debug.zesty.hook.* property (default off)'
    new = re.findall(r'^--- /dev/null\n\+\+\+ b/(\S+)', diff, re.M)
    if new:
        return (f'a hook may not add new source files ({", ".join(os.path.basename(f) for f in new)}): it must delay, hold or '
                f'force a step inside the EXISTING code. A new class can invent the crash (e.g. a field class that is not in '
                f'this repo), which proves nothing about the field crash')
    added = '\n'.join(l[1:] for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))
    added = re.sub(r'//[^\n]*|/\*.*?\*/', '', added, flags=re.S)        # comments may name these words
    selfcrash = re.findall(r'\b(FatalError|abort\s*\(|raise\s*\(|kill\s*\(|__builtin_trap|LOG\s*\(\s*FATAL|std::terminate|'
                           r'_?exit\s*\(|killProcess|throw\b|SIGSEGV|SIGABRT)', added)
    if selfcrash:
        return (f'a hook may only change timing or state (delay, hold, force a lifecycle step); it must never crash the app '
                f'itself ({", ".join(sorted(set(selfcrash)))}): a crash the hook makes proves nothing about the field crash')
    return ''


def _git(args, timeout=60):
    return subprocess.run(['git', '--no-optional-locks'] + args, cwd=config.LAB, capture_output=True, text=True, timeout=timeout)


def register(key, step, expect):
    reg = json.load(open(SIDE)) if os.path.exists(SIDE) else {}
    spec = reg.get(key) or {'expect': expect, 'ladder': []}
    spec['expect'] = spec.get('expect') or expect
    spec['ladder'] = [s for s in spec['ladder'] if s.get('name') != step['name']] + [step]
    reg[key] = spec
    json.dump(reg, open(SIDE, 'w'), indent=1)


FACTS = os.path.join(OUT, 'lab_facts.json')      # what Night Shift learned about the lab (app + phone), for every crash


def _lessons_block(case):
    """Lessons learned on OTHER crashes (lab, tooling, repro), when the learning experiment is on."""
    try:
        if not json.load(open(os.path.join(config.REPO, 'tools/nightshift/out', 'experiment.json'))).get('lessons'):
            return ''
        from . import lessons as _ls
        txt, used = _ls.prompt_block(case, kinds=('lab', 'tooling', 'repro'), exclude_case=case.get('id', ''), k=8)
        _USED_LESSONS.update(used)
        return txt
    except Exception:
        return ''


_USED_LESSONS = set()


def lab_facts():
    try:
        return json.load(open(FACTS))
    except Exception:
        return []


def _add_fact(fact):
    f = (fact or '').strip()
    if len(f) < 15:
        return False
    facts = lab_facts()
    if any(f.lower()[:60] == x.lower()[:60] for x in facts):
        return False
    json.dump((facts + [f])[-40:], open(FACTS, 'w'), indent=1)
    return True


def _json_block(txt):
    m = re.findall(r'```json\n(.*?)```', txt or '', re.S) or re.findall(r'(\{.*\})', txt or '', re.S)
    for chunk in reversed(m):
        try:
            return json.loads(chunk)
        except ValueError:
            continue
    return {}


def make_checkpoints(worker, ref, ctx, k8, deny=None):
    """The field moments the lab must reach, in order, each visible in the app log (asked once per run)."""
    prompt = ('# Job 1: checkpoints\n# Field evidence and root cause\n```json\n'
              + json.dumps({k: ctx.get(k) for k in ('kind', 'title', 'field_frames', 'analysis', 'same_bug_family', 'engine_busy_window',
                                                     'looper_wait_rule') if ctx.get(k)}, indent=1, default=str)[:30000]
              + ('\nCheckpoints must hold for EVERY event of the same-bug family; a detail seen in only one event (e.g. one timeline length) '
                 'is not a checkpoint.\n' if ctx.get('same_bug_family') else '')
              + '\n```\n' + ('# Every field instance\n```json\n' + json.dumps(ctx.get('every_field_instance') or ctx.get('breadcrumbs_tail'), default=str)[:20000] + '\n```\n'))
    txt = llm.run('repro-diagnosis', prompt, worker.cfg, OUT, f'{k8}.checkpoints', tools='Read,Grep,Glob', cwd=config.LAB,
                  timeout=CHECKPOINT_SEC, deny=deny)
    cps = (_json_block(txt).get('checkpoints') or [])[:6]
    if cps:
        json.dump(cps, open(os.path.join(OUT, f'{k8}.checkpoints.json'), 'w'), indent=1)
        worker.log(ref, 'repro author: field checkpoints the lab must reach: ' + ' → '.join(f"{c.get('id')}. {c.get('what', '')[:90]}" for c in cps))
    return cps


def hit_checkpoints(worker, ref, case, ctx, cps, k8, deny=None):
    """Which field checkpoints the UNFIXED crashing run (the repro that counted) really went through. A checkpoint the
    crash happened without is not needed: verify must not demand it, and the root cause marks it 'not needed'.
    -> {'dir', 'reached': [ids], 'not_needed': [ids]} or None. Cached per repro run."""
    rd = case.get('repro_dir') or ''
    if not rd or not cps:
        return None
    full = rd if os.path.isabs(rd) else os.path.join(config.REPO, rd)
    if not os.path.isdir(full):
        return None
    ids = [str(c.get('id')) for c in cps]
    cp = os.path.join(OUT, f'{k8}.hit_checkpoints.json')
    try:
        old = json.load(open(cp))
        if old.get('dir') == rd and old.get('ids') == ids:
            return old
    except Exception:
        pass
    parent = os.path.dirname(full) if os.path.exists(os.path.join(full, 'steps.log')) else full   # diagnose reads its run folders
    d = diagnose(worker, ref, ctx, cps, k8, 'hitrun', [('hitrun', {'result': 'CRASHED with every field frame (unfixed build)'}, [parent])],
                 deny=deny, crashed=True) or {}
    reached = [str(x) for x in (d.get('reached') or [])]
    if d.get('all_reached'):
        reached = list(ids)
    if not reached:
        return None
    reached = sorted(set(reached) | {ids[-1]}, key=ids.index) if ids[-1] in ids else reached   # it crashed: the last one happened
    out = {'dir': rd, 'ids': ids, 'reached': reached, 'not_needed': [i for i in ids[:-1] if i not in reached],
           'why': str(d.get('why', ''))[:600]}
    try:
        json.dump(out, open(cp, 'w'), indent=1)
    except Exception:
        pass
    worker.log(ref, f'checkpoints the crashing run reached: {", ".join(out["reached"])}'
                    + (f'; NOT needed for the crash: {", ".join(out["not_needed"])}' if out['not_needed'] else ''))
    return out


def diagnose(worker, ref, ctx, cps, k8, name, tried_names, deny=None, crashed=False):
    """After a miss: which checkpoints the lab reached, the first one it missed and WHY, and the setup fix.
    crashed=True: the run DID crash with the field frames; only which checkpoints it went through matters."""
    runs = []
    for nm, r, g in tried_names:
        subs = [x for d in g for x in sorted(glob.glob(os.path.join(d, '*'))) if os.path.isdir(x)]
        steps = ''
        for x in subs[:1]:
            st = os.path.join(x, 'steps.log')
            steps = ''.join(open(st, errors='replace').readlines()[-25:]) if os.path.exists(st) else ''
        # up to 3 runs: a race fires in some runs only, and one quiet run must not hide the others
        tls = [f'app timeline (run {os.path.basename(x)}):\n' + app_timeline(x, cap=120 if len(subs) == 1 else 70) for x in subs[:3]]
        runs.append(f'## recipe {nm}: {r.get("result")} ({r.get("why", "")})\nsteps:\n{steps}\n'
                    + ('\n\n'.join(tls) if tls else '(no run folder)'))
    head = ('# Job 2b: this lab run CRASHED with every field frame (unfixed build). Say which checkpoints it really went '
            'through (reached), from its app timeline; a checkpoint it crashed without is not part of the trigger.\n'
            if crashed else '# Job 2: diagnosis after a run that did not crash\n')
    prompt = (head + '# Checkpoints\n```json\n' + json.dumps(cps, indent=1) + '\n```\n'
              '# Field (root cause, timeline, trigger)\n```json\n'
              + json.dumps({k: (ctx.get('analysis') or {}).get(k) for k in ('trigger', 'timeline', 'root_cause')}, indent=1, default=str)[:12000]
              + '\n```\n# Lab runs of ' + name + '\n' + '\n\n'.join(runs)[:40000])
    txt = llm.run('repro-diagnosis', prompt, worker.cfg, OUT, f'{k8}.{name}.diagnosis', tools='Read,Grep,Glob', cwd=config.LAB,
                  timeout=DIAG_SEC, deny=deny)
    d = _json_block(txt)
    if not d:
        worker.log(ref, 'repro author: diagnosis gave no answer; the next attempt gets the raw lab timeline only')
        return {}
    if crashed:
        pass                                      # the caller logs the reached set
    elif d.get('all_reached'):
        worker.log(ref, f'repro author: DIAGNOSIS: every field checkpoint was reached and it did not crash: {str(d.get("why", ""))[:220]}')
    else:
        worker.log(ref, f'repro author: DIAGNOSIS: trigger not reached: checkpoint {d.get("first_missed")} missed '
                        f'(reached {d.get("reached")}): {str(d.get("why", ""))[:260]}')
        if d.get('setup_fix'):
            worker.log(ref, f'repro author: setup fix for the next recipes: {str(d["setup_fix"])[:240]}')
    try:                                          # kept for the lab write-back of the root cause (ns/labupdate.py)
        dp = os.path.join(OUT, f'{k8}.diagnoses.json')
        prev = json.load(open(dp)) if os.path.exists(dp) else []
        json.dump((prev + [dict(d, attempt=name)])[-12:], open(dp, 'w'), indent=1)
    except Exception:
        pass
    if not crashed and _add_fact(d.get('lab_fact')):
        worker.log(ref, f'repro author: learned about the lab (kept for every crash): {str(d["lab_fact"])[:200]}')
    return d


FIXTURES = os.path.join(OUT, 'fixtures.json')
FIX_TRIES = 3


def _fixtures(key):
    try:
        return json.load(open(FIXTURES)).get(key) or {}
    except Exception:
        return {}


def build_fixture(worker, ref, case, ctx, cps, k8, api, smap, expect, deny=None, need='', old=''):
    """SETUP BUILDER: before any recipe, build the project state the field had (clips, freezes, overlays...) ONCE per
    device as a saved project (a lab fixture), so every recipe starts from it with ed.open_fixture(k8) instead of each
    recipe trying (and failing) to rebuild it with taps. Returns the fixture description, or '' (recipes then set up
    themselves as before)."""
    devices = ['phone'] + list(getattr(worker, '_lane_serials', None) or [])
    have = _fixtures(k8)
    if have and len(have) >= len(devices) and not need:
        what = next(iter(have.values())).get('what', '')
        worker.log(ref, f'repro author: lab fixture "{k8}" already built on {len(have)} device(s): {what[:160]}')
        return what
    if not cps:
        return ''
    name = f'ns_{k8}_fx'
    path = os.path.join(AUTO, f'fx_{k8}.py')
    fb = ''
    for n in range(1, FIX_TRIES + 1):
        prompt = (
            '# Task: build a LAB FIXTURE project (setup only, NO trigger)\n'
            f'Write ONE scenario `def {name}(ed, r):` decorated `@scenario(\'nightshift\', \'auto\', \'nodraft\')` that builds, '
            'from a cold app start, the PROJECT STATE the field user had just BEFORE the trigger (what the first checkpoint(s) '
            'below need: number of clips on each layer, their kinds and rough lengths, freeze items, overlays, text, '
            'transitions...). It must NOT do the trigger actions (the edits that froze/crashed the app); recipes do those later.\n'
            'Rules:\n- First line: `ed.fixture_begin()`.\n- Open a project with ed.open_draft() (the lab test draft) and ADD what '
            'is missing (ed.add_media() adds one clip; tools are in the bottom bar: MAIN_MENU / CLIP_MENU give the item '
            'order, ed.tap_tool(\'freeze\') taps any bottom-bar tool by its name, scrolling the bar until it is on screen).\n'
            '- After each property is built, PROVE it with `ed.require_log(regex, timeout, since=mark, why=...)` on the app log '
            'line that shows it (e.g. the engine message for an added clip or a freeze).\n'
            f'- Last line: `ed.save_fixture(\'{k8}\', \'<one line: what this project holds>\')` (it leaves the editor and saves).\n'
            '- Keep it simple and robust: no stress, no timing tricks, no random choices that change the layout.\n\n'
            f'# Field evidence\n```json\n{json.dumps(ctx, indent=1, default=str)[:40000]}\n```\n'
            f'# Field checkpoints (the fixture is the state checkpoint 1 needs)\n```json\n{json.dumps(cps, indent=1)}\n```\n'
            f'# Harness you can call (tools/stress/zesty.py; read it for details)\n```\n{api}\n```\n'
            + (f'# Screen map (ids seen on the lab phone)\n```\n{smap}\n```\n' if smap else '')
            + ('# What Night Shift knows about this lab\n' + '\n'.join(f'- {x}' for x in lab_facts()) + '\n\n' if lab_facts() else '')
            + (f'# REBUILD: the last fixture was WRONG for this crash\nOld fixture: {old}\nWhat it must hold instead '
               f'(from the lab diagnosis; prove each with require_log):\n{need}\n\n' if need else '')
            + (f'# Your previous try failed\n{fb}\n\n' if fb else '')
            + '# Answer: ONE ```python``` block with the scenario (module-level helpers prefixed _fx_' + k8 + '_ are allowed).')
        txt = llm.run('repro-author', prompt, worker.cfg, OUT, f'{k8}.fixture{n}', tools='Read,Grep,Glob', cwd=config.LAB,
                      timeout=900, deny=deny)
        code, _d, _m = _blocks(txt or '')
        err = _check_code(code, name) if code else 'no python block in the answer'
        if err:
            fb = f'Your code was rejected: {err}'
            worker.log(ref, f'repro author: fixture builder try {n}: {err}')
            continue
        code = re.sub(r'^\s*(from scenarios import[^\n]*|import scenarios[^\n]*)\n', '', code, flags=re.M)  # exec'd into scenarios
        open(path, 'w', encoding='utf-8').write(f'# Night Shift lab fixture builder for {k8} (try {n})\n\n' + code.strip() + '\n')
        before = _fixtures(k8)
        worker.log(ref, f'repro author: fixture builder try {n}: building the field project on the phone')
        res = worker._ladder_step(ref, {'scenario': name, 'repeat': 1, 'name': name, 'fast': True, 'phone_only': True, 'setup': True}, expect)
        after = _fixtures(k8)
        if len(after) > len(before) or (after and after != before):
            what = next(iter(after.values())).get('what', '')
            worker.log(ref, f'repro author: lab fixture built on the phone: {what[:200]}')
            for ln in devices[1:]:                     # the same builder on every emulator lane (each has its own projects)
                worker._ladder_step(ref, {'scenario': name, 'repeat': 1, 'name': name, 'fast': True, 'lane': ln, 'setup': True}, expect)
            got = _fixtures(k8)
            worker.log(ref, f'repro author: lab fixture on {len(got)}/{len(devices)} device(s)')
            _add_fact(f'Lab fixture "{k8}": {what[:200]} (open it with ed.open_fixture("{k8}"))')
            return what
        fb = (f'The run did not save the fixture. Result: {res.get("why") or res.get("result")}\n'
              + _feedback_dirs(res.get('dirs') or []))[:6000]
        worker.log(ref, f'repro author: fixture builder try {n} failed: {(res.get("why") or "")[:200]}')
    worker.log(ref, f'repro author: could not build a lab fixture in {FIX_TRIES} tries; recipes set up the project themselves')
    return ''


def _feedback_dirs(dirs):
    out = []
    for d in dirs[:2]:
        for sub in sorted(glob.glob(os.path.join(d, '*')))[:2]:
            st = os.path.join(sub, 'steps.log')
            if os.path.exists(st):
                out.append(f'--- {os.path.basename(sub)}/steps.log ---\n' + open(st, errors='replace').read()[-3000:])
    return '\n'.join(out)


def run(worker, ref, case, merged, tried=None):
    """Returns the hit dict (level, name, natural, hits, runs, seed, dir, scenario, hook_patch) or None."""
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(AUTO, exist_ok=True)
    os.makedirs(HOOKS, exist_ok=True)
    key = case['id']
    from . import groups as _g
    k8 = _g.k8(key)                                  # split cards get their own files ('g' + fingerprint)
    analysis = (merged or {}).get('analysis') or {}
    expect = expect_frames(case, analysis)
    if not expect:
        worker.log(ref, 'repro author: no named field frame to match against; cannot judge a repro, stopping')
        return None
    api, examples, other = harness_api()
    ctx, know = _ctx(case, merged)
    smap = screen_map(worker, ref)
    sigs = field_signatures(ctx)
    blind = getattr(worker, '_blind', False)
    budget = int(getattr(worker, '_budget', 0) or BUDGET_MIN)
    level_min = int(getattr(worker, '_level_min', 0) or LEVEL_MIN)
    deny = None
    if blind:   # a fair test: only what Night Shift gathered for this crash; nothing a person wrote about it
        know = ''
        words = [k8] + [w.split('::')[-1] for w in expect]
        keep = [b for b in re.split(r'(?=\n@scenario\()', examples) if not any(w in b for w in words)]
        examples = ''.join(keep)
        other = '\n'.join(l for l in other.split('\n') if not any(w in l for w in words))
        deny = [f'{t}({p})' for t in ('Read', 'Grep', 'Glob')
                for p in ('./.git/**', './**/.git/**', './tools/nightshift/**', './stress_results/**', './tools/stress/auto/**', './*.md', './docs/**',
                          './.idea/**', './_to_delete/**', './Claude outputs/**', './bugreport/**', './anr_his_fix/**',
                          './**/.fuse_hidden*', './**/*.cpp.*', './**/*.h.*', './**/*.kt.*', './**/*.java.*', './**/*.orig', './**/*.rej', './**/*.bak', './**/*.before-hook')]
        ok, seen = deny_check(worker, ref, deny)
        if not ok:
            worker.log(ref, f'repro author: BLIND test ABORTED: the read block does not work (Claude read {seen}); '
                            f'a result would not be blind')
            return None
        worker.log(ref, 'repro author: read block verified: planted files in every blocked place stayed unreadable')
        worker.log(ref, f'repro author: BLIND test: no team notes, no earlier lab results, no hand-written repro; budget {budget} min')
    path = os.path.join(AUTO, f'{k8}.py')
    if os.path.exists(path):                     # a new run starts with a clean file: old scripts and helpers with the
        old = os.path.join(OUT, f'{k8}.auto.{dt.datetime.now():%Y%m%d-%H%M%S}.py')   # same names would shadow the new ones
        os.replace(path, old)
        worker.log(ref, f'repro author: earlier scripts for this crash kept in {os.path.relpath(old, config.REPO)}')
    t0 = dt.datetime.now()
    history, attempts = [], []
    turbo_txt = ''
    try:                                           # TURBO (out/experiment.json): replay lead + several tries per setup
        tb = (json.load(open(os.path.join(config.REPO, 'tools/nightshift/out/experiment.json'))) or {}).get('turbo') or {}
    except Exception:
        tb = {}
    if tb.get('replay') and getattr(worker, '_replay', None):
        from . import replay as _rp
        turbo_txt += _rp.hint(worker._replay)
    if int(tb.get('hammer') or 0) > 1:
        turbo_txt += (f'# SPEED RULE (turbo): one setup, several chances\nAfter the setup reaches the field state, repeat the '
                      f'trigger part up to {int(tb["hammer"])} times IN THE SAME RUN (undo it / go back and do it again), so one '
                      f'setup gives {int(tb["hammer"])} chances. Use the lab shortcuts for setup (ed.open_slideshow, open_draft); '
                      f'no idle longer than needed. The whole run must stay under {int(tb.get("run_max_s") or 240)} s.\n\n')
    facts0 = len(lab_facts()) if blind else 0       # full blind: only facts learned during THIS run are shown
    cps = make_checkpoints(worker, ref, ctx, k8, deny)
    fixture = ''
    if not blind:
        try:
            fixture = build_fixture(worker, ref, case, ctx, cps, k8, api, smap, expect, deny)
        except Exception as e:
            worker.log(ref, f'repro author: fixture builder error: {str(e)[:200]}')
    fx_rebuilds = 0
    diag, misses, misses5 = {}, [], []            # latest diagnosis; first-missed checkpoint per attempt (all / at L5)
    worker.log(ref, f'repro author: writing my own repro for {_g.label(key)}; a run counts only if the lab dump shows: {", ".join(expect)}')
    if expect == art_abort_pattern(case):
        worker.log(ref, 'repro author: the field stack has no symbols (ART fatal abort shape libc > libart > libbase); '
                        'matching by that abort path plus the field breadcrumbs: a PATTERN match, not a frame match')
    # levels an earlier run already exhausted on this crash are not repeated (their scripts stay in auto/)
    done_before = {}
    for a in (case.get('authorAttempts') or []):
        done_before[a.get('level')] = done_before.get(a.get('level'), 0) + 1
    tried = set(tried or []) | {lv for lv, k in done_before.items() if k >= TRIES_PER_LEVEL}
    if fixture and done_before:                       # the earlier tries had no field project: try every level again
        worker.log(ref, 'repro author: a lab fixture is available now, so levels tried before without it are tried again')
        tried = set(tried or []) - set(done_before)
    if not [lv for lv, _n, _r in LEVELS if lv not in tried]:
        tried = set()                                 # never end with nothing to run: start the ladder again
    start = start_level(ctx)
    if start[0] > 2 and 2 not in tried:
        tried.add(2)
        worker.log(ref, f'repro author: starting at level {start[0]} (environment): {start[1]}')
    if tried:
        worker.log(ref, f'repro author: levels already tried on this crash, skipped: {sorted(tried)}')
    for level, lname, rule in LEVELS:
        if level in tried:
            continue
        t_level = dt.datetime.now()
        misses = []                                   # '3 misses at this level' counts this level only
        for n in range(1, TRIES_PER_LEVEL + 1):
            if n > 1 and level < 5 and (dt.datetime.now() - t_level).total_seconds() > level_min * 60:
                worker.log(ref, f'repro author: L{level} used its {level_min} min; moving up so the hook level gets time')
                break
            if (dt.datetime.now() - t0).total_seconds() > budget * 60:
                worker.log(ref, f'repro author: time budget ({budget} min) used up')
                return _finish(worker, ref, case, attempts, None)
            name = f'ns_{k8}_l{level}_{n}'
            prompt = (
                f'# Task\nWrite 2 or 3 RECIPES `{name}_a`, `{name}_b` (and `{name}_c`) (ladder level {level}: {lname}) that '
                f'reproduce this field {ctx["kind"]} on the lab phone. Each recipe tests a DIFFERENT path the field '
                f'instances show (e.g. one per instance group); its docstring starts with the instances it recreates. '
                f'Each runs once; a recipe that comes close (the field error lines appear in the lab log) is repeated.\n'
                f'Level rule: {rule}\n\n'
                + ('IMPORTANT: the lab phone runs the PLAY internal-test build (the full app, release): there are NO debug hooks '
                   '(debug.zesty.hook.*) and no lab remote-control broadcasts; use only real taps (ed.ui, ed.tap_tool, ed.open_* '
                   'blocks that tap the real UI) and phone-level conditions (rotate, network, kill_bg, slow_phone).\n\n'
                   if getattr(worker, '_play_mode', False) else '')
                + f''
                f'Build recipes from the TESTED building blocks first (ed.open_slideshow, ed.slideshow_add_media, '
                f'ed.slideshow_deselect, ed.slideshow_toggle_play, ed.slideshow_media_count, ed.open_draft, ed.add_media, '
                f'ed.export_start, ed.background, ed.dev.dark_mode / rotate / network / slow_network / clear_app_cache / '
                f'font_scale / fresh_video / clear_app_files / dev.fcm_push(title, body, data, foreground, wait) = an FCM push arrives through '
                f'the app\'s real Firebase receiver; dev.slow_phone(level 0-48) = CPU busy loops so this fast lab phone is as slow as low-end '
                f'field phones (set it right before the trigger, 0 after); ed.kill_bg() = the system reclaims the cached app); ed.tap_tool(name) = tap any bottom-bar tool by its name (scrolls the bar; e.g. "freeze", "speed", "split"); raw ed.ui taps only for what no block covers. A recipe that navigates by itself from a cold '
                f'start (e.g. open_slideshow) is decorated @scenario(\'nightshift\', \'auto\', \'nodraft\') so the '
                f'runner does not open a draft first.\n\n'
                f'A run counts ONLY if the crash/ANR dump contains every one of: {json.dumps(expect)}'
                + (f' (or the stack of a confirmed same-bug family member: '
                   f'{"; ".join(json.dumps(ex) for _c, _t, ex in getattr(worker, "_family", []) or [])})' if getattr(worker, '_family', None) else '')
                + '.\n'
                f'Read EVERY field instance below (every_field_instance), not just one: find what they share and what differs; '
                f'they may reach the crash by different paths. Say in "why" which instances your scenario recreates.\n\n'
                f'# Field evidence\n```json\n{json.dumps(ctx, indent=1, default=str)[:60000]}\n```\n{know}\n\n'
                + turbo_txt +
                f'# Harness you can call (tools/stress/zesty.py; read it for details)\n```\n{api}\n```\n'
                + (f'# Screen map: ids SEEN on the lab phone with this build, per activity (use these, do not guess)\n```\n{smap}\n```\n' if smap else '')
                + 
                f'Helpers in scenarios.py: push_newest_video(ed, src, name), background_keep_screen(ed, seconds, pressure, camera), '
                f'_export_abort_clip_tool(ed, r, hook, camera, pressure, away).\n'
                f'The runner restarts the app, opens the first draft in My Projects (a short video draft), calls your function, '
                f'and watches logcat: a crash or ANR raises AppFailure and the dumps are collected for you. Do NOT catch AppFailure.\n'
                f'Other scenarios you can copy steps from: \n{other[:6000]}\n\n'
                f'# Working Night Shift repros for other crashes (style to follow)\n```python\n{examples}\n```\n\n'
                + (f'# Field checkpoints your recipe must make happen, in order (check them in the app timeline)\n```json\n{json.dumps(cps, indent=1)}\n```\n' if cps else '')
                + (f'# LAB FIXTURE (use it)\nThis crash has a lab fixture project on every lab device: {fixture}\nStart EVERY recipe '
                   f'with `ed.open_fixture(\'{k8}\')` and decorate it `@scenario(\'nightshift\', \'auto\', \'nodraft\')`. Do NOT '
                   'rebuild that project state; go straight to the field trigger.\n\n' if fixture else '')
                + ('RULE (checkpoints): check every field precondition/checkpoint that shows in the app log with '
                   '`ed.require_log(regex, timeout, since=mark, why=...)` (it stops the run as a setup error when it never shows). '
                   'NEVER just ed.log() that a checkpoint was missed and carry on: a run that skipped the field path must not '
                   'count as a clean run. If the draft lacks something the field had (e.g. freeze items, overlays, transitions), '
                   'CREATE it in the recipe first and require its log line.\n\n')
                + (f'# LOOPER-WAIT ANR\n{LOOPER_RULE}\nFor the recipe: recreate the ENGINE MESSAGES of engine_busy_window in the '
                   'same order and spacing (find in the Kotlin code which UI action sends each one), with the same project '
                   'state the field had; the main thread entry ' + ', '.join(e[5:] for e in expect if e.startswith('MAIN:'))
                   + ' must be on the main thread of the ANR dump.\n\n' if ctx.get('looper_wait_rule') else '')
                + (f'# What Night Shift knows about this lab (app + phone), learned on earlier runs\n' + '\n'.join(f'- {x}' for x in lab_facts()[facts0:]) + '\n\n' if lab_facts()[facts0:] else '')
                + _lessons_block(case)
                + (f'# DIAGNOSIS of your last attempt (a lab engineer read the app log)\n```json\n{json.dumps(diag, indent=1)[:4000]}\n```\n'
                   + ('RULE: the setup did not reach the field moment yet. Your recipes MUST fix that first (do the setup_fix, '
                      'or another way to reach checkpoint ' + str(diag.get('first_missed')) + '). Do NOT just add stress, camera, '
                      'dark mode or memory pressure on top of a setup that does not reach the field state.\n'
                      if not diag.get('all_reached') else
                      'Every checkpoint was reached without a crash: now change timing/stress, or (level 5) add the hook.\n')
                   + ('The SAME checkpoint was missed twice: change the approach completely (different media, screen path or '
                      'trigger), do not vary the same recipe.\n' if len(misses) >= 2 and misses[-1] == misses[-2] and misses[-1] else '')
                   + '\n' if diag else '')
                + (f'# Your previous attempts and what the lab phone did\n' + '\n\n'.join(history[-3:]) + '\n\n' if history else '')
                + '# Answer format\n'
                f'1. ONE ```python``` block with the recipes `def {name}_a(ed, r):`, `def {name}_b(ed, r):` [, `_c`], each '
                f'decorated `@scenario(\'nightshift\', \'auto\'[, \'nodraft\'])` with a one-line docstring; module-level '
                f'helpers are allowed (prefix them with _{k8}_); use only ed / ed.dev / time / r (random.Random).\n'
                + ('2. ```diff``` block: the hook patch (unified diff, repo-root a/ b/ paths, property debug.zesty.hook.<name>, default off).\n'
                   if level == 5 else '')
                + '3. ```json``` block: {"natural": true|false, "why": "one sentence: which field moments the recipes recreate"}\n'
                'Read the app code (Read/Grep) to find the exact UI path and the code path before writing. Keep it short.\n'
                'UI ids: prefer ids you have SEEN in a screen dump of an earlier run (feedback above) over ids guessed from '
                'layout files (other screens reuse names). Only the steps that make the trigger may raise UIError; a '
                'decorative step (open a picker, play/pause) uses ed.ui.tap(..., timeout=5) and carries on if it is missing.')
            worker.log(ref, f'repro author: L{level} attempt {n}: asking Claude for {name}')
            txt = llm.run('repro-author', prompt, worker.cfg, OUT, f'{k8}.l{level}.{n}', tools='Read,Grep,Glob',
                          cwd=config.LAB, timeout=AUTHOR_SEC, deny=deny)
            if 'timed out' in (txt or '') or not (txt or '').strip():   # one longer try, then move on (was 20 min every time)
                worker.log(ref, f'repro author: no answer in {AUTHOR_SEC // 60} min; one longer try ({2 * AUTHOR_SEC // 60} min)')
                txt = llm.run('repro-author', prompt, worker.cfg, OUT, f'{k8}.l{level}.{n}b', tools='Read,Grep,Glob',
                              cwd=config.LAB, timeout=2 * AUTHOR_SEC, deny=deny)
            code, diff, meta = _blocks(txt or '')
            names = []
            if code:
                try:
                    defined = {f.name for f in ast.parse(code).body if isinstance(f, ast.FunctionDef)}
                except SyntaxError:
                    defined = set()
                names = [f'{name}_{x}' for x in 'abcd' if f'{name}_{x}' in defined] or ([name] if name in defined else [])
            err = (_check_code(code, names[0]) if names else f'the code must define {name}_a(ed, r) and {name}_b(ed, r)') \
                if code else 'no ```python``` block in the answer'
            if not err and level == 5:
                err = _check_hook(diff) if diff else 'level 5 needs a ```diff``` hook block'
            if err:
                history.append(f'## {name}: rejected before running: {err}')
                worker.log(ref, f'repro author: {name} rejected: {err}')
                continue
            prev = open(path, encoding='utf-8').read() if os.path.exists(path) else f'# Night Shift auto repros for {key}\n'
            open(path, 'w', encoding='utf-8').write(prev.rstrip() + f'\n\n\n# {dt.datetime.now():%Y-%m-%d %H:%M} level {level} attempt {n}\n{code.strip()}\n')
            hook_file, applied, hfl = '', False, []
            if diff:
                hook_file = os.path.join(HOOKS, f'{k8}_l{level}_{n}.diff')
                open(hook_file, 'w').write(diff if diff.endswith('\n') else diff + '\n')
                hfl = []                             # model diffs often have off hunk counts: let git recount first
                for hfl in ([], ['--recount'], ['--recount', '--ignore-whitespace']):
                    chk = _git(['apply', '--check', *hfl, hook_file])
                    if not chk.returncode:
                        break
                if chk.returncode:
                    history.append(f'## {name}: hook patch does not apply: {chk.stderr[:400]}')
                    worker.log(ref, f'repro author: hook patch does not apply: {chk.stderr[:150]}')
                    continue
            new = []
            try:
                if diff:
                    _git(['apply', *hfl, hook_file])
                    applied = True
                    worker.log(ref, f'repro author: hook applied for this build only ({os.path.basename(hook_file)})')
                    if worker.install_app(ref):
                        history.append(f'## {name}: the app did not build with the hook (see build errors); fix the C++/Java')
                        continue
                res, new, tried_names = None, [], []
                try:                                 # each recipe's own source, to spot siblings that share a broken step
                    srcs = {f.name: ast.get_source_segment(code, f) or '' for f in ast.parse(code).body if isinstance(f, ast.FunctionDef)}
                except SyntaxError:
                    srcs = {}
                broken_tokens = set()
                names_seq = list(names)
                if getattr(worker, '_lane_serials', None) and len(names) > 1 and hasattr(worker, '_ladder_multi'):
                    # emulator lanes up: the recipes run side by side, one per device, instead of one after another
                    group = names[:1 + len(worker._lane_serials)]
                    rs = worker._ladder_multi(ref, [{'scenario': nm, 'repeat': 1, 'name': nm, 'fast': True} for nm in group], expect)
                    for nm, r1 in zip(group, rs):
                        r1['scenario_name'], r1['near'] = nm, ''
                        got = r1.pop('dirs', [])
                        new += got
                        tried_names.append((nm, r1, got))
                        worker.log(ref, f'repro author: recipe {nm}: {r1["result"]} ({r1["hits"]}/{r1["runs"]})'
                                   + (f'; {r1["why"]}' if r1.get('why') else ''))
                        if r1['hits'] and res is None:
                            res = r1
                    names_seq = [] if res is not None else [n_ for n_ in names if n_ not in group]
                for nm in names_seq:                 # every recipe once; a near miss is repeated twice more
                    if broken_tokens and any(t in srcs.get(nm, '') for t in broken_tokens):
                        hit_t = next(t for t in broken_tokens if t in srcs.get(nm, ''))
                        worker.log(ref, f'repro author: {nm} skipped: it uses the step that broke a sibling recipe ({hit_t})')
                        tried_names.append((nm, {'result': 'skipped', 'hits': 0, 'runs': 0, 'why': f'skipped: same broken step as a sibling ({hit_t})',
                                                 'scenario_name': nm, 'near': ''}, []))
                        continue
                    rd = os.path.join(config.REPO, worker.cfg['lab']['results_dir'])
                    before = set(glob.glob(os.path.join(rd, '*')))
                    r1 = worker._ladder_step(ref, {'scenario': nm, 'repeat': 1, 'name': nm, 'fast': True}, expect)
                    got = sorted(set(glob.glob(os.path.join(rd, '*'))) - before)
                    new += got
                    broken = 'automation' in (r1.get('why') or '')   # the script broke: repeating it would break again
                    if broken and not r1.get('hits'):     # remember WHAT broke, so siblings using the same step are skipped
                        w = r1.get('why') or ''
                        broken_tokens.update(t.strip() for t in re.findall(r"(?:id|textc?|desc|res):([A-Za-z_][\w ]{2,40}?)(?:[\s,;)'\"]|$)", w))
                        if re.search(r"don.?t keep activities", w, re.I):
                            broken_tokens.update({'dont_keep_activities', '_dka_ui'})
                    near = '' if r1['hits'] else _near_miss(got, sigs)
                    if near and broken:
                        worker.log(ref, f'repro author: {nm} showed a field error line ({near}) but its script broke; '
                                        f'not repeated, the next recipes get this as a lead')
                        near = ''
                    if near:
                        worker.log(ref, f'repro author: {nm} came close ({near}); repeating it twice')
                        before = set(glob.glob(os.path.join(rd, '*')))
                        r2 = worker._ladder_step(ref, {'scenario': nm, 'repeat': 2, 'name': nm, 'fast': True}, expect)
                        new += sorted(set(glob.glob(os.path.join(rd, '*'))) - before)
                        r2['runs'] = (r2.get('runs') or 0) + (r1.get('runs') or 0)
                        r1 = r2
                    r1['scenario_name'] = nm
                    r1['near'] = near
                    tried_names.append((nm, r1, got))
                    worker.log(ref, f'repro author: recipe {nm}: {r1["result"]} ({r1["hits"]}/{r1["runs"]})'
                               + (f'; {r1["why"]}' if r1.get('why') else ''))
                    if r1['hits']:
                        res = r1
                        break
                if res is None:                      # no hit: report the recipe that got furthest (near miss first)
                    res = sorted((t[1] for t in tried_names), key=lambda x: (not x.get('near'), x.get('result') != 'not reproduced'))[0]
            finally:
                if applied:
                    _git(['apply', '-R', *hfl, hook_file])
            win = res.get('scenario_name') or name
            try:                                    # the winning recipe's own docstring, not the combined "why"
                doc = next((ast.get_docstring(f) for f in ast.parse(code).body
                            if isinstance(f, ast.FunctionDef) and f.name == win), '') or ''
            except SyntaxError:
                doc = ''
            res.update({'level': level, 'name': f'{win}: {doc.splitlines()[0] if doc else meta.get("why", lname)}'[:200], 'scenario': win,
                        'natural': bool(meta.get('natural', level < 5)) and level < 5, 'author': True})
            if hook_file:
                res['hook_patch'] = os.path.relpath(hook_file, config.REPO)
            attempts.append(res)
            worker.log(ref, f'repro author: {name}: {res["result"]} ({res["hits"]}/{res["runs"]})'
                       + (f'; {res["why"]}' if res.get('why') else ''))
            if res['hits']:
                step = {'level': level, 'name': res['name'], 'scenario': win, 'repeat': 2, 'natural': res['natural'],
                        'author': True, 'stat_runs': int(res.get('runs') or 1), 'stat_hits': int(res.get('hits') or 1)}
                if hook_file:
                    step['hook_patch'] = res['hook_patch']
                register(key, step, expect)
                worker.log(ref, f'repro author: registered {win} for this crash; the next Reproduce starts from it')
                return _finish(worker, ref, case, attempts, res)
            if cps:
                diag = diagnose(worker, ref, ctx, cps, k8, name, tried_names, deny) or diag
                whys = ' '.join(str((r_ or {}).get('why', '')) for _n, r_, _g in tried_names)
                fx_ids = [str(v.get('id', ''))[:8] for v in _fixtures(k8).values() if isinstance(v, dict)]
                if fixture and fx_rebuilds < 2 and ('fixture project is gone' in whys or any(
                        i and f'project {i} did not open' in whys for i in fx_ids)):
                    # 2026-10-21: the fixture drafts vanished (emulator restarted read-only, app data cleared by
                    # another job) or no longer open: rebuild them the same way instead of failing every recipe.
                    diag = dict(diag, fixture_wrong=True, fixture_need=diag.get('fixture_need') or
                                'the same project as before (it is gone or no longer opens on a lab device)')
                if fixture and diag.get('fixture_wrong') and diag.get('fixture_need') and fx_rebuilds < 2:
                    fx_rebuilds += 1
                    worker.log(ref, f'repro author: the lab fixture is wrong for this crash; rebuilding it '
                                    f'({fx_rebuilds}/2): {str(diag["fixture_need"])[:220]}')
                    try:
                        allfx = json.load(open(FIXTURES))
                        old_fx = allfx.pop(k8, {})
                        allfx[f'{k8}_old_{dt.datetime.now():%Y%m%d%H%M}'] = old_fx
                        json.dump(allfx, open(FIXTURES, 'w'), indent=1)
                        new_fx = build_fixture(worker, ref, case, ctx, cps, k8, api, smap, expect, deny,
                                               need=str(diag['fixture_need']), old=fixture)
                    except Exception as e:
                        new_fx, old_fx = '', locals().get('old_fx', {})
                        worker.log(ref, f'repro author: fixture rebuild error: {str(e)[:200]}')
                    if new_fx:
                        fixture = new_fx
                        misses = []                  # the old misses were on the wrong project
                        history.append(f'## the lab fixture was rebuilt: {new_fx[:300]} (earlier misses were on the old one)')
                    else:                            # never leave the recipes with NO fixture: put the old one back,
                        gone = 'fixture project is gone' in whys or 'no lab fixture project' in whys
                        try:                             # unless it is gone (then recipes set up the project themselves)
                            allfx = json.load(open(FIXTURES))
                            if not gone and old_fx:
                                allfx[k8] = old_fx
                                json.dump(allfx, open(FIXTURES, 'w'), indent=1)
                        except Exception:
                            pass
                        if gone:
                            fixture = ''
                        worker.log(ref, 'repro author: fixture rebuild failed; ' + ('the old one is gone, recipes set up the '
                                        'project themselves' if gone else 'recipes keep the old fixture'))
                misses.append(None if diag.get('all_reached') else diag.get('first_missed'))
                if level == 5:
                    misses5.append(misses[-1])
                same = len(misses) >= 3 and misses[-1] and misses[-1] == misses[-2] == misses[-3]
                if same and level < 5:
                    # 3 misses of the same checkpoint at THIS level: the next level up gets its turn (it may reach it
                    # with a different real trigger, e.g. a system setting); the levels are not skipped to the hook
                    worker.log(ref, f'repro author: checkpoint {misses[-1]} missed 3 times at level {level}; moving up one level')
                    history.append(f'## {name}: diagnosis: {json.dumps(diag)[:1500]}')
                    misses = []
                    break
                same = len(misses5) >= 2 and misses5[-1] and misses5[-1] == misses5[-2]   # only hook-level misses count here
                if same and level == 5:
                    worker.log(ref, f'repro author: STOP: checkpoint {misses[-1]} cannot be reached on this phone even with a hook: '
                                    f'{str(diag.get("why", ""))[:240]}')
                    return _finish(worker, ref, case, attempts, None)
            history.append(f'## {name} (L{level}) recipes\n```python\n{code.strip()[:5000]}\n```\n' + '\n'.join(
                f'- {nm}: {r["result"]} ({r["hits"]}/{r["runs"]}){"; NEAR MISS: " + r["near"] if r.get("near") else ""}; '
                f'{r.get("why", "")}\n{_feedback(g[-1] if g else "")[:2500]}' for nm, r, g in tried_names))
    return _finish(worker, ref, case, attempts, None)


def _finish(worker, ref, case, attempts, hit):
    upd = {'authorAttempts': (case.get('authorAttempts') or []) +      # keep earlier runs: they decide what to skip next
           [{k: a.get(k) for k in ('level', 'name', 'scenario', 'result', 'hits', 'runs', 'why', 'natural', 'hook_patch')}
            for a in attempts]}
    worker.db.collection('cases').document(case['id']).set(upd, merge=True)
    if not hit:
        worker.log(ref, f'repro author: no level reproduced it in {len(attempts)} lab attempts')
    return hit
