# Night Shift auto repros for 501bb52658b63a6c0a32a5b8bbd06b8b


# 2026-10-21 20:10 level 3 attempt 1
def _501bb526_open(ed):
    mark = ed.log_mark()
    ed.open_fixture('501bb526')
    ed.require_log(r'MsgFreezeLoader layer_id 0|MsgAddVideoFreezeDuration', 30, since=mark,
                   why='fixture must load freeze items on layer 0 (field: MsgFreezeLoader layer_id 0 at -10.2 s)')
    ed.idle(2)


def _501bb526_speed_apply(ed, frac):
    """Speed tool -> drag the bar to frac (None = leave it, speed 1.0 like the field) -> Done (ve_speed_complete path:
    setMediaCurveSpeed + setVideoSpeed, then freezeLoader() 50 ms later). Back would skip freezeLoader, so Done is required."""
    ed.clip_tool('speed')
    s = ed.ui.wait(T.SPEED_BAR, timeout=8)
    if frac is not None and s is not None:
        l, t, rr, b = s.find(T.SPEED_BAR).b
        y = (t + b) // 2
        ed.dev.swipe((l + rr) // 2, y, int(l + 10 + frac * (rr - l - 20)), y, 400)
        ed.idle(0.5)
    s = ed.screen()
    if s is None or not s.has(T.DONE):
        raise UIError('speed tool Done button not found: no apply, no MsgSetVideoSpeed')
    mark = ed.log_mark()
    ed.step('speed apply (Done)')
    ed.dev.tap(*s.find(T.DONE).center)
    return mark


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l3_1_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI: high-speed apply on the freeze fixture on a slow phone -> layer loses its freezes, freezeLoader spins."""
    _501bb526_open(ed)
    ed.set_playing(False)
    ed.dev.slow_phone(r.randint(30, 40))            # low-end Xiaomi: main + engine both slow
    try:
        mark = _501bb526_speed_apply(ed, 1.0)       # bar to the far right: max speed (lab saw 7.6 -> 0 freeze intervals)
        ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark,
                       why='speed apply must reach the engine (field: MsgSetVideoSpeed layer 0 id 4)')
        ed.settle(20)                               # ANR came ~7-8 s after the apply in the field and the lab
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l3_1_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI: speed apply while playing + a second apply ~1.4 s later under CPU + memory pressure (slow re-extraction form)."""
    _501bb526_open(ed)
    ed.set_playing(True)                            # GL lease contended: each per-freeze lockContextForEdit really waits
    ed.idle(r.uniform(1.0, 2.0))
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
    ed.dev.slow_phone(r.randint(25, 35))
    try:
        mark = _501bb526_speed_apply(ed, r.uniform(0.55, 0.75))
        ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark, why='first speed apply')
        ed.idle(0.6)
        mark2 = _501bb526_speed_apply(ed, r.uniform(0.3, 0.5))   # field: second apply 1.4 s after the first
        ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark2,
                       why='second speed apply (field: MsgSetMediaCurveSpeed + MsgSetVideoSpeed at -1.23 s)')
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l3_1_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI: speed 1.0 applied twice (as in the field) with slow storage + critical memory pressure."""
    _501bb526_open(ed)
    ed.dev.busy_storage(True)                       # slow decoder reads for every per-freeze reach_frame/refreshPlayer
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_CRITICAL')
    ed.dev.slow_phone(r.randint(35, 45))
    try:
        mark = _501bb526_speed_apply(ed, None)      # field: 'MsgSetVideoSpeed: speed 1.000000, layer 0, id 4'
        ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark, why='first speed 1.0 apply')
        ed.idle(1.0)
        mark2 = _501bb526_speed_apply(ed, None)
        ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark2, why='second speed 1.0 apply')
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


# 2026-10-21 20:29 level 3 attempt 2
def _501bb526_fixture(ed):
    mark = ed.log_mark()
    ed.open_fixture('501bb526')
    ed.require_log(r'MsgAddVideoFreezeDuration', 30, since=mark,
                   why='fixture must load freeze items on layer 0 (field: MsgFreezeLoader layer_id 0, 255 s timeline)')
    ed.require_log(r'updateSlidersMaxValue-durationInMill:\d{5,}', 20, since=mark,
                   why='long timeline (>=10 s; hit fixture was 93 s + 20 s) so freezes sit deep in a clip')
    ed.idle(6)                                       # 862fefa4 died ~1 s into load: prove the editor survives
    ed.check()


def _501bb526_speed(ed, frac):
    """Speed tool -> bar to frac (None = untouched, speed 1.0 like the field) -> Done (POP_SPEED: setMediaCurveSpeed,
    setVideoSpeed, getCurrentTime, then freezeLoader() 50 ms later, PlayerActivity.kt:6716-6755)."""
    ed.clip_tool('speed')
    s = ed.ui.wait('id:speed_bar', timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    if frac is not None:
        l, t, rr, b = s.find('id:speed_bar').b
        y = (t + b) // 2
        ed.dev.swipe(l + (rr - l) // 2, y, int(l + 10 + frac * (rr - l - 20)), y, 400)
        ed.idle(0.5)
    s = ed.screen()
    if s is None or not s.has('id:done'):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no apply, no freezeLoader')
    mark = ed.log_mark()
    ed.step('speed apply (Done)')
    ed.dev.tap(*s.find('id:done').center)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark,
                   why='speed apply must reach the engine (field: MsgSetVideoSpeed layer 0 id 4)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l3_2_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (endless form): max-speed apply on the freeze fixture, slow phone."""
    _501bb526_fixture(ed)
    ed.set_playing(False)
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_speed(ed, 0.98)                   # lab: speed 7.6 -> layer reports 0 freeze intervals, progress 0.0
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l3_2_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form): speed 1.0 applied twice ~1.4 s apart while playing, CPU + memory pressure."""
    _501bb526_fixture(ed)
    ed.set_playing(True)                            # GL lease contended: per-freeze lockContextForEdit really waits
    ed.idle(r.uniform(1.0, 2.0))
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
    ed.dev.slow_phone(r.randint(25, 35))
    try:
        _501bb526_speed(ed, None)
        ed.idle(0.4)
        _501bb526_speed(ed, None)                   # field: MsgSetMediaCurveSpeed + MsgSetVideoSpeed at -1.23 s
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_501bb526_l3_2_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form, self-built): long fresh clip + 3 deep UI freezes, then two speed applies on it."""
    ed.set_playing(False)
    ed.dev.fresh_video('ns501', duration_s=93)      # new path -> real transcode (field: 41 s gemini clip)
    mark = ed.log_mark()
    ed.add_media(pick=0)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: .*transcoding', 150, since=mark,
                   why='long second clip on layer 0 (field: two clips, 255 s timeline)')
    ed.idle(2)
    for f in (0.45, 0.7, 0.88):                     # deep in the long clip: each re-extraction decodes far in
        ed.seek_to(f, tol=0.06)
        mark = ed.log_mark()
        ed.freeze()
        ed.require_log(r'MsgAddVideoFreezeDuration', 15, since=mark,
                       why='freeze item on layer 0 in both engine and Kotlin itemList (UI freeze tool)')
        ed.main_nav()
        ed.idle(1)
    ed.seek_to(0.6, tol=0.08)                       # playhead on the long clip: speed applies to it
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_speed(ed, r.uniform(0.35, 0.45))  # moderate speed: freezes stay inside the clip (slow form)
        ed.idle(0.4)
        _501bb526_speed(ed, r.uniform(0.35, 0.45))
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-21 20:53 level 4 attempt 1
def _501bb526_open(ed):
    mark = ed.log_mark()
    ed.open_fixture('501bb526')
    ed.require_log(r'MsgAddVideoFreezeDuration|MsgFreezeLoader layer_id 0', 40, since=mark,
                   why='checkpoint 1: fixture must load freeze items on layer 0 (field: MsgFreezeLoader layer_id 0)')
    ed.idle(4)                                       # load must survive (an earlier fixture died ~1 s into load)
    ed.check()


