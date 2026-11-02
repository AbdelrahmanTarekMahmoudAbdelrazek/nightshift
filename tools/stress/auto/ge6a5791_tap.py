# Night Shift tap repros for 2bc43cd6d24a25e5305f8167703618a8~e6a57918 (from the engine repro + full field log)


# 2026-11-01 14:41 attempt 1
"""Night Shift tap-flow repro for Crashlytics ge6a5791: SIGSEGV in VisualMedia::append_remove_bg_track_mask when an
overlay whose Remove-BG mask build is still streaming is dragged to another timeline row (changeVisualMediaLayer 2->1)."""

FIX = 'ga30bf15'                                    # layer-0 main clip + one layer-1 overlay video
CC = '/data/user/0/com.myzesty/code_cache'
MC = '/storage/emulated/0/Android/data/com.myzesty/files'


def _tap(ed, sel, pat, why, timeout=10):
    mark = ed.log_mark()
    ed.ui.tap(sel, timeout=10)
    return ed.require_log(pat, timeout=timeout, since=mark, why=why)


def _rows(ed):
    """(x, [y of overlay row 1, row 2, ...]) from the timeline; x = just right of the playhead (playhead at 0)."""
    s = ed.ui.dump()
    tv = s.find('id:videoTrackView')
    if tv is None:
        raise UIError('timeline (videoTrackView) not on screen')
    rows = [n for n in s.nodes if n.visible and 'RangeSlider' in n.cls]
    if len(rows) < 2:
        lay = [n for n in s.nodes if n.visible and 'SliderLayout' in n.cls]
        rows = [c for c in lay[0].children if c.visible] if lay else []
    ys = sorted({n.center[1] for n in rows if n.b[1] >= tv.b[1]})
    if len(ys) < 2:
        raise UIError(f'overlay rows not found in timeline: {s.summary()[:800]}')
    return tv.center[0] + 80, ys


def _select(ed, x, y, why):
    mark = ed.log_mark()
    ed.dev.tap(x, y)
    ed.require_log(r'MsgPausePlaying|MsgRefreshScreen|MsgSetOverlay\w*|seek requested', timeout=6, since=mark, why=why)
    ed.ui.wait('desc:ve_btn_overlay_duplicate', timeout=8)


def _drag(ed, x, y1, y2, old, new, why):
    mark = ed.log_mark()
    ed.dev.long_drag(x, y1, x, y2, 1.0, 14)
    ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer %d new_layer %d' % (old, new),
                   timeout=8, since=mark, why=why)


def _auto_removal(ed, why):
    _tap(ed, 'desc:ve_tab_overlay_remove_bg', r'Msg\w+|remove_bg', why + ': Remove BG menu', timeout=6)
    _tap(ed, ('desc:ve_tab_remove_bg_auto', 'textc:auto'), r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0',
         why + ': Auto Removal starts the build on (2,0)', timeout=40)
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', timeout=20, why=why + ': masks streaming')


def _two_overlays(ed):
    ed.set_playing(False)
    x, ys = _rows(ed) if False else (None, None)
    s = ed.ui.dump()
    tv = s.find('id:videoTrackView')
    lay = [n for n in s.nodes if n.visible and ('RangeSlider' in n.cls or 'SliderLayout' in n.cls) and n.b[1] >= tv.b[1]]
    y1 = min(n.center[1] for n in lay) if lay else tv.b[3] - 40
    _select(ed, tv.center[0] + 80, y1, 'select overlay A (layer 1, row 1)')
    _tap(ed, 'desc:ve_btn_overlay_duplicate', r'MsgAddVideo', 'Duplicate -> overlay B on layer 2 / row 2', timeout=20)
    ed.idle(2)
    x, ys = _rows(ed)
    return x, ys[0], ys[1]


