"""Stack groups: one board card per real crash inside a mixed Crashlytics issue.

Crashlytics cannot read our native symbols, so it groups libMYJNILIB26.so crashes by library + fault: one issue can
hold several different bugs. Every sync keys each stack group of an issue by a stable fingerprint (the crashing
function = the top named app frame, offsets / arguments / templates / lambda numbers stripped; the top 3 frames are kept
for display) and keeps that list per issue for good. (Top 3 frames split one bug reached from different JNI callers,
e.g. MsgLooper::QueueMessage, into many cards: the engineer chose the crashing function, 14 Oct.)

  out/stackgroups/<issue>.json  (the pipeline's copy)  +  Firestore stackgroups/<issue>  (the same list, for the board)

Card ids: the FIRST group of an issue keeps the plain issue id forever (so a single-stack issue, and everything an
existing card already has, never moves). Every other group is a card '<issue>~<fp8>'. A group seen for the first
time after the issue was registered is a NEW STACK card; known cards never change target automatically.
A manual override still exists: out/pin_<card>.json {"signature_contains": "..."} picks the events of that card.
"""
import datetime as dt
import hashlib
import json
import os
import re

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(HERE, 'out')
REG_DIR = os.path.join(OUT, 'stackgroups')
NATIVE = 'libMYJNILIB26.so'
SKIP = ('std::', '__', 'operator ', 'operator(', 'void* std::', 'non-virtual thunk')
# Functions that say nothing about WHICH bug it is (every crash can pass through them): never a card key on their
# own, the key skips to the first meaningful app frame below them. libc/libc++ frames outside our .so are ignored anyway.
GENERIC = re.compile(r'^(?:abort|raise|exit|_exit|assert\w*|mem(?:cpy|move|set|cmp|chr)|str\w+|wcs\w+|malloc|calloc|realloc|free|'
                     r'operator\s*(?:new|delete)(?:\[\])?|std::__throw_\w+|std::terminate|__cxa_\w+|__gnu_cxx::\w+|'
                     r'_JNIEnv::\w+|JNIEnv\w*::\w+|JNIHelper::\w+|\w*Jni\w*Helper\w*::\w+|ScopedLocalRef\w*::\w+|'
                     r'\w+::(?:Log|log|logError|LogError|print\w*|check\w*|Assert\w*|abort\w*)|android_log_\w+|__android_log_\w+|'
                     r'shared_ptr\w*::\w+|unique_ptr\w*::\w+)$')
RE_CARD = re.compile(r'^([0-9a-f]{32})(?:~([0-9a-f]{8}))?$')


# ------------------------------------------------------------------ ids

def split(card):
    """'<issue>' -> (issue, None); '<issue>~<fp8>' -> (issue, fp8). Anything else -> (card, None)."""
    m = RE_CARD.match(str(card or '').strip())
    return (m.group(1), m.group(2)) if m else (str(card or '').strip(), None)


def issue_of(card):
    return split(card)[0]


def is_card(card):
    return split(card)[1] is not None


def k8(key):
    """Short file key of a crash. Plain ids keep their old key (first 8 chars) so no existing file moves; a split
    card gets 'g' + its fingerprint, so it never shares author/live/replay/fix files with its sibling bugs."""
    iss, fp = split(key)
    if fp:
        return 'g' + fp[:7]
    return re.sub(r'\W', '', str(key))[:8]


# ------------------------------------------------------------------ fingerprints

def _clean(fn):
    fn = str(fn or '').split(' + ')[0].strip()
    fn = re.sub(r'\$_\d+', '$_', fn)                 # lambda numbers change between builds
    depth, cut = 0, None
    for i, ch in enumerate(fn):                      # drop the argument list (first '(' outside template brackets)
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == '(' and depth <= 0:
            cut = i
            break
    if cut is not None:
        fn = fn[:cut]
    fn = re.sub(r'\s*\+\s*(0x)?[0-9a-fA-F]+$', '', fn).strip()
    prev = None
    while prev != fn:                                # templates out: MsgLooper::Set<std::tuple<...>> -> MsgLooper::Set
        prev, fn = fn, re.sub(r'<[^<>]*>', '', fn)
    return fn if fn.startswith('operator') else re.sub(r'^(?:(?:const|unsigned|signed|static|virtual)\s+)*[\w:*&]+\s+(?=[\w:~]+$)', '', fn).strip()   # return type out


