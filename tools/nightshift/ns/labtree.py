"""The crash lab builds in its OWN folder, never in the engineer's working copy, so Android Studio stays free.

A git worktree of the default base branch (nightshift.yaml lab.base_branch, e.g. CPP-1.25.2; a job may name another)
under ~/.nightshift_lab/<branch>/, refreshed to that branch's latest commit at every job. Same setup as Audio Check's lab
folder: the submodules are worktrees at the commits the working copy has checked out (those build together), the big
native trees and the untracked third-party libraries under extra/ are links, local.properties / google-services.json
and the untracked debug lab sources (app/src/debug: LabControl) are copied in, and path properties that point into the
repo (opencvsdk=extra/...) are made absolute.

Everything a crash job changes - the field build's files, debug hooks, fix patches, the builds themselves - happens
here. config.LAB points at this folder for the job; config.REPO stays the working copy (tools, results, notes).
Off: nightshift.yaml lab.separate_build: false (the old in-place behaviour)."""
import json
import os
import re
import shutil
import subprocess

from . import config

ROOT = os.path.expanduser('~/.nightshift_lab')
LINKED = ('extra/oboe', 'extra/opencv')          # big native trees without Android resources: a link is enough
COPIED = ('local.properties', 'app/google-services.json')


def _sh(args, cwd=None, timeout=900, check=True):
    r = subprocess.run(args, cwd=cwd or config.REPO, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f'{" ".join(args[:6])}: {(r.stderr or r.stdout).strip()[-300:]}')
    return r.stdout


def enabled(cfg):
    return bool((cfg.get('lab') or {}).get('separate_build', False))


