#!/usr/bin/env python3
"""Invite a teammate to YOUR Night Shift board (shared board, everyone runs their own worker).

    python3 tools/nightshift/joinpack.py abdullah.khairy@msd-my.com --me a.tarek@msd-my.com

Writes tools/nightshift/out/join/nightshift-join-<name>.zip with the board's web settings and the board's worker key.
Send it PRIVATELY (AirDrop, a password manager, a direct message you delete after). Never a channel, never GitHub:
the key gives full control of the Night Shift board's data (not production, not your Mac). If it leaks: Firebase console
-> Project settings -> Service accounts -> delete that key, generate a new one, send new packs.
The first time it also sets YOUR nightshift.yaml `worker:` (you = the lab host that covers anyone whose Mac is off)."""
import argparse, json, os, re, shutil, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ns import config  # noqa: E402

SA = os.path.expanduser(os.environ.get('NIGHTSHIFT_SA', '~/.config/nightshift/service-account.json'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('email', help="the teammate's @msd-my.com address")
    ap.add_argument('--me', help='your own address (needed once, to make your worker the lab host)')
    a = ap.parse_args()
    cfg = config.load()
    fb = dict(cfg.get('firebase') or {})
    dom = str(fb.get('domain') or 'msd-my.com').lower()
    email = a.email.strip().lower()
    if not email.endswith('@' + dom):
        sys.exit(f'only @{dom} addresses can use the board')
    if not all(fb.get(k) for k in ('apiKey', 'authDomain', 'projectId', 'appId')):
        sys.exit('nightshift.yaml has no complete firebase: section (this Mac does not host a board)')
    if not os.path.exists(SA):
        sys.exit(f'no worker key at {SA}')
    if json.load(open(SA)).get('project_id') != fb['projectId']:
        sys.exit(f"{SA} is not the key of {fb['projectId']}")
    # 1) your worker becomes the lab host once a second worker exists
    yp = os.path.join(HERE, 'nightshift.yaml')
    if not str((cfg.get('worker') or {}).get('owner') or '').strip():
        if not a.me:
            sys.exit('first invite: add --me you@' + dom + ' (your worker then runs your jobs + covers anyone whose Mac is off)')
        open(yp, 'a', encoding='utf-8').write(f"\nworker:                                   # shared board: whose jobs this worker runs\n"
                                              f"  owner: {a.me.strip().lower()}\n"
                                              f"  serve_others: true                      # lab host: also runs jobs of people whose own worker is offline\n")
        print(f'your nightshift.yaml: worker.owner = {a.me}, serve_others = true (applies from the next job)')
    # 2) the allowlist (only matters when config/board.requireAllowlist is on)
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(SA))
        firestore.client().collection('staff').document(email).set({'note': 'joined with a join pack'}, merge=True)
    except Exception as e:
        print(f'note: could not add {email} to the allowlist ({str(e)[:100]}); add it with sentinel.py staff add')
    # 3) the pack
    name = re.sub(r'[^a-z0-9]+', '', email.split('@')[0])[:20]
    out = os.path.join(HERE, 'out', 'join')
    os.makedirs(out, exist_ok=True)
    zp = os.path.join(out, f'nightshift-join-{name}.zip')
    board = {k: fb[k] for k in ('apiKey', 'authDomain', 'projectId', 'appId', 'domain') if fb.get(k)}
    board['for'] = email
    board['url'] = f"https://{fb['projectId']}.web.app"
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('board.json', json.dumps(board, indent=1))
        z.write(SA, 'service-account.json')
        z.writestr('README.txt', f"Night Shift join pack for {email}\nRun:  ./setup.sh ~/video_gles3jni   and choose 'join' when asked.\n"
                                 "This file contains a KEY: keep it private, delete it after setup.\n")
    os.chmod(zp, 0o600)
    print(f'join pack: {zp}\nSend it privately to {email} (AirDrop / password manager). Then delete your copy.')


if __name__ == '__main__':
    main()
