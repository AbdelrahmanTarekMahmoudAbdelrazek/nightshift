# Night Shift auto repros for 2bc43cd6d24a25e5305f8167703618a8~e6a57918


# 2026-11-02 22:36 level 3 attempt 1
def _ge6a5791_bar(ed, row):
    """Select the overlay bar on timeline row `row` (0 = top) by a tap between its thumbs; return the (x, y) that answered."""
    s = ed.screen()
    rows = sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])
    if row >= len(rows):
        raise UIError(f'overlay row {row} not on the timeline ({len(rows)} rows)')
    L, T_, R, B = rows[row].b
    for x in range(L + 24, R - 10, max(30, (R - L) // 8)):
        mark = ed.log_mark()
        ed.dev.tap(x, (T_ + B) // 2)
        if ed.wait_log(r've_timeline_overlay', 2.5, mark):
            return x, (T_ + B) // 2
        time.sleep(1.1)
    raise UIError(f'no overlay bar answered on row {row}')


def _ge6a5791_start_removebg(ed, layer, media_id):
    """Overlay tools -> Remove BG -> Auto Removal on the selected overlay; require a long build that streams masks."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('Auto Removal (ve_tab_remove_bg_auto) not on screen (model not ready?)')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media_id}\b', 20, since=mark,
                   why='checkpoint 2: remove-bg build on the field (layer, media)')
    ed.require_log(r'masks planned from \d{3,} frames', 15, since=mark, why='checkpoint 2: hundreds of masks planned')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track through the sink')
    return mark


def _ge6a5791_move(ed, r, slow):
    """Event 1: build on (layer 2, media 0), delete the layer-1 overlay, drag the built bar onto row 1."""
    ed.new_project(tag='ns_ge6_base', duration_s=20)
    ed.seek_start()
    ed.add_overlay_video(tag='ns_ge6_o1', duration_s=6)                     # layer 1: the other overlay
    ed.seek_start()
    if ed.add_overlay_video(tag='ns_ge6_o2', duration_s=20) != 2:            # layer 2: the one being built
        raise UIError('second overlay did not land on layer 2')
    s = ed.screen()
    rows = sorted(s.find_all('id:range_slider'), key=lambda n: n.b[1])
    y_top = (rows[0].b[1] + rows[0].b[3]) // 2
    try:
        if slow:
            ed.dev.slow_phone(30)
        _ge6a5791_bar(ed, 1)
        _ge6a5791_start_removebg(ed, 2, 0)
        _ge6a5791_bar(ed, 0)                                                 # field -4.07 s: delete the OTHER overlay
        mark = ed.log_mark()
        ed.tap_tool('delete')
        ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 10, since=mark, why='layer-1 overlay deleted')
        if slow:
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(0.5, 1.5))
        x, y = _ge6a5791_bar(ed, len(sorted(ed.screen().find_all('id:range_slider'), key=lambda n: n.b[1])) - 1)
        mark = ed.log_mark()
        ed.dev.long_drag(x, y, x, y_top if y != y_top else y_top - 1, hold=1.0, steps=12)   # vertical drop on row 1
        ed.require_log(r'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer', 10, since=mark,
                       why='checkpoint 4: the built media moves to another layer while its build runs')
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l3_1_a(ed, r):
    """Event 1 (Firebase 10:02:50): remove-bg build on overlay (2,0), other overlay deleted, built bar dragged to row 1 -> SIGSEGV in append_remove_bg_track_mask."""
    _ge6a5791_move(ed, r, slow=False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l3_1_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): overlay split into 2 on layer 1, remove-bg on the right half (1,1), left half (1,0) deleted, then play."""
    ed.new_project(tag='ns_ge6_base', duration_s=20)
    ed.seek_start()
    ed.add_overlay_video(tag='ns_ge6_o1', duration_s=20)
    ed.seek_to(0.35)
    _ge6a5791_bar(ed, 0)
    mark = ed.log_mark()
    ed.tap_tool('split')
    ed.require_log(r'MsgSplitVideo', 10, since=mark, why='checkpoint 1: layer 1 holds 2 media (split overlay)')
    ed.idle(1.5)
    try:
        ed.dev.slow_phone(20)                                                 # the Vivo's software-decoder build was slow
        _ge6a5791_start_removebg(ed, 1, 1)                                    # split leaves the right half selected
        ed.seek_start()
        _ge6a5791_bar(ed, 0)                                                  # left half: first bar from the left
        mark = ed.log_mark()
        ed.tap_tool('delete')
        ed.require_log(r'MsgDeleteMedia: media_layer 1 media_id 0', 10, since=mark,
                       why='checkpoint 4: another media on the build layer deleted while the build runs')
        ed.idle(1.2)
        ed.ui.tap('id:play', timeout=5)                                       # field: MsgResumePlaying, ve_play_pause_btn
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l3_1_c(ed, r):
    """Event 1 (Firebase 10:02:50), harsher device: same move path on a slowed CPU with critical memory pressure to widen the looper's move window."""
    _ge6a5791_move(ed, r, slow=True)


# 2026-11-02 22:42 level 3 attempt 2
def _ge6a5791_rows(ed):
    s = ed.screen()
    return sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])


def _ge6a5791_bar(ed, row, right_of_center=False):
    """Tap an overlay bar on screen row `row` (others as fallback), sweeping from the playhead rightwards; return (x, y)."""
    rows = _ge6a5791_rows(ed)
    if not rows:
        raise UIError('no overlay rows (range_slider) on the timeline')
    order = [row] + [k for k in range(len(rows)) if k != row] if row < len(rows) else list(range(len(rows)))
    for k in order:
        L, T_, R, B = rows[k].b
        x0 = (L + R) // 2 + (40 if right_of_center else 20)      # timeline starts at the playhead (screen centre)
        for x in list(range(x0, R - 10, 60)) + list(range(L + 24, x0, 80)):
            mark = ed.log_mark()
            ed.dev.tap(x, (T_ + B) // 2)
            if ed.wait_log(r've_timeline_overlay', 2.5, mark):
                ed.log(f'    overlay row {k} selected at x={x}')
                return x, (T_ + B) // 2
            time.sleep(1.1)
    raise UIError(f'no overlay bar answered (asked row {row})')


def _ge6a5791_removebg(ed, layer, media_id):
    """Overlay tools -> Remove BG -> Auto Removal; require a build on (layer, media_id) that streams masks, then leave the panel."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                      # desc ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('Auto Removal (ve_tab_remove_bg_auto) not on screen')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media_id}\b', 20, since=mark,
                   why='checkpoint 2: remove-bg build on the field (layer, media)')
    ed.require_log(r'masks planned from \d{2,} frames', 15, since=mark, why='checkpoint 2: a long build is planned')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track through the sink')
    ed.main_nav()                                                 # field: ve_back_tool_btn while the build keeps running


def _ge6a5791_delete(ed, layer, media_id):
    mark = ed.log_mark()
    ed.tap_tool('delete')
    ed.ui.tap('id:firstBtn', timeout=3)                           # 'Delete Media?' sheet when it shows
    ed.require_log(rf'MsgDeleteMedia: media_layer {layer} media_id {media_id}\b', 10, since=mark,
                   why='overlay deleted on the looper while the build runs')
    if ed.wait_log(r'cancelled after \d+ masks', 0.5, since=mark):
        raise UIError('the app cancelled the build before the list change (not the field path)')


def _ge6a5791_move(ed, r, slow):
    """Event 1: other overlay A on its own layer, long overlay B on the next; Remove BG on B, delete A, drag B onto A's row."""
    ed.seek_start()
    la = ed.add_overlay_video(tag='ns_ge6_a', duration_s=6)
    ed.seek_start()
    lb = ed.add_overlay_video(tag='ns_ge6_b', duration_s=20)
    if lb == la:
        raise UIError('the two overlays share a layer: event 1 needs B on its own layer')
    ed.require_log(r'MsgGetLayerRenderOrder: \d+ slots', 30, why='checkpoint 1: overlays rendered on their layers')
    ed.seek_start()
    try:
        if slow:
            ed.dev.slow_phone(30)
        _ge6a5791_bar(ed, lb - 1)
        _ge6a5791_removebg(ed, lb, 0)
        ed.seek_start()
        _, ya = _ge6a5791_bar(ed, la - 1)                         # field -4.07 s: delete the OTHER overlay
        _ge6a5791_delete(ed, la, 0)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(0.4, 1.2))
        xb, yb = _ge6a5791_bar(ed, lb - 1)
        mark = ed.log_mark()
        ed.dev.long_drag(xb, yb, xb, ya if ya != yb else yb - 120, hold=1.0, steps=12)   # vertical drop on A's row
        ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {lb} new_layer', 10, since=mark,
                       why='checkpoint 4: the built media moves to another layer while its build runs')
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_2_a(ed, r):
    """Event 1 (Firebase 10:02:50): Remove BG on overlay B, other overlay deleted, B dragged to its row -> SIGSEGV in append_remove_bg_track_mask."""
    _ge6a5791_move(ed, r, slow=False)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_2_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): overlay split into 2 on one layer, Remove BG on the right half, left half deleted, then play."""
    ed.seek_start()
    lo = ed.add_overlay_video(tag='ns_ge6_s', duration_s=20)
    ed.require_log(r'MsgGetLayerRenderOrder: \d+ slots', 30, why='overlay rendered')
    ed.seek_start()
    ed.seek_swipe(-0.25, 300)                                     # playhead a few seconds into the overlay
    ed.idle(1)
    _ge6a5791_bar(ed, lo - 1)
    mark = ed.log_mark()
    ed.tap_tool('split')
    ed.require_log(r'MsgSplitVideo', 10, since=mark, why='checkpoint 1: the overlay layer holds 2 media')
    ed.idle(1.5)
    try:
        ed.dev.slow_phone(20)                                     # the Vivo built on a software decoder: a slow build
        _ge6a5791_bar(ed, lo - 1, right_of_center=True)           # right half = media_id 1
        _ge6a5791_removebg(ed, lo, 1)
        ed.seek_start()
        _ge6a5791_bar(ed, lo - 1)                                 # left half starts at the playhead
        _ge6a5791_delete(ed, lo, 0)                               # checkpoint 4: same-layer delete, no cancel
        ed.idle(1.2)
        ed.ui.tap('id:play', timeout=5)                           # field: MsgResumePlaying, ve_play_pause_btn
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_2_c(ed, r):
    """Event 1 (Firebase 10:02:50) on a slow phone: as _a with CPU load, so the build and the looper's move window both last longer."""
    _ge6a5791_move(ed, r, slow=True)


