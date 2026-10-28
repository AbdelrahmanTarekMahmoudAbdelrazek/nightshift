"""Generic symbols: for every build that shows up in Crashlytics or Play, fetch that build's own native library
from Google Play automatically and add it to the symbol store. No manual APK downloads.

Google Play Developer API (read-only use here, GETs only):
  GET  applications/{pkg}/generatedApks/{versionCode}                         -> APKs Play generated from the bundle
  GET  applications/{pkg}/generatedApks/{versionCode}/downloads/{id}:download -> the file
We take the arm64-v8a config split (a few MB of .so instead of the 340 MB universal APK), fall back to the
universal APK, extract lib/arm64-v8a/libMYJNILIB26.so and store it with its BuildId under symbols/<versionCode>/.
Needs the Night Shift sign-in to include the androidpublisher scope (sentinel.py play-login, once).
"""
import json
import os
import tempfile
import urllib.parse
import urllib.request

from . import symbolize, sync

API = 'https://androidpublisher.googleapis.com/androidpublisher/v3'
SCOPE = 'https://www.googleapis.com/auth/androidpublisher'


def _token():
    import google.auth.transport.requests
    from google.oauth2.credentials import Credentials
    if not os.path.exists(sync.PLAY_TOKEN):
        raise RuntimeError('not signed in: run sentinel.py play-login')
    creds = Credentials.from_authorized_user_file(sync.PLAY_TOKEN)          # keep the scopes the user granted
    if SCOPE not in (creds.scopes or []):
        raise RuntimeError('the Night Shift sign-in lacks Play app downloads; run sentinel.py play-login once more')
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _get(url, tok, raw=False):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}'})
    try:
        r = urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Play API {e.code}: {" ".join(e.read().decode(errors="replace").split())[:300]}')
    return r if raw else json.load(r)


def _pick(generated):
    """Prefer the arm64 config split (small), else the universal APK. Returns (downloadId, label)."""
    for g in generated.get('generatedApks', []) or []:
        for sp in g.get('generatedSplitApks', []) or []:
            sid = (sp.get('splitId') or '').lower()
            if 'arm64' in sid and sp.get('downloadId'):
                return sp['downloadId'], f"split {sp.get('splitId')}"
    for g in generated.get('generatedApks', []) or []:
        u = g.get('generatedUniversalApk') or {}
        if u.get('downloadId'):
            return u['downloadId'], 'universal APK'
    return None, None


def fetch(cfg, version_code, version_name=None, log=print, lib='libMYJNILIB26.so'):
    pkg = cfg['app']['package']
    tok = _token()
    gen = _get(f'{API}/applications/{pkg}/generatedApks/{version_code}', tok)
    did, label = _pick(gen)
    if not did:
        raise RuntimeError(f'Play has no generated APK for {version_code}')
    url = f'{API}/applications/{pkg}/generatedApks/{version_code}/downloads/{urllib.parse.quote(did, safe="")}:download?alt=media'
    with tempfile.NamedTemporaryFile(suffix='.apk', delete=False) as f:
        r = _get(url, tok, raw=True)
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
        path = f.name
    try:
        meta = symbolize.add(path, version_code, lib=lib, version_name=version_name)
        meta['source'] = f'Google Play {label} of {version_code}'
        json.dump(meta, open(os.path.join(symbolize.STORE, str(version_code), 'meta.json'), 'w'), indent=1)
    finally:
        os.unlink(path)
    log(f'symbols: {version_code} added from Google Play ({label}): BuildId {meta["build_id"][:16]}…, {meta["functions"]} functions')
    return meta


def ensure(cfg, codes, version_name=None, log=print):
    """Fetch every build in `codes` that the store does not have yet. Never raises: logs what it could not do."""
    have, added, failed = [], [], []
    for vc in codes:
        if os.path.exists(symbolize.store_path(vc, 'libMYJNILIB26.so')):
            have.append(vc)
            continue
        try:
            fetch(cfg, vc, version_name, log)
            added.append(vc)
        except Exception as e:
            failed.append(vc)
            log(f'symbols: could not fetch {vc}: {str(e)[:250]}')
    log(f'symbols: {len(have)} builds already stored, {len(added)} fetched, {len(failed)} missing')
    try:                                             # full debug symbols (.aab / native-debug-symbols.zip in Downloads)
        symbolize.auto_import_debug(have + added, log=log)
    except Exception as e:
        log(f'symbols: debug-symbol import skipped: {str(e)[:150]}')
    try:                                             # no .aab: the engine library the app repo committed for the release
        from . import config as _c
        symbolize.import_from_app_repo(cfg or _c.load(), have + added, version_name, log=log)
    except Exception as e:
        log(f'symbols: app-repo import skipped: {str(e)[:150]}')
    full = [vc for vc in have + added if os.path.exists(symbolize.store_path(vc, 'libMYJNILIB26.so') + '.dbg')]
    log(f'symbols: full debug symbols (function names + file:line) for {len(full)}/{len(have + added)} builds')
    return {'have': have, 'added': added, 'failed': failed, 'debug': full}
