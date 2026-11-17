# Night Shift lab fixture builder for ge6a5791 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_fx(ed, r):
    """Fixture for Crashlytics [libMYJNILIB26.so] VisualMedia::append_remove_bg_track_mask: overlay on L1 + long video overlay on L2."""
    ed.fixture_begin()
    # Clean project (the shared test draft holds leftover overlays from earlier builders).
    ed.new_project(tag='ge6a_base', duration_s=20)
    mark = ed.log_mark()
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+|ve_draft_media_applied_complete|PlayerActivity', 30,
                   since=mark - 60 if isinstance(mark, (int, float)) else mark, why='base clip on layer 0')
    ed.settle(2)

    # Overlay A: the layer-1 overlay the field user deleted later (short clip is fine).
    ed.step('overlay A (layer 1, short video)')
    la = ed.add_overlay_video(tag='ge6a_ovA', duration_s=8)
    if la != 1:
        raise UIError(f'overlay A landed on layer {la}, field needs layer 1')
    ed.wait_loader(90)
    ed.main_nav()
    ed.settle(3)

    # Overlay B: the long video overlay on layer 2 that Remove BG builds on (field: 497 frames, ~16 s).
    ed.step('overlay B (layer 2, long video)')
    lb = ed.add_overlay_video(tag='ge6a_ovB', duration_s=20)
    if lb != 2:
        raise UIError(f'overlay B landed on layer {lb}, field needs layer 2')
    ed.wait_loader(120)

    # Last run crashed on Back while overlay B was still loading inside the overlay panel:
    # let the engine finish (render order logged after an overlay add), then leave the panel calmly.
    mark = ed.log_mark()
    ed.wait_log(r'MsgGetLayerRenderOrder|MsgSetLayerRenderOrder', 20, since=mark)
    ed.set_playing(False)
    ed.settle(4)
    ed.main_nav()
    ed.settle(4)
    ed.check()

    ed.save_fixture('ge6a5791', 'new project: base clip L0, short video overlay on layer 1 (media 0), '
                                '~20 s fresh video overlay on layer 2 (media 0) for a long Remove BG build; no remove-bg yet')
