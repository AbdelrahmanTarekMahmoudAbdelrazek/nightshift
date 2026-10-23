"""The lab worker: listens for queued jobs in Firestore, runs them on this Mac, streams status back.

  job = { action: triage | reproduce | draft-fix, issue, requestedBy, status, queuedAt }
  worker adds: claimedAt, startedAt, finishedAt, log (list of lines), result, error

Safety: runs only the three known actions, only commands from this file, never deletes, never merges.
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time

from . import config, board
if not hasattr(config, 'profile'):                 # long-running worker: config.py is not in its per-job reload list;
    import importlib as _il                          # pick up the profile helpers once (LAB survives the reload)
    _il.reload(config)

PY = sys.executable
BLIND_READ_DENY = [f'{t}({p})' for t in ('Read', 'Grep', 'Glob')
                   for p in ('./.git/**', './**/.git/**', './tools/nightshift/**', './stress_results/**', './tools/stress/auto/**',
                             './*.md', './docs/**', './.idea/**', './_to_delete/**', './Claude outputs/**', './bugreport/**',
                             './anr_his_fix/**', './*.patch', './*.log', './*.txt',
                             # stray copies of source files (editor/patch/FUSE temp files) can hold a newer, fixed version
                             './**/.fuse_hidden*', './**/*.cpp.*', './**/*.h.*', './**/*.kt.*', './**/*.java.*', './**/*.orig', './**/*.rej', './**/*.bak', './**/*.before-hook')] + ['Bash']


def cairo_now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('Africa/Cairo'))
    except Exception:                               # no tz database: Egypt is UTC+3 from the last Friday of April
        u = dt.datetime.utcnow()                    # to the last Thursday of October, else UTC+2
        def last(month, wd):
            d = dt.date(u.year, month, 31 if month == 10 else 30)
            return d - dt.timedelta(days=(d.weekday() - wd) % 7)
        summer = last(4, 4) <= u.date() <= last(10, 3)
        return u + dt.timedelta(hours=3 if summer else 2)


def _now():
    return dt.datetime.now().isoformat(timespec='seconds')


# ---- shared board, one worker per person (23 Oct) ----------------------------------------------------------------
# nightshift.yaml  worker.owner: you@msd-my.com   -> this worker runs the jobs YOU queue, plus shared jobs (daily sync)
#                  worker.serve_others: true      -> also the jobs of people whose own worker is not online (the lab host)
# No owner set = the old behaviour: this worker runs every job.
SHARED_ACTIONS = ('sync', 'sync-full', 'audio-branches')       # board-wide work: whichever worker is online first
PHONE_ACTIONS = ('reproduce', 'draft-fix', 'audio-check')
WORKER_ALIVE_S = 180


def _owner(cfg):
    return str(((cfg or {}).get('worker') or {}).get('owner') or '').strip().lower()


def _lab_lock_id(cfg):
    """One phone lock PER WORKER: your repro must never wait for a colleague's repro on their own phone."""
    o = _owner(cfg)
    return 'lab_lock' if not o else 'lab_lock_' + re.sub(r'[^a-z0-9]+', '_', o)


def _stable_lock(name):
    import threading as _t
    lk = getattr(_t, name, None)
    if lk is None:
        lk = _t.Lock()
        setattr(_t, name, lk)
    return lk



RE_BT = re.compile(r'#\d+\s+pc\s+[0-9a-fA-F]+\s+(\S+)(?:\s+\(offset 0x[0-9a-fA-F]+\))?(?:\s+\((.+?)\+\d+\))?')


def crash_evidence(rd):
    """What a lab run's CRASH really was, for matching against the field frames. Only the crashed thread counts:
    the native tombstone's first backtrace (or the same DEBUG lines in logcat), the Java exception, the ANR trace.
    Never the general logcat or result.json's own target/notes: a fix's guard logs 'VisualTimeLine::get_media_starting_time'
    and the looper logs 'ProcessMessages' in every run, so a plain text search counted an unrelated crash as the field
    one (8Dl4TvBM round 2, a SIGSEGV 0x30 in pthread_mutex_lock). -> (text, frames [{lib, func}], fault, thread)"""
    def rd_(fn):
        p = os.path.join(rd, fn)
        return open(p, errors='replace').read() if os.path.exists(p) else ''
    nat, frames, fault, thread = rd_('data_app_native_crash.txt'), [], '', ''
    src = nat
    if not nat:                                      # no tombstone file: the crash_dump lines logcat got (tag DEBUG)
        src = '\n'.join(l for l in rd_('logcat.txt').splitlines() if re.search(r'\bDEBUG\b|crash_dump', l))
    if src:
        m = re.search(r'fault addr (0x[0-9a-fA-F]+|--------)', src)
        fault = m.group(1) if m else ''
        m = re.search(r'tid: \d+, name: ([^>]+?)\s+>>>', src)
        thread = m.group(1).strip() if m else ''
        bt = src.split('backtrace:', 1)[1] if 'backtrace:' in src else src
        lines = []
        for l in bt.splitlines():
            if RE_BT.search(l):
                lines.append(l)
            elif lines and l.strip() == '':
                break                                # end of the crashed thread's backtrace
        for l in lines:
            m = RE_BT.search(l)
            lib = os.path.basename(m.group(1).split('!')[-1])
            frames.append({'lib': lib, 'func': (m.group(2) or '').strip()})
        nat = '\n'.join(lines)
    java = rd_('data_app_crash.txt')
    if not java:                                     # no dropbox copy: the AndroidRuntime FATAL EXCEPTION block of logcat
        lc = rd_('logcat.txt').splitlines()
        i = next((k for k, l in enumerate(lc) if 'FATAL EXCEPTION' in l and 'AndroidRuntime' in l), None)
        if i is not None:
            java = '\n'.join(l for l in lc[i:i + 80] if 'AndroidRuntime' in l)
    anr = rd_('anr_trace.txt')
    lc = rd_('logcat.txt').splitlines()               # the system's own ANR report (ActivityManager 'ANR in <pkg>' + reason)
    i = next((k for k, l in enumerate(lc) if 'ANR in ' in l and 'ActivityManager' in l), None)
    if i is not None:
        anr += '\n' + '\n'.join(l for l in lc[i:i + 30] if 'ActivityManager' in l)
    res = ''
    try:                                             # author/live scripts: only the crash text they captured
        import json as _j
        rj = _j.load(open(os.path.join(rd, 'result.json'))) if os.path.exists(os.path.join(rd, 'result.json')) else {}
        res = str(rj.get('crash') or '') if isinstance(rj, dict) else ''
    except Exception:
        pass
    return '\n'.join(x for x in (nat, java, anr, res) if x), frames, fault, thread


def crash_label(frames, fault='', thread=''):
    names = [f['func'] or f['lib'] for f in frames[:4]]
    return ' <- '.join(names) + (f' (fault {fault}' + (f', thread {thread})' if thread else ')') if fault else '')

