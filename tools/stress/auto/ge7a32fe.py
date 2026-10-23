# Night Shift auto repros for 2bc43cd6d24a25e5305f8167703618a8~e7a32fec


# 2026-10-20 23:21 level 2 attempt 1
def _ge7a32fe_sticker_panel(ed, r):
    """Editor -> Stickers tool (ve_sticker_start) on the animated tab; returns the visible tiles."""
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.25, 0.45))                # field: sticker placed at the 3 s playhead
    ed.main_nav()
    ed.menu_tap('sticker')
    s = ed.ui.wait(T.STICKER_LIST, timeout=15)
    for tab in ('desc:ve_cat_sticker_trends', 'desc:ve_cat_sticker_animation'):
        if s is not None and s.has(tab):              # animated (webp) categories; default tab is usually one
            ed.dev.tap(*s.find(tab).center)
            ed.idle(2)
            s = ed.ui.wait(T.STICKER_LIST, timeout=10)
            break
    tiles = s.items(T.STICKER_LIST) if s else []
    if not tiles:
        raise UIError('sticker list empty (offline?)')
    return tiles


def _ge7a32fe_pick(ed, tile):
    mark = ed.log_mark()
    ed.dev.tap(*tile.center)
    if not ed.wait_log(r'MsgCreateWebpSticker', 20, since=mark):
        raise UIError('no animated (webp) sticker was created')
    ed.idle(1.5)


def _ge7a32fe_drag(ed, r, seconds):
    """Drag the live sticker around the preview, human speed (dozens of MsgSetStickerCoordinates)."""
    s = ed.screen()
    n = s.find(('id:animated_sticker', 'id:sticker', 'id:root_sticker_view', 'id:surface_view')) if s else None
    if n is None:
        raise UIError('sticker view not on screen')
    x, y = n.center
    end = time.time() + seconds
    while time.time() < end:
        dx, dy = r.randint(-60, 60), r.randint(-70, 70)
        ed.dev.swipe(x, y, x + dx, y + dy, r.randint(900, 1600))
        x, y = x + dx, y + dy
        ed.idle(r.uniform(0.3, 0.9))


def _ge7a32fe_back_then_keyframe(ed, r, gap, taps=1):
    """System back closes the add panel (discardNewSticker deletes the last sticker), then the Keyframe diamond."""
    ed.dev.key('KEYCODE_BACK')                        # 'back' videoeditor_backcalled, MsgDeleteSticker, MsgSaveDraft
    ed.idle(gap)
    for _ in range(taps):
        if not ed.ui.tap('id:keyframe', timeout=4):
            raise UIError('Keyframe button (id keyframe) not visible after the sticker was discarded')
        ed.idle(r.uniform(0.8, 1.5))
    ed.settle(5)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l2_1_a(ed, r):
    """Field instance 2026-09-26 vivo V2321: animated sticker, replace it, drag, back, Keyframe 2.5 s later -> SIGSEGV."""
    tiles = _ge7a32fe_sticker_panel(ed, r)
    _ge7a32fe_pick(ed, tiles[0])                      # sticker 0
    ed.idle(r.uniform(4, 8))
    _ge7a32fe_pick(ed, tiles[min(len(tiles) - 1, r.randint(1, 5))])   # REPLACE: delete 0, create webp sticker 1
    _ge7a32fe_drag(ed, r, r.uniform(7, 9))            # field: ~100 coordinate updates over 8 s
    ed.idle(r.uniform(4, 8))
    _ge7a32fe_back_then_keyframe(ed, r, gap=2.5)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l2_1_b(ed, r):
    """Field instance 2026-09-26 vivo V2321 (variant): one animated sticker, short drag, back, Keyframe tapped twice."""
    tiles = _ge7a32fe_sticker_panel(ed, r)
    _ge7a32fe_pick(ed, r.choice(tiles[:6]))
    _ge7a32fe_drag(ed, r, r.uniform(2, 4))
    ed.idle(1)
    _ge7a32fe_back_then_keyframe(ed, r, gap=r.uniform(1.0, 3.0), taps=2)


