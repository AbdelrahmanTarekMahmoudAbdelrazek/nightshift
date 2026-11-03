# Night Shift engine replays for 2fe03193209d272d69500de7526df59f (turbo)


# 2026-11-03 16:51 attempt 1
NOAUDIO = '/data/user/0/com.myzesty/cache/ns_noaudio.mp4'

def _plant_noaudio(ed):
    src = ed.dev.video_lengths()[0][0]                      # any phone video; ffmpeg strips its audio
    ed.dev.plant_app_file(src, 'cache/ns_noaudio.mp4', video_only=True)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_a(ed, r):
    """Crashlytics [libmedia.so] AudioMCDecoder::reset_state: Edit-tab Reverse cached-file order, then replace with a video-only file."""
    _plant_noaudio(ed)
    ed.jni('pausePlaying();setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);trimVideo(0,0.0,2.0,0);'
           f'sleep(110);replaceMedia(0,{NOAUDIO},0)', thread='bg')
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_b(ed, r):
    """Crashlytics [libmedia.so] AudioMCDecoder::reset_state: bare replaceMedia of the audio clip with a video-only file, nothing before it."""
    _plant_noaudio(ed)
    ed.jni(f'replaceMedia(0,{NOAUDIO},0);sleep(500);getMediaCounts(0)', thread='bg')
    ed.idle(5)

@scenario('nightshift', 'auto', 'replay')
def ns_2fe03193_rp1_c(ed, r):
    """Crashlytics [libmedia.so] AudioMCDecoder::reset_state: field state (canvas drags, seeks during playback) then Reverse-cache replace."""
    _plant_noaudio(ed)
    drags = ';'.join(f'applyFreeShift(0,{r.uniform(-0.4, 0.1):.3f},{r.uniform(-0.1, 0.05):.3f},0);applyFreeRotate(0,0.0,0)'
                     for _ in range(8))
    ed.jni(f'startPlaying();sleep(400);seekTo(1.2);sleep(150);seekTo(0.5);sleep(150);{drags};pausePlaying();sleep(200);'
           f'setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);trimVideo(0,0.0,2.0,0);sleep(110);'
           f'replaceMedia(0,{NOAUDIO},0)', thread='bg')
    ed.idle(5)
