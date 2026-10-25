"""Step 5 for every problem on the board: root cause + diagrams, no code changes.

For each row of `merged` (Play x Firebase), most important first, it gathers the evidence both consoles have:
  - Firebase: symbolized crashed frames (per-build .so from the symbol store), breadcrumbs, devices (case.build)
  - Google Play: the symbolized sample stack, devices and dates
  - this repo: the located function bodies and their callers
and asks Claude (skill crash-analysis) for a strict JSON answer: summary, root cause, evidence, owner, confidence,
fix direction in words (never code), how to reproduce, and two Mermaid diagrams (how it crashes / how the fix stops it).
Results land in merged/<id>.analysis (and the Crashlytics case's narrative). Already-analysed rows are skipped unless
their evidence changed, so the daily sync only pays for new problems.
"""
import datetime as dt
from collections import Counter
import hashlib
import json
import os
import re

from . import case as casemod
from . import config, llm, locate, review, source, symbolize, threads, timeline
from . import crashlytics as cl

KNOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'knowledge')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'analysis')
NATIVE = 'libMYJNILIB26.so'
VERSION = 3      # bump when the evidence or the skill changes: every problem is re-analysed on the next sync
RE_PLAY_NATIVE = re.compile(r'#\d+\s+pc\s+(?:0x)?[0-9a-fA-F]+\s+(\S+)\s*(.*)$', re.M)
RE_PLAY_JAVA = re.compile(r'^\s*at\s+([\w$.<>]+)\s*\(([^)]*)\)', re.M)


def play_frames(text):
    """Play's symbolized stack -> frames list in the same shape the Crashlytics side uses."""
    fr = []
    for m in RE_PLAY_NATIVE.finditer(text or ''):
        rest = m.group(2).split(' (BuildId')[0].strip()
        fn = re.sub(r'\+\d+$', '', rest[1:-1] if rest.startswith('(') and rest.endswith(')') else rest).strip()
        fr.append({'lib': m.group(1).split('/')[-1], 'func': fn})
    for m in RE_PLAY_JAVA.finditer(text or ''):
        fr.append({'lib': '', 'func': m.group(1), 'file': m.group(2)})
    return fr[:30]


BLIND_DENY = None   # set by the worker for a blind test: paths/tools the root-cause model must not use (.git, lab notes, ...)


def knowledge(m):
    """Team knowledge for this problem: matching files in knowledge/ plus the board note. Verified by engineers."""
    hay = json.dumps({k: v for k, v in m.items() if k not in ('analysis', 'analysis_key', 'analysedAt', 'note')}, default=str)
    out = []
    for fn in sorted(os.listdir(KNOW)) if os.path.isdir(KNOW) else []:
        if not fn.endswith('.md') or fn.lower() == 'readme.md':
            continue
        txt = open(os.path.join(KNOW, fn), encoding='utf-8').read()
        mt = re.search(r'^match:\s*(.+)$', txt, re.M)
        pats = [x.strip() for x in (mt.group(1).split(',') if mt else []) if x.strip()]
        if any(p in hay for p in pats):
            out.append({'file': f'knowledge/{fn}', 'text': txt.strip()[:6000]})
    if (m.get('note') or '').strip():
        out.append({'file': f"board note by {m.get('noteBy') or 'staff'}", 'text': m['note'].strip()[:3000]})
    return out


def _basis(m):
    """What the root cause was based on: event count (both consoles) and builds seen. Stored with the analysis."""
    ev = int((m.get('fb') or {}).get('events') or 0) + int((m.get('play') or {}).get('events') or 0)
    return {'events': ev, 'builds': sorted(str(b) for b in (m.get('builds') or []))}


def _grew(m):
    """Re-analyse an unchanged problem when the field gave much more to read: 50%+ more events (and at least 3 more),
    or a build it was not seen on before. Problems analysed before this existed get their basis on the next redo."""
    old = m.get('analysis_basis')
    if not old or not m.get('analysis'):
        return False
    now = _basis(m)
    more = now['events'] - int(old.get('events') or 0)
    return (more >= 3 and now['events'] >= 1.5 * max(1, int(old.get('events') or 0))) or \
        bool(set(now['builds']) - set(old.get('builds') or []))


def _key(m):
    return hashlib.sha1(json.dumps([m.get('title'), (m.get('play') or {}).get('id'), (m.get('fb') or {}).get('id'),
                                    m.get('match'), knowledge(m), VERSION, (m.get('fb') or {}).get('group'),
                                    'threads-v1' if m.get('kind') == 'ANR' else '',
                                    len((m.get('play') or {}).get('stack') or '') > 6000], sort_keys=True).encode()).hexdigest()[:16]


