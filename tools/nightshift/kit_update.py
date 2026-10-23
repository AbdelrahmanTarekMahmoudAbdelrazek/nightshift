#!/usr/bin/env python3
"""Update a teammate's Night Shift kit from GitHub without merge trouble (run by ./update.sh in the kit folder).

Night Shift itself writes to a few files that are also in the repo (what it learns on YOUR phone):
  tools/stress/screen_map.json, tools/nightshift/lab_repros.json, tools/nightshift/knowledge/lessons.jsonl,
  tools/stress/auto/*.py
This script keeps a copy of them, makes the folder match GitHub, then merges your learning back in (both sides kept:
JSON maps are joined, lessons are joined line by line, a recipe changed on both sides keeps GitHub's and saves yours
next to it as <name>.py.mine). Any OTHER file you edited is kept in a git stash (it says so). Nothing is lost."""
import json, os, shutil, subprocess, sys, time

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
LEARN = ['tools/stress/screen_map.json', 'tools/nightshift/lab_repros.json', 'tools/nightshift/knowledge/lessons.jsonl']
AUTO = 'tools/stress/auto/'


def git(*a, check=True):
    r = subprocess.run(['git', '-C', KIT] + list(a), capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(a)} failed:\n{(r.stdout + r.stderr).strip()[-800:]}")
    return r.stdout


def deep_merge(base, mine):
    """GitHub's version plus everything only you have; for the same key, maps are merged, lists joined, else GitHub."""
    if isinstance(base, dict) and isinstance(mine, dict):
        out = dict(base)
        for k, v in mine.items():
            out[k] = deep_merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(mine, list):
        out = list(base)
        for x in mine:
            if x not in out:
                out.append(x)
        return out
    return base


def main():
    git('config', 'core.autocrlf', 'input')            # Mac/Linux line endings in this folder, whatever the global setting
    backup = os.path.join(os.path.expanduser('~/.nightshift_backup'), time.strftime('%Y%m%d-%H%M%S'))
    changed = [l[3:].strip().strip('"') for l in git('status', '--porcelain', '--untracked-files=no').splitlines()]
    learned = [f for f in changed if f in LEARN or f.startswith(AUTO)]
    other = [f for f in changed if f not in learned]
    mine = {}
    for f in learned:                                  # keep what Night Shift learned on this computer
        p = os.path.join(KIT, f)
        if os.path.exists(p):
            os.makedirs(os.path.dirname(os.path.join(backup, f)), exist_ok=True)
            shutil.copy2(p, os.path.join(backup, f))
            mine[f] = open(p, encoding='utf-8', errors='replace').read()
    if learned:
        git('checkout', '--', *learned)
    if other:
        git('stash', 'push', '-m', 'nightshift update: your own edits', '--', *other)
        print(f'your own edits to {len(other)} file(s) are kept in a git stash (see: git -C {KIT} stash list)')
    git('fetch', '--quiet', 'origin')
    before = git('rev-parse', 'HEAD').strip()
    r = subprocess.run(['git', '-C', KIT, 'merge', '--ff-only', 'origin/main'], capture_output=True, text=True)
    if r.returncode:                                   # local commits (should not happen): put them on top of GitHub's
        git('rebase', 'origin/main')
    after = git('rev-parse', 'HEAD').strip()
    for f, txt in mine.items():                        # merge your learning back in
        p = os.path.join(KIT, f)
        theirs = open(p, encoding='utf-8', errors='replace').read() if os.path.exists(p) else ''
        try:
            if f.endswith('.json'):
                merged = json.dumps(deep_merge(json.loads(theirs or '{}'), json.loads(txt or '{}')), indent=1, ensure_ascii=False) + '\n'
            elif f.endswith('.jsonl'):
                seen, lines = set(), []
                for l in (theirs.splitlines() + txt.splitlines()):
                    if l.strip() and l not in seen:
                        seen.add(l); lines.append(l)
                merged = '\n'.join(lines) + '\n'
            elif theirs and theirs != txt:             # a recipe changed on both sides: GitHub's stays, yours next to it
                open(p + '.mine', 'w', encoding='utf-8').write(txt)   # .py.mine: never loaded as a recipe
                continue
            else:
                merged = txt
            open(p, 'w', encoding='utf-8').write(merged)
        except ValueError:
            open(p + '.mine', 'w', encoding='utf-8').write(txt)
    print(('updated ' + before[:7] + ' → ' + after[:7]) if before != after else 'already up to date')
    if learned:
        print(f'your local learning ({len(learned)} file(s)) was merged back; a copy is in {backup}')


if __name__ == '__main__':
    main()
