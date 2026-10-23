#!/usr/bin/env python3
"""
scenarios.py — scenario catalogue + runner for MyZesty editor stress testing (ANR / crash hunting).

  python3 tools/stress/scenarios.py list
  python3 tools/stress/scenarios.py run                       # every scenario once
  python3 tools/stress/scenarios.py run 'split_*' export_abort_mid --repeat 5
  python3 tools/stress/scenarios.py run --tag export --loop   # until Ctrl-C
  python3 tools/stress/scenarios.py chaos --steps 300 --seed 7
  python3 tools/stress/scenarios.py replay 'split_seek_storm_export' --seed 123456   # rerun a failing seed
  python3 tools/stress/scenarios.py probe                     # print tags/ids on the current screen

Start state: app installed, a short test draft (10–30 s, 2+ clips) as the FIRST item in My Projects.
Results: stress_results/<timestamp>/<scenario>__<n>/{steps.log, logcat.txt, fail.png, anr_trace.txt}
         stress_results/<timestamp>/summary.csv  (+ printed table)
"""
import argparse, csv, fnmatch, json, os, random, re, sys, time, traceback
from collections import OrderedDict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zesty import Device, UI, Monitor, Editor, AppFailure, UIError, ANRSAN_SERIOUS, PKG, T
from zesty import MAIN_MENU, CLIP_MENU  # bottom-bar item order, for ed.bar.tap(i, n)

SCENARIOS = {}


def scenario(*tags):
    def deco(fn):
        SCENARIOS[fn.__name__] = (fn, set(tags), (fn.__doc__ or '').strip().split('\n')[0])
        return fn
    return deco


# ═══════════════════════════ NIGHT SHIFT REPROS ═══════════════════════════
# Written by Night Shift from field evidence; each docstring names the Crashlytics issue it reproduces.

@scenario('media', 'edit', 'nightshift')
def add_media_decode_failure(ed, r):
    """Crashlytics 2bc43cd6: add a clip whose decoder fails (debug hook), then use it -> SIGSEGV in get_media_starting_time."""
    ed.set_playing(False)
    ed.add_media(fail_decode=True, pick=r.randint(0, 3))
    # the field app kept using the clip that was never added: volume, seek, play across it
    for _ in range(r.randint(2, 4)):
        ed.seek_swipe(r.uniform(0.3, 1.0), r.randint(60, 200))
        ed.idle(r.uniform(0.2, 0.8))
    ed.change_volume()
    ed.set_playing(True)
    ed.idle(2)
    ed.set_playing(False)


@scenario('lab', 'nodraft')
def lab_make_test_draft(ed, r):
    """Lab upkeep: make a fresh test draft the FIRST item in My Projects (use when the old one lost its clips)."""
    ed.dev.restore_env()
    ed.step('lab upkeep: new test draft')
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    ed.create_draft()
    ed.idle(5)
    ed.dev.key('KEYCODE_BACK')                      # leave the editor: the project is saved as the newest draft
    ed.idle(4)


@scenario('lab', 'nodraft', 'audio')
def audio_plain_splits(ed, r):
    """Audio Check: New Project from the newest video (ns_audio_splits.mp4), split it into 7 pieces, export once."""
    ed.dev.restore_env()
    ed.step('audio check: new project from the test clip')
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    ed.create_draft()
    ed.idle(3)
    ed.set_playing(False)
    for k in range(1, 7):                            # 6 cuts -> 7 pieces, evenly spread
        ed.step(f'audio check: split {k}/6')
        ed.split_at(k / 7.0, strict=True)       # an unsplit export makes every seam test meaningless
        ed.idle(1.5)
    ed.idle(2)
    ed.export_full()
    ed.idle(3)


@scenario('lab', 'nodraft')
def lab_dka_check(ed, r):
    """Lab upkeep: does "Don't keep activities" through the Settings app really destroy a backgrounded activity?"""
    on = ed._dka_ui(True)
    ed.dev.launch()
    time.sleep(6)
    t0 = ed.log_mark()
    ed.dev.key('KEYCODE_HOME')
    hit = ed.wait_log(r'I wm_on_destroy_called: \[\d+,\d+,com\.video\.myzesty', 8, since=t0)
    ed.log(f'    LAB DKA switch={on} backgrounded activity destroyed={bool(hit)} {hit[:120]}')
    off = ed._dka_ui(False)
    ed.dev.launch()
    time.sleep(5)
    t1 = ed.log_mark()
    ed.dev.key('KEYCODE_HOME')
    hit2 = ed.wait_log(r'I wm_on_destroy_called: \[\d+,\d+,com\.video\.myzesty', 6, since=t1)
    ed.log(f'    LAB DKA off={off} destroyed after OFF={bool(hit2)} (should be False)')
    ed.dev.launch()


@scenario('lab', 'nodraft')
def lab_control_check(ed, r):
    """Lab upkeep: the debug build's lab control answers, and its two setup shortcuts land where taps land
    (open_draft -> editor, open_slideshow 3 -> slideshow screen). Prints how long each took."""
    ed.dev.restore_env()
    ed.step('lab control: ping')
    if not ed.lab('ping', timeout=15):
        raise UIError('lab control did not answer (debug build without app/src/debug LabControl?)')
    mark = ed.log_mark()
    ed.lab('ping', timeout=10)
    if not ed.wait_log('LAB ok ping', 10, since=mark):
        raise UIError('wait_log did not see the LAB ok ping line')
    mark = ed.log_mark()
    ed.lab('ping', timeout=10)
    if not ed.rotate_when('LAB ok ping', 10, since=mark, back_after=1):
        raise UIError('rotate_when did not fire on the LAB ok ping line')
    t = time.time()
    ed.open_draft()
    ed.log(f'    open_draft -> editor in {time.time() - t:.1f} s')
    ed.leave_editor()
    t = time.time()
    ed.open_slideshow(3)
    ed.log(f'    open_slideshow(3) -> slideshow screen in {time.time() - t:.1f} s; clips in strip: {ed.slideshow_media_count()}')


@scenario('media', 'edit', 'nightshift', 'lifecycle')
def open_draft_decode_failure(ed, r):
    """Crashlytics 2bc43cd6: the clip's decoder fails while the draft opens (debug hook) so add_video returns -1,
    then the editor keeps using that clip -> SIGSEGV in get_media_starting_time (empty layer -> address 0)."""
    ed.leave_editor()
    # fail exactly one clip (1st or 2nd) so the draft still opens with a hole in the timeline;
    # the random token makes the value new, which restarts the hook's counter
    ed.dev.setprop('debug.zesty.hook.fail_add_video', f'{r.randint(1, 2)}:{r.randint(1000, 9999)}')
    try:
        ed.open_draft()
        ed.idle(3)
    finally:
        ed.dev.setprop('debug.zesty.hook.fail_add_video', '0')
    for _ in range(r.randint(2, 4)):
        ed.seek_swipe(r.uniform(0.2, 1.0), r.randint(60, 200))
        ed.idle(r.uniform(0.2, 0.8))
    ed.set_playing(True)
    ed.idle(2)
    ed.set_playing(False)


LONG_AUDIO_CLIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'repro_assets', 'with_audio.mov')


def push_newest_video(ed, src=LONG_AUDIO_CLIP, name='ns_long_audio.mov'):
    """Put a long clip WITH audio at the top of the gallery's Videos tab (newest first)."""
    dst = f'/sdcard/DCIM/NightShift/{name}'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    if name not in ed.dev.sh('ls /sdcard/DCIM/NightShift'):
        ed.dev.adb('push', src, dst, timeout=180)
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(2)


def background_keep_screen(ed, seconds, pressure='RUNNING_LOW', camera=True):
    """Home + memory pressure, then back to whatever screen the app was on (here: the frozen export screen).
    Unlike ed.background() it does not reopen the draft from the home screen."""
    ed.step(f'background {seconds:.0f}s with memory pressure, return to the same screen')
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    if camera:
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
        time.sleep(2)
    ed.dev.sh(f'am send-trim-memory {PKG} {pressure}')
    ed.idle(seconds)
    ed.dev.launch()                                  # brings the existing task back (export screen still on top)
    ed.idle(3)
    ed.mon.allow_death = False
    if ed.dev.pid() == '':
        raise UIError('app was killed in the background; the field user came back to a live app')


def export_eta(ed, watch=5.0):
    """Seconds the running export still needs, from its own progress rate over `watch` seconds (the engine's
    MsgGetExportingProgress lines; only polled while the app is in front). None when it cannot tell."""
    p0, t0 = ed.mon.progress_val, time.time()
    ed.idle(watch)
    p1, t1 = ed.mon.progress_val, time.time()
    if p0 is None or p1 is None or p1 <= p0:
        return None
    rate = (p1 - p0) / max(0.5, t1 - t0)            # percent per second
    return max(0.0, (100.0 - p1) / rate)


