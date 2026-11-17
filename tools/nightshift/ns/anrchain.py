"""ANR grouping by the BLOCKER, not by the main thread (9 Nov).

An ANR's main thread usually only waits. Crashlytics groups ANRs by the main thread's top frames, so it splits one bug
(the same stuck decoder reached from freezeProgress and from getMediaDuration = two issues) and merges different ones
(501bb526: a codec flush hang in October, a dequeue hang after trim on 9 Nov). One card = one fix, and the fix lives
where the chain ENDS:

  family  = what the main thread waits on   (engine queue / Java lock / join / pool task / binder / ART / busy)
            -> one family-level fix (e.g. timeouts + fallback on the synchronous engine getters)
  card    = where the blocker is stuck, in OUR code:
            waiting (codec, binder, lock): our last frame + the system call     'MCDecoder::safeCodecFlush > AMediaCodec_flush'
            running (busy, slow):          the unit of work (message handler / task), the snapshot line is noise
            not found:                     'unknown' + the main-thread call; pull more events
  victims = the main-thread calls (JNI_getMediaDuration, ...): labels only, never the key

Deterministic: read from the event's own thread dump, no model.
"""
import re

from . import threads as T

NATIVE = T.NATIVE
KEY_PREFIX = 'anr:'
MAIN_IS_END = ('art', 'busy', 'binder')

FAMILIES = {
    'engine-queue': ('Main thread waits on the engine queue (MsgLooper::Get)',
                     'Give the synchronous engine getters a timeout + fallback (getCurrentTime already does: '
                     '"WaitFor TIMEOUT ... direct access fallback"), so the main thread never waits behind a stuck engine.'),
    'join': ('Main thread joins a worker thread', 'Never join() on the main thread; stop the worker asynchronously.'),
    'future': ('Main thread waits on a pool task (future.get)', 'Never block the main thread on a future; use a callback or a timeout.'),
    'java-lock': ('Main thread waits on a Java lock', 'Do not hold that lock during slow work, or do not take it on the main thread.'),
    'native-lock': ('Main thread waits on a native lock/condition', 'Find who holds it; keep slow work outside the lock.'),
    'codec': ('Main thread calls MediaCodec directly', 'Move the codec call off the main thread.'),
    'binder': ('Main thread blocked in a binder call (another process)', 'Move the IPC off the main thread.'),
    'art': ('Main thread stalled inside the Android runtime (GC / thread suspension)', 'Usually memory pressure or a long GC; '
            'look at what else is running and at allocation spikes.'),
    'busy': ('Main thread busy (running, not waiting)', 'Move that work off the main thread.'),
}

# engine threads parked with nothing to do: never a blocker
IDLE_OURS = re.compile(r'thread_pool::worker$|ThreadQueue\w*::(pop_for|tryAndPop|pop)$|MCDecoder::worker_loop$|'
                       r'VideoPlayer::(seekThreadFunc|accurate_seek_thread_func|playerThreadRunner)$|ThreadWorker::run$|'
                       r'MsgLooper::ProcessMessages$')
# frames that dispatch work: the unit of work is the first named frame ABOVE them
DISPATCH = re.compile(r'MsgLooper::ProcessMessages|VideoPlayer::runGlTaskNow|VideoPlayer::playerThreadRunner|ThreadWorker::run|'
                      r'thread_pool::worker|std::\w*function|__invoke|packaged_task|__pthread_start|__start_thread|'
                      r'android\.os\.Handler\.dispatchMessage|android\.os\.Looper\.loop')
SYS_WAIT = re.compile(r'(AMediaCodec_\w+|AMediaExtractor_\w+|AMediaMuxer_\w+|ANativeWindow_\w+|eglSwapBuffers|eglMakeCurrent|'
                      r'BinderProxy\.transact\w*|IPCThreadState::transact|__ioctl)')
ART_STALL = re.compile(r'art::ConditionVariable::WaitHoldingLocks|art::Thread::FullSuspendCheck|art::gc::|'
                       r'art::Monitor::Lock|art::ThreadList::SuspendAll|art::Barrier::')


def _func(frame):
    """'libX.so Foo::bar(int) (file.cpp:12)' -> 'Foo::bar' (templates, args, offsets out)."""
    from . import groups
    s = re.sub(r'\s*\([^()]*:\d+\)\s*$', '', frame or '')
    parts = s.split(' ', 1)
    s = parts[1] if len(parts) > 1 and (parts[0].endswith('.so') or parts[0].endswith('.apk') or '.' in parts[0]) else s
    return groups._clean(s)


def _named_ours(t):
    """Our named frames of a thread, top first: [(index, func)]."""
    out = []
    for i, f in enumerate(t['frames']):
        if NATIVE in f or T.OUR_JAVA.search(f):
            fn = _func(f)
            if fn and not fn.startswith(('std', '__', '0x', '(')) and 'std::' not in fn and 'Missing BuildId' not in f:
                out.append((i, fn))
    return out


