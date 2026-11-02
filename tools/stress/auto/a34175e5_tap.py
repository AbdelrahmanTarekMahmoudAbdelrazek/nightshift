# Night Shift tap repros for a34175e57d4cd343ec43f9d330ccada0 (from the engine repro + full field log)


# 2026-11-01 03:53 attempt 1
# Night Shift tapflow: Crashlytics a34175e5, IndexOutOfBounds in PremiumScreenBottomSheet.buySubscription
# (subPlanList[1] on an empty list: subscriptionItem set in resolveTier before the Main coroutine refills subPlanList).

PKG_APP = 'com.myzesty'
CONTINUE = ('id:btn_continue', 'textc:continue')
SHOW_T = r'Logging event.*pro_screen_show_t\d'          # selectTab(0) in init(): the sheet is up
TIER = r'country=\S* tier=\w+'                           # TierResolver: line 775 runs right after this
TAP_T = r'Logging event.*pro_screen_tap_continue_t\d'    # btnContinue onClick reached


def _fa_verbose(ed):
    ed.dev.setprop('log.tag.FA', 'VERBOSE')
    ed.dev.setprop('log.tag.FA-SVC', 'VERBOSE')


def _continue_xy(ed, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        s = ed.screen()
        if s is not None and s.has(CONTINUE):
            return s.find(CONTINUE).center
        time.sleep(0.2)
    raise UIError('paywall Continue (btn_continue) never showed')


def _storm(ed, xy, n=60, gap=0.04):
    """Parallel `input tap`s on Continue: taps before line 775 bounce off the guard without touching debounce."""
    x, y = xy
    ed.dev.sh(f'for i in $(seq {n}); do input tap {x} {y} & sleep {gap}; done; wait', timeout=30)


def _paywall_round(ed, since, xy=None):
    ed.require_log(SHOW_T, timeout=40, since=since, why='paywall opened (pro_screen_show_t)')
    xy = xy or _continue_xy(ed)
    ed.step('TRIGGER: Continue storm across the resolveTier -> subPlanList window')
    _storm(ed, xy)
    ed.require_log(TAP_T, timeout=10, since=since, why='Continue tap reached buySubscription')
    ed.idle(2)
    ed.dev.key('KEYCODE_BACK')                          # race missed: close the Play purchase sheet if it opened
    return xy


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_1_a(ed, r):
    """FULL: fresh install first run -> onboarding skip -> bg-remover task Skip -> day0 paywall -> Continue at once."""
    ed.dev.restore_env()
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG_APP}')                    # first session: app_opened_first_time + onboarding
    _fa_verbose(ed)
    t0 = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'Logging event.*app_opened_first_time', timeout=40, since=t0, why='first app open')
    for _ in range(3):                                  # onboarding_continue / onboarding_1_skip
        ed.step('onboarding: skip')
        ed.ui.tap(('textc:skip', 'textc:continue'), timeout=15)
        if ed.wait_log(r'Logging event.*onboarding_task_bg_remover_show', 3, since=t0):
            break
    ed.require_log(r'Logging event.*onboarding_task_bg_remover_show', timeout=15, since=t0, why='TaskActivity shown')
    t1 = ed.log_mark()
    ed.step('TaskActivity: Skip (tv_skip)')
    ed.ui.tap(('id:tv_skip',), timeout=15)
    ed.require_log(r'Logging event.*onboarding_task_bg_remover_skip', timeout=10, since=t1, why='bg-remover skipped')
    xy = _paywall_round(ed, t1)
    for _ in range(3):                                  # the day0 paywall opens again on each new launch
        ed.dev.force_stop()
        t = ed.log_mark()
        ed.dev.launch()
        _paywall_round(ed, t, xy)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_1_b(ed, r):
    """HYBRID: paywall reached by a cold launch as an existing user (shows on every launch); Continue storm is real taps."""
    ed.dev.restore_env()
    _fa_verbose(ed)
    xy = None
    for k in range(6):
        ed.step(f'cold launch {k + 1}/6 -> auto paywall')
        ed.dev.force_stop()                             # HYBRID: replaces the first-run onboarding path
        t = ed.log_mark()
        ed.dev.launch()                                 # HYBRID
        xy = _paywall_round(ed, t, xy)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_1_c(ed, r):
    """HYBRID: like b on a low-end-phone CPU (busy main thread delays the subPlanList coroutine past the tap)."""
    ed.dev.restore_env()
    _fa_verbose(ed)
    xy = None
    try:
        for k in range(6):
            lvl = r.choice((30, 38, 45))
            ed.step(f'cold launch {k + 1}/6 on slow_phone({lvl})')
            ed.dev.slow_phone(0)
            ed.dev.force_stop()                         # HYBRID
            t = ed.log_mark()
            ed.dev.launch()                             # HYBRID
            ed.dev.slow_phone(lvl)                      # cold start + sheet inflate + header video all on a starved main
            ed.require_log(SHOW_T, timeout=60, since=t, why='paywall opened (pro_screen_show_t)')
            xy = xy or _continue_xy(ed, timeout=40)
            ed.trim_memory('RUNNING_LOW')
            ed.step('TRIGGER: Continue storm on the slow phone')
            _storm(ed, xy, n=90, gap=0.03)
            ed.wait_log(TIER, 15, since=t)              # informative: when line 775 ran
            ed.require_log(TAP_T, timeout=15, since=t, why='Continue tap reached buySubscription')
            ed.idle(2)
            ed.dev.key('KEYCODE_BACK')
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 03:59 attempt 2
# Night Shift tapflow: Crashlytics a34175e5, IndexOutOfBounds in PremiumScreenBottomSheet.buySubscription
# (subPlanList[1] on an empty list: subscriptionItem set in resolveTier before the Main coroutine refills subPlanList).
# The legacy sheet only shows when remote config use_superwall_paywall=false (PaywallPresenterFactory), so each
# recipe rolls fresh installs / launches until the legacy sheet (pro_screen_show_t*) opens instead of Superwall.