def paced_away(ed, r, away, eta, frac=0.45):
    """How long to stay away so the return (and the Cancel after it) lands mid-export on THIS phone: the recipe's own
    window, capped at `frac` of the time the export still needs. Fast lab phones otherwise finish the export first."""
    want = r.uniform(*away)
    if eta is None:
        return want
    paced = max(3.0, min(want, frac * eta))
    if paced < want:
        ed.log(f'    paced trigger: export needs ~{eta:.0f}s more, away {paced:.0f}s instead of {want:.0f}s')
    return paced


def _export_abort_clip_tool(ed, r, hook=False, camera=False, pressure='RUNNING_LOW', away=(15, 30)):
    """Field story of Crashlytics eb0d37d2 (ANR, main thread in getMediaDuration behind abort_export join):
    long export with audio -> app to background under memory pressure -> back -> Cancel -> Home again -> back ->
    close the export screen -> Edit -> Speed. hook=True forces the decoder freeze (debug build) that the field device
    got from Android MediaCodec; hook=False relies on the real conditions (pressure, camera) to freeze it."""
    ed.EXPORT_STALL_S = 10 ** 6                      # a frozen export is the point here, not a failure
    push_newest_video(ed)
    ed.add_media(pick=0)
    if hook:
        ed.dev.setprop('debug.zesty.hook.stall_audio_export', '1')   # armed BEFORE export: freezes as soon as audio starts
    try:
        ed.export_start()
        eta = export_eta(ed, r.uniform(3, 6))      # same wait as before, now also measuring how fast this export runs
        background_keep_screen(ed, paced_away(ed, r, away, eta), pressure=pressure, camera=camera)
        real_back = ed.back_to_editor                # the abort may never complete: do not wait 15 min for it
        ed.back_to_editor = lambda *a, **k: None
        try:
            ed.cancel_export()
        except UIError as e:
            ed.log(f'    abort did not complete (engine thread stuck in join, as in the field): {e}')
        finally:
            ed.back_to_editor = real_back
        ed.idle(1)
        background_keep_screen(ed, r.uniform(25, 40), pressure=pressure, camera=camera)
        sc = ed.screen()
        if sc is None or not ed.in_editor(sc):       # still on the export screen: its Cancel button just closes it
            w, h = ed._screen_size()
            for _ in range(2):
                ed.dev.tap(w // 2, int(h * 0.949))
                ed.idle(2)
                sc = ed.screen()
                if sc is not None and ed.in_editor(sc):
                    break
            ed.log('    export screen dismissed with its Cancel button')
        ed.clip_tools()                             # ve_edit_tool_btn
        # field main thread: setClipTools onItemClick -> EventBus -> onMessageEvent -> getMediaDurationByID ->
        # JNI getMediaDuration (no timeout). Trim is commented out of this build; Speed (OPEN_SPEED) takes that path.
        ed.menu_tap('speed')
        ed.settle(12)                               # input dispatch times out -> the ANR we are watching for
    finally:
        if hook:
            ed.dev.setprop('debug.zesty.hook.stall_audio_export', '0')


@scenario('export', 'abort', 'lifecycle', 'nightshift')
def export_bg_abort_clip_tool(ed, r):
    """Crashlytics eb0d37d2, ladder level 2 (natural): field user path with background + memory pressure, no hook."""
    _export_abort_clip_tool(ed, r, hook=False, pressure='RUNNING_LOW')


@scenario('export', 'abort', 'lifecycle', 'nightshift')
def export_bg_camera_abort_clip_tool(ed, r):
    """Crashlytics eb0d37d2, ladder level 3 (natural, harsher): camera open + critical memory pressure while the export
    runs in the background (the camera competes for codecs; Android may take the decoder away), no hook."""
    _export_abort_clip_tool(ed, r, hook=False, camera=True, pressure='RUNNING_CRITICAL', away=(40, 70))


@scenario('export', 'abort', 'lifecycle', 'nightshift')
def export_stuck_abort_clip_tool(ed, r):
    """Crashlytics eb0d37d2, ladder level 5 (hook-assisted): the audio decoder freeze is forced with a debug hook,
    everything after it is the real field chain. Reproduced 2/2 on 2026-10-06."""
    _export_abort_clip_tool(ed, r, hook=True, camera=True)


# ═══════════════════════════ SEEK ═══════════════════════════

@scenario('seek', 'export')
def seek_storm_export(ed, r):
    """Fast scrub storm while paused, then export immediately."""
    ed.set_playing(False)
    ed.seek_storm(r.randint(30, 60))
    ed.export_full()


@scenario('seek', 'export', 'play')
def seek_storm_playing_export(ed, r):
    """Scrub storm during playback, pause, export."""
    ed.set_playing(True)
    ed.seek_storm(r.randint(30, 60))
    ed.set_playing(False)
    ed.export_full()


@scenario('seek', 'play')
def seek_play_toggle_storm(ed, r):
    """Interleave scrubs with play/pause taps: preview pipeline start/stop under seeks."""
    for _ in range(r.randint(15, 30)):
        ed.seek_swipe(r.uniform(-1, 1), r.randint(30, 200))
        if r.random() < 0.6:
            ed.ui.tap_cached('id:play')
        ed.idle(r.uniform(0.05, 0.6))
    ed.set_playing(False)


@scenario('seek', 'play', 'export')
def seek_end_play_wrap_export(ed, r):
    """Play into the end of the timeline, jump to start, play again, export."""
    ed.seek_to(0.85)
    ed.set_playing(True)
    ed.idle(6)
    ed.seek_start()
    ed.idle(2)
    ed.set_playing(False)
    ed.export_full()


@scenario('seek', 'export')
def seek_storm_export_no_settle(ed, r):
    """Scrub storm and tap Export within ~100 ms of the last swipe (seek still in flight)."""
    ed.seek_storm(25, pause=(0, 0.05))
    ed.export_start()
    ed.export_wait_done()


# ═══════════════════════════ SPLIT ═══════════════════════════

@scenario('split', 'export')
def split_then_export(ed, r):
    """Split at 3 random points, export."""
    for f in sorted(r.uniform(0.1, 0.9) for _ in range(3)):
        ed.split_at(f)
    ed.export_full()


@scenario('split', 'seek', 'export')
def seek_storm_split_export(ed, r):
    """Scrub storm, split where it lands, export straight away."""
    ed.seek_storm(r.randint(20, 40))
    ed.idle(0.3)
    ed.split()
    ed.export_full()


@scenario('split', 'seek', 'export')
def split_seek_storm_export(ed, r):
    """Split 3x, scrub hard across the new boundaries, export."""
    for f in (0.25, 0.5, 0.75):
        ed.split_at(f + r.uniform(-0.08, 0.08))
    ed.seek_storm(r.randint(30, 60))
    ed.export_full()


@scenario('split')
def split_storm_short(ed, r):
    """Many splits ~0.5 s apart (hits split-too-short + tiny segments), then scrub."""
    ed.seek_to(r.uniform(0.2, 0.4))
    l, rr, y = ed._track_y()
    cx = (l + rr) // 2
    for _ in range(r.randint(6, 12)):
        ed.split()
        ed.dev.drag_no_fling(cx + 40, y, cx - 40)      # a hair forward
        ed.idle(0.3)
    ed.seek_storm(30)


@scenario('split', 'play', 'audio')
def split_play_across_boundary(ed, r):
    """Split, then repeatedly play through the cut point (audio seek-after-split glitch)."""
    f = r.uniform(0.3, 0.7)
    ed.split_at(f)
    for _ in range(4):
        ed.seek_to(max(0.0, f - 0.08))
        ed.set_playing(True)
        ed.idle(3)
        ed.set_playing(False)


@scenario('split', 'export')
def split_delete_export(ed, r):
    """Split twice, delete the middle piece, export."""
    ed.split_at(0.3)
    ed.split_at(0.6)
    ed.seek_to(0.45)
    ed.delete_clip()
    ed.export_full()


@scenario('split', 'undo', 'export')
def split_undo_redo_storm_export(ed, r):
    """Split 4x, then rapid undo/redo cycles, export."""
    for f in (0.2, 0.4, 0.6, 0.8):
        ed.split_at(f)
    for _ in range(3):
        ed.undo(4, gap=(0.02, 0.15))
        ed.redo(4, gap=(0.02, 0.15))
    ed.export_full()


@scenario('split', 'export')
def split_duplicate_reverse_export(ed, r):
    """Split, duplicate the piece, reverse it, export."""
    ed.split_at(r.uniform(0.3, 0.6))
    ed.duplicate_clip()
    ed.reverse_clip()
    ed.export_full()


@scenario('split', 'speed', 'export')
def split_speed_seek_export(ed, r):
    """Split, change speed of one piece, scrub, export."""
    ed.split_at(0.5)
    ed.change_speed()
    ed.seek_storm(25)
    ed.export_full()


@scenario('split', 'play')
def split_while_playing(ed, r):
    """Split 5x while the preview is playing."""
    ed.seek_start()
    ed.set_playing(True)
    for _ in range(5):
        ed.idle(r.uniform(0.8, 2.5))
        ed.split()
    ed.set_playing(False)


@scenario('split', 'export')
def split_volume_flip_export(ed, r):
    """Split, change volume, flip/rotate the piece, export."""
    ed.split_at(r.uniform(0.2, 0.8))
    ed.change_volume()
    ed.flip_or_rotate()
    ed.export_full()


# ═══════════════════════════ EXPORT / ABORT ═══════════════════════════

@scenario('export', 'abort')
def export_abort_early(ed, r):
    """Cancel export 0.3–1.5 s after it starts (encoder/muxer still starting)."""
    ed.export_abort(after_s=r.uniform(0.3, 1.5))
    ed.settle()


@scenario('export', 'abort')
def export_abort_mid(ed, r):
    """Cancel export at 20–70 %."""
    ed.export_abort(at_pct=r.randint(20, 70))
    ed.settle()


@scenario('export', 'abort')
def export_abort_late(ed, r):
    """Cancel export at ≥ 90 % (muxer finalising)."""
    ed.export_abort(at_pct=r.randint(90, 97))
    ed.settle()


@scenario('export', 'abort')
def export_abort_then_export(ed, r):
    """Abort mid-export, then immediately export again to completion."""
    ed.export_abort(at_pct=r.randint(15, 60))
    ed.export_full()


@scenario('export', 'abort')
def export_abort_storm(ed, r):
    """5 start/abort cycles at random moments."""
    for _ in range(5):
        if r.random() < 0.5:
            ed.export_abort(after_s=r.uniform(0.2, 4))
        else:
            ed.export_abort(at_pct=r.randint(5, 80))
    ed.settle()


@scenario('export', 'abort', 'split', 'seek')
def export_abort_then_edit_export(ed, r):
    """Abort, then scrub + split (looper busy with teardown), then export."""
    ed.export_abort(at_pct=r.randint(20, 60))
    ed.seek_storm(20, pause=(0, 0.1))
    ed.split()
    ed.export_full()


@scenario('export', 'abort')
def export_cancel_resume(ed, r):
    """Open the cancel warning, choose Resume, let it finish."""
    ed.export_abort(at_pct=r.randint(10, 60), resume=True)


@scenario('export')
def export_back_to_back(ed, r):
    """Export, come back, export again immediately."""
    ed.export_full()
    ed.export_full()


@scenario('export', 'lifecycle')
def export_background_return(ed, r):
    """Start export, go Home for 5–20 s, return, wait for it."""
    ed.export_start()
    ed.idle(r.uniform(1, 4))
    ed.step('home during export')
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(5, 20))
    ed.dev.launch()
    ed.idle(3)
    ed.export_wait_done()