def _delete_a(ed, x, y1):
    _select(ed, x, y1, 'select overlay A (row 1)')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_delete', timeout=10)
    if not ed.wait_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 3, since=mark):
        s = ed.screen()
        if s is not None and s.has('id:firstBtn'):
            ed.dev.tap(*s.find('id:firstBtn').center)
    ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', timeout=8, since=mark, why='delete A while masks stream')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_a(ed, r):
    """FULL: duplicate overlay -> Remove BG Auto on B (layer 2) -> delete A -> drag B row 2->1 mid-build (ge6a5791)."""
    ed.open_fixture(FIX)
    x, y1, y2 = _two_overlays(ed)
    _select(ed, x, y2, 'select overlay B (layer 2, row 2)')
    _auto_removal(ed, 'B')
    _tap(ed, 'desc:ve_btn_back', r'MsgSaveDraft|MsgPausePlaying|Msg\w+', 'back out of the Remove BG menu', timeout=6)
    ed.idle(r.uniform(0.5, 1.5))
    _delete_a(ed, x, y1)
    ed.idle(r.uniform(0.8, 2.5))
    _select(ed, x, y2, 'select overlay B again (row 2)')
    _drag(ed, x, y2, y1, 2, 1, 'TRIGGER: drag B from row 2 to row 1 while its masks stream')
    ed.idle(6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_b(ed, r):
    """HYBRID: the mask build on (2,0) is started by a lab shortcut; delete and row-drag of B are real taps (ge6a5791)."""
    ed.open_fixture(FIX)
    x, y1, y2 = _two_overlays(ed)
    for k in range(3):
        mark = ed.log_mark()
        ed.jni('initNativeSegmenter(1,' + CC + ');startNativeRemoveBgBuild(0,1,' + MC + ',2)', thread='bg')  # HYBRID
        ed.require_log(r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0', timeout=15, since=mark, why='build on B')  # HYBRID
        ed.require_log(r'masks planned', timeout=20, since=mark, why='masks streaming')  # HYBRID
        if k == 0:
            _delete_a(ed, x, y1)
        ed.idle(r.uniform(0.3, 2.0))
        _select(ed, x, y2, 'select overlay B (row 2)')
        _drag(ed, x, y2, y1, 2, 1, 'TRIGGER: drag B row 2 -> row 1 mid-build')
        ed.idle(3)
        _select(ed, x, y1, 'select B on row 1')
        _drag(ed, x, y1, y2, 1, 2, 'drag B back to row 2 for the next build')
        ed.idle(1)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_c(ed, r):
    """FULL: slow phone; repeat Remove BG Auto on B then drag B row 2->1 mid-build, dragging back between builds (ge6a5791)."""
    ed.open_fixture(FIX)
    x, y1, y2 = _two_overlays(ed)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        for k in range(5):
            _select(ed, x, y2, 'select overlay B (row 2)')
            _auto_removal(ed, 'B build %d' % k)
            _tap(ed, 'desc:ve_btn_back', r'Msg\w+', 'back out of the Remove BG menu', timeout=6)
            if k == 0:
                _delete_a(ed, x, y1)
            ed.idle(r.uniform(0.2, 2.5))
            _select(ed, x, y2, 'select overlay B (row 2)')
            _drag(ed, x, y2, y1, 2, 1, 'TRIGGER: drag B row 2 -> row 1 mid-build')
            ed.idle(3)
            _select(ed, x, y1, 'select B on row 1')
            _drag(ed, x, y1, y2, 1, 2, 'drag B back to row 2 for the next build')
            ed.idle(1.5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 14:46 attempt 2
"""Night Shift tap-flow repro for Crashlytics ge6a5791 (attempt 2): SIGSEGV in VisualMedia::append_remove_bg_track_mask when
the overlay whose Remove-BG mask build is streaming is dragged to another timeline row (MsgChangeVisualMediaLayer 2->1)."""

# The only project with a video overlay on 2208294910DA0LA8: layer-0 main clip + layer-1 overlay A ("ga30bf15" was retired)
FIX = 'ga30bf15_old_202611010231'
CC = '/data/user/0/com.myzesty/code_cache'
MC = '/storage/emulated/0/Android/data/com.myzesty/files'
SEL = r'MsgPausePlaying|MsgRefreshScreen|MsgGetLayerRenderOrder'   # field: every overlay tap sent MsgPausePlaying first


def _open(ed):
    mark = ed.log_mark()
    ed.open_fixture(FIX)
    ed.require_log(r'MsgAddVideo: media_layer 1 path:', 30, since=mark, why='draft restores its layer-1 overlay A')
    if ed.wait_log(r'add_video Failed|Cannot open file', 4, since=mark):
        raise UIError('overlay A file did not open: the fixture media is gone')
    ed.set_playing(False)
    ed.idle(1)


def _rows(ed):
    """(x, [y of row 1, row 2, ...]): SliderLayout's RangeSlider children, top = row 1; x just right of the playhead."""
    s = ed.ui.dump(slow=True)
    tv = s.find('id:videoTrackView')
    ys = []
    for n in sorted((n for n in s.nodes if n.visible and n.cls.endswith('RangeSlider')), key=lambda n: n.center[1]):
        if not any(abs(n.center[1] - y) < 12 for y in ys):
            ys.append(n.center[1])
    if not ys:
        raise UIError('no overlay RangeSlider rows in the timeline: ' + s.summary()[:600])
    return (tv.center[0] if tv is not None else 360) + 70, ys


def _overlay_mode(ed):
    """Main timeline -> tap the Overlay bar (TimeLineBarView #4, field ve_timeline_overlay) -> one row per overlay."""
    s = ed.ui.dump(slow=True)
    if not any(n.visible and n.cls.endswith('RangeSlider') for n in s.nodes):
        bars = sorted((n for n in s.nodes if n.visible and n.cls.endswith('TimeLineBarView')), key=lambda n: n.b[1])
        if len(bars) < 4:
            raise UIError('audio/text/effect/overlay bars not found: ' + s.summary()[:600])
        mark = ed.log_mark()
        ed.dev.tap(*bars[3].center)
        ed.require_log(SEL, 8, since=mark, why='tap the Overlay timeline bar (ve_timeline_overlay)')
        ed.idle(1.5)
    return _rows(ed)


def _select(ed, x, y, why, want='desc:ve_btn_overlay_delete'):
    for k in range(3):
        if k == 2:
            ed.dev.key('KEYCODE_BACK')               # a tool panel (Remove BG) still covers the overlay menu
            ed.idle(1)
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        ed.require_log(SEL, 8, since=mark, why=why)
        if ed.ui.wait(want, timeout=5) is not None:
            return
    raise UIError(why + ': overlay menu (%s) did not show' % want)


def _tap(ed, sel, pat, why, timeout=10):
    mark = ed.log_mark()
    ed.ui.tap(sel, timeout=10)
    return ed.require_log(pat, timeout=timeout, since=mark, why=why)


def _auto(ed, why):
    """Remove BG -> (Restore an earlier cutout) -> Auto Removal: MsgStartNativeRemoveBgBuild on B = (2,0)."""
    _tap(ed, 'desc:ve_tab_overlay_remove_bg', r'Msg\w+', why + ': open Remove BG')
    s = ed.ui.wait(('desc:ve_tab_remove_bg_auto', 'desc:ve_btn_remove_bg_restore'), timeout=10)
    if s is None:
        raise UIError(why + ': Remove BG panel did not open')
    if not s.has('desc:ve_tab_remove_bg_auto'):
        _tap(ed, 'desc:ve_btn_remove_bg_restore', r'MsgSetRemoveBgMask|Msg\w+', why + ': Restore the old cutout')
        ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=10)
    mark = ed.log_mark()
    _tap(ed, 'desc:ve_tab_remove_bg_auto', r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0', why + ': Auto Removal', 40)
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', 20, since=mark, why=why + ': masks streaming')


def _delete_a(ed, x, y1):
    _select(ed, x, y1, 'select overlay A (row 1) while B masks stream')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_delete', timeout=10)
    if not ed.wait_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 3, since=mark):
        s = ed.screen()
        if s is not None and s.has('id:firstBtn'):
            ed.dev.tap(*s.find('id:firstBtn').center)
    ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 10, since=mark, why='delete A (ve_overlay_deleted_complete)')
    _tap(ed, 'desc:ve_btn_back', r'MsgSaveDraft|Msg\w+', 'back out of the overlay tool (ve_back_tool_btn)')


def _drag(ed, x, ya, yb, old, new, why):
    _select(ed, x, ya, why + ': tap B first (field ve_timeline_overlay)', 'desc:ve_tab_overlay_remove_bg')
    mark = ed.log_mark()
    ed.dev.long_drag(x, ya, x, yb, 1.0, 14)
    ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer %d new_layer %d' % (old, new), 10, since=mark, why=why)


def _make_b(ed):
    """Overlay mode, select A, Duplicate -> B on layer 2 / row 2. Returns (x, y row 1, y row 2)."""
    x, ys = _overlay_mode(ed)
    _select(ed, x, ys[0], 'select overlay A (row 1)', 'desc:ve_btn_overlay_duplicate')
    _tap(ed, 'desc:ve_btn_overlay_duplicate', r'MsgAddVideo: media_layer 2 path:', 'Duplicate -> overlay B on layer 2', 30)
    ed.idle(2)
    x, ys = _rows(ed)
    if len(ys) < 2:
        raise UIError('row 2 (overlay B) not in the timeline after Duplicate')
    return x, ys[0], ys[1]


def _full(ed, r, rounds):
    x, y1, y2 = _make_b(ed)
    for k in range(rounds):
        _select(ed, x, y2, 'select overlay B (row 2)', 'desc:ve_tab_overlay_remove_bg')
        _auto(ed, 'B build %d' % k)
        ed.idle(r.uniform(0.8, 2.5))                 # masks stream (field: 4 s of build before the delete)
        if k == 0:
            _delete_a(ed, x, y1)
            ed.idle(r.uniform(0.5, 1.5))
        _drag(ed, x, y2, y1, 2, 1, 'TRIGGER: drag B row 2 -> row 1 while its masks stream')
        ed.idle(4)
        _drag(ed, x, y1, y2, 1, 2, 'drag B back to row 2 for the next build')
        ed.idle(1)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_a(ed, r):
    """FULL: overlay draft -> Duplicate (B, layer 2) -> Remove BG Auto on B -> delete A -> drag B row 2->1 mid-build (ge6a5791)."""
    _open(ed)
    _full(ed, r, 4)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_b(ed, r):
    """HYBRID: the (2,0) mask build is started by a lab shortcut; Duplicate, delete A and the row drag of B are real taps (ge6a5791)."""
    _open(ed)
    x, y1, y2 = _make_b(ed)
    _delete_a(ed, x, y1)                             # BEFORE the build: a delete with an unknown build cancels it
    for k in range(6):
        mark = ed.log_mark()
        ed.jni('initNativeSegmenter(1,' + CC + ');startNativeRemoveBgBuild(0,1,' + MC + ',2)', thread='bg')  # HYBRID
        ed.require_log(r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0', 15, since=mark, why='build on B (2,0)')  # HYBRID
        ed.require_log(r'masks planned', 20, since=mark, why='masks streaming')  # HYBRID
        ed.idle(r.uniform(0.3, 2.0))
        _drag(ed, x, y2, y1, 2, 1, 'TRIGGER: drag B row 2 -> row 1 while its masks stream')
        ed.idle(3)
        _drag(ed, x, y1, y2, 1, 2, 'drag B back to row 2 for the next build')
        ed.idle(1)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_c(ed, r):
    """FULL on a slow phone (field ~110 ms/mask): Remove BG Auto on B, delete A, drag B row 2->1 mid-build, 5 builds (ge6a5791)."""
    _open(ed)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _full(ed, r, 5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 14:49 attempt 3
"""Night Shift tap-flow repro for Crashlytics ge6a5791 (attempt 3): SIGSEGV in VisualMedia::append_remove_bg_track_mask when
the overlay whose Remove-BG mask build is streaming is dragged to another timeline row (MsgChangeVisualMediaLayer 2->1).
No overlay fixture survives on this phone, so each scenario builds overlay A itself on the runner's test draft."""

MC = '/storage/emulated/0/Android/data/com.myzesty/files'
CC = '/data/user/0/com.myzesty/code_cache'
SEL = r'MsgPausePlaying|MsgRefreshScreen|MsgGetLayerRenderOrder|MsgSetOverlay\w*'


def _tap(ed, sel, pat, why, timeout=10):
    mark = ed.log_mark()
    if not ed.ui.tap(sel, timeout=10):
        raise UIError(why + ': %s not on screen' % (sel,))
    return ed.require_log(pat, timeout=timeout, since=mark, why=why)


def _add_overlay_a(ed):
    """Overlay tool -> Add -> newest video (fresh 15 s copy) -> Done: MsgAddVideo layer 1 (ns_ga30bf15_fx steps)."""
    ed.dev.fresh_video('ge6a5791_ovl', duration_s=15)
    ed.set_playing(False)
    ed.main_nav()
    ed.tap_tool('overlay')
    if ed.ui.wait('desc:ve_btn_overlay_add', timeout=10) is None:
        raise UIError('overlay tool (ve_btn_overlay_add) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_add', timeout=10)
    if ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20) is None:
        raise UIError('overlay picker did not open')
    ed.ui.tap('id:video_tab', timeout=5)
    ed.idle(1.5)
    ed.ui.tap('id:gridrl', timeout=10)                # first tile = the fresh copy
    ed.idle(0.5)
    ed.ui.tap(('id:done', 'text:done', 'id:next_button'), timeout=10)
    ed.require_log(r'MsgAddVideo: media_layer 1 path:', 120, since=mark, why='overlay A added on layer 1')
    ed.idle(3)


def _rows(ed):
    s = ed.ui.dump(slow=True)
    tv = s.find('id:videoTrackView')
    ys = []
    for n in sorted((n for n in s.nodes if n.visible and n.cls.endswith('RangeSlider')), key=lambda n: n.center[1]):
        if not any(abs(n.center[1] - y) < 12 for y in ys):
            ys.append(n.center[1])
    if not ys:
        raise UIError('no overlay rows (RangeSlider) in the timeline: ' + s.summary()[:600])
    return (tv.center[0] if tv is not None else 360) + 70, ys


def _select(ed, x, y, why, want):
    for _ in range(3):
        mark = ed.log_mark()
        ed.dev.tap(x, y)                              # field: ve_timeline_overlay
        ed.require_log(SEL, 8, since=mark, why=why)
        if ed.ui.wait(want, timeout=5) is not None:
            return
        ed.dev.key('KEYCODE_BACK')                    # a tool panel still covers the overlay menu
        ed.idle(1)
    raise UIError(why + ': overlay menu (%s) did not show' % want)


def _make_b(ed):
    """Select A, Duplicate -> B gets a fresh layer (2) and row (2). Returns (x, y row 1, y row 2)."""
    x, ys = _rows(ed)
    _select(ed, x, ys[0], 'select overlay A (row 1)', 'desc:ve_btn_overlay_duplicate')
    _tap(ed, 'desc:ve_btn_overlay_duplicate', r'MsgAddVideo: media_layer 2 path:', 'Duplicate -> overlay B on layer 2', 60)
    ed.idle(2)
    x, ys = _rows(ed)
    if len(ys) < 2:
        raise UIError('row 2 (overlay B) not in the timeline after Duplicate')
    return x, ys[0], ys[1]


def _auto(ed, x, y2, why):
    _select(ed, x, y2, why + ': select B (row 2)', 'desc:ve_tab_overlay_remove_bg')
    _tap(ed, 'desc:ve_tab_overlay_remove_bg', r'MsgPausePlaying|Msg\w+', why + ': open Remove BG')
    s = ed.ui.wait(('desc:ve_tab_remove_bg_auto', 'desc:ve_btn_remove_bg_restore'), timeout=10)
    if s is not None and not s.has('desc:ve_tab_remove_bg_auto'):
        _tap(ed, 'desc:ve_btn_remove_bg_restore', r'MsgSetRemoveBgMask|Msg\w+', why + ': restore the old cutout')
    mark = ed.log_mark()
    _tap(ed, 'desc:ve_tab_remove_bg_auto', r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0', why + ': Auto Removal', 40)
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', 20, since=mark, why=why + ': masks streaming')
    _tap(ed, 'desc:ve_btn_back', r'MsgSaveDraft|Msg\w+', why + ': back (ve_back_tool_btn)')


def _delete_a(ed, x, y1):
    _select(ed, x, y1, 'select overlay A (row 1)', 'desc:ve_btn_overlay_delete')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_btn_overlay_delete', timeout=10)
    if not ed.wait_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 3, since=mark):
        s = ed.screen()
        if s is not None and s.has('id:firstBtn'):
            ed.dev.tap(*s.find('id:firstBtn').center)
    ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 10, since=mark, why='delete A (ve_overlay_deleted_complete)')
    _tap(ed, 'desc:ve_btn_back', r'MsgSaveDraft|Msg\w+', 'back out of the overlay tool (ve_back_tool_btn)')


def _drag_b(ed, x, y2, y1):
    _select(ed, x, y2, 'TRIGGER prep: tap B (ve_timeline_overlay)', 'desc:ve_tab_overlay_remove_bg')
    mark = ed.log_mark()
    ed.dev.long_drag(x, y2, x, y1, 1.0, 14)
    ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer 1', 10, since=mark,
                   why='TRIGGER: drag B row 2 -> row 1 while its masks stream')


