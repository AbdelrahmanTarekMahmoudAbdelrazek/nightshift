"""Evidence images for card reviews: replay a downloaded GLSL shader (transition or effect) frame by frame next to the
item's own thumbnail, as ONE picture a developer (and the models) can open: row 1 = the thumbnail's frames, next rows =
the shader at chosen parameter values (e.g. "what the app passes now" vs "the value in the item JSON").

No GPU code of our own: a headless Chrome/Chromium draws the shader with WebGL (SwiftShader, so every Mac gives the same
pixels) and hands back one PNG. Uniform names follow the engine (Transition.cpp): frame1, frame2, transition_progress,
textureSize, webp_frame, webp_ratio, and every item param as uniform_<name>. If no Chrome is found the stage is skipped."""
import base64
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

CHROMES = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
           '/Applications/Chromium.app/Contents/MacOS/Chromium',
           '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary']


def chrome():
    for c in CHROMES:
        if os.path.exists(c):
            return c
    for n in ('google-chrome', 'chromium', 'chromium-browser', 'chrome'):
        p = shutil.which(n)
        if p:
            return p
    hits = sorted(glob.glob('/opt/pw-browsers/chromium-*/chrome-linux/chrome')
                  + glob.glob(os.path.expanduser('~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*'))
                  + glob.glob(os.path.expanduser('~/.cache/ms-playwright/chromium-*/chrome-linux/chrome')))
    return hits[-1] if hits else None


def glsl_from(text):
    """A server shader file is either plain GLSL or a C header with the GLSL as string literals: return the GLSL."""
    t = text or ''
    if 'void main' in t and '"' in t and re.search(r'"\s*\n\s*"', t):
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', t)
        body = ''.join(parts)
        body = body.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
        if 'void main' in body:
            t = body
    if 'precision' not in t:
        t = 'precision mediump float;\n' + t
    return t


def _uri(path):
    """A local image file as a data: URI (raw bytes; Chrome decodes every frame of an animated webp/gif itself)."""
    ext = os.path.splitext(path)[1].lower().lstrip('.') or 'webp'
    mime = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif'}.get(ext, 'image/webp')
    return f'data:{mime};base64,' + base64.b64encode(open(path, 'rb').read()).decode()


