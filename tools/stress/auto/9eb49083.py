# Night Shift auto repros for 9eb490831317f4944e7f1f9d3374fda0


# 2026-10-29 21:14 level 2 attempt 1
_9eb49083_TASK = 'com.myzesty/com.myzesty.task.presentation.activity.TaskActivity'
_9eb49083_PHOTO = r'com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'


def _9eb49083_to_eraser(ed, r, pick_first=True):
    """Field path up to the Eraser tap: TaskActivity -> (select photo, permission cancel) -> Try a sample image ->
    PhotoActivity BG remover -> Start editing -> Background tab -> Done -> Eraser (BgRemovalFragment branch)."""
    mark = ed.log_mark()
    ed.start_activity(_9eb49083_TASK)
    ed.require_log(r'TaskActivity', 20, since=mark, why='onboarding BG-remover task screen (TaskActivity) must open')
    ed.idle(r.uniform(1.5, 3))
    if pick_first:                                   # field: Select a photo -> media permission popup -> cancel
        ed.ui.tap('id:btn_select_photo', timeout=5)
        ed.idle(r.uniform(2, 3.5))
        ed.dev.key('KEYCODE_BACK')                   # cancel the popup / close the picker like the user did
        ed.idle(r.uniform(1.5, 2.5))
    ed.ui.tap('id:btn_try_sample', timeout=10)       # onboarding_task_try_sample_image
    ed.require_log(_9eb49083_PHOTO, 25, since=mark, why='sample image must open PhotoActivity in BG-remover task mode')
    ed.ui.wait('id:start_creating', timeout=60)      # AI BG remover ran (model load + inference ~7 s in the field)
    ed.idle(r.uniform(2.5, 4))
    ed.ui.tap('id:start_creating', timeout=10)       # onboarding_task_start_editing
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:bg_tab', timeout=10)               # ai_bg_remover_choose_background
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:save', timeout=10)                 # Done: onboarding_task_start_done / pe_removebg_complete
    ed.idle(r.uniform(3, 5))
    ed.ui.wait('id:eraser', timeout=15)
    ed.idle(r.uniform(4, 8))                         # field: ~20 s between Done and Eraser
    ed.ui.tap('id:eraser', timeout=10)               # ai_bg_remover_eraser: no USE_ERASER_FILTER on this branch
    ed.ui.wait('id:redo', timeout=10)                # showEraser() made header undo/redo visible


