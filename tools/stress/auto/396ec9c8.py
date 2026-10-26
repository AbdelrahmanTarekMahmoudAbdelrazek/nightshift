# Night Shift auto repros for 396ec9c89dd7daa94df5060a72e329ce


# 2026-10-26 03:07 level 2 attempt 1
def _396ec9c8_photo_editor(ed):
    """Home -> photo entry (gallery picker, Photos tab) -> newest photo -> PhotoActivity (the shipped app's photo editor)."""
    ed.step('home -> photo editor with the newest photo')
    for _ in range(6):
        s = ed.screen()
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
            ed.idle(2)
    if not ed.ui.tap(('textc:edit photo', 'textc:photo editor', 'textc:dehaze', 'textc:photo'), timeout=15):
        raise UIError('no photo-editor entry on the home screen')
    ed.ui.tap('id:image_tab', timeout=5)
    s = ed.ui.wait('id:gridrl', timeout=20)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('photo picker shows no photos')
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed.idle(1)
    ed._picker_confirm()
    ed.idle(6)


def _396ec9c8_open_resource(ed, labels):
    """Tap a photo-editor tool that opens the resource category browser; gate on its Activity START (checkpoint 2)."""
    mark = ed.log_mark()
    if not ed.ui.tap(tuple(f'textc:{l}' for l in labels), timeout=15):
        raise UIError(f'photo editor has no {labels} tool')
    ed.require_log(r'START u0 .*myzesty.*activity\.resource', 15, since=mark,
                   why='the resource screen (ResourcePresenter host) must be launched')
    ed.idle(4)


