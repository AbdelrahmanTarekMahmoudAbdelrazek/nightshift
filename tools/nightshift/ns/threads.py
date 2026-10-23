"""ANRs: read EVERY thread, not just main. Deterministic digest of a thread dump for the analysis.

An ANR's main thread usually only WAITS (on a lock, a future, a binder call); the cause is the thread it waits for.
Crashlytics events carry all threads (often 150+), Google Play reports carry the full thread dump as text. This module
parses both, symbolizes engine frames per build, and keeps what matters:
  - main thread, full
  - every thread running our code (libMYJNILIB26.so or com.myzesty / com.video / com.common Java) or involved in a lock
    ("waiting to lock", "held by", Blocked), full
  - other busy threads, top frames only
  - idle pool/daemon threads (parked in epoll / futex / Object.wait / binder), counted by name
"""
import re
from collections import Counter

NATIVE = 'libMYJNILIB26.so'
OUR_JAVA = re.compile(r'\b(com\.myzesty|com\.video\.myzesty|com\.common\.myzesty|com\.picker|com\.quickcut)\.')
IDLE_TOP = re.compile(r'epoll|__ppoll|nativePollOnce|futex|pthread_cond_wait|Object\.wait|LockSupport\.park|Unsafe\.park|'
                      r'Thread\.sleep|__ioctl|binder|syscall$|read$|recvfrom|SocketInputStream|sigtimedwait|__rt_sigtimedwait', re.I)
LOCK = re.compile(r'waiting to lock|held by|Blocked|waiting on', re.I)
RE_HEAD = re.compile(r'^"(?P<name>[^"]*)"(?:\s+(?P<daemon>daemon))?(?:\s+prio=\d+)?\s+tid=(?P<tid>\d+)\s*(?P<state>.*)$')
RE_NAT = re.compile(r'#\d+\s+pc\s+(?:0x)?([0-9a-fA-F]+)\s+(\S+)\s*(.*)$')
RE_JAVA = re.compile(r'^\s*at\s+([\w$.<>]+)\s*\(([^)]*)\)')


def _fn(rest):
    rest = rest.split(' (BuildId')[0].strip()
    if rest.startswith('(') and rest.endswith(')'):
        rest = rest[1:-1]
    return re.sub(r'\+\d+$', '', rest).strip()


