#!/usr/bin/env python3
"""Build the Night Shift install kit (the folder you push to the private GitHub repo).

    python3 tools/nightshift/kit_build.py            # -> tools/nightshift/out/kit/nightshift
    python3 tools/nightshift/kit_build.py --out DIR

Copies ONLY the tool code, prompts, board pages, recipes and the debug-build lab overlay. Never copies: results (out/),
symbols, the built board (board/public), your nightshift.yaml, anything in ~/.config/nightshift, probe/one-off scripts,
logs, backups, __pycache__. Run it again after every Night Shift change, then commit + push from the kit folder.
A .git folder already in the kit is kept, so pushing updates is a normal `git add -A && git commit && git push`."""
import argparse, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
NS_DIRS = ['ns', 'audio', 'cards', 'skills', 'claude-plugin', 'templates', 'knowledge']
NS_FILES = ['connect.py', 'kit_update.py', 'sentinel.py', 'blindreset.py', 'symbols_rebuild.py', 'turbo_rollback.py', 'plugsetup.py', 'envcheck.py',
            'restartworker.py', 'workerlog.py', 'lab_repros.json', 'SECURITY.md', 'kit_build.py', 'joinpack.py']
BOARD_FILES = ['index.html', 'pr.html', 'card.html', 'audio.html', 'connect.html', 'firestore.rules', 'firestore.indexes.json', 'README.md']
STRESS_KEEP = re.compile(r'^(zesty\.py|scenarios\.py|anrsan_findings\.py|repro_slideshow_recreate\.py|screen_map\.json|README\.md)$')
SKIP_DIR = {'__pycache__', 'out', 'public', '.firebase', 'node_modules'}
SKIP_FILE = re.compile(r'(\.pyc|\.tmp|\.bak|\.log|\.orig|\.rej|~)$|^\.DS_Store$|^_')
SECRET = re.compile(r'(BEGIN (RSA |EC )?PRIVATE KEY|"private_key"|xox[bp]-|ATATT[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{30,})')
WRITTEN = set()


def put(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)                            # overwrite in place: nothing in the kit is ever deleted
    WRITTEN.add(os.path.abspath(dst))


def copytree(src, dst):
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in SKIP_DIR and not x.startswith('.')]
        rel = os.path.relpath(d, src)
        for f in files:
            if not SKIP_FILE.search(f):
                put(os.path.join(d, f), os.path.join(dst, rel, f))


def example_yaml(src, dst):
    """Your nightshift.yaml with every personal or board-specific value blanked; setup.sh fills them in."""
    s = open(src, encoding='utf-8').read()
    for key in ('apiKey', 'authDomain', 'projectId', 'appId'):
        s = re.sub(rf'^(\s+{key}:\s*).*$', rf'\1""                      # filled by setup.sh', s, flags=re.M)
    s = re.sub(r'^(\s+phone_serial:\s*)\S+', r'\1""', s, flags=re.M)
    s = re.sub(r'^(\s+crashlytics_alert_channel_id:\s*)\S+', r'\1""', s, flags=re.M)
    s = '# Night Shift settings. setup.sh copies this to nightshift.yaml and fills the board and phone lines.\n' + s
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'w', encoding='utf-8').write(s)
    WRITTEN.add(os.path.abspath(dst))


