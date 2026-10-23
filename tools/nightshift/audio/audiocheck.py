#!/usr/bin/env python3
"""Night Shift tool 2, Audio Check: build a branch with the mixer tap, export a fixed test project on the lab phone,
run the PR #3132 audio rig (rig/*.py, unchanged) on the mixer dump, and publish the verdict + graphs to the board
(Firestore audiochecks/<id>, graphs under board/public/v/<token>/). Optional control branch: the same, for comparison.

Generic for any branch: the branch's OWN change (its diff from the fork point, or the merge that brought it in) is
built on today's lab code, and the control is the same code without it. Never touches the working copy: builds run in
a worktree under ~/.nightshift_audio/ (lab commit + the lab's submodule checkouts). Nothing is committed, pushed or
posted to Bitbucket.

usage: audiocheck.py --id <job id> --branch <name> --project splits [--base <name>] [--by <email>]"""
import argparse, glob, json, os, re, secrets, shutil, subprocess, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NS = os.path.dirname(HERE)
sys.path.insert(0, NS)
from ns import config, fire                      # noqa: E402
sys.path.insert(0, HERE)
import tap                                        # noqa: E402

REPO = config.REPO
WT_ROOT = os.path.expanduser('~/.nightshift_audio')
OUT = os.path.join(NS, 'out', 'audio')
APKS = os.path.join(OUT, 'apk')
ASSETS = os.path.join(OUT, 'assets')


def ensure_assets():
    """A new install (kit) has the test clip in audio/assets only: copy it to out/audio/assets and decode the reference
    sound from it (bit-identical to the original ref: plain ffmpeg decode, f32le 44.1 kHz stereo)."""
    os.makedirs(ASSETS, exist_ok=True)
    src_dir = os.path.join(HERE, 'assets')
    for p in PROJECTS.values():
        clip, ref = os.path.join(ASSETS, p['clip']), os.path.join(ASSETS, p['ref'])
        if not os.path.exists(clip) and os.path.exists(os.path.join(src_dir, p['clip'])):
            shutil.copy2(os.path.join(src_dir, p['clip']), clip)
        if not os.path.exists(ref) and os.path.exists(clip):
            ff = shutil.which('ffmpeg') or next((c for c in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(c)), None)
            if ff:
                subprocess.run([ff, '-y', '-loglevel', 'error', '-i', clip, '-vn', '-f', 'f32le', '-ar', '44100', '-ac', '2', ref], timeout=300)
PUBLIC_V = os.path.join(NS, 'board', 'public', 'v')
SUBMODULES = ['extra/oboe', 'extra/opencv', 'overlay_collage']
APK_REL = 'app/build/outputs/apk/productionInternal/debug/app-productionInternal-debug.apk'
GRADLE = './gradlew assembleProductionInternalDebug -Pandroid.injected.build.abi=arm64-v8a'
PROJECTS = {
    'splits': {'label': 'Plain splits', 'scenario': 'audio_plain_splits', 'clip': 'ns_audio_splits.mp4',
               'ref': 'ns_audio_splits_ref.f32', 'cuts': 6},
}
EXPORTS = 3                                       # exports per build (median); NS_AUDIO_EXPORTS overrides
STEPS = ['Get the branch', 'Build the app', 'Export on the phone', 'Analyse the audio', 'Show the result']
PHONE_DIR = '/sdcard/DCIM/NightShift'
DUMP = 'files/aud_dump_mix.f32'
PKG = config.app_package()                        # the app under test (profile in nightshift.yaml)
try:                                               # how the sound is captured: 'tap' = the mixer tap patched into the
    _AC = config.load().get('audio_check') or {}   # engine (MyZesty, exact); 'export_file' = the exported video pulled
except Exception:                                  # from the phone and decoded (any app, no code hook, AAC: coarser)
    _AC = {}
CAPTURE = (os.environ.get('NS_AUDIO_CAPTURE') or str(_AC.get('capture') or 'tap')).strip()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


_GRPC_NOISE = re.compile(r'^[IWE]\d{4} \d\d:\d\d:\d\d\.\d+\s+\d+ \w+\.cc:\d+\]')


def sh(cmd, cwd=REPO, timeout=600, check=True, quiet=False):
    if not quiet:
        print(f'$ {cmd}', flush=True)
    p = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    t0 = time.time()
    for line in p.stdout:
        if _GRPC_NOISE.match(line):                    # gRPC (Firestore) fork warnings land in every child's output
            continue
        out.append(line)
        if not quiet:
            print('  ' + line.rstrip()[:300], flush=True)
        if time.time() - t0 > timeout:
            p.kill()
            raise RuntimeError(f'timed out after {timeout}s: {cmd[:120]}')
    rc = p.wait()
    if check and rc:
        tail = ''.join(out[-8:]).strip()
        raise RuntimeError(f'exit {rc}: {cmd[:120]}\n{tail[-600:]}')
    return ''.join(out)