def _396ec9c8_restore(ed, r, times=1):
    """Home, system reclaims the process, user comes back: the resource screen is the first Activity of a new process."""
    for k in range(times):
        ed.kill_bg()
        ed.idle(r.uniform(3, 8))
        mark = ed.log_mark()
        ed.dev.launch()                               # existing task back to front, like Recents
        ed.require_log(r'Start proc .*myzesty', 15, since=mark, why='a fresh process must start (checkpoint 1)')
        ed.require_log(r'START u0 .*activity\.resource|activity\.resource.*(Displayed|wm_on_create)', 15, since=mark,
                       why='the resource screen must be the activity re-created at launch (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_1_a(ed, r):
    """All 16 (OnePlus8Pro x12, HRY-LX1T x4), restore path: sticker resource screen open, process reclaimed, user returns."""
    _396ec9c8_photo_editor(ed)
    _396ec9c8_open_resource(ed, ('sticker', 'stickers'))
    ed.ui.tap(('textc:trending', 'textc:recent', 'textc:neon'), timeout=5)   # pick a category like a user would
    ed.idle(2)
    _396ec9c8_restore(ed, r, times=1)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_1_b(ed, r):
    """All 16, entry-point path: open every resource tool of the photo editor in turn (one may launch without a category)."""
    _396ec9c8_photo_editor(ed)
    hit = 0
    for labels in (('sticker',), ('frame',), ('overlay',), ('background',), ('filter',), ('text',)):
        mark = ed.log_mark()
        if not ed.ui.tap(tuple(f'textc:{l}' for l in labels), timeout=6):
            continue
        if ed.wait_log(r'START u0 .*activity\.resource', 8, since=mark):
            hit += 1
            ed.idle(3)
            ed.dev.key('KEYCODE_BACK')
        ed.idle(2)
    if not hit:
        raise UIError('no photo-editor tool launched the resource screen (checkpoint 2 never reached)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_1_c(ed, r):
    """All 16, repeat path: frame/overlay resource screen re-created by rotation, then reclaimed and reopened twice (crash loop)."""
    _396ec9c8_photo_editor(ed)
    _396ec9c8_open_resource(ed, ('frame', 'overlay', 'sticker'))
    try:
        ed.dev.rotate(True)
        ed.idle(4)
        ed.dev.rotate(False)
        ed.idle(4)
    finally:
        ed.dev.restore_env()
    _396ec9c8_restore(ed, r, times=2)


# 2026-10-26 03:10 level 2 attempt 2
def _396ec9c8_cold_start(ed, why):
    """Launcher cold start of the PHOTO app (com.photo.myzesty). Stops the run as a setup error if the harness is on the video app."""
    pkgs = ed.dev.sh('pm list packages com.photo.myzesty')
    if 'com.photo.myzesty' not in pkgs:
        raise UIError('com.photo.myzesty is not installed: install 1.25.2 (800054890) from Play internal test')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.photo\.myzesty', 15, since=mark,
                   why=f'harness must drive the photo app (ZESTY_PKG=com.photo.myzesty), not com.myzesty: {why}')
    ed.require_log(r'Displayed com\.photo\.myzesty/', 20, since=mark, why='photo app must come up (no PairIP kill)')
    ed.idle(4)
    return mark


def _396ec9c8_open_resource(ed, labels):
    """Photo editor tool that opens the resource category screen (ResourcePresenter host); gate on its START."""
    for _ in range(3):
        ed.ui.tap(T.DISMISS, timeout=3)
    ed.ui.tap(('textc:edit photo', 'textc:photo editor', 'textc:photo'), timeout=8)
    ed.ui.tap(('id:gridrl',), timeout=8)              # newest photo, if the editor asks for one
    ed.ui.tap(('textc:done', 'textc:next'), timeout=5)
    ed.idle(4)
    mark = ed.log_mark()
    if not ed.ui.tap(tuple(f'textc:{l}' for l in labels), timeout=15):
        raise UIError(f'no {labels} tool on screen')
    ed.require_log(r'START u0 .*com\.photo\.myzesty/.*\.resource\.', 15, since=mark,
                   why='the resource screen (ResourcePresenter) must be launched (checkpoint 2)')
    ed.idle(3)
    ed.ui.tap(('textc:trending', 'textc:neon', 'textc:recent', 'textc:all'), timeout=5)
    ed.idle(3)


def _396ec9c8_return(ed, r, times):
    """System reclaims the process with the resource screen on top; user comes back through the task (checkpoints 1, 2, 5)."""
    for _ in range(times):
        ed.kill_bg()
        ed.idle(r.uniform(3, 8))
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'Start proc \d+:com\.photo\.myzesty', 15, since=mark, why='fresh process (checkpoint 1)')
        ed.require_log(r'com\.photo\.myzesty/.*\.resource\..*|wm_on_create_called: .*\.resource\.', 15, since=mark,
                       why='resource screen re-created as first activity of the new process (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_2_a(ed, r):
    """All 16 (OnePlus8Pro x12, HRY-LX1T x4), crash-loop path: repeated launcher cold starts of the photo app, seconds apart."""
    for k in range(4):
        _396ec9c8_cold_start(ed, f'cold start {k + 1}/4')
        ed.idle(r.uniform(2, 6))


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_2_b(ed, r):
    """All 16, restore path: sticker resource screen open, process reclaimed by the system, user returns twice."""
    _396ec9c8_cold_start(ed, 'before opening stickers')
    _396ec9c8_open_resource(ed, ('sticker', 'stickers'))
    _396ec9c8_return(ed, r, times=2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_2_c(ed, r):
    """All 16, offline restore path: resource screen opened with no network (no fetched categories), reclaimed, reopened."""
    _396ec9c8_cold_start(ed, 'before going offline')
    try:
        ed.dev.network(False)
        ed.idle(2)
        _396ec9c8_open_resource(ed, ('sticker', 'frame', 'overlay', 'background'))
        _396ec9c8_return(ed, r, times=2)
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:12 level 2 attempt 3
def _396ec9c8_cold_start(ed):
    """Force-stop, launcher cold start of com.myzesty; setup error if PairIP's LicenseActivity kills it (non-Play install)."""
    ed.step('cold start com.myzesty (must survive the Play license check)')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='fresh process (checkpoint 1)')
    ed.idle(4)
    if ed.wait_log(r'com\.myzesty .*has died|am_proc_died: \[\d+,\d+,com\.myzesty', 1, since=mark):
        raise UIError('com.myzesty died at cold start (pairip LicenseActivity): install 1.25.2 (800054890) '
                      'from the Play internal-test track, not adb')
    ed.mon.allow_death = False
    for _ in range(3):
        ed.ui.tap(T.DISMISS, timeout=3)


def _396ec9c8_open_resource(ed, labels):
    """Home -> Photo Editor (gallery, Photos tab, newest photo) -> PhotoActivity -> resource tool; gate on its START."""
    ed.step(f'photo editor -> {labels[0]} resource screen')
    if not ed.ui.tap(('textc:photo editor', 'textc:edit photo', 'textc:dehaze'), timeout=15):
        raise UIError('no Photo Editor entry on the home screen')
    ed.ui.tap('id:image_tab', timeout=5)
    s = ed.ui.wait('id:gridrl', timeout=20)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('photo picker shows no photos')
    mark = ed.log_mark()
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed.idle(1)
    ed._picker_confirm()
    ed.require_log(r'com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity', 20, since=mark,
                   why='PhotoActivity (photo editor) must open')
    ed.idle(5)
    mark = ed.log_mark()
    if not ed.ui.tap(tuple(f'textc:{l}' for l in labels), timeout=15):
        raise UIError(f'photo editor has no {labels} tool')
    ed.require_log(r'START u0 .*com\.photo\.myzesty\.ui\.activity\.resource\.', 15, since=mark,
                   why='resource screen (ResourcePresenter host) must launch (checkpoint 2)')
    ed.idle(4)


def _396ec9c8_return(ed, r, times, gap=(3, 8)):
    """System reclaims the process with the resource screen on top; user comes back (checkpoints 1, 2, 5)."""
    for k in range(times):
        ed.step(f'process reclaimed, user returns {k + 1}/{times}')
        ed.kill_bg()
        ed.idle(r.uniform(*gap))
        mark = ed.log_mark()
        ed.dev.launch()                                   # existing task to front, like Recents
        ed.require_log(r'Start proc \d+:com\.myzesty/', 15, since=mark, why='fresh process (checkpoint 1)')
        ed.require_log(r'wm_on_create_called: .*com\.photo\.myzesty\.ui\.activity\.resource\.', 15, since=mark,
                       why='resource screen re-created as the first activity of the new process (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_3_a(ed, r):
    """All 16 (OnePlus8Pro x12, HRY-LX1T x4), restore path: sticker screen on a non-default category, reclaimed, user returns twice."""
    _396ec9c8_cold_start(ed)
    _396ec9c8_open_resource(ed, ('sticker', 'stickers'))
    ed.ui.tap(('textc:neon', 'textc:trending', 'textc:reactions'), timeout=5)
    ed.idle(3)
    _396ec9c8_return(ed, r, times=2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_3_b(ed, r):
    """All 16, offline-return path: frame/overlay resource screen, reclaimed, user returns with no network (no fetched categories)."""
    _396ec9c8_cold_start(ed)
    _396ec9c8_open_resource(ed, ('frame', 'frames', 'overlay', 'background'))
    try:
        ed.dev.network(False)
        _396ec9c8_return(ed, r, times=2)
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l2_3_c(ed, r):
    """OnePlus8Pro 08:04:47/08:04:51 crash loop: reclaimed while the sticker list still loads, returns 3-5 s apart."""
    _396ec9c8_cold_start(ed)
    _396ec9c8_open_resource(ed, ('sticker', 'stickers'))   # no extra idle: categories may still be fetching
    _396ec9c8_return(ed, r, times=3, gap=(3, 5))


# 2026-10-26 03:14 level 3 attempt 1
def _396ec9c8_cold(ed, why):
    """Cold start that must survive (checkpoint 1): stops as a SETUP error when PairIP kills a sideloaded build."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'fresh process ({why})')
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why=f'first screen up ({why})')
    ed.idle(3)
    if ed.wait_log(r'Process com\.myzesty \(pid \d+\) has died', 1, since=mark) or ed.dev.pid() == '':
        raise UIError('SETUP: PairIP LicenseActivity killed the app ~0.1 s after start: install 1.25.2 (800054890) '
                      'from the Play internal-test track (not adb) before running this crash')
    ed.mon.allow_death = False
    return mark


def _396ec9c8_resource_open(ed, r):
    """Editor -> sticker resource browser (twin of the photo app's ResourcePresenter) -> pick a category."""
    ed.open_draft()
    ed.idle(6)                                        # sticker tool right after load dies on this phone (lab fact)
    mark = ed.log_mark()
    ed.tap_tool('sticker')
    ed.require_log(r'sticker', 10, since=mark, why='resource (sticker) category screen must open (checkpoint 2)')
    ed.idle(2)
    ed.ui.tap(r.choice([('textc:trending',), ('textc:neon',), ('textc:reactions',)]), timeout=5)
    ed.idle(3)


def _396ec9c8_restore(ed, r, times):
    """System reclaims the process with the resource screen on top; user returns: it is re-created first (cp 2, 5)."""
    for k in range(times):
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.kill_bg()
        ed.idle(r.uniform(3, 8))
        mark = ed.log_mark()
        ed.dev.launch()                               # existing task to front, like Recents
        ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1}')
        ed.require_log(r'wm_on_create_called: .*PlayerActivity', 15, since=mark,
                       why='resource screen host re-created as first activity of the new pid (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_1_a(ed, r):
    """All 16 (OnePlus8Pro x12, HRY-LX1T x4), restore path: resource screen open, memory pressure reclaims it, user returns 2x."""
    _396ec9c8_cold(ed, 'before the resource screen')
    _396ec9c8_resource_open(ed, r)
    _396ec9c8_restore(ed, r, times=2)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_1_b(ed, r):
    """All 16, persisted-data crash loop: no cached/fetched categories (cache cleared, offline), cold starts seconds apart."""
    try:
        ed.dev.clear_app_cache()
        ed.dev.network(False)
        _396ec9c8_cold(ed, 'offline, empty cache')
        _396ec9c8_resource_open(ed, r)               # categories mapped with nothing fetched
        for k in range(3):                            # field: 08:04:47 and 08:04:51 on one phone
            _396ec9c8_cold(ed, f'relaunch {k + 1}/3')
            ed.idle(r.uniform(2, 6))
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_1_c(ed, r):
    """All 16, lost-state path: config change (dark mode) on the resource screen, then reclaimed and restored offline."""
    try:
        _396ec9c8_cold(ed, 'before dark mode')
        _396ec9c8_resource_open(ed, r)
        ed.dev.dark_mode(True)
        ed.idle(4)
        ed.dev.network(False)
        _396ec9c8_restore(ed, r, times=2)
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:16 level 3 attempt 2
_396ec9c8_CANDIDATES = ('ResourceActivity', 'ResourcesActivity', 'ResourceCategoryActivity', 'ResourceListActivity')


def _396ec9c8_setup(ed):
    """SETUP gate: it must be the Play internal-test 1.25.2 build (a sideloaded build is killed by PairIP), then cold start must stay alive."""
    info = ed.dev.sh('dumpsys package com.myzesty | grep -E "versionCode|installerPackageName|initiatingPackageName"')
    if '800054890' not in info or 'com.android.vending' not in info:
        raise UIError(f'SETUP: need 1.25.2 (800054890) installed FROM PLAY internal test (PairIP kills adb installs): {info.strip()[:200]}')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why='first screen up (checkpoint 1)')
    ed.idle(4)
    if ed.wait_log(r'Process com\.myzesty \(pid \d+\) has died', 1, since=mark) or ed.dev.pid() == '':
        raise UIError('SETUP: app died right after start (PairIP LicenseActivity): not a Play-licensed install')
    ed.mon.allow_death = False


def _396ec9c8_component(ed):
    """The resource screen (ResourcePresenter host) inside the installed APK, under com.photo.myzesty.ui.activity.resource."""
    found = ed.dev.sh('dumpsys package com.myzesty | grep -o "com\\.photo\\.myzesty\\.ui\\.activity\\.resource\\.[A-Za-z0-9_]*Activity" | sort -u')
    names = [l.strip() for l in found.splitlines() if l.strip()]
    names += [f'com.photo.myzesty.ui.activity.resource.{c}' for c in _396ec9c8_CANDIDATES]
    for cls in names:
        out = ed.dev.sh(f'am start -W -n com.myzesty/{cls}')     # probe on the live process; no extras = the bare entry point
        if 'does not exist' not in out and 'Error' not in out:
            return f'com.myzesty/{cls}'
        if 'Permission Denial' in out or 'not exported' in out:
            raise UIError(f'SETUP: {cls} is not exported; shell cannot start it: {out.strip()[:160]}')
    raise UIError('SETUP: no resource activity in the installed APK (read its manifest with aapt for the class name)')


def _396ec9c8_cold_resource(ed, comp, k):
    """Fresh process whose FIRST activity is the resource screen, started with no category extra (checkpoints 1-4)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.dev.sh(f'am start -n {comp} -f 0x10000000')
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'fresh process {k} (checkpoint 1)')
    ed.require_log(r'wm_on_create_called: .*\.resource\.', 10, since=mark, why=f'resource screen created first {k} (checkpoint 2)')
    ed.idle(5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_2_a(ed, r):
    """All 16 (OnePlus8Pro x12, HRY-LX1T x4), entry-point path: resource screen as first activity, offline + empty cache, relaunched seconds apart."""
    _396ec9c8_setup(ed)
    comp = _396ec9c8_component(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.network(False)                        # no fetched categories: only what is stored on the phone
        for k in range(3):                           # field: 08:04:47 and 08:04:51 on one phone
            _396ec9c8_cold_resource(ed, comp, k + 1)
            ed.idle(r.uniform(1, 4))
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_2_b(ed, r):
    """All 16, restore path: resource screen open, memory pressure + system reclaims the process, user returns through the task twice."""
    _396ec9c8_setup(ed)
    comp = _396ec9c8_component(ed)
    ed.idle(4)
    ed.ui.tap(('textc:trending', 'textc:all', 'textc:recent'), timeout=5)   # a selected category goes into saved state
    ed.idle(2)
    for k in range(2):
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.kill_bg()
        ed.idle(r.uniform(3, 8))
        mark = ed.log_mark()
        ed.dev.launch()                              # existing task comes back: resource screen re-created from saved state
        ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1} (checkpoint 1)')
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark,
                       why=f'resource screen restored as first activity {k + 1} (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_2_c(ed, r):
    """All 16, persisted-data path: category fetch cut halfway on a slow network, then cold relaunches into the resource screen offline."""
    _396ec9c8_setup(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.slow_network(r.choice([20, 40, 80]))  # categories arrive in pieces and are stored half-written
        comp = _396ec9c8_component(ed)
        ed.idle(r.uniform(1.5, 4))
        ed.dev.network(False)                        # fetch dies mid-way
        ed.idle(3)
        for k in range(2):
            _396ec9c8_cold_resource(ed, comp, k + 1)
            ed.idle(r.uniform(2, 6))
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:17 level 3 attempt 3
_396ec9c8_RES = ('ResourceActivity', 'ResourcesActivity', 'ResourceCategoryActivity', 'ResourceListActivity')


def _396ec9c8_licensed(ed):
    """SETUP gate (checkpoint 1): a cold start must get past PairIP's LicenseActivity, which only a Play install does."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why='fresh process (checkpoint 1)')
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why='first screen up (checkpoint 1)')
    ed.idle(5)
    if ed.wait_log(r'Process com\.myzesty \(pid \d+\) has died', 1, since=mark) or ed.dev.pid() == '':
        raise UIError('SETUP: PairIP LicenseActivity killed the app: the phone still has an adb install. Install 1.25.2 '
                      '(800054890) from the Play internal-test track with a tester account, then rerun')
    ed.mon.allow_death = False


def _396ec9c8_cold_entry(ed, k):
    """Fresh process whose FIRST activity is the photo app's resource screen, no category extra (checkpoints 2-4)."""
    for c in _396ec9c8_RES:
        ed.mon.allow_death = True
        ed.dev.force_stop()
        mark = ed.log_mark()
        out = ed.dev.sh(f'am start -W -n com.myzesty/com.photo.myzesty.ui.activity.resource.{c}')
        ed.mon.allow_death = False
        if 'does not exist' in out or 'Error type 3' in out:
            continue
        if 'Permission Denial' in out or 'not exported' in out:
            raise UIError(f'SETUP: {c} is not exported; only the restore path (recipe b) can make it the first activity')
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 10, since=mark, why=f'resource screen first {k} (checkpoint 2)')
        ed.idle(5)
        return
    raise UIError('SETUP: no com.photo.myzesty.ui.activity.resource.* activity in the installed APK')


def _396ec9c8_open_resource(ed, r):
    """Home -> photo editor (com.photo.myzesty PhotoActivity) -> a category browser (the ResourcePresenter screen)."""
    mark = ed.log_mark()
    ed.ui.tap(('textc:photo', 'textc:edit photo', 'textc:image'), timeout=8)
    ed.require_log(r'com\.photo\.myzesty', 20, since=mark, why='photo editor must open (field package com.photo.myzesty)')
    ed.idle(3)
    mark = ed.log_mark()
    ed.ui.tap(r.choice([('textc:sticker',), ('textc:frame',), ('textc:background',), ('textc:filter',)]), timeout=8)
    ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why='resource screen opened (checkpoint 2)')
    ed.idle(3)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_3_a(ed, r):
    """OnePlus8Pro x12 (08:04:47/08:04:51 pairs): resource screen as first activity, offline + empty cache, relaunched seconds apart."""
    _396ec9c8_licensed(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.network(False)                        # nothing fetched: only stored category data is mapped
        for k in range(3):
            _396ec9c8_cold_entry(ed, k + 1)
            ed.idle(r.uniform(1, 4))
    finally:
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_3_b(ed, r):
    """HRY-LX1T x4 (07:38/07:49 minutes apart): resource screen open, memory pressure reclaims the app, user returns 2x."""
    _396ec9c8_licensed(ed)
    _396ec9c8_open_resource(ed, r)
    for k in range(2):
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.kill_bg()
        ed.idle(r.uniform(4, 10))
        mark = ed.log_mark()
        ed.dev.launch()                              # task comes back: resource screen restored before anything else
        ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1} (checkpoint 1)')
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark,
                       why=f'resource screen restored as first activity {k + 1} (checkpoint 2)')
        ed.idle(6)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l3_3_c(ed, r):
    """All 16, persisted-data path: category fetch cut mid-way on a slow network, then reclaimed and restored offline."""
    _396ec9c8_licensed(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.slow_network(r.choice([20, 40, 80]))  # categories arrive in pieces
        _396ec9c8_open_resource(ed, r)
        ed.dev.network(False)                        # fetch dies half-stored
        ed.idle(3)
        ed.kill_bg()
        ed.idle(r.uniform(2, 5))
        mark = ed.log_mark()
        ed.dev.launch()
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark,
                       why='resource screen restored offline as first activity (checkpoint 2)')
        ed.idle(6)
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:19 level 4 attempt 1
_396ec9c8_RES = ('ResourceActivity', 'ResourcesActivity', 'ResourceCategoryActivity', 'ResourceListActivity')


