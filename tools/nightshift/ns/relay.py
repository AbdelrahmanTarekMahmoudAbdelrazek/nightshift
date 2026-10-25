"""Bitbucket reads through the board host (23 Oct): a teammate's worker without its own Bitbucket token asks the host's
worker, which makes the same read-only GET with its token and answers through Firestore (relay/<id>). Only GETs under
https://api.bitbucket.org/2.0/repositories/<workspace>/ are answered; answers over ~900 KB are refused (PR diffs then
come from git, as before). Requests are deleted by the asker after reading, and by the host after 10 minutes."""
import datetime as dt
import json
import os
import secrets
import threading
import time

API = 'https://api.bitbucket.org/2.0'


def _db():
    from firebase_admin import firestore
    return firestore.client()


def get(url, raw=False, timeout=90):
    """Ask the host for one Bitbucket GET. Returns the text (raw) or the parsed JSON; raises like urllib on errors."""
    return _ask({'url': url, 'raw': bool(raw)}, raw, timeout)


def symbolize(addrs, vc, vn, lib, timeout=60):
    """Ask the host (which keeps the symbol store: Play libraries + the full debug symbols from the .aab) to name
    these pcs of one build. -> [{'func', 'srcline', 'named_by'}] in the same order; raises when nobody answers."""
    return json.loads(_ask({'kind': 'sym', 'addrs': [int(a) for a in addrs][:400], 'vc': str(vc or ''), 'vn': str(vn or ''),
                            'lib': lib}, True, timeout))


def _ask(req, raw, timeout):
    db = _db()
    rid = secrets.token_hex(8)
    ref = db.collection('relay').document(rid)
    from google.cloud import firestore as gcf
    ref.set({**req, 'at': gcf.SERVER_TIMESTAMP})
    t0 = time.time()
    try:
        while time.time() - t0 < timeout:
            d = ref.get().to_dict() or {}
            if 'status' in d:
                if d['status'] != 200:
                    raise RuntimeError(f"via the board host: HTTP {d['status']} {d.get('error', '')}".strip())
                return d['body'] if raw else json.loads(d['body'])
            time.sleep(1.5)
        raise RuntimeError('the board host did not answer (is its computer on?)')
    finally:
        try:
            ref.delete()
        except Exception:
            pass


def start_responder(db, cfg):
    """Board host only: answer relay requests with its own Bitbucket token (a live listener, no polling)."""
    if not ((cfg or {}).get('worker') or {}).get('serve_others'):
        return
    t = getattr(threading, '_ns_relay', None)
    if t is not None and t.is_alive():
        return
    from . import bitbucket

    def answer(doc):
        x = doc.to_dict() or {}
        if 'status' in x:
            at = x.get('at')
            if at and (dt.datetime.now(dt.timezone.utc) - at).total_seconds() > 600:
                doc.reference.delete()
            return
        if x.get('kind') == 'sym':                         # name engine pcs with the host's symbol store
            try:
                from . import symbolize as sy
                lib = str(x.get('lib') or 'libMYJNILIB26.so')
                if not sy.resolve(x.get('vc'), x.get('vn') or None, lib)[0]:
                    doc.reference.update({'status': 404, 'error': f"the host has no symbols for build {x.get('vc')}"}); return
                fr = [{'lib': lib, 'address': int(a)} for a in (x.get('addrs') or [])][:400]
                sy.symbolize_frames(fr, x.get('vc'), lib, x.get('vn') or None, relay_ok=False)
                doc.reference.update({'status': 200, 'body': json.dumps([{k: f.get(k) for k in ('func', 'srcline', 'named_by', 'assumed_lib')} for f in fr])})
            except Exception as e:
                doc.reference.update({'status': 502, 'error': str(e)[:200]})
            return
        url = str(x.get('url') or '')
        try:
            c = bitbucket.creds()
            ok = url.startswith(f"{API}/repositories/{c['workspace']}/")
        except Exception as e:
            doc.reference.update({'status': 503, 'error': f'host has no token ({str(e)[:80]})'}); return
        if not ok:
            doc.reference.update({'status': 403, 'error': 'only read-only repository URLs are relayed'}); return
        try:
            body = bitbucket._get(url, raw=True, c=c)
            if len(body.encode()) > 900_000:
                doc.reference.update({'status': 413, 'error': 'answer too large for the relay'}); return
            doc.reference.update({'status': 200, 'body': body})
        except Exception as e:
            doc.reference.update({'status': getattr(e, 'code', 502) or 502, 'error': str(e)[:200]})

    def on_change(snaps, changes, read_time):
        for ch in changes:
            if ch.type.name == 'ADDED':
                threading.Thread(target=answer, args=(ch.document,), daemon=True).start()

    def loop():
        watch = None
        while True:
            try:
                if watch is None or getattr(watch, '_closed', False):
                    watch = db.collection('relay').on_snapshot(on_change)
                for d in db.collection('relay').stream():          # every 10 min: tidy old requests
                    answer(d)
            except Exception as e:
                print(f'[worker] relay: {str(e)[:120]}', flush=True)
                watch = None
            time.sleep(600)
    t = threading.Thread(target=loop, name='ns-relay', daemon=True)
    threading._ns_relay = t
    t.start()


def has_own_token():
    return os.path.exists(os.path.expanduser('~/.config/nightshift/bitbucket.json'))
