"""Shared symbols through the team's private GitHub repo (25 Oct). Free, private, no Firebase Storage needed.

The board host keeps the symbol store (symbols/<versionCode>/: the Play library, the full debug symbols from the .aab,
meta.json). After each gathering it puts every build's store, zipped, in the repo's Releases as `symbols-<versionCode>`
(one release per build, files only, nothing is committed). A teammate's worker that meets a build it has no symbols
for downloads that zip once (`gh release download`) and keeps it; the board host is asked only when GitHub has
nothing (relay.symbolize). The board's Releases page lists every build: full / names only / missing, shared or not,
and Hide (a hidden build is not offered to teammates; the file stays on GitHub, nothing is deleted).

Needs the GitHub CLI signed in (`gh auth login`, setup.sh step 8) with access to the repo.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile

from . import config, symbolize

LIB = 'libMYJNILIB26.so'
_MISS = {}                                           # versionCode -> time of the last "not on GitHub" answer


def repo(cfg=None):
    """owner/name of the team's private kit repo: nightshift.yaml symbols.github_repo, else team_board.json 'github'."""
    cfg = cfg or config.load()
    r = str(((cfg.get('symbols') or {}).get('github_repo')) or '').strip()
    if r:
        return r
    for p in (os.path.join(config.REPO, 'tools/nightshift/team_board.json'),):
        try:
            return str(json.load(open(p)).get('github') or '').strip()
        except (OSError, ValueError):
            pass
    return ''


def gh_ok():
    t = getattr(gh_ok, 'at', 0)
    if time.time() - t < 600:
        return gh_ok.ok
    ok = bool(shutil.which('gh'))
    if ok:
        try:
            ok = subprocess.run(['gh', 'auth', 'status', '-h', 'github.com'], capture_output=True, text=True, timeout=30).returncode == 0
        except Exception:
            ok = False
    gh_ok.ok, gh_ok.at = ok, time.time()
    return ok


def _gh(args, timeout=600):
    return subprocess.run(['gh', *args], capture_output=True, text=True, timeout=timeout)


def _tag(vc):
    return f'symbols-{vc}'


def _info(vc):
    d = os.path.join(symbolize.STORE, str(vc))
    try:
        m = json.load(open(os.path.join(d, 'meta.json')))
    except (OSError, ValueError):
        m = {}
    return {'have': os.path.exists(os.path.join(d, LIB)), 'full': os.path.exists(os.path.join(d, LIB + '.dbg')),
            'version': m.get('version_name') or '', 'buildId': (m.get('build_id') or '')[:16],
            'functions': m.get('debug_functions') or m.get('functions') or 0, 'source': str(m.get('source') or '')[:120]}


# ------------------------------------------------------------------ board host: publish

