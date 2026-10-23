# Night Shift auto repros for ff832bfcc56293d50aff6f599afbdda8


# 2026-10-10 09:25 level 2 attempt 1
def _ff832bfc_seed_image(ed):
    """Put a fresh image at the top of the gallery's Images tab (the crop screens only take images)."""
    p = '/sdcard/DCIM/NightShift/ns_ff832bfc.png'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'screencap -p {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
    ed.idle(2)


def _ff832bfc_picker_crop(ed):
    """Editor + -> gallery -> Images tab -> long-press the newest image -> crop screen -> Done."""
    ed.step('open the picker and the crop screen for an image')
    if not ed.ui.tap(('id:add_video', 'id:addVideo'), timeout=10):
        raise UIError('add media button not found')
    if ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20) is None:
        raise UIError('gallery picker did not open')
    ed.ui.tap('id:image_tab', timeout=5)
    ed.idle(1.5)
    s = ed.ui.wait('id:gridrl', timeout=10)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('no images in the picker')
    x, y = s.find_all('id:gridrl')[0].center
    ed.dev.swipe(x, y, x, y, 900)                   # long-press: images go straight to the crop screen
    ed.idle(3)                                      # a user looks at the crop screen
    ed._picker_confirm()                            # crop + add
    ed.idle(4)


@scenario('nightshift', 'auto')
def ns_ff832bfc_l2_1_a(ed, r):
    """All 7 instances (HRY-LX1T x4, OnePlus 8 Pro x3), path A: crop an image from the editor's gallery picker, twice like the field retries."""
    _ff832bfc_seed_image(ed)
    ed.set_playing(False)
    for _ in range(2):
        _ff832bfc_picker_crop(ed)
        ed.idle(r.uniform(2, 5))


@scenario('nightshift', 'auto')
def ns_ff832bfc_l2_1_b(ed, r):
    """All 7 instances, path B: Cover -> Upload from Gallery -> pick an image -> crop screen -> Done."""
    _ff832bfc_seed_image(ed)
    ed.set_playing(False)
    ed.step('cover: upload from gallery and crop')
    if not ed.ui.tap('id:cover_thumbnail', timeout=10):
        raise UIError('cover button (cover_thumbnail) not found')
    if not ed.ui.tap('id:tab_gallery', timeout=10):
        raise UIError('CoverActivity tab_gallery not found')
    ed.ui.tap('id:image_tab', timeout=5)
    s = ed.ui.wait('id:gridrl', timeout=15)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('no images in the cover picker')
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed.idle(4)                                      # crop screen comes up
    ed.ui.tap('id:done', timeout=5)
    ed.idle(3)
    ed.ui.tap('id:done', timeout=5)                 # CoverActivity Done
    ed.idle(3)


@scenario('nightshift', 'auto')
def ns_ff832bfc_l2_1_c(ed, r):
    """All 7 instances (0 log lines, crash right as the app comes back): leave the app on a crop screen, the process dies in the background, the user returns and the system restores the top activity."""
    _ff832bfc_seed_image(ed)
    ed.set_playing(False)
    if not ed.ui.tap(('id:add_video', 'id:addVideo'), timeout=10):
        raise UIError('add media button not found')
    ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    ed.ui.tap('id:image_tab', timeout=5)
    s = ed.ui.wait('id:gridrl', timeout=10)
    if s is None or not s.find_all('id:gridrl'):
        raise UIError('no images in the picker')
    x, y = s.find_all('id:gridrl')[0].center
    ed.dev.swipe(x, y, x, y, 900)
    ed.idle(3)
    for _ in range(2):                              # field: two launches 4 s apart
        ed.step('home on the crop screen, process killed, return')
        ed.mon.allow_death = True
        ed.dev.key('KEYCODE_HOME')
        ed.idle(3)
        ed.dev.sh(f'am kill {PKG}')
        ed.idle(r.uniform(4, 8))
        ed.dev.launch()                             # restores the task's top activity in a new process
        ed.idle(4)
        ed.mon.allow_death = False


# 2026-10-10 09:34 level 2 attempt 2
_FF832BFC_CMP = 'com.myzesty/com.yalantis.ucrop.UCropActivity'


def _ff832bfc_preflight(ed):
    """Checkpoint 1: the installed APK must declare UCropActivity (the lab 1.11.0 build does not)."""
    out = ed.dev.sh(f'cmd package query-activities --components -n {_FF832BFC_CMP}') or ''
    if 'UCropActivity' not in out:
        raise UIError('installed APK does not declare com.yalantis.ucrop.UCropActivity '
                      '(install field build 1.25.1/800054867 or a build whose merged manifest has it)')