def _501bb526_apply(ed, frac, why):
    """Speed tool -> bar to frac (None = untouched, speed 1.0 like the field) -> Done (POP_SPEED, PlayerActivity.kt:6696:
    setMediaCurveSpeed + setVideoSpeed, sync getCurrentTime, freezeLoader() 50 ms later). Back would skip freezeLoader."""
    ed.clip_tool('speed')
    s = ed.ui.wait(T.SPEED_BAR, timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    if frac is not None:
        l, t, rr, b = s.find(T.SPEED_BAR).b
        y = (t + b) // 2
        ed.dev.swipe((l + rr) // 2, y, int(l + 10 + frac * (rr - l - 20)), y, 300)
        ed.idle(0.4)
    s = ed.screen()
    if s is None or not s.has(T.DONE):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no MsgSetVideoSpeed, no freezeLoader')
    mark = ed.log_mark()
    ed.step('speed apply (Done)')
    ed.dev.tap(*s.find(T.DONE).center)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark, why=why)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_1_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (endless form, as lab hit l5_2_b): max-speed apply drops the layer's freezes, freezeLoader spins at 0.0."""
    _501bb526_open(ed)
    ed.set_playing(False)
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_apply(ed, 0.99, 'checkpoint 2: max-speed apply reaches the engine on layer 0')
        ed.settle(20)                                # field/lab ANR ~7-8 s after the apply
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_1_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form, field order): speed 1.0 applied twice ~1.4 s apart while playing."""
    _501bb526_open(ed)
    ed.set_playing(True)                             # lease contended: per-freeze lockContextForEdit really waits
    ed.idle(r.uniform(1.0, 2.0))
    ed.dev.slow_phone(r.randint(30, 42))
    try:
        _501bb526_apply(ed, None, 'checkpoint 2: first speed 1.0 apply (field -2.67 s)')
        # field: second apply (MsgSetMediaCurveSpeed + MsgSetVideoSpeed) 1.4 s later, queued behind the re-extraction
        _501bb526_apply(ed, None, 'checkpoint 5: second speed apply (field -1.23 s)')
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_1_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form, storm): 3 moderate-speed applies back to back stack freeze re-extractions on the queue."""
    _501bb526_open(ed)
    ed.set_playing(True)
    ed.idle(1.0)
    ed.dev.slow_phone(r.randint(38, 48))
    try:
        for k in range(3):                           # freezes stay inside the clip at ~1-2x: every apply re-extracts all
            _501bb526_apply(ed, r.uniform(0.3, 0.45), f'checkpoint 2/5: speed apply {k + 1}/3 on layer 0')
            ed.idle(r.uniform(0.3, 0.7))
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-21 20:57 level 4 attempt 2
def _501bb526_state(ed):
    """Checkpoint 1: layer 0 holds deep freezes in the engine AND in Kotlin itemList (real UI hold on the Freeze tile)."""
    mark = ed.log_mark()
    try:
        ed.open_fixture('501bb526')
        ed.require_log(r'MsgAddVideoFreezeDuration|MsgFreezeLoader layer_id 0', 40, since=mark,
                       why='checkpoint 1: fixture loads freeze items on layer 0')
        ed.idle(4)
        return
    except UIError as e:                             # fixture not on this phone yet (last 3 attempts): build it
        ed.log(f'    fixture 501bb526 missing ({e}); building the freeze state with real taps')
    ed.open_draft()
    ed.set_playing(False)
    ed.dev.fresh_video('ns501', duration_s=93)       # field: long gemini clips, 255 s timeline
    mark = ed.log_mark()
    ed.add_media(pick=0)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: .*transcoding', 180, since=mark,
                   why='checkpoint 1: long second clip on layer 0')
    ed.idle(3)
    ed.tap_tool('freeze')
    s = ed.ui.wait(T.FREEZE_APPLY, timeout=10)
    if s is None:
        raise UIError('freeze panel has no Add tile (ve_btn_freeze_apply)')
    x, y = s.find(T.FREEZE_APPLY).center
    for t in (25, 40, 55, 70, 85):                   # deep in the 93 s clip: each re-extraction decodes far in
        ed.jni(f'seekTo({t}.0)')                     # START_FREEZE anchors at the ENGINE clock (Player.getCurrentTime)
        ed.idle(1.0)
        mark = ed.log_mark()
        ed.step(f'freeze hold at {t} s')
        ed.dev.swipe(x, y, x, y, 1800)               # hold >0.5 s starts the freeze, release at >0.4 s commits it
        ed.require_log(r'MsgAddVideoFreezeDuration', 10, since=mark,
                       why='checkpoint 1: UI freeze item on layer 0 (engine + itemList)')
        ed.idle(1.2)
    ed.main_nav()                                    # playhead parked on the last freeze end = inside the long clip
    ed.idle(2)
    ed.check()


