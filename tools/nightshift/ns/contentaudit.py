"""Deeper checks on the server content a card names (no AI, read-only GETs/HEADs to the allow-listed hosts):

1. history  - when each file the item uses was uploaded (CDN Last-Modified), whether the thumbnail is byte-identical to
              a file of ANOTHER item or folder (SHA-256), whether it was uploaded on a different day from the rest of its
              folder, and whether the item points into another category's folder. This is what tells "the content is
              wrong" apart from "the content was overwritten / mixed up on <date>".
2. blast    - for every param the named items carry, how many of ALL live items carry it too: the size of what a
              fix that changes how that param is read would touch.
3. index    - every live item as one JSON line (server_all_items.jsonl) the models can Grep for their own checks.
4. evidence - one picture per item with a shader: its thumbnail frames next to the shader replayed at the item's JSON
              params (shaderreplay.py); the card review adds rows (e.g. the value the app really passes) later."""
import collections
import hashlib
import json
import os
import re
import urllib.request

try:
    from . import shaderreplay
except ImportError:                                       # run as a plain module in tests
    import shaderreplay  # noqa: E402


def _folder(url):
    return url.rsplit('/', 1)[0] if '/' in url else ''


def _day(lm):
    """'Wed, 29 Jan 2025 10:11:12 GMT' -> '2025-01-29' (or '' when unknown)."""
    m = re.search(r'(\d{1,2}) (\w{3}) (\d{4})', lm or '')
    if not m:
        return ''
    mon = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split().index(m.group(2)) + 1
    return f'{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}'


def head(url, ok, timeout=20):
    """{'modified': 'YYYY-MM-DD', 'raw': Last-Modified, 'etag', 'size'} for an allow-listed URL, {} on any error."""
    if not ok(url):
        return {}
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'NightShift/1.0 (read-only)'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            h = r.headers
            return {'modified': _day(h.get('Last-Modified')), 'raw': h.get('Last-Modified') or '',
                    'etag': (h.get('ETag') or '').strip('"'), 'size': int(h.get('Content-Length') or 0)}
    except Exception:
        return {}