# 2026-10-20 23:25 level 2 attempt 2
def _ge7a32fe_open_stickers(ed, r):
    """Editor -> Stickers add panel (ve_sticker_start), scrolling the bottom bar to the item; returns the tiles."""
    ed.dev.network(True)                              # the sticker catalog is downloaded (DownloadAssetsWorker)
    ed.set_playing(False)
    ed.seek_swipe(r.uniform(-0.25, -0.1), r.randint(300, 600))   # field: sticker placed ~3 s in
    ed.idle(1)
    ed.main_nav()
    w, h = ed._screen_size()
    for _ in range(5):
        s = ed.screen()
        n = s.find('id:stickerTv') if s else None
        if n is not None:
            ed.dev.tap(*n.center)
            break
        bar = s.find(('id:bottom_bar', 'id:menu_container')) if s else None
        y = bar.center[1] if bar is not None else int(h * 0.93)
        ed.dev.drag_no_fling(int(w * 0.8), y, int(w * 0.35))
        ed.idle(1)
    else:
        raise UIError('Stickers item (id stickerTv) not found in the bottom bar')
    end = time.time() + 60
    while time.time() < end:
        s = ed.ui.wait(T.STICKER_LIST, timeout=10)
        for tab in ('desc:ve_cat_sticker_trends', 'desc:ve_cat_sticker_animation'):
            if s is not None and s.has(tab):
                ed.dev.tap(*s.find(tab).center)
                ed.idle(2)
                s = ed.ui.wait(T.STICKER_LIST, timeout=10)
                break
        tiles = s.items(T.STICKER_LIST) if s else []
        if tiles:
            return tiles
        ed.idle(5)
    raise UIError('sticker list still empty after 60 s online')


def _ge7a32fe_pick(ed, tile):
    mark = ed.log_mark()
    ed.dev.tap(*tile.center)
    if not ed.wait_log(r'MsgCreate\w*Sticker', 20, since=mark):
        raise UIError('no sticker was created')
    ed.idle(1.5)


def _ge7a32fe_drag(ed, r, seconds):
    """Drag the new sticker on the preview at human speed (dozens of MsgSetStickerCoordinates)."""
    s = ed.screen()
    n = s.find(('id:animated_sticker', 'id:root_sticker_view')) if s else None
    if n is None:
        raise UIError('new sticker view not on screen')
    x, y = n.center
    end = time.time() + seconds
    while time.time() < end:
        dx, dy = r.randint(-50, 50), r.randint(-60, 60)
        ed.dev.swipe(x, y, x + dx, y + dy, r.randint(900, 1500))
        x, y = x + dx, y + dy
        ed.idle(r.uniform(0.3, 0.8))


