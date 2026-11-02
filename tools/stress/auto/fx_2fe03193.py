# Night Shift lab fixture builder for 2fe03193 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_fx(ed, r):
    """Fixture for [libmedia.so] AudioMCDecoder::reset_state SIGSEGV on Reverse (cached file): one transcoded clip WITH audio."""
    ed.fixture_begin()
    # The shared test draft is gone or full of old overlays, so build a NEW project from a fresh copy of a phone video.
    # A new source path forces a real transcode, so layer 0 points at files/outputs/transcoding-<N>.mp4 like the field photoUri.
    mark = ed.log_mark()
    ed.new_project(tag='ns_2fe03193', duration_s=35)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S*/files/outputs/transcoding-\d+\.mp4', 90, since=mark,
                   why='layer-0 clip is the transcoded copy (files/outputs/transcoding-<N>.mp4), same as the field photoUri')
    ed.require_log(r'-Pass-Audio-Constructor:- success to fetch the sample rate', 30, since=mark,
                   why='media 0 has a real audio track (the field clip had audio before Reverse)')
    ed.wait_loader(30)
    ed.settle(2)
    # Prove the editor is up on this project (any engine message for media 0 after the load).
    ed.step('editor ready on the new single-clip project')
    ed.check()
    ed.save_fixture('2fe03193', 'New project: one ~35 s video clip WITH AAC audio on layer 0 (media 0), transcoded to '
                                'files/outputs/transcoding-<N>.mp4, speed 1, no curve, not reversed, no overlays')