def _501bb526_speed(ed, frac, why):
    """Speed tool -> slider (sends MsgSetVideoSpeed) -> Done (POP_SPEED: sync getCurrentTime, freezeLoader() +50 ms)."""
    mark = ed.log_mark()
    ed.clip_tool('speed')
    s = ed.ui.wait('id:speed_bar', timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    if frac is not None:
        l, t, rr, b = s.find('id:speed_bar').b
        yy = (t + b) // 2
        ed.dev.swipe((l + rr) // 2, yy, int(l + 10 + frac * (rr - l - 20)), yy, 300)
        ed.idle(0.4)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 10, since=mark, why=why)
    s = ed.screen()
    if s is None or not s.has('id:done'):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no freezeLoader')
    ed.step('speed apply (Done)')
    ed.dev.tap(*s.find('id:done').center)


def _501bb526_undo_xy(ed):
    s = ed.screen()
    if s is None or not s.has('id:undo'):
        raise UIError('undo button (ve_btn_undo) not found')
    return s.find('id:undo').center, (s.find('id:redo').center if s.has('id:redo') else None)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_2_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (endless form, lab hit l5_2_b path): max speed pushes the deep freezes out of the clip, freezeLoader spins at 0.0."""
    _501bb526_state(ed)
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_speed(ed, 0.99, 'checkpoint 2: max-speed apply on the long layer-0 clip')
        ed.settle(20)                                # field/lab ANR ~7-8 s after the apply
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_2_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form, field order): speed apply while playing, then Undo ~1.4 s later = MsgSetMediaCurveSpeed + MsgSetVideoSpeed + freezeLoader again."""
    _501bb526_state(ed)
    ed.set_playing(True)                             # lease contended: per-freeze lockContextForEdit really waits
    ed.idle(r.uniform(1.0, 2.0))
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_speed(ed, r.uniform(0.35, 0.45), 'checkpoint 2: first speed apply on layer 0 (field -2.67 s)')
        (ux, uy), _ = _501bb526_undo_xy(ed)
        ed.idle(max(0.0, 1.4 - 0.5))
        mark = ed.log_mark()
        ed.step('undo speed (stack applySpeed -> POP_SPEED)')
        ed.dev.tap(ux, uy)
        ed.require_log(r'MsgSetMediaCurveSpeed layer 0', 12, since=mark,
                       why='checkpoint 5: second apply from the undo stack (field -1.23 s)')
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_2_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form, storm): undo/redo storm of a speed change stacks full freeze re-extractions + freezeLoader spins on main."""
    _501bb526_state(ed)
    _501bb526_speed(ed, r.uniform(0.3, 0.5), 'checkpoint 2: speed apply on layer 0 (pushes SPEED on the undo stack)')
    ed.idle(1.5)
    (ux, uy), redo = _501bb526_undo_xy(ed)
    ed.set_playing(True)
    ed.idle(1.0)
    ed.dev.slow_phone(r.randint(38, 48))
    try:
        mark = ed.log_mark()
        ed.step('undo/redo storm on the speed change')
        ed.dev.tap(ux, uy)
        ed.require_log(r'MsgSetMediaCurveSpeed layer 0', 12, since=mark,
                       why='checkpoint 5: speed re-apply from the undo stack')
        for k in range(r.randint(6, 10)):            # coordinates cached: main may already be wedged
            ed.dev.tap(*(redo if (k % 2 == 0 and redo) else (ux, uy)))
            time.sleep(r.uniform(0.15, 0.5))
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-21 21:05 level 4 attempt 3
def _501bb526_open(ed):
    """Checkpoint 1: fixture with real FREEZE items on layer 0 (engine + Kotlin itemList). 501bb526 is missing on the
    lab phones, so fall back to 617a5fe5, the fixture behind the lab hit (93.4 s + 20 s clips, 7 freezes on layer 0)."""
    mark = ed.log_mark()
    try:
        ed.open_fixture('501bb526')
    except UIError as e:
        ed.log(f'    {e}; using hit fixture 617a5fe5')
        mark = ed.log_mark()
        ed.open_fixture('617a5fe5')
    ed.require_log(r'MsgAddVideoFreezeDuration.*layer_id 0', 40, since=mark,
                   why='checkpoint 1: freeze items on layer 0 loaded at open (field: MsgFreezeLoader layer_id 0)')
    ed.idle(4)                                       # load must survive before we touch the speed tool
    ed.check()


def _501bb526_apply(ed, frac, why):
    """Speed tool -> bar to frac (None = untouched, 1.0 like the field) -> Done = POP_SPEED (PlayerActivity.kt:6696):
    setMediaCurveSpeed + setVideoSpeed, sync getCurrentTime (6725), freezeLoader() 50 ms later (6754). Back skips it."""
    mark = ed.log_mark()
    ed.clip_tool('speed')
    s = ed.ui.wait(T.SPEED_BAR, timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    if frac is not None:
        l, t, rr, b = s.find(T.SPEED_BAR).b
        y = (t + b) // 2
        ed.dev.swipe((l + rr) // 2, y, int(l + 10 + frac * (rr - l - 20)), y, 300)
        ed.idle(0.4)
    s = ed.screen()
    if s is None or not s.has(T.DONE):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no freezeLoader')
    ed.step('speed apply (Done)')
    ed.dev.tap(*s.find(T.DONE).center)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 15, since=mark, why=why)


def _501bb526_more(ed, fracs, gap):
    """Follow-up applies queued behind the first re-extraction. If main is already wedged in freezeLoader, the tool
    cannot open: that is the field state, so stop applying and let the ANR land."""
    for k, f in enumerate(fracs):
        ed.idle(gap)
        try:
            _501bb526_apply(ed, f, f'checkpoint 5: follow-up speed apply {k + 2} on layer 0 (field -1.23 s)')
        except UIError as e:
            ed.log(f'    follow-up apply blocked (main busy?): {e}')
            return


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_3_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI, endless form (lab hit l5_2_b path, no hook): max speed on the 93 s clip drops every freeze from the engine layer, freezeLoader spins at 0.0."""
    _501bb526_open(ed)
    ed.set_playing(False)                            # playhead at 0 -> the long clip 0 is the speed target
    ed.dev.slow_phone(r.randint(30, 40))
    try:
        _501bb526_apply(ed, 0.99, 'checkpoint 2: max-speed apply on the long layer-0 clip')
        ed.settle(20)                                # hit: am_anr ~8.5 s after the speed step
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_3_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI, slow form in field order: speed 1.0 applied while playing, then again right away, so two full re-extractions queue up."""
    _501bb526_open(ed)
    ed.set_playing(True)                             # lease contended: per-freeze lockContextForEdit really waits
    ed.idle(r.uniform(1.0, 2.0))
    ed.dev.slow_phone(r.randint(35, 45))
    try:
        _501bb526_apply(ed, None, 'checkpoint 2: first speed 1.0 apply on layer 0 (field -2.67 s)')
        _501bb526_more(ed, [None], gap=0.2)          # field: 2nd MsgSetMediaCurveSpeed + MsgSetVideoSpeed 1.4 s later
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l4_3_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI, slow form as a storm: slow-down applies (freezes stay inside the clip and are decoded deeper) stack re-extractions and freezeLoader spins."""
    _501bb526_open(ed)
    ed.set_playing(True)
    ed.idle(1.0)
    ed.dev.slow_phone(r.randint(40, 48))
    try:
        _501bb526_apply(ed, r.uniform(0.05, 0.15), 'checkpoint 2: slow-down speed apply on layer 0')
        _501bb526_more(ed, [r.uniform(0.2, 0.3), r.uniform(0.05, 0.15)], gap=0.1)
        ed.settle(20)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-21 21:09 level 5 attempt 1