def publish(vc, log=print, cfg=None):
    """Put one build's symbols on GitHub (new release, or the zip replaced when it gained file:line). -> 'shared'|'skip'|reason"""
    r, inf = repo(cfg), _info(vc)
    if not inf['have']:
        return 'no symbols here'
    if not r or not gh_ok():
        return 'GitHub CLI not signed in'
    name = f"{vc}{'-full' if inf['full'] else '-names'}.zip"
    v = _gh(['release', 'view', _tag(vc), '-R', r, '--json', 'assets'], 60)
    have = [a.get('name') for a in (json.loads(v.stdout or '{}').get('assets') or [])] if v.returncode == 0 else None
    if have and name in have:
        return 'skip'
    d = os.path.join(symbolize.STORE, str(vc))
    tmp = tempfile.mkdtemp(prefix='nssym')
    z = os.path.join(tmp, name)
    try:
        with zipfile.ZipFile(z, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in (LIB, LIB + '.dbg', 'meta.json'):
                if os.path.exists(os.path.join(d, f)):
                    zf.write(os.path.join(d, f), f)
            try:                                     # Play's names for this build's pcs (frames .dynsym cannot name)
                pm = symbolize.load_pcmap().get(inf['buildId']) or {}
                if pm:
                    zf.writestr('pcmap.json', json.dumps({inf['buildId']: pm}))
            except Exception:
                pass
        mb = os.path.getsize(z) / 1e6
        if have is None:
            res = _gh(['release', 'create', _tag(vc), z, '-R', r, '--title', f"Symbols {inf['version']} ({vc})",
                       '--notes', f"Night Shift symbols for build {vc} ({'function names + file:line' if inf['full'] else 'function names only'}). "
                                  'Downloaded by Night Shift on teammates\' computers. Not a release of the app.'], 900)
        else:
            res = _gh(['release', 'upload', _tag(vc), z, '-R', r], 900)
        if res.returncode:
            return (res.stderr or res.stdout).strip()[:200]
        log(f"symbols: {vc} shared on GitHub ({name}, {mb:.0f} MB)")
        return 'shared'
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def publish_all(db, codes, log=print, cfg=None):
    """Board host, after each gathering: share every build in scope and write config/symbols for the board."""
    from firebase_admin import firestore
    doc = db.collection('config').document('symbols')
    old = (doc.get().to_dict() or {}).get('builds') or {}
    builds = dict(old)
    for vc in [str(c) for c in codes]:
        inf = _info(vc)
        st = publish(vc, log, cfg) if inf['have'] else 'missing'
        prev = old.get(vc) or {}
        builds[vc] = {**prev, **inf, 'shared': st in ('shared', 'skip') or (prev.get('shared') and st != 'missing'),
                      'shareNote': '' if st in ('shared', 'skip') else st, 'hidden': bool(prev.get('hidden'))}
        if st not in ('shared', 'skip', 'missing') and not prev.get('shareNote'):
            log(f'symbols: {vc} not shared on GitHub: {st}')
    doc.set({'builds': builds, 'repo': repo(cfg), 'updatedAt': firestore.SERVER_TIMESTAMP})
    return builds


# ------------------------------------------------------------------ teammate: fetch once

def _hidden(vc):
    try:
        from firebase_admin import firestore
        b = ((firestore.client().collection('config').document('symbols').get().to_dict() or {}).get('builds') or {}).get(str(vc)) or {}
        return bool(b.get('hidden'))
    except Exception:
        return False


def fetch(vc, log=print):
    """Download one build's symbols from GitHub into the local store (once). -> True when the store has them now."""
    vc = str(vc or '')
    if not vc or os.path.exists(symbolize.store_path(vc, LIB) + '.dbg'):
        return False
    if time.time() - _MISS.get(vc, 0) < 600:
        return False
    r = repo()
    if not r or not gh_ok() or _hidden(vc):
        _MISS[vc] = time.time()
        return False
    tmp = tempfile.mkdtemp(prefix='nssym')
    try:
        res = _gh(['release', 'download', _tag(vc), '-R', r, '-p', '*.zip', '-D', tmp, '--clobber'], 600)
        zips = sorted((os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith('.zip')), key=lambda p: '-full' not in p)
        if res.returncode or not zips:
            _MISS[vc] = time.time()
            return False
        d = os.path.join(symbolize.STORE, vc)
        os.makedirs(d, exist_ok=True)
        with zipfile.ZipFile(zips[0]) as zf:
            for n in zf.namelist():
                if n in (LIB, LIB + '.dbg', 'meta.json'):
                    open(os.path.join(d, n), 'wb').write(zf.read(n))
                elif n == 'pcmap.json':
                    try:
                        symbolize.add_pcmap((b, pc, fn) for b, m in json.loads(zf.read(n)).items() for pc, fn in m.items())
                    except Exception:
                        pass
        log(f'symbols: build {vc} downloaded from the team\'s GitHub ({os.path.basename(zips[0])}); kept on this computer')
        return True
    except Exception:
        _MISS[vc] = time.time()
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
