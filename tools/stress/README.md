# Editor stress scenarios + ANRSan vulnerability scan

The point: run many scenarios on an ANRSan build so the engine walks as many threading paths as
possible, then read **one merged, ranked list of ANRSan findings** (`anrsan_findings.md`) that says
which scenario and which step first hit each one. ANRs and crashes are caught on the way.

## Overnight (leave it running)

```bash
caffeinate -dimsu python3 tools/stress/scenarios.py overnight --hours 14
```

Every scenario in random order + one chaos run (150 steps) per cycle, repeated until `--hours` is up.
`stress_results/<time>/REPORT.md` is rewritten every 5 scenarios (real ANRs/crashes with replay
commands, ANRSan findings, per-scenario table, automation errors), so a current report exists even
if the run is killed. Also: 30-min limit per scenario, waits up to 30 min for an unplugged phone,
full app reset after 4 automation errors in a row, logcats of passing scenarios gzipped.

## ANRSan workflow

```bash
./gradlew installProductionInternalDebug -PenableAnrsan=true
python3 tools/stress/scenarios.py run --skip-tag slow --repeat 3      # coverage pass
python3 tools/stress/scenarios.py chaos --steps 500                  # random paths
python3 tools/stress/anrsan_findings.py stress_results               # merge every run so far
```

What the runner does for ANRSan automatically:

- **Raises the report cap.** ANRSan stops after `max_reports=300` per process; the runner sets
  `debug.anrsan.options` (your `wrap.sh` reads it) to `max_reports=1000000` for the run, restarts the
  app, and restores your old value at the end. Change with `--anrsan-options "max_reports=…:main_block_ms=…"`.
- **Checks it is really loaded** (`libanrsan.so` in `/proc/<pid>/maps` via `run-as`) and prints
  `ANRSan: ACTIVE`. `--anrsan on` refuses to run without it.
- **Fresh app process per scenario** (`--fresh auto|on|off`). ANRSan reports each stack once per
  process, so a new process gives every scenario its complete set and exact attribution. The draft is
  saved first (leave editor → force-stop).
- **Builds `anrsan_findings.md/.csv/.json`** in the results folder when the run ends.

`anrsan_findings.py` symbolizes with `tools/anrsan/anrsan_symbolize.py` (cached as
`anrsan.sym.txt`), fingerprints every report by rule + app frames (function names, so call-site line
changes and rebuilds still match), merges, and ranks:

| severity | meaning |
|---|---|
| CRITICAL | deadlock / cycle, main thread blocked, lock-order inversion, self-deadlock |
| HIGH | main thread untimed wait, critical thread joins/blocks, long lock holds |
| MEDIUM | untimed waits on threads main depends on, waits/joins under a lock (in app code) |
| LOW `framework-sync` | the same patterns inside MediaCodec/MediaMuxer/AAudio/EGL calls |
| INFO `likely-idle` | a thread parked on its own work queue that ANRSan mistook for blocked |

The "Discovery per log" table shows new unique findings per scenario: when it stays at 0, the
scenarios have saturated — add scenarios or run chaos with new seeds.

---

## Scenarios (ANR / crash hunting too)

43 scripted scenarios + a seeded chaos mode that drive the real editor over adb and fail on
**ANR or crash**. Controls are found by the app's `AutomationTags` (contentDescription, e.g.
`ve_tab_split_clip`) and resource-ids (`videoTrackView`, `export`, `percLabel`, `cancel_button_warn`),
so nothing needs calibrating per device.

## Setup (once)

1. Install the build you want to test (any flavour; with `-PenableAnrsan=true` you also get ANRSan
   reports counted per scenario).
2. Make a **short test draft** (10–30 s, 2+ clips, at least one with audio) and make sure it is the
   **first item in My Projects**. Keep a copy: scenarios edit it. After each passing scenario the
   runner undoes back to the start and warns if the draft length drifted.
3. `pip` nothing — stdlib only. `adb` on PATH, one device connected (or `--serial`).

## Run

