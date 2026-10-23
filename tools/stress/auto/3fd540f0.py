# Night Shift auto repros for 3fd540f001f9c5c3d98e3dee6de9509c


# 2026-10-10 00:38 level 3 attempt 1
def _3fd540f0_start_new_project(ed):
    """Cold app -> New Project -> pick the 2 newest (fresh, never-transcoded) clips -> editor shows 'We're loading your media'."""
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')               # no cached transcodes: both clips are transcoded for real
    ed.dev.fresh_video('a'); ed.dev.fresh_video('b')
    ed.step('New Project with 2 fresh clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:2]:
        ed.dev.tap(*t.center)
        time.sleep(0.5)
    ed._picker_confirm()
    ed.ui.wait(('id:trans_label', 'id:progress_perc', 'id:ring_progress'), timeout=30)   # transcode dialog up, no add yet
    ed.idle(1)
    return ed.dev.pid()


def _3fd540f0_away_then_race(ed, r, hide, away_s, pressure):
    """Hide the editor mid-transcode, keep it stopped ~90 s, then bring it back and hide it again ~2 s later: the
    transcode dialog posts COMPLETE_TRANSCODING 2 s after onStart, so the two add_video renders race the stop."""
    pid = _3fd540f0_start_new_project(ed)
    ed.mon.allow_death = True
    ed.step(f'editor stopped mid-transcode ({away_s:.0f}s, {pressure})')
    hide()
    ed.dev.sh(f'am send-trim-memory {PKG} {pressure}')   # field: trim_memory_20 then 40 after ve_on_stop
    ed.idle(away_s)
    for k in range(3):
        ed.step(f'return, hide again during the 2 s success delay (try {k + 1})')
        ed.dev.launch()
        time.sleep(r.uniform(1.7, 2.6))
        hide()
        ed.idle(r.uniform(8, 15))                   # adds + forced refresh run against the released window
    ed.mon.allow_death = False
    if ed.dev.pid() != pid:
        ed.log('    app process changed while stopped (field process stayed alive)')
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_1_a(ed, r):
    """Instance 1/1 (SM-S721B): New Project, Home mid-transcode + BACKGROUND trim, ~90 s stopped, adds race the stop."""
    _3fd540f0_away_then_race(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), r.uniform(85, 95), 'BACKGROUND')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_1_b(ed, r):
    """Instance 1/1 (SM-S721B): another app (camera, codec+GL user) covers the editor mid-transcode, critical trim, adds race."""
    def cover():
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
        time.sleep(1.5)
    _3fd540f0_away_then_race(ed, r, cover, r.uniform(60, 90), 'RUNNING_CRITICAL')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_1_c(ed, r):
    """Instance 1/1 (SM-S721B): screen off mid-transcode (stop without Home), ~90 s, wake and sleep again inside the 2 s delay."""
    def screen_off():
        ed.dev.key('KEYCODE_SLEEP')
    try:
        _3fd540f0_away_then_race(ed, r, screen_off, r.uniform(85, 95), 'BACKGROUND')
    finally:
        ed.dev.key('KEYCODE_WAKEUP')
        ed.dev.sh('wm dismiss-keyguard')


# 2026-10-10 00:54 level 3 attempt 2
def _3fd540f0_pick(ed, n):
    """Picker is open: Videos tab, tap the n newest tiles (ns_long_audio.mov first: its transcode is usually cached)."""
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < n:
        raise UIError(f'picker shows fewer than {n} videos')
    for t in tiles[:n]:
        ed.dev.tap(*t.center)
        time.sleep(0.5)