def _501bb526_state(ed, holds=2):
    """Checkpoint 1: FREEZE items on layer 0 in the engine AND in Kotlin itemList (freezeLoader() only spins then)."""
    mark = ed.log_mark()
    try:
        ed.open_fixture('501bb526')
        ed.require_log(r'MsgFreezeLoader layer_id 0|MsgAddVideoFreezeDuration', 40, since=mark,
                       why='checkpoint 1: fixture loads freeze items on layer 0')
        ed.idle(3)
        return
    except UIError as e:                             # missing on both lab phones: build it with real taps
        ed.log(f'    {e}; building freezes on the test draft')
    ed.open_draft()
    ed.set_playing(False)
    ed.tap_tool('freeze')
    s = ed.ui.wait(T.FREEZE_APPLY, timeout=10)
    if s is None:
        raise UIError('freeze panel has no Add tile (ve_btn_freeze_apply)')
    x, y = s.find(T.FREEZE_APPLY).center
    for k in range(holds):                           # long-press: START_FREEZE, playback grows it, release = STOP_FREEZE
        mark = ed.log_mark()
        ed.step(f'freeze hold {k + 1}/{holds}')
        ed.dev.swipe(x, y, x, y, 2600)
        ed.require_log(r'MsgAddVideoFreezeDuration:.*layer_id 0', 8, since=mark,
                       why='checkpoint 1: UI freeze item on layer 0 (engine + itemList)')
        if ed.wait_log(r'MsgRemoveVideoFreezeDuration', 2, since=mark):
            raise UIError('freeze shorter than 0.4 s was dropped (STOP_FREEZE): no Kotlin FREEZE item')
        ed.idle(1.2)
    ed.main_nav()
    ed.idle(1.5)
    ed.check()