def _json(txt):
    """First {...} object in the model's answer (it may wrap it in a code fence)."""
    if not txt:
        return None
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', txt.strip(), flags=re.M)
    start = t.find('{')
    while start >= 0:
        depth, ins, esc = 0, False, False
        for i in range(start, len(t)):
            c = t[i]
            if ins:
                esc = (c == '\\' and not esc)
                if c == '"' and not esc:
                    ins = False
                continue
            if c == '"':
                ins = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except ValueError:
                        break
        start = t.find('{', start + 1)
    return None


def _clip(s, n):
    s = s or ''
    return s if len(s) <= n else s[:n] + '\n…'


def _events(iid):
    """Every sampled event of a Crashlytics issue (saved by case.build), summarised and symbolized per build.
    A card id ('<issue>~<fp8>', or a plain id of a split issue) returns that card's events only."""
    from . import groups
    card, iid = iid, groups.issue_of(iid)
    p = os.path.join(os.path.dirname(OUT), 'raw', iid, 'events.json')
    if not os.path.exists(p):
        return []
    evs = [cl.summarise_event(e) for e in json.load(open(p))]
    for e in evs:
        try:
            symbolize.symbolize_frames(e['frames'], e.get('version_code'), NATIVE, (e.get('version') or '').split(' ')[0])
        except Exception:
            pass
    return groups.card_events(card, evs, NATIVE)[0]


def _raw_event(iid, summ):
    """The raw Crashlytics event (all threads) behind a summarised one."""
    from . import groups
    p = os.path.join(os.path.dirname(OUT), 'raw', groups.issue_of(iid), 'events.json')
    for e in json.load(open(p)) if os.path.exists(p) else []:
        if (e.get('eventTime') or e.get('receivedTime')) == summ.get('time'):
            return e
    return None


def all_events(iid, group=None):
    evs = _events(iid)
    return timeline.evidence(evs, group) if evs else {}


