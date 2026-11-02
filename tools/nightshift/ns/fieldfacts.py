"""Field facts (28 Oct, no AI): the ODD things in the user's own log before the crash, as a numbered list every root
cause, fix and review must explain: a fix theory can sound right and still be contradicted by one line of the user's
log. A theory that contradicts one of these facts is wrong; a theory that leaves one unexplained is incomplete."""
import json
import os
import re

from . import config

ODD = [
    (r'exception|Error in processing|ERROR \||error:|failed|FAILED', 'an engine call failed / threw'),
    (r"doesn't match|does not match|mismatch|size .* differ", 'two lists disagree (app vs engine)'),
    (r'bigger than|out of range|out of bounds|index \d+ .*size|invalid (index|id)', 'an index the engine does not have'),
    (r'null|nullptr|NULL', 'a null where a value was expected'),
    (r'durationInMill:0\b|duration: 0\.0+ |Duration\(\) -> 0\.0|total duration 0', 'the timeline is empty (duration 0)'),
    (r'cancel|Cancel', 'something was cancelled'),
    (r'TIMEOUT|timed out|WaitFor', 'a wait timed out (engine thread busy or dead)'),
]


def _timeline(case):
    try:
        from . import tapflow
        return tapflow.field_timeline(case, cap=400).splitlines()
    except Exception:
        return [str(x) for x in reversed(case.get('breadcrumbs') or [])]


def facts(case, cap=25):
    """[{n, at, line, why}] oldest first; plus derived facts (play hits the end at once, the same tap repeated...)."""
    lines = _timeline(case)
    out, seen = [], set()
    for l in lines:
        for rx, why in ODD:
            if re.search(rx, l):
                key = re.sub(r'\d', '#', l.split(' ', 1)[-1])[:120]
                if key in seen:
                    break
                seen.add(key)
                out.append({'at': l[:12], 'line': l[13:260], 'why': why})
                break
    # derived: play pressed and the engine reached the end immediately (empty / zero-length timeline)
    for i, l in enumerate(lines):
        if 'MsgResumePlaying' in l and any('MsgAtEnd' in x for x in lines[i + 1:i + 3]):
            out.append({'at': l[:12], 'line': 'MsgResumePlaying followed at once by MsgAtEnd', 'why': 'play ended instantly: the engine timeline is empty'})
            break
    # derived: engine messages whose id lists repeat an id ([0, 0]) -> a stale/duplicated list on the app side
    for l in lines:
        m = re.search(r'media_ids? ([\d ]+)', l)
        if m:
            ids = m.group(1).split()
            if len(ids) != len(set(ids)):
                out.append({'at': l[:12], 'line': l[13:200], 'why': f'the app sent duplicate ids {ids}: the app-side copy of this list is out of step with the engine (stale or duplicated entry)'})
                break
    # derived: a tap/screen event with no matching engine message (the app did something the log does not name)
    out.sort(key=lambda x: x['at'])
    for i, f in enumerate(out[:cap]):
        f['n'] = i + 1
    return out[:cap]


RULE = ('FIELD FACTS RULE: the field_facts below are the odd things in the user\'s own log. Your theory must EXPLAIN '
        'EVERY ONE (say which fact each part of the theory explains). Read what each fact PROVES happened: a value in a '
        'later message can prove an earlier step ran, so a theory assuming that step did not run is wrong. A theory that '
        'CONTRADICTS a fact is wrong; a fact left unexplained means the theory is incomplete: keep looking (who sends that '
        'message: see the Kotlin map).')


def block(case):
    f = facts(case)
    if not f:
        return ''
    return '# FIELD FACTS (explain every one)\n' + RULE + '\n' + '\n'.join(f"{x['n']}. [{x['at']}] {x['line']}  -> {x['why']}" for x in f) + '\n\n'