PKG_APP = 'com.myzesty'
EV = r'(?:Logging event|AnalyticsManager: Event:)\D*?'
CONTINUE = ('id:btn_continue', 'textc:continue')
LEGACY = EV + r'pro_screen_show_t\d'                              # selectTab(0) in PremiumScreenBottomSheet.init
SUPERWALL = r'wm_create_activity: .*SuperwallPaywallActivity'
TAP_T = EV + r'pro_screen_tap_continue_t\d'                       # btnContinue onClick -> buySubscription


def _which_paywall(ed, since, timeout=40):
    line = ed.wait_log(f'{LEGACY}|{SUPERWALL}', timeout, since=since)
    return 'legacy' if line and 'pro_screen_show_t' in line else ('superwall' if line else None)


def _continue_xy(ed, timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        s = ed.screen()
        if s is not None and s.has(CONTINUE):
            return s.find(CONTINUE).center
        time.sleep(0.1)
    raise UIError('legacy paywall up but btn_continue never showed')


def _storm(ed, xy, n=60, gap=0.04):
    x, y = xy
    ed.dev.sh(f'for i in $(seq {n}); do input tap {x} {y} & sleep {gap}; done; wait', timeout=40)


def _trigger(ed, since, xy, n=60, gap=0.04):
    xy = xy or _continue_xy(ed)
    ed.step('TRIGGER: Continue storm across the resolveTier -> subPlanList window')
    _storm(ed, xy, n, gap)
    ed.require_log(TAP_T, timeout=10, since=since, why='Continue tap reached buySubscription')
    ed.idle(2)
    ed.dev.key('KEYCODE_BACK')                                    # race missed: close the Play purchase sheet
    return xy


def _first_run(ed):
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG_APP}')                              # new install: new Firebase id, new remote-config fetch
    ed.dev.setprop('log.tag.FA', 'VERBOSE')
    t0 = ed.log_mark()
    ed.dev.launch()
    ed.require_log(EV + 'app_opened_first_time', timeout=40, since=t0, why='first app open')
    for _ in range(3):
        ed.step('onboarding: skip')
        ed.ui.tap(('textc:skip', 'textc:continue'), timeout=15)
        if ed.wait_log(EV + 'onboarding_task_bg_remover_show', 4, since=t0):
            break
    ed.require_log(EV + 'onboarding_task_bg_remover_show', timeout=15, since=t0, why='TaskActivity shown')
    t1 = ed.log_mark()
    ed.step('TaskActivity: Skip (tv_skip)')
    ed.ui.tap(('id:tv_skip',), timeout=15)
    ed.require_log(EV + 'onboarding_task_bg_remover_skip', timeout=10, since=t1, why='bg-remover skipped')
    return t1