class Check:
    def __init__(self, a):
        self.a, self.db = a, fire.client()
        self.ref = self.db.collection('audiochecks').document(a.id)
        self.steps = [{'name': n, 'state': 'wait', 'note': ''} for n in STEPS]
        self.doc = {'id': a.id, 'branch': a.branch, 'base': a.base or '', 'project': a.project, 'device': getattr(a, 'device', '') or 'lab phone',
                    'projectLabel': PROJECTS[a.project]['label'], 'requestedBy': a.by or '', 'status': 'running',
                    'startedAt': now(), 'steps': self.steps, 'runs': {}}
        self.save()

    def save(self):
        self.ref.set(self.doc)

    def step(self, i, state, note=''):
        self.steps[i]['state'], self.steps[i]['note'] = state, note
        if state == 'run':
            self.steps[i]['startedAt'] = now()
        if state in ('done', 'failed'):
            self.steps[i]['finishedAt'] = now()
        print(f'▶ {STEPS[i]}: {state}{" - " + note if note else ""}', flush=True)
        self.save()

    # ── 1 · the branch's own change, on today's lab code ──
    # Generic for any branch, old or new: the app is built from TODAY'S lab code (the commit and the submodule checkouts
    # the lab working copy builds with), once WITH the branch's own change and once WITHOUT it. The change is the
    # branch's diff from where it forked (or, if it is already merged, the merge that brought it in). So a check never
    # depends on stale submodule pins or on which Java modules matched an old commit, and control = "same code, no change".
    ENGINE_DIR = 'app/src/main/cpp/audio'

    def resolve(self, spec):
        """-> (sha, kind): 'before-pr-3132' = the code just before that PR was merged; a commit hash; else a branch."""
        m = re.fullmatch(r'before-pr-(\d+)', spec)
        if m:
            sh('git fetch --no-tags origin', timeout=900, check=False, quiet=True)
            hit = sh(f'git log --all --format=%H -1 --grep="(pull request #{m.group(1)})"', quiet=True).strip()
            if not hit:
                raise RuntimeError(f'no merge of pull request #{m.group(1)} found in git')
            return sh(f'git rev-parse {hit}^1', quiet=True).strip(), f'the code just before PR #{m.group(1)} was merged ({hit[:10]})'
        if re.fullmatch(r'[0-9a-f]{7,40}', spec) and subprocess.run(['git', 'cat-file', '-e', f'{spec}^{{commit}}'], cwd=REPO).returncode == 0:
            return sh(f'git rev-parse {spec}', quiet=True).strip(), f'commit {spec[:10]}'
        return self.fetch(spec), ''

    NATIVE_SUBS = ['overlay_collage']                   # native code outside app/src/main/cpp that calls into the engine

    def sub_pins(self, wt, ref):
        """Move the native submodules of the worktree to the versions `ref` pins (an old engine with today's overlay
        library fails to link: VideoEngine::detach_media ... undefined). Returns what moved."""
        moved = []
        for ln in sh(f'git ls-tree {ref} -- ' + ' '.join(self.NATIVE_SUBS), quiet=True).splitlines():
            m = re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', ln)
            if not m:
                continue
            pin, sm = m.groups()
            d, src = os.path.join(wt, sm), os.path.join(REPO, sm)
            if not os.path.isdir(d) or os.path.islink(d):
                continue
            if subprocess.run(['git', '-C', src, 'cat-file', '-e', f'{pin}^{{commit}}'], capture_output=True).returncode != 0:
                sh(f'git -C "{src}" fetch --no-tags origin {pin}', timeout=900, check=False, quiet=True)
            if sh(f'git -C "{d}" rev-parse HEAD', quiet=True, check=False).strip() != pin:
                sh(f'git -C "{d}" checkout -q --detach --force {pin}', timeout=600)
                moved.append(f'{sm}@{pin[:8]}')
        return moved

    def sub_restore(self, wt, h0):
        """Native submodules back to the lab's own versions (see sub_pins)."""
        for ln in sh(f'git ls-tree {h0} -- ' + ' '.join(self.NATIVE_SUBS), quiet=True, check=False).splitlines():
            m = re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', ln)
            d = os.path.join(wt, m.group(2)) if m else ''
            if m and os.path.isdir(d) and not os.path.islink(d):
                lab = sh(f'git -C "{os.path.join(REPO, m.group(2))}" rev-parse HEAD', quiet=True, check=False).strip() or m.group(1)
                if sh(f'git -C "{d}" rev-parse HEAD', quiet=True, check=False).strip() != lab:
                    sh(f'git -C "{d}" checkout -q --detach --force {lab}', timeout=600, check=False, quiet=True)

    def engine_variant(self, wt, h0, ref, extra=()):
        """Today's lab code with the AUDIO ENGINE (app/src/main/cpp/audio + any healed files) as it was at ref."""
        self.pristine(wt, h0)
        subs = 'subs' in extra
        extra = [x for x in extra if x != 'subs']
        if subs:
            moved = self.sub_pins(wt, ref)
            print(f'  native submodules at {ref[:10]}\'s versions: {", ".join(moved) or "already the same"}', flush=True)
        paths = [self.ENGINE_DIR] + list(extra)
        sh(f'git -C "{wt}" checkout -q {ref} -- ' + ' '.join(f'"{p}"' for p in paths), timeout=300)
        dirs = [self.ENGINE_DIR] + [p for p in extra if not os.path.splitext(p)[1]]
        added = sh(f'git diff --name-only --diff-filter=A {ref} {h0} -- ' + ' '.join(dirs), quiet=True).split()
        for f in added:                                  # files that did not exist yet at ref
            fp = os.path.join(wt, f)
            if os.path.exists(fp):
                os.remove(fp)
        return self._tap(wt)

    def _tap(self, wt):
        """The mixer tap (exact sound). In exported-file mode it is optional: an app without it still gets checked."""
        try:
            return tap.apply(wt)
        except Exception as e:
            if CAPTURE != 'export_file':
                raise
            return f'no mixer tap ({str(e)[:60]}): exported-file mode'

    def fetch(self, branch):
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', branch)
        sh(f'git fetch --no-tags origin "+refs/heads/{branch}:refs/nightshift/audio/{safe}"', timeout=600)
        return sh(f'git rev-parse refs/nightshift/audio/{safe}', quiet=True).strip()

    def change(self, tip, control):
        """-> (diff, how): the branch's own change as a patch (submodule pointers left out)."""
        merged = subprocess.run(['git', 'merge-base', '--is-ancestor', tip, control], cwd=REPO).returncode == 0
        if merged:
            # the first commit on the control's main line that contains the branch = the merge (PR) that brought it in
            line = sh(f'git rev-list --first-parent --reverse {tip}..{control}', quiet=True).split()
            m = next((c for c in line if subprocess.run(['git', 'merge-base', '--is-ancestor', tip, c], cwd=REPO).returncode == 0), None)
            if not m:
                raise RuntimeError('the branch is in the control but its merge commit was not found')
            a, b, how = f'{m}^1', m, f'already merged into the control by {m[:10]}'
        else:
            a = sh(f'git merge-base {tip} {control}', quiet=True).strip()
            b, how = tip, f'forked from the control at {a[:10]}'
        subs = [ln.split('\t')[1] for ln in sh(f'git ls-tree -r {b}', quiet=True).splitlines() if ln.startswith('160000 ')]
        excl = ' '.join(f'":(exclude){s}"' for s in subs)
        diff = sh(f'git diff --binary {a} {b} -- . {excl}', quiet=True)
        files = sh(f'git diff --name-only {a} {b} -- . {excl}', quiet=True).split()
        return diff, how, files

    def lab_tree(self):
        """A worktree of the lab's current commit with the lab's own submodule checkouts (they build together)."""
        h0 = sh('git rev-parse HEAD', quiet=True).strip()
        wt = os.path.join(WT_ROOT, f'lab-{h0[:12]}')
        if not os.path.isdir(os.path.join(wt, 'app')):
            os.makedirs(WT_ROOT, exist_ok=True)
            sh('git worktree prune', check=False)
            sh(f'git -c core.autocrlf=false worktree add --detach --force "{wt}" {h0}', timeout=900)
        mark = os.path.join(wt, '.nightshift_submodules.json')
        done = json.load(open(mark)) if os.path.exists(mark) else {}
        for ln in sh(f'git ls-tree -r {h0}', quiet=True).splitlines():
            m = re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', ln)
            if not m:
                continue
            sm = m.group(2)
            d, src = os.path.join(wt, sm), os.path.join(REPO, sm)
            if not os.path.isdir(src):
                continue
            if sm in ('extra/oboe', 'extra/opencv'):     # big native trees, no Android resources: a link is enough
                if not os.path.islink(d):
                    if os.path.isdir(d) and not os.listdir(d):
                        os.rmdir(d)
                    if not os.path.exists(d):
                        os.makedirs(os.path.dirname(d), exist_ok=True)
                        os.symlink(src, d)
                continue
            sha = sh(f'git -C "{src}" rev-parse HEAD', quiet=True).strip()
            if done.get(sm) == sha and os.path.isdir(d) and os.listdir(d):
                continue
            if os.path.islink(d):
                os.unlink(d)
            elif os.path.isdir(d) and os.listdir(d):
                sh(f'git -C "{src}" worktree remove --force "{d}"', timeout=300, check=False)
                if os.path.isdir(d):
                    shutil.rmtree(d)
            elif os.path.isdir(d):
                os.rmdir(d)
            sh(f'git -C "{src}" worktree prune', check=False, quiet=True)
            sh(f'git -C "{src}" -c core.autocrlf=false worktree add --detach --force "{d}" {sha}', timeout=900)
            done[sm] = sha
            json.dump(done, open(mark, 'w'), indent=1)
        # third-party native libraries the lab has but git does not track (extra/libpng, freetype, harfbuzz...): CMake
        # needs them; link every untracked folder under extra/ that the worktree lacks
        ex = os.path.join(REPO, 'extra')
        for name in sorted(os.listdir(ex)) if os.path.isdir(ex) else []:
            src, d = os.path.join(ex, name), os.path.join(wt, 'extra', name)
            if os.path.isdir(src) and name != 'build' and not os.path.lexists(d):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                os.symlink(src, d)
        for f in ['local.properties', 'app/google-services.json']:
            if os.path.exists(os.path.join(REPO, f)) and not os.path.exists(os.path.join(wt, f)):
                shutil.copy2(os.path.join(REPO, f), os.path.join(wt, f))
        return h0, wt

    def pristine(self, wt, h0):
        """Put the worktree's tracked files back to the lab commit WITHOUT touching submodule paths: a plain
        reset --hard replaces the linked extra/oboe and extra/opencv with empty folders (resampler/... not found)."""
        subs = [ln.split('\t')[1] for ln in sh(f'git ls-tree -r {h0}', quiet=True).splitlines() if ln.startswith('160000 ')]
        excl = ' '.join(f'":(exclude){s}"' for s in subs)
        sh(f'git -C "{wt}" checkout -q -f {h0} -- . {excl}', timeout=300, check=False, quiet=True)
        sh(f'git -C "{wt}" clean -fdq -- app/src', timeout=300, check=False, quiet=True)
        try:
            self.sub_restore(wt, h0)
        except Exception as e:
            print(f'  submodule restore skipped ({str(e)[:100]})', flush=True)

    def variant(self, wt, h0, diff, with_change, contained):
        """Put the lab tree in the wanted state: pristine, then add or take away the branch's change, then the tap."""
        self.pristine(wt, h0)
        pf = os.path.join(wt, '.nightshift_change.patch')
        open(pf, 'w').write(diff)
        need = (with_change and not contained) or (not with_change and contained)
        if need and diff.strip() and not self._apply(wt, pf, reverse=contained):
            raise RuntimeError('the change does not apply to the lab code (conflicts)')
        return self._tap(wt)

    def _apply(self, wt, pf, reverse=False):
        """git apply, then a 3-way apply (uses the original file versions, survives moved lines). True when clean."""
        rev = ['-R'] if reverse else []
        for mode in ([], ['--3way']):
            r = subprocess.run(['git', '-C', wt, 'apply', *rev, *mode, '--whitespace=nowarn', pf], capture_output=True, text=True)
            if r.returncode == 0:
                return True
            self.pristine(wt, self._h0)                       # undo a half 3-way apply
        return False

    # ── 2 · build (cached per lab commit + change + tap version) and install ──
    def gradle(self, wt):
        """The build command for a worktree: path properties that point INTO the repo (opencvsdk=extra/opencv/...) are
        made absolute to the lab working copy's copy, so a big untracked SDK is never needed in the worktree."""
        cmd = GRADLE
        try:
            for ln in open(os.path.join(wt, 'gradle.properties'), errors='replace'):
                m = re.match(r'\s*(\w+)\s*=\s*((?:extra|libs|sdk)/[^\s#]+)\s*$', ln)
                if m and os.path.exists(os.path.join(REPO, m.group(2))):
                    cmd += f' -P{m.group(1)}="{os.path.join(REPO, m.group(2))}"'
        except OSError:
            pass
        return cmd

    def build(self, key, wt):
        os.makedirs(APKS, exist_ok=True)
        apk = os.path.join(APKS, f'{key}-{tap.VERSION}.apk')
        if not os.path.exists(apk):
            try:
                sh(self.gradle(wt), cwd=wt, timeout=5400)
            except RuntimeError:
                # the build log is long; the board gets the part that says WHY (Gradle's "What went wrong" / compiler errors)
                out = sh(self.gradle(wt) + ' --console=plain', cwd=wt, timeout=5400, check=False, quiet=True)
                os.makedirs(os.path.join(OUT, self.a.id), exist_ok=True)
                open(os.path.join(OUT, self.a.id, 'build.log'), 'w').write(out)
                ww = re.search(r'What went wrong:\n(.*?)(?:\n\* Try:|\Z)', out, re.S)
                errs = [l.strip() for l in out.splitlines() if ': error:' in l or l.startswith('e: ')][:6]
                why = (ww.group(1).strip() if ww else '') + ('\n' + '\n'.join(errs) if errs else '')
                raise RuntimeError('build failed: ' + (why[:900] or out[-600:]))
            # with -Pandroid.injected.build.abi the APK is written under intermediates/, not outputs/
            cands = [os.path.join(wt, APK_REL),
                     os.path.join(wt, 'app/build/intermediates/apk/productionInternal/debug/app-productionInternal-debug.apk')]
            cands = [c for c in cands if os.path.exists(c)]
            if not cands:
                raise RuntimeError('the build said SUCCESSFUL but wrote no APK')
            shutil.copy2(max(cands, key=os.path.getmtime), apk)
            cached = False
        else:
            cached = True
        out = sh(f'adb install -r -t "{apk}"', timeout=600, check=False)
        if 'Success' not in out and any(k in out for k in ('INSTALL_FAILED_VERSION_DOWNGRADE', 'INSTALL_FAILED_UPDATE_INCOMPATIBLE',
                                                            'signatures do not match', 'INSTALL_FAILED_ALREADY_EXISTS')):
            print('⚠ the phone has another build of the app (Play/release or another signing): uninstalling it once', flush=True)
            sh(f'adb uninstall {PKG}', timeout=120, check=False)       # same fallback as the worker's crash builds
            out = sh(f'adb install -r -t "{apk}"', timeout=600, check=False)
        if 'Success' not in out:
            raise RuntimeError('adb install failed: ' + out.strip()[-300:])
        return cached

    # ── 3 · export the test project on the phone and pull the dump ──
    def export(self, run_dir):
        p = PROJECTS[self.a.project]
        clip = os.path.join(ASSETS, p['clip'])
        dst = f'{PHONE_DIR}/{p["clip"]}'
        sh(f'adb shell mkdir -p {PHONE_DIR}', check=False)
        if p['clip'] not in sh(f'adb shell ls {PHONE_DIR}', check=False, quiet=True):
            sh(f'adb push "{clip}" {dst}', timeout=300)
        # 2026-10-21: the scenario takes the NEWEST video in the gallery. Lab runs copy other clips to new names
        # (ns_fresh_*, 100 s), and "touch" does not change the gallery date, so every export since Oct 20 used a 100 s
        # clip instead of this 35 s one. A copy under a NEW name is the newest for sure (same as fresh_video does).
        # The gallery sorts by MediaStore date_modified DESC (AllMediaInteractor), so the copy must be FIRST there:
        # checked below with the same query, before the 10-minute export (2026-10-21: the plain copy was not).
        fresh = f'{PHONE_DIR}/ns_audio_{self.a.project}_{int(time.time())}.mp4'
        sh(f'adb shell "cp {dst} {fresh}; touch {fresh}"', check=False)
        # The picker sorts videos by MediaStore date_modified DESC (AllMediaInteractor). Exports (DCIM/MyZesty-video) and
        # lab copies keep landing on top, and on Android 11 the shell's MEDIA_SCANNER broadcast is ignored, so: ask the
        # media provider to scan the copy (scan_file, then a volume scan), and if it is still not first, tap the tile
        # where it actually is (ZESTY_PICK_TILE). Never start the 10-minute export on the wrong clip.
        import shlex
        real = fresh.replace('/sdcard/', '/storage/emulated/0/')
        name = os.path.basename(fresh)

        def order():
            rows = sh('adb shell ' + shlex.quote('content query --uri content://media/external/video/media '
                                                 '--projection _data:date_modified --sort "date_modified DESC"'),
                      check=False, quiet=True)
            return [m.group(1) for m in re.finditer(r'Row: \d+ _data=(\S+?),', rows)]
        steps = [f'am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{real}',
                 f'content call --uri content://media --method scan_file --arg {real}',
                 'content call --uri content://media --method scan_volume --arg external_primary']
        tile, lst = -1, []
        for i, c in enumerate(steps):
            sh('adb shell ' + shlex.quote(c), check=False, timeout=300)
            time.sleep(4 if i < 2 else 20)
            lst = order()
            names = [os.path.basename(x) for x in lst]
            print(f'gallery after "{c.split()[0]} {c.split()[-1][:40]}": newest {names[:1]}; test copy at '
                  f'{names.index(name) if name in names else "missing"}', flush=True)
            if name in names and names.index(name) == 0:
                tile = 0
                break
        if tile < 0:                                # not first: use the tile it is on, or any earlier test copy
            names = [os.path.basename(x) for x in lst]
            idx = [k for k, n in enumerate(names) if n == name or n.startswith('ns_audio_') or n == p['clip']]
            if idx and idx[0] < 9:                  # 9 = tiles always on screen in the picker grid (3 rows of 3)
                tile = idx[0]
                print(f'the test clip is tile {tile} in the gallery ({names[tile]}); the scenario taps that tile', flush=True)
        if tile < 0:
            raise RuntimeError(f'the test clip is not among the first gallery tiles (newest: {lst[:1]}); '
                               'the export would use another clip, so it was not started')
        os.environ['ZESTY_PICK_TILE'] = str(tile)
        sh(f'adb shell am force-stop {PKG}', check=False)
        sh(f'adb shell run-as {PKG} rm -f {DUMP}', check=False)
        sh('adb logcat -G 16M', check=False)
        sh('adb logcat -c', check=False)
        t_phone = (sh('adb shell date +%s', check=False, quiet=True) or '0').strip()
        sh(f'{sys.executable} tools/stress/scenarios.py run {p["scenario"]} --repeat 1 --fresh on --reset none', timeout=1800)
        dump = os.path.join(run_dir, 'dump.f32')
        log = sh('adb logcat -d', check=False, quiet=True)
        if CAPTURE == 'export_file':
            return self.export_file(run_dir, dump, log, t_phone, p)
        sh(f'adb exec-out run-as {PKG} cat {DUMP} > "{dump}"', timeout=300, check=False)
        open(os.path.join(run_dir, 'run.log'), 'w').write(
            ''.join(l + '\n' for l in log.splitlines() if re.search(r'AUD split|underfill|OVERRUN', l)))
        seams = [float(m.group(1)) for m in re.finditer(r'AUD split at ([0-9.]+) s', log)]
        # 2026-10-21: the tap also logs the splits made in the PREVIEW (timed by pts) and one "0.0000" when the export
        # starts; only the export's own seams count (after the last 0.0000), never 0 or the very end (the rig crashed).
        if any(x < 0.001 for x in seams):
            seams = seams[len(seams) - 1 - seams[::-1].index(min(seams)) + 1:]
        seams = [x for x in seams if x > 0.05]
        under = re.findall(r'AUD layer \d+ underfill: (\d+) of (\d+) floats', log)
        size = os.path.getsize(dump) if os.path.exists(dump) else 0
        if size < 44100 * 8:
            raise RuntimeError(f'no mixer dump from the export ({size} bytes): did the export run on this build?')
        ref = os.path.join(ASSETS, p['ref'])
        src_s = os.path.getsize(ref) / 8 / 44100 if os.path.exists(ref) else 0
        got_s = size / 8 / 44100
        if src_s and abs(got_s - src_s) > max(2.0, 0.05 * src_s):
            raise RuntimeError(f'wrong test clip: the export is {got_s:.1f} s but the test clip is {src_s:.1f} s '
                               '(the project was made from another video on the phone); results would be meaningless')
        if not seams:
            raise RuntimeError('the export has no cuts (no "AUD split" from the engine): the splits did not happen, '
                               'so the seam tests would compare an unsplit clip; result discarded')
        return dump, seams, len(under), got_s

    def export_file(self, run_dir, dump, log, t_phone, p):
        """Exported-file mode (22 Oct, generic): no code hook. Take the newest video the app saved after the export
        started (MediaStore), pull it, decode its sound to the same float dump, and place the cuts from the app's own
        'MsgSplitVideo ... split_time' log lines (the running sum lands within ~25 ms of the real cut; the analysis snaps)."""
        import shlex
        try:
            t0 = int(t_phone) - 5
        except ValueError:
            t0 = 0
        rows = sh('adb shell ' + shlex.quote('content query --uri content://media/external/video/media '
                                             '--projection _data:date_added --sort "date_added DESC"'), check=False, quiet=True)
        vids = [(m.group(1), int(m.group(2))) for m in re.finditer(r'_data=(\S+?), date_added=(\d+)', rows)]
        vids = [v for v in vids if v[1] >= t0 and PHONE_DIR not in v[0]]
        if not vids:
            raise RuntimeError('exported-file mode: no new video was saved on the phone after the export started')
        src = vids[0][0]
        mp4 = os.path.join(run_dir, 'export.mp4')
        sh(f'adb pull "{src}" "{mp4}"', timeout=300, check=False)
        if not os.path.exists(mp4) or os.path.getsize(mp4) < 10000:
            raise RuntimeError(f'exported-file mode: could not pull {src}')
        ff = shutil.which('ffmpeg') or next((c for c in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(c)), None)
        if not ff:
            raise RuntimeError('exported-file mode needs ffmpeg on the Mac')
        sh(f'"{ff}" -y -loglevel error -i "{mp4}" -vn -f f32le -ar 44100 -ac 2 "{dump}"', timeout=300)
        open(os.path.join(run_dir, 'run.log'), 'w').write(''.join(l + '\n' for l in log.splitlines() if 'MsgSplitVideo' in l)
                                                          + f'exported file: {src}\n')
        parts = [int(m.group(1)) for m in re.finditer(r'MsgSplitVideo: media_layer \d+ media_id \d+ split_time (\d+)', log)]
        seams, acc = [], 0.0
        for us in parts[-max(1, p.get('cuts', len(parts))):]:   # the scenario splits the newest piece each time: a running sum
            acc += us / 1e6
            seams.append(round(acc, 4))
        size = os.path.getsize(dump) if os.path.exists(dump) else 0
        if size < 44100 * 8:
            raise RuntimeError(f'exported-file mode: the exported video has no sound ({size} bytes decoded)')
        ref = os.path.join(ASSETS, p['ref'])
        src_s = os.path.getsize(ref) / 8 / 44100 if os.path.exists(ref) else 0
        got_s = size / 8 / 44100
        if src_s and abs(got_s - src_s) > max(2.0, 0.05 * src_s):
            raise RuntimeError(f'wrong test clip: the export is {got_s:.1f} s but the test clip is {src_s:.1f} s; results would be meaningless')
        if not seams:
            raise RuntimeError('the export has no cuts (no MsgSplitVideo in the log); result discarded')
        return dump, seams, 0, got_s

    # ── 4 · the PR #3132 rig, unchanged ──
    def analyse(self, run_dir, dump, seams, tag):
        p = PROJECTS[self.a.project]
        ref = os.path.join(ASSETS, p['ref'])
        rig = os.path.join(HERE, 'rig')
        seam_arg = ','.join(f'{s:.4f}' for s in seams)
        out = sh(f'{sys.executable} "{rig}/audio_seam_check.py" --dump "{dump}" --source "{ref}" '
                 + (f'--seams {seam_arg} ' if seam_arg else '') + f'--out "{run_dir}/{tag}"', cwd=run_dir, timeout=900, check=False)
        sil = sh(f'{sys.executable} "{rig}/silence_check.py" "{dump}" --seams {seam_arg or "0"}', cwd=run_dir, timeout=600, check=False) if seam_arg else ''
        st = sh(f'{sys.executable} "{rig}/stereo_check.py" "{dump}" "{ref}"', cwd=run_dir, timeout=300, check=False)
        open(os.path.join(run_dir, 'seam_check.txt'), 'w').write(out)
        open(os.path.join(run_dir, 'silence_check.txt'), 'w').write(sil)
        open(os.path.join(run_dir, 'stereo_check.txt'), 'w').write(st)
        legacy = parse(out, sil, st)
        vj = os.path.join(run_dir, 'v2.json')
        v2o = sh(f'{sys.executable} "{rig}/seam_v2.py" --dump "{dump}" --source "{ref}" --seams {seam_arg or "0"} '
                 f'--expect-cuts {p.get("cuts", 0)} --json "{vj}"' + (' --lossy' if CAPTURE == 'export_file' else ''), cwd=run_dir, timeout=900, check=False)
        open(os.path.join(run_dir, 'v2.txt'), 'w').write(v2o)
        try:
            v2 = json.load(open(vj)) if os.path.exists(vj) else None
        except ValueError:
            v2 = None
        if v2 is None:                                   # v2 crashed: say so, keep the old rig's result
            legacy['selfcheck'] = []
            legacy['v2Error'] = (v2o.strip().splitlines() or [''])[-1][:200]
            return legacy
        res = dict(legacy)
        res.update({'tests': v2['tests'], 'passed': v2['passed'], 'cuts': v2['cuts'], 'cutsOk': v2['cutsOk'],
                    'selfcheck': v2['selfcheck'], 'limits': v2['limits'], 'analysis': 2,
                    'legacy': {'tests': legacy['tests'], 'passed': legacy['passed']}})
        return res

    def target(self, label, tag, token, with_change, ctx):
        """Steps 1-4 for one variant (with / without the branch's change). Returns the run record."""
        h0, wt, diff, contained, how, files = ctx[:6]
        rec = {'branch': label, 'commit': h0[:10], 'variant': 'with the change' if with_change else 'without the change'}
        rec['capture'] = CAPTURE                          # 'tap' (mixer tap, exact) or 'export_file' (decoded export, coarser)
        if len(ctx) > 6 and ctx[6]:
            rec['variant'] = 'old audio engine' if with_change else 'today\'s code'
        lead = 'Control: ' if not with_change else ''
        self.step(1, 'run', f'{lead}building today\'s lab code {h0[:7]} {"WITH" if with_change else "WITHOUT"} the change, with the mixer tap')
        import hashlib
        eng = ctx[6] if len(ctx) > 6 else None
        if eng and with_change:                          # ENGINE mode: the old audio engine inside today's app
            # At most TWO builds, and only one when this commit was built before: (1) only the audio engine of that commit;
            # (2) if that does not compile, the whole native layer of that commit with today's app. The mode that worked
            # is remembered per commit, so the next check of the same code goes straight to it.
            memo = os.path.join(OUT, 'engine_modes.json')
            modes = json.load(open(memo)) if os.path.exists(memo) else {}
            # decide BEFORE building: swapping only the audio engine's .cpp files compiles only when its headers (what the
            # rest of the native code sees) are the same as today. Changed headers -> straight to the whole native layer.
            hdr = sh(f'git diff --name-only {eng} {h0} -- "{self.ENGINE_DIR}/*.h" "{self.ENGINE_DIR}/*.hpp"', quiet=True).split()
            if modes.get(eng) == 'native+subs':
                tries = [['app/src/main/cpp', 'subs']]
            elif modes.get(eng) == 'native' or hdr:
                tries = [['app/src/main/cpp'], ['app/src/main/cpp', 'subs']]
                if hdr and modes.get(eng) != 'native':
                    print(f'  engine mode: {len(hdr)} audio header(s) differ from today ({", ".join(os.path.basename(h) for h in hdr[:4])}'
                          f'{"…" if len(hdr) > 4 else ""}): building the whole native layer of {eng[:10]} with today\'s app', flush=True)
            else:
                tries = [[], ['app/src/main/cpp'], ['app/src/main/cpp', 'subs']]
            for n_try, extra in enumerate(tries):
                note = self.engine_variant(wt, h0, eng, extra)
                mode = 'native+subs' if 'subs' in extra else 'native' if extra else 'audio'
                key = f'lab{h0[:10]}-eng{eng[:10]}-{mode}'
                try:
                    cached = self.build(key, wt)
                    modes[eng] = mode
                    json.dump(modes, open(memo, 'w'), indent=1)
                    break
                except RuntimeError:
                    if n_try == len(tries) - 1:
                        raise
                    nxt = tries[n_try + 1]
                    print('⚠ engine mode: ' + ('the whole native layer of that commit does not link with today\'s native submodules; '
                          f'adding {", ".join(self.NATIVE_SUBS)} at {eng[:10]}\'s versions (one more build)' if 'subs' in nxt else
                          'the old audio engine alone does not fit today\'s native code; building the whole '
                          f'native layer of {eng[:10]} with today\'s app instead (one more build)'), flush=True)
            rec['engineFrom'] = eng[:10]
            rec['engineExtra'] = extra
            note += f' · {"whole native layer + native submodules" if "subs" in extra else "whole native layer" if extra else "audio engine"} from {eng[:10]}'
        else:
            note = self.variant(wt, h0, diff, with_change, contained)
            key = f'lab{h0[:10]}-{"w" if with_change else "o"}{hashlib.sha1(diff.encode()).hexdigest()[:10]}'
            cached = self.build(key, wt)
        self.step(1, 'done', f'{lead}{"reused the APK built earlier" if cached else "built and installed"} · {note}')
        # 22 Oct (8/10 upgrade): N exports of the same build (exports of the same code differ by about one test), each
        # analysed with the v2 tests (what a listener hears at each cut) and the old PR #3132 rig for reference.
        # The result is the MEDIAN export; each test also says in how many exports it passed (stable or flaky).
        ov = os.path.join(OUT, 'exports_override.txt')                # flag file: more exports while hunting a flaky bug
        n_exp = max(1, int(os.environ.get('NS_AUDIO_EXPORTS') or (open(ov).read().strip() if os.path.exists(ov) else '') or EXPORTS))
        exps, notes = [], []
        for k in range(1, n_exp + 1):
            self.step(2, 'run', f'{lead}export {k}/{n_exp} of {PROJECTS[self.a.project]["label"]} on the lab phone')
            run_dir = os.path.join(OUT, self.a.id, tag if k == 1 else f'{tag}_{k}')
            os.makedirs(run_dir, exist_ok=True)
            try:
                dump, seams, under, secs = self.export(run_dir)
            except RuntimeError as e:
                notes.append(f'export {k}: {e}')
                print(f'⚠ export {k} discarded: {e}', flush=True)
                continue
            self.step(3, 'run', f'{lead}checking export {k}/{n_exp}: cuts, gaps, level, clicks')
            r = self.analyse(run_dir, dump, seams, tag if k == 1 else f'{tag}_{k}')
            if r.get('selfcheck'):
                notes.append(f'export {k}: ' + '; '.join(r['selfcheck']))
                print(f'⚠ export {k} failed its self-check: {r["selfcheck"]}', flush=True)
                continue
            r.update({'seams': seams, 'underfillLines': under, 'dumpSeconds': round(secs, 3), 'dir': run_dir, 'tag': tag if k == 1 else f'{tag}_{k}', 'dump': dump})
            exps.append(r)
        if not exps:
            raise RuntimeError('no valid export: ' + ' | '.join(notes)[:400])
        exps.sort(key=lambda r: r['passed'])
        med = exps[len(exps) // 2]                           # the median export stands for this build
        rec.update({k: v for k, v in med.items() if k not in ('dir', 'tag', 'dump')})
        for t in rec['tests']:                               # stable / flaky per test across the exports
            np_ = sum(1 for r in exps for x in r['tests'] if x['n'] == t['n'] and x['pass'])
            t['passCount'], t['exports'] = np_, len(exps)
            t['stable'] = np_ in (0, len(exps))
        rec['exports'] = [{'passed': r['passed'], 'cutsOk': r.get('cutsOk'), 'legacyPassed': (r.get('legacy') or {}).get('passed'),
                           'dumpSeconds': r['dumpSeconds']} for r in exps]
        rec['exportNotes'] = notes
        rec['passedRange'] = [exps[0]['passed'], exps[-1]['passed']]
        self.step(2, 'done', f'{lead}{len(exps)}/{n_exp} valid export(s) of {rec["dumpSeconds"]:.1f} s with {len(rec["seams"])} cuts'
                  + (f' ({len(notes)} discarded)' if notes else ''))
        gdir = os.path.join(PUBLIC_V, token)
        os.makedirs(gdir, exist_ok=True)
        rec['graphs'] = {}
        for g in ['offset', 'level', 'zoom', 'jumps']:
            src = os.path.join(med['dir'], f'{med["tag"]}_{g}.png')
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(gdir, f'{tag}_{g}.png'))
                rec['graphs'][g] = f'/v/{token}/{tag}_{g}.png'
        aud = os.path.join(gdir, f'{tag}.m4a')               # step 4: something to LISTEN to (the median export)
        ff = shutil.which('ffmpeg') or next((c for c in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(c)), None)
        if ff:
            sh(f'"{ff}" -y -loglevel error -f f32le -ar 44100 -ac 2 -i "{med["dump"]}" -c:a aac -b:a 192k -movflags +faststart "{aud}"', check=False, quiet=True)
            if os.path.exists(aud) and os.path.getsize(aud) > 1000:
                rec['audio'] = f'/v/{token}/{tag}.m4a'
        self.step(3, 'done', f'{lead}{rec["passed"]}/5 tests passed (median of {len(exps)}; range '
                             f'{rec["passedRange"][0]}-{rec["passedRange"][1]}) · {rec.get("cutsOk", "?")}/{len(rec.get("cuts") or [])} cuts clean')
        return rec

    def golden(self, h0, today):
        """Step 7 (range version, 22 Oct): every check also measures today's code. All its export scores per lab commit are
        kept. Today's code is known to vary between exports (it scored 1-5/5 on one build), so ONE reference run is not
        enough: a check counts as lab drift only if today's median is outside the range seen so far (+-1), and a build whose
        own exports spread by 3 or more is reported as unstable rather than blamed on the lab."""
        if not today or today.get('analysis') != 2:
            return
        gp = os.path.join(OUT, 'golden.json')
        g = json.load(open(gp)) if os.path.exists(gp) else {}
        key = f'{h0[:10]}:{self.a.project}'
        scores = [e.get('passed') for e in (today.get('exports') or []) if isinstance(e.get('passed'), int)] or [today['passed']]
        ref = g.get(key) or {}
        hist = list(ref.get('history') or ([ref['passed']] if 'passed' in ref else []))
        spread = max(scores) - min(scores)
        unstable = spread >= 3 or (hist and max(hist + scores) - min(hist + scores) >= 3)
        if not hist:
            state, note = 'set', f"today's code {today['passed']}/5 (exports {', '.join(map(str, scores))}) kept as the first reference for lab {h0[:10]}"
        elif min(hist) - 1 <= today['passed'] <= max(hist) + 1:
            state, note = 'ok', f"lab steady: today's code {today['passed']}/5, earlier runs {min(hist)}-{max(hist)}/5"
        else:
            state, note = 'drift', (f"LAB DRIFT: today's code scored {today['passed']}/5, earlier runs on this lab code "
                                    f"{min(hist)}-{max(hist)}/5; do not trust this check")
        if unstable and state != 'drift':
            note += f" · today's code itself is unstable (exports so far {min(hist + scores)}-{max(hist + scores)}/5), so compare medians, not single runs"
        g[key] = {'passed': today['passed'], 'history': hist + scores, 'runs': (ref.get('runs') or []) + [self.a.id], 'at': now(),
                  'tests': {str(t['n']): t['pass'] for t in today['tests']}}
        tmp = gp + '.tmp'
        json.dump(g, open(tmp, 'w'), indent=1); os.replace(tmp, gp)
        self.doc['golden'] = {'state': state, 'now': today['passed'], 'history': hist + scores, 'unstable': bool(unstable), 'note': note}
        if state == 'drift':
            self.doc['verdict']['headline'] = '⚠ ' + note + ' · ' + self.doc['verdict']['headline']
        elif unstable:
            self.doc['verdict']['headline'] += " · ⚠ today's code varies between exports"

    def run(self):
        ensure_assets()                                    # a fresh install: test clip + its reference sound
        token = secrets.token_hex(12)
        try:
            self.step(0, 'run', f'fetching {self.a.branch}' + (f' and {self.a.base}' if self.a.base else ''))
            tip, kind = self.resolve(self.a.branch)
            h0, wt = self.lab_tree()
            self._h0 = h0
            self.pristine(wt, h0)                                          # a check that died may have left the tap
            ab, contained, diff, how, files, eng = False, False, '', '', [], None
            if not kind:                                   # a branch: try its own change on today's code first
                control = self.fetch(self.a.base) if self.a.base else h0
                diff, how, files = self.change(tip, control)
                contained = subprocess.run(['git', 'merge-base', '--is-ancestor', tip, h0], cwd=REPO).returncode == 0
                if diff.strip():
                    pf = os.path.join(wt, '.nightshift_change.patch')
                    open(pf, 'w').write(diff)
                    ab = self._apply(wt, pf, reverse=contained)
                    self.pristine(wt, h0)
            if not ab:
                # ENGINE mode (a commit, before-pr-N, or a branch too old to add/take out): today's app with the audio
                # engine as it was at that point, against today's code. Old engines are compared the same way for years.
                eng = tip
                kind = kind or (f'{self.a.branch} is too old to add/take out its change ({how or "no change"}); its audio '
                                f'engine as it was')
                files = sh(f'git diff --name-only {tip} {h0} -- {self.ENGINE_DIR}', quiet=True).split()
            self.doc['change'] = {'how': kind if eng else how, 'files': files[:60], 'nFiles': len(files), 'lab': h0[:10],
                                  'inLabCode': contained, 'control': True, 'mode': 'engine' if eng else 'change'}
            if eng:
                self.step(0, 'done', f'{self.a.branch} = {tip[:10]}: {kind}. Mode: today\'s app with the audio engine of '
                                     f'{tip[:10]} ({len(files)} engine file(s) differ from today), against today\'s code')
                label = f'{self.a.branch}: audio engine of {tip[:10]}'
            else:
                self.step(0, 'done', f'{self.a.branch} @ {tip[:7]}: {len(files)} changed file(s), {how}'
                                     + ('; today\'s lab code already has it' if contained else ''))
                label = f'{self.a.branch} (its change on today\'s code)'
            ctx = (h0, wt, diff, contained, how, files, eng)
            try:
                self.doc['runs']['branch'] = self.target(label, 'branch', token, True, ctx)
            except RuntimeError as e:
                if eng or 'build failed' not in str(e):
                    raise
                # 2026-10-22: the branch's change applied on today's code but does not COMPILE there (it needs code or
                # submodule versions today's lab does not have). Fall back to ENGINE mode, which builds that branch's own
                # audio engine / native layer / native submodules inside today's app, so any branch, old or new, builds.
                print(f'⚠ the change of {self.a.branch} does not compile on today\'s code ({str(e)[:200]}); '
                      f'using its audio engine as it is at {tip[:10]} instead', flush=True)
                self.pristine(wt, h0)
                eng = tip
                files = sh(f'git diff --name-only {tip} {h0} -- {self.ENGINE_DIR}', quiet=True).split()
                kind = f'its change does not compile on today\'s code; its audio engine as it is at {tip[:10]}'
                self.doc['change'] = {'how': kind, 'files': files[:60], 'nFiles': len(files), 'lab': h0[:10],
                                      'inLabCode': contained, 'control': True, 'mode': 'engine'}
                label = f'{self.a.branch}: audio engine of {tip[:10]}'
                diff = ''                                 # engine mode compares against today's code as it is
                ctx = (h0, wt, diff, contained, how, files, eng)
                self.doc['runs']['branch'] = self.target(label, 'branch', token, True, ctx)
            self.save()
            self.doc['runs']['base'] = self.target("today's code" if eng else 'same code without the change', 'control', token, False, ctx)
            self.save()
            self.step(4, 'run', 'publishing')
            self.doc['verdict'] = verdict(self.doc['runs'])
            if self.doc.get('change', {}).get('mode') == 'engine':
                po, pt = self.doc['runs']['branch'].get('passed', 0), self.doc['runs']['base'].get('passed', 0)
                ob = self.doc['runs']['branch']
                if ob.get('rigError'):
                    extra_s = (ob.get('dumpSeconds') or 0) - (ob.get('sourceSeconds') or 0)
                    self.doc['verdict'] = {'proven': None, 'headline': (
                        f'old audio engine: the rig could not finish ({ob["rigError"][:80]})'
                        + (f'; it exported {extra_s:.1f} s MORE audio than the source' if extra_s > 0.5 else '')
                        + f' · today\'s code {pt}/5')}
                    po = None
                if po is not None:
                  self.doc['verdict'] = {'proven': None, 'headline': f'old audio engine {po}/5 · today\'s code {pt}/5 · ' + (
                    'today is better: the later fixes changed the result' if pt > po else
                    'same result: these tests do not see a difference' if pt == po else 'the old engine scored better')}
            rb, rc = self.doc['runs'].get('branch') or {}, self.doc['runs'].get('base') or {}
            if rb.get('cuts') is not None:                 # v2: how many cuts sound clean, per build
                nb = len(rb.get('cuts') or [])
                self.doc['verdict']['headline'] += f' · clean cuts {rb.get("cutsOk", "?")}/{nb}' + (
                    f' vs {rc.get("cutsOk", "?")}/{len(rc.get("cuts") or [])}' if rc else '')
            self.golden(h0, rc or rb)
            self.doc['status'], self.doc['finishedAt'] = 'done', now()
            self.step(4, 'done', 'verdict, graphs and audio on the board')
        except Exception as e:
            i = next((k for k, s in enumerate(self.steps) if s['state'] == 'run'), 4)
            self.steps[i]['state'], self.steps[i]['note'] = 'failed', str(e)[:300]
            self.doc['status'], self.doc['error'], self.doc['finishedAt'] = 'failed', str(e)[:500], now()
            self.save()
            print(f'ERROR {e}', flush=True)
            raise
        finally:
            try:                                          # leave the lab tree pristine for the next check
                if 'wt' in locals():
                    self.pristine(wt, h0)
            except Exception:
                pass
        os.makedirs(os.path.join(OUT, self.a.id), exist_ok=True)
        json.dump(self.doc, open(os.path.join(OUT, self.a.id, 'report.json'), 'w'), indent=1)
        print(f'DONE: {self.doc["verdict"]["headline"]}', flush=True)


