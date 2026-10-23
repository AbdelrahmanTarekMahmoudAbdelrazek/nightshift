# Night Shift auto repros for 85c581edcdb39b941df627e7b1324a71


# 2026-10-10 12:00 level 3 attempt 1
def _85c581ed_newest_jpg(ed):
    """Copy a JPG already on the phone to a new name so it is the newest item in the picker (fresh path, no cached copy)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg /sdcard/Download/*.jpg 2>/dev/null | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')   # field projects: exactly one 3 s image
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(2)


def _85c581ed_slideshow_one_jpg(ed, pressure):
    ed.dev.clear_app_cache()                         # field phones had no warm caches
    _85c581ed_newest_jpg(ed)
    ed.dev.sh(f'am send-trim-memory com.myzesty {pressure}')
    ed.open_slideshow(n=1)                           # home_slideshow_tap -> MsgCreatePlayer -> MsgAddImage -> GetMediaDuration x2 -> ss_start


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l3_1_a(ed, r):
    """Event 1 (Xiaomi M2004J19C): slideshow with one jpg, abort right at ss_start; cold cache, critical memory, a config change while the surface is live."""
    _85c581ed_slideshow_one_jpg(ed, 'RUNNING_CRITICAL')
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(r.uniform(0.1, 0.6))
    try:
        ed.dev.dark_mode(True)                       # recreates: QuickCutActivity closes to the start screen (MainActivity)
        ed.idle(3)
        ed.dev.sh('am send-trim-memory com.myzesty COMPLETE')
        ed.settle(5)
    finally:
        ed.dev.dark_mode(False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l3_1_b(ed, r):
    """Event 5 (Xiaomi M2006C3MII): slideshow just opened with one jpg, user backs out to MainActivity (ss_on_pause) under memory pressure."""
    for i in range(3):
        _85c581ed_slideshow_one_jpg(ed, 'RUNNING_LOW')
        ed.idle(r.uniform(0.2, 0.9))                 # field: ss_on_pause < 1 s after the engine settled
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.dev.key('KEYCODE_BACK')
        ed.idle(0.4)
        ed.dev.key('KEYCODE_BACK')                   # past a possible "discard?" dialog, back to MainActivity
        ed.idle(3)


@scenario('nightshift', 'auto')
def ns_85c581ed_l3_1_c(ed, r):
    """Event 6 (Xiaomi 220233L2I): video-editor New Project with one jpg, ve_on_resume/ve_on_pause flicker then MainActivity; camera + memory pressure."""
    ed.leave_editor()                                # My Projects (BaseVideoEditorActivity)
    ed.dev.clear_app_cache()
    _85c581ed_newest_jpg(ed)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab on My Projects')
    if ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20) is None:
        raise UIError('New Project did not open the gallery picker')
    ed.ui.tap('id:image_tab', timeout=5)
    ed.idle(1)
    s = ed.ui.wait('id:gridrl', timeout=10)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('the image tab shows no pictures')
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed.idle(0.5)
    ed._picker_confirm()
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.ui.wait(('id:surface_view', 'id:full_editor', 'id:addVideo'), timeout=30)   # MsgAddImage + GetMediaDuration x2
    ed.idle(r.uniform(0.2, 0.7))
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')                       # ve_on_pause
    ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(1.5)
    ed.dev.launch()                                  # ve_on_resume
    ed.idle(0.3)
    ed.mon.allow_death = False
    ed.dev.key('KEYCODE_BACK')                       # ve_on_pause -> screen_view MainActivity
    ed.idle(0.4)
    ed.dev.key('KEYCODE_BACK')
    ed.settle(5)


# 2026-10-10 12:13 level 3 attempt 2
def _85c581ed_newest_jpg(ed):
    """Copy a JPG on the phone to a new name so it is the newest picker item (one 3 s image, as in events 1 and 6)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg /sdcard/Download/*.jpg 2>/dev/null | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(2)


def _85c581ed_on_duration(ed, action, delay):
    """Phone-side waiter: run `action` `delay` s after the next MsgGetMediaDuration (adb round trips are too slow for the <1 s field window)."""
    cmd = (f'timeout 150 logcat -T 1 -v brief 2>/dev/null | grep -m1 MsgGetMediaDuration >/dev/null'
           f' && sleep {delay:.2f} && {action}')
    ed.dev.sh(f"nohup sh -c '{cmd}' >/dev/null 2>&1 &")


def _85c581ed_cycles(ed, r, action, after, n=3):
    ed.dev.setprop('debug.checkjni', '1')            # open_slideshow force-stops: the new process gets CheckJNI -> Abort message
    try:
        for i in range(n):
            ed.step(f'cycle {i + 1}/{n}: slideshow, 1 jpg, transition right after MsgGetMediaDuration')
            ed.dev.clear_app_cache()                 # field phones: no warm cache
            _85c581ed_newest_jpg(ed)
            _85c581ed_on_duration(ed, action, r.uniform(0.1, 0.8))
            ed.open_slideshow(n=1, wait=0)           # MsgCreatePlayer -> DONE -> MsgAddImage -> MsgGetMediaDuration x2
            ed.idle(3)                               # waiter fires in here
            after()
            ed.settle(4)
    finally:
        ed.dev.setprop('debug.checkjni', '0')
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l3_2_a(ed, r):
    """Events 5, 6 (Xiaomi M2006C3MII, 220233L2I): one-jpg slideshow, Back <1 s after MsgGetMediaDuration -> ss_on_pause -> MainActivity, critical memory."""
    _85c581ed_cycles(ed, r, 'am send-trim-memory com.myzesty RUNNING_CRITICAL & input keyevent 4',
                     lambda: (ed.dev.key('KEYCODE_BACK'), ed.idle(0.5)))   # past a possible discard dialog


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l3_2_b(ed, r):
    """Event 6 (Xiaomi 220233L2I): one-jpg project, Home <1 s after MsgGetMediaDuration, back (on_resume), then on_pause -> MainActivity; memory pressure."""
    def after():
        ed.dev.launch()                              # on_resume
        ed.idle(r.uniform(0.2, 0.4))
        ed.dev.key('KEYCODE_BACK')                   # on_pause -> MainActivity (surface still alive, no teardown first)
        ed.idle(0.4)
        ed.dev.key('KEYCODE_BACK')
    _85c581ed_cycles(ed, r, 'input keyevent 3 & am send-trim-memory com.myzesty RUNNING_CRITICAL', after)


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l3_2_c(ed, r):
    """Event 1 (Xiaomi M2004J19C): one-jpg slideshow just started (ss_start), config change <1 s after MsgGetMediaDuration -> MsgRefreshScreen on a live surface."""
    def after():
        ed.idle(1.5)
        ed.dev.rotate(False)                         # second config change back to portrait
        ed.idle(1)
    _85c581ed_cycles(ed, r, 'settings put system accelerometer_rotation 0; settings put system user_rotation 1', after)


# 2026-10-10 12:23 level 4 attempt 1
_85_LOGW = ("T=\"$(date '+%m-%d %H:%M:%S.000')\"; "
            "(timeout 8 logcat -T \"$T\" -v brief 2>/dev/null | grep -m1 MsgGetMediaDuration >/dev/null; "
            "sleep {d:.2f}; {act}) & sleep 0.25; input tap {x} {y}; wait")


def _85c581ed_newest_jpg(ed, i):
    """Copy a JPG to a new name so it is the newest picker tile (field: one 3 s image, no video)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg 2>/dev/null | grep -v NightShift | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}_{i}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')


def _85c581ed_home_screen(ed):
    """Back to MainActivity in the SAME process (no force-stop: the abort must be able to run)."""
    for _ in range(4):
        if ed.ui.wait('id:btnSlideShow', timeout=3) is not None:
            return
        ed.dev.key('KEYCODE_BACK')
    if ed.dev.pid() == '':
        ed.dev.launch()                              # only if it died on its own
    if ed.ui.wait('id:btnSlideShow', timeout=15) is None:
        raise UIError('MainActivity (btnSlideShow) not reached without a restart')


def _85c581ed_cycles(ed, r, act, n=20, after=None):
    """Same-process cycles: SlideShow -> 1 jpg -> Done; the phone fires `act` 30-300 ms after the first MsgGetMediaDuration."""
    ed.dev.setprop('debug.checkjni', '1')
    ed.open_slideshow(n=1, wait=60)                  # the only force-stop: new process starts with CheckJNI
    W, H = ed._screen_size()
    for i in range(n):
        ed.step(f'cycle {i + 1}/{n}: same process, slideshow + 1 jpg, transition on MsgGetMediaDuration')
        _85c581ed_home_screen(ed)
        _85c581ed_newest_jpg(ed, i)
        if not ed.ui.tap('id:btnSlideShow', timeout=10):
            raise UIError('no SlideShow button on MainActivity')
        s = ed.ui.wait(('id:select_cover', 'id:gridrl'), timeout=20)
        tiles = (s.find_all('id:select_cover') or s.find_all('id:gridrl')) if s is not None else []
        if not tiles:
            raise UIError('SlideShow picker shows no media')
        ed.dev.tap(*tiles[0].center)                 # newest = the fresh jpg
        ed.idle(0.6)
        a = act(i) if callable(act) else act
        ed.dev.marker(f'ns85 cycle {i + 1}: Done + watch MsgGetMediaDuration -> {a}')
        ed.dev.sh(_85_LOGW.format(d=r.uniform(0.03, 0.3), act=a, x=int(W * 0.86), y=H - 103), timeout=20)
        if after:
            after(i)
        ed.idle(r.uniform(0.8, 1.5))                 # no settle + force-stop: keep the process alive


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_1_a(ed, r):
    """Event 5 (Xiaomi M2006C3MII): one-jpg slideshow, Back 30-300 ms after MsgGetMediaDuration -> ss_on_pause -> MainActivity, 20x in one process."""
    try:
        _85c581ed_cycles(ed, r, 'input keyevent 4; sleep 0.15; input keyevent 4')
    finally:
        ed.dev.setprop('debug.checkjni', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_1_b(ed, r):
    """Event 1 (Xiaomi M2004J19C): one-jpg slideshow, ss_start + Play right as MsgGetMediaDuration lands (MsgRefreshScreen on the live surface), then Back."""
    W, H = ed._screen_size()
    def act(i):                                      # the play control sits under the preview; tap a few spots fast
        return f'input tap {W // 2} {int(H * 0.56)}; sleep 0.08; input tap {W // 2} {int(H * 0.56)}'
    def after(i):
        ed.slideshow_toggle_play()                   # decorative: second refresh while playing
        ed.idle(r.uniform(0.05, 0.3))
        ed.dev.key('KEYCODE_BACK')
    try:
        _85c581ed_cycles(ed, r, act, after=after)
    finally:
        ed.dev.setprop('debug.checkjni', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_1_c(ed, r):
    """Event 6 (Xiaomi 220233L2I): one-jpg project, Home right after MsgGetMediaDuration, back in (on_resume), Back ~0.3 s later (on_pause -> MainActivity)."""
    act = ('input keyevent 3; sleep 0.4; monkey -p com.myzesty -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; '
           'sleep 0.3; input keyevent 4; sleep 0.15; input keyevent 4')
    try:
        _85c581ed_cycles(ed, r, act)
    finally:
        ed.dev.setprop('debug.checkjni', '0')


# 2026-10-10 12:32 level 4 attempt 2
def _85c581ed_newest_jpg(ed, i):
    """Copy a JPG to a new name so it is the newest picker tile (field: one 3 s image, no video)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg 2>/dev/null | grep -v NightShift | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}_{i}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')


def _85c581ed_arm(ed, act, delay):
    """Phone-side watcher armed BEFORE Done: fires `act` `delay` s after the next MsgGetMediaDuration (Done lands ~2.5 s before the step log)."""
    cmd = f'timeout 40 logcat -T 1 -v brief 2>/dev/null | grep -m1 MsgGetMediaDuration >/dev/null && sleep {delay:.2f} && {act}'
    ed.dev.sh(f"nohup sh -c '{cmd}' >/dev/null 2>&1 &")


def _85c581ed_home(ed):
    """Back to MainActivity in the SAME process (no force-stop between cycles)."""
    for _ in range(4):
        if ed.ui.wait('id:btnSlideShow', timeout=3) is not None:
            return
        ed.dev.key('KEYCODE_BACK')
    if ed.dev.pid() == '':
        ed.dev.launch()
    if ed.ui.wait('id:btnSlideShow', timeout=15) is None:
        raise UIError('MainActivity (btnSlideShow) not reached without a restart')


def _85c581ed_cycles(ed, r, act, n=15):
    """Slideshow + 1 jpg -> Done; `act` fires 30-400 ms after MsgGetMediaDuration on the live surface; repeat in one process."""
    ed.dev.restore_env()                             # internet ON: offline hides layout_group (rvMedias/add_video)
    ed.dev.network(True)
    ed.dev.setprop('debug.checkjni', '1')
    try:
        _85c581ed_newest_jpg(ed, 0)
        ed.open_slideshow(n=1, wait=0)               # only force-stop: new process gets CheckJNI; do NOT wait on rvMedias
        if ed.ui.wait('id:surface_view', timeout=30) is None:
            raise UIError('slideshow editor (surface_view) did not open after Done')
        s = ed.screen()
        play = s.find('id:play') if s is not None else None
        px, py = play.center if play is not None else (ed.dev.w // 2, int(ed.dev.h * 0.56))
        for i in range(n):
            ed.step(f'cycle {i + 1}/{n}: same process, slideshow + 1 jpg, transition on MsgGetMediaDuration')
            _85c581ed_home(ed)
            _85c581ed_newest_jpg(ed, i + 1)
            if not ed.ui.tap('id:btnSlideShow', timeout=10):
                raise UIError('no SlideShow button on MainActivity')
            s = ed.ui.wait(('id:select_cover', 'id:gridrl'), timeout=20)
            tiles = (s.find_all('id:select_cover') or s.find_all('id:gridrl')) if s is not None else []
            if not tiles:
                raise UIError('SlideShow picker shows no media')
            ed.dev.tap(*tiles[0].center)
            ed.idle(0.5)
            a = act(px, py)
            ed.dev.marker(f'ns85 cycle {i + 1}: arm {a}')
            _85c581ed_arm(ed, a, r.uniform(0.03, 0.4))
            ed._picker_confirm()                     # MsgAddImage -> MsgGetMediaDuration x2 -> watcher fires
            ed.ui.wait('id:surface_view', timeout=10)
            ed.idle(r.uniform(1.0, 2.0))
        ed.settle(5)
    finally:
        ed.dev.setprop('debug.checkjni', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_2_a(ed, r):
    """Event 5 (Xiaomi M2006C3MII): one-jpg slideshow, Back 30-400 ms after MsgGetMediaDuration -> ss_on_pause -> MainActivity, 15x in one process."""
    _85c581ed_cycles(ed, r, lambda x, y: 'input keyevent 4; sleep 0.15; input keyevent 4')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_2_b(ed, r):
    """Event 6 (Xiaomi 220233L2I): one-jpg project, Home right after MsgGetMediaDuration, back in (on_resume), Back 0.3 s later (on_pause -> MainActivity)."""
    _85c581ed_cycles(ed, r, lambda x, y: (
        'input keyevent 3; sleep 0.4; monkey -p com.myzesty -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; '
        'sleep 0.3; input keyevent 4; sleep 0.15; input keyevent 4'))


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l4_2_c(ed, r):
    """Event 1 (Xiaomi M2004J19C): one-jpg slideshow, Play (ss_start, MsgRefreshScreen on the live surface) right on MsgGetMediaDuration, then Back."""
    _85c581ed_cycles(ed, r, lambda x, y: f'input tap {x} {y}; sleep 0.1; input keyevent 4; sleep 0.15; input keyevent 4')


# 2026-10-10 12:41 level 5 attempt 1
def _85c581ed_newest_jpg(ed):
    """Make a JPG the newest picker tile (field: a project with one 3 s image and no video)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg 2>/dev/null | grep -v NightShift | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(2)


def _85c581ed_run(ed, r, where, transition):
    """Hook on -> slideshow, 1 jpg, Done (MsgAddImage, MsgGetMediaDuration x2) -> the field transition, with no UI-dump gate."""
    ed.dev.restore_env()                             # internet on: offline hides the slideshow media panel
    ed.dev.setprop('debug.checkjni', '1')            # open_slideshow force-stops, so the new process picks this up
    ed.dev.setprop('debug.zesty.hook.stale_jni_ref', where)
    try:
        _85c581ed_newest_jpg(ed)
        ed.open_slideshow(n=1, wait=0)               # engine is ready ~0.3 s after Done; surface_view/rvMedias checks are unreliable
        ed.idle(r.uniform(0.3, 0.9))                 # field: transition <1 s after MsgGetMediaDuration
        transition()
        ed.settle(6)
    finally:
        ed.dev.setprop('debug.zesty.hook.stale_jni_ref', '0')
        ed.dev.setprop('debug.checkjni', '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l5_1_a(ed, r):
    """Event 5 (Xiaomi M2006C3MII): 1-jpg slideshow, Back -> ss_on_pause -> surfaceDestroyed -> MainActivity hits the stale JNI ref (hook)."""
    def back():
        ed.dev.key('KEYCODE_BACK')                   # surfaceDestroyed -> Player.onSurfaceDestroyed (shouldDestroyPlayer=true)
        ed.idle(0.4)
        ed.dev.key('KEYCODE_BACK')                   # past a possible discard dialog
    _85c581ed_run(ed, r, 'surface', back)


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l5_1_b(ed, r):
    """Event 6 (Xiaomi 220233L2I): 1-jpg project playing, Home -> onPause -> pausePlaying hits the stale JNI ref, then back in (hook)."""
    def home():
        ed.slideshow_toggle_play()                   # pausePlayer() only calls Player.pausePlaying while playing
        ed.idle(r.uniform(0.1, 0.3))
        ed.dev.key('KEYCODE_HOME')                   # onPause -> pausePlaying
        ed.idle(0.4)
        ed.dev.launch()                              # on_resume; then on_pause -> MainActivity
        ed.idle(0.3)
        ed.dev.key('KEYCODE_BACK')
    _85c581ed_run(ed, r, 'pause', home)


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l5_1_c(ed, r):
    """Event 1 (Xiaomi M2004J19C): 1-jpg slideshow, ss_start + MsgRefreshScreen on the live surface hits the stale JNI ref (hook)."""
    def refresh():
        ed.slideshow_toggle_play()                   # ss_start (a surfaceChanged right after Done may already abort)
        ed.idle(0.3)
        ed.dev.key('KEYCODE_HOME')
        ed.idle(0.5)
        ed.dev.launch()                              # surfaceCreated -> Player.refreshScreen on the same window
    _85c581ed_run(ed, r, 'refresh', refresh)


# 2026-10-10 12:44 level 5 attempt 2
def _85c581ed_newest_jpg(ed):
    """Copy a JPG to a new name so it is the newest picker tile (field: one 3 s image, no video)."""
    src = ed.dev.sh('ls -t /sdcard/DCIM/*/*.jpg /sdcard/Pictures/*.jpg 2>/dev/null | grep -v NightShift | head -1').strip()
    dst = f'/sdcard/DCIM/NightShift/ns85_{int(time.time())}.jpg'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'cp "{src}" {dst}' if src else f'screencap -p {dst}')
    ed.dev.sh(f'touch {dst}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{dst} >/dev/null 2>&1')
    ed.idle(1)


_85_HOOK = 'debug.zesty.hook.art_abort_on_transition'


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l5_2_a(ed, r):
    """Event 1 (Xiaomi M2004J19C): slideshow + one jpg; ART aborts on the MsgRefreshScreen that follows the MsgGetMediaDuration pair (hook)."""
    ed.dev.restore_env()                             # online: the slideshow media panel needs internet
    _85c581ed_newest_jpg(ed)
    ed.dev.setprop(_85_HOOK, 'refresh')              # armed by getMediaDuration, fires on the next refreshScreen
    try:
        ed.open_slideshow(n=1, wait=0)               # Done -> MsgAddImage -> MsgGetMediaDuration x2 -> MsgRefreshScreen
        ed.ui.tap('id:play', timeout=5)              # decorative: ss_start like the field user
        ed.settle(6)
    finally:
        ed.dev.setprop(_85_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_85c581ed_l5_2_b(ed, r):
    """Event 5 (Xiaomi M2006C3MII): slideshow + one jpg, Play, then leave (ss_on_pause -> pausePlaying) right after the duration queries (hook)."""
    ed.dev.restore_env()
    _85c581ed_newest_jpg(ed)
    ed.dev.setprop(_85_HOOK, 'pause')                # fires on the first pausePlaying within 15 s of getMediaDuration
    try:
        ed.open_slideshow(n=1, wait=0)
        if not ed.ui.tap('id:play', timeout=8):      # QuickCutActivity.onPause pauses only while playing
            ed.slideshow_toggle_play()
        ed.idle(r.uniform(0.2, 0.6))
        ed.dev.key('KEYCODE_HOME')                   # onPause -> pausePlayer -> JNI pausePlaying
        ed.idle(3)
        ed.dev.launch()
        ed.settle(5)
    finally:
        ed.dev.setprop(_85_HOOK, '0')


@scenario('nightshift', 'auto')
def ns_85c581ed_l5_2_c(ed, r):
    """Event 6 (Xiaomi 220233L2I): editor (PlayerActivity) + one jpg added, ve_on_pause right after getMediaDuration -> pausePlaying (hook)."""
    ed.set_playing(False)
    _85c581ed_newest_jpg(ed)
    ed.dev.setprop(_85_HOOK, 'pause')
    try:
        ed.add_media(pick=0)                         # new media -> MsgAddImage/MsgGetMediaDuration arm the hook
        ed.idle(r.uniform(0.1, 0.5))
        ed.dev.key('KEYCODE_HOME')                   # PlayerActivity.onPause always calls Player.pausePlaying()
        ed.idle(3)
        ed.dev.launch()
        ed.settle(5)
    finally:
        ed.dev.setprop(_85_HOOK, '0')
