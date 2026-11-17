# Night Shift tap repros for 501bb52658b63a6c0a32a5b8bbd06b8b~00fe1e6d (from the engine repro + full field log)


# 2026-11-09 15:11 attempt 1
"""Night Shift tapflow g00fe1e6: ANR condition_variable::wait in JNI_getMediaDuration <- onMediaTrackStartTouch
(inline trim of the last clip's END handle while the previous trim render is stuck in MediaCodec)."""

TRIM_DOWN = r'MsgTrimVideo: media_layer 0 media_id \d+ start_time [\d.]+, end_time \d+'
TRIM_UP = r've_trim_complete'


def _select_last_clip(ed):
    """Scrub to the end (last clip's end under the centred playhead), then Edit selects that clip."""
    ed.set_playing(False)
    t0 = ed.log_mark()
    ed.seek_end()
    ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=t0, why='scrub to timeline end')
    t0 = ed.log_mark()
    ed.clip_tools()                                   # taps Edit (ve_tab_edit): selects the clip under the playhead
    ed.require_log(r've_edit_tool_btn', timeout=10, since=t0, why='Edit tool selects the last clip')
    ed.idle(1.0)


def _drag_end_handle(ed, r, hold=0.3, why='end-handle trim'):
    """Press the END handle of the selected clip (just right of the playhead), drag left, lift."""
    l, rr, y = ed._track_y()
    cx = (l + rr) // 2
    x0 = cx + r.randint(14, 26)                        # inside the 15 dp handle zone right of the clip end
    t0 = ed.log_mark()
    ed.dev.drag_no_fling(x0, y, x0 - r.randint(60, 220), steps=r.randint(8, 16), hold=hold)
    ed.require_log(TRIM_DOWN, timeout=15, since=t0, why=f'{why}: press -> trimVideo(full)+getMediaDuration')
    ed.require_log(TRIM_UP, timeout=20, since=t0, why=f'{why}: lift -> ve_trim_complete')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_1_a(ed, r):
    """FULL: new project with a 60 s clip; trim its END handle again and again with scrubs between (field path)."""
    ed.new_project(tag='g00fe1e6a', duration_s=60)
    ed.idle(6)
    _select_last_clip(ed)
    for i in range(12):
        ed.step(f'inline trim {i + 1}/12')
        _drag_end_handle(ed, r, hold=r.uniform(0.2, 0.6), why=f'trim {i + 1}')
        ed.idle(r.uniform(0.8, 1.6))                  # field: next press ~1-2 s after release
        if i % 3 == 2:                                # field: scrub storms between trims
            t0 = ed.log_mark()
            for _ in range(r.randint(3, 6)):
                ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(60, 200))
            ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='scrub between trims')
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow')
def tf_g00fe1e6_1_b(ed, r):
    """HYBRID: lab test draft (several clips, last one trimmed like media 6); handle presses are real taps."""
    ed.jni('pausePlaying()')                          # HYBRID: field user was paused before every trim
    ed.idle(1)
    _select_last_clip(ed)
    for i in range(14):
        ed.step(f'inline trim {i + 1}/14')
        _drag_end_handle(ed, r, hold=r.uniform(0.1, 0.4), why=f'trim {i + 1}')
        ed.idle(r.uniform(0.6, 1.2))
        if i % 4 == 3:
            t0 = ed.log_mark()
            ed.seek_storm(n=r.randint(5, 10), min_ms=40, max_ms=160)
            ed.require_log(r'get_frame interrupted by new seek|seek requested', timeout=10, since=t0,
                           why='scrub storm between trims')
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_1_c(ed, r):
    """FULL: slow-phone variant; next END-handle press lands inside the previous trim render's TRYAGAIN window."""
    ed.new_project(tag='g00fe1e6c', duration_s=60)
    ed.idle(6)
    _select_last_clip(ed)
    try:
        ed.dev.slow_phone(r.randint(30, 45))          # low-end OPPO CPH2477: decoder gives no frame within 1 s
        ed.dev.busy_storage(True)
        ed.trim_memory('RUNNING_LOW')
        for i in range(16):
            ed.step(f'fast inline trim {i + 1}/16')
            _drag_end_handle(ed, r, hold=r.uniform(0.05, 0.25), why=f'fast trim {i + 1}')
            ed.idle(r.uniform(0.3, 0.9))              # press again while trim_media's render is still in get_frame
            if i % 5 == 4:
                t0 = ed.log_mark()
                for _ in range(r.randint(4, 8)):
                    ed.seek_swipe(r.uniform(-0.5, 0.5), r.randint(50, 150))
                ed.require_log(r'seek requested', timeout=15, since=t0, why='scrub between fast trims')
                _select_last_clip(ed)
        ed.settle(10)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)