def parse(out, sil, st):
    tests = []
    for m in re.finditer(r'TEST (\d)\s+(.+?)\s+(PASS|FAIL)\b\s*(.*)', out):
        tests.append({'n': int(m.group(1)), 'name': m.group(2).strip(), 'pass': m.group(3) == 'PASS', 'detail': m.group(4).strip()})
    holes = [{'t': float(a), 'ms': float(b)} for a, b in re.findall(r't=\s*([0-9.]+) s\s+len=\d+ \(([0-9.]+) ms\)', out)]
    steps = [{'t': float(a), 'samples': int(b), 'ms': float(c)} for a, b, c in
             re.findall(r't=\s*([0-9.]+) s\s+step ([+-]\d+) samples \(([+-][0-9.]+) ms\)', out)]
    lr = re.search(r'max\|L-R\| = ([0-9.]+)', out)
    passed = re.search(r'(\d)/5 tests passed', out)
    clicks = re.search(r'TEST 5.*?(\d+) of top 12', out)
    srows = [l.split() for l in st.splitlines()[1:] if l.strip()]
    stereo = {}
    if srows and len(srows[0]) >= 8:
        r0 = srows[0]
        stereo = {'peak': float(r0[2]), 'clipped': int(r0[3]), 'maxLR': float(r0[5]), 'sideRMS': float(r0[7])}
        if len(srows) > 1 and len(srows[1]) >= 8:
            stereo['refSideRMS'] = float(srows[1][7])
    silent = [l.strip() for l in sil.splitlines() if 'SILENT' in l]
    rig_err = ''
    if 'Traceback' in out:                            # the rig stopped part-way: the missing tests were NOT run (not failed)
        rig_err = (out.strip().splitlines() or [''])[-1][:200]
        done = {t['n'] for t in tests}
        tests += [{'n': n, 'name': '(not run)', 'pass': False, 'notRun': True,
                   'detail': f'the rig stopped before this test: {rig_err}'} for n in range(1, 6) if n not in done]
        tests.sort(key=lambda x: x['n'])
    src = re.search(r'source\s*:\s*\d+ frames \(([0-9.]+) s\)', out)
    return {'rigError': rig_err, 'sourceSeconds': float(src.group(1)) if src else None,
            'tests': tests, 'passed': int(passed.group(1)) if passed else sum(t['pass'] for t in tests),
            'holes': holes, 'repeated': [s for s in steps if s['samples'] < 0], 'skipped': [s for s in steps if s['samples'] > 0],
            'clicksNearSeams': int(clicks.group(1)) if clicks else None, 'maxLR': float(lr.group(1)) if lr else None,
            'stereo': stereo, 'silentClips': silent}


