# Night Shift auto repros for a34175e57d4cd343ec43f9d330ccada0


# 2026-11-01 04:32 level 2 attempt 1
_A34175E5_PAYWALL = r'pro_screen_show_t\d'          # selectTab(0): sheet view built, Continue live, billing still pending


def _a34175e5_tap_id(ed, sel):
    s = ed.screen()
    if s is not None and s.has((sel,)):
        ed.dev.tap(*s.find((sel,)).center)
        return True
    return False


def _a34175e5_home(ed):
    """Close any launch paywall / onboarding until the home screen (Premium pill) shows."""
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('id:home_premium_pill',)) and not s.has(('id:btn_continue',)):
            return
        if not (_a34175e5_tap_id(ed, 'id:btn_close') or _a34175e5_tap_id(ed, 'id:tv_skip')
                or _a34175e5_tap_id(ed, 'textc:skip')):
            ed.dev.key('KEYCODE_BACK')
        time.sleep(1.5)
    raise UIError('home screen (home_premium_pill) not reached')


def _a34175e5_continue_xy(ed):
    """Open the paywall once from the Premium pill, note where CONTINUE sits, close it."""
    _a34175e5_home(ed)
    ed.ui.tap('id:home_premium_pill', timeout=10)
    for _ in range(15):
        s = ed.screen()
        if s is not None and s.has(('id:btn_continue',)):
            xy = s.find(('id:btn_continue',)).center
            _a34175e5_tap_id(ed, 'id:btn_close')
            time.sleep(2)
            return xy
        time.sleep(0.7)
    raise UIError('paywall CONTINUE (btn_continue) never showed')


