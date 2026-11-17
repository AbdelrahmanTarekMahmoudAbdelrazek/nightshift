# Night Shift: frozen copy of the registered repro ns_g00fe1e6_l5_1_b (1109203616); later runs cannot change it
# Night Shift auto repros for 501bb52658b63a6c0a32a5b8bbd06b8b~00fe1e6d


# 2026-11-09 20:25 level 5 attempt 1
# Night Shift: ns_g00fe1e6 level 5. Hook debug.zesty.hook.stall_codec in MCDecoder::send_packet:
# "1" = the codec hands out no input buffer, so every trim redraw pumps to the 1 s TRYAGAIN timeout (hypothesis B);
# "hang" = AMediaCodec_dequeueInputBuffer does not return (hypothesis A, the engine frame in 4/4 field dumps).
_G00_HOOK = 'debug.zesty.hook.stall_codec'


def _g00fe1e6_arm(ed, handle, first=False):
    """Clip edge under the playhead. A press on its handle runs onMediaTrackStartTouch -> trimVideo + getMediaDurationByID."""
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
                               why='checkpoint 1: one 10-99 s video clip on layer 0, trim handle press reaches the engine')
            ed.idle(1.2)
            return cx + dx, y
        ed.dev.tap(body, y)                                  # not selected: select the clip body, try again
        ed.idle(0.8)
    raise UIError(f'inline trim {handle} handle not found at the playhead')


def _g00fe1e6_trims(ed, r, handle, x, y, n, taps=0):
    """Field cadence: drag in / release, drag out / release (two ranges, about 1 s apart); taps = extra handle presses."""
    d = (1 if handle == 'start' else -1) * r.randint(90, 150)
    m = ed.log_mark()
    for i in range(n):
        if taps:
            ed.dev.sh('; '.join([f'input tap {x} {y}'] * taps))
        ed.dev.drag_no_fling(x, y, x + (d if i % 2 == 0 else -d), steps=2, hold=r.uniform(0.02, 0.1))
        if i == 1:
            ed.require_log(r've_trim_complete', 5, since=m, why='checkpoint 4: release -> processTrim')
    return m


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_a_r1109203616(ed, r):
    """Firebase 2026-10-22 + 2026-10-23 (1.25.1, start handle 0 <-> ~8 s): codec stops giving frames (hook=1), every trim redraw times out 1 s, release loop piles up."""
    ed.open_fixture('g00fe1e6')
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    _g00fe1e6_trims(ed, r, 'start', x, y, 2)                     # natural trims first: codec still healthy
    ed.idle(1.5)
    ed.dev.setprop(_G00_HOOK, '1')
    try:
        ed.idle(0.4)
        m = _g00fe1e6_trims(ed, r, 'start', x, y, 3)
        ed.require_log(r'MCDecoder::get_frame timed out \(TRYAGAIN\)', 4, since=m,
                       why='checkpoint 2: trim redraw pumps to the 1 s timeout')
        _g00fe1e6_trims(ed, r, 'start', x, y, r.randint(8, 12), taps=r.randint(1, 2))
        ed.settle(14)
    finally:
        ed.dev.setprop(_G00_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_b_r1109203616(ed, r):
    """Firebase 2026-11-09 (1.26.0, end handle, release path): dequeueInputBuffer hangs (hook=hang) on a trim redraw, the release's sync getMediaDuration waits."""
    ed.open_fixture('g00fe1e6')
    x, y = _g00fe1e6_arm(ed, 'end', first=True)
    m = _g00fe1e6_trims(ed, r, 'end', x, y, r.randint(3, 5))     # field: several finished end-handle trims first
    ed.idle(1.5)
    ed.dev.setprop(_G00_HOOK, 'hang')
    try:
        ed.idle(0.5)
        m = ed.log_mark()
        ed.dev.drag_no_fling(x, y, x - r.randint(90, 150), steps=2, hold=0.05)   # release: SetVideoSpeed + Trim + 2x Get
        ed.require_log(r'NS_HOOK stall_codec: dequeueInputBuffer blocked', 5, since=m,
                       why='checkpoint 2: engine thread stuck in send_packet on the trim redraw')
        ed.dev.sh(f'input tap {x} {y}; input tap {x} {y}')       # next handle press queues behind the blocked main thread
        ed.settle(14)
    finally:
        ed.dev.setprop(_G00_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_l5_1_c_r1109203616(ed, r):
    """Play sample 1.25.1 (onMediaTrackStartTouch): codec hangs (hook=hang), then a start-handle PRESS sends trimVideo and blocks in getMediaDurationByID."""
    ed.open_fixture('g00fe1e6')
    x, y = _g00fe1e6_arm(ed, 'start', first=True)
    _g00fe1e6_trims(ed, r, 'start', x, y, 2)
    ed.idle(1.5)
    ed.dev.setprop(_G00_HOOK, 'hang')
    try:
        ed.idle(0.5)
        m = ed.log_mark()
        ed.dev.drag_no_fling(x, y, x, steps=1, hold=0.1)          # press only: onMediaTrackStartTouch path
        ed.require_log(r'MsgTrimVideo: media_layer 0 ', 4, since=m, why='checkpoint 4: press sends MsgTrimVideo')
        ed.require_log(r'NS_HOOK stall_codec: dequeueInputBuffer blocked', 5, since=m,
                       why='checkpoint 2: engine thread stuck in send_packet on the trim redraw')
        ed.dev.sh('; '.join([f'input tap {x} {y}'] * 3))
        ed.settle(14)
    finally:
        ed.dev.setprop(_G00_HOOK, '0')