def _ge7a32fe_back_then_keyframe(ed, r, gap):
    """Back on the add panel: discardNewSticker deletes the sticker but keeps it selected; then the Keyframe diamond."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    if not ed.wait_log(r'MsgDeleteSticker', 5, since=mark):
        raise UIError('back did not discard the new sticker (no MsgDeleteSticker)')
    ed.idle(gap)
    if not ed.ui.tap('id:keyframe', timeout=4):
        raise UIError('Keyframe button (id keyframe) not visible after the discard')
    ed.settle(6)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l2_2_a(ed, r):
    """Field instance 2026-09-26 vivo V2321: add sticker, replace it with another, drag ~8 s, back, Keyframe 2.5 s later."""
    tiles = _ge7a32fe_open_stickers(ed, r)
    _ge7a32fe_pick(ed, tiles[0])                       # field sticker 0
    ed.idle(r.uniform(3, 6))
    _ge7a32fe_pick(ed, tiles[min(len(tiles) - 1, r.randint(1, 5))])   # replace: delete 0, create sticker 1
    _ge7a32fe_drag(ed, r, r.uniform(7, 9))
    ed.idle(r.uniform(3, 6))
    _ge7a32fe_back_then_keyframe(ed, r, gap=r.uniform(2.3, 2.8))


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l2_2_b(ed, r):
    """Field instance 2026-09-26 vivo V2321 (short path): one sticker, short drag, back, Keyframe 1.5-3 s later."""
    tiles = _ge7a32fe_open_stickers(ed, r)
    _ge7a32fe_pick(ed, r.choice(tiles[:6]))
    _ge7a32fe_drag(ed, r, r.uniform(3, 5))
    ed.idle(1)
    _ge7a32fe_back_then_keyframe(ed, r, gap=r.uniform(1.5, 3.0))


# 2026-10-20 23:29 level 2 attempt 3
def _ge7a32fe_fresh_project(ed):
    """New Project from the newest gallery video: a draft with zero stickers (the phone's draft 0 holds 4)."""
    ed.dev.network(True)                                     # sticker catalog comes from the server
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    ed.create_draft()
    ed.idle(4)
    ed.set_playing(False)


def _ge7a32fe_add_panel(ed):
    """Main nav -> Sticker entry (desc ve_btn_add_sticker_entry, scrolled into view) -> add panel tiles."""
    ed.main_nav()
    w, h = ed._screen_size()
    for _ in range(6):
        s = ed.screen()
        if s is not None and s.has('desc:ve_btn_add_sticker_entry'):
            ed.dev.tap(*s.find('desc:ve_btn_add_sticker_entry').center)
            break
        row = s.find(('desc:ve_tab_edit', 'desc:ve_tab_effects', 'desc:ve_btn_add_text_entry')) if s else None
        ed.dev.drag_no_fling(int(w * 0.85), row.center[1] if row else int(h * 0.93), int(w * 0.25))
        ed.idle(1)
    else:
        raise UIError('sticker entry (desc ve_btn_add_sticker_entry) not found after scrolling the main nav')
    ed.idle(1.5)
    ed.ui.tap('desc:ve_btn_add_sticker', timeout=3)          # only when a sticker submenu opens instead of the panel
    end = time.time() + 60
    while time.time() < end:
        s = ed.ui.wait(T.STICKER_LIST, timeout=10)
        tiles = s.items(T.STICKER_LIST) if s else []
        if tiles:
            return tiles
        ed.idle(4)
    raise UIError('sticker add panel opened but no tiles after 60 s online')


def _ge7a32fe_pick(ed, tile):
    mark = ed.log_mark()
    ed.dev.tap(*tile.center)
    if not ed.wait_log(r'MsgCreate\w*Sticker', 20, since=mark):
        raise UIError('tile tap created no sticker')
    ed.idle(1.5)


def _ge7a32fe_drag(ed, r, seconds):
    """Human drag of the new sticker on the preview (MsgSetStickerCoordinates); decorative if the view is not found."""
    s = ed.screen()
    n = s.find(('id:animated_image', 'id:sticker', 'id:surface_view')) if s else None
    if n is None:
        return
    x, y = n.center
    end = time.time() + seconds
    while time.time() < end:
        dx, dy = r.randint(-50, 50), r.randint(-60, 60)
        ed.dev.swipe(x, y, x + dx, y + dy, r.randint(900, 1500))
        x, y = x + dx, y + dy
        ed.idle(r.uniform(0.3, 0.8))


def _ge7a32fe_keyframe(ed, gap):
    ed.idle(gap)
    if not ed.ui.tap('id:keyframe', timeout=4):
        raise UIError('Keyframe button (id keyframe) hidden after the sticker was removed (stale selection not kept)')
    ed.settle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge7a32fe_l2_3_a(ed, r):
    """Instance 2026-09-26 vivo V2321 (full path): fresh project, sticker 0 replaced by 1, drag 8 s, back discards it, Keyframe 2.5 s later."""
    _ge7a32fe_fresh_project(ed)
    tiles = _ge7a32fe_add_panel(ed)
    _ge7a32fe_pick(ed, tiles[0])
    ed.idle(r.uniform(6, 10))
    _ge7a32fe_pick(ed, tiles[min(len(tiles) - 1, r.randint(1, 5))])   # replace: MsgDeleteSticker 0, create 1
    _ge7a32fe_drag(ed, r, r.uniform(7, 9))
    ed.idle(r.uniform(4, 8))
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')                               # discardNewSticker: PreviewState 0 + DeleteSticker + SaveDraft
    if not ed.wait_log(r'MsgDeleteSticker', 5, since=mark):
        raise UIError('back on the add panel did not discard the sticker')
    _ge7a32fe_keyframe(ed, r.uniform(2.3, 2.8))


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge7a32fe_l2_3_b(ed, r):
    """Instance 2026-09-26 vivo V2321 (short path): fresh project, one sticker, short drag, back discards it, Keyframe 1.5-3 s later."""
    _ge7a32fe_fresh_project(ed)
    tiles = _ge7a32fe_add_panel(ed)
    _ge7a32fe_pick(ed, r.choice(tiles[:6]))
    _ge7a32fe_drag(ed, r, r.uniform(3, 5))
    ed.idle(1)
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    if not ed.wait_log(r'MsgDeleteSticker', 5, since=mark):
        raise UIError('back on the add panel did not discard the sticker')
    _ge7a32fe_keyframe(ed, r.uniform(1.5, 3.0))


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge7a32fe_l2_3_c(ed, r):
    """Instance 2026-09-26 vivo V2321 (delete-tool variant): sticker applied, selected, deleted with Delete, back, Keyframe 2.5 s later."""
    _ge7a32fe_fresh_project(ed)
    tiles = _ge7a32fe_add_panel(ed)
    _ge7a32fe_pick(ed, r.choice(tiles[:6]))
    ed.ui.tap(T.STICKER_APPLY, timeout=5)                    # ve_btn_apply_sticker: the sticker stays live
    ed.idle(2)
    _ge7a32fe_drag(ed, r, r.uniform(3, 5))                   # drag also selects it -> sticker submenu
    mark = ed.log_mark()
    if not ed.ui.tap('desc:ve_btn_sticker_delete', timeout=6):
        raise UIError('sticker Delete tool (desc ve_btn_sticker_delete) not shown')
    if not ed.wait_log(r'MsgDeleteSticker', 5, since=mark):
        raise UIError('Delete tool did not delete the sticker')
    ed.dev.key('KEYCODE_BACK')
    _ge7a32fe_keyframe(ed, r.uniform(2.0, 3.0))


# 2026-10-20 23:34 level 3 attempt 1
def _ge7a32fe_open_picker(ed, r):
    """Editor -> Stickers entry. With no stickers the picker opens directly; otherwise tap the toolbar's Add."""
    ed.set_playing(False)
    ed.seek_to(r.uniform(0.25, 0.4))                  # field: sticker placed at the ~3 s playhead
    ed.main_nav()
    mark = ed.log_mark()
    try:
        ed.menu_tap('sticker')                        # desc ve_btn_add_sticker_entry
    except UIError:
        w, h = ed._screen_size()
        for _ in range(4):                            # bottom-bar item 6/12 sits off-screen: scroll and look
            ed.dev.drag_no_fling(int(w * 0.8), int(h * 0.93), int(w * 0.3))
            ed.idle(1)
            if ed.ui.tap('desc:ve_btn_add_sticker_entry', timeout=2):
                break
        else:
            raise UIError('sticker entry ve_btn_add_sticker_entry not reachable')
    if not ed.wait_log(r've_sticker_start', 4, since=mark):
        ed.ui.tap('desc:ve_btn_add_sticker', timeout=5)   # draft already has stickers: toolbar Add -> picker
    if not ed.ui.wait('id:stickers_recycler', timeout=30):
        raise UIError('sticker picker grid (stickers_recycler) never showed')
    ed.idle(2)


def _ge7a32fe_pick(ed, r, k):
    """Tap the k-th tile of the picker grid (4 columns) and wait until the engine creates the sticker."""
    s = ed.ui.wait('id:stickers_recycler', timeout=15)
    tiles = s.items(T.STICKER_LIST) if s is not None else []
    mark = ed.log_mark()
    if tiles:
        ed.dev.tap(*tiles[min(k, len(tiles) - 1)].center)
    else:
        w, _ = ed._screen_size()
        ed.dev.tap(int(w * (2 * (k % 4) + 1) / 8), s.find('id:stickers_recycler').center[1])
    if not ed.wait_log(r'MsgCreate\w*Sticker', 40, since=mark):
        raise UIError('tapping a sticker tile created no sticker in the engine')
    ed.idle(1.5)


def _ge7a32fe_drag(ed, r, seconds):
    """Drag the new sticker (placed at the preview centre) at human speed; decorative if it misses."""
    s = ed.screen()
    n = s.find(('id:root_sticker_view', 'id:surface_view')) if s is not None else None
    if n is None:
        return
    x, y = n.center
    end = time.time() + seconds
    while time.time() < end:
        dx, dy = r.randint(-40, 40), r.randint(-50, 50)
        ed.dev.swipe(x, y, x + dx, y + dy, r.randint(800, 1400))
        x, y = x + dx, y + dy
        ed.idle(r.uniform(0.3, 0.7))


def _ge7a32fe_setup(ed, r, replace):
    _ge7a32fe_open_picker(ed, r)
    _ge7a32fe_pick(ed, r, 0)                          # field sticker 0
    if replace:
        ed.idle(r.uniform(3, 6))
        _ge7a32fe_pick(ed, r, r.randint(1, 5))        # field: delete 0, create webp sticker 1
    _ge7a32fe_drag(ed, r, r.uniform(6, 9))            # ~100 MsgSetStickerCoordinates + MsgSaveDraft


def _ge7a32fe_back_keyframe(ed, r, before_tap=None):
    """Back closes the add panel: discardNewSticker -> MsgDeleteSticker, selection still on it; then Keyframe."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    if not ed.wait_log(r'MsgDeleteSticker', 5, since=mark):
        raise UIError('back did not discard the new sticker (no MsgDeleteSticker)')
    if before_tap:
        before_tap()
    ed.idle(r.uniform(2.0, 2.8))                       # field: 2.56 s from the delete to the tap
    if not ed.ui.tap('id:keyframe', timeout=4):
        raise UIError('Keyframe button (id keyframe) not visible after the discard')
    ed.settle(6)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l3_1_a(ed, r):
    """Instance 2026-09-26 vivo V2321: sticker replaced, dragged, back, Keyframe 2.5 s later on a slowed (low-end) phone."""
    _ge7a32fe_setup(ed, r, replace=True)
    ed.dev.slow_phone(r.randint(25, 40))             # vivo field phone: audio OVERRUNs in the last second
    try:
        _ge7a32fe_back_keyframe(ed, r)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l3_1_b(ed, r):
    """Instance 2026-09-26 vivo V2321: same path, preview playing (audio thread busy) + memory pressure before Keyframe."""
    _ge7a32fe_setup(ed, r, replace=True)
    def stress():
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
        ed.ui.tap('id:play', timeout=3)               # audio callback running as in the field's last 0.3 s
    ed.dev.slow_phone(r.randint(15, 30))
    try:
        _ge7a32fe_back_keyframe(ed, r, before_tap=stress)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge7a32fe_l3_1_c(ed, r):
    """Instance 2026-09-26 vivo V2321: sticker cache cleared + slow network so the webp loads for real, one sticker, back, Keyframe."""
    ed.dev.clear_app_cache()
    ed.dev.slow_network(r.choice((300, 600)))
    try:
        _ge7a32fe_setup(ed, r, replace=False)
    finally:
        ed.dev.slow_network(0)
    _ge7a32fe_back_keyframe(ed, r)