def _relaunch_rounds(ed, r, rounds, slow=False):
    xy, got = None, False
    for k in range(rounds):
        ed.step(f'cold launch {k + 1}/{rounds} -> auto day0 paywall')
        ed.dev.slow_phone(0)
        ed.dev.force_stop()                                       # HYBRID: existing-user relaunch instead of a new install
        t = ed.log_mark()
        ed.dev.launch()                                           # HYBRID
        if slow:
            ed.dev.slow_phone(r.choice((30, 38, 45)))             # starved main: the subPlanList coroutine runs late
        kind = _which_paywall(ed, t, timeout=60 if slow else 40)
        ed.log(f'    paywall on launch {k + 1}: {kind}')
        if kind == 'legacy':
            got = True
            if slow:
                ed.trim_memory('RUNNING_LOW')
            xy = _trigger(ed, t, xy, n=90 if slow else 60, gap=0.03 if slow else 0.04)
        elif kind == 'superwall':
            ed.idle(2)
            ed.dev.key('KEYCODE_BACK')
    return got


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_2_a(ed, r):
    """FULL: fresh install first run -> onboarding skip -> bg-remover Skip -> day0 paywall -> Continue at once."""
    ed.dev.restore_env()
    for k in range(4):                                            # each pm clear = a new install, a new config bucket
        ed.step(f'fresh install {k + 1}/4')
        t1 = _first_run(ed)
        kind = _which_paywall(ed, t1)
        ed.log(f'    first-run paywall: {kind}')
        if kind == 'legacy':
            _trigger(ed, t1, None)
            return
    ed.require_log(LEGACY, timeout=1, why='legacy PremiumScreenBottomSheet never shown (remote config serves Superwall)')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_2_b(ed, r):
    """HYBRID: one real first run, then existing-user relaunches (day0 paywall every launch); Continue storm is real taps."""
    ed.dev.restore_env()
    got = False
    for k in range(2):
        t1 = _first_run(ed)                                       # also fetches this install's remote config
        if _which_paywall(ed, t1) == 'legacy':
            _trigger(ed, t1, None)
            got = True
        else:
            ed.dev.key('KEYCODE_BACK')
        got = _relaunch_rounds(ed, r, 4) or got
        if got:
            return
    ed.require_log(LEGACY, timeout=1, why='legacy PremiumScreenBottomSheet never shown (remote config serves Superwall)')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_2_c(ed, r):
    """HYBRID: like b on a low-end-phone CPU (busy main delays the subPlanList refill past the queued Continue taps)."""
    ed.dev.restore_env()
    got = False
    try:
        for k in range(2):
            t1 = _first_run(ed)
            ed.dev.slow_phone(r.choice((30, 38, 45)))             # field: low-end Xiaomi, paywall right after onboarding
            if _which_paywall(ed, t1, timeout=60) == 'legacy':
                _trigger(ed, t1, None, n=90, gap=0.03)
                got = True
            else:
                ed.dev.key('KEYCODE_BACK')
            got = _relaunch_rounds(ed, r, 4, slow=True) or got
            if got:
                return
    finally:
        ed.dev.slow_phone(0)
    ed.require_log(LEGACY, timeout=1, why='legacy PremiumScreenBottomSheet never shown (remote config serves Superwall)')


# 2026-11-01 04:17 attempt 3
# Night Shift tapflow: Crashlytics a34175e5, IndexOutOfBounds in PremiumScreenBottomSheet.buySubscription
# (subPlanList[1] on an empty list: subscriptionItem set in resolveTier (line 775) before the Main coroutine
# (780-807) refills subPlanList). The legacy sheet only opens when remote config use_superwall_paywall=false
# (PaywallPresenterFactory), so every recipe rolls new installs until one gets the legacy sheet.

PKG_APP = 'com.myzesty'
EV = r'(?:Logging event|AnalyticsManager: Event:)\D*?'
CONTINUE = ('id:btn_continue', 'textc:continue')
LEGACY = EV + r'pro_screen_show_t\d'                                   # selectTab(0) in PremiumScreenBottomSheet.init
SUPERWALL = r'wm_on_create_called: \[\d+,com\.superwall'               # app-side line (wait_log misses system lines)
TAP_T = EV + r'pro_screen_tap_continue_t\d'                            # btnContinue onClick -> buySubscription


