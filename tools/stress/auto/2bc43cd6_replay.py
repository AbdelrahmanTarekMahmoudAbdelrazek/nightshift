# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8 (turbo)


# 2026-10-14 14:06 attempt 1
@scenario('nightshift', 'auto', 'replay')
def ns_2bc43cd6_rp1_a(ed, r):
    """Firebase VisualTimeLine::get_media_starting_time SIGSEGV 0x0: recreated engine never got the clip (event 2)."""
    # Tear the live engine down and build a fresh one, as the field did at T-1.93s (MsgCreatePlayer).
    # The new engine's visual layer 0 is empty; the app still queries a clip's start time.
    ed.jni("destroyPlayer();sleep(500);createPlayer()", thread="main")
    ed.jni("sleep(400)", thread="main")
    # media_id>=1 drives the unchecked loop at VisualTimeLine.cpp:695 over an empty layer -> 0x0.
    ed.jni("getMediaStartingTime(0,1)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2bc43cd6_rp1_b(ed, r):
    """Firebase VisualTimeLine::get_media_starting_time SIGSEGV 0x0: layer 0 emptied, app still asks id 1 (event 1)."""
    # Empty visual layer 0 exactly as a failed add_video leaves it: zero objects.
    # Over-delete; the extra deleteMedia calls throw 'media_id bigger than visual objects number'
    # and are caught by the looper, just like the field's get_media_duration errors.
    empties = ";".join("deleteMedia(0,0)" for _ in range(12))
    ed.jni(empties, thread="main")
    ed.jni("sleep(200)", thread="main")
    # Start-time query for a clip the engine no longer has.
    ed.jni("getMediaStartingTime(0,1)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2bc43cd6_rp1_c(ed, r):
    """Firebase VisualTimeLine::get_media_starting_time SIGSEGV 0x0: field order id-0 ok then id>=1 crashes."""
    # Reproduce the field's escalating-id order on an empty layer 0.
    empties = ";".join("deleteMedia(0,0)" for _ in range(12))
    ed.jni(empties, thread="main")
    ed.jni("sleep(200)", thread="main")
    # get_media_duration throws and is caught (field: 'media_id bigger than visual objects number').
    ed.jni("getMediaDuration(1,0)", thread="bg")
    # media id 0 returns 0 (loop never runs) exactly as event 2 logged at T-0.00s...
    ed.jni("getMediaStartingTime(0,0)", thread="bg")
    # ...then the next start-time query, for id 1, runs the unchecked loop on the empty layer -> 0x0.
    ed.jni("getMediaStartingTime(0,1)", thread="bg")
    ed.idle(5)
