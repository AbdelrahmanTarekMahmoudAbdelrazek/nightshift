# Night Shift engine replays for 2fe03193209d272d69500de7526df59f (turbo)


# 2026-11-02 14:43 attempt 1
def _ns_2fe03193_jni(ed, calls, thread="bg"):
    out = ed.jni(calls, thread=thread)
    return out if isinstance(out, str) else "\n".join(str(x) for x in (out or []))

def _ns_2fe03193_ret(text, name):
    for line in text.splitlines():
        if ("jni " + name + "(") in line and "->" in line:
            return line.rsplit("->", 1)[1].strip()
    return ""

def _ns_2fe03193_setup(ed):
    """Find a layer-0 clip WITH audio, then build a video-only mp4 in the app cache.
    An image-only timeline exports with has_audio=false, so the mp4 has no audio track."""
    n = int(_ns_2fe03193_ret(_ns_2fe03193_jni(ed, "getMediaCounts(0)"), "getMediaCounts") or "1")
    idx = -1
    for i in range(n):
        if _ns_2fe03193_ret(_ns_2fe03193_jni(ed, "isVideoHaveAudio(0,%d)" % i), "isVideoHaveAudio") == "true":
            idx = i
            break
    assert idx >= 0, "draft has no clip with audio on layer 0"
    c = "/data/user/0/com.myzesty/cache/"
    png, silent = c + "ns_2fe03193.png", c + "transcoding-ns2fe03193.mp4"
    # frame -> png -> image clip appended at the end; park the audio clip so only the image is left
    _ns_2fe03193_jni(ed, "pausePlaying();exportImage(%s);addImage(%s,2.0,1280,0);sleep(800)" % (png, png))
    tok = _ns_2fe03193_ret(_ns_2fe03193_jni(ed, "detachMedia(%d,0)" % idx), "detachMedia")
    assert tok and tok != "0", "detachMedia failed"
    # the other clips must have no audio either, so detach all of them except the image (now the last one)
    toks = []
    m = int(_ns_2fe03193_ret(_ns_2fe03193_jni(ed, "getMediaCounts(0)"), "getMediaCounts") or "1")
    for _ in range(m - 1):
        toks.append(_ns_2fe03193_ret(_ns_2fe03193_jni(ed, "detachMedia(0,0)"), "detachMedia"))
    _ns_2fe03193_jni(ed, "exportVideo(%s,720,1280,30,1,2.0,true,);sleep(2500)" % silent)
    for _ in range(30):
        if _ns_2fe03193_ret(_ns_2fe03193_jni(ed, "isExportingFinished()"), "isExportingFinished") == "true":
            break
        time.sleep(0.5)
    for t in reversed(toks):
        _ns_2fe03193_jni(ed, "restoreMedia(%s,0)" % t)
    _ns_2fe03193_jni(ed, "restoreMedia(%s,%d);sleep(500)" % (tok, idx))
    ed.idle(1)
    return idx, silent


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_a(ed, r):
    """Crashlytics [libmedia.so] SIGSEGV AudioMCDecoder::reset_state: REVERSE preamble then replaceMedia with a video-only mp4 (field order)."""
    idx, silent = _ns_2fe03193_setup(ed)
    _ns_2fe03193_jni(ed, "setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);sleep(100);replaceMedia(%d,%s,0)"
                     % (idx, idx, idx, silent))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_b(ed, r):
    """Crashlytics [libmedia.so] reset_state: replaceMedia(video-only) while preview plays, so the old audio decoder is active."""
    idx, silent = _ns_2fe03193_setup(ed)
    _ns_2fe03193_jni(ed, "seekVideoIndex(%d,0);sleep(200);startPlaying();sleep(800);replaceMedia(%d,%s,0)"
                     % (idx, idx, silent))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_c(ed, r):
    """Crashlytics [libmedia.so] reset_state: replaceMedia(video-only) from the UI thread after edit-tool shifts and a seek away (undo/redo path)."""
    idx, silent = _ns_2fe03193_setup(ed)
    _ns_2fe03193_jni(ed, "applyFreeShift(%d,-0.1,0.05,0);applyFreeRotate(%d,0.0,0);seekToMediaEnd(%d,0);sleep(300)"
                     % (idx, idx, idx))
    _ns_2fe03193_jni(ed, "setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);replaceMedia(%d,%s,0)"
                     % (idx, idx, idx, silent), thread="main")
    ed.idle(5)


