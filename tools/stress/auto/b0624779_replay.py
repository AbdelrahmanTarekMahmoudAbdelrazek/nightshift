# Night Shift engine replays for b0624779923c1f52e97b73f75b8c5950 (turbo)


# 2026-10-14 19:14 attempt 1
@scenario('nightshift', 'auto', 'replay')
def ns_b0624779_rp1_a(ed, r):
    """Crashlytics libc.so / MsgLooper::QueueMessage: late CoverActivity seekPreview -> JNI_seekTo after destroyPlayer."""
    ed.jni("seekTo(0.5);sleep(200);pausePlaying();sleep(100)", thread="bg")
    # teardown (MsgDestroyPlayer, Looper = nullptr), then the coroutine's late seek on a worker thread
    ed.jni("destroyPlayer();sleep(50);seekTo(1.0);seekTo(1.5)", thread="bg")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay')
def ns_b0624779_rp1_b(ed, r):
    """Crashlytics libc.so / MsgLooper::QueueMessage: main-thread surfaceDestroyed/onResume call after destroyPlayer."""
    ed.jni("pausePlaying();setPreviewState(false);sleep(100)", thread="main")
    # performStop path: destroyPlayer, then surfaceDestroyed and onResume-style isInBackgroundState on the UI thread
    ed.jni("destroyPlayer();onSurfaceDestroyed();isInBackgroundState(false)", thread="main")
    ed.idle(5)


@scenario('nightshift', 'auto', 'replay', 'nodraft')
def ns_b0624779_rp1_c(ed, r):
    """Crashlytics libc.so / MsgLooper::QueueMessage: ExportDialog.onResume -> isInBackgroundState with no player ever created."""
    time.sleep(1)
    # no createPlayer has run: Looper is still the nullptr from the JNIHelper constructor
    ed.jni("isInBackgroundState(true);sleep(50);isInBackgroundState(false);seekTo(0.0)", thread="main")
    ed.idle(5)
