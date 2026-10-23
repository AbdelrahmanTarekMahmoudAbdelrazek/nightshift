"""Same-bug families: cards whose crashes are one bug hit at different moments.

A card is one crashing function (ns/groups.py). Two cards are one bug when their field crashes come up the SAME call
path (identical caller code addresses in the same build), split inside the same function close together, touch the
same object type at the same field offset, and happened after the same kind of user activity. Everything here is read
from field data only (Crashlytics events in out/raw/), never from lab results, so a blind test stays blind.

Registry: out/families.json (+ Firestore `families/<id>` when a db is given).
  status 'suggested' = found by the score, shown with its evidence; 'confirmed' = a person said it is one bug;
  'rejected' = a person said it is not (never suggested again).
Only CONFIRMED families change lab verdicts (a crash of any member counts as the field crash; a fix must stop all).
"""
import hashlib
import json
import os
import re
import datetime as dt

from . import groups

HERE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT = os.path.join(HERE, 'out')
REG = os.path.join(OUT, 'families.json')
NATIVE = groups.NATIVE
SUGGEST_AT = 6          # score needed to suggest a link (max ~11)

# ───────────────────────── registry ─────────────────────────

def load():
    try:
        return json.load(open(REG))
    except Exception:
        return {'families': []}


def save(reg, db=None):
    os.makedirs(OUT, exist_ok=True)
    tmp = REG + '.tmp'
    json.dump(reg, open(tmp, 'w'), indent=1, default=str)
    os.replace(tmp, REG)
    if db is not None:
        try:
            for f in reg['families']:
                db.collection('families').document(f['id']).set(f)
        except Exception:
            pass


def fam_id(cards):
    return 'fam_' + hashlib.sha1('|'.join(sorted(cards)).encode()).hexdigest()[:10]


def family_of(card, status=('confirmed',)):
    for f in load().get('families') or []:
        if card in f['cards'] and f.get('status') in status:
            return f
    return None


def members(card, status=('confirmed',)):
    """The OTHER cards of this card's family (confirmed only by default)."""
    f = family_of(card, status)
    return [c for c in (f or {}).get('cards', []) if c != card]


def set_status(cards, status, by, why='', db=None, evidence=None, score=None, context=None):
    reg = load()
    fid = fam_id(cards)
    f = next((x for x in reg['families'] if x['id'] == fid), None)
    if f is None:
        f = {'id': fid, 'cards': sorted(cards), 'created': dt.datetime.now().isoformat(timespec='seconds')}
        reg['families'].append(f)
    f.update({'status': status, 'by': by, 'why': why, 'at': dt.datetime.now().isoformat(timespec='seconds')})
    if evidence is not None:
        f['evidence'] = evidence
    if score is not None:
        f['score'] = score
    if context is not None:
        f['context'] = context
    save(reg, db)
    if db is not None:                     # every member card carries the link, so the board shows one bug, not one card per stack
        try:
            for c in f['cards']:
                db.collection('cases').document(c).set(
                    {'family': [{'card': o, 'title': o} for o in f['cards'] if o != c] if status == 'confirmed' else [],
                     'familyId': fid if status == 'confirmed' else None}, merge=True)
        except Exception:
            pass
    return f

# ───────────────────────── field signatures ─────────────────────────

_SYM = {}


def _symbolizer(vc, vn):
    from . import symbolize
    k = (vc, vn)
    if k not in _SYM:
        p, _ = symbolize.resolve(vc, vn, NATIVE)
        _SYM[k] = symbolize.Symbolizer(p) if p else None
    return _SYM[k]


def _func(name):
    """'FramesHelper::run_renderer_thread(unsigned long long, bool) + 872' -> 'FramesHelper::run_renderer_thread'"""
    return groups._clean(re.sub(r'\s*\+\s*\d+$', '', name or ''))


def _types(name):
    """Class/struct names mentioned in a demangled frame (method owner + template args): the objects it works on."""
    s = re.sub(r'std::__ndk1::|std::', '', name or '')
    return {t for t in re.findall(r'\b([A-Z][A-Za-z0-9_]{3,})\b', s)} - {'unsigned', 'Status'}


def raw_events(issue):
    p = os.path.join(OUT, 'raw', issue, 'events.json')
    try:
        return json.load(open(p))
    except Exception:
        return []


