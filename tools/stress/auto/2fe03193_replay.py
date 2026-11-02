# Night Shift engine replays for 2fe03193209d272d69500de7526df59f (turbo)


# 2026-11-02 15:47 attempt 1
SILENT = '/data/user/0/com.myzesty/cache/ns_2fe03193_silent.mp4'
AUDIO = '/data/user/0/com.myzesty/cache/ns_2fe03193_audio.mp4'


def _ns_export(ed, path):
    # ExportManager.cpp:90: the audio track is muxed only if the timeline has audio
    ed.jni("pausePlaying()")
    ed.jni("exportVideo(%s,720,1280,30,1,2.0,true,none)" % path)
    for _ in range(80):
        if 'true' in str(ed.jni("isExportingFinished()")).lower():
            break
        time.sleep(0.5)


def _ns_files_then_audio_clip(ed):
    _ns_export(ed, AUDIO)        # default draft has a clip with audio -> mp4 with audio track
    ed.open_slideshow(2)         # images only -> video-only mp4
    _ns_export(ed, SILENT)
    ed.open_slideshow(2)         # fresh engine, not in export state
    out = str(ed.jni("addVideo(%s,60.0,2000000.0,0)" % AUDIO))
    nums = [int(t) for t in re.findall(r'-?\d+', out)]
    return nums[-1] if nums else 2


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_a(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: plain replaceMedia(audio clip -> video-only mp4)."""
    mid = _ns_files_then_audio_clip(ed)
    ed.jni("replaceMedia(%d,%s,0)" % (mid, SILENT))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_b(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: REVERSE preamble (speed 1, curve 0, trim 0) then replaceMedia."""
    mid = _ns_files_then_audio_clip(ed)
    ed.jni("setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);trimVideo(%d,0.0,2.0,0);"
           "sleep(100);replaceMedia(%d,%s,0)" % (mid, mid, mid, mid, SILENT))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_c(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: clip is media 0 with a live decoder after play/scrub, then reverse-replace."""
    _ns_files_then_audio_clip(ed)
    ed.jni("deleteMedia(1,0);deleteMedia(0,0)")    # drop the 2 slideshow images -> audio clip is media 0, like the field
    ed.jni("seekTo(0.0);startPlaying();sleep(800);pausePlaying();"
           "seekTo(1.2);sleep(60);seekTo(0.4);sleep(60);seekTo(0.0);sleep(150)")
    ed.jni("setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);trimVideo(0,0.0,2.0,0);"
           "replaceMedia(0,%s,0)" % SILENT)
    ed.idle(5)


# 2026-11-02 15:53 attempt 2
AUDIO = '/data/user/0/com.myzesty/cache/ns_2fe03193_audio.mp4'
SILENT = '/data/user/0/com.myzesty/cache/ns_2fe03193_silent.mp4'
IMG = '/data/user/0/com.myzesty/cache/ns_2fe03193_still.jpg'


def _ns_last_int(out, default):
    digits = ''.join(c if (c.isdigit() or c == '-') else ' ' for c in str(out).split('->')[-1]).split()
    return int(digits[-1]) if digits else default


def _ns_export(ed, path):
    # the export only finishes when getExportingProgress() is polled (ExportManager.cpp:324)
    ed.jni("pausePlaying();exportVideo(%s,720,1280,30,1,2.0,true,none)" % path)
    for _ in range(40):
        out = str(ed.jni("getExportingProgress();isExportingFinished()")).lower()
        if 'true' in out.split('isexportingfinished()')[-1]:
            break
        time.sleep(0.5)


def _ns_prep(ed):
    _ns_export(ed, AUDIO)                          # draft clip with audio -> mp4 with an audio track
    ed.jni("exportImage(%s)" % IMG)
    n = _ns_last_int(ed.jni("getMediaCounts(0)"), 1)
    ed.jni("addImage(%s,3000.0,1280,0)" % IMG)
    for i in range(n - 1, -1, -1):
        ed.jni("deleteMedia(%d,0)" % i)            # image-only timeline -> video-only mp4
    _ns_export(ed, SILENT)
    ed.open_slideshow(2)
    mid = _ns_last_int(ed.jni("addVideo(%s,60.0,2000000.0,0)" % AUDIO), 2)
    ed.jni("isVideoHaveAudio(0,%d);replaceMedia(%d,%s,0)" % (mid, mid, AUDIO))   # in_export_state activates every audio decoder
    return mid


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_a(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: free an ACTIVE audio decoder, then replaceMedia(audio clip -> video-only mp4)."""
    mid = _ns_prep(ed)
    for _ in range(4):
        m1 = _ns_last_int(ed.jni("addVideo(%s,60.0,2000000.0,0)" % AUDIO), mid + 1)
        ed.jni("replaceMedia(%d,%s,0)" % (mid, AUDIO))          # every decoder is now active, m1 included
        ed.jni("deleteMedia(%d,0);replaceMedia(%d,%s,0)" % (m1, mid, SILENT))  # the new decoder reuses m1's chunk (active=true)
        ed.jni("replaceMedia(%d,%s,0)" % (mid, AUDIO))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_b(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: field order (scrub, REVERSE preamble, replace with cached video-only mp4), repeated."""
    mid = _ns_prep(ed)
    for _ in range(6):
        ed.jni("startPlaying();sleep(400);pausePlaying();seekTo(1.2);sleep(60);seekTo(0.3);sleep(60);seekTo(0.0);sleep(120)")
        ed.jni("setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);trimVideo(%d,0.0,2.0,0);sleep(100);"
               "replaceMedia(%d,%s,0)" % (mid, mid, mid, mid, SILENT))
        ed.jni("replaceMedia(%d,%s,0)" % (mid, AUDIO))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp2_c(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: replace during playback so the audio thread reactivates the old decoder before it is freed."""
    mid = _ns_prep(ed)
    for _ in range(5):
        ed.jni("startPlaying();sleep(300);replaceMedia(%d,%s,0);sleep(150);replaceMedia(%d,%s,0)"
               % (mid, AUDIO, mid, SILENT))
        ed.jni("pausePlaying();sleep(100);replaceMedia(%d,%s,0)" % (mid, AUDIO))
    ed.idle(5)


# 2026-11-02 16:00 attempt 3
SILENT = '/data/user/0/com.myzesty/cache/ns_2fe03193_silent3.mp4'
IMG = '/data/user/0/com.myzesty/cache/ns_2fe03193_still3.jpg'


def _ns_val(out):
    return str(out).split('->')[-1].strip().lower()


def _ns_int(out, default=-1):
    t = ''.join(c if (c.isdigit() or c == '-') else ' ' for c in _ns_val(out)).split()
    return int(t[-1]) if t else default


def _ns_audio_clip(ed):
    for attempt in range(3):
        n = _ns_int(ed.jni("getMediaCounts(0)"), 0)
        for i in range(n):
            if 'true' in _ns_val(ed.jni("isVideoHaveAudio(0,%d)" % i)):
                return i, n
        ed.open_slideshow(3)
    return 0, _ns_int(ed.jni("getMediaCounts(0)"), 1)


def _ns_prep(ed):
    # video-only mp4: park every clip (detach), export an image-only timeline, restore the clips
    a, n = _ns_audio_clip(ed)
    ed.jni("pausePlaying()")
    ed.jni("exportImage(%s)" % IMG)
    ed.jni("addImage(%s,3000.0,1280,0)" % IMG)
    tokens = [_ns_int(ed.jni("detachMedia(0,0)"), 0) for _ in range(n)]
    ed.jni("exportVideo(%s,720,1280,30,1,2.0,true,none)" % SILENT)
    for _ in range(40):                      # ExportManager.cpp:324 finishes only when progress is polled
        ed.jni("getExportingProgress()")
        if 'true' in _ns_val(ed.jni("isExportingFinished()")):
            break
        time.sleep(0.5)
    for k, t in enumerate(tokens):
        ed.jni("restoreMedia(%d,%d)" % (t, k))
    ed.jni("deleteMedia(%d,0)" % n)          # drop the helper image
    ed.jni("seekTo(0.0);sleep(200)")
    return a


def _ns_reverse(ed, mid):
    # field order: REVERSE preamble (PlayerActivity speed 1, curve 0, trim from 0) then replaceMedia(cached video-only mp4)
    return ("setVideoSpeed(1.0,%d,0);setMediaCurveSpeed(%d,0,0);trimVideo(%d,0.0,1.0,0);sleep(100);"
            "replaceMedia(%d,%s,0)" % (mid, mid, mid, mid, SILENT))


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_a(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: REVERSE preamble + replaceMedia(audio clip -> video-only mp4), on fresh duplicates."""
    a = _ns_prep(ed)
    ed.jni(_ns_reverse(ed, a))
    for _ in range(6):                       # uninitialised `active` != 0 -> reset_state -> configure(null codec, null format)
        ed.jni("duplicateMedia(%d,0);sleep(150)" % a)
        ed.jni(_ns_reverse(ed, a + 1))
        ed.jni("sleep(150);deleteMedia(%d,0);sleep(150)" % (a + 1))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_b(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: free an ACTIVE AudioMCDecoder just before replace so the new one reuses its chunk (active=true)."""
    a = _ns_prep(ed)
    for _ in range(6):
        ed.jni("duplicateMedia(%d,0);duplicateMedia(%d,0);sleep(200)" % (a, a))
        # delete frees the active decoder on the looper thread; replace's `new AudioMCDecoder` follows directly
        ed.jni("deleteMedia(%d,0);" % (a + 2) + _ns_reverse(ed, a + 1))
        ed.jni("sleep(150);deleteMedia(%d,0);sleep(150)" % (a + 1))
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp3_c(ed, r):
    """Play [libmedia.so] AMediaCodec_configure null codec: field heap churn (free-shift drag, scrub, playback) then REVERSE replace."""
    a = _ns_prep(ed)
    for _ in range(5):
        ed.jni("duplicateMedia(%d,0);sleep(150)" % a)
        b = a + 1
        ed.jni(";".join("applyFreeShift(%d,%.3f,%.3f,0);applyFreeRotate(%d,0.0,0)"
                        % (b, r.uniform(-0.4, 0.4), r.uniform(-0.1, 0.1), b) for _ in range(8)))
        ed.jni("startPlaying();sleep(700);pausePlaying();seekTo(1.2);sleep(60);seekTo(0.4);sleep(60);seekTo(0.0);sleep(120)")
        ed.jni(_ns_reverse(ed, b))
        ed.jni("sleep(150);deleteMedia(%d,0);sleep(150)" % b)
    ed.idle(5)