# 2026-11-02 22:53 level 3 attempt 3
def _ge6a5791_rows(ed):
    s = ed.screen()
    return sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])


def _ge6a5791_tap(ed, k, dx):
    """Tap overlay row k at dx px from the playhead (screen centre); return (x, y) if the app logged ve_timeline_OVERLAY."""
    rows = _ge6a5791_rows(ed)
    if k >= len(rows):
        return None
    L, T_, R, B = rows[k].b
    x, y = (L + R) // 2 + dx, (T_ + B) // 2
    time.sleep(1.1)                                              # onTimeLineClick drops taps within 1 s
    mark = ed.log_mark()
    ed.dev.tap(x, y)
    return (x, y) if ed.wait_log(r'(?i)ve_timeline_overlay', 2.5, mark) else None


def _ge6a5791_find(ed):
    """First row whose bar starts at time 0 (seek_start: bar begins at the playhead); (row, x, y) or None."""
    ed.seek_start()
    for k in range(len(_ge6a5791_rows(ed))):
        hit = _ge6a5791_tap(ed, k, 60)
        if hit:
            return (k,) + hit
    return None


def _ge6a5791_delete(ed, why, layer=None, media_id=None):
    mark = ed.log_mark()
    ed.tap_tool('delete')
    ed.ui.tap('id:firstBtn', timeout=3)                          # 'Delete Media?' sheet when it shows
    pat = rf'MsgDeleteMedia: media_layer {layer} media_id {media_id}\b' if layer is not None else r'MsgDeleteMedia: media_layer [1-9]'
    ed.require_log(pat, 10, since=mark, why=why)


