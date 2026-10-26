"""Bitbucket addresses for git that never ask for a password (26 Oct).

Before, Night Shift took the address from the person's checkout ("origin", e.g. https://Khairy98@bitbucket.org/...)
and relied on git's url.insteadOf rewrites to swap it for SSH or the token. On one teammate's Mac those rewrites did not
apply, and every fetch stopped at "could not read Password for 'https://Khairy98@bitbucket.org'". Now every git command
that reaches Bitbucket gets an explicit address built here:
  - SSH (git@bitbucket.org:<workspace>/<repo>.git) when this computer's SSH key is accepted by Bitbucket, else
  - HTTPS with the person's own API token (~/.config/nightshift/bitbucket.json) through a small askpass script.
The person's own remotes and git settings are never changed.
"""
import json
import os
import re
import subprocess
import time

ASKPASS = os.path.expanduser('~/.config/nightshift/git-askpass.sh')
TOKEN = os.path.expanduser('~/.config/nightshift/bitbucket.json')
_STATE = {}


def _workspace():
    try:
        return json.load(open(TOKEN)).get('workspace') or 'mitrotek'
    except Exception:
        pass
    try:
        from . import config
        u = subprocess.run(['git', '-C', config.REPO, 'config', '--get', 'remote.origin.url'], capture_output=True,
                           text=True, timeout=10).stdout.strip()
        m = re.search(r'bitbucket\.org[:/]([^/]+)/', u)
        if m:
            return m.group(1)
    except Exception:
        pass
    return 'mitrotek'


def ssh_ok():
    if time.time() - _STATE.get('ssh_at', 0) < 600:
        return _STATE['ssh']
    try:
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=10',
                            '-T', 'git@bitbucket.org'], capture_output=True, text=True, timeout=20)
        ok = 'authenticated' in (r.stdout + r.stderr).lower()
    except Exception:
        ok = False
    _STATE.update(ssh=ok, ssh_at=time.time())
    return ok


def _token_env():
    """GIT_ASKPASS answers with the person's own token; no keychain, no prompt."""
    if not os.path.exists(ASKPASS):
        os.makedirs(os.path.dirname(ASKPASS), exist_ok=True)
        with open(ASKPASS, 'w') as fh:
            fh.write('#!/bin/sh\n# Night Shift: answers git with the Bitbucket API token (no keychain, no prompt)\n'
                     'case "$1" in *sername*) echo x-bitbucket-api-token-auth;;\n'
                     ' *) python3 -c \'import json,os;print(json.load(open(os.path.expanduser("~/.config/nightshift/bitbucket.json")))["token"])\';; esac\n')
        os.chmod(ASKPASS, 0o700)
    os.environ['GIT_ASKPASS'] = ASKPASS


ISOLATED = os.path.expanduser('~/.config/nightshift/gitconfig')


def isolate():
    """Night Shift's own git commands use a copy of the person's global git config WITHOUT url.*.insteadOf rules and
    credential helpers (26 Oct: Khairy's ~/.gitconfig rewrote every git@bitbucket.org: address to
    https://Khairy98@bitbucket.org/, so git asked for a password whatever address Night Shift gave it). The person's own
    ~/.gitconfig is never changed; this only applies inside Night Shift's worker."""
    if os.environ.get('GIT_CONFIG_GLOBAL') == ISOLATED:
        return
    try:
        lines = subprocess.run(['git', 'config', '--global', '--list'], capture_output=True, text=True, timeout=10).stdout.splitlines()
    except Exception:
        lines = []
    keep = [l for l in lines if '=' in l and not l.lower().startswith(('url.', 'credential.', 'include.', 'includeif.'))]
    os.makedirs(os.path.dirname(ISOLATED), exist_ok=True)
    out = []
    for l in keep:
        k, v = l.split('=', 1)
        sec, _, name = k.rpartition('.')
        if '.' in sec:                                   # section.subsection.key
            s1, _, sub = sec.partition('.')
            out.append(f'[{s1} "{sub}"]\n\t{name} = {v}')
        else:
            out.append(f'[{sec}]\n\t{name} = {v}')
    with open(ISOLATED, 'w') as fh:
        fh.write('# Night Shift: your global git settings minus url rewrites and credential helpers (made automatically)\n'
                 + '\n'.join(out) + '\n')
    os.environ['GIT_CONFIG_GLOBAL'] = ISOLATED
    os.environ['GIT_CONFIG_NOSYSTEM'] = '1'             # the system config adds the macOS keychain helper


def rewrites():
    """Address-rewrite rules in the person's own git config (for the log)."""
    try:
        r = subprocess.run(['git', 'config', '--global', '--get-regexp', r'^url\..*\.insteadof$'], capture_output=True, text=True,
                           timeout=10, env={k: v for k, v in os.environ.items() if k not in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')})
        return [l for l in r.stdout.splitlines() if 'bitbucket' in l.lower()]
    except Exception:
        return []


def base():
    """'git@bitbucket.org:<ws>/' or 'https://x-bitbucket-api-token-auth@bitbucket.org/<ws>/'."""
    isolate()
    os.environ['GIT_TERMINAL_PROMPT'] = '0'
    ws = _workspace()
    if ssh_ok():
        return f'git@bitbucket.org:{ws}/'
    if os.path.exists(TOKEN):
        _token_env()
        return f'https://x-bitbucket-api-token-auth@bitbucket.org/{ws}/'
    raise RuntimeError('git cannot reach Bitbucket: add your SSH key or your own Bitbucket token (run ./setup.sh)')


def url(repo):
    return base() + repo + '.git'