KEY_FRAMES = 1                                       # the crashing function; registries of another depth are ignored
REG_VERSION = 2


def key_of(frames, native_lib=NATIVE, depth=None):
    """Card key: the top named app frame of the crashed thread (depth=3: the top 3, for display), or None when the top
    app frame has no name (unsymbolized build: such an event never creates or picks a group)."""
    depth = depth or KEY_FRAMES
    names, seen_top = [], False
    for f in frames or []:
        if f.get('lib') != native_lib:
            continue
        fn = f.get('func')
        if not seen_top:
            seen_top = True
            if not fn:
                return None
        if not fn:
            continue
        c = _clean(fn)
        if not c or c.startswith(SKIP) or c.startswith('std') or GENERIC.match(c):
            continue
        if c not in names:
            names.append(c)
        if len(names) >= depth:
            break
    return ' | '.join(names) or None


def fp8(key):
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def short_title(key):
    top = (key or '').split(' | ')[0]
    return top.split('::')[-1] or top


# ------------------------------------------------------------------ registry

def _path(issue):
    return os.path.join(REG_DIR, f'{issue}.json')


def load(issue, db=None):
    p = _path(issue)
    if os.path.exists(p):
        reg = json.load(open(p))
        if reg.get('version') == REG_VERSION:
            return reg
        return {'issue': issue, 'version': REG_VERSION, 'groups': []}   # an older trial keying: start over
    if db is not None:                               # the Mac lost its copy: Firestore keeps the same list
        try:
            d = db.collection('stackgroups').document(issue).get()
            if d.exists and (d.to_dict() or {}).get('version') == REG_VERSION:
                reg = d.to_dict() or {}
                reg.pop('updatedAt', None)
                save(issue, reg)
                return reg
        except Exception:
            pass
    return {'issue': issue, 'version': REG_VERSION, 'groups': []}


def save(issue, reg, db=None):
    os.makedirs(REG_DIR, exist_ok=True)
    tmp = _path(issue) + '.tmp'
    json.dump(reg, open(tmp, 'w'), indent=1)
    os.replace(tmp, _path(issue))
    if db is not None:
        from firebase_admin import firestore
        db.collection('stackgroups').document(issue).set(dict(reg, updatedAt=firestore.SERVER_TIMESTAMP))


def _locks_path():                                   # issue -> key of the bug that owns the plain id, written ONCE
    return os.path.join(REG_DIR, '_plain_locks.json')


def plain_lock(issue):
    try:
        return (json.load(open(_locks_path())) if os.path.exists(_locks_path()) else {}).get(issue)
    except Exception:
        return None


def _write_lock(issue, key, why, db=None):
    """The plain id of an issue belongs to one bug for good. Never overwritten (a registry reset, a new keying version
    or a sync where another stack has more events can not move it); only an engineer edits this file."""
    os.makedirs(REG_DIR, exist_ok=True)
    LOCKS = _locks_path()
    locks = json.load(open(LOCKS)) if os.path.exists(LOCKS) else {}
    if issue in locks:
        return locks[issue]
    locks[issue] = {'key': key, 'why': why, 'at': dt.datetime.now().isoformat(timespec='seconds')}
    tmp = LOCKS + '.tmp'
    json.dump(locks, open(tmp, 'w'), indent=1)
    os.replace(tmp, LOCKS)
    if db is not None:
        try:
            db.collection('stackgroups').document('_plain_locks').set({issue: locks[issue]}, merge=True)
        except Exception:
            pass
    return locks[issue]