```bash
python3 tools/stress/scenarios.py list                         # catalogue + tags
python3 tools/stress/scenarios.py run                          # everything once
python3 tools/stress/scenarios.py run 'split_*' --repeat 5
python3 tools/stress/scenarios.py run --tag abort --loop       # until Ctrl-C
python3 tools/stress/scenarios.py run --skip-tag slow --shuffle --repeat 3
python3 tools/stress/scenarios.py chaos --steps 300 --seed 7   # random weighted walk
python3 tools/stress/scenarios.py replay export_abort_mid --seed 318031   # rerun a failure
python3 tools/stress/scenarios.py probe                        # tags/ids on the current screen
```

Tags: `seek split export abort effects undo lifecycle play audio speed slow chaos`.

## Results

`stress_results/<timestamp>/<scenario>__<n>/`

| file | when |
|---|---|
| `steps.log` | always — every step with a timestamp |
| `logcat.txt` | always — main/system/crash/events for that scenario only |
| `anr_trace.txt` | ANR — latest `data_app_anr` dropbox entry (all thread stacks) |
| `data_app_native_crash.txt` / `data_app_crash.txt` | crash |
| `fail.png` / `ui_error.png` + `screen.txt` | failure / automation error |

`summary.csv` + a printed table: runs, pass, ANR, crash, automation errors, ANRSan count, failing seeds.

Every step is also written to logcat under tag `ZSTRESS`, so
`adb logcat -s ZSTRESS ANRSAN` shows which step produced each ANRSan report.

## Status meanings

- `FAIL_ANR` — `am_anr` / `ANR in com.myzesty` / system "isn't responding" dialog.
- `FAIL_CRASH` — Java crash, `Fatal signal`, tombstone.
- `FAIL_DIED` — process died without an LMK kill or a deliberate force-stop.
- `FAIL_EXPORT_STUCK` — export percent frozen for 90 s (`ZESTY_EXPORT_STALL_S` to change). Native and
  Java stacks of all threads are saved (`native_stacks.txt`, `java_stacks.txt`, debuggable builds).
- `ERROR` — the *automation* couldn't do a step (element missing, offline effects list…). Not an app bug;
  look at `screen.txt`.

Main-thread wedges that receive no input never become ANRs, so every scenario ends with a
`settle` window that sends a no-op key (`KEYCODE_F12`) every 2 s: if main is stuck, input dispatch
times out and the system raises the ANR.

## Adding a scenario

```python
@scenario('split', 'export')
def my_case(ed, r):
    """One-line description shown by `list`."""
    ed.split_at(r.uniform(0.2, 0.8))
    ed.seek_storm(40)
    ed.export_abort(at_pct=50)
```

Building blocks on `ed` (see `zesty.py`): `seek_storm seek_to seek_start seek_end toggle_play set_playing
split split_at delete_clip duplicate_clip reverse_clip change_speed change_volume flip_or_rotate undo redo
effects_browse add_sticker add_text tune freeze export_full export_start export_wait_done export_abort
background trim_memory rotate screen_off_on leave_editor open_draft force_stop_reopen idle settle`.

## How the bottom menu is found

The editor's bottom menu (`menu_container`, y 1475–2400) is drawn below the window edge the
accessibility layer reports (2177), so `uiautomator` never lists Edit / Effects / Split / ….
For those, the runner reads the real view tree (`adb shell dumpsys activity top`), takes the
`bottom_bar` RecyclerView's children with their true positions, and taps item *i* in the order of
`ListUtil.getMainNav` / `getClipEdit` (`MAIN_MENU` / `CLIP_MENU` in `zesty.py`). Items off-screen are
reached by scrolling the bar to its start or end. In the clip menu, the AI-credit crown on DeNoise
(index 5) is checked first, so an index can never land on Delete when Split was meant.
**If you reorder those lists in ListUtil.kt, update `MAIN_MENU` / `CLIP_MENU`.**

## Known limits

- Clip-menu items in the middle of the bar (DeNoise … Flip H, indexes 5–10 on a 1080-px screen) are
  not reachable by the start/end scroll; no scenario needs them (rotate is used instead of flip).

- The playhead clock has 1 s resolution, so `seek_to` lands within ~0.6 s of the target.
- `uiautomator dump` can stall while the UI animates; taps then fall back to the last known
  position of that control. Storms (seek/undo) never dump between taps.
- Undo history is lost when the editor is reopened, so `reopen_draft_cycle`, `force_stop_*` and
  the `background_*` scenarios can leave edits in the draft — the drift warning tells you when to
  restore it.
- Effects / stickers need network on first use; offline they show up as `ERROR`, not failures.
