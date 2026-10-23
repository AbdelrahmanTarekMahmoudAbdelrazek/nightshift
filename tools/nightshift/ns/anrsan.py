"""Parse `anrsan_findings.md` (written by tools/stress/anrsan_findings.py) into structured wait chains.

A finding looks like:
    ### F008-52b8dc
    **HIGH · CRITICAL_BLOCKED · app** — seen 5× in 4 scenario(s)
    > wait chain (2 threads):
    First hit: `stress_results/.../split_duplicate_reverse_export__1_41` at step **`leave editor`** (...)
    Scenarios: split_duplicate_reverse_export ×1, background_long_pressure ×2
    - **[0]** tid 27202 'DefaultDispatch' waits 502 ms in pthread_join for tid 27390 (exact, no timeout)
      `MsgLooper::~MsgLooper() (player/MsgLooper.cpp:34)` ← `JNIHelper::destroyPlayer() (...)`
    - **[1]** tid 27390 'Thread-20' is RUNNING on CPU (busy loop or long computation). Sampled now:
      `pthread_mutex_unlock` ← `Filter::~Filter() (video/Renderer/Filter/Filter.cpp:148)`
Nothing here is interpreted by a model: the chain is what ANRSan recorded.
"""
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

RE_HEAD = re.compile(r'^### (F\d{3}-[0-9a-f]{6})\s*$')
RE_META = re.compile(r'^\*\*(\w+) · (\w+) · ([\w-]+)\*\* — seen (\d+)× in (\d+) scenario')
RE_FIRST = re.compile(r'^First hit: `([^`]+)` at step \*\*`([^`]+)`\*\*')
RE_SCEN = re.compile(r'^Scenarios: (.+)$')
RE_ENTRY = re.compile(r'^- \*\*\[([^\]]+)\]\*\* tid (\d+) \'([^\']*)\'\s*:?\s*(.*)$')
RE_FRAME = re.compile(r'`([^`]+)`')
RE_FUNC_LOC = re.compile(r'^(.*?)\s*\(([^()]+:\d+)\)$')


@dataclass
class Frame:
    func: str
    loc: str = ''


@dataclass
class ChainEntry:
    idx: int
    tid: int
    name: str
    text: str                          # ANRSan's own sentence for this link
    kind: str = 'unknown'              # cond | join | mutex | running | opaque | main-wait
    wait_ms: Optional[int] = None
    timeout: Optional[str] = None      # 'none' | '<n> ms' | None
    target_tid: Optional[int] = None   # the thread this one waits for (exact for join/mutex, handoff for cond)
    frames: List[Frame] = field(default_factory=list)

    @property
    def top_app_frame(self) -> Optional[Frame]:
        return self.frames[0] if self.frames else None


@dataclass
class Finding:
    id: str
    severity: str = ''
    rule: str = ''
    category: str = ''
    count: int = 0
    n_scenarios: int = 0
    first_source: str = ''
    first_step: str = ''
    scenarios: List[str] = field(default_factory=list)
    headline: str = ''
    chain: List[ChainEntry] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _classify(text: str):
    t = text
    kind, wait_ms, timeout, target = 'unknown', None, None, None
    m = re.search(r'waits (\d+) ms', t)
    if m:
        wait_ms = int(m.group(1))
    if 'pthread_join' in t:
        kind = 'join'
    elif ' on cond ' in t:
        kind = 'cond'
    elif 'mutex' in t:
        kind = 'mutex'
    elif 'RUNNING' in t:
        kind = 'running'
    elif 'not in a pthread wait' in t:
        kind = 'opaque'
    if 'NO timeout' in t or 'no timeout' in t:
        timeout = 'none'
    else:
        mt = re.search(r'timeout (\d+) ms', t)
        if mt:
            timeout = f'{mt.group(1)} ms'
    m = re.search(r'for tid (\d+)', t) or re.search(r'woken by tid (\d+)', t) or re.search(r'owner tid (\d+)', t) \
        or re.search(r'held by tid (\d+)', t)
    if m:
        target = int(m.group(1))
    return kind, wait_ms, timeout, target


def _frames(line: str) -> List[Frame]:
    out = []
    for raw in RE_FRAME.findall(line):
        m = RE_FUNC_LOC.match(raw.strip())
        out.append(Frame(m.group(1).strip(), m.group(2)) if m else Frame(raw.strip()))
    return out