def verdict(runs):
    b, c = runs.get('branch') or {}, runs.get('base')
    pb = b.get('passed', 0)
    if c is None:
        head = f'{pb}/5 passed' + (' · seams are sample-clean' if pb == 5 else '')
        proven = None
    else:
        pc = c.get('passed', 0)
        proven = pb == 5 and pc <= pb
        head = f'{pb}/5 passed · control {pc}/5 · ' + ('proven' if proven else 'better than control, not proven' if pb > pc
                                                        else 'no better than control')
    return {'headline': head, 'proven': proven}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', required=True)
    ap.add_argument('--branch', required=True)
    ap.add_argument('--project', default='splits', choices=sorted(PROJECTS))
    ap.add_argument('--base', default='')
    ap.add_argument('--by', default='')
    ap.add_argument('--device', default='', help='adb serial to export on (default: the lab phone); e.g. emulator-5554')
    a = ap.parse_args()
    if a.device:                                   # step 8: the same check on another device (emulator lane)
        if not re.fullmatch(r'emulator-\d{4}|[A-Za-z0-9]{6,32}', a.device):
            sys.exit(f'bad device: {a.device}')
        os.environ['ANDROID_SERIAL'] = a.device
    for v in (a.branch, a.base):
        if v and not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', v):
            sys.exit(f'bad branch name: {v}')
    Check(a).run()