def gitlinks(sha):
    out = _sh(['git', 'ls-tree', '-r', sha])
    return [(m.group(1), m.group(2)) for m in (re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', l) for l in out.splitlines()) if m]


def pristine(wt, sha):
    """Tracked files back to sha, without touching submodule paths (a plain reset --hard would turn the linked
    extra/oboe and extra/opencv into empty folders)."""
    excl = [f':(exclude){p}' for _, p in gitlinks(sha)]
    _sh(['git', '-C', wt, 'checkout', '-q', '-f', sha, '--', '.', *excl], check=False)
    _sh(['git', '-C', wt, 'clean', '-fdq', '--', 'app/src/main'], check=False)


_SHARED = re.compile(r'^(sprint\d+|master|main|develop|dev|CPP-[\w.-]+|release[\w./-]*)$')


def _module_commit(src, sm, log=print):
    """Which commit of a Kotlin module the lab build uses. Normally the working copy's (the sprint you work on). 2 Nov:
    the working copy was on a feature branch for a manual test (bg-removal-code-clean), its Player.kt no longer had a
    JNI method the C++ looks up, and every lab run aborted at app start. A feature branch in the working copy is the
    developer's own business: the lab takes the newest sprint branch instead (and says so)."""
    head = _sh(['git', '-C', src, 'rev-parse', 'HEAD']).strip()
    br = subprocess.run(['git', '-C', src, 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
    refs = subprocess.run(['git', '-C', src, 'for-each-ref', '--format=%(refname:short)', 'refs/remotes/origin/sprint*',
                           'refs/heads/sprint*'], capture_output=True, text=True).stdout.split()
    num = lambda r: int(re.search(r'sprint(\d+)$', r).group(1)) if re.search(r'sprint(\d+)$', r) else -1
    refs = sorted((r for r in refs if num(r) >= 0), key=lambda r: (num(r), r.startswith('origin/')))
    newest = num(refs[-1]) if refs else -1
    m = re.fullmatch(r'sprint(\d+)', br or '')
    # the working copy counts only when it is on the NEWEST sprint (or a shared non-sprint branch). 2 Nov: it was on
    # sprint216 with java-common never pulled (no isBodyEffect) -> 'Unresolved reference' in the editor module.
    if not refs or br == 'HEAD' or (m and int(m.group(1)) >= newest) or (not m and _SHARED.match(br or '')):
        return head
    name = f'sprint{newest}'
    subprocess.run(['git', '-C', src, 'fetch', '-q', '--no-tags', 'origin', f'+refs/heads/{name}:refs/remotes/origin/{name}'],
                   capture_output=True, timeout=600)            # every module at the SAME, fresh sprint: they build together
    sha = subprocess.run(['git', '-C', src, 'rev-parse', '--verify', '--quiet', f'origin/{name}'], capture_output=True,
                         text=True).stdout.strip() or _sh(['git', '-C', src, 'rev-parse', refs[-1]]).strip()
    log(f'lab build: {sm} in your working copy is on {br} ({"an older sprint" if m else "a feature branch"}); the lab '
        f'uses {name} @ {sha[:8]} instead, so your own checkout cannot break the lab build')
    return sha



def _compat(d, sm, log=print):
    """Release Kotlin in the lab app: React Native stand-ins, missing namespace (ns/labcompat.py). Lab copy only."""
    try:
        from . import labcompat
        for c in labcompat.apply(d, sm, log):
            log(f'lab build: {c}')
    except Exception as e:
        log(f'lab build: {sm}: compatibility step failed ({str(e)[:120]})')

SHARED_LIBS_SKIP = {'app'}
# 3 Nov (2nd build check): taking EVERY shared library's sources from the app broke colorpicker (ColorPickerView.java:74
# cannot find symbol: the app's copy needs things the lab's own colorpicker build.gradle does not give it). Only the
# libraries the release Kotlin is known to need from the app are synced; the rest keep the engine commit's copy.
APP_LIBS = {'videotrimmerlib'}


def _app_libs(wt, app, log=print):
    """3 Nov: the small Android libraries both repos carry (videotrimmerlib, colorpicker, crop, ...) are taken from the
    SHIPPED app (myzesty_mobile android/<lib> at the app commit), not from video_gles3jni at the engine commit: the release
    Kotlin was built against the app's copies (gallerypicker needs videotrimmerlib's toMediaUri, which video_gles3jni only
    got on 21 Oct). Lab folder only; files are rewritten only when they differ (Gradle keeps its cache)."""
    import filecmp
    import tarfile
    import tempfile
    repo, commit = app
    names = subprocess.run(['git', '-C', repo, 'ls-tree', '-d', '--name-only', commit, 'android/'], capture_output=True,
                           text=True).stdout.split()
    appdirs = {os.path.basename(n).lower(): os.path.basename(n) for n in names}
    done = []
    for d in sorted(os.listdir(wt)):
        if d.lower() not in APP_LIBS and os.path.isdir(os.path.join(wt, d, 'src')) and d not in SHARED_LIBS_SKIP:
            # undo files an earlier (all-libraries) sync left behind: tracked ones are reset by pristine(), extra ones here
            subprocess.run(['git', '-C', wt, 'clean', '-fdq', '--', f'{d}/src'], capture_output=True)
            continue
        if d in SHARED_LIBS_SKIP or d.lower() not in appdirs or not os.path.isdir(os.path.join(wt, d)) \
                or not any(os.path.exists(os.path.join(wt, d, g)) for g in ('build.gradle', 'build.gradle.kts')) \
                or os.path.exists(os.path.join(wt, d, '.git')):
            continue
        src = f'android/{appdirs[d.lower()]}'
        tmp = tempfile.mkdtemp(prefix='nslib_')
        try:
            arc = subprocess.run(['git', '-C', repo, 'archive', '--format=tar', commit, src], capture_output=True, timeout=300)
            if arc.returncode:
                continue
            import io
            tarfile.open(fileobj=io.BytesIO(arc.stdout)).extractall(tmp)
            # only the SOURCES (src/): the lab keeps its own build.gradle files, which its Gradle plugin understands
            # (3 Nov: the app's older colorpicker build.gradle has no namespace -> 'problem configuring :colorpicker')
            new_root, old_root = os.path.join(tmp, src, 'src'), os.path.join(wt, d, 'src')
            if not os.path.isdir(new_root):
                continue
            changed = 0
            for root, _ds, files in os.walk(new_root):
                for f in files:
                    a = os.path.join(root, f)
                    b = os.path.join(old_root, os.path.relpath(a, new_root))
                    if not os.path.exists(b) or not filecmp.cmp(a, b, shallow=False):
                        os.makedirs(os.path.dirname(b), exist_ok=True)
                        shutil.copy2(a, b)
                        changed += 1
            for root, _ds, files in os.walk(old_root):
                if os.sep + 'build' + os.sep in root + os.sep:
                    continue
                for f in files:
                    b = os.path.join(root, f)
                    if not os.path.exists(os.path.join(new_root, os.path.relpath(b, old_root))):
                        os.remove(b)
                        changed += 1
            done.append(f'{d}{" (" + str(changed) + " files)" if changed else ""}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if done:
        log(f'lab build: shared Android library sources from the shipped app {commit[:10]}: {", ".join(done)}')


UI_PATHS = ('app/src/main/java', 'app/src/main/res', 'app/src/main/AndroidManifest.xml')


def _lab_ui(wt, ui, log=print):
    """3 Nov: the lab app's OWN screens (video_gles3jni app/src/main java/res/manifest; never cpp/) from commit `ui`.
    The engine commit of build 800054890 (342ff8625e, 15 Oct) still had the old music picker
    (MusicCategoryAdapter uses item_category_img), which the release java-common (d66f8e22) no longer has: video_gles3jni
    only synced its screens to the new java-common on 21 Oct. These screens are the lab harness, not the users' code;
    the engine (cpp/) stays at the field commit. pristine() puts everything back on the next build."""
    for rel in UI_PATHS:
        p = os.path.join(wt, rel)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.exists(p):
            os.remove(p)
        _sh(['git', '-C', wt, '-c', 'core.autocrlf=false', 'checkout', '-q', ui, '--', rel], check=False)
    log(f'lab build: the lab app\'s own screens (app/src/main java/res/manifest) from {ui[:10]}; engine C++ unchanged')


def ensure(cfg, branch=None, log=print, sha=None, pins=None, name=None, app=None, ui=None):
    """Create/refresh the lab folder for `branch` (default lab.base_branch) at its latest commit. -> (path, sha).
    2 Nov, the release recipe (ns/recipe.py): sha = the engine commit the users' build was made from (whole tree) and
    pins = {module: commit} the shipped app used; the folder is ~/.nightshift_lab/rel_<name>."""
    pins = pins or {}
    branch = branch or (cfg.get('lab') or {}).get('base_branch') or 'HEAD'
    if sha:
        if subprocess.run(['git', 'cat-file', '-e', sha + '^{commit}'], cwd=config.REPO, capture_output=True).returncode:
            _sh(['git', 'fetch', '-q', '--no-tags', 'origin', sha], check=False)
        branch = f'rel_{name or sha[:10]}'
    elif branch == 'HEAD':
        sha = _sh(['git', 'rev-parse', 'HEAD']).strip()
    else:
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', branch)
        _sh(['git', 'fetch', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/lab/{safe}'], check=False)
        r = subprocess.run(['git', 'rev-parse', f'refs/nightshift/lab/{safe}'], cwd=config.REPO, capture_output=True, text=True)
        sha = r.stdout.strip() if r.returncode == 0 else _sh(['git', 'rev-parse', branch]).strip()
    wt = os.path.join(ROOT, re.sub(r'[^A-Za-z0-9._-]', '_', branch))
    if not os.path.isdir(os.path.join(wt, 'app')):
        os.makedirs(ROOT, exist_ok=True)
        if branch.startswith('rel_'):                  # release-recipe folders: keep the 3 newest (each one is a full build)
            olds = sorted((os.path.join(ROOT, x) for x in os.listdir(ROOT) if x.startswith('rel_')), key=os.path.getmtime)
            for o in olds[:max(0, len(olds) - 2)]:
                _sh(['git', 'worktree', 'remove', '--force', o], check=False)
                shutil.rmtree(o, ignore_errors=True)
                log(f'lab folder removed (older release recipe): {o}')
        _sh(['git', 'worktree', 'prune'], check=False)
        _sh(['git', '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', '--force', wt, sha])
        log(f'lab folder created: {wt} ({branch} @ {sha[:10]}); first build there is a full build')
    else:
        _sh(['git', '-C', wt, '-c', 'core.autocrlf=false', 'checkout', '-q', '--detach', '-f', sha], check=False)
    pristine(wt, sha)
    if ui:
        _lab_ui(wt, ui, log)
    if app:
        try:
            _app_libs(wt, app, log)
        except Exception as e:
            log(f'lab build: shared libraries from the shipped app skipped ({str(e)[:120]})')
    mark = os.path.join(wt, '.nightshift_submodules.json')
    done = json.load(open(mark)) if os.path.exists(mark) else {}
    for _pin, sm in gitlinks(sha):
        d, src = os.path.join(wt, sm), os.path.join(config.REPO, sm)
        if not os.path.isdir(src):
            continue
        if sm in LINKED:
            if not os.path.islink(d):
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
                if not os.path.exists(d):
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    os.symlink(src, d)
            continue
        want = None
        pin = pins.get(os.path.basename(sm))
        if pin:                                       # release recipe: the module commit the shipped app used
            if subprocess.run(['git', '-C', src, 'cat-file', '-e', pin + '^{commit}'], capture_output=True).returncode:
                subprocess.run(['git', '-C', src, 'fetch', '-q', '--no-tags', 'origin', pin], capture_output=True, timeout=600)
            if subprocess.run(['git', '-C', src, 'cat-file', '-e', pin + '^{commit}'], capture_output=True).returncode == 0:
                want = pin
            else:
                log(f'lab build: {sm} commit {pin[:8]} of the release is not reachable; using the newest sprint')
        want = want or _module_commit(src, sm, log)
        pinned_here = bool(pin) and want == pin
        if done.get(sm) == want and os.path.isdir(d) and os.listdir(d):
            if pinned_here:
                _compat(d, sm, log)
            continue
        if os.path.islink(d):
            os.unlink(d)
        elif os.path.isdir(d) and os.listdir(d):
            _sh(['git', '-C', src, 'worktree', 'remove', '--force', d], check=False)
            if os.path.isdir(d):
                shutil.rmtree(d)
        elif os.path.isdir(d):
            os.rmdir(d)
        _sh(['git', '-C', src, 'worktree', 'prune'], check=False)
        _sh(['git', '-C', src, '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', '--force', d, want])
        done[sm] = want
        json.dump(done, open(mark, 'w'), indent=1)
        if pinned_here:
            _compat(d, sm, log)
    ex = os.path.join(config.REPO, 'extra')
    for name in sorted(os.listdir(ex)) if os.path.isdir(ex) else []:   # untracked third-party libraries (libpng, ...)
        src, d = os.path.join(ex, name), os.path.join(wt, 'extra', name)
        if os.path.isdir(src) and name != 'build' and not os.path.lexists(d):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.symlink(src, d)
    for f in COPIED:
        if os.path.exists(os.path.join(config.REPO, f)):
            os.makedirs(os.path.dirname(os.path.join(wt, f)) or wt, exist_ok=True)
            shutil.copy2(os.path.join(config.REPO, f), os.path.join(wt, f))
    dbg, dd = os.path.join(config.REPO, 'app/src/debug'), os.path.join(wt, 'app/src/debug')
    if os.path.isdir(dbg):                              # the lab's debug-only sources (LabControl): always the current ones
        if os.path.isdir(dd):
            shutil.rmtree(dd)
        shutil.copytree(dbg, dd)
    if os.path.basename(wt).startswith('rel_'):         # 3 Nov: build repairs Night Shift made for this folder
        try:
            from . import buildfix
            buildfix.reapply(wt, log)
        except Exception as e:
            log(f'lab build: kept build repairs not applied ({str(e)[:120]})')
    return wt, sha


def gradle_props(wt):
    """-P overrides for path properties that point into the repo (opencvsdk=extra/opencv/...)."""
    out = ''
    try:
        for ln in open(os.path.join(wt, 'gradle.properties'), errors='replace'):
            m = re.match(r'\s*(\w+)\s*=\s*((?:extra|libs|sdk)/[^\s#]+)\s*$', ln)
            if m and os.path.exists(os.path.join(config.REPO, m.group(2))):
                out += f' -P{m.group(1)}="{os.path.join(config.REPO, m.group(2))}"'
    except OSError:
        pass
    return out


def activate(cfg, branch=None, log=print, sha=None, pins=None, name=None, app=None, ui=None):
    """Point config.LAB at the lab folder for this job. -> (path, sha) or (REPO, '') when off."""
    if not enabled(cfg):
        config.LAB = config.REPO
        return config.REPO, ''
    wt, sha = ensure(cfg, branch, log, sha=sha, pins=pins, name=name, app=app, ui=ui)
    config.LAB = wt
    return wt, sha


def deactivate():
    config.LAB = config.REPO
