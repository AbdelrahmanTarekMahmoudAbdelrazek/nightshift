"""100% blind reset for ONE crash (and its restore). Run on the Mac (needs Firestore).

    python3 tools/nightshift/blindreset.py hide    <crash id>
    python3 tools/nightshift/blindreset.py restore <crash id>

hide: backs up, then sets aside EVERYTHING Night Shift knows about the crash, so the next run starts as if it never
saw it: the case's lab/repro/fix/analysis fields, the problem's root cause, board note and PR, team knowledge files
that match it, its lab-repro registry entry, author files (checkpoints, diagnoses, prompts, scripts), hooks, fix
patches, case files, and the lab facts learned on it. Field data (stacks, devices, breadcrumbs, counts) stays.
restore: puts every file and field back exactly (the new run's results are kept beside them in the backup folder).
Never touches production; only nightshift-myzesty Firestore and files in this repo.
"""
import glob
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ns import config, fire  # noqa: E402

OUT = os.path.join(HERE, 'out')
VAULT = os.path.join(OUT, 'blind100')
LOG = os.path.join(OUT, 'batch', 'blindreset.log')
CASE_KEEP = {'id', 'kind', 'title', 'subtitle', 'frames', 'events', 'versions', 'sync_versions', 'sync_events', 'sync_users',
             'sync_at', 'sync_run', 'models', 'manufacturers', 'android', 'breadcrumbs', 'buckets', 'per_day', 'first_seen',
             'last_seen', 'first_date', 'last_date', 'last_events', 'last_screens', 'real_users', 'sessions_hashed',
             'sample_event', 'signal', 'signals', 'native_sites', 'stack_groups', 'uptime_bands', 'with_breadcrumbs',
             'with_dump', 'with_native_logs', 'field_fingerprint', 'console_url', 'csv', 'issue', 'source', 'src',
             'internal', 'generated', 'updatedAt'}
MERGED_DROP = ('analysis', 'analysis_key', 'analysis_basis', 'analysedAt', 'note', 'noteBy', 'noteAt', 'pr')


def say(*a):
    line = ' '.join(str(x) for x in a)
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'a').write(time.strftime('%Y-%m-%dT%H:%M:%S ') + line + '\n')


def files_for(cid):
    from ns import groups
    k8 = groups.k8(cid)                              # a split card has its own files ('g' + fingerprint), never its sibling's
    pats = [f'out/author/{k8}.*', f'out/author/{k8}_*', f'out/hooks/{k8}_*', f'out/fix/{cid}.*', f'out/patches/{cid}.*',
            f'out/*_{cid}_case_file.*', f'out/{cid}.*', f'out/labbuild_backup/{cid}', f'../stress/auto/{k8}.py',
            f'../stress/auto/{k8}_*.py', f'out/replay/{cid}.json', f'out/replay/{k8}.*', f'out/replay/{k8}_*']
    hits = []
    for p in pats:
        hits += glob.glob(os.path.join(HERE, p))
    return sorted(set(hits))


def knowledge_for(m):
    hay = json.dumps({k: v for k, v in m.items() if k not in MERGED_DROP}, default=str)
    out = []
    for fn in sorted(glob.glob(os.path.join(HERE, 'knowledge', '*.md'))):
        if os.path.basename(fn).lower() == 'readme.md':
            continue
        mt = re.search(r'^match:\s*(.+)$', open(fn, encoding='utf-8').read(), re.M)
        if mt and any(p.strip() and p.strip() in hay for p in mt.group(1).split(',')):
            out.append(fn)
    return out


