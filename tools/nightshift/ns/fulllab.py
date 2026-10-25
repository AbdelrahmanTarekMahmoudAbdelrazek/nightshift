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
    _sh(['git', 'fetch', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/full/{safe}'], src, 900, check=False)
    sha = _sh(['git', 'rev-parse', f'refs/nightshift/full/{safe}'], src).strip()
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
    links = [(m.group(1), m.group(2)) for m in (re.match(r'160000 commit ([0-9a-f]{40})\t(.+)$', l)
             for l in _sh(['git', 'ls-tree', '-r', sha], src).splitlines()) if m]
    for pin, sm in links:                              # each module at the commit this branch pins
        d, s = os.path.join(wt, sm), os.path.join(src, sm)
        if not os.path.exists(os.path.join(s, '.git')):
            continue
        if done.get(sm) == pin and os.path.isdir(d) and os.listdir(d):
            _sh(['git', '-C', d, 'checkout', '-q', '-f', pin, '--', '.'], d, check=False)
            continue
        if _sh(['git', '-C', s, 'cat-file', '-t', pin], s, 60, check=False).strip() != 'commit':
            _sh(['git', '-C', s, 'fetch', '--no-tags', 'origin', pin], s, 900, check=False)
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
    if not os.path.lexists(dn):
        os.symlink(nm, dn)
    for f in COPIED:
        if os.path.exists(os.path.join(src, f)) and not os.path.exists(os.path.join(wt, f)):
            os.makedirs(os.path.dirname(os.path.join(wt, f)) or wt, exist_ok=True)
            shutil.copy2(os.path.join(src, f), os.path.join(wt, f))
    return wt, branch, sha
