#!/usr/bin/env python3
"""Connect this computer to the team board without passing files around (run by setup.sh).

1. makes a one-time code and listens on 127.0.0.1 (this computer only);
2. opens the board's "Connect this computer" page in the browser; you sign in with your company email;
3. the board host's worker answers with the board settings + the worker key, readable only by you;
4. the page hands them to this helper (or, if the browser blocks that, downloads nightshift-connect-<code>.json,
   which this helper picks up from Downloads by itself);
5. the key is saved to ~/.config/nightshift/service-account.json (only you can read it) and the board settings are
   printed as shell lines for setup.sh.
"""
import argparse, http.server, json, os, secrets, shutil, socketserver, subprocess, sys, threading, time, urllib.parse

CONF = os.path.expanduser('~/.config/nightshift')
HERE = os.path.dirname(os.path.abspath(__file__))


def team_board():
    p = os.path.join(HERE, 'team_board.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def open_url(url):
    """The default browser on macOS, Linux, or Windows when running inside WSL2."""
    wsl = 'microsoft' in open('/proc/version').read().lower() if os.path.exists('/proc/version') else False
    for cmd in ((['open', url],) if sys.platform == 'darwin' else
                (['wslview', url], ['cmd.exe', '/c', 'start', '', url.replace('&', '^&')], ['powershell.exe', '-NoProfile', 'Start-Process', url]) if wsl else
                (['xdg-open', url],)):
        cmd = cmd if isinstance(cmd, list) else cmd
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                pass
    return False


def downloads_dirs():
    dirs = [os.path.expanduser('~/Downloads')]
    if os.path.exists('/proc/version') and 'microsoft' in open('/proc/version').read().lower():
        try:
            up = subprocess.run(['cmd.exe', '/c', 'echo %USERPROFILE%'], capture_output=True, text=True, timeout=10).stdout.strip()
            wp = subprocess.run(['wslpath', up], capture_output=True, text=True, timeout=10).stdout.strip()
            if wp:
                dirs.append(os.path.join(wp, 'Downloads'))
        except Exception:
            pass
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', help='board address (default: the team board of this kit)')
    ap.add_argument('--timeout', type=int, default=900)
    a = ap.parse_args()
    tb = team_board()
    base = (a.url or tb.get('url') or '').rstrip('/')
    if not base:
        sys.exit('no team board address (team_board.json missing): ask the board owner')
    code = secrets.token_hex(6)
    got = {}
    origin = base

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _cors(self):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'content-type')
            self.send_header('Access-Control-Allow-Private-Network', 'true')

        def do_OPTIONS(self):
            self.send_response(204); self._cors(); self.end_headers()

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('content-length') or 0)) or b'{}')
                ok = body.get('code') == code and body.get('serviceAccount') and body.get('board')
            except Exception:
                ok = False
            self.send_response(200 if ok else 400); self._cors(); self.end_headers()
            self.wfile.write(b'ok' if ok else b'no')
            if ok:
                got.update(body)

    srv = socketserver.TCPServer(('127.0.0.1', 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"{base}/connect.html?code={code}&port={port}"
    print(f"    Opening {url}", file=sys.stderr)
    print("    In the browser: sign in with your company email (if asked), then wait a few seconds.", file=sys.stderr)
    if not open_url(url):
        print("    (could not open a browser: open that address yourself, on THIS computer)", file=sys.stderr)
    t0, dl = time.time(), downloads_dirs()
    while not got and time.time() - t0 < a.timeout:
        for d in dl:                                   # fallback: the page downloaded the connection file instead
            f = os.path.join(d, f'nightshift-connect-{code}.json')
            if os.path.exists(f):
                try:
                    body = json.load(open(f))
                    if body.get('code') == code:
                        got.update(body)
                except ValueError:
                    pass
                try:
                    os.remove(f)                       # contains the key: never leave it in Downloads
                except OSError:
                    print(f'    delete {f} now (it contains the board key)', file=sys.stderr)
        time.sleep(1)
    srv.shutdown()
    if not got:
        sys.exit('timed out: the board host did not answer (is the board owner\'s computer on?) Run ./setup.sh again later.')
    os.makedirs(CONF, exist_ok=True)
    os.chmod(CONF, 0o700)
    sa = os.path.join(CONF, 'service-account.json')
    with open(sa, 'w') as fh:
        fh.write(got['serviceAccount'] if isinstance(got['serviceAccount'], str) else json.dumps(got['serviceAccount']))
    os.chmod(sa, 0o600)
    b = got['board']
    import shlex
    for k, v in (('APIKEY', b.get('apiKey')), ('PROJ', b.get('projectId')), ('APPID', b.get('appId')),
                 ('ME', got.get('email')), ('BURL', base)):
        print(f'{k}={shlex.quote(str(v or ""))}')


if __name__ == '__main__':
    main()