def _ge6a5791_setup(ed, tag):
    """Delete overlays left by earlier runs (saved into the test draft), add ONE 20 s 1080x1920 overlay; return (layer, row, x, y)."""
    ed.set_playing(False)
    for _ in range(6):
        if not _ge6a5791_find(ed):
            break
        _ge6a5791_delete(ed, 'clean layout: old overlay removed')
        ed.main_nav()
    layer = ed.add_overlay_video(tag=tag, duration_s=20)
    ed.main_nav()
    hit = _ge6a5791_find(ed)
    if not hit:
        raise UIError('the new overlay bar did not answer a tap')
    return (layer,) + hit


def _ge6a5791_removebg(ed, layer, media_id):
    """Remove BG -> AI Removal on the selected overlay; require a long build streaming masks, then back out (field ve_back_tool_btn)."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                     # desc ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('AI Removal (ve_tab_remove_bg_auto) not on screen')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media_id}\b', 25, since=mark,
                   why='checkpoint 2: remove-bg build on the field (layer, media)')
    ed.require_log(r'masks planned from \d{3,} frames', 15, since=mark, why='checkpoint 2: hundreds of masks planned (1080x1920 30 fps source)')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track through the sink')
    ed.main_nav()
    return mark


def _ge6a5791_move(ed, r, slow):
    """Event 1: overlay dragged to row 2 (layer 2) BEFORE the build, Remove BG on it, then dragged back to row 1 mid-build."""
    layer, k, x, y = _ge6a5791_setup(ed, 'ns_ge6_mv')
    rows = _ge6a5791_rows(ed)
    if k + 1 >= len(rows):
        raise UIError('no empty overlay row below the bar to move it to')
    y1, y2 = y, (rows[k + 1].b[1] + rows[k + 1].b[3]) // 2
    mark = ed.log_mark()
    ed.dev.long_drag(x, y1, x, y2, hold=1.0, steps=12)           # safe move (no build yet): field build sat on layer 2
    line = ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {layer} new_layer \d+', 10, since=mark,
                          why='checkpoint 1: the overlay can move between layers (drag to another row)')
    lb = int(str(line).rsplit('new_layer ', 1)[1].split()[0])
    ed.idle(1.5)
    if not _ge6a5791_tap(ed, k + 1, 60):
        raise UIError('moved overlay bar did not answer on its new row')
    try:
        bmark = _ge6a5791_removebg(ed, lb, 0)
        if slow:
            ed.dev.slow_phone(30)                                # the Vivo's slow looper widens move->erase
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(1.0, 3.0))                             # field: move came 8 s into the build
        if not _ge6a5791_tap(ed, k + 1, 60):                     # field -2.32 s: ve_timeline_overlay
            raise UIError('built overlay bar did not answer before the move')
        if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=bmark):
            raise UIError('build was cancelled before the move (not the field path)')
        mark = ed.log_mark()
        ed.dev.long_drag(x, y2, x, y1, hold=1.0, steps=12)       # back onto row 1 while masks stream
        ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {lb} new_layer', 10, since=mark,
                       why='checkpoint 4: the built media moves to another layer while its build runs')
        ed.idle(8)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_3_a(ed, r):
    """Event 1 (Firebase 10:02:50): Remove BG build on overlay (2,0), bar dragged to row 1 mid-build -> SIGSEGV in append_remove_bg_track_mask."""
    _ge6a5791_move(ed, r, slow=False)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_3_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play V40 Lite): overlay split into (L,0)+(L,1), Remove BG on (L,1), (L,0) deleted, then play."""
    layer, k, x, y = _ge6a5791_setup(ed, 'ns_ge6_sp')
    ed.seek_swipe(-0.15, 300)                                    # playhead a few seconds into the overlay
    ed.idle(1)
    if not _ge6a5791_tap(ed, k, 80):
        raise UIError('overlay bar did not answer at the split point')
    mark = ed.log_mark()
    ed.tap_tool('split')
    ed.require_log(r'(?i)MsgSplit', 10, since=mark, why='checkpoint 1: layer holds 2 media (split overlay)')
    ed.main_nav()
    if not _ge6a5791_tap(ed, k, 120):                            # right half = media_id 1
        raise UIError('right half of the split overlay did not answer')
    try:
        bmark = _ge6a5791_removebg(ed, layer, 1)
        ed.dev.slow_phone(20)                                    # field Vivo: software decoder, slow build
        ed.idle(r.uniform(1.0, 2.5))
        if not _ge6a5791_tap(ed, k, -120):                       # left half = media_id 0
            raise UIError('left half of the split overlay did not answer')
        if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=bmark):
            raise UIError('build was cancelled before the delete (not the field path)')
        _ge6a5791_delete(ed, 'checkpoint 4: another media on the build layer deleted while the build runs', layer, 0)
        ed.idle(1.2)
        ed.ui.tap('id:play', timeout=5)                          # field: MsgResumePlaying, ve_play_pause_btn
        ed.idle(8)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l3_3_c(ed, r):
    """Event 1 (Firebase 10:02:50) on a slow phone: same move, CPU load + RUNNING_CRITICAL during the build widen the null-slot window."""
    _ge6a5791_move(ed, r, slow=True)


# 2026-11-02 22:58 level 4 attempt 1
def _ge6a5791_rows(ed):
    s = ed.screen()
    return sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])


def _ge6a5791_pick(ed, k, dxs=(40, 200, 420)):
    """Tap overlay row k at dx px from the playhead (screen centre); (x, y) once the app logs ve_timeline_overlay."""
    rows = _ge6a5791_rows(ed)
    if k >= len(rows):
        return None
    L, T_, R, B = rows[k].b
    for dx in dxs:
        x, y = (L + R) // 2 + dx, (T_ + B) // 2
        if not (L + 10 < x < R - 10):
            continue
        time.sleep(1.1)                                          # onTimeLineClick drops taps within 1 s
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        if ed.wait_log(r'(?i)ve_timeline_overlay', 2.0, mark):
            return x, y
    return None


