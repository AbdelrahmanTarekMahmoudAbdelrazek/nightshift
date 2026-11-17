# Night Shift: frozen copy of the registered repro ns_g00fe1e6_l4_1_c (1109164951); later runs cannot change it
# Night Shift auto repros for 501bb52658b63a6c0a32a5b8bbd06b8b~00fe1e6d


# 2026-11-09 15:54 level 3 attempt 1
def _g00fe1e6_codec_user(ed, on):
    """Another codec user: the system screen recorder holds a hardware encoder while the editor decodes."""
    ed.dev.sh('pkill -f "screenrecord" 2>/dev/null')
    if on:
        ed.dev.sh('nohup screenrecord --bit-rate 20000000 --time-limit 170 /sdcard/Download/ns_g00fe1e6.mp4 >/dev/null 2>&1 &')


def _g00fe1e6_arm(ed, r, handle):
    """Seek so the clip's START (or END) edge sits under the playhead, select the clip, and find the handle: the press
    that logs MsgTrimVideo (onMediaTrackStartTouch -> trimVideo -> getMediaDurationByID) is on it."""
    ed.track = None
    ed.set_playing(False)
    (ed.seek_start if handle == 'start' else ed.seek_end)()          # 4 fast swipes = the field's scrub seeks
    l, rr, y = ed._track_y()
    cx, w = (l + rr) // 2, rr - l
    for dx in (10, 25, -5, 40, -20, 55, -35, 70):
        ed.dev.tap(cx + (int(w * 0.18) if handle == 'start' else -int(w * 0.18)), y)   # clip body: select it
        ed.idle(0.8)
        m = ed.log_mark()
        ed.dev.drag_no_fling(cx + dx, y, cx + dx, steps=1, hold=0.15)
        if ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 1.5, since=m):
            ed.idle(1.2)
            return cx + dx, y
    raise UIError(f'inline trim {handle} handle not found near the playhead')


def _g00fe1e6_trim_loop(ed, r, handle, n, gap=(0.05, 0.4), reseek_every=5):
    """The field loop: drag the same handle, release (ve_trim_complete -> processTrim), again and again ~1 s apart."""
    x, y = _g00fe1e6_arm(ed, r, handle)
    sign = 1 if handle == 'start' else -1
    for i in range(n):
        ed.step(f'trim {handle} {i + 1}/{n}')
        m = ed.log_mark()
        ed.dev.drag_no_fling(x, y, x + sign * r.randint(60, 170), steps=5, hold=r.uniform(0.1, 0.3))
        if not ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 3, since=m):
            x, y = _g00fe1e6_arm(ed, r, handle)                      # selection lost: find the handle again, once
            m = ed.log_mark()
            ed.dev.drag_no_fling(x, y, x + sign * r.randint(60, 170), steps=5, hold=0.2)
            ed.require_log(r'MsgTrimVideo: media_layer 0 ', 3, since=m, why='checkpoint 2: trim release reaches the engine')
        ed.idle(r.uniform(*gap))
        if reseek_every and i % reseek_every == reseek_every - 1:     # scrub seeks between trims, then back to the edge
            ed.seek_swipe(r.choice((-1, 1)) * r.uniform(0.3, 0.6), r.randint(40, 120))
            x, y = _g00fe1e6_arm(ed, r, handle)


