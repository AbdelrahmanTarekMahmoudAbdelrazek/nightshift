# Night Shift engine replays for 621b5926412e07c4e8a50c9aaa51aaf0 (turbo)


# 2026-10-29 18:06 attempt 1
def _count(ed):
    out = ed.jni("getMediaCounts(0)", thread="bg")
    nums = [int(t) for l in out for t in str(l).replace('=', ' ').replace(':', ' ').split() if t.lstrip('-').isdigit()]
    return nums[-1] if nums else 0

def _two_clips(ed):
    n = _count(ed)
    if n < 2:
        ed.jni("duplicateMedia(0,0);sleep(300)", thread="bg")
        n = _count(ed)
    return n

@scenario('nightshift', 'auto', 'replay')
def ns_621b5926_rp1_a(ed, r):
    """Crashlytics VisualMedia::get_duration: detach every clip, then seekVideoIndex(1) on the empty base layer."""
    n = _two_clips(ed)
    ed.jni(";".join(["detachMedia(0,0);sleep(100)"] * n), thread="bg")
    ed.jni("seekVideoIndex(0,0);sleep(300);seekVideoIndex(1,0);sleep(500)", thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_621b5926_rp1_b(ed, r):
    """Crashlytics VisualMedia::get_duration: field order: seek 1, detach 0, seek 1, detach last, play/at_end, seek 0, seek 1."""
    n = _two_clips(ed)
    ed.jni("pausePlaying();pausePlaying();seekVideoIndex(1,0);sleep(500)", thread="bg")
    ed.jni(";".join(["detachMedia(0,0);sleep(200)"] * (n - 1)), thread="bg")
    ed.jni("pausePlaying();seekVideoIndex(1,0);sleep(1000);detachMedia(0,0);sleep(300)", thread="bg")
    for _ in range(3):
        ed.jni("resumePlaying();sleep(400);pausePlaying();sleep(300)", thread="bg")
    ed.jni("seekVideoIndex(0,0);sleep(900);resumePlaying();sleep(300);seekVideoIndex(1,0);sleep(500)", thread="bg")
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_621b5926_rp1_c(ed, r):
    """Crashlytics VisualMedia::get_duration: empty the layer via detach, then any get_media_starting_time(0,1) caller (getMediaStartingTime, seekToMediaEnd)."""
    n = _two_clips(ed)
    ed.jni(";".join(["detachMedia(0,0);sleep(100)"] * n), thread="bg")
    ed.jni("getMediaStartingTime(0,1);sleep(300);seekToMediaEnd(0,0);sleep(300);seekVideoIndex(1,0);sleep(500)", thread="main")
    ed.idle(5)