@scenario('nightshift', 'auto', 'tapflow')
def tf_ge6a5791_3_a(ed, r):
    """FULL: add overlay A -> Duplicate (B, layer 2) -> Remove BG Auto on B -> delete A -> drag B row 2->1 mid-build (ge6a5791)."""
    _add_overlay_a(ed)
    x, y1, y2 = _make_b(ed)
    _auto(ed, x, y2, 'B build')
    ed.idle(r.uniform(1.0, 3.0))                      # field: ~4 s of masks before the delete
    _delete_a(ed, x, y1)
    ed.idle(r.uniform(0.8, 2.0))                      # field: delete at T-4.0 s, drag at T-0.15 s
    _drag_b(ed, x, y2, y1)
    ed.idle(8)


@scenario('nightshift', 'auto', 'tapflow')
def tf_ge6a5791_3_b(ed, r):
    """HYBRID: the (2,0) mask build is started by a lab shortcut; add A, Duplicate, delete A and the row drag of B are real taps (ge6a5791)."""
    _add_overlay_a(ed)
    x, y1, y2 = _make_b(ed)
    _delete_a(ed, x, y1)
    mark = ed.log_mark()
    ed.jni('initNativeSegmenter(1,' + CC + ');startNativeRemoveBgBuild(0,1,' + MC + ',2)', thread='bg')  # HYBRID
    ed.require_log(r'MsgStartNativeRemoveBgBuild: layer 2 media_id 0', 15, since=mark, why='build on B (2,0)')  # HYBRID
    ed.require_log(r'masks planned', 20, since=mark, why='masks streaming')  # HYBRID
    ed.idle(r.uniform(0.5, 2.5))
    _drag_b(ed, x, y2, y1)
    ed.idle(8)