def _app_java(t):
    """First frame of app code on a Java stack (our packages, else any non-framework Java frame)."""
    for f in t['frames']:
        if T.OUR_JAVA.search(f):
            return _func(f)
    for f in t['frames']:
        fn = _func(f)
        if '.' in fn and not re.match(r'(android|androidx|java|javax|kotlin|kotlinx|dalvik|libcore|sun|com\.android|'
                                       r'com\.google\.android\.gms|art)\.', fn):
            return fn
    return ''


def _work_unit(t):
    """The unit of work a thread is running: the named frame right above the dispatcher (message handler / task)."""
    ours = _named_ours(t)
    if not ours:
        return ''
    disp = next((i for i, f in enumerate(t['frames']) if DISPATCH.search(f)), None)
    above = [fn for i, fn in ours if disp is None or i < disp]
    above = [fn for fn in above if not DISPATCH.search(fn) and not IDLE_OURS.search(fn)]
    return above[-1] if above else ours[-1][1]


def _short(unit):
    u = unit or '?'
    if '::' in u:
        return u.split('::')[-1]
    parts = u.split('.')
    return '.'.join(parts[-2:]) if len(parts) > 1 else u


def _main_unit(main):
    """What the main thread itself is doing: app code first, else the first Java/native frame that is not the runtime."""
    u = _app_java(main) or (_named_ours(main)[0][1] if _named_ours(main) else '')
    if u:
        return u
    for f in main['frames']:
        fn = _func(f)
        if fn and not re.match(r'(syscall|__|art::|art_|_JNIEnv|android::|J\.N\.|0x|libcore\.|dalvik\.)', fn) and 'base.apk' not in f:
            return fn
    return 'unknown frame'


def _victim(main):
    for f in main['frames'][:30]:
        m = re.search(r'\bJNI_\w+', f)
        if m:
            return m.group(0)
    return _app_java(main) or (_named_ours(main)[0][1] if _named_ours(main) else '')


def _busy_engine(threads, exclude):
    """Engine threads that are doing something (not parked idle), stuck-in-system first."""
    out = []
    for t in threads:
        if any(t is x for x in exclude):
            continue
        ours = _named_ours(t)
        if not ours or not any(NATIVE in f for f in t['frames']):
            continue
        if IDLE_OURS.search(ours[0][1]):
            continue
        top = ' | '.join(t['frames'][:12])
        out.append((0 if SYS_WAIT.search(top) else 1, -len(ours), t))
    out.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in out]


def _end_of(t):
    """How the last thread of the chain is stuck -> (mode, key_part, title, during)."""
    ours = _named_ours(t)
    top = ' | '.join(t['frames'][:12])
    m = SYS_WAIT.search(top)
    during = _work_unit(t)
    if m and ours:
        api = m.group(1)
        api = 'binder' if re.search(r'Binder|IPCThread|ioctl', api) else api
        last = ours[0][1]
        return 'waiting', f'{last} > {api}', f'{last.split("::")[-1]} stuck in {api}', during
    if ours and not re.search(r'pthread_cond_wait|futex|condition_variable|Object\.wait|LockSupport\.park', ' | '.join(t['frames'][:6])):
        return 'running', f'running {during}', f'{during.split("::")[-1]} running long', during
    if ours:
        return 'waiting', f'{ours[0][1]} > lock', f'{ours[0][1].split("::")[-1]} waiting on a lock', during
    return None, '', '', ''


def _threads(raw_event, symbolize=True):
    """threads.from_crashlytics, but the engine frames of ALL threads are named in ONE symbolizer call (one
    addr2line run per event instead of one per thread: 15 s -> <1 s per ANR event)."""
    from . import crashlytics as cl
    per = [(t, cl.frames_of(t)) for t in raw_event.get('threads') or []]
    if symbolize:
        try:
            from . import symbolize as _sy
            ver = raw_event.get('version') or {}
            vc, vn = ver.get('buildVersion'), str(ver.get('displayVersion') or '').split(' ')[0]
            todo = [f for _, fr in per for f in fr if f.get('lib') == NATIVE and not f.get('func')]
            if todo:
                _sy.symbolize_frames(todo, vc, NATIVE, vn, relay_ok=False)
        except Exception:
            pass
    out = []
    for t, fr in per:
        frames = []
        for f in fr:
            name = f.get('func') or ('0x%x' % int(f['address']) if str(f.get('address') or '').isdigit() else str(f.get('address') or '?'))
            frames.append(f"{f.get('lib') or ''} {name}".strip() + (f" ({f['file']}:{f['line']})" if f.get('file') and f.get('line') else ''))
        out.append({'name': t.get('name') or t.get('threadName') or '?', 'tid': t.get('threadId') or '', 'state': t.get('state') or '',
                    'frames': frames, 'extra': [], 'main': bool(t.get('blamed') or t.get('crashed'))})
    return out