def _g00fe1e6_project(ed, tag, seconds):
    m = ed.log_mark()
    ed.new_project(tag=tag, duration_s=seconds)
    ed.require_log(r'MsgGetMediaDuration: media_layer 0 media_id: \d+, original: \d{8},', 30, since=m,
                   why='checkpoint 1: one 10-99 s video clip on layer 0')
    ed.idle(3)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_1_a_r1109164951(ed, r):
    """Firebase 2026-10-23 + 2026-10-22 (1.25.1): START-handle trim loop on a 15-20 s clip, slow CPU + a competing hardware codec + critical memory pressure."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_a', r.choice((16, 20)))
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.dev.slow_phone(40)
        _g00fe1e6_trim_loop(ed, r, 'start', r.randint(16, 22))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_1_b_r1109164951(ed, r):
    """Firebase 2026-11-09 (1.26.0): END-handle trim loop on a 60 s clip (47 s <-> 60 s), then back + scrubs + one more trim, slow CPU + busy storage."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_b', 60)
    try:
        ed.dev.busy_storage(True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        ed.dev.slow_phone(44)
        _g00fe1e6_trim_loop(ed, r, 'end', r.randint(14, 18), reseek_every=4)
        ed.idle(1.1)
        ed.dev.key('KEYCODE_BACK')                     # field: 'back' at T-0.35s, then scrub seeks
        ed.seek_storm(r.randint(4, 8), pause=(0.0, 0.08))
        _g00fe1e6_trim_loop(ed, r, 'end', 3, reseek_every=0)
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_1_c_r1109164951(ed, r):
    """Play sample 1.25.1 (onMediaTrackStartTouch): camera took the codecs while away, return, then press the handle again while each trim render is still running."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_c', 20)
    ed.background(r.uniform(15, 25), pressure=True)    # camera open + trim-memory COMPLETE, back to the editor
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.slow_phone(42)
        _g00fe1e6_trim_loop(ed, r, 'start', r.randint(18, 24), gap=(0.0, 0.08), reseek_every=6)
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


# 2026-11-09 16:00 level 3 attempt 2
def _g00fe1e6_codec_user(ed, on):
    """Another codec user: the system screen recorder holds a hardware encoder while the editor decodes."""
    ed.dev.sh('pkill -f screenrecord 2>/dev/null')
    if on:
        ed.dev.sh('nohup screenrecord --bit-rate 20000000 --time-limit 170 /sdcard/Download/ns_g00fe1e6.mp4 >/dev/null 2>&1 &')


def _g00fe1e6_project(ed, tag, seconds):
    """New project from a fresh copy of a ~`seconds` clip; wait until it has loaded (taps before that are lost)."""
    m = ed.log_mark()
    ed.new_project(tag=tag, duration_s=seconds)
    ed.require_log(r'Event: test_ve_draft_project_complete', 60, since=m, why='editor finished loading the project')
    ed.idle(2)


def _g00fe1e6_arm(ed, handle, seek=True, first=False):
    """Put the clip's start/end edge under the playhead and find its trim handle. A plain press on it runs
    onMediaTrackStartTouch -> trimVideo + getMediaDurationByID (main), so the probe itself logs MsgTrimVideo."""
    ed.track = None
    ed.set_playing(False)
    if seek:
        (ed.seek_start if handle == 'start' else ed.seek_end)()     # 4 fast swipes = the field's scrub seeks
    l, rr, y = ed._track_y()
    cx, w = (l + rr) // 2, rr - l
    body = cx + int(w * 0.2) if handle == 'start' else cx - int(w * 0.2)
    m0 = ed.log_mark()
    for dx in (20, 20, 0, 0, 40, 40, -15, -15, 60, 60):
        m = ed.log_mark()
        ed.dev.drag_no_fling(cx + dx, y, cx + dx, steps=1, hold=0.15)
        if ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 3, since=m):
            if first:
                ed.require_log(r'MsgGetMediaDuration: media_layer 0 media_id: ?\d+, original: \d{8},', 6, since=m0,
                               why='checkpoint 1: one 10-99 s video clip on layer 0')
            ed.idle(1.2)
            return cx + dx, y
        ed.dev.tap(body, y)                          # not selected (or the tap toggled it): select the clip body
        ed.idle(0.8)
    raise UIError(f'inline trim {handle} handle not found at the playhead')


def _g00fe1e6_trim_loop(ed, r, handle, x, y, n, gap=(0.05, 0.3), reseek_every=5):
    """Field loop: drag the handle in, release; drag it back out, release (two ranges), ~1 s apart, scrubs between."""
    inward = 1 if handle == 'start' else -1
    for i in range(n):
        ed.step(f'trim {handle} {i + 1}/{n}')
        d = inward * r.randint(70, 160) * (1 if i % 2 == 0 else -1)
        m = ed.log_mark()
        ed.dev.drag_no_fling(x, y, x + d, steps=5, hold=r.uniform(0.1, 0.25))
        if not ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 4, since=m):
            x, y = _g00fe1e6_arm(ed, handle)
            m = ed.log_mark()
            ed.dev.drag_no_fling(x, y, x + d, steps=5, hold=0.2)
        ed.require_log(r've_trim_complete', 5, since=m, why='checkpoint 2: trim release -> processTrim')
        ed.require_log(r'MsgTrimVideo: media_layer 0 ', 5, since=m, why='checkpoint 2: trimVideo reached the engine')
        ed.idle(r.uniform(*gap))
        if reseek_every and i % reseek_every == reseek_every - 1:
            ed.seek_swipe(r.choice((-1, 1)) * r.uniform(0.3, 0.6), r.randint(40, 120))
            x, y = _g00fe1e6_arm(ed, handle)
    return x, y


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_2_a_r1109164951(ed, r):
    """Firebase 2026-10-23 + 2026-10-22 (1.25.1): START-handle trim loop (0 <-> ~8 s) on a 15-20 s clip, slow CPU + screen recorder codec + critical memory."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_a', r.choice((16, 20)))
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.dev.slow_phone(42)
        _g00fe1e6_trim_loop(ed, r, 'start', x, y, r.randint(16, 22))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_2_b_r1109164951(ed, r):
    """Firebase 2026-11-09 (1.26.0): END-handle trim loop (47 s <-> 60 s) on a ~60 s clip, then scrubs and final releases, slow CPU + busy storage."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_b', 60)
    x, y = _g00fe1e6_arm(ed, 'end', first=True)
    try:
        ed.dev.busy_storage(True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        ed.dev.slow_phone(44)
        x, y = _g00fe1e6_trim_loop(ed, r, 'end', x, y, r.randint(14, 18), reseek_every=4)
        ed.seek_storm(r.randint(4, 8), pause=(0.0, 0.08))   # field: scrub seeks after the last finished trim
        x, y = _g00fe1e6_arm(ed, 'end')
        _g00fe1e6_trim_loop(ed, r, 'end', x, y, 3, gap=(0.0, 0.1), reseek_every=0)
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_2_c_r1109164951(ed, r):
    """Play sample 1.25.1 (onMediaTrackStartTouch): camera took the codecs while away, return, then press/release the start handle while each trim render runs."""
    _g00fe1e6_project(ed, 'ns_g00fe1e6_c', 20)
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    background_keep_screen(ed, r.uniform(15, 25), pressure='RUNNING_CRITICAL', camera=True)
    s = ed.screen()
    if s is None or not ed.in_editor(s):
        raise UIError('did not come back to the editor after the camera')
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.slow_phone(42)
        x, y = _g00fe1e6_arm(ed, 'start', seek=False)
        x, y = _g00fe1e6_trim_loop(ed, r, 'start', x, y, r.randint(10, 14), gap=(0.0, 0.08), reseek_every=6)
        for _ in range(r.randint(8, 12)):            # press-only: trimVideo + getMediaDuration on DOWN, restore on UP
            ed.dev.drag_no_fling(x, y, x, steps=1, hold=r.uniform(0.05, 0.2))
            ed.idle(r.uniform(0.0, 0.15))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


# 2026-11-09 16:15 level 3 attempt 3
def _g00fe1e6_codec_user(ed, on):
    """Another hardware codec user: the screen recorder keeps an encoder busy while the editor decodes."""
    ed.dev.sh('pkill -f screenrecord 2>/dev/null')
    if on:
        ed.dev.sh('nohup screenrecord --bit-rate 20000000 --time-limit 170 /sdcard/Download/ns_g00fe1e6.mp4 >/dev/null 2>&1 &')


def _g00fe1e6_project(ed, r, tag, lo, hi):
    """New project from a NEW copy of a phone video whose REAL length is lo..hi s (unique name: no CACHED transcode)."""
    lens = [s for _, s in ed.dev.video_lengths() if 15 <= s <= 70]
    pick = [s for s in lens if lo <= s <= hi] or lens
    if not pick:
        raise UIError('no 15-70 s video on the phone for the field clip (15-60 s)')
    m = ed.log_mark()
    ed.new_project(tag=f'{tag}_{r.randint(10000, 99999)}', duration_s=int(round(r.choice(pick))))
    ed.require_log(r'Event: test_ve_draft_project_complete', 60, since=m, why='editor finished loading the project')
    ed.idle(2)


def _g00fe1e6_arm(ed, handle, first=False):
    """Clip edge under the playhead; a plain press on the handle = onMediaTrackStartTouch -> trimVideo + getMediaDuration."""
    ed.track = None
    ed.set_playing(False)
    (ed.seek_start if handle == 'start' else ed.seek_end)()
    l, rr, y = ed._track_y()
    cx, w = (l + rr) // 2, rr - l
    body = cx + int(w * 0.2) if handle == 'start' else cx - int(w * 0.2)
    m0 = ed.log_mark()
    for dx in (20, 20, 0, 0, 40, 40, -15, -15, 60, 60):
        m = ed.log_mark()
        ed.dev.drag_no_fling(cx + dx, y, cx + dx, steps=1, hold=0.15)
        if ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 3, since=m):
            if first:
                ed.require_log(r'MsgGetMediaDuration: media_layer 0 media_id: ?\d+, original: \d{8},', 6, since=m0,
                               why='checkpoint 1: one 10-99 s video clip on layer 0')
            ed.idle(1.2)
            return cx + dx, y
        ed.dev.tap(body, y)                              # not selected: select the clip body, try again
        ed.idle(0.8)
    raise UIError(f'inline trim {handle} handle not found at the playhead')


def _g00fe1e6_trim_loop(ed, r, handle, x, y, n, press_only=False):
    """Field loop as ONE tight gesture batch: drag in/release, drag out/release (two ranges), no dumps between."""
    d = (1 if handle == 'start' else -1) * r.randint(90, 150)
    m_all, m = ed.log_mark(), ed.log_mark()
    for i in range(n):
        if press_only:
            ed.dev.drag_no_fling(x, y, x, steps=1, hold=r.uniform(0.05, 0.2))
        else:                                            # the drag's own progress seeks = the field's scrubs
            ed.dev.drag_no_fling(x, y, x + (d if i % 2 == 0 else -d), steps=8, hold=r.uniform(0.1, 0.3))
        time.sleep(r.uniform(0.0, 0.12))
        if i == 5 and not ed.wait_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 1.5, since=m_all):
            ed.dev.slow_phone(48)                        # decoder still fast: make the phone as slow as the OPPO A17
        if i % 6 == 5:
            if not ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 0.5, since=m):
                x, y = _g00fe1e6_arm(ed, handle)         # selection lost: find the handle again
            m = ed.log_mark()
    if not press_only:
        ed.require_log(r've_trim_complete', 3, since=m_all, why='checkpoint 2: release -> processTrim')
    ed.require_log(r'MsgGetMediaDuration: media_layer 0 ', 3, since=m_all, why='checkpoint 2: getMediaDuration after trim')
    ed.require_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 3, since=m_all,
                   why='checkpoint 3: trim render slow (decoder gives no frame within 1 s)')
    return x, y


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_3_a_r1109164951(ed, r):
    """Firebase 2026-10-23 + 2026-10-22 (1.25.1): START-handle drag loop (0 <-> ~8 s) on a 15-25 s clip, slow CPU + screen-recorder codec + critical memory."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_a', 15, 25)
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.dev.slow_phone(42)
        _g00fe1e6_trim_loop(ed, r, 'start', x, y, r.randint(24, 30))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_3_b_r1109164951(ed, r):
    """Firebase 2026-11-09 (1.26.0): END-handle drag loop (47 s <-> 60 s) on a ~60 s clip, then back + scrubs + final releases, slow CPU + busy storage."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_b', 45, 70)
    x, y = _g00fe1e6_arm(ed, 'end', first=True)
    try:
        ed.dev.busy_storage(True)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        ed.dev.slow_phone(44)
        _g00fe1e6_trim_loop(ed, r, 'end', x, y, r.randint(20, 26))
        ed.dev.key('KEYCODE_BACK')                       # field: 'back' at T-0.35s, then scrub seeks
        ed.seek_storm(r.randint(4, 8), pause=(0.0, 0.08))
        x, y = _g00fe1e6_arm(ed, 'end')
        _g00fe1e6_trim_loop(ed, r, 'end', x, y, 6)
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l3_3_c_r1109164951(ed, r):
    """Play sample 1.25.1 (onMediaTrackStartTouch): camera took the codecs while away, return, then rapid handle presses (trimVideo + getMediaDuration each) under a busy codec."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_c', 15, 30)
    ed.background(r.uniform(15, 25), pressure=True)      # camera open + trim-memory COMPLETE, back to the editor
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    try:
        _g00fe1e6_codec_user(ed, True)
        ed.dev.slow_phone(44)
        _g00fe1e6_trim_loop(ed, r, 'start', x, y, r.randint(30, 40), press_only=True)
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
        _g00fe1e6_codec_user(ed, False)


# 2026-11-09 16:29 level 4 attempt 1
def _g00fe1e6_project(ed, r, tag, lo, hi):
    """New project from a fresh copy of a lo..hi s phone video, indexed for real (scan_file), so the picker's first tile IS it."""
    lens = [s for _, s in ed.dev.video_lengths() if 12 <= s <= 90]
    pick = [s for s in lens if lo <= s <= hi] or lens
    if not pick:
        raise UIError('no 12-90 s video on the phone for the field clip (15-60 s)')
    dur = int(round(r.choice(pick)))
    p = ed.dev.fresh_video(tag=tag, duration_s=dur)       # the scanner broadcast is ignored on uid 10566: scan it ourselves
    ed.dev.sh('content call --uri content://media --method scan_file --arg ' + p.replace('/sdcard/', '/storage/emulated/0/'), timeout=60)
    m = ed.log_mark()
    ed.new_project(tag=tag, duration_s=dur)
    ed.require_log(r'Event: test_ve_draft_project_complete', 60, since=m, why='editor finished loading the project')
    ed.idle(2)


def _g00fe1e6_arm(ed, handle, first=False):
    """Clip edge under the playhead; a press on its handle = onMediaTrackStartTouch -> trimVideo + getMediaDurationByID (main)."""
    ed.track = None
    ed.set_playing(False)
    (ed.seek_start if handle == 'start' else ed.seek_end)()
    l, rr, y = ed._track_y()
    cx, w = (l + rr) // 2, rr - l
    body = cx + int(w * 0.2) if handle == 'start' else cx - int(w * 0.2)
    for dx in (20, 20, 0, 0, 40, 40, -15, -15, 60, 60):
        m = ed.log_mark()
        ed.dev.drag_no_fling(cx + dx, y, cx + dx, steps=1, hold=0.1)
        if ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 3, since=m):
            if first:
                ed.require_log(r'MsgGetMediaDuration: media_layer 0 media_id: ?\d+, original: \d{8},', 6, since=m,
                               why='checkpoint 1: one 10-99 s video clip on layer 0')
            ed.idle(1.2)
            return cx + dx, y
        ed.dev.tap(body, y)                                  # not selected: select the clip body, try again
        ed.idle(0.8)
    raise UIError(f'inline trim {handle} handle not found at the playhead')