def _ge6a5791_bars(ed):
    """Rows holding an overlay bar that starts at 0 s, as [(row, x, y)]; adds one 20 s overlay if fewer than 2 (Add allows < 4)."""
    ed.set_playing(False)
    ed.main_nav()
    ed.seek_start()
    bars = [(k,) + h for k in range(len(_ge6a5791_rows(ed))) for h in [_ge6a5791_pick(ed, k)] if h]
    if len(bars) < 2:
        ed.add_overlay_video(tag='ns_ge6_ov', duration_s=20)
        ed.main_nav()
        ed.seek_start()
        bars = [(k,) + h for k in range(len(_ge6a5791_rows(ed))) for h in [_ge6a5791_pick(ed, k)] if h]
    ed.log(f'    overlay bars on rows {[b[0] for b in bars]} of {len(_ge6a5791_rows(ed))}')
    return bars


def _ge6a5791_build(ed):
    """Remove BG -> AI Removal on the selected overlay; require a build streaming masks; back out like the field; (layer, media, mark)."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                     # desc ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('AI Removal (ve_tab_remove_bg_auto) not on screen')
    line = ed.require_log(r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+', 25, since=mark,
                          why='checkpoint 2: remove-bg build started on the overlay')
    ed.require_log(r'masks planned from \d{2,} frames', 15, since=mark, why='checkpoint 2: a long build is planned')
    ed.require_log(r'RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track through the sink')
    tail = str(line).split('layer ', 1)[1].split()
    ed.main_nav()                                                # field ve_back_tool_btn: the build keeps running
    if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=mark):
        raise UIError('build cancelled before the list change (not the field path)')
    return int(tail[0]), int(tail[2]), mark


def _ge6a5791_delete(ed, layer, media_id, why):
    mark = ed.log_mark()
    ed.tap_tool('delete')                                        # desc ve_btn_overlay_delete
    ed.ui.tap('id:firstBtn', timeout=3)                          # 'Delete Media?' sheet when it shows
    ed.require_log(rf'MsgDeleteMedia: media_layer {layer} media_id {media_id}\b' if layer else r'MsgDeleteMedia: media_layer [1-9]',
                   10, since=mark, why=why)


def _ge6a5791_move(ed, x, y_from, y_to, layer, media_id):
    mark = ed.log_mark()
    ed.dev.long_drag(x, y_from, x, y_to, hold=0.8, steps=10)     # vertical drop: applyLayerChange -> changeVisualMediaLayer
    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id {media_id} old_layer {layer} new_layer', 8, since=mark,
                   why='checkpoint 4: the built media moves to another layer while its build runs')


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_a(ed, r):
    """Event 1 (Firebase 10:02:50): build on an overlay, bar dragged to the next row the moment masks stream; 3 build/move cycles."""
    bars = _ge6a5791_bars(ed)
    k, x, y = bars[min(1, len(bars) - 1)]
    rows = _ge6a5791_rows(ed)
    used = {b[0] for b in bars}
    dst = next((j for j in range(len(rows)) if j not in used), k - 1 if k > 0 else k + 1)
    ydst = (rows[dst].b[1] + rows[dst].b[3]) // 2
    for cycle in range(3):
        try:
            if not _ge6a5791_pick(ed, k):
                raise UIError(f'overlay bar on row {k} did not answer')
            layer, mid, _ = _ge6a5791_build(ed)
            ed.idle(r.uniform(0.0, 1.5))                         # land inside the stream, not after it ends
            hit = _ge6a5791_pick(ed, k) or (x, y)                # field -2.32 s: ve_timeline_overlay
            _ge6a5791_move(ed, hit[0], hit[1], ydst, layer, mid)
            ed.idle(5)
        except UIError:
            if cycle == 0:
                raise
            break
        k, y, ydst = dst, ydst, y                                # next cycle drags it back
        dst = k
        ed.seek_start()


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): overlay split so layer L holds 2 media, build on the right half, left half (media 0) deleted mid-build, play."""
    bars = _ge6a5791_bars(ed)
    if len(bars) >= 4:                                           # room for the split piece (overlay limit 4)
        _ge6a5791_pick(ed, bars[-1][0])
        _ge6a5791_delete(ed, None, None, 'make room: one old overlay removed (no build running)')
        ed.main_nav()
    k = bars[0][0]
    ed.seek_start()
    ed.seek_swipe(-0.3, 400)                                     # playhead a few seconds into the overlay
    ed.idle(1)
    if not _ge6a5791_pick(ed, k, dxs=(-60, -140)):
        raise UIError('overlay bar under the playhead did not answer')
    mark = ed.log_mark()
    ed.tap_tool('split')                                         # desc ve_btn_overlay_split: both pieces stay on one layer
    ed.require_log(r'(?i)MsgSplit', 10, since=mark, why='checkpoint 1: the build layer holds 2 media')
    ed.main_nav()
    if not _ge6a5791_pick(ed, k, dxs=(80, 200)):                 # right half starts at the playhead
        raise UIError('right half of the split overlay did not answer')
    try:
        ed.dev.slow_phone(25)                                    # the Vivo's software-decoder build was slow
        layer, mid, _ = _ge6a5791_build(ed)
        if mid < 1:
            raise UIError(f'build landed on media_id {mid}: deleting the other piece would shift nothing')
        if not _ge6a5791_pick(ed, k, dxs=(-60, -160)):           # left half: media 0 on the SAME layer
            raise UIError('left half of the split overlay did not answer')
        _ge6a5791_delete(ed, layer, 0, 'checkpoint 4: another media on the build layer deleted while the build runs')
        for _ in range(r.randint(4, 8)):                         # field: MsgResumePlaying + ve_play_pause_btn after the delete
            ed.ui.tap_cached('id:play')
            ed.idle(r.uniform(0.2, 0.7))
        ed.idle(5)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto')