def blocker(raw_event, symbolize=True):
    """One Crashlytics ANR event -> {family, familyTitle, familyFix, victim, key, title, mode, thread, during, inferred,
    chain:[...]} or None (not an ANR / no thread dump)."""
    if str((raw_event.get('issue') or {}).get('errorType') or '').upper() != 'ANR':
        return None
    th = _threads(raw_event, symbolize)
    if not th:
        return None
    main = next((t for t in th if t.get('main')), None) or next((t for t in th if t['name'] == 'main'), None)
    if not main:
        return None
    victim = _victim(main)
    mtop = ' | '.join(main['frames'][:12])
    # ---- family: what main waits on
    reason, targets, external = T.waits_for(main, th)
    if reason and 'engine call' in reason:
        fam = 'engine-queue'
    elif reason and reason.startswith('join'):
        fam = 'join'
    elif reason and reason.startswith('future'):
        fam = 'future'
    elif reason and reason.startswith('Java lock'):
        fam = 'java-lock'
    elif reason and 'MediaCodec' in reason:
        fam = 'codec'
    elif reason == 'binder call':
        fam = 'binder'
    elif ART_STALL.search(mtop):
        fam = 'art'
    elif reason:
        fam = 'native-lock'
    else:
        fam = 'busy'
    # ---- walk the chain to its end
    chain, cur, inferred, seen = [], main, False, []
    end = None
    for _ in range(8):
        if any(cur is s for s in seen):
            end = ('waiting', 'deadlock ' + ' / '.join(sorted({_victim(s) or s['name'] for s in seen}))[:120], 'deadlock', '')
            break
        seen.append(cur)
        r, tg, ex = T.waits_for(cur, th)
        chain.append({'thread': cur['name'], 'waits': r or 'running', 'at': (_named_ours(cur) or [(0, cur['frames'][0] if cur['frames'] else '')])[0][1][:90]})
        if cur is main and fam in ('art', 'busy', 'binder', 'codec'):
            unit = _main_unit(main)
            if fam == 'binder':
                end = ('waiting', f'main {unit} > binder', f'{_short(unit)} stuck in a binder call', unit)
            elif fam == 'codec':
                end = _end_of(main)
            elif fam == 'art':
                end = ('waiting', f'main {unit} > ART', f'{_short(unit)} stalled by the runtime (GC/suspend)', unit)
            else:
                end = ('running', f'main {unit}', f'main thread busy in {_short(unit)}', unit)
            break
        if ex:
            end = _end_of(cur)
            break
        if r and tg:
            cur = max(tg, key=lambda x: sum(1 for f in x['frames'][:15] if NATIVE in f))
            continue
        if cur is not main and (r or not _named_ours(cur) or IDLE_OURS.search((_named_ours(cur) or [(0, '')])[0][1])):
            # the thread main waits on is parked (e.g. the engine message thread inside a handler that hands work to
            # the player thread): the blocker is the engine thread that is actually doing something
            busy = _busy_engine(th, [main, cur])
            # 17 Nov (f4891dc9, 1.26.0): the engine thread was blocked on MCDecoder's MUTEX in get_frame and no thread
            # was in MediaCodec, yet the card said "receive_frame stuck in AMediaCodec_dequeueOutputBuffer". A thread
            # waiting on a lock is only blamed on another thread that can hold THAT lock: one running code of the same
            # class. None -> the card is the lock itself ("get_frame waiting on a lock"), owner not in the dump.
            ours_cur = _named_ours(cur)
            if r and ours_cur and not IDLE_OURS.search(ours_cur[0][1]):
                cls = ours_cur[0][1].split('::')[0] if '::' in ours_cur[0][1] else ''
                busy = [b for b in busy if cls and any(f[1].split('::')[0] == cls for f in _named_ours(b))]
            if busy:
                inferred = True
                cur = busy[0]
                chain.append({'thread': cur['name'], 'waits': 'inferred: busy engine thread', 'at': (_named_ours(cur) or [(0, '')])[0][1][:90]})
                r2, _, ex2 = T.waits_for(cur, th)
                end = _end_of(cur)
                break
        end = _end_of(cur) if cur is not main else None
        break
    if not end or not end[0]:
        key = f'unknown {victim or fam}'
        res = {'mode': 'unknown', 'key': KEY_PREFIX + key, 'title': f'blocker not found ({victim or fam})', 'during': ''}
    else:
        mode, part, title, during = end
        res = {'mode': mode, 'key': KEY_PREFIX + part, 'title': title, 'during': during}
    ft, fx = FAMILIES[fam]
    res.update({'family': fam, 'familyTitle': ft, 'familyFix': fx, 'victim': victim, 'thread': cur['name'] if end else '',
                'inferred': inferred, 'chain': chain[:6],
                # card split only when the chain leaves the main thread: when main itself is the end (busy, ART stall,
                # its own binder call) Crashlytics' main-thread grouping already is the blocker grouping
                'split': fam not in MAIN_IS_END and (res['mode'] != 'unknown' or victim.startswith('JNI_'))})
    return res


