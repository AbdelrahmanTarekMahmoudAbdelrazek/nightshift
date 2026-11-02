# Night Shift tap repros for 4d05f9e74e77520b418eac3a355108f1 (from the engine repro + full field log)


# 2026-11-01 06:33 attempt 1
# Night Shift tapflow for Crashlytics "Native method - android.os.MessageQueue.nativePollOnce" (ANR, FindClass in dispatchVsync).

AI_ACT = 'com.ai.myzesty.base.presentation.AiFeatureActivity'
AI_EXTRAS = '--es ai_tool "image_to_video" --ei ADD_MEDIA -1'   # AiFeatureActivity.intent() (AI_MODEL_TYPE is Serializable: not passable)
SHOWN = r'(Displayed|wm_on_resume_called).*AiFeatureActivity'


def _home_screen(ed):
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(('textc:ai animate',)):
            return
        time.sleep(2)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_1_a(ed, r):
    """FULL: Crashlytics nativePollOnce ANR: home AI Animate -> Sleek Vehicle -> Generate (low credits) -> credits Continue x2."""
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'(Displayed|wm_on_resume_called).*com\.myzesty', timeout=20, since=mark, why='cold app start')
    _home_screen(ed)
    mark = ed.log_mark()
    ed.ui.tap(('textc:ai animate',), timeout=15)
    ed.idle(1)
    ed.ui.tap(('textc:sleek vehicle',), timeout=15)
    ed.require_log(SHOWN, timeout=20, since=mark, why='home_temp_selected -> AiFeatureActivity')
    mark = ed.log_mark()
    ed.ui.tap(('textc:generate',), timeout=30)
    ed.require_log(r'credits|AiFeature|ReactNative', timeout=15, since=mark, why='temp_generate_btn -> low credits screen')
    for i in range(2):                                   # field: credits_screen_tap_continue twice, 3.8 s apart
        mark = ed.log_mark()
        ed.ui.tap(('textc:continue',), timeout=15)
        ed.require_log(r'(Displayed|wm_on_resume_called|START u0)', timeout=15, since=mark, why=f'credits continue {i + 1}')
        ed.idle(r.uniform(3.0, 4.5))
    ed.settle(8)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_1_b(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR: cold direct launch of AiFeatureActivity (field extras / none / empty), home at once."""
    for extras in (AI_EXTRAS, '', '--es ai_tool ""', '--ei ADD_MEDIA 0'):
        ed.dev.force_stop()                              # HYBRID: cold process, onboarding/paywall flow skipped
        mark = ed.log_mark()
        ed.start_activity(AI_ACT, extras=extras, expect_crash=False)   # HYBRID: same intent as AiFeatureActivity.intent()
        ed.require_log(SHOWN, timeout=25, since=mark, why=f'AiFeatureActivity shown ({extras or "no extras"})')
        ed.idle(r.uniform(0.3, 0.7))                     # field BACKGROUND reports: 0.3-0.7 s after the screen opens
        ed.dev.key('KEYCODE_HOME')
        ed.idle(r.uniform(2, 5))
        ed.dev.launch()
        ed.settle(6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_1_c(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR: slow low-end phone + don't-keep-activities, cold AiFeatureActivity open/leave/return."""
    ed.dev.slow_phone(40)
    ed.dont_keep_activities(True)
    try:
        for _ in range(3):
            ed.dev.force_stop()                          # HYBRID: cold process, class loading races the first vsync
            mark = ed.log_mark()
            ed.start_activity(AI_ACT, extras=AI_EXTRAS, expect_crash=False)   # HYBRID
            ed.require_log(SHOWN, timeout=40, since=mark, why='AiFeatureActivity shown on slow phone')
            ed.dev.key('KEYCODE_HOME')
            ed.idle(r.uniform(1, 3))
            mark = ed.log_mark()
            ed.dev.launch()
            ed.require_log(r'(Displayed|wm_on_resume_called|wm_on_create_called)', timeout=30, since=mark,
                           why='back to app: recreated screen')
            ed.settle(10)
    finally:
        ed.dont_keep_activities(False)
        ed.dev.slow_phone(0)


# 2026-11-01 06:35 attempt 2
# Night Shift tapflow for Crashlytics "Native method - android.os.MessageQueue.nativePollOnce" (ANR, FindClass in
# dispatchVsync). The AI/credits/paywall screens of the realme timeline are NOT in the CPP-1.25.2 lab build
# (AiFeatureActivity: "Activity class does not exist"), so these recipes follow the engine-flavoured FOREGROUND reports:
# Xiaomi (PlayerActivity seek bursts -> back -> MsgSaveDraft at T-0) and vivo (playback, audio starving, 457 ms render).

FIX = '6e2486dd'                                      # ~35 s video with AAC audio on layer 0
PLAY = r'MsgResumePlaying'
PAUSE = r'MsgPausePlaying'
SEEK = r'MsgSeek|VideoPlayer::seek'
SAVE = r'MsgSaveDraft'


def _play_seek_bursts(ed, r, bursts, playing):
    """Field Xiaomi: several seek bursts on the timeline (optionally while playing), each one checked in the engine log."""
    if playing:
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(PLAY, timeout=10, since=mark, why='play: MsgResumePlaying')
        ed.idle(r.uniform(1.5, 3.0))
    for i in range(bursts):
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.8, 0.8), r.randint(60, 200))
        ed.require_log(SEEK, timeout=10, since=mark, why=f'seek burst {i + 1}')
        ed.idle(r.uniform(0.1, 0.5))


