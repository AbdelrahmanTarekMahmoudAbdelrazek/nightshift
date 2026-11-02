# Night Shift auto repros for 2bc43cd6d24a25e5305f8167703618a8~e6a57918


# 2026-11-01 15:09 level 3 attempt 1
_GE_LOG_ADD = r'MsgAddVideo'


def _ge6a5791_tap_if(ed, sels, timeout=4):
    """Tap the first selector that shows (decorative steps: carry on when none does)."""
    end = time.time() + timeout
    while time.time() < end:
        s = ed.screen()
        for sel in sels:
            if s is not None and s.has(sel):
                ed.dev.tap(*s.find(sel).center)
                return True
        time.sleep(0.5)
    return False


def _ge6a5791_add_overlay(ed, tag, secs=18):
    """Overlay tab -> Add (ve_btn_overlay_add) -> newest gallery video (a fresh copy: real transcode + real mask build)."""
    ed.dev.fresh_video(tag, duration_s=secs)
    ed.main_nav()
    ed.tap_tool('ve_tab_overlay')
    mark = ed.log_mark()
    ed.tap_tool('ve_btn_overlay_add')
    _ge6a5791_tap_if(ed, ['id:tab_gallery'], 3)
    if not _ge6a5791_tap_if(ed, ['id:thumbnail', 'id:img', 'id:imageView'], 10):
        raise UIError('overlay picker showed no thumbnail')
    _ge6a5791_tap_if(ed, ['id:btn_done', 'id:next_button', 'text:Done'], 4)
    ed.require_log(_GE_LOG_ADD, 90, since=mark, why='checkpoint 1: video overlay added')
    ed.idle(2)


def _ge6a5791_start_build(ed, layer, media):
    """Remove BG -> Auto Removal on the selected overlay with a slow CPU, so the build streams for many seconds."""
    ed.tap_tool('ve_tab_overlay_remove_bg')
    ed.dev.slow_phone(30)
    mark = ed.log_mark()
    ed.tap_tool('ve_tab_remove_bg_auto')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media}', 30, since=mark,
                   why='checkpoint 2: native build on the field layer/media')
    ed.require_log(r'masks planned from', 20, since=mark, why='checkpoint 2: hundreds of masks planned')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks streaming')
    _ge6a5791_tap_if(ed, ['id:back'], 3)            # ve_back_tool_btn: back to the overlay tools, as in event 1


def _ge6a5791_find_bar(ed, x):
    """Tap down the timeline until a tap lands on an overlay bar (ve_timeline_overlay); returns its y."""
    w, h = ed._screen_size()
    s = ed.screen()
    cy = s.find('id:videoTrackView').center[1] if s is not None and s.has('id:videoTrackView') else int(h * 0.7)
    for y in range(int(cy - h * 0.10), int(cy + h * 0.16), int(h * 0.02)):
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        if ed.wait_log(r've_timeline_overlay', 2, since=mark):
            return y
    raise UIError('no overlay bar found on the timeline')


def _ge6a5791_drag_row(ed, x, y, want, dys):
    """Long-press the selected overlay bar and drop it on another row (applyLayerChange -> MsgChangeVisualMediaLayer)."""
    _, h = ed._screen_size()
    for k in dys:
        mark = ed.log_mark()
        ed.dev.long_drag(x, y, x, y + int(k * h * 0.045), hold=0.9, steps=20)
        if ed.wait_log(want, 4, since=mark):
            return y + int(k * h * 0.045)
    ed.require_log(want, 1, since=ed.log_mark(), why='checkpoint 5: overlay being built moved to another layer')


