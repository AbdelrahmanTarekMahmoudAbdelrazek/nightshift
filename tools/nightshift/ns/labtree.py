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


def ensure(cfg, branch=None, log=print):
    """Create/refresh the lab folder for `branch` (default lab.base_branch) at its latest commit. -> (path, sha)."""
    branch = branch or (cfg.get('lab') or {}).get('base_branch') or 'HEAD'
    if branch == 'HEAD':
        sha = _sh(['git', 'rev-parse', 'HEAD']).strip()
    else:
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', branch)
        _sh(['git', 'fetch', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/lab/{safe}'], check=False)
        r = subprocess.run(['git', 'rev-parse', f'refs/nightshift/lab/{safe}'], cwd=config.REPO, capture_output=True, text=True)
        sha = r.stdout.strip() if r.returncode == 0 else _sh(['git', 'rev-parse', branch]).strip()
    wt = os.path.join(ROOT, re.sub(r'[^A-Za-z0-9._-]', '_', branch))
    if not os.path.isdir(os.path.join(wt, 'app')):
        os.makedirs(ROOT, exist_ok=True)
        _sh(['git', 'worktree', 'prune'], check=False)
        _sh(['git', '-c', 'core.autocrlf=false', 'worktree', 'add', '--detach', '--force', wt, sha])
        log(f'lab folder created: {wt} ({branch} @ {sha[:10]}); first build there is a full build')
    else:
        _sh(['git', '-C', wt, '-c', 'core.autocrlf=false', 'checkout', '-q', '--detach', '-f', sha], check=False)
    pristine(wt, sha)
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
        want = _sh(['git', '-C', src, 'rev-parse', 'HEAD']).strip()
        if done.get(sm) == want and os.path.isdir(d) and os.listdir(d):
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


def activate(cfg, branch=None, log=print):
    """Point config.LAB at the lab folder for this job. -> (path, sha) or (REPO, '') when off."""
    if not enabled(cfg):
        config.LAB = config.REPO
        return config.REPO, ''
    wt, sha = ensure(cfg, branch, log)
    config.LAB = wt
    return wt, sha


def deactivate():
    config.LAB = config.REPO