def ns_ge6a5791_l4_1_c(ed, r):
    """Event 1 full path (Firebase 10:02:50): build on overlay B, other overlay A deleted (-4.07 s), B dragged onto A's freed row on a slow phone."""
    bars = _ge6a5791_bars(ed)
    (ka, xa, ya), (kb, xb, yb) = bars[0], bars[1]
    if not _ge6a5791_pick(ed, kb):
        raise UIError(f'overlay B on row {kb} did not answer')
    layer, mid, _ = _ge6a5791_build(ed)
    if not _ge6a5791_pick(ed, ka):
        raise UIError(f'overlay A on row {ka} did not answer')
    _ge6a5791_delete(ed, None, None, 'field -4.07 s: the other overlay deleted while the build runs')
    ed.main_nav()
    try:
        ed.dev.slow_phone(30)                                    # widens the looper's move -> erase window
        hit = _ge6a5791_pick(ed, kb) or (xb, yb)
        _ge6a5791_move(ed, hit[0], hit[1], ya, layer, mid)
        ed.idle(6)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-02 23:02 level 4 attempt 2
def _ge6a5791_rows(ed):
    s = ed.screen()
    return sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])


def _ge6a5791_pick(ed, k, dxs=(30, 160, 320)):
    """Tap overlay row k just right of the playhead (screen centre); (x, y) once the app logs ve_timeline_overlay."""
    rows = _ge6a5791_rows(ed)
    if k >= len(rows):
        return None
    L, T_, R, B = rows[k].b
    for dx in dxs:
        x, y = (L + R) // 2 + dx, (T_ + B) // 2
        if not (L + 10 < x < R - 10):
            continue
        time.sleep(1.1)                                          # onTimeLineClick drops taps within 1 s
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        if ed.wait_log(r'(?i)ve_timeline_overlay', 2.0, mark):
            return x, y
    return None


def _ge6a5791_fresh(ed, n_overlays):
    """NEW project (the shared draft is at the 4-overlay cap, so Add never opened) + n fresh 20 s video overlays."""
    ed.new_project(tag='ns_ge6_base', duration_s=20)
    layers = []
    for i in range(n_overlays):
        ed.seek_start()
        layers.append(ed.add_overlay_video(tag=f'ns_ge6_ov{i}', duration_s=20))
        ed.main_nav()
    ed.seek_start()
    bars = [(k,) + h for k in range(len(_ge6a5791_rows(ed))) for h in [_ge6a5791_pick(ed, k)] if h]
    if len(bars) < n_overlays:
        raise UIError(f'checkpoint 1: {n_overlays} overlay bars expected, {len(bars)} answered')
    return layers, bars