def _ge6a5791_delete_selected(ed):
    mark = ed.log_mark()
    ed.tap_tool('ve_btn_overlay_delete')
    ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 10, since=mark, why='checkpoint 4: overlay deleted')
    ed.require_log(r'RemoveBgTrack: frame=', 15, since=mark, why='checkpoint 4: build survived the delete')


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_1_a(ed, r):
    """Event 1 (09:02:50Z vivo V2424): build on layer 2 media 0, delete layer-1 overlay, drag the built overlay 2->1, slow CPU."""
    ed.set_playing(False)
    ed.dev.clear_app_cache()
    w, _ = ed._screen_size()
    try:
        _ge6a5791_add_overlay(ed, 'ge6a_a1')                     # A: layer 1 media 0
        _ge6a5791_add_overlay(ed, 'ge6a_a2')                     # B: layer 2 media 0, selected
        _ge6a5791_start_build(ed, 2, 0)
        ed.seek_swipe(-0.12, 150)                               # playhead inside both bars
        ya = _ge6a5791_find_bar(ed, w // 2)                     # first bar hit is A (row 1)
        ed.idle(r.uniform(0.5, 1.5))
        _ge6a5791_delete_selected(ed)
        ed.idle(r.uniform(2.5, 4.0))                            # field: move came ~4 s after the delete
        yb = _ge6a5791_find_bar(ed, w // 2)                     # only B is left
        y = _ge6a5791_drag_row(ed, w // 2, yb, r'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer 1', (-1, -2, 1))
        for _ in range(4):                                      # more moves while masks keep streaming
            ed.idle(r.uniform(0.3, 1.2))
            _ge6a5791_drag_row(ed, w // 2, y, r'MsgChangeVisualMediaLayer: media_id 0 old_layer', (1, -1))
            y = _ge6a5791_find_bar(ed, w // 2)
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_1_b(ed, r):
    """Event 2 (09:15:12Z vivo V2424): split overlay, build on layer 1 media 1, delete media 0 on the same layer, play, slow CPU."""
    ed.set_playing(False)
    ed.dev.clear_app_cache()
    w, _ = ed._screen_size()
    try:
        _ge6a5791_add_overlay(ed, 'ge6a_b1', secs=16)
        ed.seek_swipe(-0.25, 200)
        mark = ed.log_mark()
        ed.tap_tool('ve_btn_overlay_split')                     # right half selected = layer 1 media 1
        ed.require_log(r'MsgSplit|split', 10, since=mark, why='checkpoint 1: two overlays on layer 1')
        ed.idle(1.5)
        _ge6a5791_start_build(ed, 1, 1)
        ed.idle(r.uniform(2, 4))
        _ge6a5791_find_bar(ed, int(w * 0.30))                   # left half (media 0), left of the playhead
        _ge6a5791_delete_selected(ed)
        ed.idle(1.2)
        _ge6a5791_tap_if(ed, ['id:play'], 3)                    # ve_play_pause_btn -> MsgResumePlaying
        ed.idle(4)
        ed.set_playing(False)
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_1_c(ed, r):
    """Events 1+2 (vivo V2424): split, build on layer 1 media 1, delete media 0, then drag the built half 1<->2 under memory pressure."""
    ed.set_playing(False)
    ed.dev.clear_app_cache()
    w, _ = ed._screen_size()
    try:
        _ge6a5791_add_overlay(ed, 'ge6a_c1', secs=16)
        ed.seek_swipe(-0.25, 200)
        mark = ed.log_mark()
        ed.tap_tool('ve_btn_overlay_split')
        ed.require_log(r'MsgSplit|split', 10, since=mark, why='checkpoint 1: two overlays on layer 1')
        ed.idle(1.5)
        _ge6a5791_start_build(ed, 1, 1)
        ed.idle(r.uniform(2, 3))
        _ge6a5791_find_bar(ed, int(w * 0.30))
        _ge6a5791_delete_selected(ed)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(1.5, 3))
        y = _ge6a5791_find_bar(ed, int(w * 0.65))               # the half being built (now media 0)
        for _ in range(5):
            _ge6a5791_drag_row(ed, int(w * 0.65), y, r'MsgChangeVisualMediaLayer: media_id 0 old_layer', (1, -1, 2))
            ed.idle(r.uniform(0.3, 1.0))
            y = _ge6a5791_find_bar(ed, int(w * 0.65))
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 15:21 level 3 attempt 3
def _ge6a5791_after(line, key):
    """Number after `key` in an engine log line ('layer 2 media_id 0' -> 2)."""
    return int(line.split(key, 1)[1].split()[0])


def _ge6a5791_tap_if(ed, sels, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        s = ed.screen()
        for sel in sels:
            if s is not None and s.has(sel):
                ed.dev.tap(*s.find(sel).center)
                return True
        time.sleep(0.4)
    return False


def _ge6a5791_select(ed, x, y):
    """Tap one overlay bar on the timeline (onTimeLineClick, 1 s debounce) -> overlay tools; True if it was a bar."""
    ed.idle(1.1)
    mark = ed.log_mark()
    ed.dev.tap(x, y)
    return bool(ed.wait_log(r'(?i)ve_timeline_overlay', 2, since=mark))


def _ge6a5791_rows(ed, x):
    """y of every overlay row under x, top to bottom (the draft has one 20 s overlay on each of layers 1-4)."""
    w, h = ed._screen_size()
    s = ed.screen()
    cy = s.find('id:videoTrackView').center[1] if s is not None and s.has('id:videoTrackView') else int(h * 0.7)
    rows = []
    for y in range(int(cy - h * 0.15), int(cy + h * 0.15), int(h * 0.022)):
        if _ge6a5791_select(ed, x, y):
            if rows and y - rows[-1][-1] <= int(h * 0.03):
                rows[-1].append(y)
            else:
                rows.append([y])
    if len(rows) < 2:
        raise UIError(f'checkpoint 1: found {len(rows)} overlay rows on the timeline, need 2+')
    return [sum(g) // len(g) for g in rows]


def _ge6a5791_build(ed, media_re):
    """Selected overlay -> Remove BG -> Auto Removal on a slowed phone; returns the build's (layer, media)."""
    ed.tap_tool('ve_tab_overlay_remove_bg')
    ed.dev.slow_phone(30)
    mark = ed.log_mark()
    ed.tap_tool('ve_tab_remove_bg_auto')
    line = ed.require_log(r'MsgStartNativeRemoveBgBuild: layer [1-9]\d* media_id ' + media_re, 30, since=mark,
                          why='checkpoint 2: native build started on a video overlay')
    ed.require_log(r'masks planned from', 30, since=mark, why='checkpoint 2: real build (not a cache replay)')
    ed.require_log(r'RemoveBgTrack: frame=', 30, since=mark, why='checkpoint 3: masks streaming')
    _ge6a5791_tap_if(ed, ['id:back'])                         # ve_back_tool_btn, as in event 1
    return _ge6a5791_after(line, 'layer '), _ge6a5791_after(line, 'media_id ')


def _ge6a5791_delete(ed, layer_re):
    mark = ed.log_mark()
    ed.tap_tool('ve_btn_overlay_delete')
    _ge6a5791_tap_if(ed, ['id:firstBtn'], 2)                  # 'Delete Media?' sheet when it shows
    line = ed.require_log(r'MsgDeleteMedia: media_layer ' + layer_re + r' media_id 0', 10, since=mark,
                          why='checkpoint 4: another overlay deleted while the build runs')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 4: build survived the delete')
    return _ge6a5791_after(line, 'media_layer ')


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_3_a(ed, r):
    """Event 1 (10:02:50Z vivo V2424): build on an overlay layer, delete the neighbour layer's overlay, drag the built one onto that row (slow CPU, memory pressure)."""
    ed.set_playing(False)
    w, h = ed._screen_size()
    x = w // 2
    try:
        rows = _ge6a5791_rows(ed, x)
        k = 1 if len(rows) > 2 else 0
        yb, yd = rows[k], rows[k - 1] if k else rows[1]
        if not _ge6a5791_select(ed, x, yb):
            raise UIError('could not select the overlay to build')
        layer, _ = _ge6a5791_build(ed, '0')
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        ed.idle(r.uniform(2.0, 3.5))
        if not _ge6a5791_select(ed, x, yd):
            raise UIError('could not select the neighbour overlay')
        gone = _ge6a5791_delete(ed, r'\d+')
        ed.idle(r.uniform(2.5, 4.0))                          # field: move ~4 s after the delete
        src, dst, moved = layer, gone, 0
        for i in range(10):                                   # round trips: every move nulls the slot once
            y_from, y_to = (yb, yd) if src == layer else (yd, yb)
            if not _ge6a5791_select(ed, x, y_from):
                rows = _ge6a5791_rows(ed, x)
                continue
            mark = ed.log_mark()
            for dy in (0, -int(h * 0.04), int(h * 0.04)):
                ed.dev.long_drag(x, y_from, x, y_to + dy, hold=0.9, steps=20)
                if ed.wait_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {src} new_layer {dst}', 4, since=mark):
                    moved += 1
                    src, dst = dst, src
                    break
            ed.idle(r.uniform(0.2, 0.9))
        if not moved:
            ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {layer}', 1, since=ed.log_mark(),
                           why='checkpoint 5: built overlay moved to another layer while masks stream')
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_3_b(ed, r):
    """Event 2 (09:15:12Z vivo V2424): split an overlay, build on media 1, delete media 0 of the same layer, play (slow CPU)."""
    ed.set_playing(False)
    w, h = ed._screen_size()
    x = w // 2
    try:
        ed.seek_to(r.uniform(0.2, 0.3))                        # split early: media 1 keeps hundreds of frames
        y = _ge6a5791_rows(ed, x)[0]
        if not _ge6a5791_select(ed, x, y):
            raise UIError('could not select the overlay to split')
        mark = ed.log_mark()
        ed.tap_tool('ve_btn_overlay_split')
        ed.require_log(r'MsgSplit', 10, since=mark, why='checkpoint 1: two overlays on one layer (media 0, media 1)')
        ed.idle(1.5)
        if not _ge6a5791_select(ed, x + int(w * 0.15), y):     # right of the playhead = media 1
            raise UIError('could not select the right split piece')
        layer, _ = _ge6a5791_build(ed, '1')
        ed.idle(r.uniform(3.0, 5.0))                          # field: delete ~7 s into the build
        if not _ge6a5791_select(ed, x - int(w * 0.15), y):     # left piece = media 0, same layer
            raise UIError('could not select the left split piece')
        _ge6a5791_delete(ed, str(layer))                      # erase shifts the build's slot 1 -> 0
        ed.idle(r.uniform(0.5, 1.2))
        ed.ui.tap('id:play', timeout=5)                        # ve_play_pause_btn -> MsgResumePlaying
        ed.settle(6)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 15:38 level 4 attempt 1
def _ge6a5791_layer(line, key):
    """Number after `key` in an engine line ('media_layer 2 media_id 0' -> 2)."""
    return int(line.split(key, 1)[1].split()[0])


def _ge6a5791_split(ed, x, y):
    """Select the overlay under (x, y) and Split it at the playhead; returns its layer, or None when no split reached the engine."""
    ed.dev.tap(x, y)
    ed.idle(0.6)
    mark = ed.log_mark()
    ed.tap_tool('split')
    line = ed.wait_log(r'MsgSplitVideo: media_layer [1-9]\d* media_id 0', 2.5, since=mark)
    return _ge6a5791_layer(line, 'media_layer ') if line else None


def _ge6a5791_setup(ed, r, from_bottom):
    """Draft loaded -> playhead a few s into the overlays -> Overlay tab -> split the first overlay row that answers.
    Returns (x_left_piece, x_right_piece, y_row, row_pitch, layer)."""
    ed.wait_log(r've_draft_project_complete', 12)          # overlays load 6-8 s after resume; earlier taps are lost
    ed.idle(1.5)
    ed.set_playing(False)
    ed.seek_swipe(-r.uniform(0.2, 0.3), 400)               # forward: the split point (overlays run from 0 s)
    ed.idle(1)
    ed.main_nav()
    ed.tap_tool('overlay')
    ed.idle(1.5)
    ed.ui.tap('id:deselect_button', timeout=2)
    w, h = ed._screen_size()
    nums = [int(t) for t in ed.dev.sh('wm density').split() if t.isdigit()]
    pitch = int(38 * (nums[-1] if nums else 440) / 160)    # overlay row: 36 dp + 2 dp margin (SliderLayout)
    s = ed.screen()
    cy = s.find('id:videoTrackView').center[1] if s is not None and s.has('id:videoTrackView') else int(h * 0.7)
    ys = list(range(int(cy - 0.12 * h), int(cy + 0.15 * h), max(20, pitch // 2)))
    xl, xr = int(w * 0.40), int(w * 0.60)                  # left / right piece around the playhead after the split
    for y in (reversed(ys) if from_bottom else ys):
        layer = _ge6a5791_split(ed, xr, y)
        if layer is not None:
            ed.idle(1.5)
            return xl, xr, y, pitch, layer
    ed.require_log(r'MsgSplitVideo: media_layer [1-9]', 1, since=ed.log_mark(),
                   why='checkpoint 1: two video pieces on one overlay layer (overlay split)')


def _ge6a5791_build(ed, x, y, layer, media):
    """Select the piece -> Remove BG -> AI Removal; require a real, streaming native build on (layer, media)."""
    ed.dev.tap(x, y)
    ed.idle(0.8)
    mark = ed.log_mark()
    ed.tap_tool('remove bg')
    ed.tap_tool('ai removal')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media}\b', 40, since=mark,
                   why='checkpoint 2: native build on the field layer/media')
    ed.require_log(r'masks planned from', 30, since=mark, why='checkpoint 2: real build, not a cache replay')
    ed.require_log(r'RemoveBgTrack: frame=', 30, since=mark, why='checkpoint 3: masks streaming')
    ed.main_nav()                                          # field: ve_back_tool_btn, the build keeps running
    ed.tap_tool('overlay')
    ed.idle(0.8)


def _ge6a5791_delete(ed, x, y, pattern, why):
    ed.dev.tap(x, y)
    ed.idle(0.8)
    mark = ed.log_mark()
    ed.tap_tool('delete')
    ed.ui.tap('id:firstBtn', timeout=2)                    # 'Delete Media?' sheet when it shows
    ed.require_log(pattern, 10, since=mark, why=why)
    ed.require_log(r'MySurfaceTexture: destructor called|AudioMCDecoder - Destructor called', 6, since=mark,
                   why='checkpoint 4: the deleted media is really destroyed')
    return mark


def _ge6a5791_event2(ed, r, rows, slow, wait):
    """Build on media 1 of a layer, delete media 0 of that layer mid-build: the erase empties slot 1 while media 0 is destroyed."""
    xl, xr, y0, pitch, layer = _ge6a5791_setup(ed, r, from_bottom=slow > 0)
    try:
        for k in range(rows):
            y = y0 + (-k if slow else k) * pitch
            if k and (layer := _ge6a5791_split(ed, xr, y)) is None:
                break
            ed.dev.slow_phone(slow)
            _ge6a5791_build(ed, xr, y, layer, 1)
            ed.idle(r.uniform(*wait))
            _ge6a5791_delete(ed, xl, y, rf'MsgDeleteMedia: media_layer {layer} media_id 0\b',
                             'checkpoint 4: media 0 deleted on the build layer while masks stream')
            ed.idle(r.uniform(0.3, 1.2))
            ed.set_playing(True)                           # field event 2: play right after the delete
            ed.settle(4)
            ed.set_playing(False)
            ed.dev.slow_phone(0)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_a(ed, r):
    """Event 2 (09:15:12Z vivo V2424): build on overlay layer L media 1, delete media 0 of L mid-build, play; up to 3 rows, full speed."""
    _ge6a5791_event2(ed, r, rows=3, slow=0, wait=(1.0, 3.0))


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_c(ed, r):
    """Event 2 (09:15:12Z vivo V2424) on a slow phone: delete media 0 right after the first masks of media 1's build, then play."""
    _ge6a5791_event2(ed, r, rows=2, slow=r.randint(20, 32), wait=(0.2, 1.0))


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_b(ed, r):
    """Event 1 (10:02:50Z vivo V2424): build on layer L media 0, delete the neighbour overlay, drag the built layer's pieces 2->1 and back, slow CPU."""
    xl, xr, yL, pitch, L = _ge6a5791_setup(ed, r, from_bottom=True)   # last overlay row: a neighbour row sits above
    try:
        ed.dev.slow_phone(r.randint(22, 34))               # field-speed masks; a preempted looper holds the moved-out slot longer
        _ge6a5791_build(ed, xl, yL, L, 0)
        ed.idle(r.uniform(1.0, 2.5))
        mark = _ge6a5791_delete(ed, xr, yL - pitch, rf'MsgDeleteMedia: media_layer (?!{L}\b)\d+ media_id 0\b',
                                'checkpoint 4: the neighbour layer overlay deleted while the build runs')
        ed.require_log(r'RemoveBgTrack: frame=', 15, since=mark, why='checkpoint 4: build survived the delete')
        ed.idle(r.uniform(2.0, 3.5))                       # field: move ~4 s after the delete
        pos, order, pair, M = {'l': xl, 'r': xr}, ['l', 'r'], None, None
        for i in range(8):                                 # the piece at (L,0) leaves and comes back: L never empties
            x = pos[order[0]]
            mark = ed.log_mark()
            line = ''
            for a, b in ([pair] if pair else [(yL, yL - pitch), (yL, yL + pitch), (yL - pitch, yL - 2 * pitch)]):
                ed.dev.long_drag(x, a, x, b, hold=0.8, steps=12)
                line = ed.wait_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {L} new_layer \d+', 3, since=mark)
                if line:
                    pair, M = (a, b), _ge6a5791_layer(line, 'new_layer ')
                    break
            if not line:
                if i == 0:
                    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {L}', 1, since=mark,
                                   why='checkpoint 5: the built overlay moved to another layer mid-build')
                break
            ed.idle(r.uniform(0.2, 0.6))
            mark = ed.log_mark()
            ed.dev.long_drag(x, pair[1], x, pair[0], hold=0.8, steps=12)
            if not ed.wait_log(rf'MsgChangeVisualMediaLayer: media_id \d+ old_layer {M} new_layer {L}', 3, since=mark):
                break
            order = order[1:] + order[:1]                  # pushed back behind the other piece
            ed.idle(r.uniform(0.2, 0.6))
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 15:46 level 4 attempt 2
def _ge6a5791_n(line, key):
    """Number after `key` in an engine line ('old_layer 2 new_layer 1' -> 2)."""
    return int(line.split(key, 1)[1].split()[0])


def _ge6a5791_tile(ed, desc, name=None):
    """Bottom-bar tile by automation tag; label fallback only where a wrong tile cannot hurt."""
    try:
        ed.ui.tap(f'desc:{desc}', timeout=3)
        return True
    except UIError:
        if name:
            ed.tap_tool(name)
            return True
        return False


def _ge6a5791_sel(ed, x, y):
    """Tap an overlay bar (1 s click debounce); True when the app logs it as an overlay click."""
    ed.idle(1.1)
    mark = ed.log_mark()
    ed.dev.tap(x, y)
    return bool(ed.wait_log(r've_timeline_overlay', 2, since=mark))


def _ge6a5791_rows(ed, seek=0.0):
    """Open the overlay timeline (the draft has one 20 s overlay on each of layers 1-4); returns (x, y of first row, pitch)."""
    ed.idle(2)
    ed.set_playing(False)
    if seek:
        ed.seek_swipe(-seek, 400)
        ed.idle(1)
    ed.main_nav()
    ed.tap_tool('overlay')
    ed.idle(1.5)
    w, h = ed._screen_size()
    nums = [int(t) for t in ed.dev.sh('wm density').split() if t.isdigit()]
    pitch = int(38 * (nums[-1] if nums else 440) / 160)     # SliderLayout row: 36 dp + 2 dp margin
    x = int(w * 0.62)                                        # right of the playhead, inside the overlays
    s = ed.screen()
    ys = [s.find('id:range_slider').center[1]] if s is not None and s.has('id:range_slider') else []
    cy = s.find('id:videoTrackView').center[1] if s is not None and s.has('id:videoTrackView') else int(h * 0.7)
    ys += list(range(int(cy - 0.08 * h), int(cy + 0.25 * h), max(20, pitch // 2)))
    for y in ys:
        if _ge6a5791_sel(ed, x, y + pitch // 4):
            return x, y + pitch // 4, pitch
    raise UIError('checkpoint 1: no overlay bar answered a tap on the overlay timeline')


def _ge6a5791_build(ed, media_re=r'\d+'):
    """Selected overlay -> Remove BG -> AI Removal, source mtime bumped so the mask cache misses; returns (layer, media)."""
    ed.dev.sh("run-as com.myzesty sh -c 'touch files/outputs/*.mp4'")
    mark = ed.log_mark()
    _ge6a5791_tile(ed, 've_tab_overlay_remove_bg', 'remove bg')
    ed.idle(0.8)
    _ge6a5791_tile(ed, 've_tab_remove_bg_auto', 'auto removal')
    pat = r'MsgStartNativeRemoveBgBuild: layer [1-9]\d* media_id ' + media_re + r'\b'
    line = ed.wait_log(pat, 40, since=mark) or ed.require_log(pat, 1, since=mark, why='checkpoint 2: native build on a video overlay')
    ed.require_log(r'masks planned from', 30, since=mark, why='checkpoint 2: real build, not a cache replay')
    ed.require_log(r'RemoveBgTrack: frame=|setMask key=removebg_mask_', 30, since=mark, why='checkpoint 3: masks streaming')
    return _ge6a5791_n(line, 'layer '), _ge6a5791_n(line, 'media_id ')


def _ge6a5791_delete(ed, x, y, layer_re=r'[1-9]\d*'):
    """Select the bar at (x, y) and delete it mid-build; returns (layer, media) of the MsgDeleteMedia."""
    if not _ge6a5791_sel(ed, x, y):
        raise UIError('checkpoint 4: overlay to delete did not answer')
    mark = ed.log_mark()
    if not _ge6a5791_tile(ed, 've_btn_overlay_delete'):
        ed.dev.key('KEYCODE_BACK')                           # ve_back_tool_btn: Remove BG tiles -> overlay tiles
        ed.idle(0.6)
        _ge6a5791_tile(ed, 've_btn_overlay_delete')
    try:
        ed.ui.tap('id:firstBtn', timeout=1.5)                # 'Delete Media?' sheet when it shows
    except UIError:
        pass
    pat = rf'MsgDeleteMedia: media_layer {layer_re} media_id \d+'
    line = ed.wait_log(pat, 10, since=mark) or ed.require_log(pat, 1, since=mark, why='checkpoint 4: overlay deleted mid-build')
    ed.require_log(r'MySurfaceTexture: destructor called|AudioMCDecoder - Destructor called', 6, since=mark,
                   why='checkpoint 4: deleted media really destroyed')
    ed.require_log(r'RemoveBgTrack: frame=|setMask key=removebg_mask_', 20, since=mark, why='checkpoint 4: build survived the delete')
    return _ge6a5791_n(line, 'media_layer '), _ge6a5791_n(line, 'media_id ')


def _ge6a5791_move(ed, x, y_from, y_to, pitch, media, layer):
    """Long-press the built bar and drop it on another row; returns its new layer or None."""
    for dst in (y_to, y_to + pitch // 3, y_to - pitch // 3):
        if not _ge6a5791_sel(ed, x, y_from):
            return None
        mark = ed.log_mark()
        ed.dev.long_drag(x, y_from, x, dst, hold=0.9, steps=16)
        line = ed.wait_log(rf'MsgChangeVisualMediaLayer: media_id {media} old_layer {layer} new_layer \d+', 3, since=mark)
        if line:
            return _ge6a5791_n(line, 'new_layer ')
    return None


def _ge6a5791_event1(ed, r, slow, wait_del, wait_move, trips):
    x, y0, p = _ge6a5791_rows(ed)
    yb = y0 + p                                              # second row: layer 2 in the field shape
    if not _ge6a5791_sel(ed, x, yb):
        yb = y0
    try:
        ed.dev.slow_phone(slow)
        layer, media = _ge6a5791_build(ed)
        ed.seek_swipe(r.uniform(0.05, 0.15), 300)            # field: scrubs while masks stream
        ed.idle(r.uniform(*wait_del))
        yd = yb - p if yb > y0 else yb + p                   # neighbour row (field: layer 1)
        _ge6a5791_delete(ed, x, yd)
        ed.idle(r.uniform(*wait_move))
        ys, cur, moved = {layer: yb}, layer, 0
        for i in range(trips):                               # every move empties the built slot once
            back = [l for l in ys if l != cur]
            y_to = ys[back[0]] if back else yd
            new = _ge6a5791_move(ed, x, ys[cur], y_to, p, media, cur)
            if new is None:
                break
            ys[new], cur, moved = y_to, new, moved + 1
            ed.idle(r.uniform(0.05, 0.4))
        if not moved:
            ed.require_log(rf'MsgChangeVisualMediaLayer: media_id {media} old_layer {layer}', 1, since=ed.log_mark(),
                           why='checkpoint 5: built overlay moved to another layer mid-build')
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_2_a(ed, r):
    """Event 1 (2026-10-29T10:02:50Z vivo V2424): build on overlay layer 2, delete the layer-1 overlay ~4 s in, drag the built overlay onto row 1 ~4 s later (slowed CPU), then a few round trips."""
    _ge6a5791_event1(ed, r, slow=r.randint(18, 28), wait_del=(2.0, 3.5), wait_move=(2.5, 4.0), trips=4)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_2_b(ed, r):
    """Event 1 (2026-10-29T10:02:50Z vivo V2424) storm: delete the neighbour right after the first masks, then 10 back-to-back layer moves of the built overlay."""
    _ge6a5791_event1(ed, r, slow=r.randint(8, 14), wait_del=(0.2, 0.6), wait_move=(0.3, 0.8), trips=10)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_2_c(ed, r):
    """Event 2 (2026-10-29T09:15:12Z vivo V2424, Play V40 Lite): split an overlay, build on media 1, delete media 0 of that layer mid-build, play, then undo/redo the delete."""
    x, y, p = _ge6a5791_rows(ed, seek=r.uniform(0.2, 0.3))
    w, _ = ed._screen_size()
    mark = ed.log_mark()
    _ge6a5791_tile(ed, 've_btn_overlay_split')
    line = ed.require_log(r'MsgSplitVideo: media_layer [1-9]\d* media_id 0', 8, since=mark,
                          why='checkpoint 1: two pieces on one overlay layer')
    layer = _ge6a5791_n(line, 'media_layer ')
    ed.idle(1.5)
    try:
        ed.dev.slow_phone(r.randint(12, 24))
        if not _ge6a5791_sel(ed, int(w * 0.62), y):
            raise UIError('right piece of the split overlay did not answer')
        _ge6a5791_build(ed, media_re=r'[1-9]\d*')
        ed.idle(r.uniform(1.0, 3.0))
        _ge6a5791_delete(ed, int(w * 0.40), y, layer_re=str(layer))   # erase shifts the built slot 1 -> 0
        ed.idle(r.uniform(0.3, 1.2))
        ed.set_playing(True)                                 # field: ve_play_pause_btn -> MsgResumePlaying
        ed.idle(1.5)
        ed.set_playing(False)
        for _ in range(r.randint(3, 5)):                     # each undo/redo re-inserts / erases media 0 under the build
            ed.undo(1, 0.3)
            ed.redo(1, 0.3)
        ed.settle(5)
    finally:
        ed.dev.slow_phone(0)