def _which_paywall(ed, since, timeout=40):
    line = ed.wait_log(f'{LEGACY}|{SUPERWALL}', timeout, since=since)
    return 'legacy' if line and 'pro_screen_show_t' in line else ('superwall' if line else None)


def _storm(ed, since, n=80, gap=0.03):
    end = time.time() + 10
    while True:
        s = ed.screen()
        if s is not None and s.has(CONTINUE):
            x, y = s.find(CONTINUE).center
            break
        if time.time() > end:
            raise UIError('legacy paywall up but btn_continue never showed')
    ed.step('TRIGGER: Continue storm across resolveTier -> subPlanList refill')
    ed.dev.sh(f'for i in $(seq {n}); do input tap {x} {y} & sleep {gap}; done; wait', timeout=40)
    ed.require_log(TAP_T, timeout=10, since=since, why='Continue tap reached buySubscription')
    ed.idle(2)
    ed.dev.key('KEYCODE_BACK')                                         # race missed: close the Play purchase sheet


def _first_run(ed, offline=False):
    ed.dev.force_stop()
    ed.dev.sh(f'pm clear {PKG_APP}')                                   # new install: new remote-config instance
    if offline:
        ed.dev.network(False)                                          # first fetchAndActivate fails
    t0 = ed.log_mark()
    ed.dev.launch()
    ed.require_log(EV + 'app_opened_first_time', timeout=40, since=t0, why='first app open')
    if offline:
        ed.idle(4)
        ed.dev.network(True)                                           # Billing + paywall need the network
    for _ in range(3):
        ed.step('onboarding: skip')
        ed.ui.tap(('textc:skip', 'textc:continue'), timeout=15)
        if ed.wait_log(EV + 'onboarding_task_bg_remover_show', 4, since=t0):
            break
    ed.require_log(EV + 'onboarding_task_bg_remover_show', timeout=15, since=t0, why='TaskActivity shown')
    t1 = ed.log_mark()
    ed.step('TaskActivity: Skip (tv_skip)')
    ed.ui.tap(('id:tv_skip',), timeout=15)
    ed.require_log(EV + 'onboarding_task_bg_remover_skip', timeout=10, since=t1, why='bg-remover skipped')
    return t1


def _roll(ed, r, installs, relaunches=0, offline=False, slow=False):
    for k in range(installs):
        ed.step(f'fresh install {k + 1}/{installs}')
        ed.dev.slow_phone(0)
        t1 = _first_run(ed, offline=offline)
        if slow:
            ed.dev.slow_phone(r.choice((30, 38, 45)))                  # starved main: refill coroutine runs late
        kind = _which_paywall(ed, t1, timeout=60 if slow else 40)
        ed.log(f'    first-run paywall: {kind}')
        if kind != 'legacy':
            continue
        _storm(ed, t1, n=110 if slow else 80, gap=0.02 if slow else 0.03)
        for j in range(relaunches):                                    # HYBRID: same install, day0 paywall each launch
            ed.step(f'cold relaunch {j + 1}/{relaunches} of the legacy install')
            ed.dev.force_stop()                                        # HYBRID
            t = ed.log_mark()
            ed.dev.launch()                                            # HYBRID
            if slow:
                ed.dev.slow_phone(r.choice((30, 38, 45)))
            ed.require_log(LEGACY, timeout=60, since=t, why='legacy paywall on relaunch')
            if slow:
                ed.trim_memory('RUNNING_LOW')
            _storm(ed, t, n=110 if slow else 80, gap=0.02 if slow else 0.03)
        return
    ed.require_log(LEGACY, timeout=1, why='legacy PremiumScreenBottomSheet never shown (remote config serves Superwall)')


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_3_a(ed, r):
    """FULL: fresh install first run -> onboarding skip -> bg-remover Skip -> day0 legacy paywall -> Continue at once."""
    ed.dev.restore_env()
    _roll(ed, r, installs=6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_3_b(ed, r):
    """HYBRID: real first run until a legacy-paywall install, then cold relaunches of it; Continue storm is real taps."""
    ed.dev.restore_env()
    _roll(ed, r, installs=5, relaunches=6)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_a34175e5_3_c(ed, r):
    """HYBRID: like b, but the first launch is offline (config fetch fails) and the phone is low-end slow during the paywall."""
    ed.dev.restore_env()
    try:
        _roll(ed, r, installs=5, relaunches=5, offline=True, slow=True)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.network(True)