def evidence(db, cfg, m, log):
    ev = {'problem': {k: m.get(k) for k in ('kind', 'title', 'subtitle', 'match', 'proof')},
          'builds': m.get('builds')}
    if m.get('instanceSummary'):
        ev['instances'] = {'summary': m['instanceSummary'],
                           'rows': [{k: r.get(k) for k in ('src', 'dupMatch', 'time', 'build', 'device', 'alias', 'os', 'phone', 'deltaS')}
                                    for r in (m.get('instances') or [])[:30]]}
    tk = knowledge(m)
    if tk:
        ev['team_knowledge'] = tk
    try:                                              # confirmed same-bug family: read its members' field events too
        from . import bugfamily as _bf
        card = (m.get('fb') or {}).get('id') or m.get('caseId') or ''
        fam = _bf.prompt_block(card) if card else ''
        if fam:
            ev['same_bug_family'] = fam
            ev['same_bug_family_events'] = {c: (all_events(c).get('events') or []) for c in _bf.members(card)}
    except Exception as e:
        log(f'same-bug family: not read ({e})')
    if m.get('_related'):                         # the same problem reported as other clusters: read them all together
        ev['related_reports'] = related_evidence(m, m['_related'], log)
        ev['related_note'] = ('related_reports are OTHER Firebase/Play clusters of this same problem (same crashing '
                              'function). Treat every one of their events as an instance: the trigger you name must explain them too.')
    frames, rec = [], None
    fb, pl = m.get('fb'), m.get('play')
    if fb and fb.get('id'):
        try:
            rec = casemod.build(fb['id'], cfg, use_llm=False)          # pulls events, symbolizes with the per-build .so
            casemod.write(rec)
            frames = rec.get('frames') or []
            ev['firebase'] = {'users': fb.get('users'), 'events': fb.get('events'), 'title': rec.get('title'),
                              'subtitle': rec.get('subtitle'), 'signal': rec.get('signal'),
                              'devices': (fb.get('devices') or [])[:10], 'android': rec.get('android'),
                              'crashed_thread': _thread_lines(frames)}
            ev['all_events'] = all_events(fb['id'], None)   # fb.id is the card: its events only (groups.card_events)
            if ev['all_events'].get('events'):            # crashed thread from THIS crash's events, not another group's
                g = ev['all_events']['stack_group']
                frames = next((e['frames'] for e in _events(fb['id']) if timeline.signature(e['frames']) == g), frames)
                ev['firebase']['crashed_thread'] = _thread_lines(frames)
        except BaseException as e:                                 # SystemExit from the API helpers included
            ev['firebase'] = {'users': fb.get('users'), 'events': fb.get('events'), 'devices': (fb.get('devices') or [])[:10],
                              'note': f'details could not be pulled: {str(e)[:200]}'}
    if m.get('kind') == 'ANR':                        # ANR: the cause is usually the thread main waits for, read them all
        ev['all_threads'] = {}
        if fb and fb.get('id'):
            evs = _events(fb['id'])
            g = (ev.get('all_events') or {}).get('stack_group')
            e0 = next((e for e in evs if not g or timeline.signature(e['frames']) == g), None)
            raw = _raw_event(fb['id'], e0) if e0 else None
            if raw:
                vc = (raw.get('version') or {}).get('buildVersion')
                vn = ((raw.get('version') or {}).get('displayVersion') or '').split(' ')[0]
                ev['all_threads']['firebase'] = threads.digest(threads.from_crashlytics(
                    raw, lambda fr: symbolize.symbolize_frames(fr, vc, NATIVE, vn)))
        if pl and pl.get('stack'):
            ev['all_threads']['google_play'] = threads.digest(threads.from_play(pl['stack']))
        # who waits for whom, for EVERY sampled ANR (Firebase events of this group + the Play dump), and whether the
        # samples agree on where the chain ends (if not, this issue holds more than one ANR)
        chains = []
        if fb and fb.get('id'):
            g = (ev.get('all_events') or {}).get('stack_group')
            for e in _events(fb['id']):
                if g and timeline.signature(e['frames']) != g:
                    continue
                raw = _raw_event(fb['id'], e)
                if raw:
                    vc = (raw.get('version') or {}).get('buildVersion')
                    vn = ((raw.get('version') or {}).get('displayVersion') or '').split(' ')[0]
                    c = threads.wait_chain(threads.from_crashlytics(raw, lambda fr, vc=vc, vn=vn: symbolize.symbolize_frames(fr, vc, NATIVE, vn)))
                    if c:
                        chains.append({'source': f"firebase {e.get('time')} {e.get('device')}", **c})
        if pl and pl.get('stack'):
            c = threads.wait_chain(threads.from_play(pl['stack']))
            if c:
                chains.append({'source': 'google play sample', **c})
        if chains:
            ends = Counter(c['end'] for c in chains)
            ev['wait_chains'] = {'per_sample': chains[:6], 'agreement': {k: f'{v}/{len(chains)} samples' for k, v in ends.most_common()},
                                 'deadlock_in_any': any(c.get('deadlock') for c in chains)}
    if pl:
        pf = play_frames(pl.get('stack', ''))
        if not frames or not any(f.get('func') for f in frames):
            frames = pf
        ev['google_play'] = {'users': pl.get('users'), 'events': pl.get('events'), 'last_seen': pl.get('last'),
                             'devices': (pl.get('devices') or [])[:10],
                             'sample_stack': _clip('\n'.join((pl.get('stack') or '').splitlines()[:(25 if m.get('kind') == 'ANR' else 70)]), 6000)}
    try:                                          # the fault address says null vs freed vs wild before any theory does
        fid = (fb or {}).get('id')
        from . import groups as _g
        rawp = os.path.join(OUT, '..', 'raw', _g.issue_of(fid), 'events.json') if fid else ''
        mine = {e.get('time') for e in _events(fid)} if fid else set()   # this card's events only
        subs = []
        if rawp and os.path.exists(rawp):
            for e in json.load(open(rawp)):
                if mine and (e.get('eventTime') or e.get('receivedTime')) not in mine:
                    continue
                t = next((t for t in e.get('threads') or [] if t.get('crashed')), {})
                subs.append(t.get('subtitle') or '')
        elif rec and rec.get('subtitle'):
            subs.append(rec['subtitle'])
        addrs = [int(m.group(1), 16) for x in subs for m in [re.search(r'(?:SIG\w+)\s+0x([0-9a-fA-F]+)', x)] if m]
        if addrs:
            low = [a for a in addrs if a < 0x10000]
            ev['fault_address'] = {
                'addresses': sorted({hex(a) for a in addrs})[:8], 'events': len(addrs),
                'reading': (f'{len(low)}/{len(addrs)} events fault at a tiny address ({", ".join(sorted({hex(a) for a in low})[:4])}): '
                            'that is a field offset on a NULL object pointer (null dereference), NOT freed memory. Explain the '
                            'crash with the pointer being null first.') if low else
                           'fault addresses are not near zero: freed/wild pointer or corrupted object; null alone does not explain it'}
    except Exception as e:
        log(f'  fault address not read: {str(e)[:120]}')
    # read the code AS SHIPPED: the commit the crashing build was made from (ns/source.py), not the working copy
    codes = [r.get('build') for r in (m.get('instances') or []) if r.get('build')] or \
            [re.sub(r'.*\((\d+)\).*', r'\1', b) for b in (m.get('builds') or [])]
    pick = max(set(codes), key=codes.count) if codes else None
    from . import sync as _sync
    src = source.ref_for(pick, _sync.live_version(cfg) or None, cfg) if pick else None
    locate.set_sha(src['sha'] if src else None)
    if src:
        try:                                       # a pinned submodule commit that was never pushed: closest one, APK-checked
            from . import apkjava
            for sub in source.describe(src['sha'], src['ref']).get('missing') or []:
                if apkjava.best_submodule_commit(sub, src['sha'], apkjava.find_apk(pick), log=log):
                    source._subs.pop((sub, src['sha']), None)
        except Exception as e:
            log(f'  submodule fallback skipped: {str(e)[:120]}')
        ev['source'] = {'build': pick, **source.describe(src['sha'], src['ref']),
                        'note': 'code below is from the commit this build was made from, not the current branch'}
        try:                                       # Java side: are the classes in this build's APK the ones at that commit?
            from . import apkjava
            j = apkjava.check(pick, sha=src['sha'])
            ev['source']['java'] = {k: j.get(k) for k in ('verdict', 'rate', 'judged', 'matched', 'not_at_commit', 'why')}
        except Exception as e:
            ev['source']['java'] = {'verdict': 'unknown', 'why': f'APK check failed: {str(e)[:120]}'}
    # attach OUR code: skip libc++/std wrappers (condition_variable::wait, __assoc_state::move, ...) that sit on top
    # of every blocking wait; they are never in the repo and used to take all 3 slots (ANRs then had no code at all)
    def _ours(f):
        fn = re.sub(r'\s*\+\s*\d+$', '', (f.get('func') or '').strip())
        bare = re.sub(r'^[\w:<>*&\s]*?\s(?=[\w:]+::)', '', fn)          # 'double Message::GetResult<double>' -> 'Message::GetResult<double>'
        return fn and not bare.startswith(('std::', '__')) and 'std::__ndk1::' not in bare.split('<')[0] \
            and not fn.startswith(('kotlinx.', 'kotlin.', 'android.', 'com.android.', 'java.', 'org.greenrobot.'))
    code_frames = [f for f in frames if _ours(f)] or frames
    code = locate.locate(code_frames, NATIVE, limit=4) if frames else []
    ev['code'] = [{'func': c['func'][:160], 'file': c.get('file'), 'line': c.get('line'),
                   'body': _clip(c.get('body', ''), 3500), 'callers': (c.get('callers') or [])[:8]} for c in code if c.get('found')]
    ev['code_not_in_repo'] = [c['func'][:160] for c in code if not c.get('found')]
    if frames and not ev['code'] and any((f.get('lib') == NATIVE) for f in frames):
        log(f"  WARNING: {m.get('id', '')[:14]}: our frames are on the stack but no code was attached ({', '.join(ev['code_not_in_repo'][:3])[:200]})")
    return ev, rec