def signature(e, symbolize=True):
    """One field event -> its crashed thread as (pc, lib, func) + fault + build + pre-crash context."""
    from . import crashlytics as cl
    t = cl.crashed_thread(e)
    ver = e.get('version') or {}
    vc, vn = ver.get('buildVersion'), ver.get('displayVersion')
    fr = [{'pc': int(f['address']) if str(f.get('address') or '').isdigit() else None,
           'lib': os.path.basename(f.get('library') or ''), 'func': f.get('symbol') or ''} for f in (t.get('frames') or [])]
    sym = _symbolizer(vc, vn) if symbolize else None
    idx = [i for i, f in enumerate(fr) if f['lib'] == NATIVE and f['pc'] is not None and not f['func']]
    if sym and idx:
        for i, r in zip(idx, sym.lookup([fr[i]['pc'] for i in idx])):
            fr[i]['func'] = r.get('func') or ''
            fr[i]['src'] = (r.get('srcline') or '').split(':')[0]
    try:
        fault = int(t.get('crashAddress') or 0)
    except (TypeError, ValueError):
        fault = 0
    return {'time': e.get('eventTime'), 'build': vc, 'version': vn,
            'device': (e.get('device') or {}).get('displayName'), 'os': (e.get('operatingSystem') or {}).get('displayVersion'),
            'signal': t.get('signal') or t.get('title'), 'fault': fault, 'frames': fr, 'context': context_of(e)}


_ISSUE = {}


def issue_signatures(issue):
    """All events of an issue as signatures, symbolized in ONE lookup per build (addr2line start-up is the slow part)."""
    if issue in _ISSUE:
        return _ISSUE[issue]
    evs = raw_events(issue)
    sigs = [signature(e, symbolize=False) for e in evs]
    by = {}
    for s in sigs:
        by.setdefault((s['build'], s['version']), []).append(s)
    for (vc, vn), ss in by.items():
        sym = _symbolizer(vc, vn)
        todo = [f for s in ss for f in s['frames'] if f['lib'] == NATIVE and f['pc'] is not None and not f['func']]
        if sym and todo:
            pcs = sorted({f['pc'] for f in todo})
            res = dict(zip(pcs, sym.lookup(pcs)))
            for f in todo:
                f['func'] = (res.get(f['pc']) or {}).get('func') or ''
                f['src'] = ((res.get(f['pc']) or {}).get('srcline') or '').split(':')[0]
    _ISSUE[issue] = sigs
    return sigs


def card_signatures(card):
    """Every sampled field event of a card, as signatures."""
    issue = groups.issue_of(card)
    out = []
    for s in issue_signatures(issue):
        fr = [{'func': f['func'], 'lib': f['lib']} for f in s['frames']]
        evs, _ = groups.card_events(card, [{'frames': fr}], NATIVE)
        if evs:
            out.append(s)
    return out

# ───────────────────────── pre-crash context (Part 2) ─────────────────────────

# named motifs; everything else that is a MsgLooper message or a UI breadcrumb becomes its own motif automatically
MOTIFS = [
    ('scrubbing (fast seeks)', None),                     # computed: >= 4 seek requests within 3 s
    ('decoder frame fetch interrupted by a seek', r'get_frame interrupted by new seek'),
    ('GL lease timeout / edit abandoned', r'lease TIMED OUT|force_quit_edit_state|GL ownership lease NOT acquired'),
    ('render stop requested', r'render stop requested|RenderStop'),
    ('teardown / surface destroyed', r'TEARDOWN|surfaceDestroyed|onDestroy|releaseEngine'),
    ('present deadline expired', r'present deadline expired'),
    ('decoder hard timeout', r'get_frame timed out|DROP hard timeout'),
]
WINDOW_S = 20


def _ts(s):
    m = re.search(r'(\d\d):(\d\d):(\d\d)(?:\.(\d+))?', s or '')
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + float('0.' + (m.group(4) or '0'))


