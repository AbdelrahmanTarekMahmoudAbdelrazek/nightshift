"""The before/after run log the judging panel verifies. One row per real run, clock times only."""
import csv
import datetime as dt
import os
from collections import defaultdict

FIELDS = ['date', 'flow', 'issue_or_pr', 'engineer', 'mode', 'minutes', 'review_minutes', 'outcome', 'notes']
FLOWS = ('triage', 'reproduce', 'guard')


def add(path, flow, issue, engineer, mode, minutes, review_minutes=0, outcome='', notes='', date=None):
    assert flow in FLOWS, f'flow must be one of {FLOWS}'
    assert mode in ('before', 'after'), 'mode must be before|after'
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(dict(date=date or dt.date.today().isoformat(), flow=flow, issue_or_pr=issue, engineer=engineer,
                        mode=mode, minutes=int(minutes), review_minutes=int(review_minutes), outcome=outcome, notes=notes))


def rows(path):
    if not os.path.exists(path):
        return []
    return list(csv.DictReader(open(path, encoding='utf-8')))


def summary(path, runs_per_month):
    """Competition formula per flow: (before - after) x runs/month / 60. 'after' = agent minutes + human review."""
    acc = defaultdict(lambda: {'before': [], 'after': []})
    for r in rows(path):
        if str(r.get('outcome') or '').startswith('void'):   # kept for the audit trail, never counted (not a real run)
            continue
        total = int(r['minutes'] or 0) + int(r['review_minutes'] or 0)
        acc[r['flow']][r['mode']].append(total)
    out, grand = [], 0.0
    for flow in FLOWS:
        b, a = acc[flow]['before'], acc[flow]['after']
        mb = sum(b) / len(b) if b else None
        ma = sum(a) / len(a) if a else None
        rpm = int(runs_per_month.get(flow, 0)) if runs_per_month else 0
        hours = (mb - ma) * rpm / 60 if (mb is not None and ma is not None) else None
        ok = len(b) >= 5 and len(a) >= 5
        out.append(dict(flow=flow, n_before=len(b), n_after=len(a), min_before=mb, min_after=ma, runs_per_month=rpm,
                        hours_per_month=hours, panel_ready=ok))
        if hours:
            grand += hours
    return out, grand


def format_summary(out, grand):
    lines = ['flow       before(n, avg min)  after(n, avg min)  runs/mo  hours/mo  panel-ready']
    for o in out:
        mb = '-' if o['min_before'] is None else f"{o['min_before']:.0f}"
        ma = '-' if o['min_after'] is None else f"{o['min_after']:.0f}"
        h = '-' if o['hours_per_month'] is None else f"{o['hours_per_month']:.1f}"
        lines.append(f"{o['flow']:<10} {o['n_before']:>3}, {mb:>6}          {o['n_after']:>3}, {ma:>6}        "
                     f"{o['runs_per_month']:>4}   {h:>7}   {'yes' if o['panel_ready'] else 'no (need 5+5)'}")
    lines.append(f"total verified hours returned per month: {grand:.1f}")
    return '\n'.join(lines)