def _3fd540f0_hide_at_first_add(ed, r, how, pressure, n_clips, open_picker):
    """Editor stays VISIBLE until the transcode succeeds (+2 s delay); an on-device logcat watcher hides it the
    moment the first 'MsgAddVideo' prints, so the later add_video -> quit_edit_state(true) renders run after
    surfaceDestroyed. In a project with no export dialog native is never told, so they use the stale window."""
    ed.dev.restore_env()                              # cached transcodes back in files/outputs: success comes fast
    ed.grant_permissions()
    push_newest_video(ed)
    open_picker()
    _3fd540f0_pick(ed, n_clips)
    pid = ed.dev.pid()
    ed.step(f'arm watcher: on first MsgAddVideo -> {how}')
    ed.dev.sh(f"nohup sh -c 'timeout 420 logcat -T 1 -m 1 -e MsgAddVideo >/dev/null && {how}' >/dev/null 2>&1 &")
    time.sleep(0.5)
    ed._picker_confirm()
    ed.mon.allow_death = True
    end = time.time() + 430                           # transcode runs in the foreground, as long as it needs
    while time.time() < end and 'logcat -T 1 -m 1' in ed.dev.sh('ps -A -o ARGS | grep "logcat -T 1 -m 1" | grep -v grep'):
        time.sleep(2)
    ed.step(f'editor hidden mid add-burst; trim {pressure}, stay stopped')
    ed.dev.sh(f'am send-trim-memory {PKG} {pressure}')
    ed.idle(r.uniform(20, 35))                         # remaining adds + their forced refreshes run while stopped
    ed.mon.allow_death = False
    if ed.dev.pid() != pid:
        ed.log('    app process changed while stopped (field process stayed alive)')
    ed.dev.launch()
    ed.settle(6)


def _3fd540f0_new_project(ed):
    ed.step('New Project tab -> picker')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_2_a(ed, r):
    """Instance 1/1 (SM-S721B): New Project, 3 clips, Home the instant the first MsgAddVideo runs + BACKGROUND trim."""
    _3fd540f0_hide_at_first_add(ed, r, 'cmd input keyevent 3', 'BACKGROUND', 3, lambda: _3fd540f0_new_project(ed))


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_2_b(ed, r):
    """Instance 1/1 (SM-S721B): New Project, 3 clips, camera (GPU+codec user) covers the editor at the first MsgAddVideo."""
    _3fd540f0_hide_at_first_add(ed, r, 'am start -a android.media.action.STILL_IMAGE_CAMERA', 'RUNNING_CRITICAL', 3,
                                lambda: _3fd540f0_new_project(ed))


@scenario('nightshift', 'auto')
def ns_3fd540f0_l3_2_c(ed, r):
    """Instance 1/1 (SM-S721B): open draft, editor '+' adds 2 clips to layer 0, screen off at the first MsgAddVideo."""
    def plus():
        ed.set_playing(False)
        if not ed.ui.tap(('id:add_video', 'id:addVideo'), timeout=10):
            raise UIError('add media button (id add_video) not found')
    try:
        _3fd540f0_hide_at_first_add(ed, r, 'cmd input keyevent 223', 'MODERATE', 2, plus)
    finally:
        ed.dev.key('KEYCODE_WAKEUP')
        ed.dev.sh('wm dismiss-keyguard')


# 2026-10-10 01:04 level 3 attempt 3
def _3fd540f0_two_clip_project(ed):
    """Cold app -> New Project -> 2 fresh (never-transcoded) clips -> DONE; returns once the transcode dialog is up."""
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')
    ed.dev.fresh_video('a'); ed.dev.fresh_video('b')
    ed.step('New Project with 2 fresh clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:2]:
        ed.dev.tap(*t.center)
        time.sleep(0.5)
    ed._picker_confirm()                              # DONE at its drawn position (not in the dump)
    if ed.ui.wait(('id:trans_label', 'id:progress_perc', 'id:ring_progress'), timeout=30) is None:
        raise UIError('transcode dialog never showed')
    return ed.dev.pid()


def _3fd540f0_started_not_resumed(ed, r, hide, pressure, launch_while_off):
    """Hide before the transcode Success is collected; ~90 s stopped under trim; then come back STARTED but not
    RESUMED (behind the keyguard): repeatOnLifecycle(STARTED) replays Success, 2 s later both adds render to the
    window native kept since before the stop (no onResume -> no surfaceCreated -> no MsgRefreshScreen)."""
    pid = _3fd540f0_two_clip_project(ed)
    ed.mon.allow_death = True
    try:
        ed.step(f'editor hidden mid-transcode, trim {pressure}, ~90 s stopped')
        hide()
        ed.dev.sh(f'am send-trim-memory {PKG} {pressure}')
        ed.idle(1)
        ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')    # field: trim_memory_20 then 40
        ed.idle(r.uniform(85, 95))
        if launch_while_off:
            ed.step('screen off, bring the editor task to front behind the lock screen')
            ed.dev.key('KEYCODE_SLEEP')
            ed.idle(3)
            ed.dev.launch()
            ed.idle(2)
        ed.step('wake, keep the keyguard up (STARTED, not RESUMED) while the 2 s success delay runs')
        ed.dev.key('KEYCODE_WAKEUP')
        ed.idle(20)
        ed.step('unlock')
        ed.dev.sh('wm dismiss-keyguard')
        ed.idle(8)
    finally:
        ed.dev.key('KEYCODE_WAKEUP')
        ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    if ed.dev.pid() != pid:
        ed.log('    app process changed while stopped (field process stayed alive)')
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_3_a(ed, r):
    """Instance 1/1 (SM-S721B): screen off mid-transcode, ~90 s + trim, wake to the lock screen -> adds while not resumed."""
    _3fd540f0_started_not_resumed(ed, r, lambda: ed.dev.key('KEYCODE_SLEEP'), 'RUNNING_MODERATE', False)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_3_b(ed, r):
    """Instance 1/1 (SM-S721B): Home mid-transcode, ~90 s + trim, app relaunched under the keyguard -> adds while not resumed."""
    _3fd540f0_started_not_resumed(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), 'RUNNING_LOW', True)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l3_3_c(ed, r):
    """Instance 1/1 (SM-S721B): camera (GPU+codec user) covers the editor mid-transcode, critical trim, relaunch under keyguard."""
    def camera():
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
        time.sleep(2)
    _3fd540f0_started_not_resumed(ed, r, camera, 'RUNNING_CRITICAL', True)


