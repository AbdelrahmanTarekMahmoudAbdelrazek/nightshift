# Night Shift: frozen copy of the registered repro tf_2fe03193_1_a (1103172655); later runs cannot change it
# Night Shift tap repros for 2fe03193209d272d69500de7526df59f (from the engine repro + full field log)


# 2026-11-03 17:25 attempt 1
def _since_tap(ed, sel_name):
    mark = ed.log_mark()
    ed.menu_tap(sel_name)
    return mark


def _drag_canvas(ed, r, n):
    """Field: canvas drags on the preview in the Edit tab -> MsgApplyFreeShift layer 0 id 0."""
    s = ed.screen()
    box = s.find('id:surface_view') if s is not None else None
    if box is None:
        box = s.find('id:surface_area') if s is not None else None
    l, t, rr, b = box.b
    cx, cy = (l + rr) // 2, (t + b) // 2
    for _ in range(n):
        mark = ed.log_mark()
        dx, dy = r.randint(-(rr - l) // 4, (rr - l) // 4), r.randint(-(b - t) // 8, (b - t) // 8)
        ed.dev.swipe(cx, cy, cx + dx, cy + dy, r.randint(300, 900))
        ed.require_log(r'MsgApplyFreeShift: media_layer 0 media_id 0', timeout=6, since=mark, why='canvas drag')
        ed.idle(r.uniform(0.3, 1.0))


def _edit_tab(ed):
    ed.main_nav()
    mark = _since_tap(ed, 'edit')
    ed.require_log(r've_edit_tool_btn|MsgApplyFreeShift: media_layer 0 media_id 0', timeout=8, since=mark, why='Edit tab')
    ed.idle(1)


def _reverse_trigger(ed, cached=True):
    """Reverse tap: speed 1, curve 0, trim, then (cached branch) MsgReplaceVideo to cache/<name>."""
    ed.step('TRIGGER: Reverse on clip 0')
    mark = _since_tap(ed, 'reverse')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0, id 0', timeout=8, since=mark, why='Reverse -> setVideoSpeed(1)')
    ed.require_log(r'MsgSetMediaCurveSpeed layer 0 media_id 0 index 0', timeout=8, since=mark, why='Reverse -> curve 0')
    ed.require_log(r'MsgTrimVideo: media_layer 0 media_id 0 start_time 0', timeout=8, since=mark, why='Reverse -> trim')
    if cached:
        ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=10, since=mark,
                       why='Reverse cached branch -> replaceMedia(video-only cache file)')
    return mark


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_a_r1103172655(ed, r):
    """FULL: Crashlytics [libmedia.so] AudioMCDecoder::reset_state: Edit tab, canvas drags, Reverse on a clip whose cached reversed copy has no audio."""
    ed.open_fixture('2fe03193')
    ed.idle(8)                                        # wait for the draft to finish loading
    ed.set_playing(False)
    for _ in range(r.randint(2, 4)):                  # field: timeline scrubs before the Edit tab
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(0.2, 0.8), r.randint(150, 500))
        ed.require_log(r'VideoPlayer::seek requested', timeout=6, since=mark, why='timeline seek')
        ed.idle(r.uniform(0.3, 0.8))
    _edit_tab(ed)
    _drag_canvas(ed, r, r.randint(4, 8))
    _reverse_trigger(ed)
    ed.idle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_b_r1103172655(ed, r):
    """HYBRID: Crashlytics [libmedia.so] AudioMCDecoder::reset_state: real Reverse fills cache/<name>, Undo restores the original, Reverse again takes the cached video-only file."""
    ed.open_draft()                                   # HYBRID: lab test draft instead of the field's project
    ed.idle(8)
    ed.set_playing(False)
    _edit_tab(ed)
    _drag_canvas(ed, r, 2)
    ed.step('first Reverse: real reverse transcode into cache/<clip name>')
    mark = _since_tap(ed, 'reverse')
    ed.require_log(r'MsgReverseVideo|MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=15,
                   since=mark, why='first Reverse writes/uses the cache file')
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path \S*/cache/', timeout=240, since=mark,
                   why='first Reverse swaps in the reversed copy')
    ed.wait_loader(60)
    ed.idle(2)
    ed.step('Undo: back to the original clip (handleOriginal)')
    mark = ed.log_mark()
    ed.undo(1)
    ed.require_log(r'MsgReplaceVideo: media_layer 0 media_id 0 path (?!\S*/cache/)\S+', timeout=15, since=mark,
                   why='Undo restores the original (with audio)')
    ed.idle(2)
    _edit_tab(ed)
    _drag_canvas(ed, r, r.randint(2, 4))
    _reverse_trigger(ed)
    ed.idle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_2fe03193_1_c_r1103172655(ed, r):
    """FULL: Crashlytics [libmedia.so] AudioMCDecoder::reset_state: field path on a slow phone with playback and seeks around the canvas drags, then Reverse."""
    ed.open_fixture('2fe03193')
    ed.idle(10)
    ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')
    ed.dev.slow_phone(30)
    try:
        ed.set_playing(True)                          # field: playback with seeks while playing
        ed.idle(r.uniform(2, 4))
        for _ in range(r.randint(2, 3)):
            mark = ed.log_mark()
            ed.seek_swipe(r.uniform(0.2, 0.9), r.randint(100, 300))
            ed.require_log(r'VideoPlayer::seek requested', timeout=8, since=mark, why='seek during playback')
            ed.idle(r.uniform(0.3, 0.8))
        ed.set_playing(False)
        _edit_tab(ed)
        _drag_canvas(ed, r, r.randint(6, 10))
        _reverse_trigger(ed)
        ed.idle(10)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')