def context_of(e):
    """Motifs in the last WINDOW_S seconds before the crash, plus per-event facts (timeline length)."""
    lines = []
    for l in e.get('logs') or []:
        lines.append((_ts(l.get('logTime')), l.get('message') or ''))
    for b in e.get('breadcrumbs') or []:
        lines.append((_ts(b.get('eventTime')), '[ui] ' + (b.get('title') or '')))
    lines = [x for x in lines if x[0] is not None]
    if not lines:
        return {'motifs': [], 'facts': {}}
    end = max(t for t, _ in lines)
    win = [(t, m) for t, m in lines if end - t <= WINDOW_S]
    mot = set()
    seeks = sorted(t for t, m in win if 'seek requested' in m)
    if any(sum(1 for u in seeks if 0 <= u - s <= 3) >= 4 for s in seeks):
        mot.add('scrubbing (fast seeks)')
    for name, rx in MOTIFS:
        if rx and any(re.search(rx, m) for _, m in win):
            mot.add(name)
    for _, m in win:
        mm = re.search(r'MsgLooper\.cpp, line: \d+\s+(Msg[A-Za-z]+)', m)
        if mm and mm.group(1) not in ('MsgUpdateVideoVolume', 'MsgLooper'):
            mot.add('msg:' + mm.group(1))
        if m.startswith('[ui] ') and m[5:]:
            mot.add('ui:' + re.sub(r'_(start|complete|clicked)$', '', m[5:]))
    facts = {}
    d = [int(x) for x in re.findall(r'Curve::get_duration duration=(\d+)', ' '.join(m for _, m in win))]
    if d:
        facts['timeline_s'] = round(max(d) / 1e6, 1)
    return {'motifs': sorted(mot), 'facts': facts}


def shared_context(sigs):
    """What every event of the family had in common before the crash, and what only some had."""
    sets = [set(s['context']['motifs']) for s in sigs if s.get('context')]
    if not sets:
        return {'shared': [], 'only_some': [], 'facts': []}
    allm = set().union(*sets)
    shared = set.intersection(*sets)
    facts = [f"{s['time']} {s['device']}: timeline {s['context']['facts'].get('timeline_s', '?')} s" for s in sigs]
    return {'shared': sorted(shared), 'only_some': sorted(allm - shared), 'facts': facts}

# ───────────────────────── scoring (Part 1) ─────────────────────────

def _app(fr):
    return [f for f in fr if f['lib'] == NATIVE]


def pair_score(a, b):
    """Two field events -> (score, evidence lines). Same build needed for the address checks."""
    ev, sc = [], 0
    fa, fb = _app(a['frames']), _app(b['frames'])
    if not fa or not fb:
        return 0, ['no app frames']
    if a['build'] == b['build']:
        n = 0                                               # identical caller pcs counted from the thread's bottom
        for x, y in zip(reversed(fa), reversed(fb)):
            if x['pc'] != y['pc']:
                break
            n += 1
        if n >= 3:
            sc += 3
            ev.append(f"same build {a['build']}: the bottom {n} app frames are at identical code addresses "
                      f"({' <- '.join(_func(f['func']).split('::')[-1] for f in fa[-n:][:4])}…)")
        sa, sb = fa[len(fa) - n - 1] if len(fa) > n else None, fb[len(fb) - n - 1] if len(fb) > n else None
        if n >= 2 and sa and sb and sa['func'] and _func(sa['func']) == _func(sb['func']) \
                and abs(sa['pc'] - sb['pc']) <= 4096:
            sc += 2
            ev.append(f"they split inside the same function {_func(sa['func'])}, {abs(sa['pc'] - sb['pc'])} bytes apart")
            if abs(sa['pc'] - sb['pc']) <= 512:
                sc += 1
    else:
        ca = [_func(f['func']) for f in fa[1:6]]
        cb = [_func(f['func']) for f in fb[1:6]]
        common = [x for x in ca if x in cb and x and not x.startswith(('std::', 'void*', '__'))]
        if len(common) >= 2:
            sc += 2
            ev.append(f"different builds; common callers: {', '.join(common[:3])}")
    ta = set().union(*[_types(f['func']) | _types(os.path.splitext(os.path.basename(f.get('src') or ''))[0]) for f in a['frames'][:2]])
    tb = set().union(*[_types(f['func']) | _types(os.path.splitext(os.path.basename(f.get('src') or ''))[0]) for f in b['frames'][:2]])
    # the top frame's own object (the inlined accessor shows only as a file name in the dump, so also the source file)
    common_t = (ta & tb) - {'FramesHelper', 'VideoPlayer'}
    if common_t:
        sc += 2
        ev.append(f"both crash on the same object type: {', '.join(sorted(common_t))}")
    if a['signal'] == b['signal'] and a['fault'] is not None and b['fault'] is not None \
            and (a['fault'] & 0xfff) == (b['fault'] & 0xfff) and 0 < (a['fault'] & 0xfff) < 0x200:
        sc += 1
        ev.append(f"same {a['signal']} field offset +{a['fault'] & 0xfff:#x} (faults {a['fault']:#x} / {b['fault']:#x})")
    sa_, sb_ = set(a['context']['motifs']), set(b['context']['motifs'])
    if sa_ and sb_:
        j = len(sa_ & sb_) / len(sa_ | sb_)
        strong = [m for m in sa_ & sb_ if not m.startswith(('msg:', 'ui:'))]
        if strong or j >= 0.4:
            sc += 1 + (1 if strong else 0)
            ev.append(f"same activity before the crash: {', '.join(sorted(sa_ & sb_))[:200]}")
    return sc, ev


