# Night Shift tap repros for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (from the engine repro + full field log)


# 2026-11-02 22:13 attempt 1
# Crashlytics ge6a5791: Remove BG mask sink vs overlay row drag (changeVisualMediaLayer) -> SIGSEGV in append_remove_bg_track_mask.

MASKS_GE6 = '/sdcard/Android/data/com.myzesty/files'
MOVE_RE = r'MsgChangeVisualMediaLayer: media_id \d+ old_layer \d+ new_layer \d+'


def _ge6_bars(ed):
    """Overlay bars on the timeline (id:range_slider), top to bottom."""
    s = ed.screen()
    bars = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if len(bars) < 2:
        raise UIError(f'fixture ge6a5791 needs 2 overlay rows, timeline shows {len(bars)}')
    return bars


def _ge6_hit(ed, node, why):
    """Tap a bar between its thumbs like a user until the app logs ve_timeline_overlay; returns (x, y)."""
    L, T_, R, B = node.b
    y = (T_ + B) // 2
    for x in range(L + 24, R - 10, max(30, (R - L) // 8)):
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        if ed.wait_log(r've_timeline_overlay', 2.5, mark):
            return x, y
        time.sleep(1.1)
    ed.require_log(r've_timeline_overlay', 1, ed.log_mark(), why=why)   # stops the run with the reason


def _ge6_ui_build(ed, x, y):
    """Select overlay B, Remove BG -> Auto: the app's own build. Returns the build's layer."""
    _ge6_hit(ed, type('N', (), {'b': (x - 30, y - 5, x + 30, y + 5)})(), 'select overlay B for Remove BG')
    if not ed.ui.tap('desc:ve_tab_overlay_remove_bg', timeout=6):
        ed.tap_tool('remove bg')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=10) is None:
        raise UIError('Remove BG panel (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    line = ed.require_log(r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+', 20, mark, why='Remove BG Auto starts the build')
    ed.require_log(r'masks planned from', 10, mark, why='a real (uncached) build: masks must stream during the drag')
    ed.require_log(r'BGFX setMask key=removebg_mask_', 20, mark, why='first masks stream into the track')
    return int(str(line).split('layer ', 1)[1].split()[0])


def _ge6_delete_a(ed, a):
    """Select overlay A and delete it (field: MsgDeleteMedia on the other layer, build not cancelled)."""
    _ge6_hit(ed, a, 'select overlay A')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_delete', timeout=8)
    s = ed.screen()
    if s is not None and s.has('id:firstBtnTv'):
        ed.dev.tap(*s.find('id:firstBtnTv').center)
    ed.require_log(r'MsgDeleteMedia: media_layer \d+ media_id \d+', 10, mark, why='delete overlay A')
    ed.dev.key('KEYCODE_BACK')                                  # field: ve_back_tool_btn


def _ge6_drag(ed, x, y1, y2, why):
    """Long-press B's bar and drop it on another row: applyLayerChange -> moveItemToLayer -> changeVisualMediaLayer."""
    mark = ed.log_mark()
    ed.dev.long_drag(x, y1, x, y2, hold=0.8, steps=12)
    ed.require_log(MOVE_RE, 8, mark, why=why)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_a(ed, r):
    """FULL: Crashlytics ge6a5791: Remove BG on overlay B, delete overlay A, drag B onto A's row mid-build."""
    ed.open_fixture('ge6a5791')
    ed.require_log(r'test_ve_draft_project_complete|MsgAddVideo: media_layer [1-9]', 30, why='fixture overlays loaded')
    ed.idle(3)
    ed.set_playing(False)
    ed.dev.key('KEYCODE_BACK')
    ed.tap_tool('overlay')
    b, a = _ge6_bars(ed)[-1], _ge6_bars(ed)[0]                  # B above A
    xb, yb = _ge6_hit(ed, b, 'overlay B row answers')
    ya = (a.b[1] + a.b[3]) // 2
    _ge6_ui_build(ed, xb, yb)
    _ge6_delete_a(ed, a)
    ed.idle(r.uniform(0.5, 2.0))
    for k in range(3):
        ed.step(f'drag B onto the free row while masks stream ({k + 1}/3)')
        _ge6_drag(ed, xb, yb, ya, 'B row drag -> changeVisualMediaLayer (trigger)')
        ed.idle(3)
        _ge6_drag(ed, xb, ya, yb, 'B back to its row')
        ed.idle(1)
        _ge6_ui_build(ed, xb, yb)
        ed.idle(r.uniform(0.5, 2.0))
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_b(ed, r):
    """HYBRID: Crashlytics ge6a5791: build started by engine call, overlay A deleted and B dragged by real taps."""
    ed.open_fixture('ge6a5791')
    ed.require_log(r'test_ve_draft_project_complete|MsgAddVideo: media_layer [1-9]', 30, why='fixture overlays loaded')
    ed.idle(3)
    ed.set_playing(False)
    ed.dev.key('KEYCODE_BACK')
    ed.tap_tool('overlay')
    bars = _ge6_bars(ed)
    b, a = bars[-1], bars[0]
    xb, yb = _ge6_hit(ed, b, 'overlay B row answers')
    ya = (a.b[1] + a.b[3]) // 2
    _ge6_delete_a(ed, a)
    for k in range(6):
        ed.step(f'jni build on B, then real drag ({k + 1}/6)')
        mark = ed.log_mark()
        layer = 1 if k % 2 else 2       # B sits on the row it was last dropped on
        ed.jni(f'startNativeRemoveBgBuild(0,1,{MASKS_GE6},{layer});sleep(800);nativeRemoveBgBuildProgress()')  # HYBRID
        ed.require_log(r'MsgStartNativeRemoveBgBuild: layer \d+ media_id 0', 15, mark, why='build started (HYBRID)')
        ed.require_log(r'BGFX setMask key=removebg_mask_|RemoveBgTrack: frame=', 20, mark, why='masks streaming')
        y1, y2 = (yb, ya) if k % 2 == 0 else (ya, yb)
        _ge6_drag(ed, xb, y1, y2, 'B row drag -> changeVisualMediaLayer (trigger)')
        ed.idle(3)
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_c(ed, r):
    """FULL: Crashlytics ge6a5791: the field path on a slow phone (wider move window on the looper), more tries."""
    ed.open_fixture('ge6a5791')
    ed.require_log(r'test_ve_draft_project_complete|MsgAddVideo: media_layer [1-9]', 30, why='fixture overlays loaded')
    ed.idle(3)
    ed.set_playing(False)
    ed.dev.key('KEYCODE_BACK')
    ed.tap_tool('overlay')
    bars = _ge6_bars(ed)
    b, a = bars[-1], bars[0]
    xb, yb = _ge6_hit(ed, b, 'overlay B row answers')
    ya = (a.b[1] + a.b[3]) // 2
    _ge6_ui_build(ed, xb, yb)
    _ge6_delete_a(ed, a)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        for k in range(5):
            ed.step(f'slow phone: drag B onto the free row mid-build ({k + 1}/5)')
            ed.idle(r.uniform(0.3, 1.5))
            _ge6_drag(ed, xb, yb, ya, 'B row drag -> changeVisualMediaLayer (trigger)')
            ed.idle(3)
            _ge6_drag(ed, xb, ya, yb, 'B back to its row')
            ed.idle(1)
            _ge6_ui_build(ed, xb, yb)
        ed.idle(4)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-02 22:17 attempt 2
# Crashlytics ge6a5791: Remove BG mask sink vs overlay row drag (changeVisualMediaLayer) -> SIGSEGV in append_remove_bg_track_mask.

MASKS_GE6 = '/sdcard/Android/data/com.myzesty/files'
BUILD_RE = r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+'
DEL_RE = r'MsgDeleteMedia: media_layer \d+ media_id \d+'
DRAG_X = 520                                     # right of the playhead: inside the 20 s bars, between their thumbs


def _num_after(line, key):
    return int(str(line).split(key, 1)[1].split()[0].strip(','))


def _ge6_open(ed):
    """Open the fixture and STAY in the editor (attempt 1's BACK key left it)."""
    mark = ed.log_mark()
    ed.open_fixture('ge6a5791')
    ed.require_log(r'test_ve_draft_project_complete', 40, since=mark, why='fixture overlays loaded (earlier taps are lost)')
    ed.idle(2)
    ed.set_playing(False)
    return mark


def _ge6_rows(ed):
    """Overlay rows on the timeline, top to bottom, as y centres."""
    s = ed.screen()
    rows = sorted([n for n in (s.find_all('id:range_slider') if s is not None else []) if n.b[2] - n.b[0] > 300],
                  key=lambda n: n.b[1])
    return [(n.b[1] + n.b[3]) // 2 for n in rows]


def _ge6_select_at(ed, y):
    """Select the overlay bar on the row nearest y (select_overlay waits for ve_timeline_overlay)."""
    ys = _ge6_rows(ed)
    if not ys:
        raise UIError('no overlay rows on the timeline')
    i = min(range(len(ys)), key=lambda k: abs(ys[k] - y))
    ed.select_overlay(i)
    return ys[i]


def _ge6_ui_build(ed, row):
    """Select overlay B, Remove BG -> Auto (the app's own build). Returns the build's layer."""
    ed.select_overlay(row)
    if not ed.ui.tap('desc:ve_tab_overlay_remove_bg', timeout=6):
        ed.tap_tool('remove bg')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=10) is None:
        raise UIError('Remove BG panel (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    line = ed.require_log(BUILD_RE, 20, since=mark, why='Remove BG Auto starts the native build')
    ed.require_log(r'masks planned from', 10, since=mark, why='a real (uncached) build: masks must stream during the drag')
    ed.require_log(r'BGFX setMask key=removebg_mask_|RemoveBgTrack: frame=', 20, since=mark, why='first masks stream')
    return _num_after(line, 'layer ')


def _ge6_delete(ed, y):
    """Select overlay A and delete it (field: MsgDeleteMedia on the other layer, build not cancelled)."""
    _ge6_select_at(ed, y)
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_delete', timeout=8)
    s = ed.screen()
    if s is not None and s.has('id:firstBtnTv'):
        ed.dev.tap(*s.find('id:firstBtnTv').center)
    line = ed.require_log(DEL_RE, 10, since=mark, why='delete overlay A')
    ed.main_nav()                                # field: ve_back_tool_btn (back only if a panel is open)
    return _num_after(line, 'media_layer ')


def _ge6_drag(ed, y_from, y_to, lb, why):
    """Select B, long-press between its thumbs, drop on the other row: moveItemToLayer -> changeVisualMediaLayer."""
    y = _ge6_select_at(ed, y_from)
    mark = ed.log_mark()
    ed.dev.long_drag(DRAG_X, y, DRAG_X, y_to, hold=0.9, steps=14)
    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id \d+ old_layer {lb} new_layer \d+', 8, since=mark, why=why)


def _ge6_setup_full(ed):
    """Build on the top row (B), delete the row below (A). Returns (yb, ya, build layer)."""
    _ge6_open(ed)
    ed.select_overlay(0)                         # opens the overlay timeline
    ys = _ge6_rows(ed)
    if len(ys) < 2:
        raise UIError(f'fixture ge6a5791 needs 2 overlay rows, timeline shows {len(ys)}')
    yb, ya = ys[0], ys[1]
    ed.main_nav()
    lb = _ge6_ui_build(ed, 0)
    ed.main_nav()                                # leave Remove BG: the build keeps running as a background task
    la = _ge6_delete(ed, ya)
    if la == lb:
        raise UIError(f'deleted the build layer {lb}: wrong row picked for A')
    return yb, ya, lb


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_a(ed, r):
    """FULL: Crashlytics ge6a5791: Remove BG on overlay B, delete overlay A, drag B onto A's row mid-build."""
    yb, ya, lb = _ge6_setup_full(ed)
    ed.idle(r.uniform(0.5, 1.5))
    ed.step('drag B onto the freed row while masks stream (trigger)')
    _ge6_drag(ed, yb, ya, lb, 'B row drag -> MsgChangeVisualMediaLayer on the build layer (trigger)')
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_b(ed, r):
    """HYBRID: Crashlytics ge6a5791: build started by engine call; delete A and drag B by real taps."""
    opened = _ge6_open(ed)
    ed.select_overlay(0)
    ys = _ge6_rows(ed)
    if len(ys) < 2:
        raise UIError(f'fixture ge6a5791 needs 2 overlay rows, timeline shows {len(ys)}')
    yb, ya = ys[0], ys[1]
    ed.main_nav()
    la = _ge6_delete(ed, ya)
    layers = [L for L in range(1, 7) if L != la and
              ed.wait_log(rf'MsgOverlayMediaTimeLimits layer {L},', 0.5, since=opened)]
    if not layers:
        raise UIError('could not tell overlay B\'s layer from the fixture load')
    lb = layers[0]
    mark = ed.log_mark()
    ed.jni(f'startNativeRemoveBgBuild(0,1,{MASKS_GE6},{lb});sleep(800);nativeRemoveBgBuildProgress()')  # HYBRID
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {lb} media_id 0', 15, since=mark, why='build started (HYBRID)')
    ed.require_log(r'masks planned from', 10, since=mark, why='uncached build (HYBRID)')
    ed.require_log(r'BGFX setMask key=removebg_mask_|RemoveBgTrack: frame=', 20, since=mark, why='masks streaming')
    ed.step('drag B onto the freed row while masks stream (trigger)')
    _ge6_drag(ed, yb, ya, lb, 'B row drag -> MsgChangeVisualMediaLayer on the build layer (trigger)')
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_c(ed, r):
    """FULL: Crashlytics ge6a5791: field path on a slow phone, B dragged back and forth while the build runs."""
    yb, ya, lb = _ge6_setup_full(ed)
    ed.dev.slow_phone(r.randint(25, 40))         # slower looper: the move's null window (:245..:260) stays open longer
    try:
        src, dst, layer = yb, ya, lb
        for k in range(4):
            ed.step(f'slow phone: drag B across rows mid-build ({k + 1}/4)')
            ed.idle(r.uniform(0.3, 1.2))
            mark = ed.log_mark()
            _ge6_drag(ed, src, dst, layer, 'B row drag -> MsgChangeVisualMediaLayer (trigger)')
            line = ed.wait_log(r'MsgChangeVisualMediaLayer: media_id \d+ old_layer \d+ new_layer \d+', 3, since=mark)
            layer = _num_after(line, 'new_layer ') if line else layer
            src, dst = dst, src
            ed.idle(2)
        ed.idle(4)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-02 22:21 attempt 3
# Crashlytics ge6a5791: Remove BG mask sink vs overlay row drag (changeVisualMediaLayer) -> SIGSEGV in append_remove_bg_track_mask.

MASKS_GE6 = '/sdcard/Android/data/com.myzesty/files'
BUILD_RE = r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+'
MOVE_RE = r'MsgChangeVisualMediaLayer: media_id \d+ old_layer \d+ new_layer \d+'
DEL_RE = r'MsgDeleteMedia: media_layer \d+ media_id \d+'
MASK_RE = r'BGFX setMask key=removebg_mask_|RemoveBgTrack: frame='


def _num_after(line, key):
    return int(str(line).split(key, 1)[1].split()[0].strip(','))


def _ge6_rows(ed):
    """Overlay bars (id:range_slider), top to bottom; reopens the Overlay tool when they are not shown."""
    for _ in range(3):
        s = ed.screen()
        bars = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
        if bars:
            return bars
        ed.main_nav()
        ed.tap_tool('overlay')                    # attempt 2: rows only exist inside the Overlay tool
        ed.ui.wait('id:range_slider', timeout=6)
    raise UIError('overlay rows (range_slider) did not show after opening the Overlay tool')


def _ge6_open(ed):
    """Open the fixture, wait for the draft load, open the Overlay tool. Returns (mark, [bar y top->bottom])."""
    mark = ed.log_mark()
    ed.open_fixture('ge6a5791')
    ed.require_log(r'test_ve_draft_project_complete', 40, since=mark, why='fixture overlays loaded (earlier taps are lost)')
    ed.idle(2)
    ed.set_playing(False)
    ed.tap_tool('overlay')                        # no BACK key here: attempt 1 left the editor with it
    ed.ui.wait('id:range_slider', timeout=8)
    ys = [(n.b[1] + n.b[3]) // 2 for n in _ge6_rows(ed)]
    if len(ys) < 2:
        raise UIError(f'fixture ge6a5791 needs 2 overlay bars, timeline shows {len(ys)}')
    return mark, ys


def _ge6_pick(ed, y):
    """Select the bar nearest y like a user (select_overlay waits for ve_timeline_overlay); returns the node."""
    bars = _ge6_rows(ed)
    k = min(range(len(bars)), key=lambda i: abs((bars[i].b[1] + bars[i].b[3]) // 2 - y))
    ed.select_overlay(k)
    return bars[k]


def _ge6_back(ed):
    """Field ve_back_tool_btn: leave the panel; the build must keep running."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    ed.wait_log(r've_back_tool_btn|MsgSaveDraft', 3, since=mark)
    if ed.wait_log(r'RemoveBgMaskTrackBuilder: cancelled after', 1.5, since=mark):
        raise UIError('leaving the panel cancelled the build: the field build kept running')


def _ge6_build(ed, y):
    """Overlay at y -> Remove BG -> Auto (the app's own build, real uncached masks). Returns the build layer."""
    _ge6_pick(ed, y)
    if not ed.ui.tap('desc:ve_tab_overlay_remove_bg', timeout=6):
        raise UIError('overlay Remove BG tab (ve_tab_overlay_remove_bg) not on screen')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=10) is None:
        raise UIError('Remove BG panel (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    line = ed.require_log(BUILD_RE, 20, since=mark, why='Remove BG Auto starts the native build')
    ed.require_log(r'masks planned from', 15, since=mark, why='a real (uncached) build: masks must stream during the drag')
    ed.require_log(MASK_RE, 20, since=mark, why='first masks stream into the track')
    _ge6_back(ed)
    return _num_after(line, 'layer ')


def _ge6_delete(ed, y):
    """Overlay A -> Delete -> confirm (field: MsgDeleteMedia, build not cancelled). Returns A's layer."""
    _ge6_pick(ed, y)
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_overlay_delete', timeout=8):
        raise UIError('overlay Delete (ve_btn_overlay_delete) not on screen')
    s = ed.ui.wait('id:firstBtnTv', timeout=3)
    if s is not None:
        ed.dev.tap(*s.find('id:firstBtnTv').center)
    line = ed.require_log(DEL_RE, 10, since=mark, why='delete overlay A')
    _ge6_back(ed)
    return _num_after(line, 'media_layer ')


def _ge6_drag(ed, y_from, y_to, why):
    """Long-press B's bar and drop it on the other row: applyLayerChange -> moveItemToLayer -> changeVisualMediaLayer."""
    bar = _ge6_pick(ed, y_from)
    L, T_, R, B = bar.b
    x = max(L + 60, min(R - 60, (L + R) // 2))
    mark = ed.log_mark()
    ed.dev.long_drag(x, (T_ + B) // 2, x, y_to, hold=0.9, steps=14)
    return _num_after(ed.require_log(MOVE_RE, 8, since=mark, why=why), 'new_layer ')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_a(ed, r):
    """FULL: Crashlytics ge6a5791: Remove BG on overlay B, delete overlay A, drag B onto A's row mid-build."""
    _, ys = _ge6_open(ed)
    cur, other = ys[0], ys[1]                     # B = top bar (build target), A = the bar below
    lb = _ge6_build(ed, cur)
    if _ge6_delete(ed, other) == lb:
        raise UIError(f'deleted the build layer {lb}: wrong bar picked for A')
    for k in range(4):
        ed.step(f'drag B to the other row while masks stream ({k + 1}/4)')
        ed.idle(r.uniform(0.3, 1.5))
        _ge6_drag(ed, cur, other, 'B row drag -> MsgChangeVisualMediaLayer on the build media (trigger)')
        cur, other = other, cur
        ed.idle(3)
        if k < 3:
            _ge6_build(ed, cur)                   # the move ends the old build: one chance per build
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_b(ed, r):
    """HYBRID: Crashlytics ge6a5791: build started by engine call; overlay A deleted and B dragged by real taps."""
    opened, ys = _ge6_open(ed)
    cur, other = ys[0], ys[1]
    la = _ge6_delete(ed, other)
    layers = [L for L in range(1, 8) if L != la and
              ed.wait_log(rf'MsgOverlayMediaTimeLimits layer {L},', 0.3, since=opened)]
    if not layers:
        raise UIError("could not tell overlay B's layer from the fixture load")
    lb = layers[0]
    for k in range(6):
        ed.step(f'engine build on B (layer {lb}), then real drag ({k + 1}/6)')
        mark = ed.log_mark()
        ed.jni(f'startNativeRemoveBgBuild(0,1,{MASKS_GE6},{lb});sleep(800);nativeRemoveBgBuildProgress()')  # HYBRID
        ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {lb} media_id 0', 15, since=mark, why='build started (HYBRID)')
        ed.require_log(r'masks planned from', 15, since=mark, why='uncached build (HYBRID)')
        ed.require_log(MASK_RE, 20, since=mark, why='masks streaming')
        ed.idle(r.uniform(0.2, 1.2))
        lb = _ge6_drag(ed, cur, other, 'B row drag -> MsgChangeVisualMediaLayer on the build layer (trigger)')
        cur, other = other, cur
        ed.idle(3)
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_c(ed, r):
    """FULL: Crashlytics ge6a5791: field path, slow phone during the drags (wider move window), 6 builds/drags."""
    _, ys = _ge6_open(ed)
    cur, other = ys[0], ys[1]
    lb = _ge6_build(ed, cur)
    if _ge6_delete(ed, other) == lb:
        raise UIError(f'deleted the build layer {lb}: wrong bar picked for A')
    try:
        for k in range(6):
            ed.dev.slow_phone(r.randint(25, 38))  # slower looper: :245..:260 null window stays open longer
            ed.step(f'slow phone: drag B to the other row mid-build ({k + 1}/6)')
            ed.idle(r.uniform(0.2, 2.0))
            _ge6_drag(ed, cur, other, 'B row drag -> MsgChangeVisualMediaLayer (trigger)')
            cur, other = other, cur
            ed.idle(3)
            ed.dev.slow_phone(0)                  # full-speed masks for the next build
            if k < 5:
                _ge6_build(ed, cur)
        ed.idle(4)
    finally:
        ed.dev.slow_phone(0)