@scenario('export', 'lifecycle')
def export_screen_off(ed, r):
    """Screen off during export."""
    ed.export_start()
    ed.idle(r.uniform(1, 4))
    ed.screen_off_on(r.uniform(3, 10))
    ed.export_wait_done()


@scenario('export', 'lifecycle')
def export_rotate(ed, r):
    """Rotate the device during export."""
    ed.export_start()
    ed.idle(r.uniform(1, 3))
    ed.rotate(2)
    ed.export_wait_done()


@scenario('export', 'lifecycle')
def export_trim_memory(ed, r):
    """Memory-pressure callbacks during export."""
    ed.export_start()
    for _ in range(3):
        ed.idle(r.uniform(1, 3))
        ed.trim_memory()
    ed.export_wait_done()


@scenario('export', 'abort', 'lifecycle')
def export_background_abort(ed, r):
    """Start export, Home, return, abort."""
    ed.export_start()
    ed.idle(2)
    ed.dev.key('KEYCODE_HOME')
    ed.idle(r.uniform(3, 8))
    ed.dev.launch()
    ed.idle(3)
    ed.cancel_export()
    ed.settle()


# ═══════════════════════════ EFFECTS / OVERLAYS ═══════════════════════════

@scenario('effects', 'export')
def effect_browse_storm_export(ed, r):
    """Tap 20–35 effects fast with playback on, apply, export (effect-browse / getMediaDuration wedge)."""
    ed.set_playing(True)
    ed.effects_browse(r.randint(20, 35), apply=True, gap=(0.05, 0.5))
    ed.set_playing(False)
    ed.export_full()


@scenario('effects', 'seek')
def effect_browse_seek_mix(ed, r):
    """Alternate effect browsing (cancelled) with scrub storms."""
    for _ in range(3):
        ed.effects_browse(r.randint(5, 12), apply=False)
        ed.seek_storm(15)


@scenario('effects', 'split', 'export')
def sticker_text_split_export(ed, r):
    """Add sticker + text, split under them, export."""
    ed.add_sticker()
    ed.add_text('zesty %d' % r.randint(0, 999))
    ed.split_at(r.uniform(0.2, 0.8))
    ed.export_full()


@scenario('effects', 'play', 'export')
def tune_while_playing_export(ed, r):
    """Drag tune sliders during playback, export."""
    ed.set_playing(True)
    ed.tune()
    ed.set_playing(False)
    ed.export_full()


@scenario('effects', 'split', 'export')
def freeze_split_export(ed, r):
    """Freeze frame, split next to it, scrub, export."""
    ed.seek_to(r.uniform(0.2, 0.7))
    ed.freeze()
    ed.split_at(r.uniform(0.2, 0.8))
    ed.seek_storm(20)
    ed.export_full()


# ═══════════════════════════ UNDO ═══════════════════════════

@scenario('undo', 'play')
def undo_redo_storm_playing(ed, r):
    """Make 3 edits, then 30 rapid undo/redo taps during playback."""
    ed.split_at(0.3)
    ed.split_at(0.6)
    ed.duplicate_clip()
    ed.set_playing(True)
    for _ in range(15):
        ed.undo(1, gap=(0.02, 0.2))
        ed.redo(1, gap=(0.02, 0.2))
    ed.set_playing(False)


# ═══════════════════════════ LIFECYCLE ═══════════════════════════

@scenario('lifecycle', 'split', 'export')
def background_return_split_export(ed, r):
    """Playing → Home 10 s → return → split → export."""
    ed.set_playing(True)
    ed.background(10)
    ed.split_at(0.5)
    ed.export_full()


@scenario('lifecycle', 'seek', 'slow')
def background_long_pressure(ed, r):
    """Playing → camera + trim-memory COMPLETE → 60 s away → return → sticker + scrub (vivo repro)."""
    ed.set_playing(True)
    ed.background(60, pressure=True)
    ed.add_sticker()
    ed.seek_storm(20)


@scenario('lifecycle', 'play')
def rotate_storm_playing(ed, r):
    """Rotation flips during playback (surface recreate under live renderer)."""
    ed.set_playing(True)
    ed.rotate(4)
    ed.seek_storm(10)


@scenario('lifecycle', 'play')
def screen_off_on_playing(ed, r):
    """Screen off/on 3x during playback."""
    ed.set_playing(True)
    for _ in range(3):
        ed.screen_off_on(r.uniform(2, 6))
    ed.seek_storm(10)


@scenario('lifecycle', 'seek')
def reopen_draft_cycle(ed, r):
    """Leave editor and reopen the draft 5x with scrubs/plays in between (engine teardown/setup)."""
    for _ in range(5):
        ed.seek_storm(r.randint(5, 15))
        if r.random() < 0.5:
            ed.set_playing(True)
            ed.idle(r.uniform(0.3, 2))
        ed.leave_editor()
        ed.idle(r.uniform(0.2, 1.5))
        ed.open_draft()


@scenario('lifecycle', 'export')
def force_stop_reopen_export(ed, r):
    """Force-stop mid-playback, cold-start into the draft, export."""
    ed.set_playing(True)
    ed.idle(2)
    ed.force_stop_reopen()
    ed.export_full()


@scenario('lifecycle', 'export', 'abort')
def leave_editor_after_abort(ed, r):
    """Abort export then immediately leave the editor and reopen."""
    ed.export_abort(at_pct=r.randint(20, 60))
    ed.leave_editor()
    ed.open_draft()
    ed.settle()


# ═══════════════════════════ CHAOS ═══════════════════════════

