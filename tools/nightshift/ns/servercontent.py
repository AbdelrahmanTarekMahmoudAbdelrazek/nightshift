"""Server content for a card review: the effects, frames, transitions... the app downloads and runs as they are
(shaders, webp images, item JSON). Night Shift fetches the items a card names, READ-ONLY (plain GETs to the app's own
public content API and its CDN, the same requests the app makes), and saves them outside the repo so the hunters and
judges can Read/Grep them and cite their lines like code (the line check verifies those quotes too).
Hosts are allow-listed; nothing is ever written to the server."""
import json
import os
import re
import struct
import urllib.parse
import urllib.request

ROOT = os.path.expanduser('~/.nightshift_server')
HOSTS = ('api-v2.myzesty.com', 'd2y0wswd79h3fh.cloudfront.net')
DEFAULT_ENDPOINTS = ['https://api-v2.myzesty.com/api/v2/resources/ve/effect?p=0', 'https://api-v2.myzesty.com/api/v2/resources/ve/transition?p=0']
WANT = re.compile(r'effect|frame|filter|transition|sticker|template|font|shader|thumbnail|preset|overlay|endpoint|upload|server|webp|asset', re.I)
COMMON = set('open close fill fit zoom blur fade slide spin shake glow light dark warm cool basic normal classic none original simple soft hard pop flash snap swipe push pull wipe split mirror flip rotate move drop rise up down left right in out on off black white red blue green gold color colour vintage film retro cinema cinematic love heart star line lines frame frames border'.split())
ROMAN = {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4', 'v': '5', 'vi': '6', 'l': '1', 'll': '2', 'lll': '3'}


def _ok(url):
    try:
        u = urllib.parse.urlparse(url)
        return u.scheme == 'https' and u.hostname in HOSTS
    except Exception:
        return False


def _get(url, limit=4_000_000, rng=None, timeout=40):
    if not _ok(url):
        raise ValueError(f'host not allowed: {url[:80]}')
    req = urllib.request.Request(url, headers={'User-Agent': 'NightShift/1.0 (read-only)', **({'Range': rng} if rng else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def webp_size(b):
    """(width, height) from the first bytes of a webp file, or None."""
    try:
        if b[:4] != b'RIFF' or b[8:12] != b'WEBP':
            return None
        ch = b[12:16]
        if ch == b'VP8X':
            return 1 + int.from_bytes(b[24:27], 'little'), 1 + int.from_bytes(b[27:30], 'little')
        if ch == b'VP8 ':
            w, h = struct.unpack('<HH', b[26:30])
            return w & 0x3fff, h & 0x3fff
        if ch == b'VP8L':
            v = int.from_bytes(b[21:25], 'little')
            return 1 + (v & 0x3fff), 1 + ((v >> 14) & 0x3fff)
    except Exception:
        return None
    return None


def strip(src, dst, n=8, width=150):
    """An animated webp/gif thumbnail as ONE image: up to n frames side by side, left to right (ffmpeg, else Pillow)."""
    import shutil
    import subprocess
    ff = shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), None)
    if ff:
        try:
            subprocess.run([ff, '-v', 'error', '-y', '-i', src, '-vf',
                            f'select=not(mod(n\\,2)),scale={width}:-2,tile={n}x1:padding=4:margin=4:color=white',
                            '-frames:v', '1', dst], capture_output=True, timeout=60)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                return dst
        except Exception:
            pass
    try:
        from PIL import Image, ImageSequence
        im = Image.open(src)
        fr = [f.convert('RGB') for f in ImageSequence.Iterator(im)]
        if not fr:
            return None
        step = max(1, len(fr) // n)
        fr = fr[::step][:n]
        h = int(fr[0].height * width / fr[0].width)
        out = Image.new('RGB', (len(fr) * (width + 4) + 4, h + 8), 'white')
        for i, f in enumerate(fr):
            out.paste(f.resize((width, h)), (4 + i * (width + 4), 4))
        out.save(dst, quality=85)
        return dst
    except Exception:
        return None


def _norm(s):
    s = re.sub(r'[^a-z0-9 ]', ' ', str(s).lower())
    return ' '.join(ROMAN.get(t, t) for t in s.split())


def card_text(doc):
    k = doc.get('card') or {}
    parts = [k.get('title', ''), k.get('description', '')] + [f"{x.get('title', '')} {x.get('expected', '')} {x.get('actual', '')}" for x in doc.get('issues') or []]
    parts += [str(c.get('text', '')) for c in (k.get('comments') or [])[-12:]]
    return '\n'.join(str(p) for p in parts if p)


def collect(doc, key, log=print, endpoints=None, max_items=8):
    """Returns (markdown for the models, folder) or ('', None) when the card names no server item."""
    text = card_text(doc)
    if not WANT.search(text):
        return '', None
    if isinstance(endpoints, str):
        endpoints = [e.strip() for e in endpoints.split(',') if e.strip()]
    elif isinstance(endpoints, dict):                  # tolerate the board's simple YAML reader
        endpoints = [f"{k.lstrip('- ').strip()}:{v}".strip() for k, v in endpoints.items()]
    eps = [e for e in (endpoints or DEFAULT_ENDPOINTS) if _ok(e)] or list(DEFAULT_ENDPOINTS)
    eps += [u.rstrip('.,)') for u in re.findall(r'https://api-v2\.myzesty\.com/[^\s"\'<>)]+', text) if u.rstrip('.,)') not in eps]
    items = []
    for ep in eps[:4]:
        try:
            d = json.loads(_get(ep, limit=20_000_000).decode('utf-8', 'replace'))
            res = d.get('result') if isinstance(d, dict) else d
            items += [dict(x, _ep=ep) for x in res or [] if isinstance(x, dict) and x.get('name')]
        except Exception as e:
            log(f'server content: {ep[:70]} not read ({str(e)[:100]})')
    if not items:
        return '', None
    nt = ' ' + _norm(text) + ' '
    cats = {_norm(x.get('category', '')) for x in items if x.get('category')}
    named_cats = {c for c in cats if c and (f' {c} ' in nt or f' {c.rstrip("s")} ' in nt)}

    def score(x):
        n = _norm(x['name'])
        if len(n) < 3 or f' {n} ' not in nt:
            return 0
        in_cat = _norm(x.get('category', '')) in named_cats
        exact = re.search(r'(?<![A-Za-z])' + re.escape(str(x['name'])) + r'(?![A-Za-z])', text) is not None
        common = n in COMMON
        if common and not in_cat:
            return 0                                   # "open", "fill", "zoom" in a sentence are not effect names
        return 3 * in_cat + 2 * exact + (0 if common else 1)
    ranked = sorted(((score(x), i, x) for i, x in enumerate(items)), key=lambda t: (-t[0], t[1]))
    hit = [x for sc_, _, x in ranked if sc_ > 0]
    if not hit:
        return '', None
    hit = hit[:max_items]
    folder = os.path.join(ROOT, re.sub(r'[^\w-]', '_', key))
    os.makedirs(folder, exist_ok=True)
    shaders, lines = {}, []
    for x in hit:
        f = x.get('files') or {}
        slug = re.sub(r'[^\w]+', '_', x['name']).strip('_') or 'item'
        sh = f.get('shader') or ''
        shp = ''
        if sh.startswith('http') and _ok(sh):
            if sh not in shaders:
                try:
                    body = _get(sh, limit=400_000).decode('utf-8', 'replace')
                    name = re.sub(r'[^\w.]+', '_', sh.rsplit('/', 1)[-1]) or 'shader'
                    shp = os.path.join(folder, 'server_' + (name if name.endswith(('.glsl', '.h', '.frag')) else name + '.glsl'))
                    open(shp, 'w', encoding='utf-8').write(body)
                    shaders[sh] = shp
                except Exception as e:
                    log(f'server content: shader of {x["name"]} not read ({str(e)[:80]})')
            shp = shaders.get(sh, '')
        elif sh.strip():                               # the shader text itself in the JSON
            shp = os.path.join(folder, f'server_{slug}_shader.glsl')
            open(shp, 'w', encoding='utf-8').write(sh)
        imgs = []
        for w in (f.get('webp') or [])[:3]:
            p = (w or {}).get('path') if isinstance(w, dict) else w
            if p and _ok(p):
                try:
                    sz = webp_size(_get(p, limit=64, rng='bytes=0-63'))
                except Exception:
                    sz = None
                imgs.append(f"{p.rsplit('/', 1)[-1]} " + (f"{sz[0]}x{sz[1]} ({'portrait' if sz[1] > sz[0] else 'landscape' if sz[0] > sz[1] else 'square'}, w/h {sz[0] / sz[1]:.2f})" if sz else 'size unknown'))
        share = sum(1 for y in items if (y.get('files') or {}).get('shader') == sh) if sh.startswith('http') else 1
        th = f.get('thumbnail') or ''
        th_strip = ''
        if th and _ok(th):                               # the thumbnail's animation as one image the models can open
            try:
                tp = os.path.join(folder, f'thumb_{slug}' + os.path.splitext(th.rsplit('/', 1)[-1])[1][:6])
                open(tp, 'wb').write(_get(th, limit=6_000_000))
                th_strip = strip(tp, os.path.join(folder, f'thumb_{slug}_frames.jpg')) or ''
            except Exception as e:
                log(f'server content: thumbnail of {x["name"]} not read ({str(e)[:80]})')
        th_peers = [y for y in items if th and (y.get('files') or {}).get('thumbnail') == th and y is not x]
        th_note = ''
        if th_peers:
            th_note = ('; the SAME thumbnail file ' + th.rsplit('/', 1)[-1] + ' is also used by '
                       + ', '.join(f"{y['name']} ({y.get('category', '')} {y.get('i_id', '')}, shader {str((y.get('files') or {}).get('shader', '')).rsplit('/', 1)[-1]})" for y in th_peers[:4]))
        meta = {k: x.get(k) for k in ('name', 'i_id', 'type', 'category', 'c_type', 'intensity', 'params', 'isVisible')}
        meta.update({'files': f, 'endpoint': x['_ep']})
        jp = os.path.join(folder, f'server_{slug}.json')
        json.dump(meta, open(jp, 'w'), indent=1)
        lines.append(f"- **{x['name']}** ({x.get('type', '')} {x.get('i_id', '')}, category {x.get('category', '')}, c_type {x.get('c_type')}, "
                     f"{'visible in the app' if x.get('isVisible', True) else 'HIDDEN in the app'}): "
                     f"item JSON `{jp}`" + (f"; shader `{shp}`" + (f" (the SAME shader file is used by {share} items)" if share > 1 else '') if shp else '; no shader')
                     + (f"; images: {'; '.join(imgs)}" if imgs else '')
                     + (f"; thumbnail {th.rsplit('/', 1)[-1]}" if th else '') + th_note
                     + (f"; thumbnail animation frames (open with Read, left to right): `{th_strip}`" if th_strip else ''))
    log(f'server content: {len(hit)} item(s) fetched read-only: {", ".join(x["name"] for x in hit)}')
    md = ("## Server content (downloaded read-only from the live content API for this card)\n"
          "The app downloads these files and runs them as they are; they are NOT in the checkout. Read/Grep them at the paths "
          "below and cite their lines like code (path:line, the code copied exactly). Compare them with the app's own shaders and "
          "the code that loads them. Where a thumbnail strip is listed, OPEN it with Read and compare the animation it shows "
          "with what the video's preview frames show (listed below when available).\n" + '\n'.join(lines) + '\n\n')
    return md, folder
