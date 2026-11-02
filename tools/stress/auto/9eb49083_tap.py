# Night Shift tap repros for 9eb490831317f4944e7f1f9d3374fda0 (from the engine repro + full field log)


# 2026-10-29 20:52 attempt 1
"""Night Shift tapflow 9eb49083: SIGABRT in libImageFilter.so JNI_GetIntValueFromFilter (interface.cpp:157)."""
import time

PKG = 'com.myzesty'


def _fa_on(ed):
    """Firebase Analytics logs each event to logcat ('Logging event: ... name=X'): our only checkpoint here."""
    ed.dev.setprop('log.tag.FA', 'VERBOSE')
    ed.dev.setprop('log.tag.FA-SVC', 'VERBOSE')
    ed.dev.setprop('debug.firebase.analytics.app', PKG)


def _ev(name):
    return rf'Logging event.*name={name}\b'


def _tap(ed, sel, event, why, timeout=20):
    ed.step(why)
    ed.ui.tap(sel, timeout=timeout)
    ed.require_log(_ev(event), timeout=timeout, why=why)


def _onboarding_to_eraser(ed):
    """First run -> onboarding -> BG-remover task -> sample image -> BG removed -> Done -> Eraser (field order)."""
    ed.dev.launch()
    ed.require_log(_ev('app_opened_first_time'), timeout=40, why='first run after install')
    _tap(ed, ('textc:continue',), 'onboarding_continue', 'onboarding continue')
    _tap(ed, ('textc:skip',), 'onboarding_1_skip', 'onboarding 1 skip')
    ed.require_log(_ev('onboarding_task_bg_remover_show'), timeout=20, why='BG-remover task shown')
    _tap(ed, ('textc:select photo', 'textc:select'), 'onboarding_task_select_photo', 'task: select photo')
    _tap(ed, ('textc:cancel', 'textc:not now'), 'permission_pop_cancel', 'cancel media permission popup')
    _tap(ed, ('textc:sample',), 'onboarding_task_try_sample_image', 'try sample image')
    ed.require_log(_ev('process_image_done_complete'), timeout=60, why='AI BG remover finished')
    _tap(ed, ('textc:start editing',), 'onboarding_task_start_editing', 'start editing')
    _tap(ed, ('textc:background',), 'ai_bg_remover_choose_background', 'choose background')
    _tap(ed, ('textc:done',), 'onboarding_task_start_done', 'task done')
    ed.idle(2)
    _tap(ed, 'id:eraser', 'ai_bg_remover_eraser', 'Eraser in BG remover (last field event)')
    ed.idle(1.5)


def _strokes(ed, r, n):
    """Finger strokes on the photo while EraserFragment is open (unlogged in the field)."""
    s = ed.screen()
    cx, cy = s.find('id:photoView').center if s is not None and s.has('id:photoView') else (540, 1000)
    for _ in range(n):
        ed.dev.swipe(cx - r.randint(80, 250), cy + r.randint(-200, 200),
                     cx + r.randint(80, 250), cy + r.randint(-200, 200), r.randint(200, 500))
        ed.idle(r.uniform(0.3, 0.8))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_1_a(ed, r):
    """FULL: first run, onboarding BG-remover on the sample image, Eraser, then Redo in the eraser -> GetIntValueFromFilter."""
    ed.dev.sh(f'pm clear {PKG}', 30)              # the user's state: first launch after install
    _fa_on(ed)
    _onboarding_to_eraser(ed)
    ed.step('Redo inside the BG-remover eraser (only caller of GetIntValueFromFilter)')
    for _ in range(3):
        ed.ui.tap('id:redo', timeout=10)
        ed.idle(1.0)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_1_b(ed, r):
    """HYBRID: first-run state made by the lab, then the real onboarding taps, eraser strokes, Undo then Redo (trigger)."""
    ed.dev.force_stop()                           # HYBRID
    ed.dev.sh(f'pm clear {PKG}', 30)              # HYBRID: fresh-install state without a reinstall
    ed.dev.sh(f'pm grant {PKG} android.permission.POST_NOTIFICATIONS', 10)   # HYBRID: no notification prompt
    _fa_on(ed)
    _onboarding_to_eraser(ed)
    ed.step('erase a few strokes so the eraser has undo/redo history')
    _strokes(ed, r, r.randint(2, 4))
    ed.step('Undo then Redo inside the eraser')
    for _ in range(2):
        ed.ui.tap('id:undo', timeout=10)
        ed.idle(0.6)
    for _ in range(4):
        ed.ui.tap('id:redo', timeout=10)          # TRIGGER: Redo listener -> Engine.GetIntValueFromFilter
        ed.idle(0.6)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_1_c(ed, r):
    """FULL: same user path on a slowed phone (low-end OPPO CPH2127), field ~17 s gap in the eraser, then an Undo/Redo storm."""
    ed.dev.sh(f'pm clear {PKG}', 30)
    _fa_on(ed)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _onboarding_to_eraser(ed)
        ed.step('stay in the eraser like the field user (~17 s), drawing now and then')
        t_end = time.time() + r.uniform(14, 20)
        while time.time() < t_end:
            _strokes(ed, r, 1)
            ed.idle(r.uniform(1.0, 3.0))
        ed.step('Undo/Redo storm in the BG-remover eraser')
        for _ in range(r.randint(8, 14)):
            ed.ui.tap('id:redo' if r.random() < 0.65 else 'id:undo', timeout=10)
            ed.idle(r.uniform(0.05, 0.4))
        ed.settle(6)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-29 20:57 attempt 2