# 2026-10-10 01:19 level 4 attempt 1
def _3fd540f0_pick(ed, n):
    """Picker open: Videos tab, tap up to n newest tiles (needs at least 2 so the burst is more than one add)."""
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:n]:
        ed.dev.tap(*t.center)
        time.sleep(0.4)


def _3fd540f0_new_project(ed):
    ed.step('New Project tab -> picker')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')


def _3fd540f0_stop_inside_burst(ed, r, how, open_picker, n_clips=6):
    """Transcode runs in the FOREGROUND (the STARTED gate on COMPLETE_TRANSCODING passes). An on-device watcher
    stops the editor the instant the FIRST MsgAddVideo prints, so the rest of the add burst (one add_video ->
    quit_edit_state(true) -> render_frames_at -> show() per clip) renders to the window native kept: in a project
    with no export dialog surfaceDestroyed never tells native."""
    ed.dev.restore_env()                             # cached outputs back: transcode finishes in seconds, not minutes
    ed.grant_permissions()
    open_picker()
    _3fd540f0_pick(ed, n_clips)
    pid = ed.dev.pid()
    ed.step(f'arm watcher (log lines from now on only): first MsgAddVideo -> {how}')
    # -T <epoch now>: ignore MsgAddVideo lines already in the buffer (the old '-T 1' fired early on stale lines)
    ed.dev.sh("nohup sh -c 'timeout 480 logcat -T $(date +%s).000 -m 1 -e MsgAddVideo >/dev/null && "
              f"{how}' >/dev/null 2>&1 &")
    time.sleep(1)
    ed._picker_confirm()
    ed.mon.allow_death = True
    end = time.time() + 490                          # wait for the transcode however long it takes in the foreground
    while time.time() < end and 'logcat -T' in ed.dev.sh('ps -A -o ARGS | grep "logcat -T" | grep -v grep'):
        time.sleep(0.5)
    ed.step('editor stopped inside the add burst; field trim 20 then 40, stay stopped')
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW')
    ed.idle(1)
    ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')
    ed.idle(r.uniform(20, 30))
    ed.mon.allow_death = False
    if ed.dev.pid() != pid:
        ed.log('    app process changed while stopped (field process stayed alive)')
    ed.dev.key('KEYCODE_WAKEUP')
    ed.dev.sh('wm dismiss-keyguard')
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_1_a(ed, r):
    """Instance 1/1 (SM-S721B): New Project, 6 clips, Home at the first MsgAddVideo -> remaining adds render while stopped."""
    _3fd540f0_stop_inside_burst(ed, r, 'input keyevent 3', lambda: _3fd540f0_new_project(ed))


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_1_b(ed, r):
    """Instance 1/1 (SM-S721B): New Project, 6 clips, screen off at the first MsgAddVideo (stop + surface gone, no Home)."""
    _3fd540f0_stop_inside_burst(ed, r, 'input keyevent 223', lambda: _3fd540f0_new_project(ed))