def _396ec9c8_licensed(ed):
    """Checkpoint 1 gate: a cold start must get past PairIP's LicenseActivity (only a Play install does)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why='fresh process (checkpoint 1)')
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why='first screen up (checkpoint 1)')
    ed.idle(4)
    if ed.wait_log(r'LicenseActivity|Process com\.myzesty \(pid \d+\) has died', 1, since=mark) or ed.dev.pid() == '':
        raise UIError('SETUP: PairIP LicenseActivity killed the app: still an adb install. Install 1.25.2 (800054890) '
                      'from the Play internal-test track with a tester account, then rerun')
    ed.mon.allow_death = False


def _396ec9c8_open_resource(ed, r):
    """Home -> photo editor (pick an image) -> a category browser = the ResourcePresenter screen (checkpoint 2)."""
    ed.ui.tap(('textc:photo', 'textc:edit photo', 'textc:new project'), timeout=8)
    ed.ui.tap(('id:image_tab', 'textc:image', 'textc:photos'), timeout=5)
    ed.ui.tap(('id:thumbnail', 'id:img'), timeout=8)
    ed.ui.tap(('id:done', 'id:btn_done', 'textc:next'), timeout=5)
    mark = ed.log_mark()
    ed.ui.tap(r.choice([('textc:sticker',), ('textc:frame',), ('textc:background',)]), timeout=10)
    ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why='resource screen opened (checkpoint 2)')
    return mark


def _396ec9c8_return(ed, k):
    """User comes back through the task after the process was reclaimed: the resource screen is created FIRST."""
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k} (checkpoint 1)')
    ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why=f'resource screen restored first {k} (checkpoint 2)')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_1_a(ed, r):
    """OnePlus8Pro x12 (08:04:47/08:04:51 pairs): resource screen started bare (no category extra) as first activity, 4x ~4 s apart."""
    _396ec9c8_licensed(ed)
    for k in range(4):
        ed.mon.allow_death = True
        ed.dev.force_stop()
        ed.mon.allow_death = False
        mark = ed.log_mark()
        out = ''
        for c in _396ec9c8_RES:
            out = ed.dev.sh(f'am start -n com.myzesty/com.photo.myzesty.ui.activity.resource.{c} -f 0x10000000')
            if 'does not exist' not in out and 'Error type 3' not in out:
                break
        if 'Permission Denial' in out or 'not exported' in out or 'Error' in out:
            raise UIError(f'SETUP: resource activity cannot be started bare from shell: {out.strip()[:160]}')
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 10, since=mark, why=f'resource screen first {k + 1} (checkpoint 2)')
        ed.idle(r.uniform(2.5, 4.5))                  # field: the same phone relaunched 4 s later


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_1_b(ed, r):
    """HRY-LX1T x4 + OnePlus restores: resource screen open, process reclaimed, returned at once 3x on a slowed phone."""
    _396ec9c8_licensed(ed)
    _396ec9c8_open_resource(ed, r)
    ed.idle(2)
    try:
        for k in range(3):
            ed.kill_bg()                              # process death drops in-memory category state; task stays
            ed.idle(r.uniform(0.5, 2))
            ed.dev.slow_phone(r.randint(20, 40))      # low-end launch timing at the restore
            _396ec9c8_return(ed, k + 1)
            ed.dev.slow_phone(0)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_1_c(ed, r):
    """All 16, mid-load window: process reclaimed 0.2-1.5 s after the resource screen's onCreate (categories not loaded yet), restored offline."""
    _396ec9c8_licensed(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.slow_network(r.choice([20, 40]))       # category fetch still in flight when the process dies
        mark = _396ec9c8_open_resource(ed, r)
        ed.idle(r.uniform(0.2, 1.5))
        ed.kill_bg()
        ed.dev.network(False)
        for k in range(2):
            _396ec9c8_return(ed, k + 1)
            ed.kill_bg()
            ed.idle(r.uniform(1, 3))
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:21 level 4 attempt 2
_396ec9c8_RES = ('ResourceActivity', 'ResourcesActivity', 'ResourceCategoryActivity', 'ResourceListActivity', 'ResourceDetailActivity')
_396ec9c8_PKG = 'com.photo.myzesty.ui.activity.resource.'


def _396ec9c8_gate(ed):
    """Checkpoint 1: a cold start must get past PairIP's LicenseActivity (only a Play internal-test install does)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why='fresh process (checkpoint 1)')
    ed.require_log(r'Displayed com\.myzesty/', 20, since=mark, why='first screen up (checkpoint 1)')
    ed.idle(3)
    if ed.wait_log(r'pairip\.licensecheck\.LicenseActivity|Process com\.myzesty \(pid \d+\) has died', 1, since=mark) or not ed.dev.pid():
        raise UIError('SETUP: PairIP killed the app = adb/sideloaded install. Install 1.25.2 (800054890) FROM PLAY internal test')
    ed.mon.allow_death = False


def _396ec9c8_start_bare(ed, k):
    """Fresh process whose FIRST activity is the resource screen, started with no category extra (checkpoints 2-4)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    mark = ed.log_mark()
    for c in _396ec9c8_RES:
        out = ed.dev.sh(f'am start -n com.myzesty/{_396ec9c8_PKG}{c} -f 0x10000000')
        if 'does not exist' in out or 'Error type 3' in out:
            continue
        if 'Permission Denial' in out or 'not exported' in out:
            raise UIError(f'SETUP: {c} not exported; only the restore path (recipe b) can make it first: {out.strip()[:120]}')
        ed.require_log(r'Start proc \d+:com\.myzesty', 10, since=mark, why=f'fresh process {k} (checkpoint 1)')
        ed.require_log(r'wm_on_create_called: .*\.resource\.', 10, since=mark, why=f'resource screen first {k} (checkpoint 2)')
        return
    raise UIError(f'SETUP: no {_396ec9c8_PKG}* activity in the installed APK (photo module not shipped in this build)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_2_a(ed, r):
    """OnePlus8Pro x12 (08:04:47/08:04:51): resource screen cold-started bare as first activity, relaunch storm 1-4 s apart."""
    _396ec9c8_gate(ed)
    for k in range(6):
        _396ec9c8_start_bare(ed, k + 1)
        ed.idle(r.uniform(1, 4))                         # the field phone relaunched 4 s after crashing


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_2_b(ed, r):
    """HRY-LX1T x4 (07:38/07:49): resource screen open, process reclaimed, user returns via the task on a slow phone, 3x."""
    _396ec9c8_gate(ed)
    _396ec9c8_start_bare(ed, 0)                          # resource screen on top of the task (if it survives bare)
    ed.ui.tap(('textc:trending', 'textc:recent', 'textc:all'), timeout=5)
    ed.idle(2)
    try:
        for k in range(3):
            ed.kill_bg()                                 # in-memory category gone, task + saved state kept
            ed.idle(r.uniform(1, 6))
            ed.dev.slow_phone(r.randint(20, 40))         # low-end restore timing
            mark = ed.log_mark()
            ed.dev.launch()
            ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1} (checkpoint 1)')
            ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why=f'resource restored first {k + 1} (checkpoint 2)')
            ed.idle(4)
            ed.dev.slow_phone(0)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_2_c(ed, r):
    """All 16, persisted-data path: process killed 0.2-1.5 s into the resource screen's category fetch, then cold relaunched offline 3x."""
    _396ec9c8_gate(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.slow_network(r.choice([20, 40]))          # categories still arriving when the process dies
        _396ec9c8_start_bare(ed, 0)
        ed.idle(r.uniform(0.2, 1.5))
        ed.mon.allow_death = True
        ed.dev.force_stop()
        ed.mon.allow_death = False
        ed.dev.network(False)                            # only the half-stored data is mapped at the next launch
        for k in range(3):
            _396ec9c8_start_bare(ed, k + 1)
            ed.idle(r.uniform(1, 4))
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:22 level 4 attempt 3
_396ec9c8_PKG = 'com.myzesty'


def _396ec9c8_gate(ed):
    """Checkpoint 1 SETUP gate, checked BEFORE any launch: PairIP kills every non-Play install (9/9 earlier runs)."""
    inst = ed.dev.sh(f'dumpsys package {_396ec9c8_PKG} | grep -E "installerPackageName|versionCode" ')
    if 'com.android.vending' not in inst or '800054890' not in inst:
        raise UIError(f'SETUP: {_396ec9c8_PKG} is not the Play internal-test 1.25.2 (800054890) install '
                      f'({inst.strip()[:140]}); PairIP LicenseActivity kills adb installs. Install it from Play first')
    acts = ed.dev.sh(f'dumpsys package {_396ec9c8_PKG} | grep -oE "com\\.photo\\.myzesty\\.ui\\.activity\\.resource\\.[A-Za-z]+" | sort -u')
    names = [a.strip() for a in acts.split() if a.strip()]
    if not names:
        raise UIError('SETUP: installed APK has no com.photo.myzesty.ui.activity.resource.* activity')
    return names[0]


def _396ec9c8_cold(ed, act, k, extra=''):
    """Force-stop, then a fresh process whose FIRST activity is the resource screen (checkpoints 1-2)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    mark = ed.log_mark()
    out = ed.dev.sh(f'am start -n {_396ec9c8_PKG}/{act} -f 0x10000000 {extra}')
    if 'Permission Denial' in out or 'Error' in out:
        raise UIError(f'SETUP: {act} cannot be the first activity from shell: {out.strip()[:140]}')
    ed.require_log(r'Start proc \d+:com\.myzesty', 10, since=mark, why=f'fresh process {k} (checkpoint 1)')
    ed.require_log(r'wm_on_create_called: .*\.resource\.', 10, since=mark, why=f'resource screen first {k} (checkpoint 2)')
    if ed.wait_log(r'licensecheck\.LicenseActivity', 1, since=mark):
        raise UIError('SETUP: PairIP LicenseActivity started: not a Play install')


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_3_a(ed, r):
    """OnePlus8Pro x12 (08:04:47/08:04:51 pair): resource screen cold-started bare as first activity, relaunch storm 1-4 s apart."""
    act = _396ec9c8_gate(ed)
    for k in range(6):
        _396ec9c8_cold(ed, act, k + 1)
        ed.idle(r.uniform(1, 4))


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_3_b(ed, r):
    """HRY-LX1T x4 (07:38/07:49): resource screen open, process reclaimed, restored from Recents first on a slowed phone, 3x."""
    act = _396ec9c8_gate(ed)
    _396ec9c8_cold(ed, act, 0, '--es category ""')
    ed.idle(4)                                       # categories load and are cached
    try:
        for k in range(3):
            ed.kill_bg()                             # saved state kept, in-memory category gone
            ed.idle(r.uniform(1, 5))
            ed.dev.slow_phone(r.randint(20, 40))
            mark = ed.log_mark()
            ed.dev.launch()
            ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1} (checkpoint 1)')
            ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why=f'resource restored first {k + 1} (checkpoint 2)')
            ed.idle(4)
            ed.dev.slow_phone(0)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l4_3_c(ed, r):
    """All 16, entry-point path: cold start from a real FCM push into the resource screen, category cached half-fetched offline."""
    act = _396ec9c8_gate(ed)
    try:
        ed.dev.slow_network(r.choice([20, 40]))
        _396ec9c8_cold(ed, act, 0)
        ed.idle(r.uniform(0.3, 1.5))                 # category fetch still in flight
        ed.kill_bg()
        ed.dev.network(False)
        for k in range(3):
            mark = ed.log_mark()
            ed.dev.fcm_push('New stickers', 'Check the new category', data={'screen': 'resource', 'category': ''},
                            foreground=False, wait=3)
            ed.ui.tap(('textc:new stickers',), timeout=5)   # notification tap; carries on if the app opened by itself
            ed.require_log(r'wm_on_create_called: .*\.resource\.', 15, since=mark, why=f'push opened resource screen {k + 1} (checkpoint 2)')
            ed.idle(r.uniform(2, 5))
            ed.kill_bg()
    finally:
        ed.dev.restore_env()


# 2026-10-26 03:26 level 5 attempt 3
_396ec9c8_PKG = 'com.myzesty'
_396ec9c8_RES = r'wm_on_create_called: \[\d+,com\.photo\.myzesty\.ui\.activity\.resource\.'
_396ec9c8_HOOK = 'debug.zesty.hook.null_resource_category'


def _396ec9c8_gate(ed):
    """Checkpoint 1 SETUP: a Play install that survives PairIP; returns the installed resource activity class."""
    inst = ed.dev.sh(f'pm list packages -i {_396ec9c8_PKG}')
    mark = ed.log_mark()
    ed.dev.launch()
    if 'com.android.vending' not in inst or ed.wait_log(r'licensecheck\.LicenseActivity', 4, since=mark) or not ed.dev.pid():
        raise UIError(f'SETUP: {_396ec9c8_PKG} is not the Play internal-test 1.25.2 install ({inst.strip()[:80]}); '
                      'PairIP LicenseActivity kills it. Install from Play first')
    names = ed.dev.sh(f'dumpsys package {_396ec9c8_PKG} | grep -oE "com\\.photo\\.myzesty\\.ui\\.activity\\.resource\\.[A-Za-z]+" | sort -u').split()
    for act in names + ['com.photo.myzesty.ui.activity.resource.ResourceActivity',
                        'com.photo.myzesty.ui.activity.resource.ResourcesActivity']:
        if 'does not exist' not in ed.dev.sh(f'cmd package resolve-activity -c android.intent.category.DEFAULT --components {_396ec9c8_PKG}/{act} 2>&1'):
            return act
    raise UIError('SETUP: installed APK has no com.photo.myzesty.ui.activity.resource.* activity')


def _396ec9c8_cold(ed, act, k, extra=''):
    """Force-stop, then a NEW process whose first activity is the resource screen (checkpoints 1-2)."""
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.mon.allow_death = False
    mark = ed.log_mark()
    out = ed.dev.sh(f'am start -n {_396ec9c8_PKG}/{act} -f 0x10000000 {extra}')
    if 'Permission Denial' in out or 'Error' in out:
        raise UIError(f'SETUP: {act} cannot be started first from shell: {out.strip()[:140]}')
    ed.require_log(r'Start proc \d+:com\.myzesty', 10, since=mark, why=f'fresh process {k} (checkpoint 1)')
    ed.require_log(_396ec9c8_RES, 10, since=mark, why=f'resource screen created first {k} (checkpoint 2)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l5_3_a(ed, r):
    """OnePlus8Pro x12 (08:04:47/08:04:51 pair): resource screen cold-started with NO category extra, relaunched 2-5 s apart."""
    act = _396ec9c8_gate(ed)
    for k in range(4):                               # checkpoint 5: bad entry repeats seconds apart
        _396ec9c8_cold(ed, act, k + 1)
        ed.idle(r.uniform(2, 5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l5_3_b(ed, r):
    """HRY-LX1T x4 (07:38/07:49): resource screen open, process reclaimed, restored from Recents with its category lost (hook)."""
    act = _396ec9c8_gate(ed)
    _396ec9c8_cold(ed, act, 0, '--es type non_animated --es category Trending')
    ed.idle(4)
    ed.dev.setprop(_396ec9c8_HOOK, '1')              # the restored launch Intent arrives without its category
    try:
        for k in range(3):
            ed.kill_bg()
            ed.idle(r.uniform(1, 4))
            mark = ed.log_mark()
            ed.dev.launch()                          # brings the old task back: resource screen is recreated first
            ed.require_log(r'Start proc \d+:com\.myzesty', 15, since=mark, why=f'new process on return {k + 1} (checkpoint 1)')
            ed.require_log(_396ec9c8_RES, 15, since=mark, why=f'resource restored first {k + 1} (checkpoint 2)')
            ed.idle(4)
    finally:
        ed.dev.setprop(_396ec9c8_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_396ec9c8_l5_3_c(ed, r):
    """All 16, cached-data path: category cache cleared, phone offline and slow, resource screen launched with a normal category."""
    act = _396ec9c8_gate(ed)
    try:
        ed.dev.clear_app_cache()
        ed.dev.network(False)                        # no fetch can refill the category model before onCreate maps it
        ed.dev.slow_phone(r.randint(20, 40))
        for k in range(3):
            _396ec9c8_cold(ed, act, k + 1, '--es type non_animated --es category Trending')
            ed.idle(r.uniform(3, 6))
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()