def chaos_actions(ed, r):
    """(weight, name, fn). Exports are rarer because they are slow."""
    return [
        (10, 'seek_storm',   lambda: ed.seek_storm(r.randint(5, 30))),
        (6,  'seek_to',      lambda: ed.seek_to(r.random())),
        (6,  'play_toggle',  lambda: ed.toggle_play()),
        (8,  'split',        lambda: ed.split()),
        (3,  'delete',       lambda: ed.delete_clip()),
        (3,  'duplicate',    lambda: ed.duplicate_clip()),
        (1,  'reverse',      lambda: ed.reverse_clip()),
        (3,  'speed',        lambda: ed.change_speed()),
        (2,  'volume',       lambda: ed.change_volume()),
        (2,  'flip_rotate',  lambda: ed.flip_or_rotate()),
        (5,  'undo',         lambda: ed.undo(r.randint(1, 5))),
        (4,  'redo',         lambda: ed.redo(r.randint(1, 5))),
        (4,  'effects',      lambda: ed.effects_browse(r.randint(3, 15), apply=r.random() < 0.5)),
        (2,  'sticker',      lambda: ed.add_sticker()),
        (1,  'text',         lambda: ed.add_text('chaos')),
        (2,  'tune',         lambda: ed.tune()),
        (1,  'freeze',       lambda: ed.freeze()),
        (3,  'export_abort', lambda: ed.export_abort(after_s=r.uniform(0.2, 6))),
        (1,  'export_full',  lambda: ed.export_full()),
        (2,  'trim_memory',  lambda: ed.trim_memory()),
        (1,  'background',   lambda: ed.background(r.randint(3, 15))),
        (1,  'rotate',       lambda: ed.rotate(1)),
        # no 'leave + reopen editor' here: it drops undo history, so the draft could not be reset
        # (reopen_draft_cycle covers that path)
    ]


def run_chaos(ed, r, steps, log):
    acts = chaos_actions(ed, r)
    weights = [a[0] for a in acts]
    ui_errors = 0
    for i in range(steps):
        _, name, fn = r.choices(acts, weights)[0]
        ed.step(f'chaos {i + 1}/{steps}: {name}')
        try:
            fn()
        except UIError as e:
            ui_errors += 1
            log(f'    (ui: {e}) — resyncing')
            try:
                ed.main_nav()
            except UIError:
                ed.recover()
        ed.check()
    log(f'  chaos done, {ui_errors} automation hiccups')


@scenario('chaos')
def chaos_short(ed, r):
    """60 random weighted actions (seeded, replayable)."""
    run_chaos(ed, r, 60, ed.log)


# ═══════════════════════════ runner ═══════════════════════════