def _ff832bfc_seed_image(ed):
    p = '/sdcard/DCIM/NightShift/ns_ff832bfc.png'
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'screencap -p {p}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{p} >/dev/null 2>&1')
    ed.idle(2)
    return p


def _ff832bfc_start_crop(ed, src, extra=''):
    """Checkpoints 2+3: explicit START of UCropActivity, bottom controls NOT hidden (crash comes in onCreate:142 -> :459)."""
    ed.step('START UCropActivity with bottom controls shown')
    ed.dev.marker('ff832bfc START UCropActivity')
    out = ed.dev.sh(f'am start -W -n {_FF832BFC_CMP} --eu myzesty.InputUri file://{src} '
                    f'--eu myzesty.OutputUri file:///data/user/0/com.myzesty/cache/ns_ff832bfc_out.png {extra}') or ''
    if 'does not exist' in out or 'Permission Denial' in out or 'Error' in out:
        raise UIError(f'UCropActivity launch refused: {out.strip()[-200:]}')
    ed.idle(4)                                      # ClassCastException kills the process here


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l2_2_a(ed, r):
    """OnePlus 8 Pro x3 (08:05:51/08:05:55 retry pair): cold launch of UCropActivity with default options, user retries 4 s later."""
    _ff832bfc_preflight(ed)
    src = _ff832bfc_seed_image(ed)
    _ff832bfc_start_crop(ed, src)
    ed.idle(4)                                      # field retry gap
    _ff832bfc_start_crop(ed, src)


@scenario('nightshift', 'auto')
def ns_ff832bfc_l2_2_b(ed, r):
    """HUAWEI HRY-LX1T x4 (single launches hours apart): crop screen opened on top of the live editor task, HideBottomControls explicitly false."""
    _ff832bfc_preflight(ed)
    src = _ff832bfc_seed_image(ed)
    ed.set_playing(False)
    ed.idle(r.uniform(2, 4))                        # user is in the editor when the crop screen opens
    _ff832bfc_start_crop(ed, src, extra='--ez myzesty.HideBottomControls false')


# 2026-10-10 09:58 level 3 attempt 1
_FF832BFC_ACT = 'com.yalantis.ucrop.UCropActivity'
_FF832BFC_IMG = '/sdcard/DCIM/NightShift/ns_ff832bfc.png'


def _ff832bfc_find_pkg(ed):
    """Checkpoint 1: find ANY installed package whose manifest declares UCropActivity (field APK or lab flavor)."""
    out = ed.dev.sh(f'dumpsys package | grep -E "^ +[0-9a-f]+ [a-zA-Z0-9_.]+/{_FF832BFC_ACT}"') or ''
    for line in out.splitlines():
        cmp = line.strip().split()[-1]
        if '/' in cmp:
            return cmp.split('/')[0]
    raise UIError('no installed package declares com.yalantis.ucrop.UCropActivity: install field APK 1.25.1 '
                  '(800054867) or a lab build from 8856c31a with <activity ...UCropActivity exported=true/>')


def _ff832bfc_seed_image(ed):
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift')
    ed.dev.sh(f'screencap -p {_FF832BFC_IMG}; am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
              f'-d file://{_FF832BFC_IMG} >/dev/null 2>&1')
    ed.idle(2)