class Worker:
    def __init__(self, db, cfg, dry=False):
        self.db, self.cfg, self.dry = db, cfg, dry
        self.busy = threading.Lock()

    _log_lock = threading.RLock()

    def log(self, ref, line):
        with self._log_lock:                   # lanes and the main job write at the same time
            self._log(ref, line)

    def _log(self, ref, line):
        from firebase_admin import firestore
        print(f'[{_now()}] {line}', flush=True)
        try:                                   # local mirror of every job log line (readable without the board)
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'jobs.log'), 'a') as f:
                f.write(f'{_now()} [{getattr(ref, "id", "?")[:8]}] {line}\n')
        except OSError:
            pass
        # The board gets the log in batches (Firestore free plan: 20k writes/day; one write per line burned it):
        # important lines go out at once with whatever is buffered, the rest at most every 6 s. Compiler chatter
        # stays in out/jobs.log only.
        noise = bool(re.match(r'\s*(In file included from|C/C\+\+: (?!.*error:)|warning:|note:|\^|~+|I\d{4} .*ev_poll_posix)', line))
        if not noise:
            buf = self.__dict__.setdefault('_logbuf', [])
            buf.append(f'{_now()} {line}')
            important = bool(re.search(r'REPRODUCED|not reproduced|level \d result|ERROR|DONE:|VERIFIED|BUILD (SUCCESSFUL|FAILED)|'
                                       r'fix stage|CANCELLED|repro ladder|✖|■', line))
            if important or time.time() - getattr(self, '_logbuf_t', 0) > 6 or len(buf) >= 40:
                self.flush_log(ref)
        self._progress(line)

    def flush_log(self, ref):
        from firebase_admin import firestore
        buf, self._logbuf, self._logbuf_t = getattr(self, '_logbuf', []), [], time.time()
        if not buf or ref is None:
            return
        try:                                   # a slow network must not kill a 20-minute lab run over the log
            ref.update({'log': firestore.ArrayUnion(buf)}, timeout=20)
        except Exception as e:
            print(f'[worker] {len(buf)} log line(s) not sent to the board: {str(e)[:120]}', flush=True)

    # step lines worth showing on the case page while a job runs (everything else stays in the Jobs tab)
    _STEP = re.compile(r'(repro ladder|--- level|level \d result|REPRODUCED|not reproduced|repro author|step \d+ |VERIFIED|not verified|'
                       r'review:|DONE:|\$ \./gradlew|BUILD (SUCCESSFUL|FAILED)|▶ |✖ |■ |CANCELLED|ERROR)')

    def _progress(self, line):
        cref = getattr(self, '_case_ref', None)
        if cref is None or not self._STEP.search(line):
            return
        now = time.time()
        if now - getattr(self, '_prog_t', 0) < 4 and not re.search(r'REPRODUCED|VERIFIED|DONE:|ERROR|CANCELLED', line):
            return                                 # at most one write per 4 s, except for outcomes
        self._prog_t = now
        step = re.sub(r'^\[[^\]]*\]\s*', '', line)[:220]
        if step.startswith('$ ./gradlew'):
            step = 'building and installing the app on the lab phone'
        try:
            cref.update({'progress': {'job': getattr(self, '_job_action', ''), 'step': step, 'at': _now()}}, timeout=10)
        except Exception:
            pass

    def _end_progress(self, how):
        cref = getattr(self, '_case_ref', None)
        self._case_ref = None
        if cref is not None:
            try:
                cref.update({'progress': {'job': getattr(self, '_job_action', ''), 'step': how, 'at': _now(), 'done': True}})
            except Exception:
                pass

    def _watch_cancel(self, ref):
        """Cancel button on the board sets status 'cancel': stop the running command (whole process group: gradle,
        scenarios.py, adb children) and fail the job visibly. Polls the job every 10 s while it runs."""
        import signal
        self.cancelled, self._proc = False, None

        def watch():
            while True:
                time.sleep(10)
                try:
                    jd = ref.get().to_dict() or {}
                    st = jd.get('status')
                except Exception:
                    continue
                if st != 'cancel':
                    if st not in ('running', None):
                        return                     # job finished
                    continue
                self.cancelled = True
                try:                               # who pressed it (board writes cancelledBy: email · button · tab · time)
                    self.log(ref, f"cancel requested by {jd.get('cancelledBy') or 'unknown (no cancelledBy: an old board tab, or a script)'}")
                except Exception:
                    pass
                p = self._proc
                if p and p.poll() is None:
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                        time.sleep(3)
                        if p.poll() is None:
                            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    except Exception:
                        pass
                try:
                    subprocess.run(['adb', 'shell', 'am', 'force-stop', config.app_package(getattr(self, "cfg", None))], timeout=20, capture_output=True)
                except Exception:
                    pass
                self.reset_hooks()
                return
        threading.Thread(target=watch, daemon=True).start()

    def run_cmd(self, ref, cmd, timeout=3600, cwd=None):
        self.log(ref, f'$ {cmd}')
        if self.dry:
            self.log(ref, '(dry run, not executed)')
            return 0
        if getattr(self, 'cancelled', False):
            raise RuntimeError('cancelled from the board')
        p = subprocess.Popen(cmd, shell=True, cwd=cwd or config.REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             start_new_session=True)
        self._proc = p
        tail = []
        key = re.compile(r'(▶|■|✖|⚠|VERDICT|REPRODUCED|Traceback|Error:|error:|FAILURE|BUILD (SUCCESSFUL|FAILED)|INSTALL_FAILED|draft created|try \d)')
        self._last_errors = []
        for line in p.stdout:
            tail.append(line.rstrip())
            if ': error:' in line and len(self._last_errors) < 200:
                self._last_errors.append(line.rstrip())
            if key.search(line) or len(tail) % 20 == 0:   # step lines and verdicts right away, the rest sampled
                self.log(ref, tail[-1][:300])
        p.wait(timeout=timeout)
        self._proc = None
        self._last_tail = tail[-200:]
        if getattr(self, 'cancelled', False):
            raise RuntimeError('cancelled from the board')
        if p.returncode:
            self.log(ref, f'(exit {p.returncode}) ' + (' | '.join(t[:200] for t in tail[-12:]) if tail else 'no output'))
        elif tail:
            self.log(ref, tail[-1][:300])
        return p.returncode

    def republish(self, ref):
        data = board.build(self.cfg)
        from . import fire
        try:
            counts = fire.publish(self.db, data)
        except Exception as e:                       # a quota/network hiccup on the board mirror must not fail a lab job
            self.log(ref, f'board publish skipped: {str(e)[:150]} (the lab result is kept; the next job publishes it)')
            return
        self.log(ref, f'published {counts}')

    def do_analyse(self, ref, case):
        """Root cause for this one crash only: no sync, no other crash is analysed (saves time and tokens)."""
        at = os.path.join(config.REPO, 'tools/nightshift/out', 'analysetask.json')
        if os.path.exists(at):                       # engineer's local task (file only): run a Night Shift script, no phone
            import json
            t = json.load(open(at))
            os.rename(at, at + '.used')
            scr = t.get('script', '')
            if not re.fullmatch(r'tools/nightshift/[\w/]+\.py', scr):
                raise RuntimeError(f'analysetask: script not allowed: {scr}')
            args = ' '.join(f'"{a}"' for a in (t.get('args') or []) if re.fullmatch(r'[\w.:/=,-]+', str(a)))
            self.log(ref, f'local task: {scr} {args} (no analysis of this case)')
            try:
                rc = self.run_cmd(ref, f'{PY} {scr} {args}', int(t.get('timeout', 3600)))
            finally:
                if case.get('status'):
                    self.db.collection('cases').document(case['id']).update({'status': case['status']})
            if rc:
                raise RuntimeError(f'local task exited {rc}')
            return
        import importlib
        from . import analyse
        importlib.reload(analyse)
        analyse.BLIND_DENY = getattr(self, '_blind_deny', None)     # blind test: the root-cause model's read block
        from . import groups as _sgl
        self.log(ref, f'analysing only {_sgl.label(case["id"])} from its field data'
                      + (' (blind: no .git, no lab notes, no old results)' if analyse.BLIND_DENY else ''))
        st = analyse.run_all(self.db, self.cfg, log=lambda l: self.log(ref, l), only={case['id']}, force=True,   # asked for this one: always rewrite
                             stop=lambda: getattr(self, 'cancelled', False))
        self.log(ref, f'analysis finished: {st}')

    def do_start(self, ref, case):
        """One click, the whole pipeline: pull fresh details -> root cause -> a queued Reproduce on the lab phone, which
        goes on by itself (lab.auto_fix) to the fix, the check on the phone, the review and the hand-over drafts.
        The phone part is its own job so it waits for the phone like any Reproduce, and Cancel works per step."""
        self.log(ref, 'Start 1/3: pull fresh details from Crashlytics (all threads, symbols, code)')
        self.do_pull(ref, case)
        if getattr(self, 'cancelled', False):
            raise RuntimeError('cancelled')
        case = {**case, **(self.db.collection('cases').document(case['id']).get().to_dict() or {}), 'id': case['id']}
        self.log(ref, 'Start 2/3: root cause (main thread, the thread it waits for, the wait chain, the code)')
        self.do_analyse(ref, case)
        if getattr(self, 'cancelled', False):
            raise RuntimeError('cancelled')
        ok = any((self.db.collection('merged').document(p + case['id']).get().to_dict() or {}).get('analysis')
                 for p in ('m-', 'm-play-', ''))
        if not ok:
            raise RuntimeError('no root cause was written, so the lab step was not queued (see the log above)')
        from firebase_admin import firestore as _fs
        who = (ref.get().to_dict() or {}).get('requestedBy') or 'Start'
        nj = self.db.collection('jobs').add({'action': 'reproduce', 'issue': case['id'], 'requestedBy': who,
                                             'status': 'queued', 'queuedAt': _fs.SERVER_TIMESTAMP, 'chainedFrom': ref.id})
        self.log(ref, f'Start 3/3: queued Reproduce on the lab phone (job {nj[1].id[:8]}); it continues to the fix, '
                      'the phone check, the review and the hand-over drafts by itself')

    def do_triage(self, ref, case):
        csv = case.get('csv')
        if not csv:
            raise RuntimeError('case has no csv export path; pull the events first')
        rc = self.run_cmd(ref, f'{PY} tools/nightshift/sentinel.py triage --events "{csv}" --issue {case["id"]} --kind {case.get("kind","ANR")} --llm', 900)
        if rc:
            raise RuntimeError(f'triage exited {rc}')

    def _shipped_swap(self, ref, case):
        """A repro must run the code that crashed, not today's branch (which may already hold a fix). For the files on
        the crash's stack, plus files changed together with them since the release, put the version from the commit
        the field build was made from (ns/source.py pins it from the shipped .so) into the working copy for this job
        only. Returns the backups to restore."""
        import json as _json
        from . import source
        vers = case.get('versions') or {}
        top = max(vers.items(), key=lambda kv: kv[1])[0] if vers else ''
        m = re.search(r'\((\d+)\)', top)
        if not m:
            return []
        pin = (source.ref_for(m.group(1), top.split(' ')[0], self.cfg) or {}).get('sha')
        if not pin:
            self.log(ref, 'lab build: commit of the field build unknown; using the working copy as is')
            return []
        stack = {re.sub(r'/\./', '/', (f.get('srcline') or '').split(':')[0]) for f in (case.get('frames') or []) if f.get('srcline')}
        stack = {f for f in stack if f.startswith('app/src/')}
        files = set(stack)
        try:                                          # files an earlier build had to heal for this commit: swap them now,
            hp = os.path.join(config.REPO, 'tools/nightshift/out', f'heal_{pin[:12]}.json')   # not after a failed build
            files |= set(_json.load(open(hp)))
        except Exception:
            pass
        for c in source._git('log', '--format=%H', f'{pin}..HEAD', '--', *sorted(stack)).split() if stack else []:
            files |= {x for x in source._git('show', '--name-only', '--format=', c).split() if x.startswith('app/src/main/cpp/')}
        swaps, bdir = [], os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', case['id'])
        for f in sorted(files):
            old = subprocess.run(['git', 'show', f'{pin}:{f}'], cwd=config.REPO, capture_output=True).stdout   # bytes
            p = os.path.join(config.LAB, f)
            # compare with (and restore to) the lab branch's OWN version, not whatever is on disk: a file an earlier job
            # left swapped (an interrupted restore) would otherwise look 'already the field version' and the build
            # would mix it with today's other files (2026-10-21: undefined TextRenderer::clearTextCurvature)
            head = subprocess.run(['git', 'show', f'HEAD:{f}'], cwd=config.LAB, capture_output=True).stdout
            cur = open(p, 'rb').read() if os.path.exists(p) else b''
            if head and cur.replace(b'\r\n', b'\n') != head.replace(b'\r\n', b'\n') \
                    and cur.replace(b'\r\n', b'\n') == old.replace(b'\r\n', b'\n'):
                cur = head                            # left over from an earlier job: back up the branch version instead
            if not old or old.replace(b'\r\n', b'\n') == (head or cur).replace(b'\r\n', b'\n'):
                if head and cur != head and cur.replace(b'\r\n', b'\n') != head.replace(b'\r\n', b'\n'):
                    open(p, 'wb').write(head)         # same in both commits: make sure the branch version is on disk
                continue
            os.makedirs(os.path.dirname(os.path.join(bdir, f)), exist_ok=True)
            open(os.path.join(bdir, f), 'wb').write(cur)          # byte-exact backup (line endings kept)
            open(p, 'wb').write(old)
            swaps.append((p, os.path.join(bdir, f)))
        self._swap_pin, self._swap_bdir = pin, bdir
        if swaps:
            self.log(ref, f'lab build = the code that crashed: {len(swaps)} file(s) on/around the crash stack set to the field build\'s '
                          f'commit {pin[:10]} for this job ({", ".join(os.path.basename(x[0]) for x in swaps)}); the working copy is restored after')
            _json.dump([x[0] for x in swaps], open(os.path.join(bdir, 'swapped.json'), 'w'))
        else:
            self.log(ref, f'lab build: the crash files already match the field build ({pin[:10]})')
        return swaps

    def _restore_swaps(self, ref=None):
        """A job that died mid-repro may have left crash files at the field build's version: put the user's back."""
        import json as _json
        for sj in glob.glob(os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', '*', 'swapped.json')):
            bdir = os.path.dirname(sj)
            for p in _json.load(open(sj)):
                if not p.startswith(config.REPO + os.sep):    # a lab-folder file: the lab folder resets itself
                    continue
                b = os.path.join(bdir, os.path.relpath(p, config.REPO))
                if os.path.exists(b):
                    open(p, 'wb').write(open(b, 'rb').read())
            os.rename(sj, sj + '.restored')
            if ref:
                self.log(ref, f'restored the working copy left from an interrupted lab build ({os.path.basename(bdir)[:12]})')

    def do_reproduce(self, ref, case):
        th = getattr(self, '_prebuild_th', None)
        if th is not None:                            # the build started during the root cause: let it finish first
            th.join(2400)
            self._prebuild_th = None
        self._restore_swaps(ref)
        lt = os.path.join(config.REPO, 'tools/nightshift/out', 'labtask.json')
        use = (self.cfg.get('lab') or {}).get('build_as_shipped', True) and not os.path.exists(lt)
        self._lanes_start(ref)                       # emulator lanes boot while the build compiles
        swaps = self._shipped_swap(ref, case) if use else []
        self._swaps = swaps                          # install_app may extend it when the old/new mix does not compile
        try:
            return self._do_reproduce(ref, case)
        finally:
            self._lanes_stop()
            for p, b in swaps:                           # the user's working copy comes back byte for byte
                open(p, 'wb').write(open(b, 'rb').read())
            if swaps:
                sj = os.path.join(os.path.dirname(swaps[0][1]).split('/app/')[0], 'swapped.json')
                bdir = os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', case['id'])
                if os.path.exists(os.path.join(bdir, 'swapped.json')):
                    os.rename(os.path.join(bdir, 'swapped.json'), os.path.join(bdir, 'swapped.json.restored'))
                self.log(ref, f'working copy restored ({len(swaps)} file(s))')

    def _do_reproduce(self, ref, case):
        """Reproduce button. 1) a registered ladder for this crash (lab_repros.json), easiest real trigger first;
        2) if there is none or it fails, Night Shift writes its own scenarios (ns/author.py), runs them, reads what the
        phone did, fixes them and escalates level by level, up to a debug hook. A run counts only when the lab dump has
        every field frame. The winning step is registered so the next click starts from it."""
        import importlib
        from . import author
        importlib.reload(author)
        lt = os.path.join(config.REPO, 'tools/nightshift/out', 'labtask.json')
        if os.path.exists(lt):                       # engineer's lab check (local file): run these scenarios once, nothing else
            import json
            lj = json.load(open(lt))
            names = [n for n in (lj.get('scenarios') or []) if re.match(r'^[a-z0-9_]+$', n)]
            os.rename(lt, lt + '.used')
            self._labtask_only = True
            if lj.get('lab_update'):                 # only rewrite the root cause from the lab results (no phone)
                import importlib
                from . import labupdate
                importlib.reload(labupdate)               # the worker is long-running: always the current code
                labupdate.run(self.db, self.cfg, case['id'], log=lambda l: self.log(ref, l))
                self.maybe_deploy(ref)
                return
            if lj.get('trends'):                     # only the daily Crashlytics series for the dashboard (no sync, no analysis)
                import importlib, json as _j
                from . import vitals
                importlib.reload(vitals)
                from firebase_admin import firestore as _fs
                self.log(ref, 'fetching the daily Crashlytics series (about 70 read calls, ~1-2 min)')
                try:
                    tr = vitals.trends(self.cfg, log=lambda l: self.log(ref, l))
                except BaseException as e:            # SystemExit from the API helpers included
                    raise RuntimeError(f'trends failed: {str(e)[:300]}')
                self.db.collection('config').document('trends').set({'data': _j.dumps(tr), 'updatedAt': _fs.SERVER_TIMESTAMP})
                self.maybe_deploy(ref)
                if not lj.get('publish_run'):
                    return
            if lj.get('publish_run'):                # backfill the crash window from an existing crashing run
                rd = os.path.join(config.REPO, lj['publish_run'])
                mp4 = os.path.join(rd, 'repro_video.mp4')
                upd = self.lab_evidence(ref, case['id'], rd, mp4 if os.path.exists(mp4) else None)
                if case.get('reproLevel') is not None or upd.get('labCrash'):
                    upd['status'] = 'reproduced'          # publishing evidence must not reset the case's status
                self.db.collection('cases').document(case['id']).update(upd)
                self.maybe_deploy(ref)
                return
            pats = [x for x in (lj.get('patches') or []) if re.fullmatch(r'tools/nightshift/out/[\w./-]+\.diff', x)]
            self.log(ref, f'lab check (labtask.json): running {names} once, no repro this time'
                          + (f'; build WITH {", ".join(pats)}' if pats else ''))
            self._hooks_strict = bool(pats)          # a measurement of a fix must never run on a build without it
            try:
                self._install(ref, pats)
            finally:
                self._hooks_strict = False
            env = ' '.join(f'{k}={v}' for k, v in (lj.get('env') or {}).items() if re.fullmatch(r'ZESTY_\w+', k) and re.fullmatch(r'\w+', str(v)))
            for nm in names:
                self.run_cmd(ref, f"{env + ' ' if env else ''}{PY} tools/stress/scenarios.py run {nm} --repeat 1 --fresh on --reset none", 1200)
            return
        if getattr(self, '_blind', False):          # blind test: start from a clean case page, old results archived
            import json
            from google.cloud import firestore as gcf
            old = ['reproAttempts', 'labRuns', 'labFailures', 'reproLevel', 'reproNatural', 'reproRate', 'repro_scenario',
                   'repro_step', 'repro_seed', 'repro_dir', 'repro_script', 'reproAuthor', 'labMatch', 'authorAttempts',
                   'fixRounds', 'fixMinutes', 'fixAnswer', 'review', 'handover', 'patch', 'fixVerified', 'fixNote']
            bk = os.path.join(config.REPO, 'tools/nightshift/out', f'blind_backup_{case["id"]}_{int(time.time())}.json')
            json.dump(case, open(bk, 'w'), indent=1, default=str)
            gone = [k for k in old if k in case]
            if gone:
                self.db.collection('cases').document(case['id']).update({k: gcf.DELETE_FIELD for k in gone})
            case = {k: v for k, v in case.items() if k not in old}
            self.log(ref, f'blind test: earlier repro/fix results archived ({len(gone)} fields) and hidden from Night Shift')
        rs = os.path.join(config.REPO, 'tools/nightshift/out', f'reset_{case["id"]}.flag')
        if os.path.exists(rs):                       # engineer: start this crash from scratch (earlier attempts forgotten)
            os.rename(rs, rs + '.used')
            import json
            from google.cloud import firestore as gcf
            old = ['authorAttempts', 'reproAttempts', 'labRuns', 'labFailures', 'reproLevel', 'reproNatural', 'reproRate',
                   'repro_scenario', 'repro_step', 'repro_seed', 'repro_dir', 'repro_script', 'reproAuthor', 'labMatch', 'labCrash']
            json.dump(case, open(os.path.join(config.REPO, 'tools/nightshift/out', f'reset_backup_{case["id"]}_{int(time.time())}.json'), 'w'), indent=1, default=str)
            gone = [k for k in old if k in case]
            if gone:
                self.db.collection('cases').document(case['id']).update({k: gcf.DELETE_FIELD for k in gone})
            case = {k: v for k, v in case.items() if k not in old}
            self.log(ref, f'fresh start for this crash: earlier repro attempts forgotten ({len(gone)} fields, backup kept)')
        ra = os.path.join(config.REPO, 'tools/nightshift/out', f'reanalyse_{case["id"]}.flag')
        if os.path.exists(ra):                       # engineer: rewrite this root cause before the repro (evidence improved)
            os.rename(ra, ra + '.used')
            self.log(ref, 'root cause rewrite requested: writing it again from the symbolized field stack first')
            self.do_analyse(ref, case)
            case = {**case, **(self.db.collection('cases').document(case['id']).get().to_dict() or {}), 'id': case['id']}
        elif not ((self._merged(case) or {}).get('analysis')) and not getattr(self, '_blind', False):
            # gather-only syncs leave problems without a root cause: write it for this one first (the author needs it)
            self.log(ref, 'no root cause for this problem yet: writing it first (about 3-6 min)')
            self.do_analyse(ref, case)
            case = {**case, **(self.db.collection('cases').document(case['id']).get().to_dict() or {}), 'id': case['id']}
        merged = self._merged(case)
        self._t0 = time.time()
        key, spec = (None, None) if getattr(self, '_blind', False) else self._registered(case)   # blind: no hand-registered recipe
        attempts, hit = [], None
        if spec:
            hit, attempts = self.run_ladder(ref, case, key, spec)
        else:
            self.log(ref, 'no registered repro for this crash yet')
            self._install(ref, [])
        self._replay = None
        lonly = os.path.join(config.REPO, 'tools/nightshift/out', f'ladder_only_{case["id"]}.json')
        ladder_only = os.path.exists(lonly)
        if ladder_only:                              # engineer's flag file: a focused run, no long search after the ladder
            os.rename(lonly, lonly + '.used')
            self.log(ref, 'focused run (flag file): only the registered recipes; no engine replay, live agent or repro author')
        if not hit and not ladder_only and self._turbo().get('replay'):
            # TURBO step 6: direct engine calls first (seconds per run, phone + lanes); a hit is a lead for the UI
            # author and a fast fix check, never the proof
            from . import replay
            importlib.reload(replay)
            try:
                self._replay = replay.run(self, ref, case, merged)
            except Exception as e:
                self.log(ref, f'engine replay failed: {str(e)[:200]}; the UI repro author goes on as usual')
        self._early_patch = None
        if self._replay and self._turbo().get('fix_on_replay'):
            # TURBO: the fix starts as soon as the engine replay proves the crash; the phone then goes back to the
            # unfixed build for the real-tap proof
            from . import fixloop as _fx
            importlib.reload(_fx)
            try:
                self._early_patch = _fx.early(self, ref, case, merged, self._replay)
            except Exception as e:
                self.log(ref, f'early fix failed: {str(e)[:200]}; the normal fix stage runs after the repro')
            if self._early_patch:
                self.log(ref, 'early fix kept; reinstalling the unfixed crash build for the real-tap repro')
                self._install(ref, [])
        if not hit and not ladder_only and self._turbo().get('live'):
            # TURBO: the live agent drives the phone one action at a time (screen + log after each); classic author if it misses
            from . import live
            importlib.reload(live)
            try:
                hit = live.run(self, ref, case, merged, self._replay)
                if hit:
                    attempts.append(hit)
            except Exception as e:
                if 'cancelled from the board' in str(e):
                    raise
                self.log(ref, f'live agent failed: {str(e)[:200]}; the classic repro author takes over')
                hit = None
        if not hit and not ladder_only:
            self.log(ref, 'Night Shift is writing its own repro (Claude writes, the lab phone runs, Claude reads the result and fixes)')
            hit = author.run(self, ref, case, merged)
            if hit:
                attempts.append(hit)
        self._record(ref, case, attempts, hit)
        if hit and (self.cfg.get('lab') or {}).get('repro_video', True):
            try:
                expect = list((spec or {}).get('expect') or []) or author.expect_frames(case, (merged or {}).get('analysis') or {})
                self.record_video(ref, case, hit, expect)
            except Exception as e:
                self.log(ref, f'repro video skipped: {str(e)[:200]}')
        if hit and getattr(self, '_blind', False) and not getattr(self, '_blind_fix', False):
            self.log(ref, 'blind repro test: stopping after the repro (no fix rounds)')
        elif hit and (self.cfg.get('lab') or {}).get('auto_fix', True):
            # one click does the rest: propose -> verify on the phone -> review -> hand-over drafts
            from . import fixloop
            importlib.reload(fixloop)
            case = {**case, **(self.db.collection('cases').document(case['id']).get().to_dict() or {}), 'id': case['id']}
            fixloop.run(self, ref, case, merged, first_patch=getattr(self, '_early_patch', None))

    def _merged(self, case):
        for mid in ('m-' + case['id'], 'm-play-' + case['id']):
            try:
                d = self.db.collection('merged').document(mid).get()
                if d.exists:
                    return {**d.to_dict(), 'id': mid}
            except Exception:
                pass
        return {}

    def _registered(self, case):
        hay = ' '.join(str(case.get(k) or '') for k in ('id', 'title', 'subtitle', 'field_fingerprint')) + ' ' + \
              ' '.join(str((f.get('func') if isinstance(f, dict) else f) or '') for f in (case.get('frames') or []))
        repros = (self.cfg.get('lab') or {}).get('repros') or {}
        if case['id'] not in repros:
            try:                                     # a card of a split issue: the issue's title/fingerprint name OTHER
                from . import groups as _sg           # cards' functions too, so only this card's own crashing function
                g = _sg.group_of(case['id']) if _sg.is_card(case['id']) or '~' in case['id'] else None
                if g is None and len((_sg.load(_sg.issue_of(case['id'])).get('groups') or [])) > 1:
                    g = _sg.group_of(case['id'])
                if g and g.get('key'):
                    hay = g['key']
            except Exception:
                pass
        key = case['id'] if case['id'] in repros else next((k for k in repros if k in hay), None)
        if not key:
            return None, None
        spec = repros[key]
        if isinstance(spec, str):
            spec = {'ladder': [{'level': 2, 'name': spec.split()[0].split('/')[-1], 'cmd': spec, 'natural': True}]}
        elif 'ladder' not in spec:
            spec = {'expect': spec.get('expect'), 'ladder': [{'level': 5 if spec.get('hook') else 2, 'name': spec['scenario'],
                                                               'scenario': spec['scenario'], 'repeat': spec.get('repeat', 2),
                                                               'natural': not spec.get('hook')}]}
        return key, spec

    def reset_hooks(self, ref=None):
        """Every debug.zesty.hook.* property back to 0 on the phone. A run killed mid-way (Cancel, crash of the runner)
        never reaches the scenario's finally, so a hook could stay armed and make a later 'natural' level look natural."""
        cmd = ("adb shell 'for p in $(getprop | grep -o \"debug\\.zesty\\.hook\\.[a-z_]*\"); do setprop $p 0; done; "
               "svc wifi enable; svc data enable; cmd uimode night no; settings put system font_scale 1.0; settings put system show_touches 0; "
               "getprop | grep debug.zesty.hook'")
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
            if ref is not None and out:
                self.log(ref, 'debug hooks reset on the phone: ' + ' '.join(out.split())[:200])
        except Exception:
            pass

    def install_app(self, ref):
        """Build + install the debug build. Only a signature/version clash (a Play build on the phone) is fixed by
        uninstalling, which wipes the app's drafts and permissions; a compile error must never uninstall."""
        cmd = (self.cfg.get('lab') or {}).get('repro_install') or self.cfg['lab']['anrsan_install']
        cmd = cmd.split('||')[0].strip()
        if self._same_build_on_phone(cmd):
            self.log(ref, 'build skipped: no app source changed since the last install and the phone still has that build')
            k0 = self._build_key()
            c0 = os.path.join(config.REPO, 'tools/nightshift/out/apk_cache', f'{k0}.apk') if k0 else ''
            self._lanes_install(ref, c0 if c0 and os.path.exists(c0) else self._apk_path())
            return 0
        t0 = time.time()
        key = self._build_key()
        if not key:
            self.log(ref, f'build cache off for this build: the code fingerprint failed ({getattr(self, "_bk_err", "?")})')
        cached = os.path.join(config.REPO, 'tools/nightshift/out/apk_cache', f'{key}.apk') if key else ''
        if cached and os.path.exists(cached):          # this exact code state was built before: install it, no compile
            self.log(ref, f'build reused: an APK of this exact code state exists ({key[:12]}); installing it instead of compiling')
            if self.run_cmd(ref, f'adb install -r -t "{cached}"', 600) == 0:
                os.utime(cached)                       # most recently used stays in the cache
                self._save_install(cmd, t0)
                self._lanes_install(ref, cached)
                return 0
            self.log(ref, 'cached APK did not install; building instead')
        rc = self._build(ref, cmd)
        rc = self._heal_swap(ref, cmd, rc)
        if rc == 0 and key:
            key = self._build_key() or key            # the healed swap changed the code state
            self._cache_apk(ref, key, t0)
        if rc and any(k in ' '.join(getattr(self, '_last_tail', [])) for k in
                      ('INSTALL_FAILED_VERSION_DOWNGRADE', 'INSTALL_FAILED_UPDATE_INCOMPATIBLE', 'signatures do not match')):
            self.log(ref, 'the phone has a different build (Play/release): uninstalling it once, then installing the debug build')
            self.run_cmd(ref, f'adb uninstall {config.app_package(getattr(self, "cfg", None))}', 120)
            rc = self._build(ref, cmd)
        self._save_install(cmd, t0 if not rc else None)
        if not rc:
            k2 = self._build_key()
            c2 = os.path.join(config.REPO, 'tools/nightshift/out/apk_cache', f'{k2}.apk') if k2 else ''
            self._lanes_install(ref, c2 if c2 and os.path.exists(c2) else self._apk_path())
        return rc

    def _build(self, ref, cmd):
        """One build; a gradle run killed by a signal before printing anything (a starved Gradle daemon, exit -13/-9) is
        retried once after a short pause instead of failing the whole job."""
        if config.LAB != config.REPO:                 # the lab folder: repo-relative path properties made absolute
            from . import labtree
            cmd = cmd + labtree.gradle_props(config.LAB)
        rc = self.run_cmd(ref, cmd, 2400, cwd=config.LAB)
        if rc < 0 and not getattr(self, '_last_tail', None):
            self.log(ref, f'build: gradle was killed at once (signal {-rc}) with no output; stopping the Gradle daemon and trying once more')
            subprocess.run('./gradlew --stop', shell=True, cwd=config.LAB, capture_output=True, timeout=120)
            time.sleep(5)
            rc = self.run_cmd(ref, cmd, 2400, cwd=config.LAB)
        return rc

    def _heal_swap(self, ref, cmd, rc, rounds=5):
        """The crash build mixes field-commit files with today's: when today's code calls something the old files do not
        have, also set the failing files to the field commit and build again (up to `rounds` times)."""
        pin, bdir, swaps = getattr(self, '_swap_pin', None), getattr(self, '_swap_bdir', None), getattr(self, '_swaps', None)
        if not rc or not pin or swaps is None:
            return rc
        import json as _json
        for _ in range(rounds):
            done = {os.path.relpath(p_, config.LAB) for p_, _b in swaps}
            bad = []
            classes = set()
            for l in getattr(self, '_last_errors', []):
                m = re.search(r'(app/src/main/[\w/.+-]+\.(?:cpp|cc|c|h|hpp|kt|java)):\d+(?::\d+)?: error', l.replace('/./', '/'))
                if m and m.group(1) not in done and m.group(1) not in bad:
                    bad.append(m.group(1))
                # the file in the error is often already the field version: the mismatch is the HEADER that declares the
                # class ("no member named 'x' in 'VisualMedia'", "out-of-line definition ... in 'VisualTimeLine'")
                for c in re.findall(r"(?:no member named '\w+' in|does not match any declaration in|no type named '\w+' in|"
                                    r"incomplete type|unknown type name) '(?:class |struct )?([A-Za-z_]\w*)'", l):
                    classes.add(c)
            for l in getattr(self, '_last_errors', []):   # linker: "undefined symbol: VisualMedia::getAudioOverlayId() const"
                for cls, fn in re.findall(r'undefined symbol: (?:\w+::)*?(\w+)::(~?\w+)\(', l):
                    hits = subprocess.run(['git', 'grep', '-l', '-F', f'{cls}::{fn}(', pin, '--', 'app/src/main/cpp'],
                                          cwd=config.REPO, capture_output=True, text=True).stdout.split()
                    for h in hits:
                        h = h.split(':', 1)[1] if ':' in h else h
                        if h.endswith(('.cpp', '.cc')) and h not in done and h not in bad:
                            bad.append(h)
            for c in sorted(classes):
                hits = subprocess.run(['git', 'grep', '-l', '-E', rf'^[[:space:]]*(class|struct)[[:space:]]+{c}([^A-Za-z0-9_;][^;]*)?$', pin, '--', 'app/src/main/cpp'],
                                      cwd=config.REPO, capture_output=True, text=True).stdout.split()
                for h in hits:
                    h = h.split(':', 1)[1] if ':' in h else h
                    if h.endswith(('.h', '.hpp')) and h not in done and h not in bad:
                        bad.append(h)
            add = []
            for f in bad:
                old = subprocess.run(['git', 'show', f'{pin}:{f}'], cwd=config.REPO, capture_output=True).stdout
                if not old:
                    continue
                p_ = os.path.join(config.LAB, f)
                b_ = os.path.join(bdir, f)
                os.makedirs(os.path.dirname(b_), exist_ok=True)
                open(b_, 'wb').write(open(p_, 'rb').read() if os.path.exists(p_) else b'')
                open(p_, 'wb').write(old)
                swaps.append((p_, b_))
                add.append(f)
            if not add:
                break
            _json.dump([x[0] for x in swaps], open(os.path.join(bdir, 'swapped.json'), 'w'))
            self.log(ref, f'lab build: today\'s {", ".join(os.path.basename(a) for a in add)} did not fit the field files; '
                          f'set to the field commit {pin[:10]} too and building again')
            rc = self._build(ref, cmd)
            if not rc:
                break
        if not rc:                                    # remember the healed files for this commit (next build: no failed first try)
            try:
                hp = os.path.join(config.REPO, 'tools/nightshift/out', f'heal_{pin[:12]}.json')
                old = set(_json.load(open(hp))) if os.path.exists(hp) else set()
                _json.dump(sorted(old | {os.path.relpath(p_, config.LAB) for p_, _b in swaps}), open(hp, 'w'), indent=1)
            except Exception:
                pass
        return rc

    STAMP = 'tools/nightshift/out/last_install'
    APK = 'app/build/outputs/apk/productionInternal/debug/app-productionInternal-debug.apk'
    SUBS = ('android-video-editor-module', 'java-common', 'android/java-common', 'gallerypicker', 'overlay_collage',
            'u2net', 'extra/oboe', 'extra/opencv')

    def _apk_path(self):
        """The APK the last build wrote (with the single-ABI flag it is under intermediates/, not outputs/)."""
        c = [os.path.join(config.LAB, self.APK),
             os.path.join(config.LAB, 'app/build/intermediates/apk/productionInternal/debug/app-productionInternal-debug.apk')]
        c = [x for x in c if os.path.exists(x)]
        return max(c, key=os.path.getmtime) if c else c and c[0] or os.path.join(config.LAB, self.APK)

    def _build_key(self):
        """Fingerprint of the exact code that would be compiled: HEAD + every uncommitted change (shipped-code swaps,
        hooks, fix patches, the engineer's own edits) + each submodule's commit and changes + the build command.
        Same key = same APK, so a build can be reused. Any doubt -> '' (always build)."""
        import hashlib
        h = hashlib.sha1()
        try:
            def g(args, cwd=config.LAB):
                r = subprocess.run(['git', '--no-optional-locks'] + args, cwd=cwd, capture_output=True, timeout=120)
                if r.returncode:
                    raise RuntimeError(r.stderr[:200])
                return r.stdout
            h.update(g(['rev-parse', 'HEAD']))
            links = []
            if config.LAB != config.REPO:              # lab folder: extra/oboe, extra/opencv are links to the working copy's trees
                from . import labtree
                links = [l for l in labtree.LINKED if os.path.islink(os.path.join(config.LAB, l))]
            h.update(g(['diff', 'HEAD', '--binary', '--', '.', ':(exclude)tools', ':(exclude)stress_results', ':(exclude)out']
                       + [f':(exclude){l}' for l in links]))
            for l in links:
                h.update(l.encode() + g(['rev-parse', 'HEAD'], os.path.realpath(os.path.join(config.LAB, l))))
            others = g(['ls-files', '--others', '--exclude-standard', '--', 'app/src', 'crop/src'])
            h.update(others)
            for f in sorted(others.decode(errors='replace').splitlines()):   # untracked sources (app/src/debug: LabControl,
                try:                                                        # the debug manifest): their CONTENT counts too
                    h.update(open(os.path.join(config.LAB, f), 'rb').read())
                except OSError:
                    pass
            for sub in self.SUBS:
                d = os.path.join(config.LAB, sub)
                if os.path.exists(os.path.join(d, '.git')):
                    h.update(sub.encode() + g(['rev-parse', 'HEAD'], d) + g(['diff', 'HEAD', '--binary'], d))
            h.update(((self.cfg.get('lab') or {}).get('repro_install') or '').encode())
            return h.hexdigest()[:20]
        except Exception as e:
            print(f'[worker] build key not computed ({str(e)[:120]}); building', flush=True)
            self._bk_err = str(e)[:200]
            return ''

    def _cache_apk(self, ref, key, t0, keep=3):
        """Keep the APK THIS build wrote (outputs/ for a plain build, intermediates/ with the single-ABI flag); an APK
        older than the build start is stale and is never cached."""
        import shutil
        cands = [os.path.join(config.LAB, self.APK),
                 os.path.join(config.LAB, 'app/build/intermediates/apk/productionInternal/debug/app-productionInternal-debug.apk')]
        cands = [c for c in cands if os.path.exists(c) and os.path.getmtime(c) >= t0 - 1]
        d = os.path.join(config.REPO, 'tools/nightshift/out/apk_cache')
        try:
            if not cands:
                self.log(ref, 'build not cached: no APK written by this build was found')
                return
            src = max(cands, key=os.path.getmtime)
            os.makedirs(d, exist_ok=True)
            shutil.copy2(src, os.path.join(d, f'{key}.apk.tmp'))
            os.replace(os.path.join(d, f'{key}.apk.tmp'), os.path.join(d, f'{key}.apk'))
            olds = sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith('.apk')), key=os.path.getmtime)
            for f in olds[:-keep]:                         # keep the newest few (each is ~600 MB)
                os.remove(f)
            self.log(ref, f'build cached for reuse ({key[:12]}; {min(len(olds), keep)} kept)')
        except Exception as e:
            self.log(ref, f'build not cached: {str(e)[:120]}')

    def _phone_build(self):
        """When the app on the phone was last installed (changes on any reinstall, by us or by hand)."""
        try:
            out = subprocess.run(f'adb shell dumpsys package {config.app_package(getattr(self, "cfg", None))} | grep -m1 lastUpdateTime', shell=True,
                                 capture_output=True, text=True, timeout=30).stdout.strip()
            return out.split('=', 1)[-1].strip() if 'lastUpdateTime' in out else ''
        except Exception:
            return ''

    def _source_changed_since(self, stamp):
        """True when any file Gradle builds from is newer than the stamp: every module folder (has a build.gradle),
        the native submodules under extra/, and the root gradle files. Other folders in the repo (notes, outputs,
        tools) are not part of the APK and never trigger a build. Hooks and fixes edit module files, so they count."""
        root = config.LAB
        dirs = [d for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d)) and not d.startswith('.')
                and (any(os.path.exists(os.path.join(root, d, f)) for f in ('build.gradle', 'build.gradle.kts', 'CMakeLists.txt'))
                     or d in ('extra', 'gradle'))]
        files = [f for f in os.listdir(root) if f.endswith(('.gradle', '.gradle.kts', '.properties'))]
        find = (r"find " + ' '.join(f'"./{d}"' for d in dirs) +
                r" \( -name .git -o -name build -o -name .gradle -o -name .cxx -o -name .idea -o -name node_modules \) -prune"
                f' -o -type f -newer "{stamp}"' r" ! -name '*.md' ! -name .DS_Store -print -quit")
        try:
            newer_root = any(os.path.getmtime(os.path.join(root, f)) > os.path.getmtime(stamp) for f in files)
            res = subprocess.run(find, shell=True, cwd=root, capture_output=True, text=True, timeout=120)
            return newer_root or bool(res.stdout.strip()) or res.returncode != 0
        except Exception:
            return True

    def _same_build_on_phone(self, cmd):
        import json
        st = os.path.join(config.REPO, self.STAMP)
        try:
            meta = json.load(open(st + '.json'))
        except Exception:
            return False
        if meta.get('cmd') != cmd or not meta.get('phone') or meta['phone'] != self._phone_build():
            return False
        return os.path.exists(st) and not self._source_changed_since(st)

    def _save_install(self, cmd, t0):
        """After a good install: remember when the build STARTED (an edit during the build still triggers the next
        build) and which install the phone has. After a failed one: forget, so the next run builds."""
        import json
        st = os.path.join(config.REPO, self.STAMP)
        try:
            if t0 is None:
                if os.path.exists(st + '.json'):
                    os.remove(st + '.json')
                return
            open(st, 'w').close()
            os.utime(st, (t0, t0))
            json.dump({'cmd': cmd, 'phone': self._phone_build(), 'at': t0}, open(st + '.json', 'w'))
        except Exception:
            pass

    def _install(self, ref, hooks):
        """Build + install the debug build, with the given debug-hook patches applied for this build only."""
        import subprocess as sp
        busy = [l for l in sp.run(['pgrep', '-lf', 'tools/stress/'], capture_output=True, text=True).stdout.splitlines()
                if 'stress_results/lanes/' not in l]          # emulator lane runs do not use the phone
        if busy:
            raise RuntimeError('another stress run is using the phone; try again when it finishes')
        install = (self.cfg.get('lab') or {}).get('repro_install') or self.cfg['lab']['anrsan_install']
        applied = []
        try:
            for h in hooks:
                p = os.path.join(config.REPO, h)
                if self.run_cmd(ref, f'git --no-optional-locks apply "{p}"', 60, cwd=config.LAB) == 0 or \
                        self.run_cmd(ref, f'git --no-optional-locks apply --recount "{p}"', 60, cwd=config.LAB) == 0:
                    applied.append(p)
                    self.log(ref, f'debug hook applied for this build only: {h}')
                elif getattr(self, '_hooks_strict', False):
                    raise RuntimeError(f'patch does not apply to the lab code: {h}')
            if self.install_app(ref):
                raise RuntimeError('build/install failed: the phone still has the old app, so this run would prove nothing')
        finally:
            for p in reversed(applied):            # the working tree goes back exactly as it was; never committed
                subprocess.run(['git', '--no-optional-locks', 'apply', '-R', p], cwd=config.LAB, capture_output=True, timeout=60)
                self.log(ref, f'debug hook reverted: {os.path.relpath(p, config.REPO)}')

    def _step_stats(self, key, st, res, secs):
        """Keep each ladder step's track record (runs, hits, seconds) in lab_repros.json for smart ordering."""
        try:
            p = os.path.join(config.REPO, 'tools/nightshift/lab_repros.json')
            reg = json.load(open(p))
            for s_ in (reg.get(key) or {}).get('ladder') or []:
                if s_.get('name') == st.get('name'):
                    s_['stat_runs'] = (s_.get('stat_runs') or 0) + int(res.get('runs') or 0)
                    s_['stat_hits'] = (s_.get('stat_hits') or 0) + int(res.get('hits') or 0)
                    s_['stat_secs'] = round((s_.get('stat_secs') or 0) + secs)
            json.dump(reg, open(p, 'w'), indent=1)
        except Exception as e:
            print(f'[worker] step stats not saved: {e}', flush=True)

    def run_ladder(self, ref, case, key, spec):
        expect = list(spec.get('expect') or [])
        steps = sorted(spec['ladder'], key=lambda st: st.get('level', 9))
        if self._boost_cfg().get('smart_order'):
            # steps that have reproduced before go first (natural ones ahead of hooked ones, then by hit rate); steps
            # that never hit stay after them in level order. Stats live on each step in lab_repros.json.
            def rank(st):
                t, h = st.get('stat_runs') or 0, st.get('stat_hits') or 0
                return (0 if h else 1, 0 if (h and st.get('natural', True)) else 1, -(h / t if t else 0), st.get('level', 9))
            steps = sorted(steps, key=rank)
        self.log(ref, f'repro ladder for {key}: ' + ' -> '.join(f"L{st.get('level')} {st['name']}" for st in steps)
                 + (f'; must match field frames: {", ".join(expect)}' if expect else ''))
        self._install(ref, [st['hook_patch'] for st in steps if st.get('hook_patch')])
        attempts, hit = [], None
        for st in steps:
            self.log(ref, f"--- level {st.get('level')}: {st['name']} ({'natural' if st.get('natural', True) else 'hook-assisted'})")
            t_step = time.time()
            sr, sh = (st.get('stat_runs') or 0), (st.get('stat_hits') or 0)
            if self._boost_cfg().get('fast_confirm') and sr >= 2 and sh / sr >= 0.6 and int(st.get('repeat') or 2) > 1:
                st = dict(st, repeat=1)            # a step that has reproduced before: one hit is enough here, the
                self.log(ref, 'fast confirm: proven step, 1 run (the recorded run after it is the confirmation)')
            res = self._ladder_step(ref, st, expect + list(st.get('expect') or []))
            self._step_stats(key, st, res, time.time() - t_step)
            res.update({'level': st.get('level'), 'name': st['name'], 'natural': st.get('natural', True)})
            res.update({k: st.get(k) for k in ('cmd', 'scenario', 'hook_patch', 'repeat') if st.get(k)})
            attempts.append(res)
            self.log(ref, f"level {st.get('level')} result: {res['result']} ({res['hits']}/{res['runs']} runs match the field)"
                     + (f"; {res['why']}" if res.get('why') else ''))
            if res['hits']:
                hit = res
                break
        return hit, attempts

    def lab_evidence(self, ref, case_id, run_dir, mp4=None):
        """Crash window data from one crashing lab run: the lab crash parsed and symbolized against the exact build
        (BuildId), and the video + step timeline published to the board."""
        import importlib
        from . import labcrash
        importlib.reload(labcrash)
        upd = {}
        lab = labcrash.symbolize(labcrash.parse(run_dir))
        if lab:
            upd['labCrash'] = lab
            self.log(ref, f"lab crash: {lab.get('signal')} · {len(lab.get('frames') or [])} frames · symbols "
                          + (f"from {lab['symbols']['lib']} (BuildId {lab['buildId'][:12]})" if (lab.get('symbols') or {}).get('lib') else 'not found locally'))
        if mp4:
            crash_t = None
            try:                                      # crash second inside the video, from steps.log
                steps = open(os.path.join(run_dir, 'steps.log'), errors='replace').read()
                t0 = re.search(r'^(\d\d:\d\d:\d\d)', steps, re.M).group(1)
                tc = re.search(r'^(\d\d:\d\d:\d\d) ✖', steps, re.M).group(1)
                sec = lambda h: sum(int(x) * k for x, k in zip(h.split(':'), (3600, 60, 1)))
                crash_t = max(0, sec(tc) - sec(t0) - 2)
            except Exception:
                pass
            upd.update(labcrash.publish_video(case_id, mp4, crash_t))
            self.log(ref, f"repro video published to the board: {upd['reproVideoUrl']}")
        return upd

    def record_video(self, ref, case, hit, expect, tries=3):
        """After a repro: run the winning scenario again with the screen recorded, and keep the video only if that run
        crashes again with every field frame. Discovery runs are never recorded (the recorder uses the video encoder,
        which could change a codec race), so this is also one more confirmation of the repro."""
        import glob
        sc = hit.get('scenario')
        if not sc:
            self.log(ref, 'repro video: this step is a script, not a scenario; no video')
            return
        hd = hit.get('dir') or ''
        hd = hd if os.path.isabs(hd) else os.path.join(config.REPO, hd)
        have = os.path.join(hd, 'repro_video.mp4')
        if os.path.exists(have) and os.path.getsize(have) > 10000:   # an emulator lane recorded the crashing run itself
            rel = os.path.relpath(have, config.REPO)
            upd = {'reproVideo': rel, 'reproVideoNote': 'Recorded during the run that froze/crashed (emulator, host-side recording)'}
            upd.update(self.lab_evidence(ref, case['id'], hd, have))
            self.db.collection('cases').document(case['id']).update(upd)
            self.log(ref, f'repro video: the crashing run itself was recorded: {rel}')
            try:
                self.maybe_deploy(ref)
            except Exception as e:
                self.log(ref, f'board deploy for the video failed: {str(e)[:150]}')
            return rel
        rd = os.path.join(config.REPO, self.cfg['lab']['results_dir'])
        # Record on the SAME device and under the SAME conditions as the run that crashed (an emulator hit is recorded on
        # that emulator, host-side, with the same lab boost); only the last try switches the lab shortcuts off.
        m_ = re.search(r'stress_results/lanes/([^/]+)/', (hit.get('dir') or '').replace(os.sep, '/'))
        lane = m_.group(1) if m_ else ''
        where = lane or 'the phone'
        self.log(ref, f'repro video: running {sc} again on {where} with the screen recorded, same conditions as the crash '
                      f'(up to {tries} tries; the last one with real taps only)')
        lane_rd = os.path.join(config.REPO, 'stress_results', 'lanes', lane) if lane else ''
        for k in range(1, tries + 1):
            before = set(glob.glob(os.path.join(rd, '*'))) | (set(glob.glob(os.path.join(lane_rd, '*'))) if lane else set())
            st_ = {'scenario': sc, 'repeat': 1, 'name': sc, 'record': True, 'lane': lane,
                   'real_taps': k == tries and tries > 1, 'boost': hit.get('boost')}
            res = self._ladder_step(ref, st_, expect)
            new = sorted((set(glob.glob(os.path.join(rd, '*'))) | (set(glob.glob(os.path.join(lane_rd, '*'))) if lane else set())) - before)
            vids = [v for d in new for v in glob.glob(os.path.join(d, '*', 'repro_video.mp4'))]
            if res.get('hits') and vids:
                rel = os.path.relpath(vids[-1], config.REPO)
                upd = {'reproVideo': rel, 'reproVideoNote': ('Recorded on the first try' if k == 1 else f'Recorded on try {k}') + ' · the app crashes the same way it did for users'}
                upd.update(self.lab_evidence(ref, case['id'], os.path.dirname(vids[-1]), vids[-1]))
                self.db.collection('cases').document(case['id']).update(upd)
                self.log(ref, f'repro video saved: {rel} (steps as subtitles in repro_video.srt)')
                import threading as _th               # SPEED: the board deploy runs beside the fix stage (~1.5 min)
                def _dep():
                    try:
                        self.maybe_deploy(ref)           # the crash window plays it from the board
                    except Exception as e:
                        self.log(ref, f'board deploy for the video failed: {str(e)[:150]}')
                _th.Thread(target=_dep, daemon=True).start()
                return rel
            self.log(ref, f'repro video try {k}: ' + ('crashed but no video file' if res.get('hits') else
                                                      f'automation stopped before the crash: {res.get("why", "")[:160]}' if res.get('errors')
                                                      else 'reached the end and did not crash this time'))
        self.db.collection('cases').document(case['id']).update(
            {'reproVideo': '', 'reproVideoNote': f'not captured: the crash did not recur in {tries} recorded runs'})
        self.log(ref, f'repro video: not captured in {tries} tries (the repro itself stands)')

    def _record(self, ref, case, attempts, hit):
        clean = [{k: a.get(k) for k in ('level', 'name', 'scenario', 'result', 'hits', 'runs', 'fails', 'errors', 'why',
                                         'natural', 'seed', 'dir', 'author', 'hook_patch')} for a in attempts]
        upd = {'reproAttempts': clean, 'labRuns': sum(x.get('runs') or 0 for x in attempts),
               'labFailures': sum(x.get('fails', 0) for x in attempts)}
        if hit:
            upd.update({'status': 'reproduced', 'reproLevel': hit['level'], 'reproNatural': hit['natural'],
                        'reproRate': f"{hit['hits']}/{hit['runs']}", 'repro_scenario': hit['name'],
                        'repro_step': {k: hit.get(k) for k in ('level', 'name', 'scenario', 'cmd', 'natural', 'hook_patch') if hit.get(k)},
                        'repro_seed': str(hit.get('seed') or ''), 'repro_dir': hit.get('dir', ''),
                        'reproAuthor': bool(hit.get('author')),
                        'labBusy': hit.get('busy') or getattr(self, '_last_busy', '') or '',
                        'labMatch': (f"level {hit['level']} ({'natural' if hit['natural'] else 'hook-assisted'}): "
                                     f"{hit['name']}, {hit['hits']}/{hit['runs']} runs; "
                                     + (f"lab dump has the stack of same-bug family member {hit['family_hit']}, not this card's exact frames"
                                        if hit.get('family_hit') else 'lab dump has every field frame')
                                     + ('; script written by Night Shift' if hit.get('author') else ''))})
            self.log(ref, 'REPRODUCED at ' + upd['labMatch'])
            try:                                  # root cause v2 on the board right away: the trigger is confirmed
                import importlib
                from . import labupdate as _lu
                importlib.reload(_lu)
                _lu.quick_repro(self.db, case['id'], dict(hit, labMatch=upd['labMatch']), log=lambda l: self.log(ref, l))
            except Exception as e:
                self.log(ref, f'root cause v2: not written ({str(e)[:150]})')
        else:
            upd['status'] = 'not-reproduced'
            self.log(ref, f'not reproduced ({len(attempts)} registered ladder step(s); the repro author attempts are listed above)')
        self.db.collection('cases').document(case['id']).update(upd)
        try:                                      # Time saved: the real clock minutes Night Shift spent ("after")
            from . import runlog
            if not hit and not getattr(self, '_lab_steps', 0):
                raise RuntimeError('nothing ran on the phone, so this is not a run (no row: it would skew the stats)')
            mins = max(1, round((time.time() - getattr(self, '_t0', time.time())) / 60))
            runlog.add(config.repo_path(self.cfg['measurement']['runlog']), 'reproduce', case['id'], 'Night Shift', 'after',
                       mins, 0, 'reproduced' if hit else 'not reproduced',
                       (upd.get('labMatch') or f'{len(attempts)} attempts')[:120])
        except Exception as e:
            self.log(ref, f'time log not written: {str(e)[:120]}')

    def _pin_phone(self):
        """With an emulator lane running, plain `adb` would refuse ("more than one device"). Pin this process (and every
        command it starts) to the physical phone: the first non-emulator device."""
        os.environ.setdefault('ZESTY_PKG', config.app_package(getattr(self, 'cfg', None)))   # the phone driver's app (profile)
        want = str((getattr(self, 'cfg', None) or {}).get('lab', {}).get('phone_serial') or '').strip()
        if want:                                      # nightshift.yaml lab.phone_serial: always this phone
            os.environ['ANDROID_SERIAL'] = want
            return
        try:
            out = subprocess.run('adb devices', shell=True, capture_output=True, text=True, timeout=20).stdout
            phones = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith('device') and not l.startswith('emulator-')]
            if phones and os.environ.get('ANDROID_SERIAL') not in phones:
                os.environ['ANDROID_SERIAL'] = phones[0]
        except Exception:
            pass

    def _lane_rec(self, serial, fast=''):
        """Emulator lanes always record (host-side 'emu screenrecord': no guest encoder, no timing change); the video is
        kept only when that run crashes, so an emulator repro has its video without a second run."""
        on = ((self.cfg.get('lab') or {}).get('emulator_always_record', True))
        return ' --record' if on and serial.startswith('emulator-') and '--record' not in fast else ''

    def _run_lane(self, ref, serial, cmd):
        """One scenario command on an emulator lane (ANDROID_SERIAL in cmd); its key lines go to the job log."""
        try:
            p = subprocess.Popen(cmd, shell=True, cwd=config.REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 start_new_session=True)
            for line in p.stdout:
                if re.search(r'(▶|■|✖|⚠)', line):
                    self.log(ref, f'[{serial}] ' + line.rstrip()[:260])
            p.wait(timeout=3600)
        except Exception as e:
            self.log(ref, f'[{serial}] lane run failed: {str(e)[:160]}')

    def _lanes_start(self, ref):
        """boost.lanes: boot that many emulator lanes in the background, one after another (while the crash build
        compiles). A lane joins the runs as soon as it is booted AND has this job's APK and a test project; the phone
        never waits for it."""
        n = int(self._boost_cfg().get('lanes') or 0)
        self._lane_serials, self._lane_apk, self._lane_busy, self._lanes_booted = [], None, set(), False
        self._lane_ready = set()                       # every job boots fresh read-only lanes: prep again
        if not n:
            return
        import importlib
        from . import lanes as _lanes
        importlib.reload(_lanes)                       # the worker is long-running: always the current lanes code
        if not _lanes.available():
            self.log(ref, 'lab lanes: no Android emulator on this Mac; phone only')
            return
        import threading as _th
        self._lanes_ref = ref
        self._lanes_lock = _th.Lock()
        self._lanes = _lanes.Lanes(n, log=lambda m: self.log(ref, m), on_ready=lambda s: self._lane_setup(s))
        # the boot starts AFTER the crash build (see _lanes_install): two emulators booting next to Gradle on the 16 GB M1
        # starved the build (2026-10-13: a gradle run killed at once, exit -13) and one lane never booted
        self._lanes_th = _th.Thread(target=self._lanes.up, daemon=True)

    def _lane_setup(self, serial):
        """One booted lane: install the current APK, give it a test project once per boot, then let runs use it."""
        apk = self._lane_apk
        if not apk or not getattr(self, '_lanes', None):
            return                                     # no APK yet: _lanes_install sets it up when the build is done
        with self._lanes_lock:
            if serial in self._lane_busy:
                return
            self._lane_busy.add(serial)
        try:
            ref = self._lanes_ref
            if not self._lanes.install(apk, only=[serial]):
                return
            if serial not in self._lane_ready:
                clip = os.path.join(config.REPO, 'tools/nightshift/out/audio/assets/ns_audio_splits.mp4')
                if os.path.exists(clip):
                    subprocess.run(['adb', '-s', serial, 'shell', 'mkdir -p /sdcard/DCIM/NightShift'], capture_output=True, timeout=30)
                    subprocess.run(['adb', '-s', serial, 'push', clip, '/sdcard/DCIM/NightShift/ns_lane_clip.mp4'], capture_output=True, timeout=120)
                    subprocess.run(['adb', '-s', serial, 'shell', 'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
                                    '-d file:///sdcard/DCIM/NightShift/ns_lane_clip.mp4'], capture_output=True, timeout=30)
                self._run_lane(ref, serial, f'ANDROID_SERIAL={serial} {PY} tools/stress/scenarios.py run lab_make_test_draft --repeat 1 '
                                            f'--fresh on --reset none --out stress_results/lanes/{serial}/prep')
                self._lane_ready.add(serial)
            if apk == self._lane_apk and serial not in self._lane_serials:
                self._lane_serials = self._lane_serials + [serial]      # new list: readers never see a half update
                self.log(ref, f'lab lanes: {serial} joins the runs (same APK as the phone)')
        finally:
            with self._lanes_lock:
                self._lane_busy.discard(serial)

    def _lanes_install(self, ref, apk):
        """A new APK (crash build, or the fix build): lanes drop out until they have it; booted ones get it now in the
        background, lanes still booting get it when they are ready."""
        if not getattr(self, '_lanes', None) or not apk or not os.path.exists(apk):
            return
        import threading as _th
        self._lane_apk, self._lane_serials = apk, []
        if not self._lanes_th.is_alive() and not self._lanes.serials and not getattr(self, '_lanes_booted', False):
            self._lanes_booted = True
            self._lanes_th.start()
            self.log(ref, 'lab lanes: booting now that the build is done; the phone starts and the lanes join when ready')
            return
        for s_ in list(self._lanes.serials):
            _th.Thread(target=self._lane_setup, args=(s_,), daemon=True).start()
        if not self._lanes.serials:
            self.log(ref, 'lab lanes: still booting; the phone starts now and the lanes join when ready')

    def _lanes_stop(self):
        if getattr(self, '_lanes', None):
            try:
                self._lanes.down()
            except Exception:
                pass
            self._lanes, self._lane_serials = None, []

    def _turbo(self):
        """out/experiment.json "turbo": engine replay, adaptive verify, run cutoff (absent = classic behaviour).
        Rollback: tools/nightshift/turbo_rollback.py off|code|history|all."""
        try:
            return (json.load(open(os.path.join(config.REPO, 'tools/nightshift/out/experiment.json'))) or {}).get('turbo') or {}
        except Exception:
            return {}

    def _cutoff(self, st):
        """turbo.run_max_s: a lab run that goes far past a normal run is stopped as an automation error (a timer in the
        test runner, not in the app). Never on the recorded proof run."""
        n = int(st.get('max_s') or self._turbo().get('run_max_s') or 0)
        return f' --scenario-timeout {n}' if n and not st.get('record') else ''

    def _boost_cfg(self):
        try:
            return (json.load(open(os.path.join(config.REPO, 'tools/nightshift/out/experiment.json'))) or {}).get('boost') or {}
        except Exception:
            return {}

    def _boost_on(self, ref, st=None):
        """Speed-up switches for a lab run (out/experiment.json "boost"): the lab watchdog (near-ANR with the field stack),
        and CPU load on the phone for ANR cases (a fast lab phone behaves like the slow field devices)."""
        b = self._boost_cfg()
        if not b:
            return None
        wd = int(b.get('watchdog_ms') or 0)
        if wd:
            subprocess.run(f'adb shell setprop debug.zesty.wd_ms {wd}', shell=True, capture_output=True, timeout=30)
            for ln in getattr(self, '_lane_serials', None) or []:
                subprocess.run(f'adb -s {ln} shell setprop debug.zesty.wd_ms {wd}', shell=True, capture_output=True, timeout=30)
        load = int(b.get('cpu_load') or 0) if getattr(self, '_case_kind', '') == 'ANR' or b.get('cpu_load_all') else 0
        if st is not None and (not st.get('natural', True) or st.get('lane') or st.get('setup')):
            load = 0     # hooked steps force the freeze; a run on one emulator lane leaves the phone idle (the load is phone-only)
        # a recorded run keeps the load: it must run under the same conditions as the run that crashed
        pids = []
        for _ in range(load):
            r = subprocess.run("adb shell 'nohup sh -c \"while :; do :; done\" >/dev/null 2>&1 & echo $!'", shell=True,
                               capture_output=True, text=True, timeout=30)
            if r.stdout.strip().isdigit():
                pids.append(r.stdout.strip())
        alive = ''
        if pids:
            time.sleep(1)
            r = subprocess.run("adb shell 'ps -A -o PID,ARGS | grep -v grep | grep -c \"while :\"'", shell=True,
                               capture_output=True, text=True, timeout=30)
            alive = f' ({r.stdout.strip() or "?"} running)'
        if wd or pids:
            self.log(ref, f'lab boost: watchdog {wd} ms' + (f', CPU load x{len(pids)} on the phone{alive}' if pids else ''))
        return {'wd': wd, 'pids': pids}

    def _boost_off(self, ref, b):
        if not b:
            return
        if b.get('pids'):
            subprocess.run(f"adb shell kill {' '.join(b['pids'])}", shell=True, capture_output=True, timeout=30)
        if b.get('wd'):
            subprocess.run('adb shell setprop debug.zesty.wd_ms 0', shell=True, capture_output=True, timeout=30)

    def _ladder_step(self, ref, st, expect):
        """Run one ladder step. Script steps (cmd) write stress_results/repro_*/summary.json; scenario steps write
        stress_results/<time>/summary.csv. A run counts only if its dump/logs contain every expected field frame."""
        self.reset_hooks(ref)                      # each level starts with every hook off; hooked scenarios arm their own
        self._lab_steps = getattr(self, '_lab_steps', 0) + 1
        import csv, glob, json as js
        res_dir = os.path.join(config.REPO, self.cfg['lab']['results_dir'])
        before = set(glob.glob(os.path.join(res_dir, '*')))
        lane_glob = os.path.join(config.REPO, 'stress_results', 'lanes', '*', '*')
        before_l = set(glob.glob(lane_glob))
        if st.get('scenario'):
            fast = ' --stop-on-error --ui-stall 30' if st.get('fast') else ''   # Night Shift's own scripts: fail fast
            fast += ' --record' if st.get('record') else ''
            fast += self._cutoff(st)
            # the recorded confirmation run uses real taps end to end (lab-control shortcuts off): a repro whose setup used
            # shortcuts counts only if it also crashes this way
            env = 'ZESTY_LAB=0 ' if st.get('real_taps') else ''
            if re.fullmatch(r'(ZESTY_\w+=[\w./-]+ )+', st.get('env') or ''):
                env += st['env']                       # e.g. turbo replay check: ZESTY_JNI_REPEAT=10
            boost = self._boost_on(ref, st)
            jv = [e[5:] if e.startswith('MAIN:') else e for e in expect]
            jv = [e for e in jv if '.' in e and '::' not in e and not e.startswith('JNI_')]
            if boost and boost.get('wd') and jv:
                env += 'ZESTY_WD_EXPECT="' + '|'.join(e.replace('"', '') for e in jv) + '" '
            # a live-agent replay ('_live<n>') taps the phone's own pixel positions on the phone's own project: on an
            # emulator (other screen size, other projects) it only ever errors, so it runs on the phone alone
            live_replay = bool(re.search(r'_live\d+$', st.get('scenario') or ''))
            lanes = [] if (st.get('record') or st.get('phone_only') or live_replay) else list(getattr(self, '_lane_serials', None) or [])
            rep = int(st.get('repeat', 2))
            try:
                if st.get('lane'):                     # one named device lane only (e.g. the recorded run of an emulator hit)
                    ln = st['lane']
                    self.log(ref, f'lab lane: {st["scenario"]} x{rep} on {ln}')
                    self._run_lane(ref, ln, f"ANDROID_SERIAL={ln} {env}{PY} tools/stress/scenarios.py run "
                                   f"{st['scenario']} --repeat {rep} --fresh on{fast} --out stress_results/lanes/{ln}")
                elif lanes:                              # phone + emulator lanes side by side; the runs are split between them
                    import math, threading as _th
                    per = max(1, math.ceil(rep / (1 + len(lanes))))
                    self.log(ref, f'lab lanes: {st["scenario"]} x{per} on the phone and on {", ".join(lanes)} at the same time')
                    ths = [_th.Thread(target=self._run_lane, args=(ref, ln, f"ANDROID_SERIAL={ln} {env}{PY} tools/stress/scenarios.py run "
                                      f"{st['scenario']} --repeat {per} --fresh on{fast}{self._lane_rec(ln, fast)} --out stress_results/lanes/{ln}"), daemon=True) for ln in lanes]
                    [t.start() for t in ths]
                    self.run_cmd(ref, f"{env}{PY} tools/stress/scenarios.py run {st['scenario']} --repeat {per} --fresh on{fast}", 3600)
                    [t.join(3600) for t in ths]
                else:
                    self.run_cmd(ref, f"{env}{PY} tools/stress/scenarios.py run {st['scenario']} --repeat {rep} --fresh on{fast}", 3600)
            finally:
                self._boost_off(ref, boost)
        else:
            self.run_cmd(ref, f"{PY} {st['cmd']}", 3600)
        new = sorted(set(glob.glob(os.path.join(res_dir, '*'))) - before) + sorted(set(glob.glob(lane_glob)) - before_l)
        new = [d for d in new if os.path.basename(d) != 'lanes']
        res = dict(self._eval_runs(new, expect), dirs=new)
        if res.get('busy'):                            # looper-wait ANR: what made the engine's message thread slow
            self.log(ref, f"engine message thread at the ANR (what made it slow): {res['busy'][:260]}")
            self._last_busy = res['busy']
        return res

    def _eval_runs(self, new, expect):
        """Count runs / app failures / field matches in the given result folders (one ladder step, or one lane)."""
        import csv, json as js
        runs, fails, hits, first, missing_seen = 0, 0, 0, None, set()
        busy_seen = []
        errors, others, known, trunc = [], [], 0, 0
        try:
            from . import groups as _sg
        except Exception:
            _sg = None
        me = getattr(self, '_card_under_test', None)
        for d in new:
            rows = []
            if os.path.exists(os.path.join(d, 'summary.csv')):
                rows = [dict(r, dir=r.get('dir') or d) for r in csv.DictReader(open(os.path.join(d, 'summary.csv')))]
                rows = [dict(r, failed=r.get('status', '').startswith('FAIL')) for r in rows]
            elif os.path.exists(os.path.join(d, 'summary.json')):
                sj = js.load(open(os.path.join(d, 'summary.json')))
                rows = [{'dir': os.path.join(d, f"try_{r.get('try')}"), 'seed': sj.get('seed'),
                         'failed': r.get('verdict') in ('REPRODUCED', 'OTHER CRASH'), 'verdict': r.get('verdict')}
                        for r in sj.get('results', [])]
            for r in rows:
                r['dir'] = r['dir'] if os.path.isabs(r['dir']) else os.path.join(config.REPO, r['dir'])
                runs += 1
                if r.get('status') == 'ERROR' or r.get('verdict') in ('UI STUCK', 'ERROR'):
                    errors.append((r.get('detail') or r.get('verdict') or 'automation error')[:160])
                if not r['failed']:
                    continue
                fails += 1
                rd = r['dir'] if os.path.isabs(r['dir']) else os.path.join(config.REPO, r['dir'])
                text, cframes, cfault, cthread = crash_evidence(rd)
                wdlog = ''.join(l for l in open(os.path.join(rd, 'logcat.txt'), errors='replace') if 'ZWATCHDOG' in l) \
                    if os.path.exists(os.path.join(rd, 'logcat.txt')) else ''
                main = ''
                if any(e.startswith('MAIN:') for e in expect):    # the main thread's own stack in the ANR dump
                    m_ = re.search(r'"main"[^\n]*\n(?:[^\n]+\n){0,400}', text)   # the whole main block: Java frames sit deep under ART frames
                    main = m_.group(0) if m_ else ''
                def _has(e):                          # 'MAIN:' = in the main thread's own stack; 'a|b' = any of them
                    hay = main if e.startswith('MAIN:') else text
                    return any(x and x in hay for x in (e[5:] if e.startswith('MAIN:') else e).split('|'))
                miss = [e for e in expect if not _has(e)]
                fs = getattr(self, '_field_short', None)
                if miss and fs and cframes and len(cframes) <= 2 and not any(f['lib'] == 'libMYJNILIB26.so' for f in cframes):
                    # the realme's unwinder stops inside libc/libc++ (2 frames): when those frames' libraries AND the fault
                    # address are exactly the field crash's own top frames and fault, it IS the field crash
                    try:
                        lab_fault = int(cfault, 16) if cfault and cfault.startswith('0x') else None
                    except ValueError:
                        lab_fault = None
                    if lab_fault is not None and lab_fault == fs['fault'] and [f['lib'] for f in cframes] == fs['libs'][:len(cframes)]:
                        miss = []
                        r['cut_short_match'] = True
                if miss and 'ZWATCHDOG MAIN_BLOCKED' in wdlog:
                    text = text + '\n' + wdlog
                    # lab watchdog: the main thread was blocked >= the threshold with the field's Java frames on its stack.
                    # Native frames never show on a Java stack, so only the Java ones are required here.
                    jv = [e[5:] if e.startswith('MAIN:') else e for e in expect]
                    jv = [e for e in jv if '.' in e and '::' not in e and not e.startswith('JNI_')]
                    wd = '\n'.join(l for l in text.splitlines() if 'ZWATCHDOG' in l)
                    if jv and all(e in wd for e in jv):
                        miss = []
                        r['near_anr'] = True
                if miss and expect and getattr(self, '_family', None):
                    for c_, t_, ex_ in self._family:      # confirmed same-bug family: another member's stack is a hit too
                        if ex_ and all(e in text for e in ex_):
                            miss = []
                            r['family_hit'] = t_
                            break
                if r.get('verdict') == 'OTHER CRASH' and not expect:
                    miss = ['the target frame']
                missing_seen.update(miss)
                try:                                  # looper-wait ANR: what the engine's message thread was busy doing
                    from . import author as _au
                    r['busy'] = _au.engine_busy(text) if 'MsgLooper::Get' in text else ''
                except Exception:
                    r['busy'] = ''
                if r['busy']:
                    busy_seen.append(r['busy'])
                if not miss:
                    hits += 1
                    first = first or r
                else:                                 # a different crash: name it, and say if it is a known card's bug
                    card, title = (_sg.find_card(cframes, exclude=me) if _sg and cframes else (None, None))
                    known += bool(card)
                    # a native dump the unwinder cut short (realme: 2 frames, libc/libc++ only, no app frame) says nothing
                    # about WHICH bug crashed: unknown, worth one re-run, never a verdict on its own
                    short = bool(cframes) and len(cframes) <= 2 and not card and \
                        not any(f['lib'] == 'libMYJNILIB26.so' for f in cframes) and 'FATAL EXCEPTION' not in text and 'ANR in ' not in text
                    trunc += short
                    others.append({'label': crash_label(cframes, cfault, cthread) or (r.get('detail') or r.get('verdict') or '?')[:160],
                                   'card': card, 'title': title, 'truncated': short, 'dir': os.path.relpath(rd, config.REPO)})
        why = ''
        if not hits:
            why = (f'automation did not reach the trigger in {len(errors)}/{runs} runs: {errors[0]}' if errors and not fails else
                   'no crash/ANR in any run (trigger too weak for this phone)' if not fails else
                   f'{fails} failure(s) but different from the field: missing {", ".join(sorted(missing_seen))[:200]}'
                   + (f'; it was: {others[0]["label"][:180]}' if others else '')
                   + (f' = known bug {others[0]["title"]}' if others and others[0].get('card') else '')
                   + (f'; engine message thread was busy in: {busy_seen[0][:200]}' if busy_seen else ''))
        if hits and (first or {}).get('cut_short_match'):
            why = ('matched on the field crash\'s own top frames (' + ' <- '.join((getattr(self, '_field_short', None) or {}).get('libs', [])[:2])
                   + f") and fault address {hex((getattr(self, '_field_short', None) or {}).get('fault', 0))}; this phone's unwinder stops before the app frames")
        if hits and (first or {}).get('family_hit'):
            why = (f"same-bug family hit: the lab crash has the stack of {first['family_hit']}, a confirmed member of this "
                   f"crash's family (same bug, other moment)")
        if hits and (first or {}).get('near_anr'):
            why = 'lab watchdog: main thread blocked with the field ANR stack (near-ANR; the system ANR dialog needs 5 s)'
        return {'runs': runs, 'fails': fails, 'hits': hits, 'errors': len(errors), 'result': 'reproduced' if hits else 'not reproduced', 'why': why,
                'others': others, 'known_other': known, 'truncated': trunc,
                'near_anr': bool((first or {}).get('near_anr')), 'family_hit': (first or {}).get('family_hit'),
                'seed': (first or {}).get('seed'), 'dir': os.path.relpath((first or {}).get('dir', ''), config.REPO) if first else '',
                'busy': ((first or {}).get('busy') or (busy_seen[0] if busy_seen else ''))}

    def _ladder_multi(self, ref, sts, expect):
        """Different recipes on different devices AT THE SAME TIME: sts[0] on the phone, sts[1:] on the emulator lanes
        (one each). Returns one result per recipe, each judged on its own runs. Used by the repro author."""
        import glob, threading as _th
        lanes = list(getattr(self, '_lane_serials', None) or [])
        sts = sts[:1 + len(lanes)]
        self.reset_hooks(ref)
        res_dir = os.path.join(config.REPO, self.cfg['lab']['results_dir'])
        before = set(glob.glob(os.path.join(res_dir, '*')))
        lane_before = {ln: set(glob.glob(os.path.join(config.REPO, 'stress_results', 'lanes', ln, '*'))) for ln in lanes}
        boost = self._boost_on(ref, sts[0])
        jv = [e[5:] if e.startswith('MAIN:') else e for e in expect]
        jv = [e for e in jv if '.' in e and '::' not in e and not e.startswith('JNI_')]
        env = ('ZESTY_WD_EXPECT="' + '|'.join(e.replace('"', '') for e in jv) + '" ') if boost and boost.get('wd') and jv else ''
        self.log(ref, 'lab lanes: ' + ', '.join(f"{st['scenario']} on {('the phone' if i == 0 else lanes[i - 1])}" for i, st in enumerate(sts)))
        ths = []
        for i, st in enumerate(sts[1:]):
            ln = lanes[i]
            fast = (' --stop-on-error --ui-stall 30' if st.get('fast') else '') + self._cutoff(st)
            ths.append(_th.Thread(target=self._run_lane, daemon=True, args=(ref, ln, f"ANDROID_SERIAL={ln} {env}{PY} tools/stress/scenarios.py run "
                       f"{st['scenario']} --repeat {int(st.get('repeat', 1))} --fresh on{fast}{self._lane_rec(ln, fast)} --out stress_results/lanes/{ln}")))
        [t.start() for t in ths]
        try:
            fast = (' --stop-on-error --ui-stall 30' if sts[0].get('fast') else '') + self._cutoff(sts[0])
            self.run_cmd(ref, f"{env}{PY} tools/stress/scenarios.py run {sts[0]['scenario']} --repeat {int(sts[0].get('repeat', 1))} --fresh on{fast}", 3600)
            [t.join(3600) for t in ths]
        finally:
            self._boost_off(ref, boost)
        d0 = sorted(set(glob.glob(os.path.join(res_dir, '*'))) - before)
        out = [dict(self._eval_runs(d0, expect), dirs=d0)]
        for i, st in enumerate(sts[1:]):
            ln = lanes[i]
            new = [d for d in sorted(set(glob.glob(os.path.join(config.REPO, 'stress_results', 'lanes', ln, '*'))) - lane_before[ln])
                   if os.path.basename(d) != 'prep']
            out.append(dict(self._eval_runs(new, expect), dirs=new))
        return out

    def do_pull(self, ref, case):
        rc = self.run_cmd(ref, f'{PY} tools/nightshift/sentinel.py pull {case["id"]} --llm', 900)
        if rc:
            raise RuntimeError(f'pull exited {rc}')

    def do_draft_fix(self, ref, case):
        """Fix rounds run on the code that crashed too (same shipped-code swap as Reproduce), so a fix already on the
        branch can not make Night Shift's own patch look verified."""
        self._restore_swaps(ref)
        use = (self.cfg.get('lab') or {}).get('build_as_shipped', True)
        swaps = self._shipped_swap(ref, case) if use else []
        try:
            return self._do_draft_fix(ref, case)
        finally:
            for p, b in swaps:
                open(p, 'wb').write(open(b, 'rb').read())
            if swaps:
                bdir = os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', case['id'])
                if os.path.exists(os.path.join(bdir, 'swapped.json')):
                    os.rename(os.path.join(bdir, 'swapped.json'), os.path.join(bdir, 'swapped.json.restored'))
                self.log(ref, f'working copy restored ({len(swaps)} file(s))')

    def _retro(self, ref, job, case):
        """Learning experiment: turn this job's log into generic lessons and credit the lessons the repro author used."""
        try:
            exp = json.load(open(os.path.join(config.REPO, 'tools/nightshift/out', 'experiment.json')))
        except Exception:
            exp = {}
        if not exp.get('lessons'):
            return
        try:
            import importlib
            from . import lessons as _ls, author as _au
            importlib.reload(_ls)
            tag = f'[{ref.id[:8]}]'
            lines = [l.rstrip() for l in open(os.path.join(config.REPO, 'tools/nightshift/out/jobs.log'), errors='replace')
                     if tag in l and 'C/C++' not in l]
            c = (self.db.collection('cases').document(case['id']).get().to_dict() or {})
            ok = bool(c.get('reproLevel') is not None) if job['action'] == 'reproduce' else bool(c.get('fixVerified'))
            if getattr(_au, '_USED_LESSONS', None):
                _ls.credit(set(_au._USED_LESSONS), bool(c.get('reproLevel') is not None))
                _au._USED_LESSONS.clear()
            frames = [f.get('fn', '') if isinstance(f, dict) else str(f) for f in (case.get('frames') or [])][:12]
            _ls.retro(self.cfg, case['id'], frames, lines, 'success' if ok else 'no success', log=lambda l: self.log(ref, l))
        except Exception as e:
            self.log(ref, f'lessons: retro skipped ({str(e)[:160]})')

    def _do_draft_fix(self, ref, case):
        if case.get('repro_step'):                  # reproduced by the ladder/author: full propose-verify-review loop
            import importlib
            from . import fixloop
            importlib.reload(fixloop)
            fixloop.run(self, ref, case, self._merged(case))
            return
        # step 8: propose; step 9: verify by applying, rebuilding, replaying, then reverting the working tree
        rc = self.run_cmd(ref, f'{PY} tools/nightshift/sentinel.py fix {case["id"]}', 900)
        patch = os.path.join(config.REPO, 'tools/nightshift/out/patches', f'{case["id"]}.patch')
        if rc or not os.path.exists(patch):
            raise RuntimeError('no patch proposed (see the job log / prompt pack)')
        seed, scen = case.get('repro_seed'), case.get('repro_scenario')
        patch_txt = open(patch).read()[:20000]
        if not (seed and scen):
            # nothing has reproduced this crash yet: a clean run would prove nothing, so do not claim verification
            self.db.collection('cases').document(case['id']).update({'status': 'fix-proposed', 'patch': patch_txt, 'fixVerified': False,
                'fixNote': 'Not verified: no lab run has reproduced this crash yet. Reproduce first (needs a scenario that triggers it), then verify by replaying that seed.'})
            self.log(ref, 'patch proposed; NOT verified because no reproducing seed exists yet')
            return
        if self.run_cmd(ref, f'git apply --check "{patch}"', 60):
            raise RuntimeError('patch does not apply to the current tree')
        self.run_cmd(ref, f'git apply "{patch}"', 60)
        try:
            if self.run_cmd(ref, self.cfg['lab']['anrsan_install'], 2400):
                raise RuntimeError('build/install with the patch failed: not verified')
            rc2 = self.run_cmd(ref, f'{PY} tools/stress/scenarios.py replay {scen} --seed {seed}', 3600)
        finally:
            self.run_cmd(ref, f'git apply -R "{patch}"', 60)   # leave the working tree exactly as it was
        verified = (rc2 == 0)
        self.db.collection('cases').document(case['id']).update({
            'status': 'fix-verified' if verified else 'fix-failed', 'patch': patch_txt, 'fixVerified': verified,
            'fixNote': f'replayed {scen} seed {seed}: ' + ('clean' if verified else 'still fails')})
        self.log(ref, 'replay clean: fix verified' if verified else 'replay still fails: patch is not the fix')

    def _release_lab(self, job):
        if job.get('action') in ('reproduce', 'draft-fix'):
            try:
                self.db.collection('config').document(_lab_lock_id(self.cfg)).delete()
            except Exception:
                pass

    def handle_locked(self, snap, lock):
        # The phone is the only shared resource: lab jobs (reproduce / draft-fix) queue behind each other, but a
        # long sync (73 root causes, hours) must not block a Reproduce click. Locks live on the threading module
        # so they survive the per-job module reload.
        import importlib
        importlib.reload(config)                      # nightshift.yaml / lab_repros.json edits apply to the next job
        self.cfg = config.load()
        action = (snap.to_dict() or {}).get('action')
        self.heartbeat()
        if not self.route(snap.to_dict() or {}):       # another person's job, and their own worker is online: leave it
            return
        self._pin_phone()                             # every adb command of this job (and its scripts) goes to the lab phone
        # 2026-10-21: an Audio Check ran beside a Reproduce; the Reproduce install killed the export. Phone jobs share one lock.
        self.busy = _stable_lock('_ns_lab_lock' if action in ('reproduce', 'draft-fix', 'audio-check') else '_ns_other_lock')
        if action in ('reproduce', 'draft-fix'):        # lane runs left by a cancelled job would block the prebuild
            subprocess.run(['pkill', '-f', 'stress_results/lanes/'], capture_output=True)
            subprocess.run('adb shell \'pkill -f "# nsload"; pkill -f "# nsio"; rm -f /sdcard/Download/ns_io_*.tmp\'',
                           shell=True, capture_output=True, timeout=30)   # load a cancelled run could not stop
        try:
            self.handle(snap)
        finally:
            if action in ('reproduce', 'draft-fix'):
                config.LAB = config.REPO              # the lab folder is this job's only
            self.flush_log(snap.reference)            # the last buffered log lines reach the board

    def heartbeat(self):
        """workers/<owner>: this person's worker is alive (the board shows "no worker online" without it)."""
        o = _owner(getattr(self, 'cfg', None))
        if not o:
            return
        try:
            from google.cloud import firestore as gcf
            self.db.collection('workers').document(o).set({
                'owner': o, 'host': os.uname().nodename, 'lastSeen': gcf.SERVER_TIMESTAMP,
                'phone': os.environ.get('ANDROID_SERIAL') or str(((self.cfg.get('lab') or {}).get('phone_serial')) or ''),
                'servesOthers': bool((self.cfg.get('worker') or {}).get('serve_others'))}, merge=True)
        except Exception:
            pass

    def _alive(self, email):
        try:
            d = self.db.collection('workers').document(email).get().to_dict() or {}
            t = d.get('lastSeen')
            return bool(t) and (dt.datetime.now(dt.timezone.utc) - t).total_seconds() < WORKER_ALIVE_S
        except Exception:
            return False

    def route(self, job):
        """Should THIS worker take the job? Mine; shared board work (anyone); or a colleague's job when this worker
        serves others and their own worker is not online. The claim transaction still guarantees one runner."""
        me = _owner(self.cfg)
        if not me:
            return True                                     # single-worker setup: run everything (as before)
        who = str(job.get('requestedBy') or '').strip().lower()
        serve = bool((self.cfg.get('worker') or {}).get('serve_others'))
        if who == me:
            return True
        if '@' not in who:                                  # scheduled ('daily 08:00', 'nightly golden check'): the host
            if serve:                                       # runs it; if the host is off, any worker after 15 min (not phone work)
                return True
            try:
                q = job.get('queuedAt')
                return job.get('action') not in PHONE_ACTIONS and q is not None and (dt.datetime.now(dt.timezone.utc) - q).total_seconds() > 900
            except Exception:
                return False
        if job.get('action') in SHARED_ACTIONS:
            return True
        if not serve or self._alive(who):
            return False
        try:                                                # give their own worker 90 s to wake up and claim it first
            q = job.get('queuedAt')
            return q is None or (dt.datetime.now(dt.timezone.utc) - q).total_seconds() > 90
        except Exception:
            return True

    def handle(self, snap):
        job = snap.to_dict()
        ref = snap.reference
        try:                                        # the worker is long-running: model-call code (blind sandbox) stays current
            import importlib
            from . import llm as _llm
            importlib.reload(_llm)
        except Exception:
            pass
        with self.busy:
            # atomic claim: a Firestore transaction moves queued -> running, so even two worker processes
            # (or two windows) can never run the same job, and a lab job never overlaps another lab job
            from google.cloud import firestore as gcf
            me = f'{os.uname().nodename}:{os.getpid()}'
            @gcf.transactional
            def claim(tx):
                snap = ref.get(transaction=tx)
                d = snap.to_dict() or {}
                if d.get('status') != 'queued':
                    return False
                lab = self.db.collection('config').document(_lab_lock_id(self.cfg))
                lk = (lab.get(transaction=tx).to_dict() or {})
                if job.get('action') in ('reproduce', 'draft-fix') and lk.get('holder') and lk.get('holder') != me:
                    return False                      # another worker is using the phone; leave the job queued
                tx.update(ref, {'status': 'running', 'claimedAt': _now(), 'startedAt': _now(), 'worker': me, 'workerOwner': _owner(self.cfg), 'log': []})
                if job.get('action') in ('reproduce', 'draft-fix'):
                    tx.set(lab, {'holder': me, 'job': ref.id, 'since': _now()})
                return True
            if not claim(self.db.transaction()):
                return
            if job.get('action') in ('reproduce', 'draft-fix'):    # we hold the phone: any other lab job of this worker
                try:                                               # still 'running'/'cancel' lost its thread; close it
                    for st in ('running', 'cancel'):
                        for d in self.db.collection('jobs').where('status', '==', st).stream():
                            x = d.to_dict() or {}
                            if d.id != ref.id and x.get('worker') == me and x.get('action') in ('reproduce', 'draft-fix'):
                                d.reference.update({'status': 'cancelled' if st == 'cancel' else 'failed', 'finishedAt': _now(),
                                                    'error': 'job thread stopped (closed by the next lab job)'})
                except Exception as e:
                    print(f'[worker] could not close stale lab jobs: {e}', flush=True)
            self._watch_cancel(ref)
            self._pin_phone()                         # every adb call of this job goes to the physical lab phone
            if job.get('action') == 'card-read':         # Card Issue: read a Jira card, watch its video frame by frame, write steps
                parts = str(job.get('issue') or '').split('|', 2)     # KEY | branch | note  (old form: KEY | note)
                key = parts[0].strip().upper()
                branch, note = (parts[1].strip(), parts[2]) if len(parts) == 3 else ('', parts[1] if len(parts) == 2 else '')
                if branch and not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', branch):
                    branch = ''
                nf = ''
                if note.strip():                          # the developer's note goes to the reader as a file (no shell quoting)
                    nf = os.path.join(config.REPO, 'tools/nightshift/out/cards', key, 'note.txt')
                    os.makedirs(os.path.dirname(nf), exist_ok=True)
                    open(nf, 'w').write(note.strip()[:1500])
                if not re.fullmatch(r'[A-Z][A-Z0-9]{1,9}-[0-9]{1,7}', key):
                    self.log(ref, f'ERROR card issue: bad card key {key!r}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': 'bad card key'})
                    return
                self.log(ref, f'Card Issue: reading {key}' + (' (with a developer note)' if nf else '') + (f' · root cause in {branch}' if branch else ''))
                try:
                    rc = self.run_cmd(ref, f'{PY} tools/nightshift/cards/cardread.py --id {ref.id} --card {key} --by "{job.get("requestedBy", "")}"' + (f' --note-file "{nf}"' if nf else '') + (f' --branch "{branch}"' if branch else ''), 5400)
                    try:
                        self.maybe_deploy(ref)            # the frames live under board/public/v/<token>/
                    except Exception as e:
                        self.log(ref, f'board deploy skipped: {str(e)[:200]}')
                    ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else ('done' if rc == 0 else 'failed'), 'finishedAt': _now()})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                return
            if job.get('action') == 'symbols-rebuild':   # file:line for a new release: rebuild its native lib from its commit, keep it only if identical
                vcs = str(job.get('issue') or '')
                if not re.fullmatch(r'\d{6,12}(,\d{6,12}){0,5}', vcs):
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': 'bad version code list'})
                    return
                self.log(ref, f'Symbols: rebuilding the release native library of {vcs} for file:line (no AI, nothing installed or uploaded)')
                try:
                    rc = self.run_cmd(ref, f'{PY} tools/nightshift/symbols_rebuild.py --id {ref.id} --vc {vcs}', 3 * 3600)
                    ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else ('done' if rc == 0 else 'failed'), 'finishedAt': _now()})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                return
            if job.get('action') == 'audio-check':       # Audio Check: build a branch with the mixer tap, export on the phone, run the rig
                parts = str(job.get('issue') or '').split(';')
                br, proj, base, dev = (parts + ['', '', '', ''])[:4]
                if dev and not re.fullmatch(r'emulator-\d{4}|[A-Za-z0-9]{6,32}', dev):
                    dev = ''
                if not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', br) or proj not in ('splits',) or (base and not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', base)):
                    self.log(ref, f'ERROR audio check: bad request {job.get("issue")!r} (only the Plain splits project is connected so far)')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': 'bad audio check request'})
                    return
                self.log(ref, f'Audio Check: {br} · {proj}' + (f' · control {base}' if base else ''))
                try:
                    rc = self.run_cmd(ref, f'{PY} tools/nightshift/audio/audiocheck.py --id {ref.id} --branch "{br}" --project {proj}'
                                           + (f' --base "{base}"' if base else '') + (f' --device {dev}' if dev else '')
                                           + f' --by "{job.get("requestedBy", "")}"', 4 * 3600)
                    try:
                        self.maybe_deploy(ref)            # the graphs live under board/public/v/<token>/
                    except Exception as e:
                        self.log(ref, f'board deploy skipped: {str(e)[:200]}')
                    ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else ('done' if rc == 0 else 'failed'), 'finishedAt': _now()})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                return
            if job.get('action') == 'audio-branches':    # Audio Check: list the latest Bitbucket branches for the picker
                try:
                    self.maybe_deploy(ref)
                except Exception as e:
                    self.log(ref, f'board deploy skipped: {str(e)[:200]}')
                try:
                    import importlib
                    from . import bitbucket
                    importlib.reload(bitbucket)
                    qy = str(job.get('issue') or '').strip()
                    br = bitbucket.branches(40, qy or None)
                    self.db.collection('config').document('audiobranches').set({'branches': br, 'fetchedAt': _now(), 'query': qy})
                    self.log(ref, f'Audio Check: fetched {len(br)} branches from Bitbucket' + (f' matching "{qy}"' if qy else ''))
                    ref.update({'status': 'done', 'finishedAt': _now()})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                return
            if job.get('action') == 'pr-review':         # tool 1: review open Bitbucket PRs (no phone)
                try:
                    self.maybe_deploy(ref)            # board page changed on disk -> publish it first
                except Exception as e:
                    self.log(ref, f'board deploy skipped: {str(e)[:200]}')
                try:
                    import importlib
                    from . import prreview, bitbucket
                    importlib.reload(bitbucket)
                    importlib.reload(prreview)
                    self.log(ref, 'PR review: open Bitbucket PRs, read-only (classify, then Anthropic pr-review-toolkit + 5 nightshift-review skills with Opus, in parallel)')
                    done = prreview.run(self.db, self.cfg, log=lambda l: self.log(ref, l), only=job.get('issue') or None,
                                        stop=lambda: getattr(self, 'cancelled', False))
                    ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else 'done', 'finishedAt': _now()})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                return
            if job.get('action') in ('sync', 'sync-full'):   # no case: gather the issue lists for the whole app
                try:
                    self.maybe_deploy(ref)                # board page changed on disk -> publish it first
                except Exception as e:
                    self.log(ref, f'board deploy skipped: {e}')
                try:
                    from . import sync
                    full = job.get('action') == 'sync-full' or str((self.cfg.get('sources') or {}).get('sync_root_causes', 'false')).lower() in ('true', 'yes', '1')
                    if full:
                        self.log(ref, 'FULL sync: gather, then a root cause for every new or changed problem (no repros)')
                    else:
                        self.log(ref, 'gather only (no root causes, no repros): open a crash and press Analyse or Reproduce for those')
                    st = sync.run(self.db, self.cfg, log=lambda l: self.log(ref, l), analyse=full,
                                  stop=lambda: getattr(self, 'cancelled', False))
                    bad = [k for k in ('crashlytics', 'play') if isinstance(st.get(k), dict) and not st[k].get('ok')]
                    ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else 'failed' if len(bad) == 2 else 'done',
                                'finishedAt': _now(),
                                **({'error': '; '.join(f'{k}: {st[k]["error"]}' for k in bad)[:500]} if bad else {})})
                except Exception as e:
                    self.log(ref, f'ERROR {e}')
                    ref.update({'status': 'failed', 'finishedAt': _now(), 'error': str(e)[:500]})
                if str(job.get('requestedBy', '')).startswith('daily'):
                    try:                                  # Audio Check step 7: a golden check of today's code every day
                        gb = str((self.cfg.get('audio') or {}).get('golden_branch') or (self.cfg.get('lab') or {}).get('base_branch') or 'CPP-1.25.2')
                        from firebase_admin import firestore as _fs
                        self.db.collection('jobs').add({'action': 'audio-check', 'issue': f'{gb};splits;', 'requestedBy': 'nightly golden check',
                                                        'status': 'queued', 'queuedAt': _fs.SERVER_TIMESTAMP})
                        self.log(ref, f'queued the daily golden Audio Check of {gb} (the lab drift check)')
                    except Exception as e:
                        self.log(ref, f'golden Audio Check not queued: {str(e)[:200]}')
                return
            try:
                case_ref = self.db.collection('cases').document(job['issue'])
                case = case_ref.get().to_dict()
                self._case_kind = str((case or {}).get('kind') or '').upper()   # ANR cases get the lab boost's CPU load
                if not case and job['action'] in ('pull', 'start'):
                    case_ref.set({'id': job['issue'], 'status': 'pulling', 'verdict': 'pending', 'kind': '?', 'title': 'pulling from Crashlytics…'})
                    case = {'id': job['issue']}
                if not case:
                    raise RuntimeError(f'unknown case {job["issue"]}')
                case['id'] = job['issue']
                self._card_under_test = job['issue']      # a lab crash of ANOTHER card is named as that card's bug
                self._field_short = None                  # field top-frame libs + fault, for dumps the phone cuts short
                try:                                      # from the case: the sample event's fault + its top 2 frames' libraries
                    import glob as _gl, json as _js
                    cf = next(iter(_gl.glob(os.path.join(config.REPO, 'tools/nightshift/out', f'*_{job["issue"]}_case_file.json'))), None)
                    cj = _js.load(open(cf)) if cf else {}
                    m_ = re.search(r'SIG\w+\s+0x([0-9a-fA-F]+)', (cj.get('sample_event') or {}).get('subtitle') or '')
                    lb = [f.get('lib') or '' for f in (cj.get('frames') or [])[:2]]
                    if m_ and len(lb) == 2 and 'libMYJNILIB26.so' not in lb and all(lb):
                        self._field_short = {'fault': int(m_.group(1), 16), 'libs': lb}
                except Exception:
                    self._field_short = None
                self._family = []                         # confirmed same-bug family: a crash of ANY member is the field crash
                try:
                    from . import bugfamily as _bf, author as _au
                    if job['action'] in ('analyse', 'reproduce', 'draft-fix', 'verify-fix', 'start'):
                        _bf.scan_card(job['issue'], log=lambda t: self.log(ref, t))
                    def _exp(c):
                        ss = _bf.card_signatures(c)
                        return _au.expect_frames({'frames': [{'func': f['func'], 'lib': f['lib']} for f in ss[0]['frames']]}) if ss else []
                    self._family = _bf.expect_sets(job['issue'], _exp)
                    for c_, t_, ex_ in self._family:
                        self.log(ref, f'same-bug family (confirmed): a lab crash of {t_} ({", ".join(ex_)}) also counts as this crash')
                    if self._family:                      # the board's case brief links the other members
                        case_ref.set({'family': [{'card': c_, 'title': t_} for c_, t_, _ in self._family]}, merge=True)
                except Exception as e_:
                    self.log(ref, f'same-bug family: not loaded ({e_})')
                    self._family = []
                case_ref.update({'status': f'{job["action"]}-running'})
                self._case_ref, self._job_action = case_ref, job['action']
                if job['action'] in ('reproduce', 'draft-fix'):
                    # crash builds happen in the lab folder, never in the working copy (Android Studio stays free)
                    import importlib
                    from . import labtree
                    importlib.reload(labtree)
                    base = job.get('base') if re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', str(job.get('base') or '')) else None
                    lw, ls = labtree.activate(self.cfg, base, log=lambda l: self.log(ref, l))
                    if ls:
                        self.log(ref, f'lab folder: {lw} = {base or self.cfg["lab"].get("base_branch")} @ {ls[:10]} '
                                      f'(your working copy and Android Studio are not touched)')
                self._blind = bool(job.get('blind'))
                self._blind_fix = False
                self._lab_steps = 0
                self._labtask_only = False
                self._budget = job.get('budget_min')
                flag = os.path.join(config.REPO, 'tools/nightshift/out', f'blind_{job["issue"]}.json')
                fflag = os.path.join(config.REPO, 'tools/nightshift/out', f'blind_fix_{job["issue"]}.json')
                if job['action'] == 'draft-fix' and os.path.exists(fflag):    # blind fix-only run (engineer's flag file)
                    os.rename(fflag, fflag + '.used')
                    self._blind = True
                    self.log(ref, 'BLIND fix test for this crash (flag file): proposer and reviewer get the read block; '
                                  'the repro is the one Night Shift wrote blind')
                if job['action'] == 'reproduce' and os.path.exists(flag):   # set up by an engineer for a fair test
                    import json
                    fl = json.load(open(flag))
                    os.rename(flag, flag + '.used')
                    if fl.get('rehide') and re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', job['issue']):   # a split card too
                        # start from zero again: set aside what earlier blind runs of this crash left (blindreset rehide)
                        self.run_cmd(ref, f'{PY} tools/nightshift/blindreset.py rehide {job["issue"]}', 600)
                        case = {**(case_ref.get().to_dict() or {}), 'id': job['issue']}
                    self._blind, self._budget = True, fl.get('budget_min')
                    self._level_min = fl.get('level_min')
                    self._blind_fix = bool(fl.get('fix'))
                    if self._blind_fix:
                        self.log(ref, 'blind test continues after a repro: propose a fix, verify it on the phone (trigger reached, no crash), review')
                    self.log(ref, 'BLIND repro test for this crash (flag file): ' + ('fresh root cause first, then ' if fl.get('analyse_first', True) else '')
                             + 'the repro author alone')
                    if fl.get('analyse_first', True):
                        # 100% blind root cause: the model may not read .git (later fix commits), lab notes or old results,
                        # and it reads the crash files as SHIPPED (swapped in for the analysis, restored right after)
                        self._blind_deny = BLIND_READ_DENY
                        self._restore_swaps(ref)
                        swaps = self._shipped_swap(ref, case) if (self.cfg.get('lab') or {}).get('build_as_shipped', True) else []
                        self._swaps = list(swaps)        # the prebuild can heal an old/new mix that does not compile too
                        lab_mode = config.LAB != config.REPO
                        if lab_mode and job['action'] == 'reproduce' and self._turbo().get('prebuild', True):
                            # SPEED: the crash build needs only the field files, not the root cause: build + install in
                            # the lab folder WHILE Claude writes the root cause (the phone is idle then)
                            import threading as _th
                            def _pre():
                                try:
                                    # gRPC (Firestore) breaks when a subprocess is forked during its calls ("skipping fork()
                                    # handlers" -> TSI_DATA_CORRUPTED): let the analysis finish its Firestore reads first
                                    time.sleep(20)
                                    self._install(ref, [])
                                    self.log(ref, 'prebuild: crash build installed while the root cause was being written')
                                except Exception as e:
                                    self.log(ref, f'prebuild failed ({str(e)[:120]}); the normal build runs after the root cause')
                            self._prebuild_th = _th.Thread(target=_pre, daemon=True)
                            self._prebuild_th.start()
                        try:
                            try:
                                self.do_analyse(ref, case)
                            except Exception as e:      # a gRPC glitch (fork during a Firestore call): once more
                                if not any(k in str(e) for k in ('_retry', 'TSI_', 'SSL', 'Deadline', 'UNAVAILABLE')):
                                    raise
                                self.log(ref, f'analysis: Firestore connection glitch ({str(e)[:80]}); trying once more')
                                time.sleep(5)
                                self.do_analyse(ref, case)
                        finally:
                            for p, b in ([] if lab_mode else swaps):     # lab folder: the build uses these same files
                                open(p, 'wb').write(open(b, 'rb').read())
                            if swaps:
                                bdir = os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', case['id'])
                                if os.path.exists(os.path.join(bdir, 'swapped.json')):
                                    os.rename(os.path.join(bdir, 'swapped.json'), os.path.join(bdir, 'swapped.json.restored'))
                            self._blind_deny = None
                        self.log(ref, 'blind root cause written with the read block (.git, lab notes, old results) and the shipped crash files')
                        case = {**case, **(case_ref.get().to_dict() or {}), 'id': job['issue']}
                {'start': self.do_start, 'analyse': self.do_analyse, 'triage': self.do_triage, 'reproduce': self.do_reproduce, 'draft-fix': self.do_draft_fix, 'pull': self.do_pull}[job['action']](ref, case)
                if job['action'] in ('reproduce', 'draft-fix') and not getattr(self, '_labtask_only', False) \
                        and not getattr(self, '_lab_steps', 0):
                    self.log(ref, 'lab update skipped: nothing ran on the phone in this job, so the root cause stays as it was')
                elif job['action'] in ('reproduce', 'draft-fix') and not getattr(self, '_labtask_only', False):
                    try:                                  # the board must never show a root cause older than the lab
                        import importlib
                        from . import labupdate
                        importlib.reload(labupdate)
                        if getattr(self, '_blind', False):  # blind: same read block + the shipped crash files as the analysis
                            self.log(ref, 'lab update (blind): read block on, shipped crash files swapped in, no git')
                            self._restore_swaps(ref)
                            swaps = self._shipped_swap(ref, case) if (self.cfg.get('lab') or {}).get('build_as_shipped', True) else []
                            try:
                                labupdate.run(self.db, self.cfg, job['issue'], log=lambda l: self.log(ref, l), deny=BLIND_READ_DENY)
                            finally:
                                for p, b in swaps:
                                    open(p, 'wb').write(open(b, 'rb').read())
                                bdir = os.path.join(config.REPO, 'tools/nightshift/out', 'labbuild_backup', case['id'])
                                if swaps and os.path.exists(os.path.join(bdir, 'swapped.json')):
                                    os.rename(os.path.join(bdir, 'swapped.json'), os.path.join(bdir, 'swapped.json.restored'))
                        else:
                            labupdate.run(self.db, self.cfg, job['issue'], log=lambda l: self.log(ref, l))
                    except Exception as e:
                        self.log(ref, f'lab update skipped: {str(e)[:200]}')
                if job['action'] in ('reproduce', 'draft-fix') and getattr(self, '_lab_steps', 0) \
                        and not getattr(self, '_labtask_only', False):
                    self._retro(ref, job, case)
                self.republish(ref)
                try:
                    self.maybe_deploy(ref)                # board page edited since the last deploy -> publish it now
                except Exception as e:
                    self.log(ref, f'board deploy skipped: {str(e)[:200]}')
                ref.update({'status': 'done', 'finishedAt': _now()})
                self._end_progress('finished')
                self._release_lab(job)
            except Exception as e:  # the job fails visibly; the worker keeps running
                self.log(ref, 'CANCELLED from the board' if getattr(self, 'cancelled', False) else f'ERROR {e}')
                ref.update({'status': 'cancelled' if getattr(self, 'cancelled', False) else 'failed',
                            'finishedAt': _now(), 'error': str(e)[:500]})
                self._end_progress('cancelled' if getattr(self, 'cancelled', False) else f'stopped: {str(e)[:150]}')
                self._release_lab(job)
                try:
                    self.db.collection('cases').document(job['issue']).update({'status': 'triaged'})
                except Exception:
                    pass

    def maybe_deploy(self, ref):
        """Republish the case board (nightshift-myzesty hosting only) when board/index.html is newer than what was deployed."""
        if ((self.cfg.get('worker') or {}).get('deploy_board', True)) is False:
            return                                      # shared board: only the board host publishes (a deploy replaces the whole site)
        b = os.path.join(config.REPO, 'tools/nightshift/board')
        src, mark = os.path.join(b, 'index.html'), os.path.join(b, 'public', '.deployed')
        rules = os.path.join(b, 'firestore.rules')
        vids = [os.path.getmtime(p) for p in glob.glob(os.path.join(b, 'public', 'v', '*', '*'))]
        prp = os.path.join(b, 'pr.html')
        pages = [os.path.getmtime(os.path.join(b, f)) for f in ('card.html', 'audio.html') if os.path.exists(os.path.join(b, f))]
        newest = max([os.path.getmtime(src), os.path.getmtime(rules) if os.path.exists(rules) else 0,
                      os.path.getmtime(prp) if os.path.exists(prp) else 0] + vids + pages)
        if os.path.exists(mark) and os.path.getmtime(mark) >= newest:
            return                                # this version of the page is already live
        self.log(ref, f'board page changed: rebuilding and deploying hosting ({(self.cfg.get("firebase") or {}).get("projectId")})')
        if self.run_cmd(ref, f'{PY} tools/nightshift/sentinel.py board --live', 300):
            raise RuntimeError('board build failed')
        import shutil
        home = os.path.expanduser('~')
        fb = shutil.which('firebase') or next((c for c in ['/opt/homebrew/bin/firebase', '/usr/local/bin/firebase', f'{home}/.npm-global/bin/firebase']
                                               + sorted(glob.glob(f'{home}/.nvm/versions/node/*/bin/firebase'), reverse=True)
                                               + glob.glob(f'{home}/.volta/bin/firebase') if os.path.exists(c)), None)
        if not fb:
            raise RuntimeError('firebase CLI not found for the worker')
        nodebin = os.path.dirname(os.path.realpath(fb))
        res = subprocess.run(f'cd tools/nightshift/board && PATH="{os.path.dirname(fb)}:{nodebin}:$PATH" "{fb}" deploy --only hosting,firestore:rules --project {(self.cfg.get("firebase") or {}).get("projectId") or "nightshift-myzesty"} --non-interactive',
                             shell=True, cwd=config.REPO, capture_output=True, text=True, timeout=600)
        tail = (res.stdout + res.stderr).strip().splitlines()[-6:]
        for l in tail:
            self.log(ref, '  ' + l[:200])
        if res.returncode:
            raise RuntimeError('firebase deploy failed')
        open(mark, 'w').write(_now())

    def cleanup_stale(self):
        """A worker that was stopped mid-job leaves that job 'running' and may hold the phone lock. On start,
        fail those jobs (same Mac, other process) and free the lock, so new jobs are not blocked."""
        host = os.uname().nodename
        me = f'{host}:{os.getpid()}'
        try:
            stale = list(self.db.collection('jobs').where('status', '==', 'running').stream()) + \
                    list(self.db.collection('jobs').where('status', '==', 'cancel').stream())
            for d in stale:
                w = (d.to_dict() or {}).get('worker', '')
                if w.startswith(host + ':') and w != me:
                    was_cancel = (d.to_dict() or {}).get('status') == 'cancel'
                    d.reference.update({'status': 'cancelled' if was_cancel else 'failed', 'finishedAt': _now(),
                                        'error': 'cancelled from the board' if was_cancel else 'worker was restarted while this job ran'})
                    iss = (d.to_dict() or {}).get('issue')
                    if iss:
                        c = self.db.collection('cases').document(iss)
                        if str((c.get().to_dict() or {}).get('status', '')).endswith('-running'):
                            c.update({'status': 'triaged'})
                    print(f'[worker] marked stale job {d.id} failed', flush=True)
            lab = self.db.collection('config').document(_lab_lock_id(self.cfg))
            h = (lab.get().to_dict() or {}).get('holder', '')
            if h.startswith(host + ':') and h != me:
                lab.delete()
                print('[worker] freed a stale phone lock', flush=True)
        except Exception as e:
            print(f'[worker] stale cleanup failed: {e}', flush=True)

    def daily_sync(self):
        """Queue one 'sync' job per day at 08:00 Egypt time (or as soon as the Mac is awake after that)."""
        now = cairo_now()
        hh, mm = [int(x) for x in str(self.cfg.get('sources', {}).get('sync_time', '08:00')).split(':')]
        if (now.hour, now.minute) < (hh, mm):
            return
        day = now.strftime('%Y-%m-%d')
        from google.cloud import firestore as gcf
        from firebase_admin import firestore
        sched = self.db.collection('config').document('sync_schedule')
        job = self.db.collection('jobs').document()

        @gcf.transactional
        def book(tx):
            if (sched.get(transaction=tx).to_dict() or {}).get('day') == day:
                return False
            tx.set(sched, {'day': day, 'job': job.id, 'at': _now()})
            tx.set(job, {'action': 'sync', 'issue': '', 'requestedBy': 'daily 08:00 (Egypt)', 'status': 'queued',
                         'queuedAt': firestore.SERVER_TIMESTAMP})
            return True
        if book(self.db.transaction()):
            print(f'[worker] queued the daily sync for {day}', flush=True)

    def serve(self):
        q = self.db.collection('jobs').where('status', '==', 'queued')

        def dispatch(doc):
            # reload the pipeline code for every job, so code changes apply without restarting the worker
            import importlib
            import ns.case, ns.crashlytics, ns.locate, ns.match, ns.fix, ns.llm, ns.symbolize, ns.board, ns.fire, ns.sync, ns.merge, ns.worker
            import ns.timeline, ns.threads, ns.source, ns.review, ns.analyse, ns.groups, ns.bugfamily
            for m in (ns.groups, ns.bugfamily, ns.crashlytics, ns.source, ns.locate, ns.match, ns.llm, ns.symbolize, ns.timeline, ns.threads, ns.review,
                      ns.fix, ns.case, ns.fire, ns.board, ns.analyse, ns.sync, ns.merge, ns.worker):
                importlib.reload(m)
            cfg = config.load()
            ns.worker.Worker(self.db, cfg, dry=self.dry).handle_locked(doc, self.busy)

        seen = {}                                     # job id -> when this process last dispatched it

        def fire(doc):
            seen[doc.id] = time.time()
            threading.Thread(target=dispatch, args=(doc,), daemon=True).start()

        def on_snapshot(col_snapshot, changes, read_time):
            for ch in changes:
                if ch.type.name in ('ADDED', 'MODIFIED'):
                    fire(ch.document)
        self.cleanup_stale()
        watch = q.on_snapshot(on_snapshot)
        print(f'worker {os.uname().nodename} listening for jobs (dry={self.dry}); Ctrl-C to stop', flush=True)
        last_poll = time.time()
        while True:
            time.sleep(30)
            try:                                       # "my worker is online" for the shared board (every 30 s, idle too)
                sys.modules['ns.worker'].Worker.heartbeat(self)          # the newest code, even in an old process
            except Exception:
                pass
            # Safety net (2026-10-12: a Firestore quota error silently ended the live listener and queued jobs sat
            # for hours): every 60 s also look for queued jobs; re-subscribe when the listener has died.
            if time.time() - last_poll < 60:
                continue
            last_poll = time.time()
            try:
                if getattr(watch, '_closed', False) or not getattr(watch, 'is_active', True):
                    print('[worker] job listener ended; subscribing again', flush=True)
                    watch = q.on_snapshot(on_snapshot)
                for d in q.stream():
                    if time.time() - seen.get(d.id, 0) > 600:      # not dispatched by this process in the last 10 min
                        print(f'[worker] poll found queued job {d.id[:8]} the listener missed', flush=True)
                        fire(d)
            except Exception as e:
                print(f'[worker] poll for queued jobs failed: {str(e)[:150]}', flush=True)
            try:
                self.daily_sync()
            except Exception as e:
                print(f'[worker] daily sync scheduling failed: {e}', flush=True)
            try:                                   # pick up jobs that waited for the phone lock
                for doc in q.get():
                    threading.Thread(target=dispatch, args=(doc,), daemon=True).start()
            except Exception as e:
                print(f'[worker] rescan failed: {e}', flush=True)