PAGE = r"""<!doctype html><html><body style="margin:0;background:#222"><script>
const SPEC = __SPEC__;
const VS = 'attribute vec2 pos; varying vec2 tc; void main(){ tc = pos*0.5+0.5; gl_Position = vec4(pos,0.0,1.0); }';
function load(u){ return new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; }); }
async function frames(u){            // every frame of an animated webp/gif (WebCodecs), else the one still image
  try {
    if (typeof ImageDecoder !== 'undefined') {
      const type = u.slice(5, u.indexOf(';')), data = await (await fetch(u)).arrayBuffer();
      const dec = new ImageDecoder({data, type}); await dec.tracks.ready;
      const n = dec.tracks.selectedTrack.frameCount, out = [];
      for (let i = 0; i < Math.min(n, 80); i++) { const r = await dec.decode({frameIndex: i}); out.push(await createImageBitmap(r.image)); r.image.close(); }
      if (out.length) return out;
    }
  } catch (e) {}
  return [await createImageBitmap(await load(u))];
}
// WebGL ignores UNPACK_FLIP_Y for ImageBitmaps: flip them once so tc (0,0) is the image's bottom-left, as in the app
const up = b => createImageBitmap(b, {imageOrientation: 'flipY'});
(async () => {
  const W = SPEC.cell[0], H = SPEC.cell[1], L = SPEC.label, G = 3, cols = SPEC.cols;
  const out = document.createElement('canvas');
  out.width = L + cols * (W + G) + G; out.height = SPEC.rows.length * (H + G) + G + (SPEC.title ? 26 : 0);
  const c2 = out.getContext('2d'); c2.fillStyle = '#222'; c2.fillRect(0, 0, out.width, out.height);
  const top = SPEC.title ? 26 : 0;
  if (SPEC.title) { c2.fillStyle = '#fff'; c2.font = 'bold 14px sans-serif'; c2.fillText(SPEC.title, 8, 18); }
  const glc = document.createElement('canvas'); glc.width = W; glc.height = H;
  const gl = glc.getContext('webgl', {preserveDrawingBuffer: true, premultipliedAlpha: false});
  const errors = [];
  if (!gl) { document.body.innerText = JSON.stringify({error: 'no WebGL'}); return; }
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
  function tex(img){ const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img); return t; }
  function prog(fs){
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.bindAttribLocation(p, 0, 'pos'); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }
  function setU(p, name, v){
    const l = gl.getUniformLocation(p, name); if (l === null) return false;
    const a = Array.isArray(v) ? v : [v];
    [gl.uniform1fv, gl.uniform2fv, gl.uniform3fv, gl.uniform4fv][Math.min(a.length, 4) - 1].call(gl, l, new Float32Array(a.slice(0, 4)));
    return true;
  }
  for (let r = 0; r < SPEC.rows.length; r++) {
    const row = SPEC.rows[r], y = top + G + r * (H + G);
    c2.fillStyle = row.color || '#ddd'; c2.font = '12px sans-serif';
    String(row.label).split('\n').forEach((ln, k) => c2.fillText(ln.slice(0, 34), 6, y + 16 + k * 15));
    if (row.anim) {
      const imgs = await frames(row.anim);
      c2.fillText(String(row.label).split('\n').length > 1 ? '' : '(' + imgs.length + ' frames)', 6, y + 31);
      for (let i = 0; i < cols; i++) {
        const im = imgs[Math.round(i * (imgs.length - 1) / Math.max(1, cols - 1))];
        if (im) c2.drawImage(im, L + G + i * (W + G), y, W, H);
      }
      continue;
    }
    try {
      const p = prog(row.shader); gl.useProgram(p);
      gl.enableVertexAttribArray(0); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      const src = await frames(row.src), A = await up(src[0]), B = await up(src[src.length - 1]);
      const webp = await Promise.all([].concat(...(row.webp ? await Promise.all(row.webp.map(frames)) : [])).map(up));
      const tA = tex(A), tB = tex(B), tW = webp.map(tex);
      for (let i = 0; i < cols; i++) {
        const pr = i / Math.max(1, cols - 1);
        gl.viewport(0, 0, W, H); gl.clearColor(0, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
        gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tA); gl.uniform1i(gl.getUniformLocation(p, 'frame1'), 0);
        gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, tB); gl.uniform1i(gl.getUniformLocation(p, 'frame2'), 1);
        if (tW.length) { gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, tW[Math.min(tW.length - 1, Math.floor(pr * tW.length))]);
          gl.uniform1i(gl.getUniformLocation(p, 'webp_frame'), 2); setU(p, 'webp_ratio', [webp[0].width, webp[0].height]); }
        setU(p, 'transition_progress', pr); setU(p, 'progress', pr);
        setU(p, 'textureSize', [W, H]);
        for (const [k, v] of Object.entries(row.params || {})) { setU(p, 'uniform_' + k, v) || setU(p, k, v); }
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        c2.drawImage(glc, L + G + i * (W + G), y, W, H);
      }
    } catch (e) {
      errors.push({row: row.label, error: String(e.message || e).slice(0, 400)});
      c2.fillStyle = '#e55'; c2.fillText('shader did not compile: ' + String(e.message || e).slice(0, 80), L + 8, y + H / 2);
    }
  }
  document.body.innerText = JSON.stringify({png: out.toDataURL('image/png'), errors});
})().catch(e => { document.body.innerText = JSON.stringify({error: String(e)}); });
</script></body></html>"""


