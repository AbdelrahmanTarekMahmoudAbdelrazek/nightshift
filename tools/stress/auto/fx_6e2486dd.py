# Night Shift lab fixture builder for 6e2486dd (try 2)

# Night Shift lab fixture builder for 6e2486dd (try 2)

def _fx_6e2486dd_pick_len(ed):
    """Length (s) of the gallery video closest to the field clip (~38 s, needs audio)."""
    lens = [s for _, s in ed.dev.video_lengths() if 30 <= s <= 60]
    return min(lens, key=lambda s: abs(s - 38)) if lens else 38


@scenario('nightshift', 'auto', 'nodraft')
def ns_6e2486dd_fx(ed, r):
    """Fixture for Crashlytics AudioLayer::getSamples(int) SIGSEGV: one ~38 s video+AAC clip on layer 0."""
    ed.fixture_begin()
    # Cold start lands on the developer menu; open_draft knows the way (REVAMP UI -> My Projects -> editor).
    ed.open_draft()
    # Back out to My Projects (BaseVideoEditorActivity), the only screen with the "New Project" tab.
    ed.leave_editor()
    # A NEW gallery path forces a real transcode (no cached result), like the field reverse source.
    ed.step('fresh ~38 s source video')
    ed.dev.fresh_video('ns6e2486dd', _fx_6e2486dd_pick_len(ed))
    # A new project from the newest gallery video: layer 0 holds media 0 only.
    ed.step('new single-clip project')
    mark = ed.log_mark()
    ed.create_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path: .*end_time: [1-9]\d{7}\.', 90, since=mark,
                   why='layer 0 media 0 is a long video clip (field trim end_time=37863998 us)')
    ed.wait_loader(120)
    ed.require_log(r'MsgAddAudio|AudioMCDecoder', 30, since=mark,
                   why='the clip has an audio track that the audio timeline decodes')
    # Short play to prove that playback opens the audio path on layer 0, then rewind to 0.
    ed.step('prove audio playback')
    mark = ed.log_mark()
    ed.set_playing(True)
    ed.require_log(r'MsgResumePlaying', 15, since=mark, why='playback starts on the fixture')
    ed.require_log(r'AudioMCDecoder|AudioMedia::|AUD layer 0|MCDecoder::stats', 15, since=mark,
                   why='the Oboe callback pulls layer 0 audio while playing')
    ed.idle(2)
    ed.set_playing(False)
    ed.seek_start()
    ed.check()
    ed.save_fixture('6e2486dd', 'Single ~38 s video clip with AAC audio on layer 0 (media 0 only), '
                    'fresh transcode, speed 1.0, no curve, not reversed, playhead at 0')
