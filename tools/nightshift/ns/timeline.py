"""Read every line of every event: per-event timelines and what all events of one crash have in common.

Why: a root cause built from one event's last 25 log lines latches onto whatever error is printed last (for example
"add_video failed -10000") and misses the lifecycle story around it (surface destroyed, engine recreated, template
reloading while old messages still run). Here every breadcrumb line of every sampled event is kept, tagged and
compressed (long runs of the same message collapse to "xN"), and the lines are compared ACROSS events so the analysis
sees which moments repeat in every crash and which are one-off noise. Deterministic, no model.
"""
import re
from collections import Counter

NATIVE = 'libMYJNILIB26.so'

TAGS = [   # first match wins; order matters
    ('USER', re.compile(r'\[event\]')),
    ('TEARDOWN', re.compile(r'destructor|~VideoEngine|~MsgLooper|destroyVideoEngineContext|Finished ProcessMessages|stopRendering|'
                            r'Destroying EGL|surface.*released|onDestroy|onStop|onPause|force_quit|cleanupEGL|eglReleaseThread|'
                            r'backcalled|\bback\b', re.I)),
    ('CREATE', re.compile(r'MsgCreatePlayer|Started ProcessMessages|DisplayWindow created|C\+\+17 is enabled|onCreate|onResume|'
                          r'ThreadPool::start|AudioPlayer::rebuild stream opened', re.I)),
    ('ERROR', re.compile(r'exception|error|fail|out of range|bigger than|threw|cancelled|crash|abort|OVERRUN|timeout', re.I)),
    ('MEDIA', re.compile(r'MsgAdd|MsgDelete|MsgRemove|MsgReplace|setAudio|add_video|add_image|template|MsgSaveDraft|MsgLoad|'
                         r'MsgTrim|MsgSetAudioTiming|MsgGetMedia|transcod', re.I)),
]


def tag(msg):
    for name, rx in TAGS:
        if rx.search(msg):
            return name
    return 'ENGINE'


def _secs(ts):
    m = re.match(r'(\d\d):(\d\d):(\d\d)(?:\.(\d+))?', ts or '')
    if not m:
        return None
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + float('0.' + (m[4] or '0'))


def _norm(msg):
    """Shape of a message: numbers, ids, paths, hex and device ids removed, so the same event matches across phones."""
    s = re.sub(r'"device_id": "[^"]*",?\s*', '', msg)
    s = re.sub(r'/data/\S+|/storage/\S+', '<path>', s)
    s = re.sub(r'0x[0-9a-fA-F]+|\b\d+(\.\d+)?\b', '#', s)
    return re.sub(r'\s+', ' ', s).strip()[:140]


def signature(frames):
    """Stack group of one event: first named frame in our engine, else first engine pc, else first Java frame."""
    for f in frames or []:
        if f.get('lib') == NATIVE and f.get('func'):
            return f['func'].split(' + ')[0].split('(')[0].strip()
    for f in frames or []:
        if f.get('lib') == NATIVE and f.get('address'):
            return 'pc 0x%x' % int(str(f['address']), 0) if str(f['address']).startswith('0x') else 'pc 0x%x' % int(f['address'])
    for f in frames or []:
        if f.get('func') and '.' in f['func'] and not str(f.get('lib') or '').endswith('.so'):
            return f['func']
    return 'unknown'


def event_timeline(logs, max_chars=7000, window=20.0):
    """logs: 'HH:MM:SS.mmm message' lines (any order). Returns chronological compressed lines + facts."""
    rows = []
    for l in reversed(list(logs or [])):            # input is newest first; keep true order for equal timestamps
        ts, _, msg = l.partition(' ')
        rows.append((_secs(ts), ts, msg.strip()))
    rows.sort(key=lambda r: (r[0] is None, r[0] or 0))
    end = max((r[0] for r in rows if r[0] is not None), default=None)
    out, prev, count = [], None, 0

    def flush():
        if prev:
            t, ts, msg, tg = prev
            dt_ = f'-{end - t:6.2f}s' if (end is not None and t is not None) else '      ?'
            out.append(f'{dt_} {tg:8} {msg[:260]}' + (f'   (x{count})' if count > 1 else ''))
    for t, ts, msg in rows:
        if prev and _norm(msg) == _norm(prev[2]):
            count += 1
            continue
        flush()
        prev, count = (t, ts, msg, tag(msg)), 1
    flush()
    final = [r for r in rows if end is not None and r[0] is not None and end - r[0] <= window]
    facts = {
        'lines_total': len(rows),
        'span_seconds': round(end - min(r[0] for r in rows if r[0] is not None), 1) if end is not None and rows else None,
        'last_user_action': next((m for t, _, m in reversed(rows) if tag(m) == 'USER'), None),
        'teardown_in_last_%ds' % int(window): any(tag(m) == 'TEARDOWN' for _, _, m in final),
        'recreate_in_last_%ds' % int(window): any(tag(m) == 'CREATE' for _, _, m in final),
        'errors_in_last_%ds' % int(window): sum(1 for _, _, m in final if tag(m) == 'ERROR'),
    }
    text = '\n'.join(out)
    if len(text) > max_chars:                       # keep the end (the crash) whole; summarise the older part by tag
        older = Counter(l.split()[1] for l in out[:-120] if len(l.split()) > 1)
        text = (f'[{len(out) - 120} older compressed lines: ' + ', '.join(f'{k} {v}' for k, v in older.most_common()) + ']\n'
                + '\n'.join(out[-120:]))[-max_chars:]
    return text, facts, final


def common(events, window=20.0):
    """Moments that repeat across events (same message shape in the final seconds), most shared first."""
    seen = Counter()
    tags = {}
    for e in events:
        shapes = set()
        for _, _, msg in event_timeline(e.get('logs'), window=window)[2]:
            n = _norm(msg)
            shapes.add(n)
            tags[n] = tag(msg)
        seen.update(shapes)
    n = len(events)
    rows = [(c, s) for s, c in seen.items() if c >= 2 or n == 1]
    rows.sort(key=lambda r: (-r[0], ['TEARDOWN', 'CREATE', 'ERROR', 'USER', 'MEDIA', 'ENGINE'].index(tags[r[1]])))
    return [f'{c}/{n} events  {tags[s]:8} {s}' for c, s in rows[:40]]


def evidence(events, group=None, max_events=20):
    """events: summarised Crashlytics events with symbolized frames. Returns the dict the analysis prompt gets."""
    groups = Counter(signature(e.get('frames')) for e in events)
    mine = [e for e in events if not group or signature(e.get('frames')) == group] or events
    others = {g: c for g, c in groups.items() if g != (group or signature(mine[0].get('frames')) if mine else None)}
    per = []
    for e in mine[:max_events]:
        text, facts, _ = event_timeline(e.get('logs'))
        per.append({'time': e.get('time'), 'version': e.get('version'), 'device': e.get('device'), 'os': e.get('os'),
                    'process_state': e.get('process_state'), 'custom_keys': e.get('keys') or {}, 'facts': facts,
                    'timeline_oldest_first': text})
    return {
        'stack_group': group or (signature(mine[0].get('frames')) if mine else None),
        'events_in_this_crash': len(mine),
        'other_crashes_in_same_crashlytics_issue': others,
        'shared_across_events_final_20s': common(mine),
        'events': per,
    }
