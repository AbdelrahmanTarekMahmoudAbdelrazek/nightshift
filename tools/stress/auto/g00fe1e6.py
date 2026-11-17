# Night Shift auto repros for 501bb52658b63a6c0a32a5b8bbd06b8b~00fe1e6d


# 2026-11-10 14:23 level 5 attempt 1
_G00FE1E6_HOOK = 'debug.zesty.hook.codec_stall'   # 1 = dequeueInputBuffer hangs, 2 = codec gives no input slot


def _g00fe1e6_arm(ed, handle):
    """Clip edge under the playhead; a press on its handle = onMediaTrackStartTouch -> trimVideo + getMediaDurationByID."""
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
            ed.require_log(r'MsgGetMediaDuration: media_layer 0 media_id: ?\d+, original: \d{8},', 6, since=m,
                           why='checkpoint 1: one 10-99 s video clip on layer 0, trim handle pressed')
            ed.idle(1.2)
            return cx + dx, y
        ed.dev.tap(body, y)                                  # not selected: select the clip body, try again
        ed.idle(0.8)
    raise UIError(f'inline trim {handle} handle not found at the playhead')


def _g00fe1e6_open(ed, handle):
    m = ed.log_mark()
    ed.open_fixture('g00fe1e6')                              # 30 s clip, layer 0, untrimmed, speed 1.0
    ed.wait_log(r'test_ve_draft_project_complete', 20, since=m)   # taps before the draft finished loading are lost
    ed.idle(2)
    return _g00fe1e6_arm(ed, handle)


def _g00fe1e6_stalled_trims(ed, r, x, y, inward, n, gap=(0.9, 1.3)):
    """Codec gives no input slot (hook=2): drag in / release, drag out / release ~1 s apart; each trim redraw times out."""
    ed.dev.setprop(_G00FE1E6_HOOK, '2')
    d = inward * r.randint(90, 150)
    m = ed.log_mark()
    for i in range(n):
        ed.dev.drag_no_fling(x, y, x + (d if i % 2 == 0 else -d), steps=2, hold=r.uniform(0.05, 0.15))
        time.sleep(r.uniform(*gap))
    ed.require_log(r've_trim_complete', 4, since=m, why='checkpoint 1/4: release -> processTrim')
    ed.require_log(r'MsgSetVideoSpeed: speed 1\.0+, layer 0', 4, since=m, why='checkpoint 4: release sends SetVideoSpeed(1.0)')
    ed.require_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 4, since=m,
                   why='checkpoints 2-3: trim redraw pumps the stalled codec to the 1 s timeout')
    return d


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_a(ed, r):
    """Firebase 2026-10-22 + 2026-10-23 (1.25.1) + Play samples: start-handle trims on a stalled codec, then a handle PRESS (onMediaTrackStartTouch -> getMediaDuration) while dequeueInputBuffer hangs."""
    x, y = _g00fe1e6_open(ed, 'start')
    try:
        _g00fe1e6_stalled_trims(ed, r, x, y, +1, r.randint(4, 6))
        ed.dev.setprop(_G00FE1E6_HOOK, '1')                  # codec now hangs inside the call (field wait chain)
        ed.dev.drag_no_fling(x, y, x, steps=1, hold=0.1)     # press: trimVideo -> redraw hangs; sync getMediaDuration waits
        ed.settle(12)
    finally:
        ed.dev.setprop(_G00FE1E6_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_b(ed, r):
    """Firebase 2026-11-09 (1.26.0): end-handle trims alternating full/trimmed length, codec hangs mid-drag, the RELEASE (processTrim -> getMediaDuration) blocks."""
    x, y = _g00fe1e6_open(ed, 'end')
    try:
        d = _g00fe1e6_stalled_trims(ed, r, x, y, -1, r.randint(5, 7))
        m = ed.log_mark()
        ed.dev.sh(f'input motionevent DOWN {x} {y}; input motionevent MOVE {x + d // 2} {y}')
        ed.require_log(r'MsgGetMediaDuration: media_layer 0 ', 4, since=m, why='press answered before the codec hangs')
        ed.dev.setprop(_G00FE1E6_HOOK, '1')
        ed.dev.sh(f'input motionevent MOVE {x + d} {y}; sleep 0.1; input motionevent UP {x + d} {y}')
        ed.settle(12)                                        # release: SetVideoSpeed + TrimVideo + sync getMediaDuration
    finally:
        ed.dev.setprop(_G00FE1E6_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_c(ed, r):
    """Firebase 2026-10-23 (1.25.1) cadence, hypothesis B only: codec gives no input slot (no hang), press bursts into 1 s trim redraws on a slow CPU until the waits add up."""
    x, y = _g00fe1e6_open(ed, 'start')
    try:
        _g00fe1e6_stalled_trims(ed, r, x, y, +1, r.randint(3, 5))
        ed.dev.slow_phone(44)
        for _ in range(r.randint(10, 14)):                   # press + release bursts: trimVideo + getMediaDuration each
            ed.dev.sh('; '.join([f'input tap {x} {y}'] * r.randint(2, 4)))
            ed.dev.drag_no_fling(x, y, x + r.randint(90, 150), steps=2, hold=0.05)
            time.sleep(r.uniform(0.0, 0.15))
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.setprop(_G00FE1E6_HOOK, '0')