def _a34175e5_burst(ed, r, xy, seconds=2.0):
    """The field user still tapping as the sheet comes up: CONTINUE again and again at finger speed."""
    end = time.time() + seconds
    while time.time() < end:
        ed.dev.tap(*xy)
        time.sleep(r.uniform(0.06, 0.14))
    ed.idle(1.5)
    for _ in range(2):                               # no crash: close the Play purchase sheet / paywall
        ed.dev.key('KEYCODE_BACK')
        time.sleep(1)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_1_a(ed, r):
    """Instance phone 2 (1.25.1, breadcrumbs): fresh install -> skip onboarding + bg-remover task -> auto paywall -> CONTINUE at once."""
    xy = _a34175e5_continue_xy(ed)
    ed.step('fresh install state: clear app data, first launch')
    ed.mon.allow_death = True
    ed.dev.sh('pm clear com.myzesty')
    time.sleep(2)
    m0 = ed.log_mark()
    ed.dev.launch()
    time.sleep(4)
    ed.mon.allow_death = False
    ed.require_log(r'app_opened_first_time', 20, since=m0, why='field: first session after install')
    task_done, shots, since = False, 0, m0
    for _ in range(40):
        m = ed.log_mark()
        if ed.wait_log(_A34175E5_PAYWALL, 1.5, since=since):
            ed.step('paywall up: tap CONTINUE right away')
            _a34175e5_burst(ed, r, xy)
            shots += 1
            since = ed.log_mark()
            if task_done:
                break                                # the field moment: the paywall right after the task
            continue
        since = m
        if _a34175e5_tap_id(ed, 'id:tv_skip'):       # TaskActivity bg-remover task, skipped as in the field
            ed.require_log(r'onboarding_task_bg_remover_skip', 10, since=m, why='field: bg-remover task skipped')
            task_done = True
            since = m
        elif _a34175e5_tap_id(ed, 'textc:skip'):     # AppIntro page 1 -> onboarding_1_skip
            time.sleep(r.uniform(1.0, 2.0))
    if not task_done:
        raise UIError('bg-remover task (TaskActivity tv_skip) never showed after the first launch')
    ed.require_log(r'onboarding_task_bg_remover_show', 2, since=m0, why='field: onboarding led into the bg-remover task')
    if shots == 0:
        raise UIError('no paywall (pro_screen_show_t*) opened on MainActivity after the task')


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_1_b(ed, r):
    """Instance phone 1 (1.25.2, no breadcrumbs) + any user who opens the paywall and taps CONTINUE before the plans show (Premium pill)."""
    xy = _a34175e5_continue_xy(ed)
    for k in range(5):
        ed.step(f'Premium pill -> CONTINUE right away ({k + 1}/5)')
        _a34175e5_home(ed)
        m = ed.log_mark()
        ed.ui.tap('id:home_premium_pill', timeout=10)
        ed.require_log(_A34175E5_PAYWALL, 10, since=m, why='PremiumScreenBottomSheet tab 0 shown')
        _a34175e5_burst(ed, r, xy)
        ed.idle(r.uniform(1, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_1_c(ed, r):
    """Instances phone 1+2 auto-open: launch-landing paywall on MainActivity (pro_screen_show_dayN_openM) on a cold open, CONTINUE at once."""
    xy = _a34175e5_continue_xy(ed)
    for k in range(4):
        ed.step(f'cold open -> landing paywall -> CONTINUE right away ({k + 1}/4)')
        ed.mon.allow_death = True
        ed.dev.force_stop()
        m = ed.log_mark()
        ed.dev.launch()
        time.sleep(2)
        ed.mon.allow_death = False
        ed.require_log(r'pro_screen_show_day\d+_open\d+', 25, since=m, why='field: paywall auto-opened on MainActivity')
        ed.require_log(_A34175E5_PAYWALL, 10, since=m, why='PremiumScreenBottomSheet tab 0 shown')
        _a34175e5_burst(ed, r, xy)
        ed.idle(r.uniform(2, 4))


# 2026-11-01 04:44 level 2 attempt 2
_A34175E5_SHOW_T = r'pro_screen_show_t\d'            # selectTab(0): sheet view built, Continue live, billing not answered yet
_A34175E5_PLACEMENT = r'pro_screen_show_day\d+_open\d+'


def _a34175e5_tap_id(ed, sel):
    s = ed.screen()
    if s is not None and s.has((sel,)):
        ed.dev.tap(*s.find((sel,)).center)
        return True
    return False


def _a34175e5_front(ed):
    return 'com.myzesty' in ed.dev.sh('dumpsys window | grep -m1 mCurrentFocus')


def _a34175e5_setup_logs(ed):
    ed.dev.setprop('debug.firebase.analytics.app', 'com.myzesty')   # analytics events visible in logcat
    ed.dev.setprop('log.tag.FA', 'VERBOSE')
    ed.dev.setprop('log.tag.FA-SVC', 'VERBOSE')


def _a34175e5_cold(ed):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    m = ed.log_mark()
    ed.dev.launch()
    time.sleep(1)
    ed.mon.allow_death = False
    return m


def _a34175e5_close(ed):
    for _ in range(5):                               # never BACK blindly: on home it leaves the app
        if _a34175e5_tap_id(ed, 'id:btn_close'):
            time.sleep(1.5)
            return True
        time.sleep(0.6)
    return False


def _a34175e5_continue_xy(ed):
    """The paywall is up: note where CONTINUE sits, then close it with its Cancel button."""
    for _ in range(10):
        s = ed.screen()
        if s is not None and s.has(('id:btn_continue',)):
            xy = s.find(('id:btn_continue',)).center
            _a34175e5_close(ed)
            return xy
        time.sleep(0.5)
    raise UIError('paywall CONTINUE (btn_continue) not on screen')


def _a34175e5_burst(ed, r, xy, seconds=3.0):
    """The field user tapping CONTINUE again and again (finger speed) while the plans are still loading."""
    ed.step('paywall up: CONTINUE tapped right away, repeatedly')
    end = time.time() + seconds
    while time.time() < end:
        ed.dev.tap(*xy)
        time.sleep(r.uniform(0.07, 0.15))
    ed.idle(1.5)
    if not _a34175e5_front(ed):                       # no crash: the Play purchase sheet opened; cancel it
        ed.dev.key('KEYCODE_BACK')
        time.sleep(1.5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_2_a(ed, r):
    """Instance phone 2 (1.25.1, breadcrumbs): pm clear -> first run -> skip onboarding + bg-remover task -> auto paywall -> CONTINUE."""
    _a34175e5_setup_logs(ed)
    m = _a34175e5_cold(ed)
    ed.require_log(_A34175E5_SHOW_T, 30, since=m, why='launch paywall, to learn where CONTINUE sits')
    xy = _a34175e5_continue_xy(ed)
    ed.step('fresh install state: clear app data, first launch')
    ed.mon.allow_death = True
    ed.dev.sh('pm clear com.myzesty')
    time.sleep(2)
    ed.dev.sh('pm grant com.myzesty android.permission.POST_NOTIFICATIONS 2>/dev/null')
    m0 = ed.log_mark()
    ed.dev.launch()
    time.sleep(3)
    ed.mon.allow_death = False
    ed.require_log(r'app_opened_first_time', 30, since=m0, why='field: first session after install')
    since, end = m0, time.time() + 150
    while time.time() < end:
        if ed.wait_log(_A34175E5_SHOW_T, 0.5, since=since):   # a paywall before the task: the user closed it
            since = ed.log_mark()
            _a34175e5_close(ed)
            continue
        if not _a34175e5_front(ed):
            ed.dev.launch()
            time.sleep(3)
            continue
        m = ed.log_mark()
        if _a34175e5_tap_id(ed, 'id:tv_skip'):       # TaskActivity bg-remover task skipped, as in the field
            for k in range(4):                       # the field paywall: right after the task, or on the next open
                if ed.wait_log(_A34175E5_SHOW_T, 20, since=m):
                    _a34175e5_burst(ed, r, xy)
                    ed.require_log(r'onboarding_task_bg_remover_skip', 2, since=m0, why='field: bg-remover task skipped')
                    ed.require_log(_A34175E5_PLACEMENT, 2, since=m0, why='field: dayN/openM auto paywall')
                    return
                ed.step(f'no paywall yet: home and reopen ({k + 1})')
                ed.dev.key('KEYCODE_HOME')
                time.sleep(2)
                m = ed.log_mark()
                ed.dev.launch()
            raise UIError('no auto paywall on MainActivity after the bg-remover task')
        if not _a34175e5_tap_id(ed, 'id:btn_close'):
            _a34175e5_tap_id(ed, 'textc:skip')       # onboarding page -> onboarding_1_skip
        time.sleep(r.uniform(1.0, 2.0))
    raise UIError('bg-remover task (TaskActivity tv_skip) never showed after the first launch')


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_2_b(ed, r):
    """Instances phone 1+2: the dayN/openM paywall auto-opens on a cold MainActivity; CONTINUE tapped as it comes up (6 opens)."""
    _a34175e5_setup_logs(ed)
    m = _a34175e5_cold(ed)
    ed.require_log(_A34175E5_SHOW_T, 30, since=m, why='launch paywall, to learn where CONTINUE sits')
    xy = _a34175e5_continue_xy(ed)
    for k in range(6):
        ed.step(f'cold open -> auto paywall -> CONTINUE ({k + 1}/6)')
        m = _a34175e5_cold(ed)
        ed.require_log(_A34175E5_SHOW_T, 30, since=m, why='field: paywall view built on MainActivity, Continue live')
        _a34175e5_burst(ed, r, xy)
        ed.require_log(_A34175E5_PLACEMENT, 2, since=m, why='field: auto-opened dayN/openM paywall')
        ed.idle(r.uniform(1, 2))


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_2_c(ed, r):
    """Instance phone 1 (1.25.2, no breadcrumbs): fresh process, close the launch paywall, open it from the Premium pill, CONTINUE at once (5x)."""
    _a34175e5_setup_logs(ed)
    xy = None
    for k in range(5):
        ed.step(f'fresh process -> Premium pill -> CONTINUE ({k + 1}/5)')
        m = _a34175e5_cold(ed)
        ed.require_log(_A34175E5_SHOW_T, 30, since=m, why='launch paywall on MainActivity')
        if xy is None:
            xy = _a34175e5_continue_xy(ed)
        elif not _a34175e5_close(ed):
            raise UIError('launch paywall Cancel (btn_close) not found')
        ed.idle(r.uniform(0.5, 1.5))
        m = ed.log_mark()
        ed.ui.tap('id:home_premium_pill', timeout=10)
        ed.require_log(_A34175E5_SHOW_T, 10, since=m, why='PremiumScreenBottomSheet Pro tab shown from the pill')
        _a34175e5_burst(ed, r, xy)


# 2026-11-01 04:48 level 2 attempt 3
_A34175E5_SHOW_T = r'pro_screen_show_t\d'            # selectTab(0): sheet built, Continue live, billing still answering
_A34175E5_TAP_T = r'pro_screen_tap_continue_t\d'     # btnContinue listener ran (before the guard / debounce)


def _a34175e5_tap_id(ed, sel):
    s = ed.screen()
    if s is not None and s.has((sel,)):
        ed.dev.tap(*s.find((sel,)).center)
        return True
    return False


def _a34175e5_front(ed):
    return 'com.myzesty' in ed.dev.sh('dumpsys window | grep -m1 mCurrentFocus')


def _a34175e5_home(ed, timeout=60):
    """Reach the home screen (Premium pill). Never BACK on home: it leaves the app (last attempt's failure)."""
    end = time.time() + timeout
    while time.time() < end:
        if not _a34175e5_front(ed):
            ed.dev.launch()
            time.sleep(3)
            continue
        s = ed.screen()
        if s is not None and s.has(('id:home_premium_pill',)) and not s.has(('id:btn_continue',)):
            return
        if s is not None and (s.has(('id:btn_continue',)) or s.has(('id:tv_skip',))):
            _a34175e5_tap_id(ed, 'id:btn_close') or _a34175e5_tap_id(ed, 'id:tv_skip')
        elif 'Superwall' in ed.dev.sh('dumpsys window | grep -m1 mCurrentFocus'):
            ed.dev.key('KEYCODE_BACK')               # a launch paywall activity on top: close it
        time.sleep(1.5)
    raise UIError('home screen (home_premium_pill) not reached')


def _a34175e5_continue_xy(ed):
    """Open the paywall once from the Premium pill, note where CONTINUE sits, let billing settle, close it."""
    _a34175e5_home(ed)
    _a34175e5_tap_id(ed, 'id:home_premium_pill')
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('id:btn_continue',)):
            xy = s.find(('id:btn_continue',)).center
            time.sleep(2)
            _a34175e5_tap_id(ed, 'id:btn_close')
            time.sleep(2)
            return xy
        time.sleep(0.7)
    raise UIError('paywall CONTINUE (btn_continue) never showed after the Premium pill')


def _a34175e5_burst(ed, r, xy, since, seconds=1.6):
    """Sheet is up (show_t logged): CONTINUE tapped again and again at finger speed while the plans load."""
    ed.require_log(_A34175E5_SHOW_T, 15, since=since, why='PremiumScreenBottomSheet tab 0 shown (Continue live)')
    end = time.time() + seconds
    while time.time() < end:
        ed.dev.tap(*xy)
        time.sleep(r.uniform(0.06, 0.12))
    ed.require_log(_A34175E5_TAP_T, 3, since=since, why='btnContinue click reached the sheet')
    ed.idle(1.5)
    for _ in range(3):                               # no crash: Play purchase sheet / paywall closed again
        if _a34175e5_front(ed) and not _a34175e5_tap_id(ed, 'id:btn_close'):
            break
        if not _a34175e5_front(ed):
            ed.dev.key('KEYCODE_BACK')
        time.sleep(1.5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_3_a(ed, r):
    """Instances phone 1+2: paywall opened on MainActivity, CONTINUE tapped at once while Play billing answers (Premium pill, 6 opens)."""
    xy = _a34175e5_continue_xy(ed)
    for k in range(6):
        ed.step(f'Premium pill -> CONTINUE right away ({k + 1}/6)')
        _a34175e5_home(ed)
        m = ed.log_mark()
        _a34175e5_tap_id(ed, 'id:home_premium_pill')
        _a34175e5_burst(ed, r, xy, m)
        ed.idle(r.uniform(1, 3))


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_3_b(ed, r):
    """Instances phone 1+2: paywall opened seconds after a launch (billing client still connecting, as in the field), CONTINUE at once."""
    xy = _a34175e5_continue_xy(ed)
    for k in range(3):
        ed.step(f'home -> back to the app -> Premium pill as soon as home shows ({k + 1}/3)')
        ed.dev.key('KEYCODE_HOME')                   # background -> active, like the field user's app switches
        time.sleep(r.uniform(3, 6))
        ed.dev.launch()
        _a34175e5_home(ed, timeout=30)
        m = ed.log_mark()
        _a34175e5_tap_id(ed, 'id:home_premium_pill')
        _a34175e5_burst(ed, r, xy, m)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l2_3_c(ed, r):
    """Instance phone 2 (1.25.1 breadcrumbs): first session after cleared data -> the auto paywall pops up -> CONTINUE tapped as it appears."""
    xy = _a34175e5_continue_xy(ed)
    ed.step('first session: clear app data, launch, wait for the automatic paywall')
    ed.mon.allow_death = True
    ed.dev.sh('pm clear com.myzesty')
    time.sleep(2)
    m0 = ed.log_mark()
    ed.dev.launch()
    time.sleep(3)
    ed.mon.allow_death = False
    ed.require_log(r'app_opened_first_time', 30, since=m0, why='field: first session')
    since, end = m0, time.time() + 120
    while time.time() < end:                         # onboarding / bg-remover task skipped as in the field
        if ed.wait_log(_A34175E5_SHOW_T, 1.0, since=since):
            _a34175e5_burst(ed, r, xy, since)
            return
        if not _a34175e5_front(ed):
            ed.dev.launch()
            time.sleep(3)
            continue
        _a34175e5_tap_id(ed, 'id:tv_skip') or _a34175e5_tap_id(ed, 'textc:skip')
        time.sleep(r.uniform(0.8, 1.5))
    raise UIError('no automatic paywall (pro_screen_show_t*) in the first session')


# 2026-11-01 04:57 level 3 attempt 1
_A34175E5_EV = r'Event: (?:test_)?'                  # AnalyticsManager logs every event (ProductionInternal adds test_)


def _a34175e5_tap_id(ed, sel):
    s = ed.screen()
    if s is not None and s.has((sel,)):
        ed.dev.tap(*s.find((sel,)).center)
        return True
    return False


def _a34175e5_front(ed):
    return 'com.myzesty' in ed.dev.sh('dumpsys window | grep -m1 mCurrentFocus')


def _a34175e5_online(ed):
    """Network back on AFTER the cold start: Remote Config already failed its only (startup) fetch, so
    use_superwall_paywall stays at its default false -> the legacy PremiumScreenBottomSheet; billing still works."""
    ed.dev.network(True)
    for _ in range(20):
        if ' 0% packet loss' in ed.dev.sh('ping -c1 -W1 8.8.8.8'):
            break
        time.sleep(1)
    time.sleep(3)


def _a34175e5_offline_cold(ed, clear=False):
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.dev.network(False)
    if clear:
        ed.dev.sh('pm clear com.myzesty')
        time.sleep(2)
        ed.dev.sh('pm grant com.myzesty android.permission.POST_NOTIFICATIONS 2>/dev/null')
    m = ed.log_mark()
    ed.dev.launch()
    time.sleep(3)
    ed.mon.allow_death = False
    return m


def _a34175e5_home(ed, timeout=150):
    """Skip onboarding page / bg-remover task / any sheet until the home Premium pill shows. Never BACK blindly."""
    end = time.time() + timeout
    while time.time() < end:
        if not _a34175e5_front(ed):
            ed.dev.launch()
            time.sleep(3)
            continue
        s = ed.screen()
        if s is not None and s.has(('id:home_premium_pill',)) and not s.has(('id:btn_continue',)):
            return s.find(('id:home_premium_pill',)).center
        if not (_a34175e5_tap_id(ed, 'id:tv_skip') or _a34175e5_tap_id(ed, 'id:btn_close')
                or _a34175e5_tap_id(ed, 'textc:skip')):
            time.sleep(1)
        time.sleep(1.2)
    raise UIError('home screen (home_premium_pill) not reached')


def _a34175e5_learn_xy(ed, pill):
    """Open the legacy sheet once, wait for the plans, note CONTINUE, close it (Cancel)."""
    m = ed.log_mark()
    ed.dev.tap(*pill)
    ed.require_log(_A34175E5_EV + r'pro_screen_show_t\d', 15, since=m,
                   why='legacy PremiumScreenBottomSheet tab 0 (not Superwall)')
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('id:btn_continue',)) and s.has(('id:tvPrice',)):
            xy = s.find(('id:btn_continue',)).center
            _a34175e5_tap_id(ed, 'id:btn_close')
            time.sleep(2)
            return xy
        time.sleep(0.5)
    raise UIError('paywall CONTINUE with plans never showed')


def _a34175e5_burst(ed, r, pill, xy, slow, pressure=None, seconds=2.5):
    """Pill -> sheet attaches (pro_screen_show_t*) -> CONTINUE hammered while billing answers, on a slow busy phone."""
    ed.step(f'paywall -> CONTINUE burst (slow_phone {slow}, pressure {pressure})')
    ed.dev.slow_phone(slow)
    try:
        m = ed.log_mark()
        ed.dev.tap(*pill)
        if pressure:
            ed.dev.sh(f'am send-trim-memory com.myzesty {pressure}')
        ed.require_log(_A34175E5_EV + r'pro_screen_show_t\d', 10, since=m, why='sheet view built, Continue live')
        end, n = time.time() + seconds, 0
        while time.time() < end:
            ed.dev.tap(*xy)
            n += 1
            if n % 2 == 0 and not _a34175e5_front(ed):
                break                                    # Play purchase sheet: the plans were already there
    finally:
        ed.dev.slow_phone(0)
    ed.require_log(_A34175E5_EV + r'pro_screen_tap_continue_t\d', 5, since=m, why='taps reached btnContinue')
    ed.idle(1.5)
    if not _a34175e5_front(ed):
        ed.dev.key('KEYCODE_BACK')                       # cancel the Play purchase sheet, never buy
        time.sleep(2)
    _a34175e5_tap_id(ed, 'id:btn_close')
    time.sleep(1.5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_1_a(ed, r):
    """Instance phone 2 (1.25.1): pm clear first run -> skip onboarding + bg-remover task -> home -> first paywall of a cold process, CONTINUE at once on a slow phone."""
    try:
        m0 = _a34175e5_offline_cold(ed, clear=True)
        ed.require_log(_A34175E5_EV + 'app_opened_first_time', 40, since=m0, why='field: first session after install')
        pill = _a34175e5_home(ed)
        ed.require_log(_A34175E5_EV + 'onboarding_task_bg_remover_skip', 2, since=m0, why='field: bg-remover task skipped')
        _a34175e5_online(ed)
        xy = _a34175e5_learn_xy(ed, pill)
        for k in range(2):                               # field: first sheet of the process (tier not cached yet)
            _a34175e5_offline_cold(ed)
            pill = _a34175e5_home(ed, 60)
            _a34175e5_online(ed)
            _a34175e5_burst(ed, r, pill, xy, slow=r.choice([28, 36, 44]))
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_1_b(ed, r):
    """Instance phone 1 (1.25.2, no breadcrumbs): repeated paywall opens in one process (tier cached, billing answers off main) under CPU load + critical memory pressure."""
    try:
        _a34175e5_offline_cold(ed, clear=True)
        pill = _a34175e5_home(ed)
        _a34175e5_online(ed)
        xy = _a34175e5_learn_xy(ed, pill)
        for k in range(5):
            _a34175e5_burst(ed, r, pill, xy, slow=r.choice([24, 36, 48]),
                            pressure=r.choice(['RUNNING_CRITICAL', 'RUNNING_LOW', None]))
            ed.idle(r.uniform(1, 2))
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_1_c(ed, r):
    """Instances phone 1+2: MainActivity coming back (camera + memory pressure in between, as after the task) -> paywall at once -> CONTINUE on a slow phone."""
    try:
        _a34175e5_offline_cold(ed, clear=True)
        pill = _a34175e5_home(ed)
        _a34175e5_online(ed)
        xy = _a34175e5_learn_xy(ed, pill)
        for k in range(3):
            ed.step(f'away with camera + trim memory, back to home ({k + 1}/3)')
            ed.dev.key('KEYCODE_HOME')
            ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
            time.sleep(2)
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
            ed.idle(r.uniform(4, 10))
            ed.dev.launch()
            time.sleep(r.uniform(0.8, 1.5))
            pill = _a34175e5_home(ed, 40)
            _a34175e5_burst(ed, r, pill, xy, slow=r.choice([32, 40, 48]), pressure='RUNNING_MODERATE')
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


# 2026-11-01 05:09 level 3 attempt 2
_A34175E5_TASK = r'com\.myzesty/\S*TaskActivity'      # onboarding bg-remover task (system log; app events are not in logcat)


def _a34175e5_tap_id(ed, sel):
    s = ed.screen()
    if s is not None and s.has((sel,)):
        ed.dev.tap(*s.find((sel,)).center)
        return True
    return False


def _a34175e5_focus(ed):
    return ed.dev.sh('dumpsys window | grep -m1 mCurrentFocus')


def _a34175e5_home(ed, timeout=120):
    """Close intro / task / sheets until the home Premium pill shows (never BACK blindly)."""
    end = time.time() + timeout
    while time.time() < end:
        if 'com.myzesty' not in _a34175e5_focus(ed):
            ed.dev.launch()
            time.sleep(3)
            continue
        s = ed.screen()
        if s is not None and s.has(('id:home_premium_pill',)) and not s.has(('id:btn_continue',)):
            return s.find(('id:home_premium_pill',)).center
        if not (_a34175e5_tap_id(ed, 'id:btn_close') or _a34175e5_tap_id(ed, 'id:tv_skip')
                or _a34175e5_tap_id(ed, 'textc:skip')):
            time.sleep(0.8)
        time.sleep(0.8)
    raise UIError('home screen (home_premium_pill) not reached')


def _a34175e5_learn(ed):
    """Open the legacy PremiumScreenBottomSheet once from the pill, note CONTINUE, close it."""
    pill = _a34175e5_home(ed)
    ed.dev.tap(*pill)
    for _ in range(30):
        s = ed.screen()
        if s is not None and s.has(('id:btn_continue',)) and s.has(('id:tvPrice',)):
            xy = s.find(('id:btn_continue',)).center
            _a34175e5_tap_id(ed, 'id:btn_close')
            time.sleep(1.5)
            return pill, xy
        time.sleep(0.5)
    raise UIError('legacy paywall (btn_continue + plans) never showed: Superwall flag on?')


def _a34175e5_burst(ed, pill, xy, slow, pressure=None, n=16):
    """Pill -> sheet attaches -> CONTINUE hammered from the device itself (finger speed) while billing answers;
    the loop stops as soon as the Play purchase sheet takes focus (never buy)."""
    ed.step(f'pill -> CONTINUE burst on device (slow_phone {slow}, pressure {pressure})')
    loop = (f"(input tap {pill[0]} {pill[1]}; sleep 0.2; i=0; while [ $i -lt {n} ]; do "
            f"dumpsys window | grep -m1 mCurrentFocus | grep -q myzesty || break; "
            f"input tap {xy[0]} {xy[1]} & i=$((i+1)); sleep 0.03; done) >/dev/null 2>&1 &")
    ed.dev.slow_phone(slow)
    try:
        ed.dev.sh(loop)
        if pressure:
            ed.dev.sh(f'am send-trim-memory com.myzesty {pressure}')
        ed.idle(6)                                       # IndexOutOfBounds on main -> AppFailure here
    finally:
        ed.dev.slow_phone(0)
    if 'vending' in _a34175e5_focus(ed):
        ed.dev.key('KEYCODE_BACK')                       # cancel the Play purchase sheet
        time.sleep(2)
    _a34175e5_tap_id(ed, 'id:btn_close')
    time.sleep(1.5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_2_a(ed, r):
    """Instance phone 2 (1.25.1): pm clear first session -> skip intro + bg-remover task -> paywall right on return, CONTINUE burst on a low-end-slow phone."""
    ed.dev.restore_env()
    pill, xy = _a34175e5_learn(ed)
    ed.step('first session: clear app data, launch online')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.dev.sh('pm clear com.myzesty')
    time.sleep(2)
    ed.dev.sh('pm grant com.myzesty android.permission.POST_NOTIFICATIONS 2>/dev/null')
    m0 = ed.log_mark()
    ed.dev.launch()
    time.sleep(3)
    ed.mon.allow_death = False
    end = time.time() + 90
    while time.time() < end and not ed.wait_log(_A34175E5_TASK, 0.5, since=m0):
        if not (_a34175e5_tap_id(ed, 'textc:skip') or _a34175e5_tap_id(ed, 'id:btn_close')):
            time.sleep(1)
    ed.require_log(_A34175E5_TASK, 2, since=m0, why='field: intro skipped into the TaskActivity bg-remover task')
    ed.ui.tap('id:tv_skip', timeout=20)                  # field: onboarding_task_bg_remover_skip
    try:
        pill = _a34175e5_home(ed, 40)                    # back on MainActivity: field paywall came 1.7 s later
        _a34175e5_burst(ed, pill, xy, slow=r.choice([32, 40, 46]))
        for _ in range(2):
            _a34175e5_burst(ed, _a34175e5_home(ed, 30), xy, slow=r.choice([36, 46]))
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_2_b(ed, r):
    """Instances phone 1+2: first sheet of a cold process on a slow network (billing answers late, mid-tapping), slow phone, 4 cold opens."""
    ed.dev.restore_env()
    _, xy = _a34175e5_learn(ed)
    try:
        for k in range(4):
            ed.step(f'cold open {k + 1}/4, slow network')
            ed.mon.allow_death = True
            ed.dev.force_stop()
            ed.dev.launch()
            time.sleep(2)
            ed.mon.allow_death = False
            pill = _a34175e5_home(ed, 60)
            ed.dev.slow_network(r.choice([48, 96, 160]))
            _a34175e5_burst(ed, pill, xy, slow=r.choice([28, 40]))
            ed.dev.slow_network(0)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.restore_env()


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_l3_2_c(ed, r):
    """Instances phone 1+2: app reclaimed in background, relaunch, paywall + CONTINUE as soon as home shows, under critical memory pressure."""
    ed.dev.restore_env()
    _, xy = _a34175e5_learn(ed)
    try:
        for k in range(4):
            ed.step(f'system reclaim + relaunch {k + 1}/4')
            ed.kill_bg()
            ed.dev.launch()
            pill = _a34175e5_home(ed, 60)                # startup work still running on main, like the field
            _a34175e5_burst(ed, pill, xy, slow=r.choice([36, 46]), pressure='RUNNING_CRITICAL')
    finally:
        ed.dev.slow_phone(0)
