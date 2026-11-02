# Night Shift lab fixture builder for 621b5926 (try 1)

@scenario('nightshift', 'auto', 'nodraft')
def ns_621b5926_fx(ed, r):
    """Fixture for Crashlytics VisualMedia::get_duration SIGSEGV (seek_media on stale id): 2 video clips on layer 0."""
    ed.fixture_begin()

    # The test draft opens with its long (~35 s) video clip as layer 0 media 0.
    ed.step('open test draft')
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path: .*', 30, since=mark,
                   why='test draft loaded its first video clip into layer 0')
    ed.idle(1.5)

    # Field: the app sends MsgSeekVideo 0/1 (seek time ~71 s) and sort lists for 2 ids, so layer 0 holds at
    # least 2 long clips. Add a second video through the editor's "+" and gallery picker.
    ed.step('add second clip')
    ed.main_nav()
    mark = ed.log_mark()
    ed.add_media()
    ed.require_log(r'MsgAddVideo: media_layer 0 path: .*', 45, since=mark,
                   why='second video clip reached the engine on layer 0 (media 1 exists)')
    ed.wait_loader(30)
    ed.idle(2)

    # Prove media 1 can be reached: seeking into the second half of the timeline lands in clip 1, with no crash.
    ed.step('settle at start')
    ed.main_nav()
    ed.seek_start()
    ed.idle(1)
    ed.check()

    ed.save_fixture('621b5926', 'Layer 0 holds 2 long video clips (test draft clip + one added from the gallery), '
                                'no other edits, playhead at 0; trigger = desync + delete clip 0 + seek to media 1')