def _run_page(exe, page, profile, timeout, swift=True):
    """Open the page in headless Chrome over its DevTools pipe (stdlib only) and wait until the page has written its
    answer into <body>. Returns that text ('' on timeout)."""
    import time
    r3, w3 = os.pipe()                                   # we write -> Chrome reads fd 3
    r4, w4 = os.pipe()                                   # Chrome writes fd 4 -> we read
    cmd = [exe, '--headless=new', '--no-sandbox', '--disable-gpu-sandbox', '--ignore-gpu-blocklist', '--no-first-run',
           '--no-default-browser-check', f'--user-data-dir={profile}', '--remote-debugging-pipe', 'about:blank']
    if swift:                                            # software WebGL: the same pixels on every machine
        cmd[1:1] = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']

    def fds():
        os.dup2(r3, 3)
        os.dup2(w4, 4)
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            pass_fds=(3, 4), preexec_fn=fds)
    os.close(r3)
    os.close(w4)
    out, buf, seq = os.fdopen(w3, 'wb', buffering=0), b'', [0]

    def send(method, params=None, session=None):
        seq[0] += 1
        msg = {'id': seq[0], 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
        out.write(json.dumps(msg).encode() + b'\0')
        return seq[0]

    def wait(mid, until):
        nonlocal buf
        while time.time() < until:
            while b'\0' in buf:
                raw, buf = buf.split(b'\0', 1)
                m = json.loads(raw)
                if m.get('id') == mid:
                    return m.get('result') or {}
            chunk = os.read(r4, 1 << 20)
            if not chunk:
                return None
            buf += chunk
        return None
    until = time.time() + timeout
    try:
        res = wait(send('Target.createTarget', {'url': 'file://' + page}), until) or {}
        sess = (wait(send('Target.attachToTarget', {'targetId': res.get('targetId'), 'flatten': True}), until) or {}).get('sessionId')
        while sess and time.time() < until:
            r = wait(send('Runtime.evaluate', {'expression': 'document.body ? document.body.innerText : ""', 'returnByValue': True}, sess), until) or {}
            txt = ((r.get('result') or {}).get('value')) or ''
            if txt.startswith('{"'):
                return txt
            time.sleep(0.4)
        return ''
    finally:
        try:
            send('Browser.close')
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        os.close(r4)
        out.close()


def render(rows, out_png, title='', cols=10, cell=(96, 96), label=170, log=print, timeout=90):
    """rows: [{'label', 'anim': image path} | {'label', 'shader': glsl, 'params': {k: [floats]}, 'src': the
    thumbnail path (its first/last frame are clip A/B), 'webp': [overlay paths]}]. Writes out_png; returns
    (path or None, [shader errors])."""
    exe = chrome()
    if not exe:
        log('evidence replay skipped: no Chrome/Chromium found on this Mac')
        return None, []
    spec_rows = []
    for r in rows:
        x = {'label': r.get('label', ''), 'color': r.get('color')}
        if r.get('anim'):
            x['anim'] = _uri(r['anim'])
        else:
            x.update({'shader': glsl_from(r['shader']), 'params': r.get('params') or {}, 'src': _uri(r['src']),
                      'webp': [_uri(w) for w in (r.get('webp') or [])][:3] or None})
        spec_rows.append(x)
    spec = {'rows': spec_rows, 'cols': cols, 'cell': list(cell), 'label': label, 'title': title}
    d = tempfile.mkdtemp(prefix='ns_replay_')
    try:
        page = os.path.join(d, 'replay.html')
        open(page, 'w').write(PAGE.replace('__SPEC__', json.dumps(spec)))
        body = _run_page(exe, page, os.path.join(d, 'profile'), timeout)
        if 'no WebGL' in (body or '') or not body:       # this Chrome has no software WebGL: use the GPU
            body = _run_page(exe, page, os.path.join(d, 'profile2'), timeout, swift=False)
        m = re.search(r'\{"(png|error)".*\}', body or '', re.S)
        if not m:
            log(f'evidence replay: Chrome gave no picture ({(body or "no answer")[-160:]})')
            return None, []
        o = json.loads(m.group(0))
        if o.get('error'):
            log(f"evidence replay failed: {o['error'][:200]}")
            return None, []
        open(out_png, 'wb').write(base64.b64decode(o['png'].split(',', 1)[1]))
        for e in o.get('errors') or []:
            log(f"evidence replay: {e['row']}: {e['error'][:160]}")
        return out_png, o.get('errors') or []
    except Exception as e:
        log(f'evidence replay failed ({str(e)[:160]})')
        return None, []
    finally:
        shutil.rmtree(d, ignore_errors=True)


def item_rows(thumb_path, shader_text, variants, webp_paths=(), cols=10):
    """The standard evidence for one server item: its thumbnail frames, then the shader once per variant
    ({'label', 'params'}), drawn on the thumbnail's own first and last frame (clip A and clip B)."""
    if not thumb_path or not os.path.exists(thumb_path) or not shader_text:
        return []
    rows = [{'label': 'Thumbnail', 'anim': thumb_path, 'color': '#9cf'}]
    for v in variants:
        rows.append({'label': v.get('label', ''), 'shader': shader_text, 'params': v.get('params') or {},
                     'src': thumb_path, 'webp': list(webp_paths or []), 'color': v.get('color')})
    return rows
