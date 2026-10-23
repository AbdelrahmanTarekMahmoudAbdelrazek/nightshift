"""Deterministic Mermaid diagrams for a wait chain.

Root cause: generated only from what ANRSan recorded (threads, waits, frames). The model never draws it.
Solution: the same lanes, with the edge the patch changes relabelled; produced only once the fix was
verified by a replay (the caller decides that; this module just draws what it is told).
"""
import html
from typing import Dict, List, Optional

from .anrsan import Finding, ChainEntry, app_frames

RULE_TITLES = {
    'CRITICAL_BLOCKED': 'a thread the main thread depends on is blocked on another thread',
    'CRITICAL_JOIN': 'a thread the main thread waits on joins a thread that is still running',
    'MAIN_BLOCKED': 'the main thread is blocked',
    'MAIN_UNTIMED_WAIT': 'the main thread waits with no timeout',
    'MAIN_LONG_TIMED_WAIT': 'the main thread waits with a long timeout',
    'DEADLOCK': 'the wait chain loops back on itself',
    'LOCK_ORDER_INVERSION': 'two mutexes are taken in opposite orders',
    'SELF_DEADLOCK': 'a thread locks a mutex it already holds',
    'JOIN_UNDER_LOCK': 'a join while holding a mutex',
    'WAIT_UNDER_LOCK': 'a blocking wait while holding a mutex',
    'LONG_HOLD': 'a mutex held for a long time while others wait',
    'MAIN_LOCK_WAIT': 'the main thread waited on a contended mutex',
}


def _esc(s: str) -> str:
    return s.replace('"', '#quot;').replace('<', '#lt;').replace('>', '#gt;')


def _short(func: str, n=38) -> str:
    f = func.split('(')[0].strip()
    return f if len(f) <= n else f[: n - 1] + '…'


def _node_label(e: ChainEntry) -> str:
    head = f"tid {e.tid} '{e.name}'"
    fa = app_frames(e)
    fr = fa[0] if fa else e.top_app_frame
    where = f"{_esc(_short(fr.func))}<br/><small>{_esc(fr.loc)}</small>" if fr and fr.loc else (_esc(_short(fr.func)) if fr else 'no app frames')
    state = {
        'join': 'blocked in pthread_join',
        'cond': 'blocked on condition variable',
        'mutex': 'blocked on mutex',
        'running': 'RUNNING on CPU',
        'opaque': 'in a syscall / binder / epoll',
        'holds': 'HOLDS a mutex acquired here while waiting above',
    }.get(e.kind, e.kind)
    if e.wait_ms is not None:
        state += f', {e.wait_ms} ms so far'
    if e.timeout == 'none':
        state += ', no timeout'
    elif e.timeout:
        state += f', timeout {e.timeout}'
    return f"<b>{_esc(head)}</b><br/>{_esc(state)}<br/>{where}"


def _edge_label(e: ChainEntry) -> str:
    return {
        'join': 'join(), waits for exit',
        'cond': 'waits for a signal (handoff)',
        'mutex': 'waits for the mutex',
    }.get(e.kind, 'waits for')


def _nid(f: Finding, e: ChainEntry) -> str:
    return f'n{e.idx}'


def _target_node(f: Finding, e: ChainEntry):
    """Node id of the link `e` waits for: the first chain entry with that tid after `e`, else before it."""
    if e.target_tid is None:
        return None
    after = [x for x in f.chain if x.tid == e.target_tid and x.idx > e.idx]
    before = [x for x in f.chain if x.tid == e.target_tid and x.idx != e.idx]
    pick = (after or before)
    return _nid(f, pick[0]) if pick else None


