"""Is a lab-verified fix in the live release, and is the crash still happening there?

For a problem whose case has a fix verified on the lab phone (A/B), read the fix's patch and look for its added lines in
the code of the live release (the commit its newest build was made from, ns/source.py). Then:
  shipped   the fix is in the release and the release has no events of this problem  -> "Fixed in 1.25.2"
  regressed the fix is in the release but the release still has events               -> "Still crashing on 1.25.2"
  pending   the fix is not in the release yet                                         -> "Fix verified, not in 1.25.2 yet"
  unknown   the release commit or the patch could not be read
Read-only: git show <commit>:<path> only."""
import os
import re
import subprocess

from . import config

_files = {}
_strings = {}
SYMS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'symbols')


def _so_strings(vc):
    """Printable strings of a build's own libMYJNILIB26.so (symbol store), cached."""
    vc = str(vc or '')
    if vc not in _strings:
        p = os.path.join(SYMS, vc, 'libMYJNILIB26.so')
        try:
            _strings[vc] = subprocess.run(['strings', '-n', '10', p], capture_output=True, text=True, timeout=60,
                                          errors='replace').stdout if os.path.exists(p) else None
        except Exception:
            _strings[vc] = None
    return _strings[vc]


def guards(patch):
    """Log messages the fix ADDS (its guard says so when it runs): the first literal part, 14+ characters."""
    out = [re.split(r'%|\\\\', m)[0].strip() for m in re.findall(r'^\+.*?LOG[EIWDV]?\s*\(\s*"([^"]+)"', patch or '', re.M)]
    return [g for g in out if len(g) >= 14]


def _show(sha, path):
    k = (sha, path)
    if k not in _files:
        try:
            r = subprocess.run(['git', '--no-optional-locks', 'show', f'{sha}:{path}'], cwd=config.REPO, capture_output=True,
                               text=True, timeout=60, errors='replace')
            _files[k] = r.stdout if r.returncode == 0 else None
        except Exception:
            _files[k] = None
    return _files[k]


def _added(patch):
    """{path: [added lines worth checking]} from a unified diff."""
    out, cur = {}, None
    for ln in (patch or '').splitlines():
        if ln.startswith('+++ '):
            p = ln[4:].strip()
            cur = None if p == '/dev/null' else re.sub(r'^b/', '', p)
            continue
        if cur and ln.startswith('+') and not ln.startswith('+++'):
            t = ln[1:].strip()
            if len(t) >= 8 and not re.fullmatch(r'[{}();,\s]*', t) and not t.startswith(('//', '/*', '*')):
                out.setdefault(cur, []).append(t)
    return out


def patch_in(patch, sha):
    """True / False / None (partly or unreadable) and a short reason."""
    add = _added(patch)
    total = found = 0
    for path, lines in add.items():
        src = _show(sha, path)
        if src is None:
            continue
        flat = {re.sub(r'\s+', ' ', l.strip()) for l in src.splitlines()}
        for l in lines:
            total += 1
            found += re.sub(r'\s+', ' ', l) in flat
    if not total:
        return None, 'the patch has no lines to look for in that commit'
    r = found / total
    why = f'{found} of {total} lines the fix adds are in {sha[:10]}'
    return (True if r >= 0.8 else False if r <= 0.2 else None), why


def state(case_docs, per_build, live_codes, live_label, live_sha):
    """case_docs: the problem's case documents (its own and its parent issue). Returns a dict for the board, or None."""
    c = next((d for d in case_docs if d and (d.get('fixVerified') or str(d.get('status', '')).startswith('fix-verified')) and d.get('patch')), None)
    if not c:
        return None
    ev = sum(int((per_build.get(b) or {}).get('fb') or 0) + int((per_build.get(b) or {}).get('play') or 0) for b in live_codes)
    out = {'verified': True, 'release': live_label, 'releaseEvents': ev}
    if not live_sha:
        out.update(state='unknown', why='the commit of the live release is not known yet')
        return out
    inr, why = patch_in(c.get('patch'), live_sha)
    # binary evidence: the fix's guard message is in the release's .so but not in the build the crash came from
    base = max(((b, int(v.get('fb') or 0) + int(v.get('play') or 0)) for b, v in per_build.items() if b not in live_codes),
               key=lambda t: t[1], default=(None, 0))[0]
    g = guards(c.get('patch'))
    live_s, base_s = _so_strings(live_codes[0]) if live_codes else None, _so_strings(base) if base else None
    if g and live_s is not None:
        new_in_live = [x for x in g if x in live_s and (base_s is None or x not in base_s)]
        if new_in_live:
            inr, why = True, why + f'; the fix\'s guard message "{new_in_live[0][:60]}" is in the {live_label} library'
        elif not any(x in live_s for x in g):
            inr = False if inr is not True else inr
            why += f'; its guard message "{g[0][:60]}" is not in the {live_label} library'
    out['why'] = why
    if inr is True:
        out['state'] = 'regressed' if ev else 'shipped'
    elif inr is False:
        out['state'] = 'pending'
    else:
        out['state'] = 'unknown'
    return out