def hide(cid):
    db = fire.client()
    vault = os.path.join(VAULT, cid)
    if os.path.exists(os.path.join(vault, 'manifest.json')):
        sys.exit(f'already hidden (restore first): {vault}')
    if os.path.isdir(vault) and os.listdir(vault):          # an earlier hide/restore cycle: keep it whole, start a new vault
        os.rename(vault, f'{vault}.prev_{int(time.time())}')
    os.makedirs(vault, exist_ok=True)
    man = {'cid': cid, 'hidden_at': time.time(), 'files': [], 'case_dropped': [], 'merged': {}, 'registry': None, 'facts': []}
    # Firestore: case (keep field data only) and every merged problem row of this crash
    cref = db.collection('cases').document(cid)
    case = cref.get().to_dict() or {}
    json.dump(case, open(os.path.join(vault, 'case.json'), 'w'), indent=1, default=str)
    from google.cloud import firestore as gcf
    drop = [k for k in case if k not in CASE_KEEP]
    if drop:
        cref.update({k: gcf.DELETE_FIELD for k in drop})
    man['case_dropped'] = drop
    for d in db.collection('merged').where('fb.id', '==', cid).stream():
        m = d.to_dict() or {}
        man['merged'][d.id] = {k: m[k] for k in MERGED_DROP if k in m}
        json.dump(m, open(os.path.join(vault, f'merged_{d.id}.json'), 'w'), indent=1, default=str)
        gone = [k for k in MERGED_DROP if k in m]
        if gone:
            d.reference.update({k: gcf.DELETE_FIELD for k in gone})
        for fn in knowledge_for(m):
            man['files'].append(os.path.relpath(fn, HERE))
    # files
    man['files'] = sorted(set(man['files'] + [os.path.relpath(f, HERE) for f in files_for(cid)]))
    for rel in man['files']:
        src = os.path.join(HERE, rel)
        dst = os.path.join(vault, 'files', rel.replace('../', 'UP/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    # lab-repro registry entry
    rp = os.path.join(HERE, 'lab_repros.json')
    reg = json.load(open(rp))
    if cid in reg:
        man['registry'] = reg.pop(cid)
    # hand-registered ladders keyed by a field frame of this crash (e.g. 'VisualTimeLine::get_media_starting_time')
    hay = json.dumps(case.get('frames') or [], default=str) + ' ' + str(case.get('title') or '')
    man['registry_extra'] = {k: reg.pop(k) for k in [k for k in reg if not re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', k) and k in hay]}
    json.dump(reg, open(rp, 'w'), indent=1)
    # lab facts learned on this crash (blind runs hide old facts anyway; this removes them for good until restore)
    fp = os.path.join(OUT, 'author', 'lab_facts.json')
    if os.path.exists(fp):
        facts = json.load(open(fp))
        keep = [f for f in facts if cid[:8] not in json.dumps(f)]
        man['facts'] = [f for f in facts if cid[:8] in json.dumps(f)]
        json.dump(keep, open(fp, 'w'), indent=1)
    json.dump(man, open(os.path.join(vault, 'manifest.json'), 'w'), indent=1, default=str)
    say(f'HIDE {cid}: case fields dropped {len(drop)}, merged rows {len(man["merged"])}, files moved {len(man["files"])} '
        f'({", ".join(os.path.basename(f) for f in man["files"] if "knowledge" in f) or "no knowledge file"}), '
        f'registry {"yes" if man["registry"] else "no"} (+{len(man["registry_extra"])} frame-keyed), facts {len(man["facts"])}')
    # self-check: nothing about the crash is left where Night Shift can read it
    left = [os.path.relpath(f, HERE) for f in files_for(cid)] + [os.path.relpath(f, HERE) for f in sum((knowledge_for(m) for m in [
        d.to_dict() or {} for d in db.collection('merged').where('fb.id', '==', cid).stream()]), [])]
    say(f'CHECK {cid}: ' + ('clean: no file, note, root cause, registry entry or knowledge file left' if not left else f'LEFT: {left}'))


def restore(cid):
    db = fire.client()
    vault = os.path.join(VAULT, cid)
    man = json.load(open(os.path.join(vault, 'manifest.json')))
    case = json.load(open(os.path.join(vault, 'case.json')))
    cref = db.collection('cases').document(cid)
    now = cref.get().to_dict() or {}
    json.dump(now, open(os.path.join(vault, f'case_after_blind_{int(time.time())}.json'), 'w'), indent=1, default=str)
    old = {k: case[k] for k in man['case_dropped'] if k in case}
    if old:
        cref.set(old, merge=True)
    for mid, fields in man['merged'].items():
        mref = db.collection('merged').document(mid)
        cur = mref.get().to_dict() or {}
        json.dump(cur, open(os.path.join(vault, f'merged_{mid}_after_blind_{int(time.time())}.json'), 'w'), indent=1, default=str)
        if fields:
            mref.set(fields, merge=True)
    for rel in man['files']:
        src = os.path.join(vault, 'files', rel.replace('../', 'UP/'))
        dst = os.path.join(HERE, rel)
        if os.path.exists(dst):                           # the blind run made a new one: keep it beside the backup
            shutil.move(dst, src + f'.blindrun_{int(time.time())}')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
    if man.get('registry'):
        rp = os.path.join(HERE, 'lab_repros.json')
        reg = json.load(open(rp))
        if cid in reg:
            json.dump(reg[cid], open(os.path.join(vault, f'registry_after_blind_{int(time.time())}.json'), 'w'), indent=1)
        reg[cid] = man['registry']
        json.dump(reg, open(rp, 'w'), indent=1)
    if man.get('registry_extra'):
        rp = os.path.join(HERE, 'lab_repros.json')
        reg = json.load(open(rp))
        reg.update(man['registry_extra'])
        json.dump(reg, open(rp, 'w'), indent=1)
    if man.get('facts'):
        fp = os.path.join(OUT, 'author', 'lab_facts.json')
        facts = json.load(open(fp)) if os.path.exists(fp) else []
        json.dump(facts + man['facts'], open(fp, 'w'), indent=1)
    os.rename(os.path.join(vault, 'manifest.json'), os.path.join(vault, f'manifest.restored_{int(time.time())}.json'))
    say(f'RESTORE {cid}: case fields {len(old)}, merged rows {len(man["merged"])}, files {len(man["files"])}, registry '
        f'{"yes" if man.get("registry") else "no"}, facts {len(man.get("facts") or [])}')


def drop(cid, field):
    """Hide one more case field of an already hidden crash (recorded, so restore puts it back)."""
    db = fire.client()
    vault = os.path.join(VAULT, cid)
    man = json.load(open(os.path.join(vault, 'manifest.json')))
    from google.cloud import firestore as gcf
    db.collection('cases').document(cid).update({field: gcf.DELETE_FIELD})
    if field not in man['case_dropped']:
        man['case_dropped'].append(field)
    json.dump(man, open(os.path.join(vault, 'manifest.json'), 'w'), indent=1, default=str)
    say(f'DROP {cid}: case field {field} hidden (restore puts it back)')


def rehide(cid):
    """A blind run on an already hidden crash left new knowledge (registry entry, author/replay files, case fields):
    set it aside in the vault (run_<time>/) so the next run starts from zero again. restore later puts back the
    ORIGINAL history only; the set-aside runs stay in the vault for comparison."""
    db = fire.client()
    vault = os.path.join(VAULT, cid)
    if not os.path.exists(os.path.join(vault, 'manifest.json')):
        return hide(cid)                          # not hidden yet: a first hide does the same job
    man = json.load(open(os.path.join(vault, 'manifest.json')))
    run = os.path.join(vault, f'run_{int(time.time())}')
    os.makedirs(run, exist_ok=True)
    cref = db.collection('cases').document(cid)
    case = cref.get().to_dict() or {}
    json.dump(case, open(os.path.join(run, 'case.json'), 'w'), indent=1, default=str)
    from google.cloud import firestore as gcf
    drop = [k for k in case if k not in CASE_KEEP]
    if drop:
        cref.update({k: gcf.DELETE_FIELD for k in drop})
    man['case_dropped'] = sorted(set(man['case_dropped']) | set(drop))   # restore must not leave these behind
    for d in db.collection('merged').where('fb.id', '==', cid).stream():
        m = d.to_dict() or {}
        json.dump(m, open(os.path.join(run, f'merged_{d.id}.json'), 'w'), indent=1, default=str)
        gone = [k for k in MERGED_DROP if k in m]
        if gone:
            d.reference.update({k: gcf.DELETE_FIELD for k in gone})
    moved = []
    for f in files_for(cid):
        rel = os.path.relpath(f, HERE)
        dst = os.path.join(run, 'files', rel.replace('../', 'UP/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(f, dst)
        moved.append(rel)
    rp = os.path.join(HERE, 'lab_repros.json')
    reg = json.load(open(rp))
    if cid in reg:
        json.dump(reg.pop(cid), open(os.path.join(run, 'registry.json'), 'w'), indent=1)
        json.dump(reg, open(rp, 'w'), indent=1)
    json.dump(man, open(os.path.join(vault, 'manifest.json'), 'w'), indent=1, default=str)
    say(f'REHIDE {cid}: case fields {len(drop)}, files {len(moved)}, set aside in {os.path.relpath(run, HERE)}')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == 'drop' and re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', sys.argv[2]) and re.fullmatch(r'\w+', sys.argv[3]):
        drop(sys.argv[2], sys.argv[3])
        sys.exit(0)
    if len(sys.argv) == 3 and sys.argv[1] == 'rehide' and re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', sys.argv[2]):
        rehide(sys.argv[2])
        sys.exit(0)
    if len(sys.argv) != 3 or sys.argv[1] not in ('hide', 'restore') or not re.fullmatch(r'[0-9a-f]{32}(~[0-9a-f]{8})?', sys.argv[2]):
        print(__doc__)
        sys.exit(2)
    (hide if sys.argv[1] == 'hide' else restore)(sys.argv[2])
