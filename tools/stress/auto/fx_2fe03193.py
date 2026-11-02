# Night Shift lab fixture builder for 2fe03193 (try 1)

@scenario('nightshift', 'auto', 'nodraft')
def ns_2fe03193_fx(ed, r):
    """Fixture for [libmedia.so] AudioMCDecoder::reset_state null codec on Reverse replace_media: one clip with audio on layer 0, from files/outputs."""
    ed.fixture_begin()
    # Fresh project, not the shared test draft (it has leftover overlays). A fresh source name makes the app transcode
    # the clip into files/outputs/transcoding-<n>.mp4, like the field photoUri, and leaves no cache/<same name> reversed file.
    # The clip has to stay outside cache/ because fixture snapshots do not keep the cache dir.
    mark = ed.log_mark()
    ed.new_project(tag='ns_2fe03193', duration_s=40)
    ed.require_log(r'MsgAddVideo: media_layer 0 path: \S+', 90, since=mark,
                   why='main clip (layer 0, media 0) added to the new project')
    out = ed.wait_log(r'MsgAddVideo: media_layer 0 path: \S*/files/outputs/transcoding-\d+\.mp4', 5, since=mark)
    ed.dev.marker('NSFX 2fe03193 layer0 path ' + ('files/outputs/transcoding (field-like)' if out else 'NOT files/outputs'))
    ed.require_log(r'MCAudioNormalizer initialized successfully', 30, since=mark,
                   why='the clip has an audio track and its audio decoder came up (old decoder has_audio=true)')
    # Opening must not take the decoder's no-audio early return: the field clip had audio before the reverse.
    if ed.wait_log(r'-Error-Audio-Constructor- no audio', 2, since=mark):
        ed.require_log(r'NS_IMPOSSIBLE_2fe03193_audio_present', 1, since=mark,
                       why='the new clip opened with no audio track; the field clip had audio')
    # Make sure the project, at speed 1 with nothing reversed, is in the saved draft before we leave.
    ed.settle(2)
    ed.save_fixture('2fe03193', 'New project: one fresh ~40 s video clip WITH audio on layer 0 (media 0), transcoded to '
                                'files/outputs/transcoding-<n>.mp4, speed 1, no curve, not reversed, no cache/<n>.mp4 reversed file yet')