def _seed_key(issue, keys, frames_of_case=None, native_lib=NATIVE):
    """Which group keeps the plain id when a mixed issue is registered: the stored lock (always wins, never
    recomputed), then the manual pin, then the stack the existing card was already built on (its lab work belongs to
    that bug), then the biggest group. Whatever is chosen is locked at once."""
    lk = plain_lock(issue)
    if lk:
        return lk['key'] if lk['key'] in keys else '__locked_absent__'
    pin = os.path.join(OUT, f'pin_{issue}.json')
    if os.path.exists(pin):
        want = (json.load(open(pin)).get('signature_contains') or '').strip()
        hit = [k for k in keys if want and want.split('::')[-1] in k]
        if hit:
            return hit[0]
    if frames_of_case:
        k = key_of(frames_of_case, native_lib)
        if k in keys:
            return k
    return None


def _case_frames(issue):
    import glob
    for p in glob.glob(os.path.join(OUT, f'*_{issue}_case_file.json')):
        try:
            return json.load(open(p)).get('frames') or []
        except Exception:
            pass
    return []


def assign(issue, events, db=None, native_lib=NATIVE, log=print, frames_key='frames'):
    """Register the stack groups of one issue from its sampled events. Returns (reg, by_card) where by_card maps
    every card id of the issue to its events. Events without a usable key go to no card unless the issue has one card."""
    reg = load(issue, db)
    reg['version'] = REG_VERSION
    groups = reg.setdefault('groups', [])
    known = {g['key']: g for g in groups}
    keyed = [(key_of(e.get(frames_key), native_lib), e) for e in events]
    top3 = {}
    for k, e in keyed:
        if k and k not in top3:
            top3[k] = key_of(e.get(frames_key), native_lib, depth=3) or k
    cnt = {}
    for k, _ in keyed:
        if k:
            cnt[k] = cnt.get(k, 0) + 1
    order = sorted(cnt, key=lambda k: -cnt[k])
    now = dt.datetime.now().isoformat(timespec='seconds')
    changed = False
    if not groups and order:
        first = _seed_key(issue, order, _case_frames(issue), native_lib) or order[0]
        if first == '__locked_absent__':             # the locked bug is not in this sample: it keeps the plain id anyway
            lk = plain_lock(issue)['key']
            g = {'key': lk, 'fp': fp8(lk), 'card': issue, 'title': short_title(lk), 'stack3': lk, 'firstSeen': now,
                 'newStack': False, 'origin': 'plain-id lock (no event in this sample)'}
            groups.append(g); known[lk] = g
            for k in order:
                g = {'key': k, 'fp': fp8(k), 'card': f'{issue}~{fp8(k)}', 'title': short_title(k), 'stack3': top3.get(k, ''),
                     'firstSeen': now, 'newStack': False, 'origin': 'split at first sync'}
                groups.append(g); known[k] = g
            order = []
            changed = True
        else:
            _write_lock(issue, first, 'pin / existing case' if _seed_key(issue, order, _case_frames(issue), native_lib) else 'most sampled events at first registration', db)
            order = [first] + [k for k in order if k != first]
        for i, k in enumerate(order):
            g = {'key': k, 'fp': fp8(k), 'card': issue if i == 0 else f'{issue}~{fp8(k)}', 'title': short_title(k), 'stack3': top3.get(k, ''),
                 'firstSeen': now, 'newStack': False, 'origin': 'first sync' if i == 0 else 'split at first sync'}
            groups.append(g); known[k] = g
        changed = True
        if len(order) > 1:
            log(f'stack groups: {issue[:8]} holds {len(order)} different crashes: '
                + '; '.join(f"{g['card'][:8]}{'~' + g['fp'] if '~' in g['card'] else ''} = {g['title']}" for g in groups))
    else:
        for k in order:
            if k in known:
                continue
            g = {'key': k, 'fp': fp8(k), 'card': f'{issue}~{fp8(k)}', 'title': short_title(k), 'stack3': top3.get(k, ''), 'firstSeen': now,
                 'newStack': True, 'origin': 'new stack in a later sync'}
            groups.append(g); known[k] = g
            changed = True
            log(f'STACK GROUP ADDED: {issue[:8]}~{g["fp"]} = {k} ({cnt[k]} sampled events); the existing card(s) keep their target')
    for g in groups:                                 # counts of the latest sample, for the board
        g['sampled'] = cnt.get(g['key'], 0)
    reg['cards'] = len(groups)
    if groups:
        reg['plainKey'] = next((g['key'] for g in groups if g['card'] == issue), None)
        lk = plain_lock(issue)
        if lk and reg['plainKey'] != lk['key']:      # can only happen if someone edited the registry by hand
            log(f'stack groups: WARNING {issue[:8]} plain id is {reg["plainKey"]} but the lock says {lk["key"]}; the lock file wins next reset')
    if changed or (db is not None and groups):
        save(issue, reg, db)
    by_card = {g['card']: [e for k, e in keyed if k == g['key']] for g in groups}
    if len(groups) <= 1:                             # single stack: every event belongs to the one card
        by_card = {(groups[0]['card'] if groups else issue): [e for _, e in keyed]}
    return reg, by_card