@scenario('nightshift', 'auto', 'tapflow')
def tf_ge6a5791_3_c(ed, r):
    """FULL, slow phone: Remove BG Auto on B, delete A, then build -> drag B row 2->1 -> Undo, repeated (ge6a5791)."""
    _add_overlay_a(ed)
    x, y1, y2 = _make_b(ed)
    ed.dev.slow_phone(r.randint(25, 40))              # field vivo: 110 ms/mask, wider move->erase window
    try:
        for k in range(4):
            _auto(ed, x, y2, 'B build %d' % k)
            ed.idle(r.uniform(0.3, 2.0))
            if k == 0:
                _delete_a(ed, x, y1)
                ed.idle(r.uniform(0.3, 1.0))
            _drag_b(ed, x, y2, y1)
            ed.idle(3)
            mark = ed.log_mark()
            ed.undo(1)                                # puts B back on layer 2 / row 2 for the next build
            ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer 1 new_layer 2', 10, since=mark,
                           why='Undo moves B back to layer 2')
            ed.idle(1.5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 16:27 attempt 1
SEG = ('setSegmentationModelPath(/data/user/0/com.myzesty/files/pp_humansegv2_mobile_256x256.tflite);'
       'initNativeSegmenter(1,/data/user/0/com.myzesty/cache)')
CACHE = '/data/user/0/com.myzesty/cache'
BUILD = r'MsgStartNativeRemoveBgBuild: layer (\d+) media_id (\d+)'
MOVE = r'MsgChangeVisualMediaLayer: media_id \d+ old_layer \d+ new_layer \d+'


def _open_overlays(ed):
    """Fixture ge6a5791 (base + overlays A, B), overlay timeline open; returns [(x, y)] per overlay row, top first."""
    ed.open_fixture('ge6a5791')
    ed.require_log(r've_draft_project_complete|MsgAddVideo: media_layer 2', 40, why='fixture overlays loaded')
    ed.set_playing(False)
    ed.tap_tool('overlay')
    s = ed.ui.wait('id:range_slider', timeout=10)
    rows = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if len(rows) < 2:
        raise UIError(f'fixture shows {len(rows)} overlay rows, need A and B')
    return [(min(n.b[2] - 20, n.b[0] + 100), (n.b[1] + n.b[3]) // 2) for n in rows[:2]]


def _ai_removal_tap(ed, row):
    """Select the overlay row, Remove BG -> AI Removal: the real build must start (not served from the mask cache)."""
    ed.select_overlay(row)
    ed.tap_tool('ve_tab_overlay_remove_bg')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=8) is None:
        raise UIError('Remove BG sub-menu (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    ed.require_log(BUILD, 30, since=mark, why='AI Removal started the native build')
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', 15, since=mark,
                   why='real mask build (a mask-cache replay ends in ~1 s)')
    ed.ui.tap('id:back', timeout=5)                         # field ve_back_tool_btn: back to the overlay tools
    if ed.ui.wait('desc:ve_btn_overlay_delete', timeout=8) is None:
        raise UIError('overlay tools not back after leaving Remove BG')


def _delete_row(ed, row):
    """Field: ve_overlay_deleted_complete -> MsgDeleteMedia on the OTHER overlay (the build keeps running)."""
    ed.select_overlay(row)
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_overlay_delete', timeout=6):
        raise UIError('overlay Delete (ve_btn_overlay_delete) not on screen')
    ed.require_log(r'MsgDeleteMedia: media_layer \d+ media_id \d+', 15, since=mark, why='other overlay deleted')


def _drag_storm(ed, r, x, y_from, y_to, n):
    """TRIGGER (real taps): select the built overlay's bar, long-press drag it to the other row, back and forth."""
    ed.step('trigger: drag the overlay being built to another row while masks stream')
    mark = ed.log_mark()
    ed.dev.tap(x, y_from)
    ed.require_log(r've_timeline_overlay', 8, since=mark, why='built overlay selected on the timeline')
    for i in range(n):
        if ed.wait_log(r'RemoveBgMaskTrackBuilder: (finished|cancelled)', 0.2, since=mark):
            raise UIError('mask build ended before the layer move landed')
        m = ed.log_mark()
        ed.dev.long_drag(x, y_from, x, y_to, hold=0.8, steps=8)
        if not ed.wait_log(MOVE, 6, since=m):            # selection lost after the drop: select again, one retry
            ed.dev.tap(x, y_to if i else y_from)
            ed.idle(0.5)
            ed.dev.long_drag(x, y_from, x, y_to, hold=0.8, steps=8)
        ed.require_log(MOVE, 8, since=m, why=f'drag {i + 1}: MsgChangeVisualMediaLayer')
        y_from, y_to = y_to, y_from
        ed.idle(r.uniform(0.05, 0.4))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_a(ed, r):
    """FULL: Crashlytics ge6a5791 - AI Removal on overlay B, delete overlay A, drag B into A's row -> SIGSEGV append_remove_bg_track_mask."""
    rows = _open_overlays(ed)
    built, other = 0, 1                                     # B (top row) is built, A is deleted, as in field event 1
    _ai_removal_tap(ed, built)
    ed.idle(r.uniform(1.0, 3.0))                            # field: ~4 s of masks before the delete
    _delete_row(ed, other)
    ed.idle(r.uniform(0.8, 1.6))                            # field: back + overlay tap, 3.9 s, before the move
    (x, yb), (_, ya) = rows[built], rows[other]
    _drag_storm(ed, r, x, yb, ya, 10)
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_b(ed, r):
    """HYBRID: Crashlytics ge6a5791 - real delete of A, engine-started build on B, real drag of B across rows -> SIGSEGV."""
    rows = _open_overlays(ed)
    built, other = 0, 1
    _delete_row(ed, other)                                  # delete first: with no Kotlin target the delete would cancel the build
    ed.idle(1)
    s = ed.screen()
    ovl = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    mark = ed.log_mark()
    ed.jni(SEG, thread='bg')                                # HYBRID: segmenter up
    ed.jni('startNativeRemoveBgBuild(0,1,%s,2)' % CACHE, thread='bg')   # HYBRID: B = layer 2 media 0 (fixture)
    ed.require_log(BUILD, 20, since=mark, why='native build running on B')
    ed.idle(r.uniform(0.8, 2.0))
    (x, yb), (_, ya) = rows[built], rows[other]
    _drag_storm(ed, r, x, yb, ya, 12)                       # TRIGGER: real long-press drags
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_1_c(ed, r):
    """FULL: Crashlytics ge6a5791 - field path on a slow phone (110 ms/mask as on the vivo V2424), drags land mid-stream."""
    rows = _open_overlays(ed)
    built, other = 0, 1
    try:
        ed.dev.slow_phone(r.randint(25, 35))                # builder at field speed: a long window of mask appends
        _ai_removal_tap(ed, built)
        ed.idle(r.uniform(2.0, 4.0))
        _delete_row(ed, other)
        ed.idle(r.uniform(0.3, 1.0))
        (x, yb), (_, ya) = rows[built], rows[other]
        _drag_storm(ed, r, x, yb, ya, 14)
        ed.idle(5)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 16:34 attempt 2
CACHE = '/data/user/0/com.myzesty/cache'
SEG = ('setSegmentationModelPath(/data/user/0/com.myzesty/files/pp_humansegv2_mobile_256x256.tflite);'
       'initNativeSegmenter(1,%s)' % CACHE)
BUILD = r'MsgStartNativeRemoveBgBuild: layer (\d+) media_id (\d+)'
ENDED = r'RemoveBgMaskTrackBuilder: (finished|cancelled)'


def _rows(ed):
    """Overlay timeline rows (range_slider), top first, as (x inside the bar, y centre)."""
    s = ed.ui.wait('id:range_slider', timeout=10)
    rows = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if len(rows) < 3:
        raise UIError(f'overlay timeline shows {len(rows)} rows, need 3')
    return [(min(n.b[2] - 20, n.b[0] + 120), (n.b[1] + n.b[3]) // 2) for n in rows]


def _open_overlay_tool(ed):
    mark = ed.log_mark()
    ed.tap_tool('overlay')
    ed.require_log(r'(?i)ve_overlay_tool_btn|ve_timeline_overlay', 10, since=mark, why='overlay tool open')
    return _rows(ed)


def _open(ed):
    ed.open_fixture('ge6a5791')
    ed.require_log(r'(?i)ve_draft_project_complete', 40, why='fixture A (layer 1) + B (layer 2) loaded')
    ed.set_playing(False)
    return _open_overlay_tool(ed)


def _pick(ed, xy):
    """Sub-bar tap -> onSliderSelected: logs nothing, the next engine message proves which overlay it was."""
    ed.dev.tap(*xy)
    ed.idle(0.8)


def _ai_removal(ed, xy):
    """Field 10:02:41: Remove BG -> AI Removal on the tapped overlay; returns the layer the real build runs on."""
    _pick(ed, xy)
    if not ed.ui.tap('desc:ve_tab_overlay_remove_bg', timeout=3):
        ed.tap_tool('ve_tab_overlay_remove_bg')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=8) is None:
        raise UIError('Remove BG panel (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    line = ed.require_log(BUILD, 30, since=mark, why='AI Removal -> MsgStartNativeRemoveBgBuild')
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', 15, since=mark,
                   why='live mask build (a cache replay is over in ~1 s)')
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_back', timeout=3):
        ed.ui.tap('id:back', timeout=3)
    ed.require_log(r'(?i)ve_back_tool_btn|MsgSaveDraft', 8, since=mark, why='back from Remove BG, build keeps running')
    return int(str(line).split('layer ', 1)[1].split()[0])


def _delete(ed, xy, layer):
    """Field 10:02:45: delete the OTHER overlay (coordinator returns early: B's build keeps streaming)."""
    _pick(ed, xy)
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_overlay_delete', timeout=6):
        raise UIError('overlay Delete (ve_btn_overlay_delete) not on screen')
    ed.require_log(r'MsgDeleteMedia: media_layer %d media_id 0' % layer, 15, since=mark, why='other overlay deleted')


def _drag_storm(ed, r, src, dst, layers, n, hold=0.8, steps=8, gap=(0.05, 0.4)):
    """TRIGGER (real long-press drags): the bar being built hops between two rows while masks land."""
    ed.step('trigger: drag the overlay being built across rows while masks stream')
    start = ed.log_mark()
    _pick(ed, src)
    for i in range(n):
        if ed.wait_log(ENDED, 0.2, since=start):
            raise UIError('mask build ended before enough layer moves landed')
        move = r'MsgChangeVisualMediaLayer: media_id \d+ old_layer %d new_layer %d' % layers
        m = ed.log_mark()
        ed.dev.long_drag(src[0], src[1], dst[0], dst[1], hold=hold, steps=steps)
        if not ed.wait_log(move, 4, since=m):          # landing row lost the selection: reselect, one retry
            _pick(ed, src)
            ed.dev.long_drag(src[0], src[1], dst[0], dst[1], hold=hold, steps=steps)
        ed.require_log(move, 8, since=m, why=f'drag {i + 1}: MsgChangeVisualMediaLayer {layers[0]}->{layers[1]}')
        src, dst, layers = dst, src, (layers[1], layers[0])
        ed.idle(r.uniform(*gap))


def _field_path(ed, r, n, **drag):
    rows = _open(ed)
    built = _ai_removal(ed, rows[1])                     # B: child 1 = row 2 = layer 2 (fixture)
    b_row, o_row = (1, 0) if built == 2 else (0, 1)
    ed.idle(r.uniform(1.5, 4.0))                         # field: ~4 s of masks before the delete
    _delete(ed, rows[o_row], 3 - built)
    rows = _open_overlay_tool(ed)                        # field: ve_back_tool_btn, then the overlay bar again
    ed.idle(r.uniform(0.5, 2.0))
    _drag_storm(ed, r, rows[b_row], rows[o_row], (built, 3 - built), n, **drag)
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_a(ed, r):
    """FULL: Crashlytics ge6a5791 - AI Removal on B, delete A, drag B into A's row and back -> SIGSEGV append_remove_bg_track_mask."""
    _field_path(ed, r, 16)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_b(ed, r):
    """HYBRID: Crashlytics ge6a5791 - engine-started build on B, real long-press drags B rows 2<->3 -> SIGSEGV."""
    rows = _open(ed)
    mark = ed.log_mark()
    ed.dev.long_drag(rows[1][0], rows[1][1], rows[2][0], rows[2][1], hold=0.8, steps=8)   # prove the drag first
    if not ed.wait_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer 3', 4, since=mark):
        _pick(ed, rows[1])
        ed.dev.long_drag(rows[1][0], rows[1][1], rows[2][0], rows[2][1], hold=0.8, steps=8)
    ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer 3', 8, since=mark,
                   why='B dragged to the empty third row')
    mark = ed.log_mark()
    ed.jni(SEG, thread='bg')                                                   # HYBRID: segmenter up
    ed.jni('startNativeRemoveBgBuild(0,1,%s,3)' % CACHE, thread='bg')          # HYBRID: build on B (now layer 3)
    ed.require_log(BUILD, 20, since=mark, why='native build running on B')
    ed.require_log(r'RemoveBgMaskTrackBuilder: \d+ masks planned', 15, since=mark, why='live mask build')
    ed.idle(r.uniform(0.5, 1.5))
    _drag_storm(ed, r, rows[2], rows[1], (3, 2), 18)                          # TRIGGER: real drags
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_2_c(ed, r):
    """FULL: Crashlytics ge6a5791 - field path on a vivo-speed phone (~110 ms/mask), quick drags land mid-stream."""
    try:
        ed.dev.slow_phone(r.randint(25, 35))
        _field_path(ed, r, 22, hold=0.65, steps=5, gap=(0.0, 0.2))
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 16:42 attempt 3
CACHE = '/data/user/0/com.myzesty/cache'
EXT = '/sdcard/Android/data/com.myzesty/files'          # debug build: NativeRemoveBgVideoBuild mask cache root
SEG = ('setSegmentationModelPath(/data/user/0/com.myzesty/files/pp_humansegv2_mobile_256x256.tflite);'
       'initNativeSegmenter(1,%s)' % CACHE)
BUILD = r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+'
PLANNED = r'RemoveBgMaskTrackBuilder: \d+ masks planned'
ENDED = r'RemoveBgMaskTrackBuilder: (finished|cancelled|served)'
MOVE = r'MsgChangeVisualMediaLayer: media_id \d+ old_layer %s new_layer \d+'


def _num(line, key):
    return int(str(line).split(key, 1)[1].split()[0])


def _fresh_masks(ed):
    """Lab upkeep: both fixture overlays share one transcode, and a finished build is replayed from the per-path mask
    cache in ~1 s. Move the caches aside (reversible, nothing deleted) so the build streams for real."""
    ed.dev.clear_app_cache('removebg_masks')
    ed.dev.sh(f'mkdir -p {EXT}/.ns_bak && mv {EXT}/removebg_masks {EXT}/.ns_bak/removebg_masks_{int(time.time())} 2>/dev/null')


def _overlay_rows(ed):
    """Overlay tool -> its SliderLayout rows (vertical, child 0 on top), as a tap point inside each bar's body."""
    mark = ed.log_mark()
    ed.tap_tool('overlay')
    ed.require_log(r've_overlay_tool_btn', 10, since=mark, why='overlay tool open')
    s = ed.ui.wait('id:range_slider', timeout=10)
    rows = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if len(rows) < 3:
        raise UIError(f'overlay timeline shows {len(rows)} rows, need 3')
    return [(min(n.b[2] - 80, n.b[0] + 226), (n.b[1] + n.b[3]) // 2) for n in rows]


def _open(ed):
    _fresh_masks(ed)
    mark = ed.log_mark()                                  # before the open: the line comes while open_fixture waits
    ed.open_fixture('ge6a5791')
    ed.require_log(r've_draft_project_complete', 40, since=mark, why='fixture A (layer 1) + B (layer 2) restored')
    ed.set_playing(False)
    return _overlay_rows(ed)


def _select(ed, xy):
    ed.dev.tap(*xy)                                       # RangeSlider -> onSliderSelected: no engine message
    ed.idle(0.7)


def _back(ed, until, why):
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_back', timeout=2):
        ed.dev.key('KEYCODE_BACK')
    ed.require_log(r've_back_tool_btn|MsgSaveDraft', 6, since=mark, why=why)
    if until and ed.ui.wait(until, timeout=6) is None:
        raise UIError(f'{until} not on screen after back ({why})')


def _storm(ed, r, rows, src, dst, layer, until, hold=0.7, steps=6, gap=(0.0, 0.3)):
    """TRIGGER (real long-press drags): the bar being built hops between rows while masks land.
    Returns (layer, src, dst) where the bar is now."""
    ed.step('trigger: drag the overlay being built across rows while masks stream')
    start = ed.log_mark()
    _select(ed, rows[src])
    while time.time() < until and not ed.wait_log(ENDED, 0.1, since=start):
        m = ed.log_mark()
        ed.dev.long_drag(rows[src][0], rows[src][1], rows[src][0], rows[dst][1], hold=hold, steps=steps)
        line = ed.wait_log(MOVE % layer, 4, since=m)
        if not line:                                      # selection lost after the drop: select again, one retry
            _select(ed, rows[src])
            ed.dev.long_drag(rows[src][0], rows[src][1], rows[src][0], rows[dst][1], hold=hold, steps=steps)
            line = ed.require_log(MOVE % layer, 6, since=m, why=f'drag of layer {layer}: MsgChangeVisualMediaLayer')
        layer, src, dst = _num(line, 'new_layer '), dst, src
        ed.idle(r.uniform(*gap))
    return layer, src, dst


def _field_path(ed, r, slow=0, **drag):
    rows = _open(ed)
    if slow:
        ed.dev.slow_phone(slow)                           # vivo V2424 speed: ~110 ms/mask, long append window
    _select(ed, rows[1])                                  # B (field: layer 2 media 0)
    ed.tap_tool('ve_tab_overlay_remove_bg')
    if ed.ui.wait('desc:ve_tab_remove_bg_auto', timeout=8) is None:
        raise UIError('Remove BG panel (ve_tab_remove_bg_auto) did not open')
    mark = ed.log_mark()
    ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=5)
    built = _num(ed.require_log(BUILD, 30, since=mark, why='AI Removal -> MsgStartNativeRemoveBgBuild'), 'layer ')
    ed.require_log(PLANNED, 15, since=mark, why='live mask build, not a cache replay')
    _back(ed, 'desc:ve_btn_overlay_delete', 'leave Remove BG, the build keeps running')
    ed.idle(r.uniform(1.0, 3.0))                          # field: ~4 s of masks before the delete
    _select(ed, rows[0])                                  # A, the other overlay
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_overlay_delete', timeout=6):
        raise UIError('overlay Delete (ve_btn_overlay_delete) not on screen')
    ed.require_log(r'MsgDeleteMedia: media_layer %d media_id 0' % (3 - built), 15, since=mark, why='other overlay deleted')
    _back(ed, None, 'field ve_back_tool_btn after the delete')
    rows = _overlay_rows(ed)                              # field: back into the overlay timeline
    _storm(ed, r, rows, 1, 0, built, time.time() + 90, **drag)
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_a(ed, r):
    """FULL: Crashlytics ge6a5791 - AI Removal on B, delete A, drag B into A's row and back -> SIGSEGV append_remove_bg_track_mask."""
    _field_path(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_b(ed, r):
    """HYBRID: Crashlytics ge6a5791 - engine-started builds on B, real long-press drags of B across rows -> SIGSEGV."""
    rows = _open(ed)
    _select(ed, rows[1])
    mark = ed.log_mark()
    ed.dev.long_drag(rows[1][0], rows[1][1], rows[1][0], rows[2][1], hold=0.8, steps=8)   # B to the empty 3rd row
    layer = _num(ed.require_log(MOVE % r'\d+', 8, since=mark, why='first real drag: B to row 3'), 'new_layer ')
    src, dst = 2, 1
    end = time.time() + 80
    while time.time() < end:
        ed.dev.clear_app_cache('removebg_masks')                                            # HYBRID: no cache replay
        mark = ed.log_mark()
        ed.jni(SEG + ';startNativeRemoveBgBuild(0,1,%s,%d)' % (CACHE, layer), thread='bg')  # HYBRID: build on B
        ed.require_log(BUILD, 20, since=mark, why=f'native build on B (layer {layer})')
        ed.require_log(PLANNED, 15, since=mark, why='live mask build')
        ed.idle(r.uniform(0.3, 1.2))
        layer, src, dst = _storm(ed, r, rows, src, dst, layer, end, hold=0.65, steps=5)      # TRIGGER: real drags
    ed.idle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ge6a5791_3_c(ed, r):
    """FULL: Crashlytics ge6a5791 - field path on a vivo-speed phone (~110 ms/mask), quick drags land mid-stream."""
    try:
        _field_path(ed, r, slow=r.randint(25, 35), hold=0.6, steps=4, gap=(0.0, 0.15))
    finally:
        ed.dev.slow_phone(0)