def _back_save(ed, r):
    """The trigger: back in PlayerActivity -> MsgSaveDraft; keep touching the screen so a wedged main thread shows as ANR."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    ed.require_log(SAVE, timeout=15, since=mark, why='back -> MsgSaveDraft (field T-0)')
    for _ in range(4):
        ed.dev.tap(360, 800)
        ed.idle(0.4)
    ed.settle(10)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_2_a(ed, r):
    """FULL: Crashlytics nativePollOnce ANR (editor variant): open draft, play, seek bursts, pause, back -> MsgSaveDraft."""
    ed.open_fixture(FIX)
    _play_seek_bursts(ed, r, bursts=r.randint(5, 9), playing=True)
    mark = ed.log_mark()
    ed.set_playing(False)
    ed.require_log(PAUSE, timeout=10, since=mark, why='pause: MsgPausePlaying')
    _play_seek_bursts(ed, r, bursts=r.randint(3, 6), playing=False)   # field: seek bursts until T-1.75 s
    ed.idle(r.uniform(1.0, 2.0))
    _back_save(ed, r)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_2_b(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR (vivo variant): starved playback audio, seeks while playing, back -> save."""
    ed.open_fixture(FIX)
    ed.dev.setprop('debug.zesty.hook.slow_audio_ms', str(r.choice([120, 150, 200])))   # HYBRID: field audio null frames
    try:
        _play_seek_bursts(ed, r, bursts=r.randint(6, 10), playing=True)
        ed.idle(r.uniform(0.5, 1.5))
        _back_save(ed, r)                             # real tap while playback still runs
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_4d05f9e7_2_c(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR on a slow low-end phone with busy storage: play, seeks, back -> MsgSaveDraft."""
    ed.open_fixture(FIX)
    ed.dev.slow_phone(40)                             # HYBRID: low-end field phones (render 457 ms)
    ed.dev.busy_storage(True)                         # HYBRID: draft save + class loading compete for slow I/O
    try:
        _play_seek_bursts(ed, r, bursts=r.randint(6, 10), playing=True)
        ed.trim_memory('RUNNING_LOW')
        mark = ed.log_mark()
        ed.set_playing(False)
        ed.require_log(PAUSE, timeout=20, since=mark, why='pause: MsgPausePlaying (slow phone)')
        _play_seek_bursts(ed, r, bursts=r.randint(3, 5), playing=False)
        _back_save(ed, r)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)


# 2026-11-01 06:36 attempt 3
# Night Shift tapflow for Crashlytics "Native method - android.os.MessageQueue.nativePollOnce" (ANR, FindClass in
# dispatchVsync). AiFeatureActivity / credits / t3 paywall / bg remover are NOT in the CPP-1.25.2 lab build, and
# fixture 6e2486dd is gone, so these recipes run on the runner's test draft and follow the engine FOREGROUND reports:
# Xiaomi (seek bursts -> back -> MsgSaveDraft at T-0) and vivo (playback, audio starving, 457 ms render).

PLAY = r'MsgResumePlaying'
PAUSE = r'MsgPausePlaying'
SEEK = r'VideoPlayer::seek requested'
SAVE = r'MsgSaveDraft'


def _seek_bursts(ed, r, n, playing):
    """Field Xiaomi: seek bursts on the timeline (optionally while playing), each one checked in the engine log."""
    if playing:
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(PLAY, timeout=10, since=mark, why='play -> MsgResumePlaying')
        ed.idle(r.uniform(1.5, 3.0))
    for i in range(n):
        mark = ed.log_mark()
        ed.seek_swipe(r.uniform(-0.8, 0.8), r.randint(60, 200))
        ed.require_log(SEEK, timeout=10, since=mark, why=f'seek burst {i + 1}')
        ed.idle(r.uniform(0.1, 0.5))


def _back_save(ed, taps=4):
    """TRIGGER (real key): Back in PlayerActivity -> MsgSaveDraft; then touch input so a wedged main thread ANRs."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    ed.require_log(SAVE, timeout=20, since=mark, why='back -> MsgSaveDraft (field T-0)')
    for _ in range(taps):
        ed.dev.tap(360, 800)
        ed.idle(0.4)
    ed.settle(10)


@scenario('nightshift', 'auto', 'tapflow')
def tf_4d05f9e7_3_a(ed, r):
    """FULL: Crashlytics nativePollOnce ANR (Xiaomi editor variant): play, seek bursts, pause, seeks, back -> MsgSaveDraft."""
    _seek_bursts(ed, r, r.randint(5, 9), playing=True)
    mark = ed.log_mark()
    ed.set_playing(False)
    ed.require_log(PAUSE, timeout=10, since=mark, why='pause -> MsgPausePlaying')
    _seek_bursts(ed, r, r.randint(3, 6), playing=False)   # field: seek bursts until T-1.75 s
    ed.idle(r.uniform(1.0, 2.0))
    _back_save(ed)


@scenario('nightshift', 'auto', 'tapflow')
def tf_4d05f9e7_3_b(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR (vivo variant): starved playback audio, seeks while playing, back -> save."""
    ed.dev.setprop('debug.zesty.hook.slow_audio_ms', str(r.choice([120, 150, 200])))   # HYBRID: field audio null frames
    try:
        _seek_bursts(ed, r, r.randint(6, 10), playing=True)
        ed.idle(r.uniform(0.5, 1.5))
        _back_save(ed)                                       # real Back while playback is still running
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')


@scenario('nightshift', 'auto', 'tapflow')
def tf_4d05f9e7_3_c(ed, r):
    """HYBRID: Crashlytics nativePollOnce ANR on a slow low-end phone with busy storage: play, seeks, back -> MsgSaveDraft."""
    ed.dev.slow_phone(r.randint(30, 45))                     # HYBRID: low-end field phones (457 ms render)
    ed.dev.busy_storage(True)                                # HYBRID: draft save and class loading compete for slow I/O
    ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '150')  # HYBRID: field 'AUD callback OVERRUN'
    try:
        _seek_bursts(ed, r, r.randint(6, 10), playing=True)
        ed.trim_memory('RUNNING_LOW')
        if r.random() < 0.5:                                 # half the runs: Back while still playing (vivo)
            mark = ed.log_mark()
            ed.set_playing(False)
            ed.require_log(PAUSE, timeout=20, since=mark, why='pause -> MsgPausePlaying (slow phone)')
            _seek_bursts(ed, r, r.randint(3, 5), playing=False)
        _back_save(ed, taps=8)
    finally:
        ed.dev.setprop('debug.zesty.hook.slow_audio_ms', '0')
        ed.dev.busy_storage(False)
        ed.dev.slow_phone(0)