# 2026-11-09 15:20 attempt 2
"""Night Shift tapflow g00fe1e6: ANR condition_variable::wait in JNI_getMediaDuration <- onMediaTrackStartTouch
(inline trim of the last clip's END handle while the previous trim render is stuck in MediaCodec)."""

PRESS = r'MsgTrimVideo: media_layer 0 media_id \d+ start_time [\d.]+, end_time \d+'
RELEASE = r've_trim_complete'


def _unlock(ed):
    """Attempt 1 died on the lock screen (keyguard): wake the phone and dismiss it before any launch."""
    ed.dev.key('KEYCODE_WAKEUP')
    ed.dev.sh('wm dismiss-keyguard; svc power stayon usb')
    time.sleep(1.5)


def _select_last_clip(ed):
    """Scrub to the end (last clip's end under the playhead), then Edit selects that clip."""
    ed.set_playing(False)
    t0 = ed.log_mark()
    ed.seek_end()
    ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=t0, why='scrub to timeline end')
    if not ed.in_clip_tools():
        t0 = ed.log_mark()
        ed.clip_tools()                               # Edit (ve_tab_edit) selects the clip under the playhead
        ed.require_log(r've_edit_tool_btn', timeout=10, since=t0, why='Edit tool selects the last clip')
    ed.idle(1.0)


def _trim(ed, r, hold, why):
    """Press the END handle (just right of the playhead), drag left, lift: press = trimVideo(full)+getMediaDuration."""
    l, rr, y = ed._track_y()
    x0 = (l + rr) // 2 + r.randint(14, 26)
    t0 = ed.log_mark()
    ed.dev.drag_no_fling(x0, y, x0 - r.randint(60, 220), steps=r.randint(8, 16), hold=hold)
    ed.require_log(PRESS, timeout=15, since=t0, why=f'{why}: press -> MsgTrimVideo')
    ed.require_log(RELEASE, timeout=20, since=t0, why=f'{why}: lift -> ve_trim_complete')


def _scrub(ed, r, n):
    t0 = ed.log_mark()
    for _ in range(n):
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(50, 200))
    ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='scrub between trims')


def _setup_two_clips(ed, tag):
    _unlock(ed)
    ed.new_project(tag=tag, duration_s=60)
    ed.idle(4)
    ed.set_playing(False)
    t0 = ed.log_mark()
    ed.add_media(pick=0)                              # field: trimmed clip is media 6 behind media 5 (two long clips)
    ed.require_log(r'MsgAddVideo: media_layer 0', timeout=60, since=t0, why='second clip on layer 0')
    ed.idle(3)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_2_a(ed, r):
    """FULL: new project, 2 long clips; trim the last clip's END handle again and again with scrubs between."""
    _setup_two_clips(ed, 'g00fe1e6a')
    _select_last_clip(ed)
    for i in range(14):
        ed.step(f'inline trim {i + 1}/14')
        _trim(ed, r, r.uniform(0.2, 0.6), f'trim {i + 1}')
        ed.idle(r.uniform(0.8, 1.8))                  # field: next press 1-2 s after the release
        if i % 3 == 2:
            _scrub(ed, r, r.randint(3, 6))
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_2_b(ed, r):
    """HYBRID: lab test draft (clips on layer 0); pause via JNI, every handle press/release is a real touch."""
    _unlock(ed)
    ed.open_draft()
    ed.idle(8)                                        # taps before the draft finished loading are lost
    ed.jni('pausePlaying()')                          # HYBRID: field user was paused before every trim
    _select_last_clip(ed)
    for i in range(16):
        ed.step(f'inline trim {i + 1}/16')
        _trim(ed, r, r.uniform(0.1, 0.4), f'trim {i + 1}')
        ed.idle(r.uniform(0.6, 1.2))
        if i % 4 == 3:
            _scrub(ed, r, r.randint(5, 9))
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_2_c(ed, r):
    """FULL: slow-phone variant; each END-handle press lands inside the previous trim render's TRYAGAIN window."""
    _setup_two_clips(ed, 'g00fe1e6c')
    _select_last_clip(ed)
    try:
        ed.dev.slow_phone(r.randint(30, 45))          # low-end OPPO CPH2477: decoder gives no frame within 1 s
        ed.dev.busy_storage(True)
        ed.trim_memory('RUNNING_LOW')
        for i in range(18):
            ed.step(f'fast inline trim {i + 1}/18')
            _trim(ed, r, r.uniform(0.05, 0.25), f'fast trim {i + 1}')
            ed.idle(r.uniform(0.3, 0.9))              # press again while trim_media's render is still in get_frame
            if i % 5 == 4:
                _scrub(ed, r, r.randint(4, 8))
                _select_last_clip(ed)
        ed.settle(10)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)


# 2026-11-09 15:31 attempt 3
"""Night Shift tapflow g00fe1e6: ANR condition_variable::wait in JNI_getMediaDuration <- onMediaTrackStartTouch
(press on the END trim handle while the previous trim's render (trim_media) is stuck in MediaCodec)."""