def _501bb526_speed_open(ed, frac):
    """Speed tool, drag the bar: live MsgSetVideoSpeed on layer 0 (set_video_speed re-extracts every freeze)."""
    mark = ed.log_mark()
    ed.clip_tool('speed')
    s = ed.ui.wait('id:speed_bar', timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    l, t, rr, b = s.find('id:speed_bar').b
    yy = (t + b) // 2
    ed.dev.swipe((l + rr) // 2, yy, int(l + 10 + frac * (rr - l - 20)), yy, 300)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 10, since=mark,
                   why='checkpoint 2: speed change reaches the engine on layer 0')
    ed.idle(2.0)                                     # let the slider's own re-extraction finish before arming
    s = ed.screen()
    if s is None or not s.has('id:done'):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no POP_SPEED, no freezeLoader')
    return s.find('id:done').center


def _501bb526_apply(ed, r, hook, value, extra_taps=0):
    xy = _501bb526_speed_open(ed, r.uniform(0.3, 0.45))
    ed.dev.setprop(f'debug.zesty.hook.{hook}', value)
    try:
        mark = ed.log_mark()
        ed.step('speed apply (Done) -> POP_SPEED -> freezeLoader() +50 ms')
        ed.dev.tap(*xy)
        ed.require_log(rf'NSHOOK {hook}', 6, since=mark, why='checkpoint 3: freezeLoader reached the engine')
        for _ in range(extra_taps):                  # field: second apply ~1.4 s later, queued behind main
            ed.idle(1.4)
            ed.dev.tap(*xy)
        ed.settle(20)                                # field ANR ~7 s after the apply
    finally:
        ed.dev.setprop(f'debug.zesty.hook.{hook}', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_1_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (engine thread idle in dump): layer reports 0 freezes after speed apply (hook), freezeLoader spins at 0.0."""
    _501bb526_state(ed)
    _501bb526_apply(ed, r, 'freeze_layer_empty', '1')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_1_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form): MsgFreezeLoader re-extraction made low-end slow (hook 6 s/freeze), main blocked in freezeProgress."""
    _501bb526_state(ed)
    _501bb526_apply(ed, r, 'freeze_slow_ms', '6000')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_1_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (field order): slow re-extraction (hook 3.5 s/freeze) + second apply tap 1.4 s later on a slowed phone."""
    _501bb526_state(ed)
    ed.dev.slow_phone(r.randint(25, 35))
    try:
        _501bb526_apply(ed, r, 'freeze_slow_ms', '3500', extra_taps=1)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-21 21:15 level 5 attempt 2
def _501bb526_open(ed):
    """Checkpoint 1: fixture 501bb526 with FREEZE items on layer 0, in the engine and in the Kotlin itemList."""
    mark = ed.log_mark()
    ed.open_fixture('501bb526')
    ed.require_log(r'MsgFreezeLoader layer_id 0', 40, since=mark,
                   why='checkpoint 1: draft open runs freezeLoader() (Kotlin FREEZE items) -> MsgFreezeLoader layer 0')
    ed.idle(4)                                       # the open-time freezeLoader spin must finish before the speed tool
    ed.set_playing(False)
    ed.check()


def _501bb526_speed_open(ed, fracs):
    """Speed tool. Each bar drag sends a live MsgSetVideoSpeed on layer 0 (set_video_speed re-extracts every freeze)."""
    mark = ed.log_mark()
    ed.clip_tool('speed')
    s = ed.ui.wait('id:speed_bar', timeout=8)
    if s is None:
        raise UIError('speed tool did not open (no speed_bar)')
    l, t, rr, b = s.find('id:speed_bar').b
    y = (t + b) // 2
    for f in fracs:                                  # field: two speed applies about 1.4 s apart
        ed.dev.swipe((l + rr) // 2, y, int(l + 10 + f * (rr - l - 20)), y, 300)
        ed.idle(0.6)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 10, since=mark,
                   why='checkpoint 2: speed change reaches the engine on layer 0')
    ed.idle(2.5)                                     # let the bar's own re-extraction drain: POP_SPEED's getMediaDuration has no timeout
    s = ed.screen()
    if s is None or not s.has('id:done'):
        raise UIError('speed Done (ve_btn_apply_changes) not found: no POP_SPEED, no freezeLoader')
    return s.find('id:done').center


def _501bb526_apply(ed, hook, value, fracs, slow=0):
    """Arm the hook only for the Done: POP_SPEED -> postDelayed 50 ms freezeLoader() -> spin on freezeProgress."""
    xy = _501bb526_speed_open(ed, fracs)
    ed.dev.setprop(f'debug.zesty.hook.{hook}', value)
    ed.dev.slow_phone(slow)
    try:
        mark = ed.log_mark()
        ed.step('speed apply (Done) -> POP_SPEED -> freezeLoader() +50 ms')
        ed.dev.tap(*xy)
        ed.require_log(rf'NSHOOK {hook}', 8, since=mark,
                       why='checkpoint 3: freezeLoader reached the engine with the field condition forced')
        ed.settle(20)                                # field ANR ~7 s after the apply, lab hit ~8.5 s
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop(f'debug.zesty.hook.{hook}', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_2_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (engine thread idle in ProcessMessages, endless form): layer reports 0 freezes after the speed Done, freezeLoader spins at 0.0."""
    _501bb526_open(ed)
    _501bb526_apply(ed, 'freeze_layer_empty', '1', [r.uniform(0.3, 0.45)])


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_2_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form): MsgFreezeLoader re-extraction after the speed Done takes 8 s per freeze, main blocked in freezeProgress Get."""
    _501bb526_open(ed)
    _501bb526_apply(ed, 'freeze_slow_ms', '8000', [r.uniform(0.3, 0.45)])


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_2_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (field order): two speed changes ~1.4 s apart, then Done on a slowed phone with slow per-freeze extraction (4 s)."""
    _501bb526_open(ed)
    _501bb526_apply(ed, 'freeze_slow_ms', '4000', [r.uniform(0.3, 0.4), r.uniform(0.45, 0.55)],
                    slow=r.randint(25, 35))


# 2026-10-21 21:18 level 5 attempt 3
def _501bb526_open(ed):
    """Checkpoint 1: lab fixture with FREEZE items on layer 0 in the engine and in the Kotlin itemList."""
    mark = ed.log_mark()
    ed.open_fixture('501bb526')
    ed.require_log(r'MsgFreezeLoader layer_id 0|MsgAddVideoFreezeDuration.*layer_id 0', 40, since=mark,
                   why='checkpoint 1: fixture loads freeze items on layer 0 at open')
    ed.idle(4)                                       # the open-time freezeLoader() (PlayerActivity.kt:4304) must finish
    ed.check()
    ed.set_playing(False)


def _501bb526_speed_tool(ed):
    """Open Speed on the clip under the playhead. Returns the speed_bar bounds and the Done (ve_btn_apply_changes) center."""
    ed.clip_tool('speed')
    s = ed.ui.wait('id:speed_bar', timeout=8)
    if s is None or not s.has('id:done'):
        raise UIError('speed tool did not open (no speed_bar / done)')
    return s.find('id:speed_bar').b, s.find('id:done').center


def _501bb526_drag(ed, bar, frac):
    """Move the speed bar so the slider sends a live MsgSetVideoSpeed (set_video_speed re-extracts every freeze)."""
    mark = ed.log_mark()
    l, t, rr, b = bar
    y = (t + b) // 2
    ed.dev.swipe((l + rr) // 2, y, int(l + 10 + frac * (rr - l - 20)), y, 300)
    ed.require_log(r'MsgSetVideoSpeed: speed [\d.]+, layer 0', 10, since=mark,
                   why='checkpoint 2: speed change reaches the engine on layer 0')


def _501bb526_done(ed, xy, gate, why):
    """Done = POP_SPEED: sync getCurrentTime (6725), then freezeLoader() 50 ms later spins on freezeProgress (14610)."""
    mark = ed.log_mark()
    ed.step('speed apply (Done) -> freezeLoader() +50 ms')
    ed.dev.tap(*xy)
    ed.require_log(gate, 10, since=mark, why=why)
    ed.settle(20)                                    # lab hit: am_anr ~8.5 s after the apply


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_3_a(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (engine thread idle): layer reports 0 freezes (hook) after a speed apply, freezeLoader spins at 0.0."""
    _501bb526_open(ed)
    bar, xy = _501bb526_speed_tool(ed)
    _501bb526_drag(ed, bar, r.uniform(0.85, 0.99))  # speed-up, as in the lab hit (speed 7.6 emptied the layer)
    ed.idle(2.0)                                     # the slider's own re-extraction finishes first
    ed.dev.setprop('debug.zesty.hook.freeze_layer_empty', '1')
    try:
        _501bb526_done(ed, xy, r'NSHOOK freeze_layer_empty',
                       'checkpoint 3: main is in freezeLoader and the layer reports no freeze intervals')
    finally:
        ed.dev.setprop('debug.zesty.hook.freeze_layer_empty', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_3_b(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (slow form): MsgFreezeLoader re-extraction as slow as a low-end phone (hook), main blocked in freezeProgress."""
    _501bb526_open(ed)
    bar, xy = _501bb526_speed_tool(ed)
    _501bb526_drag(ed, bar, r.uniform(0.3, 0.45))
    ed.idle(2.0)
    ed.dev.setprop('debug.zesty.hook.freeze_slow_ms', str(r.choice([2000, 3000])))
    ed.dev.slow_phone(r.randint(25, 35))
    try:
        _501bb526_done(ed, xy, r'NSHOOK freeze_slow_ms',
                       'checkpoint 3: MsgFreezeLoader re-extraction runs on the message thread while main spins')
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop('debug.zesty.hook.freeze_slow_ms', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_l5_3_c(ed, r):
    """Field 2026-10-18T03:47:50Z Xiaomi 21091116UI (field order): MsgSetVideoSpeed's own re-extraction is slow (hook), so Done meets a busy queue: getCurrentTime TIMEOUT, then freezeLoader waits."""
    _501bb526_open(ed)
    bar, xy = _501bb526_speed_tool(ed)
    ed.dev.setprop('debug.zesty.hook.freeze_slow_ms', '1500')   # armed BEFORE the speed change, like the field
    try:
        _501bb526_drag(ed, bar, r.uniform(0.3, 0.6))
        ed.require_log(r'NSHOOK freeze_slow_ms', 6, why='checkpoint 3: set_video_speed re-extracts freezes, queue busy')
        ed.idle(r.uniform(0.3, 0.8))                 # field: apply landed ~1 s into the silence
        _501bb526_done(ed, xy, r'getCurrentTime: TIMEOUT|WaitFor TIMEOUT for message ID: MsgGetCurrentTime',
                       'checkpoint 4: main getCurrentTime after apply times out behind the speed handler')
    finally:
        ed.dev.setprop('debug.zesty.hook.freeze_slow_ms', '0')