# 2026-11-02 14:50 attempt 2
C = "/data/user/0/com.myzesty/cache/"

def _j(ed, calls, thread="bg"):
    out = ed.jni(calls, thread=thread)
    return out if isinstance(out, str) else "\n".join(str(x) for x in (out or []))

def _ret(text, name):
    for line in text.splitlines():
        if ("jni " + name + "(") in line and "->" in line:
            return line.rsplit("->", 1)[1].strip()
    return ""

def _export(ed, path):
    _j(ed, "pausePlaying();exportVideo(%s,720,1280,30,1,1.5,true,)" % path)
    for _ in range(60):
        time.sleep(0.5)
        if _ret(_j(ed, "isExportingFinished()"), "isExportingFinished") == "true":
            break
    _j(ed, "seekTo(0.0);sleep(300)")

def _setup(ed):
    """Returns (index of a clip WITH audio, path of a video-only mp4). The silent mp4 is exported
    from an image-only base layer, so ExportManager has has_audio=false and writes no audio track."""
    voiced, silent, png = C + "ns2fe_voiced.mp4", C + "transcoding-ns2fe.mp4", C + "ns2fe.png"
    _export(ed, voiced)                                     # 1.5 s of the draft: has an audio track
    _j(ed, "exportImage(%s);addImage(%s,1.5,1280,0);sleep(600)" % (png, png))
    n = int(_ret(_j(ed, "getMediaCounts(0)"), "getMediaCounts") or "1")
    for _ in range(n - 1):                                  # drop every voiced clip; only the image is left
        _j(ed, "deleteMedia(0,0);sleep(250)")
    _export(ed, silent)
    _j(ed, "addVideo(%s,45.0,1500000.0,0);sleep(600)" % voiced)   # AudioMedia has_audio=true
    assert _ret(_j(ed, "isVideoHaveAudio(0,1)"), "isVideoHaveAudio") == "true", "re-added clip has no audio"
    return 1, silent


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_a(ed, r):
    """Crashlytics [libmedia.so] AudioMCDecoder::reset_state: field order speed(1)->curve(0)->trim(0,dur)->replaceMedia(video-only)."""
    idx, silent = _setup(ed)
    _j(ed, "applyFreeShift(%d,-0.1,0.02,0);applyFreeRotate(%d,0.0,0);sleep(200);"
           "setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);trimVideo(%d,0.0,1.5,0);sleep(100);"
           "replaceMedia(%d,%s,0)" % (idx, idx, idx, idx, idx, idx, silent))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_b(ed, r):
    """Crashlytics [libmedia.so] reset_state: replaceMedia(video-only) on the UI thread while the voiced clip's decoder is active in playback."""
    idx, silent = _setup(ed)
    _j(ed, "seekVideoIndex(%d,0);sleep(200);startPlaying();sleep(700)" % idx)
    _j(ed, "replaceMedia(%d,%s,0)" % (idx, silent), thread="main")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_c(ed, r):
    """Crashlytics [libmedia.so] reset_state: audio-side replace (has_audio kept) to a video-only file, then export resets every decoder."""
    idx, silent = _setup(ed)
    _j(ed, "replaceAudio(%s,0,%d,true);sleep(300);exportVideo(%sx.mp4,720,1280,30,1,1.0,true,)" % (silent, idx, C))
    ed.idle(5)
