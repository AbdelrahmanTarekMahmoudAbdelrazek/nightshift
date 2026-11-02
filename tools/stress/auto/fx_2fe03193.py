# Night Shift lab fixture builder for 2fe03193 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_fx(ed, r):
    """Fixture for [libmedia.so] AudioMCDecoder::reset_state SIGSEGV on Reverse (cached file, no audio): one clip with audio on layer 0."""
    ed.fixture_begin()
    # Last two tries: create_draft on whatever video was newest in the gallery aborted the app (SIGABRT) before
    # the editor opened. new_project() first copies a known phone video (~35 s, the length of the clip that had
    # AAC audio in fixture 6e2486dd) to a fresh name, so the picker takes a clean, fresh copy and transcodes it for real.
    ed.step('new clean project from a fresh ~35 s video with audio')
    mark = ed.log_mark()
    ed.new_project(tag='fx2fe03193', duration_s=35)
    # Checkpoint 1: layer 0 / media 0 is a video clip at a durable path (the field photoUri was files/outputs/transcoding-<n>.mp4).
    line = ed.require_log(r'MsgAddVideo: media_layer 0 path: /\S+\.mp4', 60, since=mark,
                          why='main clip (layer 0, media 0) loaded into the engine')
    ed.dev.marker('fx 2fe03193 main clip: %s' % line[-160:])
    if '/cache/' in line:
        # Snapshots do not keep cache/: a project pointing there fails to reopen, so it would be a useless fixture.
        raise AssertionError('fixture clip points into cache/, not durable: ' + line)
    # The clip's audio decoder came up normally, so the decoder that the replace later destroys has has_audio=true.
    ed.require_log(r'MCAudioNormalizer initialized successfully', 30, since=mark,
                   why='main clip has an audio track and its audio decoder started')
    ed.settle(3)
    if ed.wait_log(r'-Error-Audio-Constructor- no audio', 1, since=mark):
        raise AssertionError('main clip opened without audio; the field clip had audio')
    if not ed.wait_log(r'MsgAddVideo: media_layer 0 path: \S*files/outputs/transcoding-\d+\.mp4', 1, since=mark):
        ed.dev.marker('fx 2fe03193 note: layer 0 path is not files/outputs/transcoding-*.mp4')
    ed.save_fixture('2fe03193', 'New project: layer 0 media 0 is one ~35 s video clip WITH audio (decoder up, normalizer ok), '
                                'durable path (not cache/), speed 1, not reversed, no reverse cache file yet')
