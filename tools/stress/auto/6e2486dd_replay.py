# Night Shift engine replays for 6e2486dde1f6797760258759f18a7333 (turbo)


# 2026-10-28 13:09 attempt 1
REV = '/data/user/0/com.myzesty/cache/transcoding-ns6e2486dd.mp4'


def _poll_reverse(ed, secs):
    end = time.time() + secs
    while time.time() < end:
        ed.jni('isReverseFinished()', thread='bg')
        time.sleep(0.5)


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp1_a(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: reverse clip 0 while playback audio is live (unsilenced)."""
    ed.jni('seekTo(0.0);resumePlaying();sleep(1500)', thread='bg')
    # reverse_video does not pause/silence AudioPlayer: Oboe callback + reverse audio thread share layer 0 queue
    ed.jni('setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);reverseVideo(0,%s,0)' % REV, thread='bg')
    _poll_reverse(ed, 35)
    ed.jni('abortReverse()', thread='bg')
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp1_b(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: field order - play to end (MsgAtEnd), speed/curve/trim reset, reverse."""
    d = float(ed.jni('getTotalDuration()', thread='bg')[-1])
    ed.jni('seekTo(%d.0);resumePlaying();sleep(2500)' % max(0, int(d) - 1500000), thread='bg')
    # at_end leaves isEndLastMethodCalled=true so pausePlaying is skipped; resume unmutes the still-running stream
    ed.jni('at_the_end();pausePlaying();resumePlaying();sleep(300)', thread='bg')
    ed.jni('setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);trimVideo(0,0.0,%d.0,0);reverseVideo(0,%s,0)'
           % (int(d), REV), thread='bg')
    _poll_reverse(ed, 35)
    ed.jni('abortReverse()', thread='bg')
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp1_c(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: reverse first, then resume playback repeatedly during reverse audio pass."""
    ed.jni('pausePlaying();reverseVideo(0,%s,0);sleep(200)' % REV, thread='bg')
    end = time.time() + 35
    while time.time() < end:
        # seekTo sets seek_flage -> reverse thread runs seek_medias synchronously while the callback pops the queue
        ed.jni('resumePlaying();sleep(%d);seekTo(%d.0);resumePlaying();sleep(%d);isReverseFinished()'
               % (r.randint(300, 900), r.randint(0, 5000000), r.randint(300, 900)), thread='bg')
    ed.jni('pausePlaying();abortReverse()', thread='bg')
    ed.idle(5)


# 2026-10-28 13:13 attempt 2
def _dur(ed):
    return float(ed.jni('getTotalDuration()', thread='bg')[-1].split('->')[-1])


REV = '/data/user/0/com.myzesty/cache/transcoding-ns6e2486dd2.mp4'


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp2_a(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: reverse_audio_thread caching get_frames_at(in_export) races the live Oboe callback on the shared mixer."""
    end = time.time() + 45
    while time.time() < end:
        # the playback callback is unsilenced, then the reverse thread drains layer 0 through the same AudioMixer
        ed.jni('seekTo(0.0);resumePlaying();sleep(400);reverseVideo(0,%s,0);sleep(%d);resumePlaying();sleep(%d);abortReverse()'
               % (REV, r.randint(300, 900), r.randint(600, 1800)), thread='bg')
    ed.jni('pausePlaying()', thread='bg')
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp2_b(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: a playback seek worker's seek_medias/reset_layer_queue runs while the reverse export and callback read layer 0."""
    d = _dur(ed)
    ed.jni('seekTo(0.0);resumePlaying();sleep(500);reverseVideo(0,%s,0)' % REV, thread='bg')
    end = time.time() + 40
    while time.time() < end:
        # seekTo (seconds) sets seek_flage: the callback spawns the detached seek_medias worker, and the reverse thread runs its synchronous one
        ed.jni('seekTo(%.2f);resumePlaying();sleep(%d);isReverseFinished()'
               % (r.uniform(0.0, max(0.5, d - 1.0)), r.randint(80, 400)), thread='bg')
    ed.jni('pausePlaying();abortReverse()', thread='bg')
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_6e2486dd_rp2_c(ed, r):
    """Crashlytics AudioLayer::getSamples SIGSEGV: field order at_end, unsilenced, speed/curve/trim, reverse, then finish reset_layer_queue under the live callback."""
    d = _dur(ed)
    ed.jni('seekTo(%.2f);resumePlaying();sleep(2500);at_the_end();resumePlaying();sleep(300)' % max(0.0, d - 1.5), thread='bg')
    ed.jni('setVideoSpeed(1.0,0,0);setMediaCurveSpeed(0,0,0);trimVideo(0,0.0,%.3f,0);reverseVideo(0,%s,0)' % (d, REV),
           thread='bg')
    end = time.time() + 45
    done = False
    while time.time() < end and not done:
        # keep playback audio live; isReverseFinished() true runs reset_layer_queue on the looper while the callback is inside getSamples
        out = ed.jni('resumePlaying();sleep(%d);isReverseFinished()' % r.randint(100, 300), thread='bg')
        done = 'true' in out[-1]
    if not done:
        ed.jni('abortReverse()', thread='bg')
    ed.jni('pausePlaying()', thread='bg')
    ed.idle(5)