_FILES = None
import threading as _threading
_FILES_LOCK = _threading.Lock()


def file_index(text):
    """Bare file names the answer cites (JNI.cpp:3020) -> repo path, so the board can link them to Bitbucket."""
    global _FILES
    with _FILES_LOCK:
      if _FILES is None:
        _FILES = {}
        for root in ('app/src/main/cpp', 'app/src/main/java') + locate.JAVA_ROOTS:
            for d, _, fs in os.walk(os.path.join(config.REPO, root)):
                if '/build/' in d + '/' or '/.cxx' in d:
                    continue
                for f in fs:
                    if f.endswith(('.cpp', '.h', '.hpp', '.cc', '.kt', '.java')):
                        _FILES.setdefault(f, []).append(os.path.relpath(os.path.join(d, f), config.REPO))
    out = {}
    for name in set(re.findall(r'([\w.-]+\.(?:cpp|h|hpp|cc|kt|java)):\d+', text or '')):
        hits = _FILES.get(name) or []
        if len(hits) == 1:
            out[name] = hits[0]
    return out


def _shrink(ev):
    """Same evidence, smaller: shorter timelines and code bodies, only the threads that matter."""
    e = json.loads(json.dumps(ev, default=str))
    for x in (e.get('all_events') or {}).get('events', []) or []:
        x['timeline_oldest_first'] = (x.get('timeline_oldest_first') or '')[-2500:]
    if e.get('all_events'):
        e['all_events']['events'] = e['all_events'].get('events', [])[:3]
    for src in (e.get('all_threads') or {}).values():
        if isinstance(src, dict):
            src.pop('other_busy_threads', None); src.pop('idle_threads_by_name', None)
            src['our_code_or_lock_threads'] = src.get('our_code_or_lock_threads', [])[:8]
    for c in e.get('code', []) or []:
        c['body'] = (c.get('body') or '')[:1500]
    if e.get('google_play'):
        e['google_play']['sample_stack'] = (e['google_play'].get('sample_stack') or '')[:2500]
    return e