"""Night Shift tapflow 9eb49083: SIGABRT in libImageFilter.so JNI_GetIntValueFromFilter (interface.cpp:157)."""
import time

PKG = 'com.myzesty'


def _ev(name):
    # AnalyticsManager.kt:69 logs 'Event: <name>'; ProductionInternal builds prefix 'test_' (buildEventName)
    return rf'AnalyticsManager: Event: (?:test_)?{name}\b'


def _tap(ed, sel, event, why, timeout=20):
    ed.step(why)
    ed.ui.tap(sel, timeout=timeout)
    ed.require_log(_ev(event), timeout=timeout, why=why)


def _onboarding_to_eraser(ed, slow=1.0):
    """First run -> onboarding -> BG-remover task -> sample image -> BG removed -> Done -> Eraser (field order)."""
    ed.dev.launch()
    ed.require_log(_ev('app_opened_first_time'), timeout=int(40 * slow), why='first run after install')
    _tap(ed, ('textc:continue', 'textc:next', 'desc:continue-button-1'), 'onboarding_continue', 'onboarding continue')
    _tap(ed, ('textc:skip', 'desc:skip-intro-button'), 'onboarding_1_skip', 'onboarding 1 skip')
    ed.require_log(_ev('onboarding_task_bg_remover_show'), timeout=int(20 * slow), why='BG-remover task shown')
    _tap(ed, ('textc:select a photo',), 'onboarding_task_select_photo', 'task: Select a photo')
    _tap(ed, ('textc:cancel', 'textc:not now', 'textc:later', 'textc:deny'), 'permission_pop_cancel',
         'cancel media permission popup')
    mark = ed.log_mark()
    _tap(ed, ('textc:try a sample image',), 'onboarding_task_try_sample_image', 'Try a sample image')
    if not ed.wait_log(_ev('ai_bg_remover_start'), int(10 * slow), since=mark):
        ed.step('Sample images screen: pick the first sample')   # sample_selection_title screen
        ed.screen()
        ed.dev.tap(180, 640)
    ed.require_log(_ev('ai_bg_remover_start'), timeout=int(30 * slow), since=mark, why='PhotoActivity BG remover')
    ed.require_log(_ev('process_image_done_complete'), timeout=int(90 * slow), since=mark, why='AI BG remover done')
    ed.idle(2)
    _tap(ed, ('textc:start editing', 'textc:start creating', 'textc:edit'), 'onboarding_task_start_editing',
         'start editing')
    _tap(ed, ('textc:background',), 'ai_bg_remover_choose_background', 'choose background')
    _tap(ed, ('textc:done',), 'onboarding_task_start_done', 'task Done')
    ed.idle(2)
    _tap(ed, 'id:eraser', 'ai_bg_remover_eraser', 'Eraser in BG remover (last field event)')
    ed.idle(1.5)