def group_of(card, db=None):
    """The registry entry of a card, or None (issue never split / never synced)."""
    iss, _ = split(card)
    for g in load(iss, db).get('groups', []):
        if g['card'] == card:
            return g
    return None


def card_events(card, events, native_lib=NATIVE, frames_key='frames', db=None):
    """The events of THIS card only. Pin file first (manual override), then the registry. A plain id of an issue
    that was never split keeps every event (nothing changes for single-stack issues)."""
    pin = os.path.join(OUT, f'pin_{card}.json')
    if os.path.exists(pin):
        want = (json.load(open(pin)).get('signature_contains') or '').strip()
        mine = [e for e in events if want and any(want in str(f.get('func') or '') for f in (e.get(frames_key) or [])[:6])]
        if mine:
            return mine, f'pinned to "{want}" ({os.path.basename(pin)})'
    reg = load(split(card)[0], db)
    gs = reg.get('groups') or []
    if len(gs) <= 1:
        return list(events), None
    g = next((g for g in gs if g['card'] == card), None)
    if g is None:
        return list(events), f'card {card} is not in the stack-group registry: all events used'
    mine = [e for e in events if key_of(e.get(frames_key), native_lib) == g['key']]
    return mine, f"card {g['title']}: {len(mine)} of {len(events)} sampled events (1 of {len(gs)} crashes in Crashlytics issue {split(card)[0][:8]})"


def card_title(card, db=None):
    iss, _ = split(card)
    g = group_of(card, db)
    return f"{iss[:8]} · {g['title']}" if g else iss[:8]


def label(key):
    """How a crash is named in jobs.log: plain ids as before (first 12 chars), split cards as '<issue8>~<fp8>'."""
    iss, fp = split(key)
    return f'{iss[:8]}~{fp}' if fp else str(key)[:12]


def find_card(frames, native_lib=NATIVE, exclude=None):
    """Which known card (any issue) a lab crash belongs to: same crashing function as a registered stack group.
    -> (card id, title) or (None, None). `exclude` = the card under test (its own crash is the field crash)."""
    k = key_of(frames, native_lib)
    if not k or not os.path.isdir(REG_DIR):
        return None, None
    for fn in sorted(os.listdir(REG_DIR)):
        if not re.fullmatch(r'[0-9a-f]{32}\.json', fn):
            continue
        try:
            reg = json.load(open(os.path.join(REG_DIR, fn)))
        except Exception:
            continue
        for g in reg.get('groups') or []:
            if g.get('key') == k and g.get('card') != exclude:
                return g['card'], f"{g['card'][:8]} · {g.get('title') or k}"
    return None, None