def files_in(out):
    got = set()
    for d, dirs, files in os.walk(out):
        dirs[:] = [x for x in dirs if x != '.git']
        got |= {os.path.abspath(os.path.join(d, f)) for f in files}
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(HERE, 'out', 'kit', 'nightshift'))
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    before = files_in(out)
    ns_out = os.path.join(out, 'tools', 'nightshift')
    for d in NS_DIRS:
        if os.path.isdir(os.path.join(HERE, d)):
            copytree(os.path.join(HERE, d), os.path.join(ns_out, d))
    for f in NS_FILES:
        if os.path.exists(os.path.join(HERE, f)):
            put(os.path.join(HERE, f), os.path.join(ns_out, f))
    for f in BOARD_FILES:
        if os.path.exists(os.path.join(HERE, 'board', f)):
            put(os.path.join(HERE, 'board', f), os.path.join(ns_out, 'board', f))
    example_yaml(os.path.join(HERE, 'nightshift.yaml'), os.path.join(ns_out, 'nightshift.example.yaml'))
    try:                                              # the team board's address (public web settings, no key): setup joins it
        sys.path.insert(0, HERE)
        from ns import config as _c
        fb = dict(_c.load().get('firebase') or {})
        if fb.get('projectId'):
            tb = {k: fb[k] for k in ('apiKey', 'authDomain', 'projectId', 'appId', 'domain') if fb.get(k)}
            tb['url'] = f"https://{fb['projectId']}.web.app"
            p = os.path.join(ns_out, 'team_board.json')
            json.dump(tb, open(p, 'w'), indent=1)
            WRITTEN.add(os.path.abspath(p))
    except Exception as e:
        print(f'note: team_board.json not written ({e})')
    st_src, st_out = os.path.join(REPO, 'tools', 'stress'), os.path.join(out, 'tools', 'stress')
    for f in os.listdir(st_src):
        if STRESS_KEEP.match(f):
            put(os.path.join(st_src, f), os.path.join(st_out, f))
    if os.path.isdir(os.path.join(st_src, 'auto')):
        copytree(os.path.join(st_src, 'auto'), os.path.join(st_out, 'auto'))
    dbg = os.path.join(REPO, 'app', 'src', 'debug')    # the lab's remote control inside debug builds (LabControl)
    if os.path.isdir(dbg):
        copytree(dbg, os.path.join(out, 'app-overlay', 'app', 'src', 'debug'))
    for f in ('README.md', 'SOP.md', 'setup.sh', 'update.sh', '.gitignore', '.gitattributes', 'requirements.txt'):   # the kit's own files
        if os.path.exists(os.path.join(HERE, 'kit', f)):
            put(os.path.join(HERE, 'kit', f), os.path.join(out, f))
    for sh in ('setup.sh', 'update.sh'):
        if os.path.exists(os.path.join(out, sh)):
            os.chmod(os.path.join(out, sh), 0o755)
    # files a teammate's setup made inside the kit (their yaml, board build, results) are theirs: ignored by .gitignore
    stale = sorted(os.path.relpath(p, out) for p in before - WRITTEN
                   if not re.match(r'tools/nightshift/(out|board/public|board/\.firebase|symbols)/|tools/nightshift/(nightshift\.yaml|runlog\.csv)$|tools/nightshift/board/(firebase\.json|\.firebaserc)$|.*__pycache__',
                                   os.path.relpath(p, out)))
    bad, size = [], 0
    for p in WRITTEN:                                  # safety: no key, token or private file may leave this Mac
        size += os.path.getsize(p)
        f = os.path.basename(p)
        if f in ('service-account.json', 'bitbucket.json', 'jira.json', 'play-token.json', 'play-oauth-client.json', 'nightshift.yaml'):
            bad.append(p)
        elif f != 'kit_build.py' and os.path.getsize(p) < 5_000_000:   # (this file holds the patterns themselves)
            try:
                if SECRET.search(open(p, encoding='utf-8', errors='ignore').read()):
                    bad.append(p)
            except OSError:
                pass
    if bad:
        sys.exit('STOP: possible secrets in the kit, do not push:\n  ' + '\n  '.join(sorted(bad)))
    print(f'kit ready: {out}  ({len(WRITTEN)} files, {size / 1e6:.1f} MB, no secrets found)')
    if stale:
        print('note: these files are no longer part of Night Shift but are still in the kit (nothing is deleted here); '
              'remove them with `git rm` before pushing:\n  ' + '\n  '.join(stale[:40]))


if __name__ == '__main__':
    main()