def root_cause(f: Finding, title: Optional[str] = None) -> str:
    """One node per chain link, one edge per wait; the link everyone waits for is marked."""
    t = title or f"{f.id} · {f.rule}: {RULE_TITLES.get(f.rule, f.headline)}"
    lines = ['flowchart TD', f'  %% {t}', '  classDef waiting fill:none,stroke:#6b7280,stroke-width:1.25px;',
             '  classDef blocker fill:#fde8e8,stroke:#a32d2d,stroke-width:2px;',
             '  classDef running fill:#fff4e5,stroke:#b45309,stroke-width:2px;']
    if not f.chain:
        lines.append(f'  n0["{_esc(f.headline or f.rule)}"]:::blocker')
        return '\n'.join(lines)
    for e in f.chain:
        lines.append(f'  {_nid(f, e)}["{_node_label(e)}"]')
    extra_nodes = set()
    for e in f.chain:
        tgt = _target_node(f, e)
        if tgt is None and e.target_tid is not None:
            tgt = f'x{e.target_tid}'
            if tgt not in extra_nodes:
                extra_nodes.add(tgt)
                lines.append(f'  {tgt}["<b>tid {e.target_tid}</b><br/>still running (named in the report)"]')
                lines.append(f'  class {tgt} running;')
        if tgt is not None:
            style = '-.->' if e.kind == 'cond' else '-->'
            lines.append(f'  {_nid(f, e)} {style}|"{_esc(_edge_label(e))}"| {tgt}')
    if f.rule == 'DEADLOCK' and len(f.chain) > 1:
        lines.append(f'  {_nid(f, f.chain[-1])} -->|"cycle"| {_nid(f, f.chain[0])}')
    # a held-lock link is drawn as a dashed tie to its waiter, not as a wait target
    for e in f.chain:
        if e.kind == 'holds':
            owner = [x for x in f.chain if x.tid == e.tid and x.idx < e.idx]
            if owner:
                lines.append(f'  {_nid(f, owner[-1])} -. "holding" .- {_nid(f, e)}')
    last = f.chain[-1]
    for e in f.chain[:-1]:
        lines.append(f'  class {_nid(f, e)} waiting;')
    if extra_nodes or last.kind == 'holds':
        lines.append(f'  class {_nid(f, last)} waiting;')
        if last.kind == 'holds':
            lines.append(f'  class {_nid(f, f.chain[0])} blocker;')
    elif False:
        lines.append(f'  class {_nid(f, last)} waiting;')
    else:
        lines.append(f"  class {_nid(f, last)} {'running' if last.kind == 'running' else 'blocker'};")
    lines.append(f'  %% first hit: {f.first_source} at step "{f.first_step}"; seen {f.count}x in {f.n_scenarios} scenarios')
    return '\n'.join(lines)


def solution(f: Finding, changes: Dict[int, str], verified: bool, title: Optional[str] = None) -> str:
    """`changes` maps a chain index to the new behaviour of that link, taken from the patch diff
    (e.g. {0: 'join with 2 s timeout, then detach', 1: 'checks abort flag every 500 ms'}).
    Drawn in green only when `verified` (replay with the same seed came back clean)."""
    t = title or f"{f.id} · fix: {'verified by replay' if verified else 'NOT yet verified'}"
    ok = 'fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px' if verified else 'fill:#fff8e1,stroke:#b45309,stroke-width:2px,stroke-dasharray:4 4'
    lines = ['flowchart TD', f'  %% {t}', f'  classDef changed {ok};', '  classDef same fill:none,stroke:#6b7280,stroke-width:1.25px;']
    for e in f.chain:
        new = changes.get(e.idx)
        label = f"<b>tid {e.tid} '{_esc(e.name)}'</b><br/>{_esc(new)}" if new else f"<b>tid {e.tid} '{_esc(e.name)}'</b><br/>unchanged"
        lines.append(f'  {_nid(f, e)}["{label}"]')
        lines.append(f"  class {_nid(f, e)} {'changed' if new else 'same'};")
    for e in f.chain:
        tgt = _target_node(f, e)
        if tgt is not None:
            lbl = 'bounded wait' if e.idx in changes else _edge_label(e)
            lines.append(f'  {_nid(f, e)} -->|"{_esc(lbl)}"| {tgt}')
    lines.append(f"  %% {'replay clean: the chain no longer forms' if verified else 'hypothesis only: replay has not confirmed this fix'}")
    return '\n'.join(lines)


def html_page(blocks: List[str], title='Night Shift diagrams') -> str:
    """Self-contained preview page (Mermaid from cdnjs) for a quick look or for attaching to a ticket."""
    body = '\n'.join(f'<section><pre class="mermaid">{html.escape(b)}</pre></section>' for b in blocks)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<style>body{{font:14px system-ui;margin:24px;max-width:960px}}section{{margin:0 0 32px}}</style></head>
<body><h1>{html.escape(title)}</h1>{body}
<script>mermaid.initialize({{startOnLoad:true,securityLevel:'loose',flowchart:{{htmlLabels:true}}}});</script></body></html>"""