def _9eb49083_strokes(ed, r, n):
    w, h = ed._screen_size()
    for _ in range(n):
        y = int(h * r.uniform(0.35, 0.6))
        ed.dev.swipe(int(w * r.uniform(0.2, 0.4)), y, int(w * r.uniform(0.6, 0.8)), y + r.randint(-60, 60),
                     r.randint(300, 700))
        ed.idle(r.uniform(0.6, 1.5))


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_a(ed, r):
    """Crashlytics 9eb49083 (instance 1/1, OPPO CPH2127): onboarding sample image -> BG remover -> Eraser -> Redo straight away."""
    ed.open_fixture('9eb49083')
    _9eb49083_to_eraser(ed, r, pick_first=True)
    ed.idle(r.uniform(1.5, 3))
    for _ in range(3):                               # Redo -> Engine.GetIntValueFromFilter(ERASER_REDOABLE_STEPS_CNT)
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.8, 1.6))
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_b(ed, r):
    """Crashlytics 9eb49083 (instance 1/1): same field path, ~17 s in the eraser with strokes and Undo, then Redo."""
    ed.open_fixture('9eb49083')
    _9eb49083_to_eraser(ed, r, pick_first=True)
    _9eb49083_strokes(ed, r, r.randint(3, 5))        # field gap Eraser -> crash ~17 s
    ed.idle(r.uniform(3, 6))
    for _ in range(2):
        ed.ui.tap('id:undo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    for _ in range(3):
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_c(ed, r):
    """Crashlytics 9eb49083 (instance 1/1): straight to the sample image, Eraser toggled again (inversion) in the eraser, then Redo."""
    ed.open_fixture('9eb49083')
    _9eb49083_to_eraser(ed, r, pick_first=False)
    ed.idle(r.uniform(2, 4))
    ed.ui.tap('id:eraser', timeout=5)                # EraserFragment branch: ERASER_TOGGLE_INVERSION (redraw mode)
    ed.idle(r.uniform(1, 2))
    _9eb49083_strokes(ed, r, 2)
    ed.idle(r.uniform(4, 8))
    for _ in range(3):
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    ed.settle(8)


# 2026-10-29 21:33 level 2 attempt 2
_9eb49083_TASK = 'com.myzesty/com.myzesty.task.presentation.activity.TaskActivity'


def _9eb49083_to_bg_editor(ed, r, pick_first):
    """TaskActivity (opened directly, as RNEditorModule FIRST_OPEN_TASK does) -> [Select a photo, cancel popup] ->
    Try a sample image -> PhotoActivity runs the AI BG remover -> Start editing -> Background tab."""
    mark = ed.log_mark()
    ed.start_activity(_9eb49083_TASK, extras='', expect_crash=False)
    ed.require_log(r'onboarding_task_bg_remover_show', 20, since=mark, why='onboarding BG-remover task (TaskActivity) must open')
    ed.idle(r.uniform(1.5, 2.5))
    if pick_first:                                   # field: select photo -> media permission popup -> cancel
        ed.ui.tap('id:btn_select_photo', timeout=5)
        ed.idle(r.uniform(2.5, 3.5))
        ed.dev.key('KEYCODE_BACK')
        ed.idle(r.uniform(1.5, 2))
    ed.ui.tap('id:btn_try_sample', timeout=10)
    ed.require_log(r'onboarding_task_try_sample_image', 10, since=mark, why='Try a sample image tap')
    ed.require_log(r'process_image_done', 60, since=mark, why='AI BG remover must really run on the sample image')
    ed.ui.wait('id:start_creating', timeout=20)
    ed.idle(r.uniform(2.5, 3.5))
    ed.ui.tap('id:start_creating', timeout=10)       # onboarding_task_start_editing
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:bg_tab', timeout=10)               # ai_bg_remover_choose_background
    ed.require_log(r'ai_bg_remover_choose_background', 10, since=mark, why='Background tab in BgRemovalFragment')
    ed.idle(r.uniform(2, 3))
    return mark


def _9eb49083_eraser_then_redo(ed, r, mark, strokes):
    ed.ui.tap('id:eraser', timeout=15)               # BgRemovalFragment branch: no USE_ERASER_FILTER
    ed.require_log(r'ai_bg_remover_eraser', 10, since=mark, why='Eraser on the BG/Bokeh branch (photo.isRemoveBg)')
    ed.ui.wait('id:redo', timeout=10)
    w, h = ed._screen_size()
    t0 = time.time()
    for _ in range(strokes):
        y = int(h * r.uniform(0.35, 0.55))
        ed.dev.swipe(int(w * 0.3), y, int(w * 0.7), y + r.randint(-50, 50), r.randint(400, 700))
        ed.idle(r.uniform(1.5, 3))
    ed.idle(max(1.0, r.uniform(14, 18) - (time.time() - t0)))   # field: crash ~17 s after the Eraser tap
    for _ in range(3):                               # Redo -> Engine.GetIntValueFromFilter(ERASER_REDOABLE_STEPS_CNT)
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_2_a(ed, r):
    """Instance 1/1 (OPPO CPH2127) as logged: sample image -> BG remover -> Done -> ~20 s -> Eraser -> Redo."""
    mark = _9eb49083_to_bg_editor(ed, r, pick_first=True)
    ed.ui.tap('id:save', timeout=10)                 # Done: onboarding_task_start_done / pe_removebg_complete
    ed.require_log(r'pe_removebg_complete', 15, since=mark, why='Done completes the BG remove')
    ed.idle(r.uniform(15, 19))                       # field: 20.8 s Done -> Eraser
    _9eb49083_eraser_then_redo(ed, r, mark, strokes=0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_2_b(ed, r):
    """Instance 1/1, eraser variant: sample image -> BG remover -> Background tab -> Eraser (no Done) -> strokes -> Redo."""
    mark = _9eb49083_to_bg_editor(ed, r, pick_first=False)
    _9eb49083_eraser_then_redo(ed, r, mark, strokes=r.randint(2, 4))


# 2026-10-29 21:38 level 2 attempt 3
_9eb49083_TASK = 'com.myzesty/com.myzesty.task.presentation.activity.TaskActivity'


def _9eb49083_to_bg_editor(ed, r, pick_first=True):
    """TaskActivity -> [Select a photo, back] -> Try a sample image -> sample tile -> PhotoActivity BG remover runs ->
    Start editing -> Background tab. Returns the log mark."""
    mark = ed.log_mark()
    ed.start_activity(_9eb49083_TASK, extras='', expect_crash=False)
    ed.require_log(r'onboarding_task_bg_remover_show', 20, since=mark, why='onboarding BG-remover task (TaskActivity) must open')
    ed.idle(r.uniform(1.5, 2.5))
    if pick_first:                                   # field: Select a photo -> permission popup -> cancel
        if ed.ui.tap('id:btn_select_photo', timeout=5):
            ed.idle(r.uniform(2.5, 3.5))
            ed.dev.key('KEYCODE_BACK')
            ed.idle(r.uniform(1.5, 2))
    ed.ui.tap('id:btn_try_sample', timeout=10)       # only opens SampleSelectionFragment (grid)
    ed.require_log(r'onboarding_task_try_sample_image', 10, since=mark, why='Try a sample image tap')
    ed.ui.wait('id:rv_sample_images', timeout=15)
    ed.idle(r.uniform(1, 2))
    ed.ui.tap('id:ivSampleImage', timeout=10)        # tile -> openBgRemovalWithSampleImage -> PhotoActivity(TASK_BG_REMOVAL)
    ed.require_log(r'wm_create_activity.*PhotoActivity', 20, since=mark, why='sample tile must start PhotoActivity')
    ed.require_log(r'process_image_done', 60, since=mark, why='AI BG remover must really run on the sample image')
    ed.ui.wait('id:start_creating', timeout=20)
    ed.idle(r.uniform(2.5, 3.5))
    ed.ui.tap('id:start_creating', timeout=10)       # onboarding_task_start_editing
    ed.require_log(r'onboarding_task_start_editing', 10, since=mark, why='Start editing in task mode')
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:bg_tab', timeout=10)               # ai_bg_remover_choose_background
    ed.require_log(r'ai_bg_remover_choose_background', 10, since=mark, why='Background tab in BgRemovalFragment')
    ed.idle(r.uniform(2, 3))
    return mark


def _9eb49083_done(ed, r, mark):
    ed.ui.tap('id:save', timeout=10)                 # header Done: onboarding_task_start_done / pe_removebg_complete
    ed.require_log(r'onboarding_task_start_done', 15, since=mark, why='Done in the BG remover (task mode)')
    ed.idle(r.uniform(16, 20))                       # field: 20.8 s Done -> Eraser


def _9eb49083_eraser_redo(ed, r, mark, strokes=0, undo=0):
    ed.ui.tap('id:eraser', timeout=15)               # BgRemovalFragment branch: no USE_ERASER_FILTER, showEraser()
    ed.require_log(r'ai_bg_remover_eraser', 10, since=mark, why='Eraser on the BG branch (photo.isRemoveBg)')
    ed.ui.wait('id:redo', timeout=10)
    w, h = ed._screen_size()
    t0 = time.time()
    for _ in range(strokes):
        y = int(h * r.uniform(0.35, 0.55))
        ed.dev.swipe(int(w * 0.3), y, int(w * 0.7), y + r.randint(-50, 50), r.randint(400, 700))
        ed.idle(r.uniform(1.5, 3))
    for _ in range(undo):
        ed.ui.tap('id:undo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    ed.idle(max(1.0, r.uniform(14, 17) - (time.time() - t0)))   # field: crash ~17 s after the Eraser tap
    for _ in range(3):                               # header Redo -> Engine.GetIntValueFromFilter(ERASER_REDOABLE_STEPS_CNT)
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.8, 1.5))
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_a(ed, r):
    """Instance 1/1 (OPPO CPH2127) as logged: sample tile -> BG remover -> Done -> ~20 s -> Eraser -> ~17 s -> Redo."""
    mark = _9eb49083_to_bg_editor(ed, r, pick_first=True)
    _9eb49083_done(ed, r, mark)
    _9eb49083_eraser_redo(ed, r, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_b(ed, r):
    """Instance 1/1, with strokes: BG remover -> Done -> Eraser -> erase strokes + Undo -> Redo."""
    mark = _9eb49083_to_bg_editor(ed, r, pick_first=True)
    _9eb49083_done(ed, r, mark)
    _9eb49083_eraser_redo(ed, r, mark, strokes=r.randint(2, 4), undo=r.randint(1, 2))


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_c(ed, r):
    """Instance 1/1, no Done: sample tile -> BG remover -> Background tab -> Eraser -> Redo."""
    mark = _9eb49083_to_bg_editor(ed, r, pick_first=False)
    _9eb49083_eraser_redo(ed, r, mark, strokes=r.randint(0, 2))


# 2026-10-29 21:42 level 3 attempt 1
_9eb49083_TASK = 'com.myzesty/com.myzesty.task.presentation.activity.TaskActivity'


def _9eb49083_to_eraser(ed, r):
    """TaskActivity -> Try a sample image -> tile -> AI BG remover (log-gated, 60 s) -> Start editing -> Background
    -> Done -> ~20 s -> Eraser on the BgRemovalFragment branch (no USE_ERASER_FILTER)."""
    mark = ed.log_mark()
    ed.start_activity(_9eb49083_TASK, extras='', expect_crash=False)
    ed.require_log(r'onboarding_task_bg_remover_show', 20, since=mark, why='onboarding BG-remover task (TaskActivity)')
    ed.idle(r.uniform(1.5, 2.5))
    ed.ui.tap('id:btn_try_sample', timeout=10)
    ed.require_log(r'onboarding_task_try_sample_image', 10, since=mark, why='Try a sample image tap')
    ed.ui.wait('id:rv_sample_images', timeout=15)
    ed.idle(1)
    ed.ui.tap('id:ivSampleImage', timeout=10)        # -> PhotoActivity(TASK_BG_REMOVAL), 8-11 s on this phone
    ed.require_log(r'onboarding_task_complete', 60, since=mark, why='AI BG remover must really run on the sample image')
    ed.ui.wait('id:start_creating', timeout=20)
    ed.idle(r.uniform(2.5, 3.5))
    ed.ui.tap('id:start_creating', timeout=10)
    ed.require_log(r'onboarding_task_start_editing', 10, since=mark, why='Start editing (task mode)')
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:bg_tab', timeout=10)
    ed.require_log(r'ai_bg_remover_choose_background', 10, since=mark, why='Background tab in BgRemovalFragment')
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:save', timeout=10)                 # header Done
    ed.require_log(r'onboarding_task_start_done', 15, since=mark, why='Done completes the BG remove')
    ed.idle(r.uniform(16, 20))                       # field: 20.8 s Done -> Eraser
    ed.ui.tap('id:eraser', timeout=15)
    ed.require_log(r'ai_bg_remover_eraser', 10, since=mark, why='Eraser on the BG branch (photo.isRemoveBg)')
    if ed.wait_log(r'pe_removebg_earse', 1, since=mark):
        raise UIError('eraser took the non-AI branch (pe_removebg_earse), not the field path')
    ed.ui.wait('id:redo', timeout=10)
    return mark


def _9eb49083_redo(ed, r, n=3):
    for _ in range(n):                               # Redo -> Engine.GetIntValueFromFilter(ERASER_REDOABLE_STEPS_CNT)
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.6, 1.4))


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_a(ed, r):
    """Instance 1/1 (OPPO CPH2127, low-end): field path, slow CPU in the eraser, ~17 s idle, Redo with no strokes."""
    _9eb49083_to_eraser(ed, r)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        ed.idle(r.uniform(13, 17))                   # field: crash ~17 s after the Eraser tap
        _9eb49083_redo(ed, r)
        ed.settle(8)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_b(ed, r):
    """Instance 1/1: cold BG-remover cache, erase strokes + Undo, memory pressure, then Redo (~17 s after Eraser)."""
    ed.dev.clear_app_cache()
    _9eb49083_to_eraser(ed, r)
    w, h = ed._screen_size()
    for _ in range(r.randint(2, 4)):
        y = int(h * r.uniform(0.35, 0.55))
        ed.dev.swipe(int(w * 0.3), y, int(w * 0.7), y + r.randint(-50, 50), r.randint(400, 700))
        ed.idle(r.uniform(1.5, 2.5))
    ed.ui.tap('id:undo', timeout=5)
    ed.idle(r.uniform(3, 6))
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(2)
    _9eb49083_redo(ed, r)
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_c(ed, r):
    """Instance 1/1: in the eraser the app goes Home under critical memory pressure, comes back, then Redo."""
    _9eb49083_to_eraser(ed, r)
    ed.idle(r.uniform(3, 5))
    ed.mon.allow_death = True
    ed.dev.key('KEYCODE_HOME')
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
    ed.idle(r.uniform(6, 9))
    ed.dev.launch()                                  # brings the PhotoActivity task back (eraser still shown)
    ed.idle(3)
    ed.mon.allow_death = False
    if ed.dev.pid() == '':
        raise UIError('app was reclaimed in the background; field user stayed in a live app')
    ed.ui.wait('id:redo', timeout=10)
    _9eb49083_redo(ed, r)
    ed.settle(8)


