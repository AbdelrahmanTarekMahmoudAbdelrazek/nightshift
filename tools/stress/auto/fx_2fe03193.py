# Night Shift lab fixture builder for 2fe03193 (try 1)

@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_fx(ed, r):
    """Fixture for [libmedia.so] SIGSEGV in AudioMCDecoder::reset_state <- replace_media (Reverse, cached video-only file)."""
    ed.fixture_begin()
    # The field state just before the trigger: one video clip WITH audio on layer 0 (media 0), not reversed, speed 1,
    # no curve. Use a NEW clean project, not ed.open_draft(): the shared test draft holds overlays left by earlier
    # builders. The clip must point outside cache/: a cache/ clip does not survive a snapshot restore.
    mark = ed.log_mark()
    ed.new_project(tag='ns_fx_2fe03193', duration_s=20)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: /(?!data/user/0/com\.myzesty/cache/)\S+', 90, since=mark,
                   why='one video clip added on layer 0 (media 0), from durable media outside cache/')
    ed.require_log(r'-Pass-Audio-Constructor:- success to fetch the sample rate|primeDecoderForActualFormat',
                   60, since=mark, why='the clip has an audio track: its AudioMCDecoder built a codec')
    ed.wait_loader(60)
    ed.settle(2)
    ed.check()
    ed.save_fixture('2fe03193', 'New project: one ~20 s video clip with an audio track on layer 0 (media 0), source '
                                'outside cache/, speed 1, no curve, never reversed, playhead at start')
