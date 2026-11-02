# Night Shift lab fixture builder for ge6a5791 (try 2)

_FX_GE6A5791_ADD = r'MsgAddVideo: media_layer ([1-9]\d*) path: \S+'


def _fx_ge6a5791_layer(line):
    import re
    m = re.search(_FX_GE6A5791_ADD, line or '')
    return int(m.group(1)) if m else None


@scenario('nightshift', 'auto', 'nodraft')
def ns_ge6a5791_fx(ed, r):
    """Fixture for Crashlytics [libMYJNILIB26.so] VisualMedia::append_remove_bg_track_mask: two stacked ~20 s video overlays."""
    ed.fixture_begin()
    ed.step('open a project without the wizard (new_project hangs on Full Editor)')
    if not ed.drafts():
        ed.remake_test_draft()
    if not ed.drafts():
        raise RuntimeError('no project in My Projects even after remake_test_draft; cannot build without the wizard')
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r've_draft_project_complete|MsgAddVideo: media_layer 0 ', 30, since=mark,
                   why='editor opened the project and loaded its base clip')
    ed.wait_log(r've_draft_project_complete', 10, since=mark)
    ed.idle(2)

    ed.step('overlay A: the lower overlay (field: layer 1 media 0, deleted later)')
    mark = ed.log_mark()
    la = ed.add_overlay_video(tag='ge6a5791_a', duration_s=20)
    line_a = ed.require_log(_FX_GE6A5791_ADD, 40, since=mark,
                            why='first video overlay reached the engine (MsgAddVideo on an overlay layer)')
    la = la if la is not None else _fx_ge6a5791_layer(line_a)
    ed.idle(2)
    ed.main_nav()

    ed.step('overlay B: the overlay the remove-bg build will target (sits above A)')
    mark = ed.log_mark()
    lb = ed.add_overlay_video(tag='ge6a5791_b', duration_s=20)
    line_b = ed.require_log(_FX_GE6A5791_ADD, 40, since=mark,
                            why='second ~20 s video overlay reached the engine (several hundred masks later)')
    lb = lb if lb is not None else _fx_ge6a5791_layer(line_b)
    if la is None or lb is None or la == lb:
        raise RuntimeError('overlays did not land on two distinct layers: A=%s B=%s' % (la, lb))
    if lb < la:
        raise RuntimeError('overlay B is not above A: A=%s B=%s' % (la, lb))
    ed.dev.marker('ge6a5791 fixture: overlay A layer %s, overlay B layer %s' % (la, lb))
    ed.idle(2)
    ed.main_nav()

    ed.save_fixture('ge6a5791', 'Base clip on layer 0 plus two fresh ~20 s video overlays on separate layers, '
                                'B above A (B = remove-bg build target, A = the overlay below it); no remove-bg applied')