PRESS = r'MsgTrimVideo: media_layer 0 media_id \d+ start_time [\d.]+, end_time \d+'
RELEASE = r've_trim_complete|MsgTrimVideo: media_layer 0 media_id \d+ start_time'


def _unlock(ed):
    ed.dev.key('KEYCODE_WAKEUP')
    ed.dev.sh('wm dismiss-keyguard; svc power stayon usb')
    time.sleep(1.5)


def _select_last_clip(ed):
    """Scrub to the end (last clip's end under the playhead), then Edit selects that clip."""
    ed.set_playing(False)                             # a press while playing only pauses (ThumbLineView:517)
    t0 = ed.log_mark()
    ed.seek_end()
    ed.require_log(r'VideoPlayer::seek requested time=\d+', timeout=10, since=t0, why='scrub to timeline end')
    if not ed.in_clip_tools():
        t0 = ed.log_mark()
        ed.clip_tools()
        ed.require_log(r've_edit_tool_btn', timeout=10, since=t0, why='Edit tool selects the last clip')
    ed.idle(1.0)


def _trim(ed, r, i, hold, why):
    """Press END handle (= trimVideo(full)+getMediaDuration on main: the field frame), drag, lift.
    Odd i drags right (re-extends) so the release really changes the trim like the field 47..60 s trims."""
    l, rr, y = ed._track_y()
    x0 = (l + rr) // 2 + r.randint(14, 26)
    dx = r.randint(40, 160) * (1 if i % 2 else -1)
    t0 = ed.log_mark()
    ed.dev.drag_no_fling(x0, y, x0 + dx, steps=r.randint(8, 16), hold=hold)
    ed.require_log(PRESS, timeout=15, since=t0, why=f'{why}: press -> MsgTrimVideo + getMediaDuration')
    if not ed.wait_log(RELEASE, 8, since=ed.log_mark()):
        ed.step(f'{why}: release left the trim unchanged (no-op revert, like field 22.879)')


def _scrub(ed, r, n):
    t0 = ed.log_mark()
    for _ in range(n):
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(50, 200))
    ed.require_log(r'VideoPlayer::seek requested', timeout=10, since=t0, why='scrub between trims')


def _setup_two_clips(ed, tag):
    _unlock(ed)
    ed.new_project(tag=tag, duration_s=60)
    ed.idle(4)
    ed.set_playing(False)
    t0 = ed.log_mark()
    ed.add_media(pick=0)                              # field: trimmed clip is media 6 behind another 60 s clip
    ed.require_log(r'MsgAddVideo: media_layer 0|transcode_session', timeout=60, since=t0, why='second clip')
    ed.idle(3)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_3_a(ed, r):
    """FULL: new project, 2 long clips; trim the last clip's END handle again and again with scrubs between."""
    _setup_two_clips(ed, 'g00fe1e6a')
    _select_last_clip(ed)
    for i in range(16):
        ed.step(f'inline trim {i + 1}/16')
        _trim(ed, r, i, r.uniform(0.2, 0.6), f'trim {i + 1}')
        ed.idle(r.uniform(0.8, 1.8))                  # field: next press 1-2 s after the release
        if i % 4 == 3:
            _scrub(ed, r, r.randint(3, 6))
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_3_b(ed, r):
    """HYBRID: lab test draft; pause via JNI, every END-handle press/release is a real touch."""
    _unlock(ed)
    ed.open_draft()
    ed.idle(8)                                        # taps before draft_project_complete are lost
    ed.jni('pausePlaying()')                          # HYBRID: field user was paused before every trim
    _select_last_clip(ed)
    for i in range(18):
        ed.step(f'inline trim {i + 1}/18')
        _trim(ed, r, i, r.uniform(0.1, 0.4), f'trim {i + 1}')
        ed.idle(r.uniform(0.6, 1.2))
        if i % 5 == 4:
            _scrub(ed, r, r.randint(5, 9))
            _select_last_clip(ed)
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_g00fe1e6_3_c(ed, r):
    """FULL: slow-phone variant; each press lands 0.1-0.4 s after a release, inside its trim_media render."""
    _setup_two_clips(ed, 'g00fe1e6c')
    _select_last_clip(ed)
    try:
        ed.dev.slow_phone(r.randint(35, 45))          # OPPO CPH2477: decoder gives no frame within 1 s
        ed.dev.busy_storage(True)
        ed.trim_memory('RUNNING_LOW')
        for i in range(20):
            ed.step(f'fast inline trim {i + 1}/20')
            _trim(ed, r, i, r.uniform(0.05, 0.2), f'fast trim {i + 1}')
            ed.idle(r.uniform(0.1, 0.4))              # press while the release's trim render is in get_frame
            if i % 6 == 5:
                _scrub(ed, r, r.randint(4, 8))
                _select_last_clip(ed)
        ed.settle(10)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)