def parse(path: str) -> List[Finding]:
    findings, cur, entry, in_details = [], None, None, False
    for raw in open(path, encoding='utf-8'):
        line = raw.rstrip('\n')
        if line.startswith('<details'):
            in_details = True
        if line.startswith('</details>'):
            in_details = False
            continue
        if in_details:
            continue
        m = RE_HEAD.match(line)
        if m:
            cur = Finding(id=m.group(1))
            findings.append(cur)
            entry = None
            continue
        if cur is None:
            continue
        m = RE_META.match(line)
        if m:
            cur.severity, cur.rule, cur.category = m.group(1), m.group(2), m.group(3)
            cur.count, cur.n_scenarios = int(m.group(4)), int(m.group(5))
            continue
        if line.startswith('> '):
            cur.headline = line[2:].strip()
            continue
        m = RE_FIRST.match(line)
        if m:
            cur.first_source, cur.first_step = m.group(1), m.group(2)
            continue
        m = RE_SCEN.match(line)
        if m:
            cur.scenarios = [s.strip().split(' ×')[0] for s in m.group(1).split(',')]
            continue
        m = RE_ENTRY.match(line)
        if m:
            label, rest = m.group(1), m.group(4).strip()
            if label.isdigit():                      # runtime rule: numbered wait chain
                idx, text = int(label), rest
            else:                                    # pattern rule: '[joins (no timeout) here]', '[main thread waits here]'
                idx, text = len(cur.chain), (label + (' ' + rest if rest else '')).strip()
            kind, wait_ms, timeout, target = _classify(text)
            if 'holding' in label.lower():
                kind, timeout, target = 'holds', None, None
            if kind == 'unknown':
                low = label.lower()
                kind = 'holds' if 'holding' in low else 'join' if 'join' in low else 'mutex' if ('lock' in low or 'mutex' in low) else 'cond' if 'wait' in low else kind
            if timeout is None and ('no timeout' in label.lower() or 'NO timeout' in cur.headline or 'no timeout' in cur.headline):
                timeout = 'none'
            if target is None and idx == 0:
                mt = re.search(r'(?:joins|waits (?:on|for)|blocked by|held by) tid (\d+)', cur.headline)
                if mt:
                    target = int(mt.group(1))
            entry = ChainEntry(idx, int(m.group(2)), m.group(3), text, kind, wait_ms, timeout, target)
            cur.chain.append(entry)
            continue
        if entry is not None and line.startswith('  ') and ('`' in line or '_(no app frames)_' in line):
            if '`' in line:
                entry.frames = _frames(line)
            continue
    # resolve 'handoff' targets: a cond waiter whose target is unknown points at the next entry
    for f in findings:
        tids = {e.tid for e in f.chain}
        for i, e in enumerate(f.chain):
            nxt = f.chain[i + 1].tid if i + 1 < len(f.chain) else None
            nxt_kind = f.chain[i + 1].kind if i + 1 < len(f.chain) else None
            if e.kind in ('cond', 'join', 'mutex') and nxt is not None and nxt_kind != 'holds' and (e.target_tid is None or e.target_tid not in tids):
                # the summary line may be truncated ('woken by tid 18'); the next link is ANRSan's own ordering
                e.target_tid = nxt
    return findings


NOISE_LOC = ('anrsan/',)
NOISE_FUNC = ('pthread_', 'now_ns', '__', 'std::')


def app_frames(e: ChainEntry):
    return [fr for fr in e.frames if not fr.loc.startswith(NOISE_LOC) and not fr.func.startswith(NOISE_FUNC)]


def get(findings: List[Finding], fid: str) -> Finding:
    for f in findings:
        if f.id == fid or f.id.startswith(fid):
            return f
    raise KeyError(f'no finding {fid}')


def fingerprint(f: Finding) -> str:
    """Rule + app-frame function names, the same idea anrsan_findings.py uses, so lab chains match field stacks
    across rebuilds and line changes."""
    parts = [f.rule]
    for e in f.chain:
        parts.append('|'.join(fr.func for fr in app_frames(e)[:3]) or '#')
    return '\n'.join(parts)