def _redo(ed, why):
    mark = ed.log_mark()
    ed.ui.tap('id:redo', timeout=10)               # PhotoActivity.kt:375 -> Engine.GetIntValueFromFilter
    ed.wait_log(r'libImageFilter|GetIntValueFromFilter|Fatal signal', 2, since=mark)   # Redo logs nothing itself
    ed.step(why)


def _strokes(ed, r, n):
    """Finger strokes on the photo while EraserFragment is open (unlogged in the field)."""
    for _ in range(n):
        ed.dev.swipe(360 - r.randint(80, 250), 700 + r.randint(-200, 200),
                     360 + r.randint(80, 250), 700 + r.randint(-200, 200), r.randint(200, 500))
        ed.idle(r.uniform(0.3, 0.8))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_2_a(ed, r):
    """FULL: first run, onboarding BG-remover on the sample image, Eraser, then Redo in the eraser -> GetIntValueFromFilter."""
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG}', 30)               # the user's state: first launch after install
    _onboarding_to_eraser(ed)
    for k in range(3):
        _redo(ed, f'Redo {k + 1} in BG-remover eraser')
        ed.idle(1.0)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_2_b(ed, r):
    """HYBRID: first-run state made by the lab, real onboarding taps, eraser strokes, Undo then Redo (trigger)."""
    ed.dev.force_stop()                            # HYBRID
    ed.dev.sh(f'pm clear {PKG}', 30)               # HYBRID: fresh-install state without a reinstall
    _onboarding_to_eraser(ed)
    ed.step('erase a few strokes so the eraser has history')
    _strokes(ed, r, r.randint(2, 4))
    for _ in range(2):
        ed.ui.tap('id:undo', timeout=10)
        ed.idle(0.6)
    for k in range(4):
        _redo(ed, f'Redo {k + 1} after undo (TRIGGER)')
        ed.idle(0.6)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_2_c(ed, r):
    """FULL: same path on a slowed phone (low-end OPPO CPH2127), ~17 s in the eraser like the field, then Undo/Redo storm."""
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG}', 30)
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _onboarding_to_eraser(ed, slow=2.0)
        ed.step('stay in the eraser ~17 s, drawing now and then')
        t_end = time.time() + r.uniform(14, 20)
        while time.time() < t_end:
            _strokes(ed, r, 1)
            ed.idle(r.uniform(1.0, 3.0))
        for k in range(r.randint(8, 14)):
            if r.random() < 0.65:
                _redo(ed, f'storm Redo {k}')
            else:
                ed.ui.tap('id:undo', timeout=10)
            ed.idle(r.uniform(0.05, 0.4))
        ed.settle(6)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-29 21:03 attempt 3
"""Night Shift tapflow 9eb49083: SIGABRT in libImageFilter.so JNI_GetIntValueFromFilter (interface.cpp:157)."""
import time

PKG = 'com.myzesty'


def _ev(name):
    # AnalyticsManager logs 'Event: <name> | type: ...'; this build prefixes 'test_' (seen in attempt 1)
    return rf'AnalyticsManager: Event: (?:test_)?{name}\b'


def _tap(ed, sel, event, why, timeout=20):
    ed.step(why)
    mark = ed.log_mark()
    ed.ui.tap(sel, timeout=timeout)
    ed.require_log(_ev(event), timeout=timeout, since=mark, why=why)