OURS = ('libMYJNILIB26', 'com.myzesty', 'com.video.myzesty', 'com.ai.myzesty', 'com.picker.', 'com.common.myzesty',
        'com.overlay', 'myzesty')


def _engine_fn(text):
    """'libMYJNILIB26.so MsgLooper::QueueMessage(std::shared_ptr..)' -> 'MsgLooper::QueueMessage'; None for library frames."""
    t = str(text or '')
    if 'libMYJNILIB26' not in t:
        return None
    fn = re.sub(r'\(.*$', '', t.split('libMYJNILIB26.so', 1)[1]).strip(' ]-')
    fn = re.sub(r'^.*? - ', '', fn).strip()          # '[lib] File.cpp - Class::fn' -> 'Class::fn'
    if not fn or fn.startswith(('std::', '__', 'operator', 'void ', 'non-virtual', '0x')) or '::' not in fn:
        return None                                  # a library frame (std::future, operator new) says nothing about the cause
    return fn


def family_key(m):
    """Same crashing function in our engine = same problem, even when Crashlytics and Play split it into several
    clusters (different build, offset, inlined caller, or a title naming only libc/libc++). Key: kind + the first
    engine function of the title, else of the top frames (Firebase, then Play)."""
    cands = [m.get('title')] + list((m.get('fb') or {}).get('top') or [])[:8] + list((m.get('play') or {}).get('top') or [])[:8]
    for t in cands:
        fn = _engine_fn(t)
        if fn:
            return (m.get('kind') or 'CRASH', fn)
    return None                                      # no engine frame (Java, system): never grouped here


def _worked(r):
    """A report that already has a root cause or a verified fix stays the main one, so new clusters join it."""
    return 2 if r.get('fixState') else 1 if r.get('analysis') else 0


def families(rows):
    """{merged id: [ids of every report cluster of the same problem]}. The primary of a family is the one already worked
    on (verified fix, then root cause), then the one with the most field data; it gets the analysis, the others point to it."""
    fam = {}
    for r in rows:
        k = family_key(r)
        if k:
            fam.setdefault(k, []).append(r)
    out = {}
    for k, rs in fam.items():
        rs.sort(key=lambda r: (-_worked(r), r.get('match') != 'both', -(((r.get('fb') or {}).get('events') or 0) + ((r.get('play') or {}).get('events') or 0))))
        for r in rs:
            out[r['id']] = [x['id'] for x in rs]
    return out


def related_evidence(m, rel, log=print):
    """Every other report cluster of the same problem, read together with this one: devices, builds, Play sample
    stacks, and for Crashlytics clusters every sampled event with its breadcrumb timeline."""
    out = []
    for r in rel:
        fb, pl = r.get('fb') or {}, r.get('play') or {}
        x = {'cluster': r['id'], 'source': r.get('match'), 'firebase_events': fb.get('events'), 'play_events': pl.get('events'),
             'users': max(fb.get('users') or 0, pl.get('users') or 0), 'builds': r.get('builds'),
             'devices': ((fb.get('devices') or []) + (pl.get('devices') or []))[:10]}
        if pl.get('stack'):
            x['play_sample_stack'] = _clip('\n'.join(pl['stack'].splitlines()[:(25 if m.get('kind') == 'ANR' else 45)]), 3000)
            if m.get('kind') == 'ANR':
                c = threads.wait_chain(threads.from_play(pl['stack']))
                if c:
                    x['wait_chain'] = c
        if fb.get('id'):
            try:
                x['events'] = all_events(fb['id'], fb.get('group')).get('events') or []
            except Exception as e:
                x['events_error'] = str(e)[:150]
        out.append(x)
    return out


def _has_engine(m):
    """True when the crashing stack (crash) or the main thread (ANR) has a frame in our native engine."""
    parts = [str(m.get('title') or '')]
    for side in ('fb', 'play'):
        for f in ((m.get(side) or {}).get('top') or [])[:15]:
            parts.append(json.dumps(f, default=str) if not isinstance(f, str) else f)
    if m.get('kind') != 'ANR':                      # a crash's Play stack is the crashing thread only
        parts.append(str((m.get('play') or {}).get('stack') or '')[:6000])
    return 'libMYJNILIB26' in ' '.join(parts)


def _thread_lines(frames, cap=40):
    """Crashed thread for the prompt: runs of unnamed frames of one library collapse to one line, so our own frames
    (often below 20+ driver frames) are always included."""
    out, run = [], None
    for f in frames:
        lib, fn = f.get('lib', ''), (f.get('func') or '').strip()
        if not fn:
            if run and run[0] == lib:
                run[1] += 1
                continue
            run = [lib, 1]
            out.append(run)
            continue
        run = None
        loc = f" ({f.get('file')}:{f.get('line')})" if f.get('file') and f.get('line') else (f" ({f.get('srcline')})" if f.get('srcline') else '')
        out.append(f'{lib} {fn}{loc}'.strip())
    lines = [x if isinstance(x, str) else (f'{x[0]} x{x[1]} frames (no symbols)' if x[1] > 1 else f'{x[0]} (no symbols)') for x in out]
    return lines[:cap]


