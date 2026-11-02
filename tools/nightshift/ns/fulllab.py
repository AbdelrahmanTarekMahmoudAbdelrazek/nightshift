"""The full app built from source (26 Oct). Anyone whose computer has a myzesty_mobile checkout (nightshift.yaml
full_app.path) reproduces full-app crashes from source: a debug build of the release branch the crash came from
(release/<version>, else full_app.base_branch, default development), so fixes are built and verified on the phone
exactly like engine crashes. Nobody else's computer is ever used.

Built in its OWN folder, never in the person's checkout: a git worktree under ~/.nightshift_lab/full-<branch>/, its
submodules as worktrees at the commits that branch pins, node_modules linked from the checkout, untracked settings
(local.properties, google-services.json, .env*) copied. The debug variant bundles the JavaScript
(productionInternalDebug is not in debuggableVariants), so no Metro server is needed.
"""
import json
import os
import re
import shutil
import subprocess

ROOT = os.path.expanduser('~/.nightshift_lab')
INSTALL = ('cd android && ENVFILE=.env.production ./gradlew installProductionInternalDebug '
           '-PreactNativeArchitectures=arm64-v8a')
# untracked (gitignored) folders the build needs, linked from the person's checkout like node_modules (28 Oct: the
# first full-app build failed because settings.gradle points :opencv at the ignored OpenCV SDK folder)
LINKED = ('android/extra/opencv/OpenCV-android-sdk',)
COPIED = ('android/local.properties', 'android/app/google-services.json', '.env', '.env.production', '.env.staging')


def checkout(cfg):
    """The person's myzesty_mobile folder, or None. nightshift.yaml full_app.path, else a usual place."""
    p = str(((cfg or {}).get('full_app') or {}).get('path') or '').strip()
    cands = [p] if p else ['~/myzesty_mobile', '~/AndroidStudioProjects/myzesty_mobile', '~/Projects/myzesty_mobile',
                           '~/Documents/myzesty_mobile', '~/work/myzesty_mobile', '~/StudioProjects/myzesty_mobile']
    for c in cands:
        c = os.path.expanduser(c)
        if os.path.isdir(os.path.join(c, 'android', 'app')) and os.path.isdir(os.path.join(c, '.git')):
            return c
    return None


def install_cmd(cfg):
    return str(((cfg or {}).get('full_app') or {}).get('install') or INSTALL)


def _sh(args, cwd, timeout=900, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f'{" ".join(args[:6])}: {(r.stderr or r.stdout).strip()[-300:]}')
    return r.stdout


def branch_for(cfg, src, version):
    """release/<version> when the full app has that branch (the code the users had), else the base branch."""
    base = str(((cfg or {}).get('full_app') or {}).get('base_branch') or 'development')
    if version:
        b = f'release/{version}'
        if _sh(['git', 'ls-remote', '--heads', 'origin', b], src, 120, check=False).strip():
            return b
    return base