# 2026-10-29 21:46 level 3 attempt 2
_9eb49083_TASK = 'com.myzesty/com.myzesty.task.presentation.activity.TaskActivity'
_9eb49083_PERMS = ('android.permission.READ_EXTERNAL_STORAGE', 'android.permission.WRITE_EXTERNAL_STORAGE')


def _9eb49083_to_eraser(ed, r):
    """Field state: no storage permission (user cancelled the media popup) -> sample BG remover -> Background tab ->
    Done -> checkStorageAndSave asks for storage (SDK < 33) -> Deny -> stays in BgRemovalFragment -> ~20 s -> Eraser."""
    ed.open_fixture('9eb49083')
    ed.mon.allow_death = True                        # pm revoke kills the running app
    for p in _9eb49083_PERMS:
        ed.dev.sh(f'pm revoke com.myzesty {p}')
    ed.idle(2)
    ed.dev.launch()
    ed.idle(6)
    ed.mon.allow_death = False
    mark = ed.log_mark()
    ed.start_activity(_9eb49083_TASK, extras='', expect_crash=False)
    ed.require_log(r'onboarding_task_bg_remover_show', 20, since=mark, why='onboarding BG-remover task (TaskActivity)')
    ed.idle(r.uniform(1.5, 2.5))
    if ed.ui.tap('id:btn_select_photo', timeout=5):  # field: media permission popup -> cancel
        ed.idle(r.uniform(2, 3))
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
    ed.ui.tap('id:btn_try_sample', timeout=10)
    ed.require_log(r'onboarding_task_try_sample_image', 10, since=mark, why='Try a sample image tap')
    ed.ui.wait('id:rv_sample_images', timeout=15)
    ed.idle(1)
    ed.ui.tap('id:ivSampleImage', timeout=10)
    ed.require_log(r'onboarding_task_complete', 60, since=mark, why='AI BG remover must really run on the sample image')
    ed.ui.wait('id:start_creating', timeout=20)
    ed.idle(r.uniform(2.5, 3.5))
    ed.ui.tap('id:start_creating', timeout=10)
    ed.require_log(r'onboarding_task_start_editing', 10, since=mark, why='Start editing (task mode)')
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:bg_tab', timeout=10)
    ed.require_log(r'ai_bg_remover_choose_background', 10, since=mark, why='Background tab in BgRemovalFragment')
    ed.idle(r.uniform(2, 3))
    ed.ui.tap('id:save', timeout=10)                 # Done -> pe_removebg_complete -> storage permission request
    ed.require_log(r'pe_removebg_complete', 15, since=mark, why='Done applies the BG remove (field pe_removebg_complete)')
    ed.require_log(r'GrantPermissionsActivity', 15, since=mark, why='Done must ask for storage (permission missing as in the field)')
    ed.idle(1.5)
    if not ed.ui.tap('id:permission_deny_button', timeout=6):
        ed.ui.tap('textc:deny', timeout=4)
    ed.idle(2)
    if ed.wait_log(r'ai_bg_remover_complete|export_1', 1, since=mark):
        raise UIError('Done saved and closed PhotoActivity; field user stayed in the BG remover')
    ed.idle(r.uniform(15, 18))                       # field: 20.8 s Done -> Eraser
    ed.ui.tap('id:eraser', timeout=15)               # BgRemovalFragment branch: no USE_ERASER_FILTER
    ed.require_log(r'ai_bg_remover_eraser', 10, since=mark, why='Eraser on the BG branch (photo.isRemoveBg)')
    ed.ui.wait('id:redo', timeout=10)
    return mark


