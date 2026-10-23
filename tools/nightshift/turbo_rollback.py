"""Night Shift TURBO: switch it off, roll the code back, or put a crash's history back. Run on the Mac:

    python3 tools/nightshift/turbo_rollback.py off       # turbo off right now (code stays; next job runs the old way)
    python3 tools/nightshift/turbo_rollback.py on        # turbo on again
    python3 tools/nightshift/turbo_rollback.py code      # every file turbo changed goes back to its pre-turbo copy
    python3 tools/nightshift/turbo_rollback.py history   # the starting-time crash's hidden history comes back
    python3 tools/nightshift/turbo_rollback.py all       # off + code + history

Turbo = engine replay (step 6), several tries per setup (1), adaptive verify count (2), run cutoff (7), 2 emulator lanes.
Pre-turbo copies: tools/nightshift/out/bk_turbo/<stamp>/ (stamp in out/bk_turbo/LATEST). Nothing is deleted: the turbo
versions are kept in out/bk_turbo/<stamp>/after_<time>/ so a rollback can itself be undone."""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
EXP = os.path.join(HERE, 'out', 'experiment.json')
BK = os.path.join(HERE, 'out', 'bk_turbo')
CASE = '2bc43cd6d24a25e5305f8167703618a8'
NEW_FILES = ['tools/nightshift/ns/replay.py', 'tools/nightshift/ns/live.py', 'tools/stress/auto/_live_agent.py']             # files turbo added (moved aside on a code rollback)
SKIP = {'tools/nightshift/out/experiment.json', 'tools/nightshift/lab_repros.json'}   # owned by off/on and history


def off():
    e = json.load(open(EXP))
    if 'turbo' in e:
        e['turbo_off'] = e.pop('turbo')
    b = e.setdefault('boost', {})
    if 'lanes_before_turbo' in b:
        b['lanes'] = b.pop('lanes_before_turbo')
    json.dump(e, open(EXP, 'w'))
    print('turbo OFF:', json.dumps(e))


def on():
    e = json.load(open(EXP))
    if 'turbo_off' in e:
        e['turbo'] = e.pop('turbo_off')
    b = e.setdefault('boost', {})
    want = int((e.get('turbo') or {}).get('lanes', 1))  # one 3 GB emulator: two at 2 GB starved the 16 GB M1 (2026-10-13)
    if 'lanes_before_turbo' not in b:
        b['lanes_before_turbo'] = b.get('lanes', 0)
    b['lanes'] = want
    json.dump(e, open(EXP, 'w'))
    print('turbo ON:', json.dumps(e))


def code():
    stamp = open(os.path.join(BK, 'LATEST')).read().strip()
    src = os.path.join(BK, stamp)
    keep = os.path.join(src, f'after_{time.strftime("%Y%m%d-%H%M%S")}')
    n = 0
    for root, _dirs, files in os.walk(src):
        if os.path.basename(root).startswith('after_') or '/after_' in root:
            continue
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), src)
            if rel.startswith('after_') or rel in SKIP:
                continue
            cur = os.path.join(REPO, rel)
            if os.path.exists(cur):
                os.makedirs(os.path.dirname(os.path.join(keep, rel)), exist_ok=True)
                shutil.copy2(cur, os.path.join(keep, rel))
            shutil.copy2(os.path.join(root, f), cur)
            n += 1
            print('restored', rel)
    for rel in NEW_FILES:
        cur = os.path.join(REPO, rel)
        if os.path.exists(cur):
            os.makedirs(os.path.dirname(os.path.join(keep, 'new', rel)), exist_ok=True)
            shutil.move(cur, os.path.join(keep, 'new', rel))
            print('moved aside (turbo-only file)', rel)
    auto = os.path.join(REPO, 'tools', 'stress', 'auto')
    for f in sorted(os.listdir(auto)):
        if f.endswith('_replay.py'):                     # engine replays need the turbo LabControl; set them aside too
            os.makedirs(os.path.join(keep, 'new', 'tools/stress/auto'), exist_ok=True)
            shutil.move(os.path.join(auto, f), os.path.join(keep, 'new', 'tools/stress/auto', f))
            print('moved aside', f)
    print(f'code rolled back ({n} files); the turbo versions are in {os.path.relpath(keep, REPO)}')


def history():
    r = subprocess.run([sys.executable, os.path.join(HERE, 'blindreset.py'), 'restore', CASE])
    if r.returncode:
        print('history: nothing hidden to restore (or restore failed; see out/batch/blindreset.log)')


if __name__ == '__main__':
    what = sys.argv[1] if len(sys.argv) > 1 else ''
    if what not in ('off', 'on', 'code', 'history', 'all'):
        sys.exit(__doc__)
    if what in ('off', 'all'):
        off()
    if what == 'on':
        on()
    if what in ('code', 'all'):
        code()
    if what in ('history', 'all'):
        history()