def _model_for(m, cfg, frames=None):
    """Cheaper model (llm.model_thirdparty, e.g. sonnet) for crashes that are not in our code: none of the top frames
    is ours and the last analysis (if any) did not blame the engine or the app. Our own crashes keep the default."""
    alt = (cfg.get('llm') or {}).get('model_thirdparty') or ''
    if not alt:
        return ''
    owner = ((m.get('analysis') or {}).get('owner') or '').lower()
    if owner in ('engine', 'app-java', 'app', 'mixed'):
        return ''
    tops = []
    for side in ('fb', 'play'):
        for f in ((m.get(side) or {}).get('top') or [])[:8]:
            tops.append(json.dumps(f, default=str) if not isinstance(f, str) else f)
    tops += [f"{f.get('lib', '')} {f.get('func') or ''}" for f in (frames or [])]   # the pulled, symbolized stack too
    hay = ' '.join(tops) + ' ' + str(m.get('title') or '')
    if any(o in hay for o in OURS):
        return ''
    return alt if (tops or owner in ('third-party', 'system')) else ''


def field_file(mid):
    return os.path.join(OUT, f'{mid}.field.json')


def analyse_one(db, cfg, m, log):
    ev, rec = evidence(db, cfg, m, log)
    try:                                             # every field instance, kept for the repro author (reads them all)
        json.dump({'kind': m.get('kind'), 'firebase_events': (ev.get('all_events') or {}).get('events') or [],
                   'shared_across_events_final_20s': (ev.get('all_events') or {}).get('shared_across_events_final_20s'),
                   'google_play': ev.get('google_play'), 'related_reports': ev.get('related_reports') or [],
                   'wait_chains': ev.get('wait_chains')}, open(field_file(m['id']), 'w'), indent=1, default=str)
    except Exception as e:
        log(f'  field instances not saved: {str(e)[:120]}')
    prompt = ('Analyse this production problem of the MyZesty Android app (native video engine libMYJNILIB26.so + Java/Kotlin app). '
              'Answer with the JSON object described in your instructions and nothing else.\n\n'
              + json.dumps(ev, indent=1, default=str))
    tag = f"{m['id']}.analysis"
    mdl = _model_for(m, cfg, (rec or {}).get('frames') or [])
    if mdl:
        log(f'  {m.get("title", "")[:60]}: not our code (third-party/system), analysed with {mdl}')
    txt = llm.run('crash-analysis', prompt, cfg, OUT, tag, model=mdl, deny=BLIND_DENY)
    a = _json(txt)
    if not a:                                        # the CLI sometimes dies on one input every time: retry smaller
        small = _shrink(ev)
        log(f'  retrying {m["id"][:30]} with compact evidence ({len(json.dumps(small, default=str))} chars)')
        txt = llm.run('crash-analysis', prompt.split('\n\n', 1)[0] + '\n\n' + json.dumps(small, indent=1, default=str),
                      cfg, OUT, tag + '.compact', model=mdl, deny=BLIND_DENY)
        a = _json(txt)
    if not a:
        return None, rec
    keep = ('summary', 'root_cause', 'trigger', 'timeline', 'hypotheses', 'evidence', 'owner', 'confidence',
            'severity', 'fix_direction', 'repro', 'diagram_cause', 'diagram_fix', 'open_questions')
    a = {k: a.get(k) for k in keep}
    # ---- self-check: deterministic checks + independent reviewer; redo with the problems listed (max 2 rounds)
    first, rounds, remaining = [], 0, []
    for rnd in range(3):
        issues, extra = review.checks(a, ev, file_index(json.dumps(a, default=str)))
        if extra:
            ev.setdefault('code', []).extend(x for x in extra if not any(c.get('func') == x['func'] for c in ev['code']))
            ev['code_not_in_repo'] = [f for f in ev.get('code_not_in_repo') or [] if not any(x['func'] == f for x in extra)]
        crit, verdict = review.critic(a, ev, cfg, OUT, f'{tag}.review{rnd}')
        issues += crit
        if rnd == 0:
            first = issues
        if not issues:
            remaining = []
            break
        remaining = issues
        if rnd == 2:
            break
        log(f'  self-check round {rnd + 1}: {len(issues)} problem(s) -> redo ({"; ".join(i.get("problem", "")[:60] for i in issues[:3])})')
        redo_prompt = (prompt.split('\n\n', 1)[0] + '\n\n' + json.dumps(ev, indent=1, default=str) +
                       '\n\nA reviewer checked your previous answer against this evidence and found these problems. Fix every one, '
                       'keep what was right, answer with the full JSON object again.\nPROBLEMS:\n' + json.dumps(issues, indent=1) +
                       '\nPREVIOUS ANSWER:\n' + json.dumps(a, indent=1, default=str))
        b = _json(llm.run('crash-analysis', redo_prompt, cfg, OUT, f'{tag}.redo{rnd + 1}', model=mdl, deny=BLIND_DENY))
        if not b:
            break
        a = {k: b.get(k) for k in keep}
        rounds += 1
    a['review'] = {'verdict': 'passed' if not remaining and not rounds else ('passed after fixes' if not remaining else 'issues remain'),
                   'rounds': rounds, 'found': first[:10], 'remaining': remaining[:10]}
    a['events_read'] = (ev.get('all_events') or {}).get('events_in_this_crash')
    if (ev.get('firebase') or {}).get('note'):        # Crashlytics details failed: keep the answer, retry next sync
        a['incomplete'] = ev['firebase']['note'][:200]
    a['file_index'] = file_index(json.dumps(a, default=str))
    a['source'] = ev.get('source')
    if ev.get('wait_chains'):
        wc = ev['wait_chains']
        a['wait_chains'] = {'first': wc['per_sample'][0], 'agreement': wc['agreement'], 'deadlock': wc['deadlock_in_any'],
                            'samples': len(wc['per_sample'])}
    locate.set_sha(None)
    a['team_knowledge'] = [k['file'] for k in ev.get('team_knowledge', [])]
    a['located'] = [f"{c['file']}:{c['line']}" for c in ev.get('code', [])]
    return a, rec


