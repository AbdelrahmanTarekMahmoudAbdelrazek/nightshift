# Night Shift: frozen copy of the registered repro tf_ge6a5791_1_b (1103213835); later runs cannot change it
# Night Shift tap repros for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (from the engine repro + full field log)


# 2026-11-03 21:35 attempt 1
CACHE = '/data/user/0/com.myzesty/cache'
BUILD = r'MsgStartNativeRemoveBgBuild: layer (\d+) media_id 0'


def _rows(ed):
    """Overlay bars (id:range_slider) top to bottom; opens the Overlay tool when they are not on screen."""
    s = ed.screen()
    if s is None or not s.has('id:range_slider'):
        ed.main_nav()
        ed.tap_tool('overlay')
        ed.idle(1.5)
        s = ed.screen()
    rows = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if not rows:
        raise UIError('no overlay rows (range_slider) on the timeline')
    return rows


def _remove_bg(ed, why):
    """Overlay sub-tool Remove BG (toggleRemoveBgCutout); a second tap when the first only restored a cut-out."""
    for _ in range(2):
        mark = ed.log_mark()
        if not ed.ui.tap('desc:ve_tab_overlay_remove_bg', timeout=8):
            raise UIError('Remove BG (ve_tab_overlay_remove_bg) not on screen')
        if ed.wait_log(BUILD, 4, since=mark):
            break
        ed.idle(0.6)
    line = ed.require_log(BUILD, 10, since=mark, why=why)
    return int(str(line).split('layer ', 1)[1].split()[0])


def _drag_row(ed, y_from, y_to, layer, why):
    """Long-press the selected bar and drop it on another row: applyLayerChange -> moveItemToLayer -> changeVisualMediaLayer."""
    L, _, R, _ = _rows(ed)[0].b
    mark = ed.log_mark()
    for x in range(L + 40, R - 20, max(40, (R - L) // 8)):
        ed.dev.long_drag(x, y_from, x, y_to, hold=0.3, steps=8)
        if ed.wait_log(r'MsgChangeVisualMediaLayer', 2, since=mark):
            break
    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {layer} new_layer \d+', 6, since=mark, why=why)


def _field_path(ed, r, dur, cycles):
    ed.new_project(tag='ns_ge6a_base', duration_s=dur)
    l1 = ed.add_overlay_video(tag='ns_ge6a_o1', duration_s=dur)
    l2 = ed.add_overlay_video(tag='ns_ge6a_o2', duration_s=dur)
    ed.step(f'overlays on layers {l1},{l2}')
    rows = _rows(ed)
    ys = [(n.b[1] + n.b[3]) // 2 for n in rows]
    h = rows[0].b[3] - rows[0].b[1]
    y_top, y_bot = ys[0], (ys[1] if len(ys) > 1 else ys[0] + h)
    ed.select_overlay(1)                                   # bottom bar = the second overlay (field: layer 2)
    layer = _remove_bg(ed, 'Remove BG build starts on the selected overlay')
    ed.select_overlay(0)                                   # the other overlay (field: layer 1, media 0)
    other = l1 if layer == l2 else l2
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_overlay_delete', timeout=6):
        raise UIError('overlay Delete (ve_btn_overlay_delete) not on screen')
    ed.require_log(rf'MsgDeleteMedia: media_layer {other} media_id 0', 8, since=mark, why='delete the other overlay, build keeps running')
    y_cur, y_dst = y_bot, y_top
    for k in range(cycles):
        ed.step(f'drag cycle {k + 1}/{cycles}: overlay on layer {layer} -> other row while masks stream')
        ed.select_overlay()
        if k:                                              # rebuild on the layer the overlay sits on now
            layer = _remove_bg(ed, f'Remove BG build restarts on layer {layer}')
        ed.require_log(r'RemoveBgTrack: frame=', 15, why='masks are streaming into the overlay')
        ed.idle(r.uniform(0.2, 1.2))
        _drag_row(ed, y_cur, y_dst, layer, 'row drag moves the overlay that is being built')
        line = ed.wait_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer \d+ new_layer (\d+)', 2)
        layer = int(str(line).rsplit('new_layer ', 1)[1].split()[0]) if line else layer
        y_cur, y_dst = y_dst, y_cur
        ed.idle(1.5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_a_r1103213835(ed, r):
    """FULL: Crashlytics ge6a5791 ev1: Remove BG on overlay layer 2, delete overlay layer 1, drag the built overlay to row 1 -> SIGSEGV append_remove_bg_track_mask."""
    _field_path(ed, r, dur=17, cycles=8)
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_b_r1103213835(ed, r):
    """HYBRID: Crashlytics ge6a5791: the build is started by engine call; the trigger is the real row drag of the overlay being built."""
    ed.new_project(tag='ns_ge6a_base', duration_s=17)
    layer = ed.add_overlay_video(tag='ns_ge6a_h', duration_s=17)
    rows = _rows(ed)
    y_a = (rows[0].b[1] + rows[0].b[3]) // 2
    y_b = y_a + (rows[0].b[3] - rows[0].b[1])
    ed.jni(f'initNativeSegmenter(1,{CACHE})')                                     # HYBRID
    for k in range(10):
        ed.step(f'hybrid cycle {k + 1}/10: build on layer {layer}, then drag the bar')
        ed.select_overlay()
        mark = ed.log_mark()
        ed.jni(f'startNativeRemoveBgBuild(0,1,{CACHE},{layer});sleep(1500)')     # HYBRID
        ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id 0', 8, since=mark, why='build running')
        ed.idle(r.uniform(0.1, 1.0))
        src, dst = (y_a, y_b) if k % 2 == 0 else (y_b, y_a)
        _drag_row(ed, src, dst, layer, 'row drag moves the overlay that is being built')
        line = ed.wait_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer \d+ new_layer (\d+)', 2, since=mark)
        layer = int(str(line).rsplit('new_layer ', 1)[1].split()[0]) if line else layer
        ed.idle(1.5)
    ed.idle(4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_c_r1103213835(ed, r):
    """FULL: Crashlytics ge6a5791 on a slow phone (field vivo V2424, 110 ms/mask): the build is still streaming when each row drag lands."""
    try:
        ed.dev.slow_phone(30)
        _field_path(ed, r, dur=30, cycles=10)
        ed.idle(4)
    finally:
        ed.dev.slow_phone(0)