def scan(issue_cards, log=print, db=None, only=None):
    """Score every pair of cards (best event pair each). New links above SUGGEST_AT are saved as 'suggested'."""
    sigs = {c: card_signatures(c) for c in issue_cards}
    reg = load()
    known = {f['id']: f for f in reg['families']}
    found = []
    cards = [c for c in issue_cards if sigs[c]]
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            if only and only not in (a, b):
                continue
            best = max(((pair_score(x, y), x, y) for x in sigs[a] for y in sigs[b]), key=lambda t: t[0][0])
            (sc, ev), x, y = best
            fid = fam_id([a, b])
            if sc < SUGGEST_AT:
                continue
            ctx = shared_context(sigs[a] + sigs[b])
            found.append((a, b, sc, ev))
            if fid in known and known[fid].get('status') in ('confirmed', 'rejected'):
                continue
            set_status([a, b], 'suggested', 'night shift (field stacks)', db=db, evidence=ev, score=sc, context=ctx)
            log(f"same-bug family suggested: {groups.label(a)} + {groups.label(b)} (score {sc}): " + '; '.join(ev)[:300])
    return found

def scan_card(card, log=print, db=None):
    """Compare one card with every registered card (any issue) that shares a caller function in its stack3.
    Cheap prefilter on the registries, full scoring only for those candidates."""
    import glob
    mine = groups.group_of(card) or {}
    callers = {x.strip() for x in (mine.get('stack3') or '').split('|')[1:] if x.strip()}
    cands = []
    for fn in glob.glob(os.path.join(groups.REG_DIR, '*.json')):
        if not re.fullmatch(r'[0-9a-f]{32}\.json', os.path.basename(fn)):
            continue
        try:
            reg = json.load(open(fn))
        except Exception:
            continue
        for g in reg.get('groups') or []:
            st = {x.strip() for x in (g.get('stack3') or '').split('|')[1:]}
            if g.get('card') != card and (groups.issue_of(g['card']) == groups.issue_of(card) or callers & st):
                cands.append(g['card'])
    return scan([card] + cands, log=log, db=db, only=card) if cands else []


# ───────────────────────── for the lab and the prompts (Parts 2, 3) ─────────────────────────

def expect_sets(card, expect_of):
    """[(card, label, expect list)] for every confirmed member; expect_of(card) gives a card's own frames."""
    out = []
    for m in members(card):
        try:
            ex = expect_of(m)
        except Exception:
            ex = []
        if ex:
            out.append((m, groups.card_title(m) or groups.label(m), ex))
    return out


def prompt_block(card):
    """Text for the root cause / repro / replay prompts: the family, its evidence, and what all its field events share."""
    f = family_of(card)
    if not f:
        return ''
    sigs = []
    for c in f['cards']:
        sigs += [dict(s, card=c) for s in card_signatures(c)]
    ctx = shared_context(sigs)
    lines = [f"SAME-BUG FAMILY (confirmed by {f.get('by')}): this crash and {len(f['cards']) - 1} other card(s) are ONE bug "
             f"hit at different moments. Your root cause, trigger and fix must explain and stop ALL of them."]
    for c in f['cards']:
        ss = [s for s in sigs if s['card'] == c]
        top = ' <- '.join(_func(fr['func']) for fr in _app(ss[0]['frames'])[:4]) if ss else '?'
        lines.append(f"- {groups.card_title(c) or groups.label(c)}{' (THIS card)' if c == card else ''}: {top}; "
                     + '; '.join(f"{s['time']} {s['device']} Android {s['os']} fault {s['fault']:#x}" for s in ss[:3]))
    lines.append('Why they are one bug: ' + '; '.join(f.get('evidence') or []))
    lines.append('Before EVERY event of the family: ' + (', '.join(ctx['shared']) or '(nothing in common in the logs)'))
    if ctx['only_some']:
        lines.append('Seen in SOME events only, so NOT required for the crash: ' + ', '.join(ctx['only_some'])[:600])
    lines.append('Per event: ' + '; '.join(ctx['facts']))
    lines.append('A lab crash with the stack of ANY card above counts as the field crash.')
    return '\n'.join(lines)