def _first_run_to_eraser(ed, slow=1.0):
    """pm clear -> onboarding -> BG-remover task -> permission sheet closed -> sample -> BG removed -> Done -> Eraser."""
    w = lambda s: int(s * slow)
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG}', 30)                 # the field user: first run after install, no media access
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Displayed com\.myzesty/\.MainActivity', timeout=w(40), since=mark, why='first launch')
    ed.step('onboarding Continue')                   # RN onboarding: its events skip AnalyticsManager
    ed.ui.tap(('desc:continue-button-1', 'textc:continue'), timeout=w(30))
    ed.ui.wait('desc:skip-intro-button', timeout=w(20))
    ed.step('onboarding Skip')
    mark = ed.log_mark()
    ed.ui.tap(('desc:skip-intro-button', 'textc:skip'), timeout=w(20))
    ed.require_log(r'wm_on_create_called: \[\d+,com\.myzesty\.task\.presentation\.activity\.TaskActivity',
                   timeout=w(30), since=mark, why='TaskActivity after onboarding skip')
    ed.require_log(_ev('onboarding_task_bg_remover_show'), timeout=w(20), since=mark, why='BG-remover task shown')
    _tap(ed, 'id:btn_select_photo', 'permission_popup', 'Select a photo -> media permission sheet', w(20))
    _tap(ed, 'id:cross_btn', 'permission_pop_cancel', 'close permission sheet (field fact)', w(20))
    mark = ed.log_mark()
    _tap(ed, 'id:btn_try_sample', 'onboarding_task_try_sample_image', 'Try a sample image', w(20))
    if not ed.wait_log(_ev('ai_bg_remover_start'), w(8), since=mark):
        ed.step('Sample images screen: first sample')
        ed.ui.wait('textc:sample images', timeout=w(10))
        ed.dev.tap(180, 640)
    ed.require_log(_ev('ai_bg_remover_start'), timeout=w(30), since=mark, why='PhotoActivity BG remover opened')
    ed.require_log(_ev('onboarding_task_complete'), timeout=w(120), since=mark, why='AI BG removal done')
    ed.idle(2)
    _tap(ed, ('textc:start editing', 'textc:start creating', 'textc:edit'), 'onboarding_task_start_editing',
         'start editing', w(20))
    _tap(ed, ('textc:background',), 'ai_bg_remover_choose_background', 'choose background', w(20))
    _tap(ed, ('textc:done',), 'onboarding_task_start_done', 'task Done', w(20))
    ed.idle(2)
    _tap(ed, 'id:eraser', 'ai_bg_remover_eraser', 'Eraser in BG remover (last field event)', w(20))
    ed.idle(1.5)


def _redo(ed, why):
    ed.step(why)
    mark = ed.log_mark()
    ed.ui.tap('id:redo', timeout=10)                 # PhotoActivity.kt:375 -> Engine.GetIntValueFromFilter
    ed.wait_log(r'libImageFilter|GetIntValueFromFilter|Fatal signal', 2, since=mark)  # Redo logs nothing itself


def _strokes(ed, r, n):
    for _ in range(n):                               # unlogged eraser strokes on the photo
        ed.dev.swipe(360 - r.randint(80, 250), 700 + r.randint(-200, 200),
                     360 + r.randint(80, 250), 700 + r.randint(-200, 200), r.randint(200, 500))
        ed.idle(r.uniform(0.3, 0.8))


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_3_a(ed, r):
    """FULL: first run, onboarding BG-remover on the sample image, Eraser, then Redo in the eraser -> GetIntValueFromFilter."""
    _first_run_to_eraser(ed)
    for k in range(3):
        _redo(ed, f'Redo {k + 1} in BG-remover eraser (TRIGGER)')
        ed.idle(1.0)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_3_b(ed, r):
    """HYBRID: first-run state by pm clear (lab), real onboarding taps, eraser strokes, Undo then Redo (trigger)."""
    _first_run_to_eraser(ed)                         # HYBRID: pm clear stands in for a fresh install
    ed.step('erase a few strokes so the eraser has history')
    _strokes(ed, r, r.randint(2, 4))
    for _ in range(2):
        ed.ui.tap('id:undo', timeout=10)
        ed.idle(0.6)
    for k in range(4):
        _redo(ed, f'Redo {k + 1} after undo (TRIGGER)')
        ed.idle(0.6)
    ed.settle(5)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_9eb49083_3_c(ed, r):
    """FULL: same path on a slowed phone (low-end OPPO CPH2127), ~17 s in the eraser like the field, then Undo/Redo storm."""
    ed.dev.slow_phone(r.randint(25, 40))
    try:
        _first_run_to_eraser(ed, slow=2.0)
        ed.step('stay in the eraser ~17 s, drawing now and then')
        t_end = time.time() + r.uniform(14, 20)
        while time.time() < t_end:
            _strokes(ed, r, 1)
            ed.idle(r.uniform(1.0, 3.0))
        for k in range(r.randint(8, 14)):
            if r.random() < 0.65:
                _redo(ed, f'storm Redo {k} (TRIGGER)')
            else:
                ed.ui.tap('id:undo', timeout=10)
            ed.idle(r.uniform(0.05, 0.4))
        ed.settle(6)
    finally:
        ed.dev.slow_phone(0)
