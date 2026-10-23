# Night Shift lab fixture builder for 501bb526 (try 3)

"""Lab fixture for Crashlytics 501bb526 (ANR condition_variable::wait in JNI_freezeProgrees after a speed apply)."""

_FX_501BB526_FRZ = r'MsgAddVideoFreezeDuration:\s+start_time \d+ , end_time \d+,layer_id 0'


def _fx_501bb526_add(ed, lo, hi, want, why):
    """Copy the gallery clip whose length is closest to `want` (within lo..hi) to a new path and add it, which forces a real transcode."""
    lens = [s for _, s in ed.dev.video_lengths() if lo <= s <= hi]
    if not lens:
        raise UIError('no gallery video between %d and %d s (push one to /sdcard/DCIM)' % (lo, hi))
    src_s = min(lens, key=lambda s: abs(s - want))
    ed.dev.fresh_video(tag='fx501_%d' % int(src_s), duration_s=src_s)
    mark = ed.log_mark()
    ed.add_media(pick=0)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', 600, since=mark, why=why)
    ed.settle(3)
    ed.main_nav()
    return src_s


def _fx_501bb526_freeze(ed, t, i):
    """Freeze APPLY needs a press held for 500 ms or more (START_FREEZE). Releasing sends STOP_FREEZE, and a freeze under 0.4 s is removed."""
    _, tot = ed.read_time()
    ed.seek_to(min(0.97, t / tot))
    s = ed.ui.wait(T.FREEZE_APPLY, timeout=5)
    if s is None:
        ed.main_nav()
        ed.tap_tool('freeze')
        s = ed.ui.wait(T.FREEZE_APPLY, timeout=10)
        if s is None:
            raise UIError('freeze panel shows no ve_btn_freeze_apply')
    x, y = s.find(T.FREEZE_APPLY).center
    mark = ed.log_mark()
    ed.dev.swipe(x, y, x, y, 1800)
    ed.require_log(_FX_501BB526_FRZ, 15, since=mark, why='freeze %d added on layer 0 at ~%.0f s' % (i, t))
    ed.settle(1.5)
    if ed.wait_log(r'MsgRemoveVideoFreezeDuration', 1, since=mark):
        raise UIError('freeze %d was removed as too short' % i)


@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_fx(ed, r):
    """Fixture for Crashlytics 501bb526: 2 long real clips at speed 1.0 with 7 Freeze-tool freezes on layer 0."""
    ed.fixture_begin()
    ed.open_draft()
    ed.main_nav()
    ed.set_playing(False)
    _, base = ed.read_time()                              # the test draft's own clip(s) come first
    long_s = _fx_501bb526_add(ed, 40, 120, 95, 'long clip (40-120 s) must reach the engine on layer 0')
    short_s = _fx_501bb526_add(ed, 12, 35, 20, 'about 20 s clip must reach the engine on layer 0')
    _, tot = ed.read_time()
    if not tot or tot < 100:                               # updateSlidersMaxValue is a Crashlytics-only log, so read the UI clock instead
        raise UIError('timeline is %s s; it needs about 100 s or more' % tot)
    offs = [base + long_s * f for f in (0.12, 0.3, 0.45, 0.6, 0.8)] + \
           [base + long_s + short_s * f for f in (0.25, 0.6)]
    ed.set_playing(False)
    ed.tap_tool('freeze')
    for i, t in enumerate(offs):                           # ascending order, so a play-forward seek never goes back
        ed.step('freeze %d at ~%.0f s' % (i + 1, t))
        _fx_501bb526_freeze(ed, t + 1.4 * i, i + 1)        # each earlier freeze adds ~1.3 s to the timeline
    ed.main_nav()
    ed.idle(3)
    ed.step('reopen: the freezes must load from the draft')
    ed.leave_editor()
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'MsgFreezeLoader layer_id 0', 40, since=mark,
                   why='draft open loads the Kotlin FREEZE items (freezeLoader on layer 0)')
    ed.require_log(_FX_501BB526_FRZ, 20, since=mark, why='engine re-adds the layer-0 freezes on open')
    ed.idle(3)
    ed.check()
    ed.save_fixture('501bb526', 'test draft + ~%d s and ~%d s fresh clips on layer 0 at speed 1.0 (total %s s), '
                                '7 freeze items: 5 at 12-80%% of the long clip, 2 in the short clip; no speed change'
                    % (long_s, short_s, tot))