def ensure(cfg, version=None, log=print):
    """Create/refresh the full-app lab folder. -> (path, branch, sha)"""
    src = checkout(cfg)
    if not src:
        raise RuntimeError('no myzesty_mobile checkout on this computer (nightshift.yaml full_app.path)')
    branch = branch_for(cfg, src, version)
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', branch)
    # shallow: a checkout cloned with --depth 1 (the full history is several GB) stays small
    _sh(['git', 'fetch', '--depth', '1', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/full/{safe}'], src, 1800, check=False)
    sha = _sh(['git', 'rev-parse', f'refs/nightshift/full/{safe}'], src).strip()
    # 29 Oct: a branch TIP is not what users have (release/1.25.2's tip did not even start: a later merge used
    # NativeModules without importing it). nightshift.yaml full_app.pins: "1.25.2=<sha>, ..." = the commit that build
    # was really made from; use it when known (fetched with enough history to reach it).
    pins = dict(x.split('=', 1) for x in str(((cfg or {}).get('full_app') or {}).get('pins') or '').replace(' ', '').split(',') if '=' in x)
    pin_sha = pins.get(str(version or ''))
    if pin_sha:
        if _sh(['git', 'cat-file', '-t', pin_sha], src, 60, check=False).strip() != 'commit':
            _sh(['git', 'fetch', '--depth', '300', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/full/{safe}'], src, 1800, check=False)
        if _sh(['git', 'cat-file', '-t', pin_sha], src, 60, check=False).strip() == 'commit':
            sha = _sh(['git', 'rev-parse', pin_sha], src).strip()
            log(f'full-app lab folder: {version} pinned to {sha[:10]} (nightshift.yaml full_app.pins), not the {branch} tip')
        else:
            log(f'full-app lab folder: pinned commit {pin_sha} for {version} not found in {branch}; using the tip')
    wt = os.path.join(ROOT, f'full-{safe}')
    if not os.path.isdir(os.path.join(wt, 'android')):
        os.makedirs(ROOT, exist_ok=True)
        _sh(['git', 'worktree', 'prune'], src, check=False)
        _sh(['git', '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', '--force', wt, sha], src)
        log(f'full-app lab folder created: {wt} ({branch} @ {sha[:10]}); the first build there is a full build')
    else:
        _sh(['git', '-C', wt, '-c', 'core.autocrlf=false', 'checkout', '-q', '--detach', '-f', sha], wt, check=False)
        _sh(['git', '-C', wt, 'checkout', '-q', '-f', sha, '--', '.'], wt, check=False)   # a previous fix/hook is gone
    mark = os.path.join(wt, '.nightshift_submodules.json')
    done = json.load(open(mark)) if os.path.exists(mark) else {}
    base = str(((cfg or {}).get('full_app') or {}).get('base_branch') or 'development')
    tip_when = _sh(['git', 'show', '-s', '--format=%cI', sha], src, 60, check=False).strip() or 'now'
    try:
        import datetime as _dt
        tip_since = (_dt.datetime.fromisoformat(tip_when) - _dt.timedelta(days=60)).date().isoformat()
    except Exception:
        tip_since = '2026-01-01'
    links = [(m.group(1), m.group(2)) for m in (re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', l)
             for l in _sh(['git', 'ls-tree', '-r', sha], src).splitlines()) if m]
    # the snapshot time: the newest of the app commit and the modules' own release-branch heads (modules without that
    # branch take their base branch as of this time, so all modules come from the same moment)
    for _pin, _sm in links:
        _s = os.path.join(src, _sm)
        if not os.path.exists(os.path.join(_s, '.git')) or branch == base:
            continue
        _h = _sh(['git', '-C', _s, 'ls-remote', '--heads', 'origin', branch], _s, 120, check=False).split()
        if _h and re.fullmatch(r'[0-9a-f]{40}', _h[0]):
            if _sh(['git', '-C', _s, 'cat-file', '-t', _h[0]], _s, 60, check=False).strip() != 'commit':
                _sh(['git', '-C', _s, 'fetch', '--depth', '1', '--no-tags', 'origin', branch], _s, 1800, check=False)
            _t = _sh(['git', '-C', _s, 'show', '-s', '--format=%cI', _h[0]], _s, 60, check=False).strip()
            try:
                import datetime as _dt
                if _t and _dt.datetime.fromisoformat(_t) > _dt.datetime.fromisoformat(tip_when):
                    tip_when = _t
            except Exception:
                pass
    for pin, sm in links:                              # each module at the commit this branch pins
        d, s = os.path.join(wt, sm), os.path.join(src, sm)
        if not os.path.exists(os.path.join(s, '.git')):
            continue
        # 28 Oct: the team builds with each module on ITS OWN branch of the same name (release/1.25.2), not at the
        # commit the app branch pins (the pins lag: release/1.25.2 pinned an older java-common than the editor module
        # needed, and the build did not compile). Use that branch's head when the module has it, else the pin.
        heads = _sh(['git', '-C', s, 'ls-remote', '--heads', 'origin', branch], s, 120, check=False).split()
        if heads and re.fullmatch(r'[0-9a-f]{40}', heads[0]):
            if heads[0] != pin:
                log(f'full-app lab folder: {sm} at its {branch} head {heads[0][:10]} (the app branch pins {pin[:10]})')
            pin = heads[0]
        elif branch != base:
            # no such branch in this module (e.g. the editor module has no release/x.y.z): its base branch
            # (development) as it was at the app branch's last commit, never a later sprint
            _sh(['git', '-C', s, 'fetch', '--no-tags', f'--shallow-since={tip_since}', 'origin', base], s, 1800, check=False)
            at = _sh(['git', '-C', s, 'rev-list', '-1', f'--before={tip_when}', 'FETCH_HEAD'], s, 60, check=False).strip()
            if re.fullmatch(r'[0-9a-f]{40}', at):
                if at != pin:
                    log(f'full-app lab folder: {sm} has no {branch}: its {base} at {tip_when[:16]} = {at[:10]} '
                        f'(the app branch pins {pin[:10]})')
                pin = at
        if done.get(sm) == pin and os.path.isdir(d) and os.listdir(d):
            _sh(['git', '-C', d, 'checkout', '-q', '-f', pin, '--', '.'], d, check=False)
            continue
        if _sh(['git', '-C', s, 'cat-file', '-t', pin], s, 60, check=False).strip() != 'commit':
            _sh(['git', '-C', s, 'fetch', '--depth', '1', '--no-tags', 'origin', branch], s, 1800, check=False)
            if _sh(['git', '-C', s, 'cat-file', '-t', pin], s, 60, check=False).strip() != 'commit':
                _sh(['git', '-C', s, 'fetch', '--depth', '1', '--no-tags', 'origin', pin], s, 1800, check=False)
        if os.path.isdir(d) and os.listdir(d):
            _sh(['git', '-C', s, 'worktree', 'remove', '--force', d], s, check=False)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
        _sh(['git', '-C', s, 'worktree', 'prune'], s, check=False)
        _sh(['git', '-C', s, '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', '--force', d, pin], s)
        done[sm] = pin
        json.dump(done, open(mark, 'w'), indent=1)
    nm, dn = os.path.join(src, 'node_modules'), os.path.join(wt, 'node_modules')
    if not os.path.isdir(nm):
        raise RuntimeError(f'{src} has no node_modules: run "npm install" there once (Night Shift never installs packages itself)')
    # 28 Oct: Metro does not index files behind a symlinked node_modules ("Unable to resolve module @babel/runtime/...").
    # On macOS make a real folder as an APFS clone (cp -c: instant, no extra disk until a file changes); else symlink.
    if os.path.islink(dn) and _sh(['uname'], wt, 30, check=False).strip() == 'Darwin':
        os.unlink(dn)
    if not os.path.lexists(dn):
        ok = False
        if _sh(['uname'], wt, 30, check=False).strip() == 'Darwin':
            r = subprocess.run(['cp', '-cR', nm, dn], capture_output=True, text=True, timeout=1800)
            ok = r.returncode == 0
            log('full-app lab folder: node_modules cloned from your checkout (APFS clone)' if ok else
                f'full-app lab folder: node_modules clone failed ({(r.stderr or "").strip()[:120]}); using a link')
            if not ok:
                shutil.rmtree(dn, ignore_errors=True)
        if not ok:
            os.symlink(nm, dn)
    # modules listed in .gitmodules but NOT pinned by the app branch (e.g. android/extra/opencv): the team gets them from
    # their own repo, so clone that (the app branch name if the repo has it, else its default branch) into a cache and
    # link it in. 28 Oct: the person's untracked copy was an old OpenCV 4.5.2 without OpenCVLoader.initLocal().
    pinned = {sm for _p, sm in links}
    gm = _sh(['git', 'show', f'{sha}:.gitmodules'], src, 60, check=False)
    for path_, url_ in re.findall(r'path\s*=\s*(\S+)\s*\n\s*url\s*=\s*(\S+)', gm):
        if path_ in pinned or os.path.exists(os.path.join(wt, path_, '.git')):
            continue
        name = re.sub(r'\.git$', '', url_.rstrip('/').split('/')[-1].split(':')[-1])
        hb = _sh(['git', 'ls-remote', '--heads', url_, branch], src, 120, check=False).split()
        mb = branch if hb else None
        cache = os.path.join(ROOT, '_modules', re.sub(r'[^A-Za-z0-9._-]', '_', f'{name}@{mb or "default"}'))
        if not os.path.isdir(os.path.join(cache, '.git')):
            shutil.rmtree(cache, ignore_errors=True)
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            r = subprocess.run(['git', 'clone', '-q', '--depth', '1'] + (['-b', mb] if mb else []) + [url_, cache],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode:
                log(f'full-app lab folder: could not clone {name} ({(r.stderr or "").strip()[:120]}); using your copy')
                shutil.rmtree(cache, ignore_errors=True)
                continue
        else:
            subprocess.run(['git', '-C', cache, 'pull', '-q', '--ff-only'], capture_output=True, text=True, timeout=900)
        d_ = os.path.join(wt, path_)
        if os.path.islink(d_) or (os.path.isdir(d_) and not os.listdir(d_)):
            os.unlink(d_) if os.path.islink(d_) else os.rmdir(d_)
        if os.path.isdir(d_):                          # files from an older run (a link inside): replace them
            shutil.rmtree(d_, ignore_errors=True)
        os.makedirs(os.path.dirname(d_), exist_ok=True)
        os.symlink(cache, d_)
        log(f'full-app lab folder: {path_} = {name} ({mb or "default branch"}) from its own repo')
    for rel in list(LINKED) + [x.strip() for x in str(((cfg or {}).get('full_app') or {}).get('linked') or '').split(',') if x.strip()]:
        s_, d_ = os.path.join(src, rel), os.path.join(wt, rel)
        if os.path.isdir(s_) and not os.path.lexists(d_):
            os.makedirs(os.path.dirname(d_), exist_ok=True)
            os.symlink(s_, d_)
            log(f'full-app lab folder: linked {rel} from your checkout (not in git)')
    # 29 Oct: the lab door (debug lab build only): a receiver that opens the app's own screens with missing/empty extras,
    # which adb cannot do for a non-exported activity. Its own variant source set: no file of the checkout is touched.
    try:
        door = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hooklib', 'fullapp_lab')
        dst = os.path.join(wt, 'android', 'app', 'src', 'productionInternalDebug')
        if os.path.isdir(door):
            for d_, _ds, fs_ in os.walk(door):
                for fn in fs_:
                    a_ = os.path.join(d_, fn)
                    b_ = os.path.join(dst, os.path.relpath(a_, door))
                    os.makedirs(os.path.dirname(b_), exist_ok=True)
                    if not os.path.exists(b_) or open(a_, 'rb').read() != open(b_, 'rb').read():
                        shutil.copyfile(a_, b_)
    except Exception as e:
        log(f'full-app lab folder: lab door not added ({str(e)[:120]})')
    for f in COPIED:
        if os.path.exists(os.path.join(src, f)) and not os.path.exists(os.path.join(wt, f)):
            os.makedirs(os.path.dirname(os.path.join(wt, f)) or wt, exist_ok=True)
            shutil.copy2(os.path.join(src, f), os.path.join(wt, f))
    return wt, branch, sha
