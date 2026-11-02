# Night Shift lab fixture builder for ga30bf15 (try 3)

def _fx_ga30bf15_pick_len(ed, want=15.0):
    """Source video whose length is closest to the field overlay (~15 s)."""
    best = None
    for path, secs in ed.dev.video_lengths():
        if secs >= 8 and (best is None or abs(secs - want) < abs(best - want)):
            best = secs
    return best or want


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_fx(ed, r):
    """Fixture for Crashlytics [libMYJNILIB26.so] getAudioOverlayId SIGSEGV: draft with layer-0 video + layer-1 video overlay."""
    ed.fixture_begin()
    # Overlay source: a NEW ~15 s file, so it is the newest tile in the picker (first cell of the All tab).
    ed.dev.fresh_video(tag='ga30bf15_ovl', duration_s=_fx_ga30bf15_pick_len(ed))

    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', 60, since=mark,
                   why='draft opened with a layer-0 main video')
    ed.settle(2)

    # Overlay tile -> overlay sub-menu (OPEN_OVERLAY_MENU); its "Add" tile (ve_btn_overlay_add) opens the picker.
    ed.step('overlay menu')
    ed.tap_tool('overlay')
    ed.idle(1.0)
    ed.step('overlay add -> picker')
    ed.tap_tool('add')
    ed.ui.wait('mediaList', timeout=20)
    ed.idle(1.5)                               # let the grid's paging load fill the first cells

    mark = ed.log_mark()
    ed.step('select newest clip')
    ed.ui.tap('gridrl', timeout=10)            # first grid cell = newest = the fresh overlay copy
    ed.idle(1.0)
    ed.step('picker done')
    ed.ui.tap('done', timeout=10)

    # OVERLAY_REQ -> TranscodingFragment -> COMPLETE_TRANSCODING -> addOverlays -> Player.addVideo(layer 1)
    ed.require_log(r'MsgAddVideo: media_layer 1 path: \S+', 180, since=mark,
                   why='overlay video added on layer 1')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \S+ layer 1 mediaId 0', 30, since=mark,
                   why='overlay volume sent for layer 1 media 0 (the call the restore repeats)')
    ed.wait_loader(30)
    ed.settle(2)

    # Prove the saved draft restores the overlay on reopen (same restore path the field crash runs).
    ed.main_nav()
    ed.save_fixture('ga30bf15', 'Lab test draft: layer-0 main video + layer-1 ~15 s video overlay '
                                '(fresh copy ns_fresh_*_ga30bf15_ovl.mp4; stored path is whatever MsgAddVideo '
                                'media_layer 1 logged, likely files/outputs/transcoding-*.mp4: make that file '
                                'unreadable before reopening)')