def history(items, hit, thumbs, get, ok, headf=None, log=print, peers_cap=12, twins_cap=14):
    """Lines (markdown bullets) about where each named item's files came from. thumbs = {item name: local thumbnail
    path} for the files already downloaded."""
    headf = headf or (lambda u: head(u, ok))
    out, cache_h, cache_sha = [], {}, {}

    def H(u):
        if u not in cache_h:
            cache_h[u] = headf(u) or {}
        return cache_h[u]

    def SHA(u, local=None):
        if u not in cache_sha:
            try:
                b = open(local, 'rb').read() if local and os.path.exists(local) else get(u, limit=8_000_000)
                cache_sha[u] = hashlib.sha256(b).hexdigest()
            except Exception:
                cache_sha[u] = ''
        return cache_sha[u]

    th_of = lambda y: str((y.get('files') or {}).get('thumbnail') or '')
    by_cat = collections.defaultdict(list)            # a category per content list: "Split" exists for effects AND transitions
    for y in items:
        if th_of(y) and ok(th_of(y)):
            by_cat[(y.get('category', ''), y.get('_ep'))].append(y)
    for x in hit:
        f = x.get('files') or {}
        th, sh = th_of(x), str(f.get('shader') or '')
        notes = []
        for kind, u in (('thumbnail', th), ('shader', sh)):
            if u.startswith('http') and ok(u):
                h = H(u)
                if h.get('modified'):
                    notes.append(f"{kind} `{u.rsplit('/', 1)[-1]}` uploaded {h['modified']} ({h.get('size', 0)} bytes)")
        if th and ok(th):
            mine = SHA(th, thumbs.get(x['name']))
            fold = _folder(th)
            # 1. byte-identical twins: the same file name in every other thumbnail folder (also files no item uses any
            #    more, e.g. a category's own copy that was replaced), and the thumbnails of items with the same name
            base = th.rsplit('/', 1)[-1]
            users = collections.defaultdict(list)
            for y in items:
                users[th_of(y)].append(y)
            near = lambda d: -len(os.path.commonprefix([d.split('/'), fold.split('/')]))   # sibling folders first
            folders = sorted({_folder(th_of(y)) for y in items if th_of(y)} - {fold}, key=lambda d: (near(d), d))
            cand = [d + '/' + base for d in folders]
            cand += [th_of(y) for y in items if y is not x and th_of(y) and th_of(y) != th and _norm(y.get('name')) == _norm(x.get('name'))]
            done = set()
            for u in cand:
                if u in done or len(done) >= twins_cap:
                    continue
                done.add(u)
                if u not in users and not H(u).get('size'):
                    continue                                   # no such file in that folder
                if mine and SHA(u) == mine:
                    hy = H(u)
                    who = ', '.join(f"{y['name']} ({y.get('category', '')} {y.get('i_id', '')})" for y in users.get(u, [])[:3])
                    notes.append(f"the thumbnail is BYTE-IDENTICAL (SHA-256 {mine[:12]}) to `{_short(u)}`"
                                 + (f", uploaded {hy['modified']}" if hy.get('modified') else '')
                                 + (f", used by {who}" if who else ', a file no live item points to'))
            # 2. uploaded on another day than the rest of its folder
            peers = [th_of(y) for y in items if th_of(y) != th and _folder(th_of(y)) == fold][:peers_cap]
            days = collections.Counter(H(u).get('modified') for u in peers if H(u).get('modified'))
            me = H(th).get('modified')
            if days and me:
                top, n = days.most_common(1)[0]
                if me != top and n >= max(2, len(peers) // 2):
                    notes.append(f"UPLOAD-DATE OUTLIER: {n} of {sum(days.values())} other thumbnails in `{_short(fold)}/` were "
                                 f"uploaded {top}; this one {me} (re-uploaded or replaced later)")
            # 3. points into another category's folder
            mates = by_cat.get((x.get('category', ''), x.get('_ep')), [])
            cat_folders = collections.Counter(_folder(th_of(y)) for y in mates)
            if cat_folders and len(mates) >= 3:
                main, n = cat_folders.most_common(1)[0]
                if fold != main and n >= 2:
                    owners = sorted({y.get('category', '') for y in items if _folder(th_of(y)) == fold and y.get('category') != x.get('category')
                             and y.get('_ep') == x.get('_ep')})
                    notes.append(f"FOLDER MISMATCH: {n} of {sum(cat_folders.values())} {x.get('category', '')} items keep their "
                                 f"thumbnails in `{_short(main)}/`, this one points into `{_short(fold)}/`"
                                 + (f" (the folder of {', '.join(owners[:3])})" if owners else ''))
        if notes:
            out.append(f"- **{x['name']}** ({x.get('category', '')} {x.get('i_id', '')}): " + '; '.join(notes))
    return out


def blast(items, hit, cap_names=8):
    """For each param key a named item carries: how many live items carry it (and which)."""
    out, seen = [], set()
    total = len(items)
    for x in hit:
        for p in _params(x):
            if p in seen:
                continue
            seen.add(p)
            have = [y for y in items if p in _params(y)]
            names = ', '.join(f"{y['name']} ({y.get('category', '')} {y.get('i_id', '')})" for y in have[:cap_names])
            out.append(f"- param `{p}`: {len(have)} of {total} live items carry it"
                       + (f": {names}" + (' ...' if len(have) > cap_names else '') if have else ''))
    tops = collections.Counter(k for y in items for k in ('intensity', 'duration', 'speed') if y.get(k) not in (None, ''))
    if tops:
        out.append('- top-level fields across all live items: ' + ', '.join(f'`{k}` on {n}' for k, n in tops.most_common()))
    return out


def index(items, folder):
    p = os.path.join(folder, 'server_all_items.jsonl')
    with open(p, 'w') as fh:
        for y in items:
            f = y.get('files') or {}
            fh.write(json.dumps({'name': y.get('name'), 'i_id': y.get('i_id'), 'category': y.get('category'),
                                 'c_type': y.get('c_type'), 'isVisible': y.get('isVisible', True), 'intensity': y.get('intensity'),
                                 'params': y.get('params'), 'thumbnail': f.get('thumbnail'), 'shader': f.get('shader'),
                                 'webp': [(w or {}).get('path') if isinstance(w, dict) else w for w in f.get('webp') or []],
                                 'endpoint': y.get('_ep')}, ensure_ascii=False) + '\n')
    return p


def json_params(x):
    """The item's own shader params as {name: [floats]} (the server's list of {k, v} or a dict)."""
    out = {}
    ps = x.get('params')
    if isinstance(ps, dict):
        ps = [{'k': k, 'v': v} for k, v in ps.items()]
    for p in ps or []:
        if not isinstance(p, dict):
            continue
        k = p.get('k') or p.get('key') or p.get('name')
        v = p.get('v', p.get('value'))
        if not k:
            continue
        vals = v if isinstance(v, list) else [v]
        try:
            out[str(k)] = [float(z) for z in vals][:4]
        except (TypeError, ValueError):
            continue
    return out


def evidence(spec, folder, log=print, extra=None):
    """spec: {'name', 'slug', 'thumb', 'shader', 'webp': [paths], 'params'}. extra: more rows [{'label', 'params'}].
    Returns the PNG path or None."""
    if not spec.get('thumb') or not spec.get('shader') or not os.path.exists(spec['thumb']):
        return None
    text = open(spec['shader'], encoding='utf-8', errors='replace').read()
    if 'void main' not in text:                       # not shader code (e.g. a URL the app resolves itself)
        log(f"evidence replay: {spec.get('name')}: the shader file holds no GLSL; skipped")
        return None
    variants = list(extra or [])
    if not any(v.get('label', '').lower().startswith('item json') for v in variants):
        variants.append({'label': 'Item JSON params\n' + (_pstr(spec.get('params')) or '(none)'), 'params': spec.get('params') or {},
                         'color': '#8f8'})
    rows = shaderreplay.item_rows(spec['thumb'], text, variants, spec.get('webp') or [])
    if not rows:
        return None
    out = os.path.join(folder, f"evidence_{spec['slug']}.png")
    png, _ = shaderreplay.render(rows, out, title=f"{spec['name']}: thumbnail vs the server shader replayed", log=log)
    return png


def _pstr(p):
    return ', '.join(f"{k} {'/'.join(f'{v:g}' for v in vs)}" for k, vs in (p or {}).items())


def _params(x):
    ps = x.get('params')
    if isinstance(ps, dict):
        return set(ps)
    return {str(p.get('k') or p.get('key') or p.get('name')) for p in ps or [] if isinstance(p, dict) and (p.get('k') or p.get('key') or p.get('name'))}


def _short(u):
    return re.sub(r'^https://[^/]+/resources/files/', '', u)


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s or '').lower())
