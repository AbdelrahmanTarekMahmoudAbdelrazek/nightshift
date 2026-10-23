"""Firestore access for the worker (Admin SDK). Optional dependency: `pip3 install firebase-admin`.

The service-account key lives outside the repo; path from $NIGHTSHIFT_SA (default ~/.config/nightshift/service-account.json).
"""
import os

SA_DEFAULT = os.path.expanduser('~/.config/nightshift/service-account.json')


def _install_retries():
    """The Mac mini's Wi-Fi drops connections (504 Deadline Exceeded, connection reset). Every Firestore write in
    Night Shift (batch commits, set, update) retries transient errors 3 times instead of failing the whole sync/job.
    Patched on the classes once per process, so clients created earlier get it too."""
    try:
        import time
        from google.api_core import exceptions as ex
        from google.cloud.firestore_v1 import batch as fb, document as fd
    except Exception:
        return
    transient = (ex.ServiceUnavailable, ex.DeadlineExceeded, ex.InternalServerError, ex.Aborted, ex.RetryError,
                 ConnectionError, TimeoutError)

    def wrap(f):
        if getattr(f, '_ns_retry', False):
            return f

        def g(*a, **k):
            for i in range(4):
                try:
                    return f(*a, **k)
                except transient:
                    if i == 3:
                        raise
                    time.sleep(3 * (i + 1))
        g._ns_retry = True
        return g
    for cls, names in ((fb.WriteBatch, ('commit',)), (fd.DocumentReference, ('set', 'update', 'delete'))):
        for n in names:
            if hasattr(cls, n):
                setattr(cls, n, wrap(getattr(cls, n)))


_install_retries()


def client():
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as e:
        raise SystemExit('firebase-admin is not installed: pip3 install firebase-admin') from e
    sa = os.environ.get('NIGHTSHIFT_SA', SA_DEFAULT)
    if not os.path.exists(sa):
        raise SystemExit(f'service account key not found at {sa} (set NIGHTSHIFT_SA); see board/README.md step 5')
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(sa))
    return firestore.client()


def publish(db, data: dict) -> dict:
    """Mirror out/board.json into Firestore: cases, findings, runlog, config/board. Batched, idempotent."""
    from firebase_admin import firestore
    import hashlib, json as _json
    counts = {'cases': 0, 'findings': 0, 'runlog': 0, 'unchanged': 0}
    batch, n = db.batch(), 0
    # Free plan: 20k writes/day. Every job republished ~270 docs (+1 read per case, + one read per open board tab per
    # write). A local fingerprint of what was last published skips every unchanged doc: no read, no write.
    cpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'fire_publish_cache.json')
    try:
        cache = _json.load(open(cpath))
    except Exception:
        cache = {}
    def fp(d):
        return hashlib.sha1(_json.dumps({k: v for k, v in d.items() if k != 'updatedAt'}, sort_keys=True, default=str).encode()).hexdigest()
    def same(key, d):
        h = fp(d)
        if cache.get(key) == h:
            counts['unchanged'] += 1
            return True
        cache[key] = h
        return False

    def put(ref, doc):
        nonlocal batch, n
        batch.set(ref, doc, merge=True)
        n += 1
        if n >= 400:
            batch.commit()
            batch, n = db.batch(), 0

    for c in data.get('issues', []):
        if same('cases/' + str(c['id']), c):
            continue
        doc = dict(c)
        doc.setdefault('narrative', '')          # always overwrite: never leave a stale analysis on the board
        doc['updatedAt'] = firestore.SERVER_TIMESTAMP
        ref = db.collection('cases').document(c['id'])
        old = ref.get().to_dict() or {}
        for k in ('status', 'patch', 'fixVerified', 'fixNote', 'repro_scenario', 'repro_seed', 'repro_dir', 'labMatch', 'labRuns', 'labFailures',
                  'reproAttempts', 'repro_step', 'reproAuthor', 'reproVideo', 'reproVideoNote', 'reproVideoUrl', 'reproVideoVtt', 'reproSteps', 'labCrash', 'authorAttempts', 'fixRounds', 'fixMinutes', 'fixAnswer', 'review', 'handover', 'progress', 'reproLevel', 'reproNatural', 'reproRate', 'repro_script', 'narrative', 'frames', 'breadcrumbs',
                  'stack_groups', 'field_fingerprint',
                  'src', 'sync_run', 'sync_at', 'sync_events', 'sync_users', 'sync_versions', 'signals', 'first_seen', 'last_seen',
                  'play_name', 'last_report', 'stack', 'sample_device', 'sample_version', 'console_url'):
            if k in old and k not in doc:
                doc[k] = old[k]          # keep lab/fix results the worker wrote; replace everything else
        keep = ('reproduced', 'not-reproduced', 'fix-proposed', 'fix-verified', 'fix-failed', 'lab-run-done')
        if old.get('status') in keep and doc.get('status') == 'triaged':
            doc['status'] = old['status']          # lab/fix outcomes survive a re-pull; '*-running' never does
        batch.set(ref, doc)              # full replace (no merge): stale map entries like old bucket counts disappear
        n += 1
        if n >= 400:
            batch.commit(); batch, n = db.batch(), 0
        continue
        put(ref, doc)
        counts['cases'] += 1
    run = (data.get('sources') or {}).get('lab_run') or 'unknown'
    for f in data.get('findings', []):
        doc = dict(f, run=run, updatedAt=firestore.SERVER_TIMESTAMP)
        if same(f"findings/{run}_{f['id']}", doc):
            continue
        put(db.collection('findings').document(f"{run}_{f['id']}"), doc)
        counts['findings'] += 1
    for i, r in enumerate((data.get('runlog') or {}).get('rows', [])):
        if same(f"runlog/{r['date']}_{r['flow']}_{r['mode']}_{i}", dict(r)):
            continue
        put(db.collection('runlog').document(f"{r['date']}_{r['flow']}_{r['mode']}_{i}"), dict(r))
        counts['runlog'] += 1
    bd = {'app': data.get('app'), 'sources': data.get('sources'), 'generated_at': data.get('generated_at'),
          'runlogSummary': (data.get('runlog') or {}).get('summary'), 'totalHours': (data.get('runlog') or {}).get('total_hours'),
          'latestRun': run}
    if not same('config/board', {k: v for k, v in bd.items() if k != 'generated_at'}):
        put(db.collection('config').document('board'), dict(bd, updatedAt=firestore.SERVER_TIMESTAMP))
    if n:
        batch.commit()
    try:
        _json.dump(cache, open(cpath, 'w'))
    except OSError:
        pass
    return counts