def _ge6a5791_build(ed):
    """Remove BG -> AI Removal on the selected overlay; require a long build streaming masks; back out (field ve_back_tool_btn)."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                     # desc ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('AI Removal (ve_tab_remove_bg_auto) not on screen')
    line = ed.require_log(r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+', 25, since=mark,
                          why='checkpoint 2: remove-bg build started on the overlay')
    ed.require_log(r'masks planned from \d{2,} frames', 15, since=mark, why='checkpoint 2: a long build is planned')
    ed.require_log(r'removebg_mask_\d+|RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track')
    tail = str(line).split('layer ', 1)[1].split()
    ed.main_nav()
    if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=mark):
        raise UIError('build cancelled before the list change (not the field path)')
    return int(tail[0]), int(tail[2]), mark


def _ge6a5791_delete(ed, layer, media_id, why):
    mark = ed.log_mark()
    ed.tap_tool('delete')                                        # desc ve_btn_overlay_delete
    ed.ui.tap('id:firstBtn', timeout=3)                          # 'Delete Media?' sheet when it shows
    ed.require_log(rf'MsgDeleteMedia: media_layer {layer} media_id {media_id}\b', 10, since=mark, why=why)


def _ge6a5791_drag_storm(ed, r, x, y_a, y_b, layer, media_id, n):
    """Drag the built bar between two rows n times while masks stream; the first move must be the field's move."""
    mark = ed.log_mark()
    ed.dev.long_drag(x, y_a, x, y_b, hold=0.7, steps=8)          # vertical drop -> moveItemToLayer -> changeVisualMediaLayer
    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id {media_id} old_layer {layer} new_layer', 8, since=mark,
                   why='checkpoint 4: the built media moves to another layer while its build runs')
    for i in range(n - 1):
        y_a, y_b = y_b, y_a
        ed.idle(r.uniform(0.05, 0.4))
        _ge6a5791_pick(ed, [k for k, row in enumerate(_ge6a5791_rows(ed)) if abs((row.b[1] + row.b[3]) // 2 - y_a) < 20][0]
                       if any(abs((row.b[1] + row.b[3]) // 2 - y_a) < 20 for row in _ge6a5791_rows(ed)) else 0, dxs=(x - ed.dev.w // 2,)) if hasattr(ed.dev, 'w') else None
        ed.dev.long_drag(x, y_a, x, y_b, hold=0.7, steps=8)
    ed.idle(6)                                                   # let the in-flight sink calls land


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_2_a(ed, r):
    """Event 1 (Firebase 10:02:50): 2 overlays, Remove BG on one, other deleted, built bar dragged onto the freed row mid-build."""
    layers, bars = _ge6a5791_fresh(ed, 2)
    (kb, xb, yb), (ka, xa, ya) = bars[-1], bars[0]               # B = later-added bar, A = the other overlay
    try:
        ed.dev.slow_phone(25)                                    # Vivo V40 Lite speed: wider move window (:245 -> :260)
        if not _ge6a5791_pick(ed, kb):
            raise UIError('overlay B did not answer')
        layer, mid, _ = _ge6a5791_build(ed)
        if not _ge6a5791_pick(ed, ka):                           # field -4.07 s: delete the OTHER overlay mid-build
            raise UIError('overlay A did not answer')
        other = next(l for l in layers if l != layer)
        _ge6a5791_delete(ed, other, 0, 'field -4.07 s: the other overlay deleted while the build runs')
        ed.idle(r.uniform(0.3, 1.0))
        hit = _ge6a5791_pick(ed, kb) or (xb, yb)                 # field -2.32 s: ve_timeline_overlay on the built bar
        _ge6a5791_drag_storm(ed, r, hit[0], hit[1], ya, layer, mid, 1)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_2_c(ed, r):
    """Event 1 storm: Remove BG on the layer-2 overlay, its bar dragged to an empty row and back 6x while masks stream."""
    layers, bars = _ge6a5791_fresh(ed, 2)
    kb, xb, yb = bars[-1]
    rows = _ge6a5791_rows(ed)
    used = {b[0] for b in bars}
    dst = next((j for j in range(len(rows)) if j not in used), None)
    if dst is None:
        raise UIError('no empty overlay row to drag the bar to')
    ydst = (rows[dst].b[1] + rows[dst].b[3]) // 2
    if not _ge6a5791_pick(ed, kb):
        raise UIError('overlay B did not answer')
    layer, mid, _ = _ge6a5791_build(ed)
    hit = _ge6a5791_pick(ed, kb) or (xb, yb)
    _ge6a5791_drag_storm(ed, r, hit[0], hit[1], ydst, layer, mid, 6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_2_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): overlay split in 3 on one layer, Remove BG on the middle piece, piece 0 deleted mid-build, undo/redo + play storm."""
    layers, bars = _ge6a5791_fresh(ed, 1)
    k = bars[0][0]
    for frac in (0.33, 0.66):                                    # 3 media on one layer: media_id 0, 1, 2
        ed.seek_to(frac)
        if not _ge6a5791_pick(ed, k, dxs=(15, -15)):
            raise UIError('overlay piece under the playhead did not answer')
        mark = ed.log_mark()
        ed.tap_tool('split')                                     # desc ve_btn_overlay_split
        ed.require_log(rf'MsgSplitVideo: media_layer {layers[0]} ', 10, since=mark,
                       why='checkpoint 1: the build layer holds several media (field: media_id 1 on layer 1)')
        ed.main_nav()
    ed.seek_to(0.5)
    if not _ge6a5791_pick(ed, k, dxs=(15, -15)):
        raise UIError('middle piece did not answer')
    layer, mid, _ = _ge6a5791_build(ed)
    if mid == 0:
        raise UIError('build landed on media 0: the delete would cancel it (not the field path)')
    ed.seek_start()
    if not _ge6a5791_pick(ed, k, dxs=(30, 80)):
        raise UIError('piece 0 did not answer')
    _ge6a5791_delete(ed, layer, 0, 'checkpoint 4: another media on the build layer deleted mid-build (no cancel)')
    for _ in range(r.randint(3, 5)):                             # every undo/redo re-shifts the build layer's slots
        ed.undo(1, gap=r.uniform(0.1, 0.3))
        ed.redo(1, gap=r.uniform(0.1, 0.3))
    ed.ui.tap('id:play', timeout=5)                              # field -0.03 s: MsgResumePlaying + ve_play_pause_btn
    ed.idle(8)


# 2026-11-02 23:10 level 4 attempt 3
def _ge6a5791_rows(ed):
    s = ed.screen()
    return sorted(s.find_all('id:range_slider') if s is not None else [], key=lambda n: n.b[1])


def _ge6a5791_panel(ed):
    """Overlay rows only exist while the overlay tool panel is open: reopen it when a Back/settle closed it."""
    rows = _ge6a5791_rows(ed)
    if not rows:
        ed.main_nav()
        ed.tap_tool('overlay')
        ed.idle(1.0)
        rows = _ge6a5791_rows(ed)
    if not rows:
        raise UIError('overlay panel: no overlay rows (range_slider) on screen')
    return rows


def _ge6a5791_pick(ed, k, dxs=(40, 200, -200, 400)):
    """Tap overlay row k at dx from the playhead (row centre) until the app logs ve_timeline_overlay; (x, y) or None."""
    rows = _ge6a5791_panel(ed)
    if k >= len(rows):
        return None
    L, T_, R, B = rows[k].b
    cx, y = (L + R) // 2, (T_ + B) // 2
    for x in [cx + d for d in dxs] + list(range(L + 24, R - 10, max(30, (R - L) // 8))):
        if not (L + 10 < x < R - 10):
            continue
        time.sleep(1.1)                                          # onTimeLineClick drops taps within 1 s
        mark = ed.log_mark()
        ed.dev.tap(x, y)
        if ed.wait_log(r'(?i)ve_timeline_overlay', 2.0, mark):
            return x, y
    return None


def _ge6a5791_row_y(ed, k):
    b = _ge6a5791_panel(ed)[k].b
    return (b[1] + b[3]) // 2


def _ge6a5791_clip():
    return 20


def _ge6a5791_setup(ed, n):
    """NEW project + n fresh long video overlays (real transcodes); returns their layers."""
    lens = [d for _, d in ed.dev.video_lengths() if 10 <= d <= 40]
    dur = max(lens) if lens else 20                              # longest clip: hundreds of masks planned
    ed.new_project(tag='ns_ge6_base', duration_s=dur)
    ed.set_playing(False)
    mark = ed.log_mark()
    layers = [ed.add_overlay_video(tag=f'ns_ge6_ov{i}', duration_s=dur) for i in range(n)]
    ed.require_log(r'MsgGetLayerRenderOrder', 20, since=mark, why='checkpoint 1: overlay layers registered')
    if len(set(layers)) != n:
        raise UIError(f'checkpoint 1: expected {n} overlay layers, got {layers}')
    return layers


def _ge6a5791_build(ed, layer=None, media=None):
    """Remove BG -> AI Removal on the selected overlay; require a build streaming masks; Back (field ve_back_tool_btn)."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                     # desc ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('AI Removal (ve_tab_remove_bg_auto) not on screen')
    pat = (rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media}\b' if layer is not None
           else r'MsgStartNativeRemoveBgBuild: layer \d+ media_id \d+')
    line = ed.require_log(pat, 25, since=mark, why='checkpoint 2: remove-bg build started on the field (layer, media)')
    ed.require_log(r'masks planned from \d{2,} frames', 15, since=mark, why='checkpoint 2: a long build is planned')
    ed.require_log(r'removebg_mask_\d+|RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track')
    ed.dev.key('KEYCODE_BACK')                                   # leave the panel; the build keeps running
    ed.idle(0.8)
    if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=mark):
        raise UIError('build cancelled before the list change (not the field path)')
    t = str(line).split('MsgStartNativeRemoveBgBuild: layer ', 1)[1].split()
    return int(t[0]), int(t[2])


def _ge6a5791_moves(ed, r, k_src, k_dst, built, n):
    """Event 1 move, stormed: drag the bar under a live build to the other row; rebuild and drag back, n times."""
    for i in range(n):
        if built is None:
            if not _ge6a5791_pick(ed, k_src):
                raise UIError(f'bar on row {k_src} did not answer before the build')
            built = _ge6a5791_build(ed)
            ed.idle(r.uniform(0.3, 2.0))
        layer, mid = built
        hit = _ge6a5791_pick(ed, k_src)                          # field -2.32 s: ve_timeline_overlay
        if not hit:
            raise UIError('built bar did not answer before the move')
        ydst = _ge6a5791_row_y(ed, k_dst)
        mark = ed.log_mark()
        try:
            ed.dev.slow_phone(30)                                # Vivo-speed looper: wider move window (:245 -> :260)
            ed.dev.long_drag(hit[0], hit[1], hit[0], ydst, hold=0.8, steps=8)
            ed.require_log(rf'MsgChangeVisualMediaLayer: media_id {mid} old_layer {layer} new_layer \d+', 8, since=mark,
                           why='checkpoint 4: the built media moves to another layer while its build runs')
            ed.idle(3)
        finally:
            ed.dev.slow_phone(0)
        k_src, k_dst, built = k_dst, k_src, None


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_3_a(ed, r):
    """Event 1 (Firebase 10:02:50): 2 overlays, Remove BG on the upper one, the other deleted, built bar dragged onto its row mid-build; 4 cycles."""
    la, lb = _ge6a5791_setup(ed, 2)
    if not _ge6a5791_pick(ed, 1):
        raise UIError('overlay on row 1 did not answer')
    layer, mid = _ge6a5791_build(ed)
    other = la if layer == lb else lb
    ed.idle(r.uniform(0.5, 2.0))
    if not _ge6a5791_pick(ed, 0):                                # field -4.07 s: delete the OTHER overlay
        raise UIError('overlay on row 0 did not answer')
    mark = ed.log_mark()
    ed.tap_tool('delete')                                        # desc ve_btn_overlay_delete
    ed.ui.tap('id:firstBtn', timeout=3)                          # 'Delete Media?' sheet when it shows
    ed.require_log(rf'MsgDeleteMedia: media_layer {other} media_id 0\b', 10, since=mark,
                   why='field -4.07 s: the other overlay deleted while the build runs')
    _ge6a5791_moves(ed, r, 1, 0, (layer, mid), 4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_3_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): overlay split so its layer holds media 0+1, build on media 1, media 0 deleted mid-build, play; 3 cycles."""
    (layer,) = _ge6a5791_setup(ed, 1)
    for f in (0.3, 0.55, 0.8):
        ed.main_nav()
        ed.seek_to(f)
        if not _ge6a5791_pick(ed, 0, dxs=(-80, 80, -200)):
            raise UIError('overlay bar under the playhead did not answer')
        mark = ed.log_mark()
        ed.tap_tool('split')                                     # desc ve_btn_overlay_split
        ed.require_log(r'MsgSplitVideo', 10, since=mark, why='checkpoint 1: the overlay layer now holds 2 media')
        ed.idle(1.5)
        if not _ge6a5791_pick(ed, 0, dxs=(60, 150, 300)):        # right half = media_id 1
            raise UIError('right half did not answer')
        _ge6a5791_build(ed, layer, 1)
        ed.idle(r.uniform(0.3, 1.5))
        if not _ge6a5791_pick(ed, 0, dxs=(-60, -150, -300)):     # left half = media_id 0, same layer
            raise UIError('left half did not answer')
        try:
            ed.dev.slow_phone(30)
            mark = ed.log_mark()
            ed.tap_tool('delete')
            ed.ui.tap('id:firstBtn', timeout=3)
            ed.require_log(rf'MsgDeleteMedia: media_layer {layer} media_id 0\b', 10, since=mark,
                           why="checkpoint 4: another media on the build's own layer deleted mid-build")
            ed.idle(r.uniform(0.2, 1.2))
            ed.set_playing(True)                                 # field: MsgResumePlaying + ve_play_pause_btn
            ed.idle(3)
            ed.set_playing(False)
        finally:
            ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l4_3_c(ed, r):
    """Event 1 (Firebase 10:02:50) move only: one overlay dragged to row 2 (layer 2), Remove BG on it, dragged back mid-build; 4 cycles."""
    (layer,) = _ge6a5791_setup(ed, 1)
    hit = _ge6a5791_pick(ed, 0)
    if not hit:
        raise UIError('overlay bar did not answer')
    mark = ed.log_mark()
    ed.dev.long_drag(hit[0], hit[1], hit[0], _ge6a5791_row_y(ed, 1), hold=0.8, steps=8)   # no build yet: safe move
    ed.require_log(rf'MsgChangeVisualMediaLayer: media_id 0 old_layer {layer} new_layer \d+', 8, since=mark,
                   why='checkpoint 1: the overlay can move to a second layer (field build sat on layer 2)')
    ed.idle(1.5)
    _ge6a5791_moves(ed, r, 1, 0, None, 4)


# 2026-11-02 23:20 level 5 attempt 1
def _ge6a5791_setup(ed):
    """New project + one long overlay split at ~30 %: its layer L holds media 0 (left) and 1 (right, auto-selected)."""
    lens = [d for _, d in ed.dev.video_lengths() if 16 <= d <= 40]
    dur = min(lens) if lens else 20                              # >= 16 s like the field's 496-mask build
    ed.new_project(tag='ns_ge6_base', duration_s=dur)
    ed.set_playing(False)
    ed.seek_start()
    layer = ed.add_overlay_video(tag='ns_ge6_ov', duration_s=dur)
    ed.main_nav()
    ed.seek_to(0.3)
    ed.tap_tool('overlay')                                       # openOverlay re-selects the (only) overlay: no bar tap
    ed.idle(1.0)
    mark = ed.log_mark()
    ed.tap_tool('split')                                         # ve_btn_overlay_split -> right half selected
    ed.require_log(rf'MsgSplitVideo: media_layer {layer} media_id 0', 10, since=mark,
                   why='checkpoint 1: the overlay layer holds 2 media')
    ed.idle(1.5)
    return layer


def _ge6a5791_bar(ed, dx):
    """(x, y, h) on the overlay row, dx px from the playhead (left of it = left half, right = right half)."""
    l, r, _ = ed._track_y()
    x = (l + r) // 2 + dx
    s = ed.screen()
    rows = [n for n in (s.find_all('id:range_slider') if s is not None else []) if n.b[0] < x < n.b[2]]
    if not rows:
        raise UIError('checkpoint 1: no overlay bar at the playhead (overlay tool closed?)')
    n = min(rows, key=lambda n: n.b[1])
    return x, (n.b[1] + n.b[3]) // 2, n.b[3] - n.b[1]


def _ge6a5791_build(ed, layer, media):
    """Remove BG -> AI Removal on the selected half; a long build streams masks; Back (field ve_back_tool_btn)."""
    mark = ed.log_mark()
    ed.tap_tool('remove bg')                                     # ve_tab_overlay_remove_bg
    if not ed.ui.tap('desc:ve_tab_remove_bg_auto', timeout=15):
        raise UIError('AI Removal (ve_tab_remove_bg_auto) not on screen')
    ed.require_log(rf'MsgStartNativeRemoveBgBuild: layer {layer} media_id {media}\b', 25, since=mark,
                   why=f'checkpoint 2: build on ({layer},{media})')
    ed.require_log(r'masks planned from \d{2,} frames', 15, since=mark, why='checkpoint 2: a long build is planned')
    ed.require_log(r'removebg_mask_\d+|RemoveBgTrack: frame=', 20, since=mark, why='checkpoint 3: masks reach the track')
    ed.dev.key('KEYCODE_BACK')                                   # back to the overlay tools; the build keeps running
    ed.idle(0.8)
    if ed.wait_log(r'cancelled after \d+ masks', 0.3, since=mark):
        raise UIError('build cancelled before the list change (not the field path)')


def _ge6a5791_move(ed, dx, layer, media):
    """Long-press the half at dx and drop it on another row: applyRowChangeToRenderOrder -> moveItemToLayer."""
    x, y, h = _ge6a5791_bar(ed, dx)
    s = ed.screen()
    ys = sorted({(n.b[1] + n.b[3]) // 2 for n in (s.find_all('id:range_slider') if s is not None else [])} - {y})
    for yt in ([min(ys, key=lambda v: abs(v - y))] if ys else []) + [y + int(1.6 * h), y - int(1.6 * h)]:
        mark = ed.log_mark()
        ed.dev.long_drag(x, y, x, yt, hold=0.8, steps=10)
        if ed.wait_log(rf'MsgChangeVisualMediaLayer: media_id {media} old_layer {layer} new_layer \d+', 4, since=mark):
            ed.require_log(r'NS_HOOK layer_gap: changeVisualMediaLayer', 3, since=mark, why='hook held the moved slot null')
            ed.idle(5)
            return
    raise UIError('checkpoint 4: the bar drag never reached MsgChangeVisualMediaLayer')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l5_1_a(ed, r):
    """Event 1 (Firebase 10:02:50): build on (L,0), then that half dragged to another row mid-build; hook holds the moved slot null."""
    layer = _ge6a5791_setup(ed)
    x, y, _ = _ge6a5791_bar(ed, -150)
    ed.dev.tap(x, y)                                             # select the left half (media 0); the build line confirms it
    ed.idle(1.2)
    _ge6a5791_build(ed, layer, 0)
    try:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '1')
        _ge6a5791_move(ed, -150, layer, 0)
    finally:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l5_1_b(ed, r):
    """Event 2 (Firebase 09:15:12 + Play): build on (L,1), media 0 on the SAME layer deleted mid-build, then play; hook holds the erase's last slot null."""
    layer = _ge6a5791_setup(ed)
    _ge6a5791_build(ed, layer, 1)                                # right half, auto-selected by the split
    x, y, _ = _ge6a5791_bar(ed, -150)
    ed.dev.tap(x, y)                                             # select the left half (media 0)
    ed.idle(1.2)
    try:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '1')
        mark = ed.log_mark()
        ed.tap_tool('delete')                                    # ve_btn_overlay_delete
        ed.ui.tap('id:firstBtn', timeout=3)                      # 'Delete Media?' sheet when it shows
        ed.require_log(rf'MsgDeleteMedia: media_layer {layer} media_id 0\b', 10, since=mark,
                       why='checkpoint 4: the OTHER media on the build layer deleted (coordinator returns early)')
        ed.require_log(r'NS_HOOK layer_gap: delete_media', 3, since=mark, why='hook held the vacated slot null')
        ed.ui.tap('id:play', timeout=2)                          # field: MsgResumePlaying + ve_play_pause_btn
        ed.idle(5)
    finally:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_l5_1_c(ed, r):
    """Event 1 mechanism without a selection tap: build on the auto-selected right half (L,1), drag it to another row mid-build."""
    layer = _ge6a5791_setup(ed)
    _ge6a5791_build(ed, layer, 1)
    try:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '1')
        _ge6a5791_move(ed, 150, layer, 1)
    finally:
        ed.dev.setprop('debug.zesty.hook.layer_gap', '0')