def from_play(text):
    """Play thread dump text -> [{name, tid, state, frames:[str], extra:[lock lines]}]."""
    out, cur = [], None
    for line in (text or '').splitlines():
        h = RE_HEAD.match(line.strip())
        if h:
            cur = {'name': h['name'], 'tid': h['tid'], 'state': h['state'].strip(), 'frames': [], 'extra': []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = RE_NAT.search(line)
        if m:
            cur['frames'].append(f"{m.group(2).split('/')[-1]} {_fn(m.group(3)) or '0x' + m.group(1)}")
            continue
        j = RE_JAVA.match(line)
        if j:
            cur['frames'].append(f'{j.group(1)} ({j.group(2)})')
        elif LOCK.search(line):
            cur['extra'].append(line.strip()[:200])
    return out


def from_crashlytics(event, symbolize_fn=None):
    """Crashlytics event -> same shape. symbolize_fn(frames) names engine frames with the build's own .so."""
    from . import crashlytics as cl
    out = []
    for t in event.get('threads') or []:
        fr = cl.frames_of(t)
        if symbolize_fn:
            try:
                symbolize_fn(fr)
            except Exception:
                pass
        frames = []
        for f in fr:
            name = f.get('func') or ('0x%x' % int(f['address']) if str(f.get('address') or '').isdigit() else str(f.get('address') or '?'))
            frames.append(f"{f.get('lib') or ''} {name}".strip() + (f" ({f['file']}:{f['line']})" if f.get('file') and f.get('line') else ''))
        out.append({'name': t.get('name') or t.get('threadName') or '?', 'tid': t.get('threadId') or '', 'state': t.get('state') or '',
                    'frames': frames, 'extra': [], 'main': bool(t.get('blamed') or t.get('crashed'))})
    return out


def _ours(t):
    return any(NATIVE in f or OUR_JAVA.search(f) for f in t['frames'])


def _idle(t):
    top = ' '.join(t['frames'][:3])
    return not _ours(t) and not t['extra'] and (not t['frames'] or bool(IDLE_TOP.search(top)))


def digest(threads, max_full=25, max_other=20):
    if not threads:
        return {}
    main = next((t for t in threads if t.get('main')), None) or next((t for t in threads if t['name'] == 'main' or t.get('tid') in ('1', 1)), threads[0])
    full, other, idle = [], [], Counter()
    for t in threads:
        if t is main:
            continue
        if _ours(t) or t['extra'] or LOCK.search(t.get('state', '')):
            full.append(t)
        elif _idle(t):
            idle[re.sub(r'[-_:#]?\d+$', '', t['name']).strip() or '?'] += 1
        else:
            other.append(t)
    # threads serving the engine message queue first: the main thread often waits on MsgLooper::Get
    full.sort(key=lambda t: (not any('ProcessMessages' in f for f in t['frames']),        # the engine message thread
                             not any('MsgLooper::Get' in f or 'GetResult' in f for f in t['frames']),   # threads waiting on it
                             not _ours(t)))
    fmt = lambda t, n: {'name': t['name'], 'state': t.get('state', ''), 'locks': t['extra'][:4], 'frames': t['frames'][:n]}
    main_waits = ' '.join(main['frames'][:8])
    return {
        'threads_total': len(threads),
        'main': fmt(main, 40),
        'main_is_waiting': bool(IDLE_TOP.search(main_waits) or 'MsgLooper::Get' in main_waits or 'GetResult' in main_waits),
        'our_code_or_lock_threads': [fmt(t, 30) for t in full[:max_full]],
        'other_busy_threads': [fmt(t, 4) for t in other[:max_other]],
        'idle_threads_by_name': dict(idle.most_common(30)),
    }


# ------------------------------------------------------------------ who waits for whom (ANR wait-for graph)

def _cls(frame):
    m = re.search(r'\b([A-Z][A-Za-z0-9_]*)::[~A-Za-z_]', frame or '')
    return m.group(1) if m else None


def _first(t, rx):
    return next((i for i, f in enumerate(t['frames'][:25]) if re.search(rx, f)), None)


def waits_for(t, threads):
    """(reason, [threads it waits for], external description) for one thread, from its top frames."""
    F = t['frames']
    top = ' | '.join(F[:12])
    for line in t.get('extra') or []:                    # Java monitor: "waiting to lock <0x..> held by thread 23"
        m = re.search(r'held by (?:thread |tid=)(\d+)', line)
        if m:
            return f'Java lock ({line.strip()[:80]})', [x for x in threads if str(x.get('tid')) == m.group(1)], None
    i = _first(t, r'MsgLooper::Get|Message::GetResult')
    if i is not None and _first(t, r'MsgLooper::ProcessMessages') is None:
        call = next((f for f in F[i:i + 3] if re.search(r'\bJNI_\w+', f)), F[min(i + 1, len(F) - 1)])
        jni = (re.search(r'JNI_[A-Za-z0-9_]+', call) or [call[:40]])[0]
        return (f'synchronous engine call ({jni}) waiting for the engine message thread',
                [x for x in threads if x is not t and _first(x, r'MsgLooper::ProcessMessages') is not None], None)
    i = _first(t, r'thread::join|pthread_join')
    if i is not None:
        caller = next((f for f in F[i + 1:i + 4] if _cls(f)), '')
        c = _cls(caller)
        targets = [x for x in threads if x is not t and c and any(c + '::' in f for f in x['frames'][:15])
                   and _first(x, r'ProcessMessages') is None]
        return f'join() in {caller.split(" ", 1)[-1][:70]} waiting for its worker thread to finish', targets, None
    i = _first(t, r'future<.*>::get|__assoc_sub_state::(copy|__sub_wait)|std::.*future.*wait')
    if i is not None and _first(t, r'MsgLooper') is None:
        caller = next((f for f in F[i + 1:i + 4] if _cls(f)), '')
        c = _cls(caller)
        targets = [x for x in threads if x is not t and c and any(c + '::' in f for f in x['frames'][:15])
                   and (_first(x, r'packaged_task|ThreadWorker|ThreadPool') is not None)]
        return f'future.get() in {caller.split(" ", 1)[-1][:70]} waiting for a pool task', targets, None
    if re.search(r'MediaCodec::|AMediaCodec_|ALooper::awaitResponse', top):
        api = next((re.sub(r'.*(AMediaCodec_\w+).*', r'\1', f) for f in F[:10] if 'AMediaCodec_' in f), 'MediaCodec')
        return f'{api} blocked inside Android MediaCodec', [], 'Android MediaCodec (system codec, outside the app)'
    if re.search(r'__ioctl|binder|BinderProxy|transact', top, re.I):
        return 'binder call', [], 'another process (binder transaction)'
    if re.search(r'Object\.wait|LockSupport\.park|pthread_cond_wait|futex', top):
        return 'waiting on a condition/lock (owner not visible in the dump)', [], None
    return None, [], None


def wait_chain(threads, max_len=8):
    """Follow the main thread through who-waits-for-whom. Returns {chain, end, deadlock} or {} if main not waiting."""
    if not threads:
        return {}
    main = next((t for t in threads if t.get('main')), None) or next((t for t in threads if t['name'] == 'main'), threads[0])
    chain, seen, cur = [], [], main
    while cur is not None and len(chain) < max_len:
        if any(cur is s for s in seen):
            return {'chain': chain, 'deadlock': True, 'end': f'cycle back to {cur["name"]}: DEADLOCK'}
        seen.append(cur)
        reason, targets, external = waits_for(cur, threads)
        ours = [f for f in cur['frames'][:14] if NATIVE in f or OUR_JAVA.search(f)]
        hot = next((f for f in ours if re.search(r'JNI_\w+', f)), None) or \
            next((f for f in ours if '::' in f and 'std::' not in f.split(' ', 1)[-1][:6]), None) or \
            (ours[0] if ours else (cur['frames'][0] if cur['frames'] else ''))
        step = {'thread': cur['name'], 'state': cur.get('state', ''), 'at': hot[:160], 'waits': reason}
        chain.append(step)
        if external:
            step['waits_for'] = external
            return {'chain': chain, 'deadlock': False, 'end': external}
        if not reason:
            return {'chain': chain, 'deadlock': False, 'end': f'{cur["name"]} is running (busy), not waiting'}
        if not targets:
            return {'chain': chain, 'deadlock': False, 'end': f'{cur["name"]}: {reason}; the thread it waits for is not in the dump'}
        nxt = max(targets, key=lambda x: sum(1 for f in x['frames'][:15] if NATIVE in f))
        step['waits_for'] = nxt['name']
        cur = nxt
    return {'chain': chain, 'deadlock': False, 'end': 'chain longer than shown'}


def chain_signature(c):
    return ' -> '.join(re.sub(r'\(.*', '', s['at'].split(' ', 1)[-1])[:60] for s in (c or {}).get('chain', []))
