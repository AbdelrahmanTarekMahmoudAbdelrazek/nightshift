---
name: scenario-match
description: Map field evidence (breadcrumbs, last screen, native log sites, thread-dump frames) to stress scenarios in tools/stress/scenarios.py, or draft a new scenario when none fits. Use before running the lab for an engine-attributed issue.
---

# Scenario match

Goal: pick the 2–5 scenarios most likely to walk the same engine path the field ANR took, or write a new one.

## Inputs
- Field evidence: `last_event` values (e.g. `video_editing_cancel`, `ve_play_pause_btn`), `last_screen`, native log sites (`MsgLooper.cpp:MsgLooper::~MsgLooper`), and symbolized frames when a dump exists.
- The scenario catalogue: run `python3 tools/nightshift/sentinel.py match --evidence ...` for the keyword ranking, and read `tools/stress/scenarios.py` for the real steps (each scenario is a short function over `Editor` methods: `seek_storm`, `split_at`, `export_full`, `abort_export`, `apply_effect`, `leave_editor`, lifecycle helpers).

## Output
A ranked list, each line: scenario name, why (which evidence token maps to which step), expected ANRSan rule if it reproduces (e.g. `CRITICAL_JOIN` for teardown joins, `MAIN_UNTIMED_WAIT` for `MsgLooper::Get` from the UI thread).

If nothing scores above 1: draft a **new scenario** as a Python function in the exact style of the file:
```python
@scenario('lifecycle', 'export', 'abort')
def export_abort_then_background(ed, r):
    """Abort an export, background the app within 1 s, return. Field case: <issue id>, last_event video_editing_cancel then trim_memory."""
    ed.export_start()
    ed.idle(r.uniform(0.5, 2.0))
    ed.abort_export()
    ed.background(r.uniform(0.2, 1.0))
    ed.foreground()
    ed.leave_editor()
```
Use only `Editor` methods that exist in `tools/stress/zesty.py`; if a step needs a new helper, say so instead of inventing one. The docstring must cite the field issue id. The scenario is reviewed like code before it is merged.

## Rules
- Prefer scenarios whose steps include the *last* breadcrumb action; the ANR is usually within seconds of it.
- Teardown evidence (`~MsgLooper`, `destroyPlayer`, `leave editor`) ranks `lifecycle` scenarios first.
- Never claim a scenario reproduces anything; that is decided by the ANRSan fingerprint match after the run.