def _9eb49083_redo(ed, r, n=3):
    for _ in range(n):                               # Redo -> Engine.GetIntValueFromFilter(ERASER_REDOABLE_STEPS_CNT)
        ed.ui.tap('id:redo', timeout=5)
        ed.idle(r.uniform(0.6, 1.4))
    ed.settle(8)


def _9eb49083_regrant(ed):
    for p in _9eb49083_PERMS:
        ed.dev.sh(f'pm grant com.myzesty {p}')


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_a(ed, r):
    """Instance 1/1 (OPPO CPH2127, Android 12) as logged: storage denied at Done, Eraser ~20 s later, Redo ~17 s on."""
    try:
        _9eb49083_to_eraser(ed, r)
        ed.idle(r.uniform(13, 16))
        _9eb49083_redo(ed, r)
    finally:
        _9eb49083_regrant(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_b(ed, r):
    """Instance 1/1 on a low-end phone: same path, eraser strokes + Undo, slow CPU and memory pressure, then Redo."""
    try:
        _9eb49083_to_eraser(ed, r)
        w, h = ed._screen_size()
        for _ in range(r.randint(2, 3)):
            y = int(h * r.uniform(0.35, 0.55))
            ed.dev.swipe(int(w * 0.3), y, int(w * 0.7), y + r.randint(-50, 50), r.randint(400, 700))
            ed.idle(r.uniform(1.5, 2.5))
        ed.ui.tap('id:undo', timeout=5)
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(6, 9))
        _9eb49083_redo(ed, r)
    finally:
        ed.dev.slow_phone(0)
        _9eb49083_regrant(ed)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_c(ed, r):
    """Instance 1/1: same path, Redo tapped right after Eraser (no strokes), then again after ~15 s idle."""
    try:
        _9eb49083_to_eraser(ed, r)
        ed.idle(r.uniform(0.8, 1.5))
        _9eb49083_redo(ed, r, n=2)
        ed.idle(r.uniform(10, 14))
        _9eb49083_redo(ed, r, n=3)
    finally:
        _9eb49083_regrant(ed)