def _ff832bfc_start(ed, pkg, src_uri, extra=''):
    """Checkpoints 2-4: explicit START, bottom controls shown -> setupViews -> setupAspectRatioWidget:459 cast."""
    ed.step(f'START {pkg}/{_FF832BFC_ACT} (bottom controls shown)')
    ed.dev.marker('ff832bfc START UCropActivity')
    out = ed.dev.sh(f'am start -W -n {pkg}/{_FF832BFC_ACT} --eu myzesty.InputUri {src_uri} '
                    f'--eu myzesty.OutputUri file:///data/user/0/{pkg}/cache/ns_ff832bfc_out.png {extra}') or ''
    if 'does not exist' in out or 'Permission Denial' in out or 'SecurityException' in out:
        raise UIError(f'UCropActivity launch refused: {out.strip()[-200:]}')
    ed.idle(5)                                      # the ClassCastException in onCreate kills the process here


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l3_1_a(ed, r):
    """OnePlus 8 Pro x3 (08:05:51/08:05:55 retry pair): app backgrounded under low memory, crop screen started, retried 4 s later."""
    pkg = _ff832bfc_find_pkg(ed)
    _ff832bfc_seed_image(ed)
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh(f'am send-trim-memory {pkg} RUNNING_LOW')
    ed.idle(r.uniform(3, 6))
    _ff832bfc_start(ed, pkg, f'file://{_FF832BFC_IMG}')
    ed.idle(4)                                      # field retry gap
    _ff832bfc_start(ed, pkg, f'file://{_FF832BFC_IMG}')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l3_1_b(ed, r):
    """HUAWEI HRY-LX1T x4 (single launches hours apart): crop screen launched after config changes (dark mode + landscape), HideBottomControls false."""
    pkg = _ff832bfc_find_pkg(ed)
    _ff832bfc_seed_image(ed)
    ed.dev.dark_mode(True)
    ed.dev.rotate(True)
    ed.idle(3)
    _ff832bfc_start(ed, pkg, f'file://{_FF832BFC_IMG}', extra='--ez myzesty.HideBottomControls false')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l3_1_c(ed, r):
    """All 7 instances (0 logs, crash right at launch): offline + cleared cache, crop screen gets a MediaStore content:// image like a gallery pick."""
    pkg = _ff832bfc_find_pkg(ed)
    _ff832bfc_seed_image(ed)
    q = ed.dev.sh('content query --uri content://media/external/images/media --projection _id '
                  '--where "_display_name=\'ns_ff832bfc.png\'"') or ''
    mid = q.split('_id=')[-1].split()[0].strip(',') if '_id=' in q else ''
    src = f'content://media/external/images/media/{mid}' if mid.isdigit() else f'file://{_FF832BFC_IMG}'
    ed.dev.clear_app_cache()
    ed.dev.network(False)
    ed.idle(2)
    _ff832bfc_start(ed, pkg, src)


# 2026-10-10 10:25 level 5 attempt 2
_FF832BFC_HOOK = 'debug.zesty.hook.ucrop_activity'
_FF832BFC_STUB = 'com.myzesty/com.myzesty.MainActivity'


def _ff832bfc_restart_with_hook(ed):
    """Arm the hook, then start a new process: App.onCreate installs it only when the property is on at start."""
    ed.dev.setprop(_FF832BFC_HOOK, '1')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    time.sleep(1)
    ed.mon.allow_death = False


def _ff832bfc_launch_ucrop(ed, extra=''):
    """Explicit-component start of the crop screen (stub instantiated as UCropActivity), default uCrop options."""
    ed.dev.sh('mkdir -p /sdcard/DCIM/NightShift; screencap -p /sdcard/DCIM/NightShift/ns_crop_in.png')
    ed.dev.marker('ff832bfc: START UCropActivity')
    ed.dev.sh(f'am start -n {_FF832BFC_STUB} --ez debug.zesty.ucrop_stub true '
              f'--eu myzesty.InputUri file:///sdcard/DCIM/NightShift/ns_crop_in.png '
              f'--eu myzesty.OutputUri file:///sdcard/DCIM/NightShift/ns_crop_out.jpg {extra}')
    ed.idle(6)                                       # onCreate -> setupAspectRatioWidget -> ClassCastException


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l5_2_a(ed, r):
    """HUAWEI HRY-LX1T x4 (Crashlytics ff832bfc): cold start straight into UCropActivity with default options -> CCE in setupAspectRatioWidget."""
    try:
        _ff832bfc_restart_with_hook(ed)
        _ff832bfc_launch_ucrop(ed)                   # process starts for the crop screen itself, no prior user action
        ed.settle(4)
    finally:
        ed.dev.setprop(_FF832BFC_HOOK, '0')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ff832bfc_l5_2_b(ed, r):
    """OnePlus 8 Pro x3 (Crashlytics ff832bfc): app already in the editor, in-app launch of UCropActivity with bottom controls shown -> CCE."""
    try:
        _ff832bfc_restart_with_hook(ed)
        ed.dev.launch()
        ed.idle(4)
        ed.open_draft()                              # warm app with the editor on top, like an in-app caller
        ed.idle(r.uniform(2, 4))
        _ff832bfc_launch_ucrop(ed, '--ez myzesty.HideBottomControls false')
        ed.settle(4)
    finally:
        ed.dev.setprop(_FF832BFC_HOOK, '0')
