"""Minimal YAML-subset loader (two-level mappings, scalars, inline comments). No PyYAML needed."""
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
try:                # where crash builds happen: the lab folder during a crash job (ns/labtree.py), else the working copy.
    LAB             # kept across the per-job reload of this module (an Audio Check job reloads it mid crash job)
except NameError:
    LAB = REPO


def _scalar(v):
    v = v.strip()
    if v[:1] in '"\'':
        q = v[0]
        end = v.find(q, 1)
        return v[1:end] if end > 0 else v[1:]
    if ' #' in v:
        v = v.split(' #', 1)[0].strip()
    elif v.startswith('#'):
        v = ''
    if v.lower() in ('true', 'false'):
        return v.lower() == 'true'
    try:
        return int(v)
    except ValueError:
        return v


def load(path=None):
    path = path or os.path.join(HERE, 'nightshift.yaml')
    cfg = {}
    stack = [(-1, cfg)]
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if not line.strip() or line.strip().startswith('#'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        key, _, val = line.strip().partition(':')
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == '' or val.strip().startswith('#'):
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = _scalar(val)
    # lists and flow mappings (the repro ladders) are beyond this loader: they live in lab_repros.json
    side = os.path.join(os.path.dirname(path), 'lab_repros.json')
    if os.path.exists(side):
        import json
        cfg.setdefault('lab', {})['repros'] = json.load(open(side, encoding='utf-8'))
    return cfg


def repo_path(*parts):
    return os.path.join(REPO, *parts)


# ---- profile (22 Oct): everything project-specific comes from nightshift.yaml, defaults = MyZesty as before ----
def _list(v):
    return [x.strip() for x in str(v or '').split(',') if x.strip()]


def profile(cfg=None):
    cfg = cfg if cfg is not None else load()
    p = dict(cfg.get('profile') or {})
    p.setdefault('name', 'MyZesty')
    repos = _list(p.get('repos')) or ['video_gles3jni']
    p['repos'] = repos
    p['main_repo'] = repos[0]
    p['review_repos'] = _list(p.get('review_repos')) or [repos[0]]
    p['code_packages'] = _list(p.get('code_packages')) or ['com.video.', 'com.common.', 'com.myzesty.']
    p['jira_keys'] = _list(p.get('jira_keys')) or [str((cfg.get('integrations') or {}).get('jira_project') or 'MZ')]
    p['package'] = str((cfg.get('app') or {}).get('package') or 'com.myzesty')
    return p


def app_package(cfg=None):
    try:
        return profile(cfg)['package']
    except Exception:
        return 'com.myzesty'
