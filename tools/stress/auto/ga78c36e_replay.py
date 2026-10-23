# Night Shift engine replays for 2bc43cd6d24a25e5305f8167703618a8~a78c36e6 (turbo)


# 2026-10-15 12:24 attempt 1
def _total(ed):
    try:
        return max(2.0, float(str(ed.jni("getTotalDuration()")[-1]).split()[-1]))
    except Exception:
        return 10.0


def _storm(r, lo, hi, n, gap=(10, 60)):
    return ";".join("seekTo(%.3f);sleep(%d)" % (r.uniform(lo, hi), r.randint(*gap)) for _ in range(n))


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp1_a(ed, r):
    """Crashlytics a78c36e (get_frames_at / OptRun family): field order pause, preview 0, save, then seek storm on a plain clip."""
    t = _total(ed)
    for _ in range(12):
        ed.jni("seekTo(%.3f);sleep(40);pausePlaying();setPreviewState(false);sleep(30);saveDraft();setPreviewState(true);"
               % (t * 0.5) + _storm(r, t * 0.3, t * 0.8, 16), thread="bg")
        ed.jni("saveDraft();" + _storm(r, t * 0.3, t * 0.8, 10, (5, 25)), thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp1_b(ed, r):
    """Crashlytics a78c36e: speed curve on media 0, then seeks at the media end so fetchFrameDecoder's curve loop runs out without returning."""
    for idx in (1, 2, 3, 4):
        ed.jni("pausePlaying();setMediaCurveSpeed(0;%d;0);sleep(200);saveDraft()" % idx, thread="bg")
        t = _total(ed)
        ends = ";".join("seekTo(%.4f);sleep(%d)" % (t - r.uniform(0.0, 0.08), r.randint(15, 60)) for _ in range(14))
        ed.jni("seekToMediaEnd(0;0);sleep(60);" + ends + ";seekTo(%.3f);sleep(40);seekTo(%.3f)" % (t, t + 1.0), thread="bg")
        ed.jni(_storm(r, t * 0.2, t, 14), thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp1_c(ed, r):
    """Crashlytics a78c36e (OPPO path): seek storm, then media state changed by the message thread mid-fetch (edit state, trim, save)."""
    t = _total(ed)
    for i in range(10):
        a, b = r.uniform(0.0, t * 0.1), r.uniform(t * 0.85, t)
        ed.jni(_storm(r, t * 0.3, t * 0.9, 12, (5, 30)) +
               ";setEditMode(true);trimVideo(0;%.3f;%.3f;0);sleep(5);" % (a, b) +
               _storm(r, t * 0.3, t * 0.8, 6, (3, 15)) +
               ";pausePlaying();setPreviewState(false);saveDraft();setEditMode(false);setPreviewState(true);" +
               _storm(r, t * 0.3, t * 0.8, 8, (5, 20)), thread="bg")
        ed.jni("trimVideo(0;0.0;%.3f;0);saveDraft()" % t, thread="bg")
    ed.idle(5)


# 2026-10-15 12:26 attempt 2
def _total(ed):
    try:
        return max(2.0, float(str(ed.jni("getTotalDuration()")[-1]).split()[-1]))
    except Exception:
        return 10.0


def _storm(r, lo, hi, n, gap=(5, 40)):
    return ";".join("seekTo(%.3f);sleep(%d)" % (r.uniform(lo, hi), r.randint(*gap)) for _ in range(n))


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp2_a(ed, r):
    """Crashlytics a78c36e (get_frames_at): curve speed set, then seeks at/after the media end so fetchFrameDecoder's curve loop runs out with no return."""
    for idx in (1, 2, 3, 4, 5):
        ed.jni("pausePlaying();setMediaCurveSpeed(0,%d,0);sleep(250);setPreviewState(false);saveDraft();setPreviewState(true)" % idx, thread="bg")
        t = _total(ed)
        tail = ";".join("seekTo(%.4f);sleep(%d)" % (t - r.uniform(0.0, 0.12), r.randint(8, 40)) for _ in range(16))
        ed.jni("seekToMediaEnd(0,0);sleep(60);" + tail + ";seekTo(%.3f);sleep(30);seekTo(%.3f);" % (t, t + 0.5)
               + _storm(r, t * 0.5, t, 10), thread="bg")
        ed.jni("startPlaying();sleep(300);seekTo(%.3f);sleep(%d);pausePlaying()" % (t - 0.3, r.randint(300, 600)), thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp2_b(ed, r):
    """Crashlytics a78c36e (OptRun / get_frames_at): curve preset swapped by the message thread while the render thread fetches frames in a seek storm."""
    t = _total(ed)
    for i in range(14):
        a, b = r.randint(1, 5), r.randint(0, 5)
        ed.jni(_storm(r, t * 0.2, t * 0.9, 6, (3, 15)) + ";setMediaCurveSpeed(0,%d,0);" % a +
               _storm(r, t * 0.2, t * 0.9, 6, (2, 10)) + ";setMediaCurveSpeed(0,%d,0);" % b +
               _storm(r, t * 0.6, t, 6, (2, 10)), thread="bg")
        ed.jni("pausePlaying();setPreviewState(false);saveDraft();setPreviewState(true);" +
               _storm(r, t * 0.3, t * 0.95, 10, (3, 20)), thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_ga78c36e_rp2_c(ed, r):
    """Crashlytics a78c36e (OPPO order): seek storm, then trim/speed/edit-state changes and render stop mid-fetch, save, back-like preview off."""
    t = _total(ed)
    for i in range(10):
        s, e = r.uniform(0.0, t * 0.15), r.uniform(t * 0.8, t)
        ed.jni(_storm(r, t * 0.3, t * 0.9, 12, (3, 25)) +
               ";setEditMode(true);trimVideo(0,%.3f,%.3f,0);setVideoSpeed(%.2f,0,0);" % (s, e, r.choice([0.5, 2.0, 3.0])) +
               _storm(r, t * 0.2, t * 0.7, 6, (2, 10)) +
               ";shouldRenderFrame(false);pausePlaying();setPreviewState(false);saveDraft();setEditMode(false);"
               "shouldRenderFrame(true);setPreviewState(true);" + _storm(r, t * 0.2, t * 0.6, 8, (3, 15)), thread="bg")
        ed.jni("setVideoSpeed(1.0,0,0);trimVideo(0,0.0,%.3f,0);saveDraft()" % t, thread="bg")
    ed.idle(5)