def fs_safe(o):
    """Firestore rejects empty or non-string map keys (and the model or file_index can produce them)."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            k = str(k).strip() if k is not None else ''
            out[k or '_'] = fs_safe(v)
        return out
    if isinstance(o, (list, tuple)):
        return [fs_safe(v) for v in o]
    return o


def link_families(db, log=print, rows=None):
    """No model calls: mark every report cluster that belongs to a bigger problem (merged/<id>.familyOf = primary).
    Run on every gathering too, so the board shows a new cluster of an old, already fixed bug as part of that bug.
    -> (rows, fams, followers)"""
    if rows is None:
        rows = [d.to_dict() | {'id': d.id} for d in db.collection('merged').stream()]
        rows = [r for r in rows if not r.get('stale')]
    fams = families(rows)
    byid = {r['id']: r for r in rows}
    followers = {i for ids in fams.values() for i in ids[1:]}
    for r in rows:                                   # the primary of a family reads every other cluster of it
        ids = fams.get(r['id']) or []
        if ids and ids[0] == r['id'] and len(ids) > 1:
            r['_related'] = [byid[i] for i in ids[1:]]
    for r in rows:                                   # a link from an earlier, wrong grouping is removed
        if r.get('familyOf') and r['id'] not in followers:
            try:
                from firebase_admin import firestore as _fs
                db.collection('merged').document(r['id']).update({'familyOf': _fs.DELETE_FIELD})
                log(f"analysis: {r['id'][:22]} is its own problem again (unlinked from {r['familyOf'][:22]})")
            except Exception:
                pass
    for i in followers:                              # the board shows them as part of the primary, no own analysis
        prim = next(ids[0] for ids in fams.values() if i in ids)
        if byid[i].get('familyOf') != prim:
            try:
                db.collection('merged').document(i).update({'familyOf': prim})
            except Exception:
                pass
    if followers:
        log(f'analysis: {len(followers)} report cluster(s) are part of a bigger problem; read together with it, not alone')
    return rows, fams, followers


def run_all(db, cfg, log=print, limit=None, force=False, stop=None, only=None):
    from firebase_admin import firestore
    rows, fams, followers = link_families(db, log=log)
    byid = {r['id']: r for r in rows}
    rows = [r for r in rows if r['id'] not in followers]
    if only:                                         # one crash only (Analyse button / tests): no other problem is touched
        ids = {p + x for x in only for p in ('', 'm-', 'm-play-')}      # this crash's own records, not linked ones
        rows = [r for r in rows if r['id'] in ids]
        force = True
    pri = {'both': 0, 'likely': 1, 'firebase': 2, 'play': 3}
    rows.sort(key=lambda r: (pri.get(r.get('match'), 9), -max((r.get('play') or {}).get('users') or 0, (r.get('fb') or {}).get('users') or 0)))
    redo = set()
    rf = os.path.join(os.path.dirname(OUT), 'reanalyse.txt')     # ids to redo once (e.g. analysed with missing evidence)
    if os.path.exists(rf):
        redo = {l.strip() for l in open(rf) if l.strip()}
    if (cfg.get('analysis') or {}).get('skip_pure_java', True) and not force:
        java = [r for r in rows if not _has_engine(r) and r['id'] not in redo]
        if java:                                     # Night Shift is for the native engine: pure Java/Kotlin costs no tokens
            log(f'analysis: skipping {len(java)} problem(s) with no libMYJNILIB26 frame (Java/Kotlin, system, SDK); they stay on the board with their stacks')
            for r in java:
                if not r.get('analysisSkipped'):
                    try:
                        db.collection('merged').document(r['id']).update({'analysisSkipped': 'no native engine frame (pure Java/Kotlin or system/SDK only)'})
                    except Exception:
                        pass
            skip = {r['id'] for r in java}
            rows = [r for r in rows if r['id'] not in skip]
    todo = [r for r in rows if force or r['id'] in redo or (r.get('analysis') or {}).get('incomplete')
            or r.get('analysis_key') != _key(r) or not r.get('analysis') or _grew(r)]
    grew = sum(1 for r in todo if r.get('analysis') and r.get('analysis_key') == _key(r) and _grew(r))
    if grew:
        log(f'analysis: {grew} problem(s) grew since their last root cause (50%+ more events or a new build): redoing them')
    if limit:
        todo = todo[:limit]
    log(f'analysis: {len(todo)} of {len(rows)} problems need a root cause (others unchanged since last analysis)')
    def one(i, m):
        if stop and stop():                          # Cancel on the board: finish the ones running, start no new one
            return 'skipped'
        t0 = dt.datetime.now()
        try:
            a, rec = analyse_one(db, cfg, m, log)
        except BaseException as e:
            a, rec = None, None
            log(f'  [{i}/{len(todo)}] {m.get("title", "")[:70]}: error {str(e)[:200]}')
        ref = db.collection('merged').document(m['id'])
        if a:
            a = fs_safe(a)
            try:
                json.dump(a, open(os.path.join(OUT, f'm-{m["id"]}.analysis.json'), 'w'), indent=1, default=str)
            except Exception:
                pass
            try:
                ref.update({'analysis': a, 'analysis_key': _key(m), 'analysis_basis': _basis(m),
                            'analysedAt': firestore.SERVER_TIMESTAMP})
            except BaseException as e:                                # one bad write must not stop the other 72
                log(f'  [{i}/{len(todo)}] {m.get("title", "")[:70]}: could not save ({str(e)[:150]})')
                return 'failed'
            if rec and (m.get('fb') or {}).get('id'):                 # the Cases tab shows the same analysis
                keep = {k: rec.get(k) for k in ('frames', 'code', 'breadcrumbs', 'verdict', 'confidence', 'reasons', 'title', 'subtitle',
                                                 'signal', 'field_fingerprint', 'stack_groups', 'scenarios', 'repro_plan', 'android', 'models')}
                keep['narrative'] = '\n\n'.join(x for x in (a.get('summary'), '**Cause** ' + (a.get('root_cause') or ''),
                                                           '**Fix direction** ' + (a.get('fix_direction') or '')) if x)
                try:
                    db.collection('cases').document(m['fb']['id']).set(fs_safe(keep), merge=list(keep))
                except BaseException as e:
                    log(f'  case copy not saved: {str(e)[:150]}')
            log(f'  [{i}/{len(todo)}] {m.get("title", "")[:70]} -> {a.get("owner")}, {a.get("confidence")} '
                f'({int((dt.datetime.now() - t0).total_seconds())} s)')
            return 'done'
        else:
            ref.update({'analysisError': f'no analysis on {dt.date.today()}'})
            log(f'  [{i}/{len(todo)}] {m.get("title", "")[:70]}: no answer from the model')
            return 'failed'

    # several root causes at once: each one mostly waits on Claude, so 3 in parallel is ~3x faster on the Mac mini
    import concurrent.futures as cf
    par = max(1, int(((cfg.get('analysis') or {}).get('parallel')) or 3))
    log(f'analysis: {par} at a time')
    res = []
    with cf.ThreadPoolExecutor(max_workers=par) as pool:
        futs = [pool.submit(one, i, m) for i, m in enumerate(todo, 1)]
        for f in futs:
            try:
                res.append(f.result())
            except BaseException as e:
                log(f'  analysis worker error: {str(e)[:200]}')
                res.append('failed')
    done, failed = res.count('done'), res.count('failed')
    if res.count('skipped'):
        log(f'analysis: cancelled; {res.count("skipped")} problem(s) left for the next sync')
    if redo and not only and os.path.exists(rf):
        os.rename(rf, rf + '.done')
    log(f'analysis: {done} done, {failed} failed')
    return {'done': done, 'failed': failed, 'total': len(rows)}