# ═══════════════════ NIGHT SHIFT AUTO-WRITTEN REPROS (tools/stress/auto/*.py) ═══════════════════
# Night Shift's repro author writes one file per crash; each file is plain Python that uses the helpers above and
# registers its scenarios with @scenario('nightshift', 'auto'). A file that fails to load is skipped, never fatal.
import glob as _glob
for _f in sorted(_glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auto', '*.py'))):
    try:
        exec(compile(open(_f, encoding='utf-8').read(), _f, 'exec'), globals())
    except Exception as _e:
        print(f'[scenarios] skipped {os.path.basename(_f)}: {type(_e).__name__}: {_e}', file=sys.stderr)


def collect(dev, d, kind, line=''):
    dev.screenshot(os.path.join(d, 'fail.png'))
    if kind == 'ANR':
        # The ANR's own entry: match the PID from the am_anr line. Dropbox is written a few seconds after am_anr,
        # so wait for it; taking "the last entry" grabbed the previous run's ANR.
        m = re.search(r'am_anr\s*:\s*\[\d+,(\d+),', line or '')
        want = m.group(1) if m else None
        own = ''                                   # 2026-10-21: dropbox said "contents lost" and the run counted as a
        pid = want or dev.pid()                    # different ANR; the phone is not rooted (debuggerd: root is required).
        try:                                       # The lab build's main-thread watch logs the hung main stack itself.
            lc = dev.sh('logcat -d -v threadtime -s ZestyLab:W', timeout=60)
            blocks, cur = [], None
            for ln in lc.splitlines():
                f = ln.split()
                if pid and len(f) > 2 and f[2] != str(pid):
                    continue
                if 'LAB MAINSTACK begin' in ln:
                    cur = [ln.split('LAB MAINSTACK begin', 1)[1].strip()]
                elif 'LAB MAINSTACK end' in ln and cur is not None:
                    blocks.append(cur); cur = None
                elif 'LAB MAINSTACK   at ' in ln and cur is not None:
                    cur.append('  at ' + ln.split('LAB MAINSTACK   at ', 1)[1].strip())
            if blocks:
                b = blocks[-1]
                own = (f'"main" prio=5 tid=1 Native (lab main-thread watch, {b[0]}, pid {pid})\n' + '\n'.join(b[1:]) + '\n')
                open(os.path.join(d, 'main_stack_lab.txt'), 'w').write(own)
        except Exception as e:
            own = f'(lab main-thread watch read failed: {e})\n'
        mine, out = [], ''
        for _ in range(12):
            out = dev.sh('dumpsys dropbox --print data_app_anr', timeout=90)
            mine = [c for c in out.split('========================================')
                    if PKG in c and (not want or re.search(rf'^PID: {want}\b', c, re.M))]
            if mine or not want:
                break
            time.sleep(5)
        if not (mine and '"main"' in mine[-1]) and '"main"' not in own and pid:
            # No root, fast (Android 11+): the system keeps the trace file of the LAST ANR; shell has the DUMP permission.
            try:
                la = dev.sh('dumpsys activity lastanr-traces', timeout=60)
                if re.search(rf'----- pid {pid} at', la) and '"main"' in la:
                    own = '(ANR stack from dumpsys activity lastanr-traces)\n' + la
                    open(os.path.join(d, 'anr_lastanr_traces.txt'), 'w').write(la)
            except Exception as e:
                own += f'\n(lastanr-traces failed: {e})\n'
        if not (mine and '"main"' in mine[-1]) and '"main"' not in own and pid:
            # No root needed: a bugreport carries the full /data/anr/anr_* files (the dropbox copy is often
            # "contents lost"). Slow (1-3 min), so only when nothing else gave the main stack.
            try:
                import zipfile
                br = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_bugreport.zip')   # one file, overwritten
                dev.adb('bugreport', br, timeout=400)
                if os.path.exists(br):
                    with zipfile.ZipFile(br) as z:
                        for n in sorted((n for n in z.namelist() if '/anr/anr_' in n or '/anr/trace_' in n), reverse=True):
                            txt = z.read(n).decode('utf-8', 'replace')
                            if re.search(rf'----- pid {pid} at', txt) and '"main"' in txt:
                                own = f'(ANR stack from the bugreport: {n})\n' + txt
                                open(os.path.join(d, 'anr_from_bugreport.txt'), 'w').write(txt)
                                break
            except Exception as e:
                own += f'\n(bugreport fallback failed: {e})\n'
        has_own = '"main"' in own
        open(os.path.join(d, 'anr_trace.txt'), 'w').write(
            mine[-1] if mine and '"main"' in mine[-1] else
            (f'(dropbox entry for PID {want} missing or lost; stacks taken by the lab at the ANR)\n' + own) if has_own else
            (mine[-1] if mine else f'(no dropbox entry for PID {want} yet)\n' + own + out[-200000:]))
    elif kind == 'EXPORT_STUCK':
        pid = dev.pid()
        if pid:   # debuggable build: stacks of every thread, native and Java, while it is frozen
            for flag, name in (('-b', 'native_stacks.txt'), ('-j', 'java_stacks.txt')):
                out = dev.sh(f'run-as {PKG} debuggerd {flag} {pid} 2>&1 || debuggerd {flag} {pid} 2>&1', timeout=120)
                open(os.path.join(d, name), 'w').write(out)
    elif kind in ('CRASH', 'DIED'):
        # only THIS run's entry: match the PID from the crash/death line ("taking the last entry" picked up an
        # earlier run's crash when this process merely died, and a fix was failed on it)
        m = (re.search(r'\bpid (\d+) \(', line or '') or re.search(r'am_proc_died\s*:\s*\[\d+,(\d+),', line or '')
             or re.search(r'PID: (\d+)', line or '') or re.search(r'am_crash\s*:\s*\[\d+,(\d+),', line or ''))
        want = m.group(1) if m else None
        import datetime as _dt
        try:                                       # no PID in the line: accept only an entry from the last 2 minutes
            now = _dt.datetime.strptime(dev.sh('date "+%Y-%m-%d %H:%M:%S"', timeout=20).strip(), '%Y-%m-%d %H:%M:%S')
        except Exception:
            now = None

        def fresh(c):
            if want:
                return bool(re.search(rf'^PID: {want}\b', c, re.M))
            t = re.search(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) data_app_', c)
            try:
                return bool(now and t and (now - _dt.datetime.strptime(t.group(1), '%Y-%m-%d %H:%M:%S')).total_seconds() < 120)
            except ValueError:
                return False
        for tag in ('data_app_native_crash', 'data_app_crash'):
            mine = []
            for _ in range(3 if kind == 'CRASH' else 1):
                out = dev.sh(f'dumpsys dropbox --print {tag}', timeout=90)
                mine = [c for c in out.split('========================================')
                        if PKG in c and fresh(c)]
                if mine:
                    break
                time.sleep(3)
            if mine:
                open(os.path.join(d, f'{tag}.txt'), 'w').write(mine[-1])


@scenario('map', 'nodraft')
def check_actions(ed, r):
    """Prove the building blocks on this phone/build: open the slideshow, add a clip, play, dark mode, rotate."""
    ed.open_slideshow(n=2)
    c0 = ed.slideshow_media_count()
    ed.log(f'    strip shows {c0} clip(s)')
    if not ed.slideshow_add_media(1, wait=150):
        raise UIError(f'slideshow_add_media: the strip did not grow from {c0} within 150 s')
    ed.log(f'    OK slideshow_add_media: strip now {ed.slideshow_media_count()}')
    ed.slideshow_toggle_play(); ed.idle(2); ed.slideshow_toggle_play()
    ed.dev.dark_mode(True); ed.idle(4); ed.dev.dark_mode(False); ed.idle(4)
    s = ed.ui.wait(('id:rvMedias', 'id:add_video', 'id:btnSlideShow'), timeout=20)
    where = 'slideshow kept' if s is not None and s.has('id:rvMedias') else 'back on the start screen' if s is not None else 'unknown'
    ed.log(f'    OK dark_mode on/off: {where} ({ed.ui.activity})')
    ed.dev.rotate(True); ed.idle(4); ed.dev.rotate(False); ed.idle(4)
    ed.log('    OK rotate')
    ed.dev.restore_env()


@scenario('map')
def map_screens(ed, r):
    """Walk the main screens once (home, New Project picker, editor, slideshow, its add-media picker) so the screen
    map (tools/stress/screen_map.json) knows the real ids on this phone and build. Night Shift runs it once per build."""
    def tap(sel, timeout=6):
        try:
            return ed.ui.tap(sel, timeout=timeout)
        except UIError:
            return False

    def look(what):
        ed.idle(1.5)
        ed.ui.dump()
        ed.log(f'    mapped: {what} ({ed.ui.activity})')
    look('editor (draft opened by the runner)')
    for sel in (('id:menu', 'textc:edit'), ('textc:effects',), ('textc:text',), ('textc:audio', 'textc:music')):
        if tap(sel, 4):
            look(f'editor menu {sel[0]}')
            ed.dev.key('KEYCODE_BACK')
            ed.idle(1)
    try:
        ed.leave_editor()
    except UIError:
        ed.dev.key('KEYCODE_BACK'); ed.idle(2)
    look('home / My Projects')
    if tap(('textc:new project',), 8):
        look('New Project picker')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
    try:
        ed.open_slideshow(n=2)
        look('slideshow screen')
    except UIError as e:
        ed.log(f'    slideshow not mapped: {e}')
        return
    if tap('id:add_video', 8):
        look('slideshow add-media picker')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
    look('slideshow screen again')


_NAMES = {'next_button': 'Next clip', 'previous_button': 'Previous clip', 've_tab_edit': 'Edit', 've_tab_clip_speed': 'Speed',
          've_tab_effects': 'Effects', 've_btn_add_text_entry': 'Text', 've_btn_add_sticker_entry': 'Sticker', 've_tab_freeze': 'Freeze'}


def _plain_name(target):
    """'desc:ve_tab_edit' -> 'Edit', 'id:next_button' -> 'Next clip', 'text:Done' -> 'Done'."""
    k, _, v = str(target).partition(':')
    if k in ('text', 'textc'):
        return v
    if v in _NAMES:
        return _NAMES[v]
    w = re.sub(r'^(ve_)?(tab_|btn_)?', '', v)
    w = re.sub(r'_(button|btn|entry|view|icon)$', '', w).replace('_', ' ').strip()
    return w[:1].upper() + w[1:] if w else v


def human_step(txt):
    """A steps.log line -> a plain sentence for the video's captions and the board's step list (None = not shown)."""
    t = re.sub(r'^(replay|live \d+:)\s+', '', txt.strip(' ·'))
    t = re.sub(r'\s+\(.*\)$', '', t) if txt.lstrip(' ·').startswith('live ') else t
    if re.match(r'(screen recording|fresh timing|screen dumps|lab control|debug hooks|video kept|test draft|open_draft\b)', t) \
            or t[:1] in '✖■⚠▶':
        return None
    m = re.match(r'(\w+)\s*(\{.*)?$', t)            # the arguments may be cut short (captions keep 90 chars)
    act, args = (m.group(1), m.group(2)) if m else (None, None)
    try:
        a = json.loads(args) if args else {}
    except ValueError:
        a = dict(re.findall(r'"(\w+)":\s*"([^"]*)', args or ''))
    if t == 'fresh app process':
        return 'Start the app fresh'
    if t == 'open draft':
        return 'Open the test project'
    if t == 'leave editor':
        return 'Leave the editor'
    if act == 'tap' and a.get('target'):
        nm = _plain_name(a['target'])
        if re.search(r've_tab_|_tool|tab_clip_', a['target']):
            return f'Open {nm}'                      # a tool panel; human_steps() says if nothing was changed in it
        return f'Tap {nm}'
    if act == 'tap_xy':
        return 'Tap the screen'
    if act == 'arm':
        return 'Wait a few seconds (nothing tapped)'
    simple = {'back': "Press the phone's Back button (system Back, not the panel's ✓ or ✕)", 'home': 'Go to the home screen', 'resume': 'Return to the app', 'rotate': 'Rotate the phone',
              'open_draft': 'Open the test project', 'run_jobs': 'Let background jobs run'}
    if act in simple:
        return simple[act]
    if act == 'background':
        return f'Put the app in the background for {a.get("seconds", "a few")} s'
    if act == 'dark_mode':
        return f'Turn dark mode {a.get("on", "on")}'
    if act == 'reclaim_activities':
        return "Turn on Don't keep activities"
    if act == 'when_log':
        return f'When the app logs it, {a.get("then", "act")}'
    return re.sub(r'\s*\{.*\}\s*$', '', t)[:90] or None


def human_steps(rows):
    """[(t, plain step)] with context: a tool opened and left without any tap inside says so ("don't change anything")."""
    out = list(rows)
    for i, (t, x) in enumerate(out):
        if not x.startswith('Open ') or x == 'Open the test project':
            continue
        nxt = [y for _, y in out[i + 1:]]
        if nxt and nxt[0].startswith('Open '):
            continue                                 # a menu on the way to the tool, not the tool itself
        inside = []
        for y in nxt:
            if y.startswith(("Press the phone's Back", 'Open ', 'Tap Previous', 'Tap Next', 'Leave', 'Start ')):
                break
            inside.append(y)
        if not any(y.startswith('Tap ') for y in inside):
            out[i] = (t, f"{x} (don't change anything)")
    return out


def _video_subtitles(d, vids):
    """Each step of steps.log as a subtitle on the video (repro_video_N.srt next to it), so the video shows what the
    recipe was doing at each moment. One file 'repro_video.mp4' when ffmpeg can join the segments."""
    import shutil, subprocess
    steps = []
    day = time.strftime('%Y-%m-%d')
    for ln in open(os.path.join(d, 'steps.log'), errors='replace'):
        m = re.match(r'(\d\d:\d\d:\d\d)\s+(.*)', ln.rstrip())
        if m:
            t = time.mktime(time.strptime(f'{day} {m.group(1)}', '%Y-%m-%d %H:%M:%S'))
            h = human_step(m.group(2))
            if h:
                steps.append((t, h))
    steps = human_steps(steps)
    def ts(x):
        x = max(0.0, x)
        return f'{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(x * 1000 % 1000):03d}'
    for k, (path, t0) in enumerate(vids):
        t1 = vids[k + 1][1] if k + 1 < len(vids) else time.time()
        rows = [(t, txt) for t, txt in steps if t0 - 1 <= t <= t1]
        with open(path[:-4] + '.srt', 'w') as f:
            for j, (t, txt) in enumerate(rows):
                end = rows[j + 1][0] if j + 1 < len(rows) else t + 6
                f.write(f'{j + 1}\n{ts(t - t0)} --> {ts(end - t0)}\n{txt[:90]}\n\n')
    allrows = [(t, txt) for t, txt in steps if t >= vids[0][1] - 1]       # subtitles for the one joined file
    with open(os.path.join(d, 'repro_video.srt'), 'w') as f:
        for j, (t, txt) in enumerate(allrows):
            end = allrows[j + 1][0] if j + 1 < len(allrows) else t + 6
            f.write(f'{j + 1}\n{ts(t - vids[0][1])} --> {ts(end - vids[0][1])}\n{txt[:90]}\n\n')
    ff = shutil.which('ffmpeg') or next((c for c in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(c)), None)
    if ff and len(vids) > 1:
        lst = os.path.join(d, 'videos.txt')
        open(lst, 'w').write(''.join(f"file '{os.path.abspath(v)}'\n" for v, _ in vids))
        subprocess.run([ff, '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy',
                        os.path.join(d, 'repro_video.mp4')], timeout=120)
    elif vids:
        shutil.copyfile(vids[-1][0], os.path.join(d, 'repro_video.mp4'))


def _turbo_flag(k):
    try:
        import json as _j
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nightshift', 'out', 'experiment.json')
        return bool(((_j.load(open(p)) or {}).get('turbo') or {}).get(k))
    except Exception:
        return False


def _turbo_no_recover():
    """Night Shift turbo: with a fresh app process before every run, re-opening a draft after a failed run (up to 3 min)
    is wasted; the next run restarts the app anyway. Switch: out/experiment.json turbo.no_recover."""
    try:
        import json as _j
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nightshift', 'out', 'experiment.json')
        return bool(((_j.load(open(p)) or {}).get('turbo') or {}).get('no_recover'))
    except Exception:
        return False


def run_one(ed, name, fn, seed, d, args):
    os.makedirs(d, exist_ok=True)
    steps = open(os.path.join(d, 'steps.log'), 'w')
    t_start = time.time()

    def log(msg):
        line = f'{time.strftime("%H:%M:%S")} {msg}'
        print(line, flush=True)
        steps.write(line + '\n')
        steps.flush()

    ed.log = log
    ed.artifact_dir = d
    ed.mon.start(os.path.join(d, 'logcat.txt'))
    ed.rng = random.Random(seed)
    status, detail = 'PASS', ''
    try:
        ed.dev.restore_env()                        # a previous run may have left the network off, dark mode on, ...
    except Exception:
        pass
    log(f'▶ {name}  seed={seed}  (prep {time.time() - t_start:.1f} s)')
    ed.dev.marker(f'BEGIN {name} seed={seed}')
    rec = None
    if getattr(args, 'record', False):
        from zesty import Recorder
        rec = Recorder(ed.dev)
        rec.start()
        log('  · screen recording on (kept only if this run crashes)')
    drift = None
    ed.deadline = time.time() + args.scenario_timeout if args.scenario_timeout else None
    try:
        nodraft = 'nodraft' in SCENARIOS.get(name, (None, set()))[1]   # navigates itself (slideshow, home...)
        if args.fresh_on:
            ed.restart_fresh()
        if not nodraft:
            ed.open_draft()
            if ed.baseline_total is None:
                ed.set_playing(False)
                ed.check_drift()                       # records the baseline length
        fn(ed, random.Random(seed))
        ed.deadline = None                         # the scenario finished in time: the late-crash watch is not 'stuck'
        ed.settle(args.settle)
        if args.reset == 'undo' and not nodraft:
            try:
                undo_bug = ed.reset_edits()
                drift = ed.check_drift()
                if undo_bug:
                    drift = undo_bug + (f'; {drift}' if drift else '')
            except UIError as e:
                drift = f'reset failed: {e}'
            if drift:
                log(f'  ! {drift}')
            ed.mon.check()
    except AppFailure as e:
        status, detail = f'FAIL_{e.kind}', str(e)
        log(f'✖ {status}: {e}')
        time.sleep(2)                      # let traces land in dropbox
        collect(ed.dev, d, e.kind, getattr(e, 'line', '') or str(e))
    except UIError as e:
        status, detail = 'ERROR', str(e)
        log(f'⚠ automation: {e}')
        ed.dev.screenshot(os.path.join(d, 'ui_error.png'))
        open(os.path.join(d, 'screen.txt'), 'w').write(ed.ui.last.summary() if ed.ui.last else '(no dump)')
    except KeyboardInterrupt:
        ed.mon.stop()
        raise
    except Exception as e:
        status, detail = 'ERROR', f'{type(e).__name__}: {e}'
        log(traceback.format_exc())
    ed.deadline = None
    if rec is not None:
        try:
            vids = rec.stop(d if status.startswith('FAIL') else None)
            if vids:
                _video_subtitles(d, vids)
                log(f'  · video kept: {", ".join(os.path.basename(v) for v, _ in vids)} (+ steps as subtitles)')
        except Exception as e:
            log(f'  · video not saved: {e}')
    ed.dev.marker(f'END {name} {status}')
    time.sleep(0.5)
    ed.mon.stop()
    if status == 'PASS' or args.gzip_all:
        gzip_file(os.path.join(d, 'logcat.txt'))     # ~5 MB each; hundreds per night
    anrsan = list(ed.mon.anrsan)
    engine_aborts = ed.mon.abort_n
    serious = sorted({k for k in anrsan if k in ANRSAN_SERIOUS})
    notes = '; '.join(([drift] if drift else []) + ed.mon.notes[:3])
    from zesty import UI as _UI
    log(f'  · screen dumps: {_UI.STATS["n"]} taking {_UI.STATS["secs"]:.0f} s of this run'
        + (f' (fast in-app {_UI.FAST_STATS["fast"]}, uiautomator {_UI.FAST_STATS["fallback"]})' if _UI.FAST else ''))
    _UI.STATS.update(n=0, secs=0.0)
    _UI.FAST_STATS.update(fast=0, fallback=0)
    log(f'■ {status}  {time.time() - t_start:.0f}s  anrsan={len(anrsan)}{" SERIOUS=" + ",".join(serious) if serious else ""}'
        f'{"  notes: " + notes if notes else ""}')
    steps.close()
    ed.log = print
    if status != 'PASS':
        ed.mon.reset()                     # the failure is recorded; don't re-raise it during recovery
        if args.fresh_on and _turbo_no_recover():
            return dict(scenario=name, seed=seed, status=status, start=time.strftime('%H:%M:%S', time.localtime(t_start)),
                        secs=round(time.time() - t_start), anrsan=len(anrsan), anrsan_serious=','.join(serious),
                        engine_aborts=engine_aborts, detail=detail[:300], notes=notes[:300], dir=d)
        try:
            ed.recover()
        except Exception as e:
            print(f'   recovery failed: {e}', flush=True)
    return dict(scenario=name, seed=seed, status=status, start=time.strftime('%H:%M:%S', time.localtime(t_start)),
                secs=round(time.time() - t_start),
                anrsan=len(anrsan), anrsan_serious=','.join(serious), engine_aborts=engine_aborts,
                detail=detail[:300], notes=notes[:300],
                dir=d)


def gzip_file(path):
    import gzip, shutil
    if os.path.exists(path):
        with open(path, 'rb') as a, gzip.open(path + '.gz', 'wb', compresslevel=6) as b:
            shutil.copyfileobj(a, b)
        os.remove(path)


def wait_device(dev, max_wait=1800):
    """Phone unplugged / adb restarted: wait for it instead of failing every scenario."""
    t0 = time.time()
    warned = False
    while time.time() - t0 < max_wait:
        if dev.adb('get-state', timeout=15).strip() == 'device':
            if warned:
                print(f'   device back after {time.time() - t0:.0f}s', flush=True)
                time.sleep(5)
            return True
        if not warned:
            print('   ! device not connected — waiting (up to %d min)' % (max_wait // 60), flush=True)
            warned = True
        time.sleep(20)
    return False


def write_report(out_dir, rows, meta, findings):
    """REPORT.md: real ANRs/crashes + ANRSan findings + per-scenario table + automation errors."""
    import collections
    fails = [r for r in rows if r['status'].startswith('FAIL')]
    errs = [r for r in rows if r['status'] == 'ERROR']
    c = collections.Counter(r['status'] for r in rows)
    L = [f'# Stress run report', '',
         f'- Started **{meta["start"]}**, last update **{time.strftime("%Y-%m-%d %H:%M:%S")}** '
         f'({(time.time() - meta["t0"]) / 3600:.1f} h){"" if meta.get("done") else " — *still running*"}',
         f'- Device {meta["device"]} · ANRSan: **{meta["anrsan"]}** · fresh process per scenario: {meta["fresh"]}',
         f'- **{len(rows)} scenario runs** ({len({r["scenario"] for r in rows})} distinct): '
         + ', '.join(f'{k} {v}' for k, v in sorted(c.items())),
         f'- Draft length at start: {meta.get("baseline") or "?"} s',
         f'- Export aborts that really reached the engine: **{sum(r.get("engine_aborts", 0) for r in rows)}**', '']
    L += ['## Real ANRs / crashes', '']
    if not fails:
        L += ['None.', '']
    else:
        L += ['| time | status | scenario | seed | detail | folder | replay |', '|---|---|---|---|---|---|---|']
        for r in fails:
            L.append(f'| {r["start"]} | **{r["status"]}** | {r["scenario"]} | {r["seed"]} | '
                     f'{r["detail"][:140].replace("|", "/")} | `{os.path.relpath(r["dir"], out_dir)}` | '
                     f'`scenarios.py replay {r["scenario"]} --seed {r["seed"]}` |')
        L += ['', 'Each folder has `steps.log`, `logcat.txt`, `fail.png` and the trace '
              '(`anr_trace.txt` / `data_app_*crash.txt` / `*_stacks.txt`).', '']
    L += ['## ANRSan findings', '']
    if findings is None:
        L += ['ANRSan not active in this build — no findings.', '']
    else:
        sev = collections.Counter(f['severity'] for f in findings)
        L += [f'{len(findings)} unique findings: ' + ', '.join(f'{k} {sev[k]}' for k in
              ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO') if sev[k]) +
              ' — full stacks in [anrsan_findings.md](anrsan_findings.md).', '',
              '| id | sev | rule | seen | scenarios | first hit (scenario → step) | what |',
              '|---|---|---|---|---|---|---|']
        for f in findings:
            if f['severity'] in ('CRITICAL', 'HIGH', 'MEDIUM') and f['category'] in ('app', 'guessed-cycle'):
                r = f['first']
                L.append(f'| {f["id"]} | **{f["severity"]}** | {f["rule"]} | {f["count"]} | {len(f["scenarios"])} | '
                         f'{os.path.basename(r.source).split("__")[0]} → `{r.step}` | '
                         f'{f["headline"][:110].replace("|", "/")} |')
        low = sum(1 for f in findings if f['category'] in ('framework-sync', 'likely-idle'))
        L += ['', f'{low} more are framework-sync (waits inside MediaCodec/Muxer/AAudio/EGL) or likely-idle '
              '— listed in anrsan_findings.md.', '']
    L += ['## Per scenario', '', '| scenario | runs | pass | ANR | crash | stuck | error | engine aborts | anrsan reports |',
          '|---|---|---|---|---|---|---|---|---|']
    by = collections.OrderedDict()
    for r in rows:
        by.setdefault(r['scenario'], []).append(r)
    for n, rs in sorted(by.items()):
        k = lambda p: sum(1 for x in rs if x['status'].startswith(p))
        L.append(f'| {n} | {len(rs)} | {k("PASS")} | {k("FAIL_ANR")} | {k("FAIL_CRASH") + k("FAIL_DIED")} | '
                 f'{k("FAIL_EXPORT_STUCK")} | {k("ERROR")} | {sum(x.get("engine_aborts", 0) for x in rs)} | '
                 f'{sum(x["anrsan"] for x in rs)} |')
    L += ['', '## Automation errors (not app bugs — send these if a scenario keeps failing)', '']
    if not errs:
        L += ['None.', '']
    else:
        grp = collections.Counter((r['scenario'], re.sub(r'\d+', '#', r['detail'][:120])) for r in errs)
        L += ['| scenario | error | times |', '|---|---|---|']
        L += [f'| {sc} | {msg.replace("|", "/")} | {n} |' for (sc, msg), n in grp.most_common(40)]
        L.append('')
    ub = [r for r in rows if 'UNDO_WITHOUT_EDITS' in r.get('notes', '')]
    if ub:
        L += ['## App state bug: Undo enabled without any edit', '',
              f'{len(ub)} run(s) ended with Undo enabled although the scenario made no edits. On the '
              'test phone, pressing that Undo after an export abort trimmed clip 0 to clip 1\'s length and '
              'deleted clip 1 (MsgTrimVideo + MsgDeleteMedia in logcat). The runner no longer presses it; '
              'see `undo_without_edits.png` in each folder.', '',
              '| scenario | seed | start | engine aborts |', '|---|---|---|---|']
        L += [f'| {r["scenario"]} | {r["seed"]} | {r["start"]} | {r.get("engine_aborts", 0)} |' for r in ub[:30]]
        L.append('')
    drift = [r for r in rows if 'drifted' in r.get('notes', '')]
    if drift:
        L += [f'⚠ The draft length drifted in {len(drift)} run(s) (first: {drift[0]["start"]}) — restore the test '
              'draft from your copy before the next run.', '']
    open(os.path.join(out_dir, 'REPORT.md'), 'w').write('\n'.join(L))


def refresh_reports(out_dir, rows, meta, anrsan_on, quiet=True):
    summarize(rows, out_dir, quiet=quiet)
    findings = None
    if anrsan_on:
        try:
            import anrsan_findings
            findings = anrsan_findings.build([out_dir], quiet=quiet) or []
        except Exception as e:
            print(f'   (anrsan_findings failed: {e})', flush=True)
            findings = []
    write_report(out_dir, rows, meta, findings)
    return findings


def run_overnight(ed, args, out_dir, rows, meta, base_seed, anrsan_on):
    """Every scenario (shuffled) + one chaos run per cycle, until --hours is up. REPORT.md is
    rewritten every --report-every scenarios, so there is always a current report."""
    names = select(args)
    if not names:
        sys.exit('no scenarios match')
    rnd = random.Random(base_seed)
    stop_at = time.time() + args.hours * 3600
    cycle, streak = 0, 0
    print(f'overnight: {len(names)} scenarios + chaos({args.chaos_steps}) per cycle, '
          f'until {time.strftime("%H:%M", time.localtime(stop_at))}', flush=True)
    while time.time() < stop_at:
        cycle += 1
        batch = list(names)
        rnd.shuffle(batch)
        batch.insert(rnd.randrange(len(batch) + 1), '__chaos__')
        for k, n in enumerate(batch):
            if time.time() >= stop_at:
                break
            if not wait_device(ed.dev):
                print('device gone for 30 min — stopping', flush=True)
                return
            seed = rnd.randrange(10 ** 6)
            left = (stop_at - time.time()) / 3600
            print(f'\n[cycle {cycle} · {k + 1}/{len(batch)} · {len(rows)} done · {left:.1f} h left]', end=' ')
            if n == '__chaos__':
                def chaos(ed_, r):
                    run_chaos(ed_, r, args.chaos_steps, ed_.log)
                saved, args.scenario_timeout = args.scenario_timeout, max(args.scenario_timeout, 3 * 3600)
                row = run_one(ed, 'chaos', chaos, seed, os.path.join(out_dir, f'chaos__{cycle}'), args)
                args.scenario_timeout = saved
            else:
                row = run_one(ed, n, SCENARIOS[n][0], seed, os.path.join(out_dir, f'{n}__{cycle}_{k + 1}'), args)
            rows.append(row)
            meta['baseline'] = ed.baseline_total
            # automation keeps failing (app in a weird state / dialog on top): full reset of the app
            streak = streak + 1 if row['status'] == 'ERROR' else 0
            if streak and streak % 4 == 0:
                print(f'   {streak} automation errors in a row — full app reset', flush=True)
                try:
                    setup_anrsan(ed.dev, args) if anrsan_on else None
                    ed.mon.reset()
                    ed.recover()
                except Exception as e:
                    print(f'   reset failed: {e}', flush=True)
                if streak >= 12:
                    print('   still failing — pausing 5 min', flush=True)
                    time.sleep(300)
            if len(rows) % args.report_every == 0:
                refresh_reports(out_dir, rows, meta, anrsan_on and not args.no_findings)
                print(f'   (REPORT.md updated: {len(rows)} runs)', flush=True)


def merge_opts(old, new):
    kv = OrderedDict()
    for part in (old or '').split(':') + (new or '').split(':'):
        if '=' in part:
            k, v = part.split('=', 1)
            kv[k.strip()] = v.strip()
    return ':'.join(f'{k}={v}' for k, v in kv.items())


def setup_anrsan(dev, args):
    """Raise ANRSan's per-process report cap (default 300 would silence it after a few scenarios),
    restart the app so wrap.sh picks it up, and confirm libanrsan.so is loaded."""
    if args.anrsan == 'off':
        return False, None
    old = dev.getprop('debug.anrsan.options')
    opts = merge_opts(old, args.anrsan_options)
    dev.setprop('debug.anrsan.options', opts)
    dev.force_stop()
    time.sleep(1)
    dev.launch()
    time.sleep(5)
    state = dev.anrsan_loaded()
    label = {True: 'ACTIVE', False: 'NOT in this build', None: 'unknown (build not debuggable?)'}[state]
    print(f'ANRSan: {label}   debug.anrsan.options="{opts}"')
    if state is False:
        dev.setprop('debug.anrsan.options', old)
        if args.anrsan == 'on':
            sys.exit('ANRSan required: ./gradlew installProductionInternalDebug -PenableAnrsan=true')
        print('  → running without ANRSan: only ANRs/crashes will be found')
        return False, None
    return state, old


def select(args):
    names = list(SCENARIOS)
    if args.names:
        names = [n for n in names if any(fnmatch.fnmatch(n, p) for p in args.names)]
    if args.tag:
        names = [n for n in names if SCENARIOS[n][1] & set(args.tag)]
    if args.skip_tag:
        names = [n for n in names if not SCENARIOS[n][1] & set(args.skip_tag)]
    return names


def summarize(rows, out_dir, quiet=False):
    if not rows:
        return
    path = os.path.join(out_dir, 'summary.csv')
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if quiet:
        return
    by = {}
    for r in rows:
        by.setdefault(r['scenario'], []).append(r)
    print('\n' + '═' * 92)
    print(f'{"scenario":38} {"runs":>4} {"pass":>4} {"ANR":>4} {"crash":>5} {"err":>4} {"anrsan":>6}  failing seeds')
    for n, rs in by.items():
        c = lambda s: sum(1 for x in rs if x['status'].startswith(s))
        seeds = ' '.join(str(x['seed']) for x in rs if x['status'].startswith('FAIL'))
        print(f'{n:38} {len(rs):4} {c("PASS"):4} {c("FAIL_ANR"):4} {c("FAIL_CRASH") + c("FAIL_DIED"):5} '
              f'{c("ERROR"):4} {sum(x["anrsan"] for x in rs):6}  {seeds}')
    fails = [r for r in rows if r['status'].startswith('FAIL')]
    print('═' * 92)
    print(f'{len(rows)} runs, {len(fails)} app failures, {sum(r["status"] == "ERROR" for r in rows)} automation errors')
    for r in fails:
        print(f'  {r["status"]:11} {r["scenario"]}  seed={r["seed"]}\n      {r["detail"][:160]}\n      {r["dir"]}')
    print(f'\nsummary: {path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    sub.add_parser('probe')
    for c in ('run', 'chaos', 'replay', 'overnight'):
        p = sub.add_parser(c)
        if c == 'overnight':
            p.add_argument('--hours', type=float, default=12, help='stop starting new scenarios after this')
            p.add_argument('--chaos-steps', type=int, default=150, help='one chaos run of this length per cycle')
            p.add_argument('--report-every', type=int, default=5, help='rewrite REPORT.md every N scenarios')
        p.add_argument('--scenario-timeout', type=float, default=1800 if c != 'chaos' else 0,
                       help='seconds before a scenario is abandoned as ERROR (0 = none)')
        p.add_argument('--gzip-all', action='store_true', help='also gzip logcats of failed scenarios')
        p.add_argument('names', nargs='*', help='scenario names or globs (run/replay)')
        p.add_argument('--tag', action='append', help='only scenarios with this tag (repeatable)')
        p.add_argument('--skip-tag', action='append', default=None, help='e.g. --skip-tag slow --skip-tag lifecycle')
        p.add_argument('--repeat', type=int, default=1)
        p.add_argument('--loop', action='store_true', help='repeat the selection until Ctrl-C')
        p.add_argument('--shuffle', action='store_true')
        p.add_argument('--seed', type=int, default=None)
        p.add_argument('--steps', type=int, default=200, help='chaos only')
        p.add_argument('--settle', type=float, default=6, help='late-ANR watch after each scenario (s)')
        p.add_argument('--stop-on-fail', action='store_true')
        p.add_argument('--record', action='store_true',
                       help='screen-record each run; the video is kept only when the run fails (crash/ANR)')
        p.add_argument('--stop-on-error', action='store_true',
                       help='stop the repeats after an automation ERROR (the next repeat would fail the same way)')
        p.add_argument('--ui-stall', type=float, default=0,
                       help='a UI wait gives up after this many seconds of an unchanged screen with no loader (0 = off)')
        p.add_argument('--anrsan', choices=['auto', 'on', 'off'], default='auto',
                       help='auto: use ANRSan if the build has it; on: refuse to run without it')
        p.add_argument('--anrsan-options', default='max_reports=1000000',
                       help='merged into debug.anrsan.options for the run (restored afterwards)')
        p.add_argument('--fresh', choices=['auto', 'on', 'off'], default='auto',
                       help='new app process before each scenario (auto = on when ANRSan is active)')
        p.add_argument('--no-findings', action='store_true', help='skip anrsan_findings report at the end')
        p.add_argument('--reset', choices=['undo', 'none'], default='undo',
                       help='after a passing scenario, undo back to the original draft (default)')
        p.add_argument('--out', default='stress_results')
        p.add_argument('--serial', default=None)
    args = ap.parse_args()

    if args.cmd == 'list':
        tags = {}
        for n, (_, t, doc) in SCENARIOS.items():
            print(f'{n:36} [{",".join(sorted(t))}]\n{"":36} {doc}')
            for x in t:
                tags[x] = tags.get(x, 0) + 1
        print(f'\n{len(SCENARIOS)} scenarios. tags: ' + ', '.join(f'{k}({v})' for k, v in sorted(tags.items())))
        return

    _t0 = time.time()
    if getattr(args, 'anrsan', None) == 'auto' and _turbo_flag('skip_anrsan_probe'):
        args.anrsan = 'off'                      # turbo: ANRSan is not in the lab builds; its probe restarts the app (~10 s)
    dev = Device(getattr(args, 'serial', None))
    ui = UI(dev)
    if args.cmd == 'probe':
        s = ui.dump()
        print(s.summary() if s else 'uiautomator dump failed (UI never idle? pause playback and retry)')
        from zesty import BottomBar, MAIN_MENU, CLIP_MENU
        bar, items, back = BottomBar(dev).read()
        if bar is None:
            print('\nbottom bar: not in view tree')
        else:
            names = CLIP_MENU if back else MAIN_MENU
            first = 0 if abs(items[0].b[0] - bar.b[0]) <= 2 else (
                len(names) - len(items) if abs(items[-1].b[2] - bar.b[2]) <= 2 else None)
            print(f'\nbottom bar ({"clip/sub menu" if back else "main menu"}) {bar.b}, {len(items)} items laid out:')
            for k, it in enumerate(items):
                label = names[first + k] if first is not None and first + k < len(names) else '?'
                crown = '  [crown]' if it.has_visible('crownIcon') else ''
                print(f'   {label:10} tap at {it.center}{crown}')
        return

    mon = Monitor(dev)
    ed = Editor(dev, ui, mon, print)
    out_dir = os.path.join(args.out, datetime.now().strftime('%Y%m%d-%H%M%S'))
    os.makedirs(out_dir, exist_ok=True)
    base_seed = args.seed if args.seed is not None else random.randrange(10 ** 6)
    print(f'device {dev.w}x{dev.h}  results → {out_dir}  base seed {base_seed}')
    _t1 = time.time()
    anrsan, old_opts = setup_anrsan(dev, args)
    print(f'startup: device {_t1 - _t0:.1f} s, anrsan probe {time.time() - _t1:.1f} s', flush=True)
    args.fresh_on = args.fresh == 'on' or (args.fresh == 'auto' and anrsan is not False and args.cmd != 'chaos')
    print(f'fresh app process per scenario: {"yes" if args.fresh_on else "no"}  (startup {time.time() - _t0:.1f} s)', flush=True)
    rows = []
    meta = dict(start=time.strftime('%Y-%m-%d %H:%M:%S'), t0=time.time(), device=f'{dev.w}x{dev.h}',
                anrsan={True: 'active', False: 'not in build', None: 'unknown'}[anrsan],
                fresh='yes' if args.fresh_on else 'no')
    try:
        if args.cmd == 'overnight':
            run_overnight(ed, args, out_dir, rows, meta, base_seed, anrsan is not False)
            return
        if args.cmd == 'chaos':
            def chaos(ed_, r):
                run_chaos(ed_, r, args.steps, ed_.log)
            rows.append(run_one(ed, 'chaos', chaos, base_seed, os.path.join(out_dir, 'chaos'), args))
            return
        names = select(args)
        if not names:
            sys.exit('no scenarios match')
        if args.cmd == 'replay':
            if args.seed is None:
                sys.exit('replay needs --seed (from summary.csv)')
            for n in names:
                rows.append(run_one(ed, n, SCENARIOS[n][0], args.seed, os.path.join(out_dir, f'{n}__replay'), args))
            return
        UI.stall = getattr(args, 'ui_stall', 0) or None
        rnd = random.Random(base_seed)
        it = 0
        while True:
            it += 1
            batch = [n for n in names for _ in range(args.repeat)]
            if args.shuffle:
                rnd.shuffle(batch)
            for k, n in enumerate(batch):
                seed = rnd.randrange(10 ** 6)
                print(f'\n[{it}:{k + 1}/{len(batch)}]', end=' ')
                row = run_one(ed, n, SCENARIOS[n][0], seed, os.path.join(out_dir, f'{n}__{it}_{k + 1}'), args)
                rows.append(row)
                summarize(rows, out_dir) if k % 10 == 9 else None
                if args.stop_on_fail and row['status'].startswith('FAIL'):
                    return
                if getattr(args, 'stop_on_error', False) and row['status'] == 'ERROR':
                    print('\nstopping: automation error; the remaining repeats would fail the same way')
                    return
            if not args.loop:
                return
    except KeyboardInterrupt:
        print('\ninterrupted')
    finally:
        mon.stop()
        try:
            import zesty
            zesty.save_screen_map()
        except Exception as e:
            print(f'screen map not saved: {e}')
        if old_opts is not None:
            dev.setprop('debug.anrsan.options', old_opts)
        meta['done'] = True
        meta['baseline'] = ed.baseline_total
        if rows:
            refresh_reports(out_dir, rows, meta, anrsan is not False and not args.no_findings, quiet=False)
            print(f'\nREPORT: {os.path.join(out_dir, "REPORT.md")}')


if __name__ == '__main__':
    main()