def title_of(key):
    """Readable card title from a key alone (registry entries keep only the key)."""
    k = (key or '')[len(KEY_PREFIX):] if (key or '').startswith(KEY_PREFIX) else (key or '')
    if ' > ' in k and not k.startswith('main '):
        a, b = k.split(' > ', 1)
        return f'{a.split("::")[-1]} stuck in {b}'
    if k.startswith('running '):
        return f'{k[8:].split("::")[-1]} running long'
    if k.startswith('main '):
        u = k[5:]
        if u.endswith(' > binder'):
            return f'{_short(u[:-9])} stuck in a binder call'
        if u.endswith(' > ART'):
            return f'{_short(u[:-6])} stalled by the runtime (GC/suspend)'
        return f'main thread busy in {_short(u)}'
    return k[:60]


# ------------------------------------------------------------------ cross-issue map (board: ANR families -> blocker cards)

def build_map(units, issue_of_card, new_cards=()):
    """units: {card id: [samples with 'anr', 'version']} of ANR cards. -> (map doc, {card: row field}).
    A blocker card spans Crashlytics issues: the same stuck point reached from different main-thread calls is one bug."""
    from collections import Counter, defaultdict
    bykey = defaultdict(lambda: {'n': 0, 'fam': Counter(), 'victims': Counter(), 'during': Counter(), 'members': {},
                                 'title': '', 'mode': '', 'inferred': 0})
    for card, smp in units.items():
        for x in smp or []:
            a = x.get('anr') or {}
            # 9 Nov (feedback): only real chains (main waits on ANOTHER thread that was found). Main-thread-busy / GC /
            # binder ANRs and "blocker not found" Java ANRs are not linked across issues: same top frame != same bug
            if not a.get('key') or not a.get('split', True):
                continue
            b = bykey[a['key']]
            b['n'] += 1
            b['fam'][a.get('family') or '?'] += 1
            if a.get('victim'):
                b['victims'][a['victim']] += 1
            if a.get('during'):
                b['during'][a['during']] += 1
            b['title'] = b['title'] or a.get('title') or title_of(a['key'])
            b['mode'] = b['mode'] or a.get('mode') or ''
            b['inferred'] += 1 if a.get('inferred') else 0
            m = b['members'].setdefault(card, {'card': card, 'issue': issue_of_card.get(card, card.split('~')[0]), 'events': 0,
                                               'versions': Counter(), 'new': card in new_cards})
            m['events'] += 1
            m['versions'][str(x.get('version') or '?').split(' ')[0]] += 1
    fams = defaultdict(list)
    for k, b in bykey.items():
        fam = b['fam'].most_common(1)[0][0]
        members = sorted(b['members'].values(), key=lambda m: -m['events'])
        fams[fam].append({
            'key': k, 'title': b['title'], 'mode': b['mode'], 'events': b['n'], 'inferred': b['inferred'],
            'victims': [v for v, _ in b['victims'].most_common(6)], 'during': [d for d, _ in b['during'].most_common(4)],
            'issues': sorted({m['issue'] for m in members}),
            'members': [{'card': m['card'], 'issue': m['issue'], 'events': m['events'], 'new': m['new'],
                         'versions': sorted(m['versions'])} for m in members],
            'new': any(m['new'] for m in members)})
    out = []
    for fam, cards in fams.items():
        cards.sort(key=lambda c: (-c['events'], c['key']))
        t, fx = FAMILIES.get(fam, (fam, ''))
        out.append({'id': fam, 'title': t, 'fix': fx, 'events': sum(c['events'] for c in cards),
                    'issues': len({i for c in cards for i in c['issues']}), 'cards': cards})
    order = list(FAMILIES)
    out.sort(key=lambda f: (f['id'] not in ('engine-queue', 'join', 'future', 'native-lock', 'codec'), -f['events'],
                            order.index(f['id']) if f['id'] in order else 99))
    rowf = {}
    for f in out:
        for c in f['cards']:
            for m in c['members']:
                rowf[m['card']] = {'key': c['key'], 'title': c['title'], 'mode': c['mode'], 'family': f['id'],
                                   'familyTitle': f['title'], 'familyFix': f['fix'], 'during': c['during'][:2],
                                   'victims': c['victims'][:4],
                                   'siblings': [x['card'] for x in c['members'] if x['card'] != m['card']][:8]}
    return {'families': out}, rowf