@scenario('nightshift', 'auto')
def ns_3fd540f0_l4_1_c(ed, r):
    """Instance 1/1 (SM-S721B): open draft, editor '+' adds 5 clips to layer 0, Home at the first MsgAddVideo."""
    def plus():
        ed.set_playing(False)
        if not ed.ui.tap(('id:addVideo', 'id:add_video'), timeout=10):
            raise UIError('add media button (id addVideo) not found')
    _3fd540f0_stop_inside_burst(ed, r, 'input keyevent 3', plus, n_clips=5)


# 2026-10-10 01:30 level 4 attempt 2
def _3fd540f0_project_transcoding(ed):
    """Cold app -> New Project -> 2 fresh (never transcoded) clips -> DONE; returns once the transcode dialog is up."""
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')                 # no cached transcoding-*.mp4: the transcode is real and long
    ed.dev.fresh_video('a'); ed.dev.fresh_video('b')
    ed.step('New Project with 2 fresh clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:2]:
        ed.dev.tap(*t.center)
        time.sleep(0.5)
    ed._picker_confirm()
    if ed.ui.wait(('id:trans_label', 'id:progress_perc', 'id:ring_progress'), timeout=30) is None:
        raise UIError('transcode dialog never showed')
    return ed.dev.pid()


def _3fd540f0_stopped_until_transcoded(ed, r, hide):
    """Hide BEFORE any MsgAddVideo, field trims 20 then 40, stay stopped >= ~90 s AND until both outputs are
    complete (size stable), so Success is waiting for the next STARTED and native still holds the pre-stop window."""
    pid = _3fd540f0_project_transcoding(ed)
    ed.mon.allow_death = True
    ed.step('hide mid-transcode (no add yet), trim 20 + 40, wait for both transcodes')
    hide()
    t0 = time.time()
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW'); ed.idle(1)
    ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')
    last, stable = None, 0
    while time.time() - t0 < 330:
        out = ed.dev.sh(f"run-as {PKG} sh -c 'ls -l files/outputs/ 2>/dev/null | grep transcoding-'")
        stable = stable + 1 if (out == last and out.count('transcoding-') >= 2) else 0
        last = out
        if stable >= 3 and time.time() - t0 >= r.uniform(88, 95):
            break
        time.sleep(3)
    ed.log(f'    stopped {time.time() - t0:.0f}s, outputs: {last.count("transcoding-") if last else 0}')
    if ed.dev.pid() != pid:
        raise UIError('app process died while stopped (field process stayed alive)')
    return pid


def _3fd540f0_arm_hide_on_add(ed, how):
    # second add's quit_edit_state(true) -> show() then runs after surfaceDestroyed (native never told: no exportDialog)
    ed.dev.sh("nohup sh -c 'timeout 120 logcat -T $(date +%s).000 -m 1 -e MsgAddVideo >/dev/null && "
              f"{how}' >/dev/null 2>&1 &")
    time.sleep(0.5)


def _3fd540f0_finish(ed, s):
    ed.idle(s)
    ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_2_a(ed, r):
    """Instance 1/1 (SM-S721B): Home mid-transcode, 90 s stopped + trims, return, Home again the instant clip 0 is added."""
    _3fd540f0_stopped_until_transcoded(ed, r, lambda: ed.dev.key('KEYCODE_HOME'))
    _3fd540f0_arm_hide_on_add(ed, 'input keyevent 3')
    ed.step('return: Success replays, +2 s adds; watcher stops the editor between add 0 and add 1')
    ed.dev.launch()
    _3fd540f0_finish(ed, r.uniform(20, 30))


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_2_b(ed, r):
    """Instance 1/1 (SM-S721B): screen off mid-transcode, 90 s + trims, app relaunched while the screen stays OFF (no resume, 90-s-old window)."""
    try:
        _3fd540f0_stopped_until_transcoded(ed, r, lambda: ed.dev.key('KEYCODE_SLEEP'))
        ed.step('bring the editor task to front with the display still asleep; stay dark 30 s')
        ed.dev.launch()
        ed.idle(30)                                    # any STARTED-while-sleeping window runs the 2 s delay + both adds
    finally:
        _3fd540f0_finish(ed, 2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_2_c(ed, r):
    """Instance 1/1 (SM-S721B): Home mid-transcode, 90 s + trims, return straight under a translucent share sheet (STARTED, paused) + hide at add 0."""
    _3fd540f0_stopped_until_transcoded(ed, r, lambda: ed.dev.key('KEYCODE_HOME'))
    _3fd540f0_arm_hide_on_add(ed, 'input keyevent 3')
    ed.step('return covered by a system sheet in the same breath: editor STARTED, not interactive')
    ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; '
              'am start -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT ns >/dev/null 2>&1')
    _3fd540f0_finish(ed, r.uniform(20, 30))


# 2026-10-10 01:59 level 4 attempt 3
def _3fd540f0_record_clips(ed):
    """Two ~12 s screen recordings (1080x2340, 20 Mbps) as the 2 newest gallery videos: above the device size limit so
    they really transcode, but short enough to finish while the editor is stopped (5.5 min lab clips never did)."""
    t = int(time.time())
    a, b = (f'/sdcard/DCIM/NightShift/ns_fresh_sr_{t}_{x}.mp4' for x in 'ab')   # ns_fresh_ keeps fresh_video off them
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh(f"nohup sh -c 'screenrecord --time-limit 12 --bit-rate 20000000 {a}; "
              f"screenrecord --time-limit 12 --bit-rate 20000000 {b}' >/dev/null 2>&1 &")
    end = time.time() + 27
    while time.time() < end:                          # motion so the clips have real frames
        ed.dev.swipe(540, 1900, 540, 600, 250); time.sleep(1.2)
        ed.dev.swipe(540, 600, 540, 1900, 250); time.sleep(1.2)
    ed.dev.key('KEYCODE_HOME')
    for p in (a, b):
        ed.dev.sh(f'touch {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
        time.sleep(1)
    ed.idle(3)


def _3fd540f0_project(ed, short):
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')                 # no cached transcoding-*.mp4
    if short:
        _3fd540f0_record_clips(ed)
    else:
        ed.dev.fresh_video('a'); ed.dev.fresh_video('b')
    ed.dev.launch()
    ed.step('New Project with the 2 newest clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5); time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:2]:
        ed.dev.tap(*t.center); time.sleep(0.5)
    ed._picker_confirm()                              # DONE at its drawn position
    if ed.ui.wait(('id:trans_label', 'id:progress_perc', 'id:ring_progress'), timeout=30) is None:
        raise UIError('transcode dialog never showed')


def _3fd540f0_stopped_until_done(ed, r, hide, max_s):
    """Hide before any add; trims 20 then 40; stay stopped >= ~90 s AND until BOTH transcodes are finished."""
    pid = ed.dev.pid()
    ed.mon.allow_death = True
    ed.step('hide mid-transcode, trim 20 + 40, wait for BOTH transcodes to finish while stopped')
    t_dev = ed.dev.sh('date +%s').strip()
    hide()
    t0 = time.time()
    ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW'); ed.idle(1)
    ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')
    last, stable, eos, need = None, 0, 0, r.uniform(90, 100)
    while time.time() - t0 < max_s:
        out = ed.dev.sh(f"run-as {PKG} sh -c 'ls -l files/outputs/ 2>/dev/null | grep transcoding-'")
        eos = int((ed.dev.sh(f'logcat -d -T {t_dev}.000 | grep -c "produced EoS"') or '0').strip() or 0)
        stable = stable + 1 if (out == last and out.count('transcoding-') >= 2) else 0
        last = out
        if (stable >= 3 or eos >= 2) and time.time() - t0 >= need:
            break
        time.sleep(4)
    n = last.count('transcoding-') if last else 0
    ed.log(f'    stopped {time.time() - t0:.0f}s, outputs: {n}, EoS: {eos}')
    if ed.dev.pid() != pid:
        raise UIError('app process died while stopped (field process stayed alive)')
    if n < 2:
        raise UIError('second transcode not done while stopped: adds would only fire after resume')


def _3fd540f0_arm(ed, how):
    # first MsgAddVideo -> hide: add 1's quit_edit_state(true) -> show() renders to a window native was never told is gone
    ed.dev.sh("nohup sh -c 'timeout 150 logcat -T $(date +%s).000 -m 1 -e MsgAddVideo >/dev/null && "
              f"{how}' >/dev/null 2>&1 &")
    time.sleep(0.5)


def _3fd540f0_return_under_sheet(ed):
    ed.step('return covered by a translucent system sheet in the same breath: STARTED, not interactive')
    ed.dev.sh(f'monkey -p {PKG} -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1; '
              'am start -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT ns >/dev/null 2>&1')
    ed.idle(25)                                       # Success replay + 2 s delay + both adds


def _3fd540f0_finish(ed):
    ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    ed.dev.key('KEYCODE_BACK')
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_3_a(ed, r):
    """Instance 1/1 (SM-S721B): short clips transcode while Home-stopped 90 s+trims, return under a sheet, Home at add 0."""
    _3fd540f0_project(ed, short=True)
    _3fd540f0_stopped_until_done(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), 420)
    _3fd540f0_arm(ed, 'input keyevent 3')
    _3fd540f0_return_under_sheet(ed)
    _3fd540f0_finish(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_3_b(ed, r):
    """Instance 1/1 (SM-S721B): short clips transcode while screen-off 90 s+trims; wake+relaunch, Home+critical trim at add 0."""
    _3fd540f0_project(ed, short=True)
    try:
        _3fd540f0_stopped_until_done(ed, r, lambda: ed.dev.key('KEYCODE_SLEEP'), 420)
        _3fd540f0_arm(ed, f'input keyevent 3; am send-trim-memory {PKG} RUNNING_CRITICAL')
        ed.step('wake, relaunch: adds 2 s after onStart, editor hidden again at the first add')
        ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
        ed.dev.launch()
        ed.idle(25)
    finally:
        _3fd540f0_finish(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l4_3_c(ed, r):
    """Instance 1/1 (SM-S721B): long clips with audio (as in the field), stopped until both transcodes finish, sheet return, Home at add 0."""
    _3fd540f0_project(ed, short=False)
    _3fd540f0_stopped_until_done(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), 900)
    _3fd540f0_arm(ed, 'input keyevent 3')
    _3fd540f0_return_under_sheet(ed)
    _3fd540f0_finish(ed)


# 2026-10-10 02:17 level 5 attempt 1
_3FD_HOOK = 'debug.zesty.hook.add_while_stopped'


def _3fd540f0_record_clips(ed):
    """Two fresh ~15 s 1080x2340 screen recordings as the 2 newest videos (transcode in seconds on this phone)."""
    t = int(time.time())
    clips = [f'/sdcard/DCIM/NightShift/ns_fresh_sr_{t}_{x}.mp4' for x in 'ab']
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh(f"nohup sh -c 'screenrecord --time-limit 15 --bit-rate 20000000 {clips[0]}; "
              f"screenrecord --time-limit 15 --bit-rate 20000000 {clips[1]}' >/dev/null 2>&1 &")
    end = time.time() + 33
    while time.time() < end:                          # motion so the clips have real frames
        ed.dev.swipe(540, 1900, 540, 600, 250); time.sleep(1.2)
        ed.dev.swipe(540, 600, 540, 1900, 250); time.sleep(1.2)
    for p in clips:
        ed.dev.sh(f'touch {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
    ed.idle(3)


def _3fd540f0_pick2(ed):
    ed.step('New Project with the 2 newest clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5); time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    for t in tiles[:2]:
        ed.dev.tap(*t.center); time.sleep(0.5)


def _3fd540f0_stopped_adds(ed, r, hide):
    """Hide the editor at transcode start (trim 20 + 40), hook lets Success post while STOPPED -> 2 adds render to the stale window."""
    ed.dev.restore_env(); ed.grant_permissions(); ed.dev.clear_app_files('outputs')
    _3fd540f0_record_clips(ed)
    ed.dev.launch()
    _3fd540f0_pick2(ed)
    pid, t_dev = ed.dev.pid(), ed.dev.sh('date +%s').strip()
    ed.dev.setprop(_3FD_HOOK, '1')
    try:
        ed.step(f'arm: first transcode frame -> {hide} + trim 20/40; confirm picker')
        ed.dev.sh("nohup sh -c 'timeout 90 logcat -T $(date +%s).000 -m 1 -e Decoder.output.format.changed >/dev/null && "
                  f"{hide}; sleep 1; am send-trim-memory {PKG} RUNNING_LOW; sleep 1; "
                  f"am send-trim-memory {PKG} BACKGROUND' >/dev/null 2>&1 &")
        time.sleep(0.5)
        ed.mon.allow_death = True
        ed._picker_confirm()
        ed.step('editor stopped: wait for both MsgAddVideo (no resume, no MsgRefreshScreen)')
        end, n = time.time() + 300, 0
        while time.time() < end and n < 2:
            time.sleep(2)
            n = int((ed.dev.sh(f'logcat -d -T {t_dev}.000 | grep -c MsgAddVideo') or '0').strip() or 0)
        seq = ed.dev.sh(f'logcat -d -T {t_dev}.000 | grep -oE "we_on_stop|we_on_resume|MsgAddVideo"').split()
        ed.log(f'    adds: {n}, order: {seq[:8]}')
        if n < 2 or 'we_on_stop' not in seq or seq.index('we_on_stop') > seq.index('MsgAddVideo'):
            raise UIError('the adds did not land while the editor was stopped')
        if 'we_on_resume' in seq[seq.index('we_on_stop'):seq.index('MsgAddVideo') + 2]:
            raise UIError('editor resumed before the second add')
        ed.idle(r.uniform(8, 15))
    finally:
        ed.dev.setprop(_3FD_HOOK, '0')
    if ed.dev.pid() != pid:
        ed.log('    app process changed while stopped')
    ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_1_a(ed, r):
    """Instance 1/1 (SM-S721B, Firebase 2026-10-09): Home mid-transcode, trims, both adds while stopped (hook: no STARTED gate)."""
    _3fd540f0_stopped_adds(ed, r, 'input keyevent 3')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_1_b(ed, r):
    """Instance 1/1 (SM-S721B, Firebase 2026-10-09): screen off mid-transcode, both adds while stopped and dark (hook: no STARTED gate)."""
    _3fd540f0_stopped_adds(ed, r, 'input keyevent 223')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_1_c(ed, r):
    """Instance 1/1 (SM-S721B, Firebase 2026-10-09): another app (camera) covers the editor mid-transcode, both adds while stopped (hook)."""
    _3fd540f0_stopped_adds(ed, r, 'am start -a android.media.action.STILL_IMAGE_CAMERA')


# 2026-10-10 02:19 level 5 attempt 2
def _3fd540f0_record_clips(ed):
    """Two ~12 s screen recordings (1080x2340, 20 Mbps) as the 2 newest gallery videos: above the size limit so they
    go through the real transcoder (transcoding-*.mp4 outputs, as in the field), and short enough to finish in seconds."""
    t = int(time.time())
    a, b = (f'/sdcard/DCIM/NightShift/ns_fresh_sr_{t}_{x}.mp4' for x in 'ab')
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh(f"nohup sh -c 'screenrecord --time-limit 12 --bit-rate 20000000 {a}; "
              f"screenrecord --time-limit 12 --bit-rate 20000000 {b}' >/dev/null 2>&1 &")
    end = time.time() + 27
    while time.time() < end:                          # motion so the clips have real frames
        ed.dev.swipe(540, 1900, 540, 600, 250); time.sleep(1.2)
        ed.dev.swipe(540, 600, 540, 1900, 250); time.sleep(1.2)
    for p in (a, b):
        ed.dev.sh(f'touch {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
        time.sleep(1)
    ed.idle(3)


def _3fd540f0_run(ed, r, hide, hold_s):
    """New project, pick 2 clips, DONE, hide at once. The hook holds the transcode Success for hold_s and then posts
    COMPLETE_TRANSCODING whatever the lifecycle, so both MsgAddVideo run while stopped. Native still holds the
    pre-stop window because surfaceDestroyed skips Player.onSurfaceDestroyed when exportDialog == null."""
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')
    _3fd540f0_record_clips(ed)
    ed.dev.launch()
    ed.step('New Project with the 2 newest clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5); time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    ed.dev.setprop('debug.zesty.hook.add_while_stopped', str(int(hold_s * 1000)))
    try:
        for t in tiles[:2]:
            ed.dev.tap(*t.center); time.sleep(0.5)
        ed._picker_confirm()                          # DONE at its drawn position
        ed.ui.wait(('id:trans_label', 'id:progress_perc', 'id:ring_progress'), timeout=8)
        pid = ed.dev.pid()
        ed.mon.allow_death = True
        ed.step(f'hide before any add; field trims 20 + 40; adds fire ~{hold_s:.0f}s later while stopped')
        hide()
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW'); ed.idle(1)
        ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')
        ed.idle(hold_s + 25)                          # both add_video -> quit_edit_state(true) -> show() on the stale window
        if ed.dev.pid() != pid:
            raise UIError('app process died while stopped (field process stayed alive)')
    finally:
        ed.dev.setprop('debug.zesty.hook.add_while_stopped', '0')
    ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_2_a(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): Home right after the picker, ~90 s stopped, then both adds land while stopped (hook)."""
    _3fd540f0_run(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), r.uniform(85, 95))


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_2_b(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): screen off right after the picker, ~90 s stopped, then both adds land while stopped (hook)."""
    _3fd540f0_run(ed, r, lambda: ed.dev.key('KEYCODE_SLEEP'), r.uniform(85, 95))


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_2_c(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): another app (camera) covers the editor, then both adds land while stopped (hook)."""
    def hide():
        ed.dev.key('KEYCODE_HOME')
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    _3fd540f0_run(ed, r, hide, r.uniform(85, 95))


# 2026-10-10 02:38 level 5 attempt 3
def _3fd540f0_record_clips(ed):
    """Two ~12 s screen recordings (1080x2340, 20 Mbps) as the 2 newest videos: they go through the real transcoder."""
    t = int(time.time())
    a, b = (f'/sdcard/DCIM/NightShift/ns_fresh_sr_{t}_{x}.mp4' for x in 'ab')
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh(f"nohup sh -c 'screenrecord --time-limit 12 --bit-rate 20000000 {a}; "
              f"screenrecord --time-limit 12 --bit-rate 20000000 {b}' >/dev/null 2>&1 &")
    end = time.time() + 27
    while time.time() < end:
        ed.dev.swipe(540, 1900, 540, 600, 250); time.sleep(1.2)
        ed.dev.swipe(540, 600, 540, 1900, 250); time.sleep(1.2)
    for p in (a, b):
        ed.dev.sh(f'touch {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
        time.sleep(1)
    ed.idle(3)


def _3fd540f0_run(ed, r, hide, label):
    """New project, 2 clips, DONE, hide at once. The hook holds the import's first JNI addVideo (IO thread) ~90 s, so
    both MsgAddVideo -> quit_edit_state(true) -> show() run while stopped on the window native was never told is gone."""
    ed.dev.restore_env()
    ed.grant_permissions()
    ed.dev.clear_app_files('outputs')
    _3fd540f0_record_clips(ed)
    ed.dev.launch()
    ed.step('New Project with the 2 newest clips')
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        time.sleep(2)
    if not ed.ui.tap(('textc:new project',), timeout=10):
        raise UIError('no "New Project" tab')
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is not None and s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5); time.sleep(1)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    tiles = s.find_all('id:gridrl') if s is not None else []
    if len(tiles) < 2:
        raise UIError('picker shows fewer than 2 videos')
    hold_s = r.uniform(88, 95)                        # field: ~90 s between ve_on_stop and the first add
    ed.dev.setprop('debug.zesty.hook.hold_add_video', f'{int(hold_s * 1000)}:{r.randint(1000, 9999)}')
    try:
        for t in tiles[:2]:
            ed.dev.tap(*t.center); time.sleep(0.5)
        ed._picker_confirm()                          # transcode -> processMedia -> addVideo #1 parks in the hook
        pid = ed.dev.pid()
        ed.mon.allow_death = True
        ed.step(f'{label} right after DONE; trims 20 + 40; held add #1 + add #2 land ~{hold_s:.0f}s later, stopped')
        hide()
        ed.dev.sh(f'am send-trim-memory {PKG} RUNNING_LOW'); ed.idle(1)
        ed.dev.sh(f'am send-trim-memory {PKG} BACKGROUND')
        ed.idle(hold_s + 20)
        if ed.dev.pid() != pid:
            raise UIError('app process died while stopped (field process stayed alive)')
    finally:
        ed.dev.setprop('debug.zesty.hook.hold_add_video', '0')
    ed.dev.key('KEYCODE_WAKEUP'); ed.dev.sh('wm dismiss-keyguard')
    ed.mon.allow_death = False
    ed.dev.launch()
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_3_a(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): Home during import, both adds land ~90 s after on_stop (hold hook)."""
    _3fd540f0_run(ed, r, lambda: ed.dev.key('KEYCODE_HOME'), 'Home')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_3_b(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): another app (camera) covers the editor during import, adds land stopped (hold hook)."""
    def hide():
        ed.dev.key('KEYCODE_HOME')
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
    _3fd540f0_run(ed, r, hide, 'camera on top')


@scenario('nightshift', 'auto', 'nodraft')
def ns_3fd540f0_l5_3_c(ed, r):
    """Instance 1/1 (SM-S721B, Crashlytics 3fd540f0): screen off during import, adds land while stopped (hold hook)."""
    _3fd540f0_run(ed, r, lambda: ed.dev.key('KEYCODE_SLEEP'), 'screen off')
