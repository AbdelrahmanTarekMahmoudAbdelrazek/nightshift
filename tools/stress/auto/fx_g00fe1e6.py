# Night Shift lab fixture builder for g00fe1e6 (try 1)

def _fx_g00fe1e6_dur_line(ed, since):
    # The draft-load path (getMediaDurationByID, PlayerActivity.kt:4309) may log the clip length.
    # Some builds don't log it, so this check is optional; the MsgAddVideo check is the hard proof.
    return ed.wait_log(r'MsgGetMediaDuration: media_layer 0 media_id: 0, original: (\d+)', 15, since=since)


@scenario('nightshift', 'auto', 'nodraft')
def ns_g00fe1e6_fx(ed, r):
    """Fixture for ANR [split_config.arm64_v8a.apk] condition_variable::wait (getMediaDuration during trim-handle drags)."""
    ed.fixture_begin()
    # The field state is one long-ish video (15-60 s) on layer 0 with no overlays. Start a NEW clean project
    # from a fresh 30 s copy (new path = no transcode cache hit). The shared test draft from open_draft()
    # holds leftover overlays and clips of unknown length from earlier runs, so it does not match the field.
    ed.step('new project with one fresh 30 s clip')
    mark = ed.log_mark()
    ed.new_project(tag='g00fe1e6', duration_s=30)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', 60, since=mark,
                   why='the base clip (layer 0) reached the engine')
    ed.require_log(r'START .*PlayerActivity|Displayed .*PlayerActivity', 30, since=mark,
                   why='PlayerActivity editor is open on the new project')
    line = _fx_g00fe1e6_dur_line(ed, mark)
    if line:
        ed.dev.marker('fx g00fe1e6 clip length line: %s' % line.strip()[-120:])
    # No overlay, text, speed, trim or transition: the recipes do the trim-handle bursts themselves.
    ed.idle(2)
    ed.save_fixture('g00fe1e6', 'one fresh 30 s video clip on layer 0 (no overlays, untrimmed, speed 1.0) for trim-handle drags')