def _g00fe1e6_loop(ed, r, handle, x, y, n, scrub_every=0, taps=0):
    """Field cadence: drag in / release, drag out / release (two ranges) ~1 s apart; 2 MOVEs only (each `input` = 1 JVM)."""
    d = (1 if handle == 'start' else -1) * r.randint(90, 150)
    m_all = m = ed.log_mark()
    for i in range(n):
        if taps:                                             # Play sample: presses on the handle while the trim render runs
            ed.dev.sh('; '.join([f'input tap {x} {y}'] * taps))
        ed.dev.drag_no_fling(x, y, x + (d if i % 2 == 0 else -d), steps=2, hold=r.uniform(0.02, 0.1))
        if scrub_every and i % scrub_every == scrub_every - 1:
            (ed.seek_start if handle == 'start' else ed.seek_end)()   # scrub seeks INTO the trim render, back to the edge
        if i == 5 and not ed.wait_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 0.5, since=m_all):
            ed.dev.slow_phone(48)                            # decoder still fast: as slow as the OPPO A17
        if i == 3:
            ed.require_log(r've_trim_complete', 4, since=m_all, why='checkpoint 2: release -> processTrim')
            ed.require_log(r'MsgGetMediaDuration: media_layer 0 ', 4, since=m_all, why='checkpoint 2: getMediaDuration after trimVideo')
        if i == 12:
            ed.require_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 3, since=m_all,
                           why='checkpoint 3: trim render slow (no decoder frame within 1 s)')
        if i % 6 == 5:
            if not ed.wait_log(r'MsgTrimVideo: media_layer 0 ', 0.5, since=m):
                x, y = _g00fe1e6_arm(ed, handle)             # selection lost: find the handle again
            m = ed.log_mark()


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l4_1_a_r1109164951(ed, r):
    """Firebase 2026-10-23 + 2026-10-22 (1.25.1): START-handle drag/release loop (0 <-> ~8 s) on a 15-25 s clip at ~1 s cadence, slow CPU."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_a', 15, 25)
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    try:
        ed.dev.slow_phone(44)
        _g00fe1e6_loop(ed, r, 'start', x, y, r.randint(26, 34))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l4_1_b_r1109164951(ed, r):
    """Firebase 2026-11-09 (1.26.0): END-handle loop (47 s <-> 60 s) on a 45-65 s clip, scrub seeks fired into every 3rd trim render, slow CPU."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_b', 45, 65)
    x, y = _g00fe1e6_arm(ed, 'end', first=True)
    try:
        ed.dev.slow_phone(44)
        _g00fe1e6_loop(ed, r, 'end', x, y, r.randint(24, 30), scrub_every=3)
        ed.dev.drag_no_fling(x, y, x - 120, steps=2, hold=0.05)   # one more release right after the last scrub
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l4_1_c_r1109164951(ed, r):
    """Play sample 1.25.1 (onMediaTrackStartTouch): bursts of handle presses (trimVideo + sync getMediaDuration each) into running trim renders, slow CPU."""
    _g00fe1e6_project(ed, r, 'ns_g00fe1e6_c', 15, 25)
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    try:
        ed.dev.slow_phone(44)
        _g00fe1e6_loop(ed, r, 'start', x, y, r.randint(18, 24), taps=r.randint(3, 5))
        ed.settle(14)
    finally:
        ed.dev.slow_phone(0)
