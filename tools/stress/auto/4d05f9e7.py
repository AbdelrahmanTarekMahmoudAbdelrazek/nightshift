# Night Shift auto repros for 4d05f9e74e77520b418eac3a355108f1


# 2026-11-01 06:54 level 2 attempt 1
def _4d05f9e7_seek_burst(ed, r, n):
    for _ in range(n):
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(80, 220))
        ed.idle(r.uniform(0.1, 0.35))


@scenario('nightshift', 'auto')
def ns_4d05f9e7_l2_1_a(ed, r):
    """Xiaomi 21091116UI (1/20, FOREGROUND): freeze, scrub bursts, back, scrub again, leave editor -> MsgSaveDraft."""
    ed.set_playing(False)
    mark = ed.log_mark()
    ed.freeze()
    ed.require_log(r'MsgActivateFreeze', 15, since=mark, why='field toggled a freeze (MsgActivateFreeze) before back')
    ed.idle(r.uniform(2, 3))
    mark = ed.log_mark()
    _4d05f9e7_seek_burst(ed, r, r.randint(10, 14))
    ed.require_log(r'VideoPlayer::seek requested', 10, since=mark, why='field had seek bursts before back')
    ed.dev.key('KEYCODE_BACK')                       # field 'back' (videoeditor_backcalled) at T-7.02s
    ed.idle(1.5)
    sc = ed.screen()
    if sc is not None and ed.in_editor(sc):          # field kept scrubbing ~5 s after that back
        _4d05f9e7_seek_burst(ed, r, r.randint(12, 18))
    mark = ed.log_mark()
    ed.leave_editor()                                # field: lease ACQUIRED, then MsgSaveDraft at T-0
    ed.require_log(r'MsgSaveDraft', 15, since=mark, why='field ANR was recorded at MsgSaveDraft')
    ed.settle(12)


@scenario('nightshift', 'auto')
def ns_4d05f9e7_l2_1_b(ed, r):
    """vivo V2207 (1/20, FOREGROUND): playback with an audio clip, play/pause taps while audio decoders run dry."""
    push_newest_video(ed)
    mark = ed.log_mark()
    ed.add_media(pick=0)
    ed.require_log(r'MsgAddVideo', 30, since=mark, why='field timeline had a long clip with audio')
    ed.idle(3)
    for _ in range(r.randint(4, 6)):
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='field was playing (ve_play_pause_btn)')
        ed.idle(r.uniform(3, 8))
        ed.seek_swipe(r.uniform(-0.5, 0.5), r.randint(100, 250))
        ed.idle(r.uniform(0.5, 1.5))
        ed.set_playing(False)                        # field last action: ve_play_pause_btn
        ed.idle(r.uniform(0.3, 1.0))
    ed.set_playing(True)
    ed.idle(r.uniform(4, 8))
    ed.toggle_play()
    ed.settle(12)


@scenario('nightshift', 'auto')
def ns_4d05f9e7_l2_1_c(ed, r):
    """Xiaomi 21091116UI (1/20) on a longer timeline: added clip, split, freeze, scrub storm, back to save while seeks fly."""
    push_newest_video(ed)
    ed.add_media(pick=0)
    ed.idle(3)
    ed.set_playing(False)
    ed.split_at(r.uniform(0.3, 0.6))
    ed.idle(1.5)
    mark = ed.log_mark()
    ed.freeze()
    ed.require_log(r'MsgActivateFreeze', 15, since=mark, why='field toggled a freeze before back')
    ed.idle(2)
    ed.set_playing(True)
    ed.idle(r.uniform(1, 2))
    mark = ed.log_mark()
    _4d05f9e7_seek_burst(ed, r, r.randint(14, 20))
    ed.require_log(r'VideoPlayer::seek requested', 10, since=mark, why='field had seek bursts before back')
    mark = ed.log_mark()
    ed.main_nav()
    ed.dev.key('KEYCODE_BACK')                       # leave right after the burst: save-draft behind live seeks
    ed.require_log(r'MsgSaveDraft', 20, since=mark, why='field ANR was recorded at MsgSaveDraft')
    ed.settle(12)


# 2026-11-01 07:03 level 2 attempt 2
_4D_SEL_ONB = (('textc:continue',), ('textc:next',), ('textc:get started',), ('textc:allow',))


def _4d05f9e7_ev(name):
    return rf'Event: (test_)?{name}\b'


def _4d05f9e7_first_install_to_task(ed):
    """pm clear = a real first install (day-0 onboarding comes back), launch, walk onboarding to TaskActivity."""
    ed.step('first install: pm clear + launch')
    ed.mon.allow_death = True
    ed.dev.sh('pm clear com.myzesty', timeout=30)
    time.sleep(1)
    mark = ed.log_mark()
    ed.dev.launch()
    ed.mon.allow_death = False
    ed.require_log(_4d05f9e7_ev('app_opened_first_time'), 30, since=mark, why='field sessions start as a first install')
    for _ in range(40):                              # onboarding pages at human speed, until the bg-remover task shows
        s = ed.screen()
        if s is not None and s.has(('textc:try a sample image',)):
            break
        for sel in _4D_SEL_ONB:
            if s is not None and s.has(sel):
                ed.dev.tap(*s.find(sel).center)
                break
        time.sleep(1.5)
    ed.require_log(_4d05f9e7_ev('onboarding_task_bg_remover_show'), 10, since=mark, why='field went into the bg-remover task')
    ed.require_log(r'START .*TaskActivity', 5, since=mark, why='field screen_view TaskActivity')
    ed.idle(2)


def _4d05f9e7_bg_remove_and_back_to_paywall(ed, r, mark):
    """Model loads and runs for real, user leaves the result, MainActivity auto-shows the t3 paywall."""
    ed.require_log(r'START .*PhotoActivity', 30, since=mark, why='field opened PhotoActivity from the task')
    ed.require_log(_4d05f9e7_ev('LOAD_MODEL_DONE_complete'), 40, since=mark, why='bg-remover model must really load')
    ed.require_log(_4d05f9e7_ev('onboarding_task_complete'), 60, since=mark, why='field finished the onboarding task')
    ed.idle(r.uniform(4, 6))                         # field: ~4 s on the result before cancel
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')                       # ai_bg_remover_cancel
    ed.require_log(_4d05f9e7_ev('ai_bg_remover_cancel'), 15, since=mark, why='field left the bg-remover result')
    ed.require_log(_4d05f9e7_ev('pro_screen_show_t3'), 20, since=mark, why='t3 paywall auto-shows on MainActivity')


def _4d05f9e7_close_paywall(ed, r):
    ed.idle(r.uniform(6, 13))                        # field: 6.5-13.5 s on the paywall, app in front
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    ed.require_log(_4d05f9e7_ev('pro_screen_cancel_t3'), 10, since=mark, why='field closed the t3 paywall (OPPO T-0)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l2_2_a(ed, r):
    """OPPO CPH2579 + Nokia 5.4 (FOREGROUND): first install, sample-image bg removal, back, t3 paywall shows, close it."""
    _4d05f9e7_first_install_to_task(ed)
    mark = ed.log_mark()
    ed.ui.tap(('textc:try a sample image',), timeout=10)
    ed.require_log(_4d05f9e7_ev('onboarding_task_try_sample_image'), 10, since=mark, why='OPPO used the sample image')
    _4d05f9e7_bg_remove_and_back_to_paywall(ed, r, mark)
    _4d05f9e7_close_paywall(ed, r)
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l2_2_b(ed, r):
    """OnePlus8Pro 07:01/07:16/07:44 + HUAWEI 06:57 (BACKGROUND): after the paywall, tap Ads Creator, Home as AiFeatureActivity opens."""
    _4d05f9e7_first_install_to_task(ed)
    mark = ed.log_mark()
    ed.ui.tap(('textc:try a sample image',), timeout=10)
    _4d05f9e7_bg_remove_and_back_to_paywall(ed, r, mark)
    _4d05f9e7_close_paywall(ed, r)
    ed.idle(r.uniform(2, 4))
    mark = ed.log_mark()
    ed.ui.tap(('textc:ads creator',), timeout=10)    # home AI Studio card (ai_card_label) -> home_ai_ads_tap
    ed.require_log(_4d05f9e7_ev('home_ai_ads_tap'), 10, since=mark, why='field tapped a home AI tool')
    ed.wait_log(r'START .*AiFeatureActivity', 5, since=mark)
    ed.dev.key('KEYCODE_HOME')                       # field process was BACKGROUND right as AiFeatureActivity started
    ed.require_log(r'START .*AiFeatureActivity', 5, since=mark, why='field ended at screen_view AiFeatureActivity')
    ed.idle(r.uniform(10, 15))
    ed.dev.launch()                                  # user comes back (the OnePlus pairs repeat ~3 s later)
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l2_2_c(ed, r):
    """Xiaomi 24116RACCG + HUAWEI 07:14 + realme (permission path): Select a photo, Turn on, allow, pick, bg removal, sit on result."""
    _4d05f9e7_first_install_to_task(ed)
    mark = ed.log_mark()
    ed.ui.tap(('textc:select a photo',), timeout=10)
    ed.require_log(_4d05f9e7_ev('permission_popup'), 10, since=mark, why='field got the media permission popup')
    ed.grant_permissions()                           # 'Turn on' -> system Allow (permission_access_allow)
    ed.require_log(_4d05f9e7_ev('permission_access_allow'), 15, since=mark, why='field allowed media access (Xiaomi T-0)')
    ed.idle(r.uniform(2, 4))
    ed.ui.tap(('id:gridrl',), timeout=15)            # first photo in the picker
    ed.idle(1)
    ed.ui.tap(('id:done',), timeout=3) if ed.screen() is not None and ed.screen().has(('id:done',)) else None
    _4d05f9e7_bg_remove_and_back_to_paywall(ed, r, mark)
    _4d05f9e7_close_paywall(ed, r)
    ed.settle(12)


# 2026-11-01 07:06 level 2 attempt 3
def _4d05f9e7_new_project_from_newest(ed):
    """After the pm clear of the last round there is no test draft: New Project from the newest gallery video."""
    ed.dev.restore_env()
    for _ in range(20):
        s = ed.screen()
        if s is not None and s.has(('textc:new project',)):
            break
        if s is not None and s.has(('textc:turn on',)):
            ed.grant_permissions()                   # pm clear revoked media access
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        time.sleep(2)
    mark = ed.log_mark()
    ed.create_draft()
    ed.require_log(r'MsgAddVideo', 30, since=mark, why='field editor had a real clip loaded')
    ed.idle(3)


def _4d05f9e7_seek_burst(ed, r, n):
    for _ in range(n):
        ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(80, 220))
        ed.idle(r.uniform(0.1, 0.35))


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l2_3_a(ed, r):
    """Xiaomi 21091116UI (FOREGROUND, PlayerActivity): 2 long clips, freeze on/off, seek bursts, back -> lease -> MsgSaveDraft."""
    push_newest_video(ed)                            # long clip with audio, newest in the gallery
    _4d05f9e7_new_project_from_newest(ed)
    mark = ed.log_mark()
    ed.add_media(pick=1)                             # field timeline had several long clips (media_id 3, 4)
    ed.require_log(r'MsgAddVideo', 30, since=mark, why='field timeline had more than one clip')
    ed.idle(3)
    ed.set_playing(False)
    mark = ed.log_mark()
    ed.freeze()
    ed.require_log(r'MsgActivateFreeze', 15, since=mark, why='field toggled a freeze 8 s before back')
    ed.idle(r.uniform(1.5, 3))
    mark = ed.log_mark()
    _4d05f9e7_seek_burst(ed, r, r.randint(12, 16))
    ed.require_log(r'VideoPlayer::seek requested', 10, since=mark, why='field had seek bursts before back')
    ed.main_nav()
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')                       # field 'back' (videoeditor_backcalled) at T-7.02s
    ed.require_log(r'Event: (test_)?back\b', 10, since=mark, why='field pressed back in PlayerActivity')
    ed.idle(1.0)
    sc = ed.screen()
    if sc is not None and ed.in_editor(sc):          # field kept scrubbing ~5 s after that back
        _4d05f9e7_seek_burst(ed, r, r.randint(14, 20))
        ed.dev.key('KEYCODE_BACK')
    ed.require_log(r'MsgSaveDraft', 20, since=mark, why='field ANR was recorded at MsgSaveDraft')
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l2_3_b(ed, r):
    """vivo V2207 (FOREGROUND, PlayerActivity): two clips with audio, long playback with play/pause taps as audio runs dry."""
    push_newest_video(ed)
    _4d05f9e7_new_project_from_newest(ed)
    mark = ed.log_mark()
    ed.add_media(pick=0)                             # second audio-bearing clip (field: AUD layers 0 and 11)
    ed.require_log(r'MsgAddVideo', 30, since=mark, why='field had more than one audio source playing')
    ed.idle(3)
    for _ in range(r.randint(4, 6)):
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='field was playing (ve_play_pause_btn)')
        ed.idle(r.uniform(4, 9))
        ed.seek_swipe(r.uniform(-0.5, 0.5), r.randint(100, 250))
        ed.idle(r.uniform(0.5, 1.5))
        ed.set_playing(False)                        # field last action: ve_play_pause_btn
        ed.idle(r.uniform(0.3, 1.0))
    ed.seek_to(0.8)                                  # play into the end, where audio decoders drain
    ed.set_playing(True)
    ed.idle(r.uniform(6, 10))
    ed.toggle_play()
    ed.settle(12)


# 2026-11-01 07:11 level 3 attempt 1
_4D_ONB = (('textc:continue',), ('textc:next',), ('textc:get started',), ('textc:allow',))
_4D_CLOSE = (('id:img_close',), ('id:close_btn',), ('id:btn_close',), ('id:close',))


def _4d05f9e7_ev(name):
    return rf'Event: (test_)?{name}\b'


def _4d05f9e7_tap_any(ed, sels):
    s = ed.screen()
    for sel in sels:
        if s is not None and s.has(sel):
            ed.dev.tap(*s.find(sel).center)
            return True
    return False


def _4d05f9e7_first_install_bg_remove(ed, r, slow=0):
    """pm clear (real day-0 state), cold launch, onboarding -> TaskActivity -> sample image -> real model load."""
    ed.step('first install: pm clear + cold launch')
    ed.mon.allow_death = True
    mark = ed.log_mark()
    ed.dev.sh('pm clear com.myzesty', timeout=30)
    ed.require_log(r'com\.myzesty.*clear data', 15, since=mark, why='field sessions start as a first install')
    time.sleep(1)
    ed.dev.launch()
    ed.mon.allow_death = False
    ed.require_log(r'Displayed com\.myzesty/\.MainActivity', 40, since=mark, why='first-install cold start of MainActivity')
    for _ in range(40):                              # onboarding pages at human speed until the bg-remover task shows
        s = ed.screen()
        if s is not None and s.has(('textc:try a sample image',)):
            break
        _4d05f9e7_tap_any(ed, _4D_ONB)
        time.sleep(1.5)
    ed.require_log(_4d05f9e7_ev('onboarding_task_bg_remover_show'), 10, since=mark, why='field went into the bg-remover task')
    ed.idle(r.uniform(1.5, 3))
    mark = ed.log_mark()
    ed.dev.slow_phone(slow)                          # low-end field phones run the model load + result step slowly
    ed.ui.tap(('textc:try a sample image',), timeout=10)
    ed.require_log(r'START .*PhotoActivity', 30, since=mark, why='field opened PhotoActivity from the task')
    ed.require_log(_4d05f9e7_ev('LOAD_MODEL_DONE_complete'), 60, since=mark, why='bg-remover model must really load')
    ed.require_log(_4d05f9e7_ev('process_image_done_complete'), 60, since=mark, why='bg-remover really processed the image')
    return mark


def _4d05f9e7_back_to_paywall(ed, r):
    ed.idle(r.uniform(4, 6))                         # field: ~4 s on the result before cancel
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')                       # ai_bg_remover_cancel -> MainActivity -> t3 paywall
    ed.require_log(_4d05f9e7_ev('ai_bg_remover_cancel'), 15, since=mark, why='field left the bg-remover result')
    ed.require_log(_4d05f9e7_ev('pro_screen_show_t3'), 30, since=mark, why='t3 paywall auto-shows on MainActivity')


def _4d05f9e7_close_paywall(ed, r):
    ed.idle(r.uniform(6, 13))                        # field: 6.5-13.5 s on the paywall, app in front
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    if not ed.wait_log(_4d05f9e7_ev('pro_screen_cancel_t3'), 4, since=mark):
        _4d05f9e7_tap_any(ed, _4D_CLOSE)
    ed.require_log(_4d05f9e7_ev('pro_screen_cancel_t3'), 8, since=mark, why='field closed the t3 paywall (OPPO T-0)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_1_a(ed, r):
    """OPPO CPH2579 + Nokia 5.4 + realme (FOREGROUND): first install, slow phone + slow network on the t3 paywall show/close."""
    try:
        _4d05f9e7_first_install_bg_remove(ed, r, slow=r.randint(25, 40))
        ed.dev.slow_network(r.choice((64, 128)))     # paywall prices / billing load slowly as on field networks
        _4d05f9e7_back_to_paywall(ed, r)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        _4d05f9e7_close_paywall(ed, r)
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_1_b(ed, r):
    """OnePlus8Pro 07:01/07:16/07:44 + HUAWEI 06:57 (BACKGROUND): after the paywall tap Ads Creator, Home + memory pressure as AiFeatureActivity starts."""
    try:
        _4d05f9e7_first_install_bg_remove(ed, r, slow=r.randint(20, 35))
        _4d05f9e7_back_to_paywall(ed, r)
        _4d05f9e7_close_paywall(ed, r)
        ed.idle(r.uniform(1.5, 3))
        ed.dev.slow_phone(r.randint(35, 48))
        mark = ed.log_mark()
        ed.ui.tap(('textc:ads creator',), timeout=10)  # home AI Studio card (ai_card_label) -> home_ai_ads_tap
        ed.require_log(_4d05f9e7_ev('home_ai_ads_tap'), 10, since=mark, why='field tapped a home AI tool')
        ed.wait_log(r'START .*AiFeatureActivity', 3, since=mark)
        ed.dev.key('KEYCODE_HOME')                   # field process BACKGROUND right as AiFeatureActivity starts
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.require_log(r'START .*AiFeatureActivity', 5, since=mark, why='field ended at screen_view AiFeatureActivity')
        ed.idle(r.uniform(10, 15))
        ed.dev.slow_phone(0)
        ed.dev.launch()                              # user comes back (the OnePlus pairs repeat ~3 s later)
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_1_c(ed, r):
    """HUAWEI HRY-LX1T 07:14/30 (FOREGROUND) + OnePlus8Pro 06:56 (BACKGROUND): slow phone + busy storage at onboarding_task_complete, then Home."""
    try:
        ed.dev.busy_storage(True)                    # result save / model files on slow storage
        mark = _4d05f9e7_first_install_bg_remove(ed, r, slow=r.randint(35, 48))
        ed.require_log(_4d05f9e7_ev('onboarding_task_complete'), 60, since=mark, why='field ANR at onboarding_task_complete')
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(1, 3))
        ed.dev.key('KEYCODE_HOME')                   # OnePlus 06:56 was BACKGROUND at that moment
        ed.dev.sh('am send-trim-memory com.myzesty UI_HIDDEN')
        ed.idle(r.uniform(8, 12))
        ed.dev.launch()
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


# 2026-11-01 07:17 level 3 attempt 2
_4D_TASK = 'com.myzesty.task.presentation.activity.TaskActivity'
_4D_AI = 'com.ai.myzesty.base.presentation.AiFeatureActivity'
_4D_AI_SHOWN = r'(START u0|Displayed|wm_on_resume_called).*AiFeatureActivity'
_4D_CLOSE = (('id:img_close',), ('id:close_btn',), ('id:btn_close',), ('id:close',), ('id:cancel',))


def _4d05f9e7_tap_any(ed, sels):
    s = ed.screen()
    for sel in sels:
        if s is not None and s.has(sel):
            ed.dev.tap(*s.find(sel).center)
            return True
    return False


def _4d05f9e7_day0_task(ed, r):
    """pm clear (day-0: t3 paywall + onboarding task state), cold MainActivity, then TaskActivity opened directly
    (the onboarding pages cannot be tapped in the lab). start_activity raises UIError at once if this build has no TaskActivity."""
    ed.step('day-0 install state: pm clear + cold launch + TaskActivity')
    ed.mon.allow_death = True
    mark = ed.log_mark()
    ed.dev.sh('pm clear com.myzesty', timeout=30)
    ed.require_log(r'com\.myzesty.*clear data', 15, since=mark, why='field sessions start as a first install')
    time.sleep(1)
    ed.dev.launch()
    ed.mon.allow_death = False
    ed.require_log(r'Displayed com\.myzesty/', 40, since=mark, why='first-install cold start')
    ed.idle(r.uniform(3, 5))
    ed.dev.clear_app_cache()                         # no cached bg-remover model/result: it loads for real
    mark = ed.log_mark()
    ed.start_activity(_4D_TASK, extras='', expect_crash=False)   # PREFLIGHT: needs the full 1.25.2 app on the phone
    ed.require_log(r'(onboarding_task_bg_remover_show|Displayed.*TaskActivity|wm_on_resume_called.*TaskActivity)',
                   20, since=mark, why='onboarding bg-remover task (TaskActivity)')
    ed.idle(r.uniform(1.5, 3))
    return mark


def _4d05f9e7_bg_remove(ed, r, mark, slow):
    ed.dev.slow_phone(slow)                          # low-end field phones: model load + result step on a busy CPU
    ed.require_log(r'(START u0|Displayed).*PhotoActivity', 30, since=mark, why='task opened PhotoActivity')
    ed.require_log(r'LOAD_MODEL_DONE', 60, since=mark, why='bg-remover model must really load')
    ed.require_log(r'process_image_done', 60, since=mark, why='bg-remover really processed the image')
    ed.require_log(r'onboarding_task_complete', 20, since=mark, why='HUAWEI 07:14 / OnePlus 06:56 T-0 moment')
    ed.idle(r.uniform(4, 6))


def _4d05f9e7_back_to_paywall(ed, r):
    mark = ed.log_mark()
    ed.dev.slow_network(r.choice((64, 128)))         # paywall prices / billing load slowly as on field networks
    for _ in range(3):                               # ai_bg_remover_cancel -> MainActivity (TaskActivity may sit between)
        ed.dev.key('KEYCODE_BACK')
        if ed.wait_log(r'pro_screen_show_t3', 6, since=mark):
            break
    ed.require_log(r'pro_screen_show_t3', 20, since=mark, why='t3 paywall auto-shows on MainActivity')
    ed.idle(r.uniform(6, 13))                        # field: 6.5-13.5 s on the paywall, app in front
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    if not ed.wait_log(r'pro_screen_cancel_t3', 4, since=mark):
        _4d05f9e7_tap_any(ed, _4D_CLOSE)
    ed.require_log(r'pro_screen_cancel_t3', 8, since=mark, why='field closed the t3 paywall (OPPO T-0)')


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_2_a(ed, r):
    """OPPO CPH2579 + Nokia 5.4 + realme (FOREGROUND): day-0 sample-image bg removal on a slow phone, back, t3 paywall on slow network, close."""
    try:
        mark = _4d05f9e7_day0_task(ed, r)
        ed.ui.tap('id:btn_try_sample', timeout=10)   # onboarding_task_try_sample_image
        _4d05f9e7_bg_remove(ed, r, mark, slow=r.randint(25, 40))
        _4d05f9e7_back_to_paywall(ed, r)
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_2_b(ed, r):
    """OnePlus8Pro 07:01/07:16/07:44 + HUAWEI 06:57 (BACKGROUND): after bg remover + paywall, Ads Creator opens AiFeatureActivity, Home + camera + critical memory at once."""
    try:
        mark = _4d05f9e7_day0_task(ed, r)
        ed.ui.tap('id:btn_try_sample', timeout=10)
        _4d05f9e7_bg_remove(ed, r, mark, slow=r.randint(20, 30))
        _4d05f9e7_back_to_paywall(ed, r)
        ed.dev.slow_network(0)
        ed.idle(r.uniform(1.5, 3))
        ed.dev.slow_phone(r.randint(35, 48))
        mark = ed.log_mark()
        if not ed.ui.tap(('textc:ads creator',), timeout=8):          # home AI Studio card -> home_ai_ads_tap
            ed.start_activity(_4D_AI, extras='--es ai_tool "ads"', expect_crash=False)
        ed.require_log(_4D_AI_SHOWN, 10, since=mark, why='field ended at screen_view AiFeatureActivity')
        ed.idle(r.uniform(0.1, 0.4))                 # field: process already BACKGROUND as the screen starts
        ed.dev.key('KEYCODE_HOME')
        ed.dev.sh('am start -a android.media.action.STILL_IMAGE_CAMERA')
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
        ed.idle(r.uniform(8, 14))
        ed.dev.slow_phone(0)
        ed.dev.launch()                              # the OnePlus pairs repeat ~3 s later
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_2_c(ed, r):
    """Xiaomi 24116RACCG + HUAWEI 07:14 + realme (permission path): Select a photo, Turn on, allow under memory pressure, pick, slow bg removal to onboarding_task_complete."""
    try:
        mark = _4d05f9e7_day0_task(ed, r)
        ed.ui.tap('id:btn_select_photo', timeout=10)  # onboarding_task_select_photo -> permission_popup
        ed.require_log(r'permission_popup', 10, since=mark, why='field got the media permission popup')
        ed.idle(r.uniform(2, 3))
        ed.dev.slow_phone(r.randint(30, 45))
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')   # app paused behind the system dialog (Xiaomi BACKGROUND)
        ed.grant_permissions()                       # 'Turn on' -> system Allow
        ed.require_log(r'permission_access_allow', 15, since=mark, why='field allowed media access (Xiaomi T-0)')
        ed.idle(r.uniform(2, 4))
        ed.dev.slow_phone(0)
        ed.ui.tap('id:gridrl', timeout=15)           # first photo in the picker
        _4d05f9e7_bg_remove(ed, r, mark, slow=r.randint(30, 45))
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 07:22 level 3 attempt 3
_4D_EV = r'Event: (test_)?{}\b'
_4D_AI_START = r'(START u0|Displayed|wm_on_resume_called).*AiFeatureActivity'
_4D_CLOSE = (('id:btn_close',), ('id:img_close',), ('id:close_btn',), ('id:close',), ('id:cancel',))


def _4d05f9e7_tap_first(ed, sels):
    s = ed.screen()
    for sel in sels:
        if s is not None and s.has(sel):
            ed.dev.tap(*s.find(sel).center)
            return True
    return False


def _4d05f9e7_home(ed):
    """Existing install: get to the MainActivity home with the AI Studio row (ids seen there: home_logo, ai_card_label)."""
    for _ in range(12):
        s = ed.screen()
        if s is not None and s.has(('textc:ads creator',)):
            return
        if s is not None and s.has(('id:home_logo',)):
            ed.dev.swipe(540, 1500, 540, 900, 300)    # AI Studio row sits below the CTA row
        elif s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif not _4d05f9e7_tap_first(ed, _4D_CLOSE):
            ed.dev.key('KEYCODE_BACK')
        time.sleep(1.5)
    raise UIError('home AI Studio card "Ads Creator" never showed')


def _4d05f9e7_tap_ads(ed):
    mark = ed.log_mark()
    ed.ui.tap(('textc:ads creator',), timeout=8)     # home_ai_ads_tap -> ai_tool_opened -> AiFeatureActivity
    ed.require_log(_4D_EV.format('home_ai_ads_tap'), 8, since=mark, why='field tapped the home Ads Creator card')
    ed.require_log(_4D_AI_START, 8, since=mark, why='field ended at screen_view AiFeatureActivity')
    return mark


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_3_a(ed, r):
    """OnePlus8Pro 07:16:54/58, 07:44, 07:01 + HUAWEI 06:57 (BACKGROUND): an existing install taps Ads Creator, the app goes to Home as AiFeatureActivity starts (slow CPU, critical memory), twice."""
    try:
        _4d05f9e7_home(ed)
        ed.dev.clear_app_cache()                     # AI screen assets/config load for real, not from a warm cache
        ed.dev.slow_network(r.choice((64, 128)))
        for _ in range(2):                           # the field ANRs come in pairs about 3 s apart
            ed.dev.slow_phone(r.randint(35, 48))
            _4d05f9e7_tap_ads(ed)
            ed.idle(r.uniform(0.1, 0.4))
            ed.dev.key('KEYCODE_HOME')               # field process_state BACKGROUND at that moment
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
            ed.idle(r.uniform(10, 14))               # broadcast/service timeout window while main sits idle
            ed.dev.slow_phone(0)
            ed.dev.launch()
            ed.settle(6)
            _4d05f9e7_home(ed)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_3_b(ed, r):
    """OPPO CPH2579 + Nokia 5.4 + realme (FOREGROUND): paywall opened from home on a slow network and slow CPU, closed after 6-13 s, then Ads Creator is tapped right away."""
    try:
        _4d05f9e7_home(ed)
        ed.dev.slow_network(r.choice((32, 64)))      # billing prices / paywall media load slowly as on field networks
        ed.dev.slow_phone(r.randint(30, 45))
        mark = ed.log_mark()
        ed.ui.tap(('id:home_premium_pill',), timeout=8)
        ed.require_log(_4D_EV.format(r'pro_screen_show\w*'), 15, since=mark, why='paywall shows (field pro_screen_show_t3)')
        ed.idle(r.uniform(6, 13))                    # field: 6.5-13.5 s on the paywall, app in front
        mark = ed.log_mark()
        ed.dev.key('KEYCODE_BACK')
        if not ed.wait_log(_4D_EV.format(r'pro_screen_cancel\w*'), 4, since=mark):
            _4d05f9e7_tap_first(ed, _4D_CLOSE)
        ed.require_log(_4D_EV.format(r'pro_screen_cancel\w*'), 8, since=mark, why='field closed the paywall (OPPO T-0)')
        ed.idle(r.uniform(0.5, 1.5))
        _4d05f9e7_home(ed)
        _4d05f9e7_tap_ads(ed)                        # realme: AI tool screen in front right after the paywall
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l3_3_c(ed, r):
    """HUAWEI 07:14 + OnePlus 06:56 + OPPO CPH2579 (day 0): pm clear, onboarding by ids (skip allowed), Try a sample image, real bg removal on a slow CPU, back to the t3 paywall."""
    ed.mon.allow_death = True
    mark = ed.log_mark()
    ed.dev.sh('pm clear com.myzesty', timeout=30)
    ed.require_log(r'com\.myzesty.*clear data', 15, since=mark, why='field sessions start as a first install')
    time.sleep(1)
    ed.dev.launch()
    ed.mon.allow_death = False
    ed.require_log(r'Displayed com\.myzesty/', 40, since=mark, why='first-install cold start')
    onb = (('id:btn_continue',), ('id:continueBtn',), ('id:next_button',), ('textc:CONTINUE',), ('textc:Continue',),
           ('textc:Next',), ('textc:Get Started',), ('textc:Skip',), ('textc:Allow',), ('textc:OK',))
    try:
        for i in range(30):
            if ed.wait_log(_4D_EV.format('onboarding_task_bg_remover_show'), 0.5, since=mark):
                break
            if not _4d05f9e7_tap_first(ed, onb):
                ed.log(f'    onboarding page {i}: no known button; screen = {ed.screen()!r}'[:600])
                ed.dev.swipe(900, 1200, 150, 1200, 250)   # pager pages advance by swipe
            time.sleep(2)
        ed.require_log(_4D_EV.format('onboarding_task_bg_remover_show'), 10, since=mark, why='field went into the bg-remover task')
        ed.idle(r.uniform(1.5, 3))
        mark = ed.log_mark()
        ed.dev.slow_phone(r.randint(25, 40))
        ed.ui.tap(('textc:Try a sample image',), timeout=10)
        ed.require_log(r'(START u0|Displayed).*PhotoActivity', 30, since=mark, why='task opened PhotoActivity')
        ed.require_log(_4D_EV.format('process_image_done_complete'), 90, since=mark, why='bg remover really ran')
        ed.require_log(_4D_EV.format('onboarding_task_complete'), 20, since=mark, why='HUAWEI 07:14 / OnePlus 06:56 T-0')
        ed.idle(r.uniform(4, 6))
        mark = ed.log_mark()
        ed.dev.slow_network(64)
        ed.dev.key('KEYCODE_BACK')                   # ai_bg_remover_cancel -> MainActivity -> t3 paywall
        ed.require_log(_4D_EV.format('pro_screen_show_t3'), 25, since=mark, why='t3 paywall auto-shows')
        ed.idle(r.uniform(6, 13))
        mark = ed.log_mark()
        ed.dev.key('KEYCODE_BACK')
        ed.require_log(_4D_EV.format('pro_screen_cancel_t3'), 8, since=mark, why='field closed the t3 paywall')
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.slow_network(0)


# 2026-11-01 07:29 level 4 attempt 1
_4D_ACT = r'(START u0|Displayed|wm_on_resume_called).*{}'
_4D_EV = r'Event: (test_)?{}\b'
_4D_ONB = (('text:allow',), ('textc:skip',), ('textc:get started',), ('textc:next',), ('id:btn_continue',),
           ('textc:continue',), ('text:ok',))
_4D_CLOSE = (('id:btn_close',), ('id:img_close',), ('id:close_btn',), ('id:close',))


def _4d05f9e7_dump(ed):
    s = ed.ui.dump(slow=True)                        # every window: system permission dialogs too (fast reader missed them)
    return s if s is not None and hasattr(s, 'has') else None


def _4d05f9e7_tap(ed, s, sels):
    for sel in sels:
        if s is not None and s.has(sel):
            ed.dev.tap(*s.find(sel).center)
            return True
    return False


def _4d05f9e7_paywall(s):
    return s is not None and (s.has(('id:tv_auto_cancel',)) or s.has(('id:tvPrice',)))


def _4d05f9e7_day0(ed):
    """pm clear (real first install), cold launch, walk onboarding by a full-window dump until the bg-remover task."""
    ed.step('first install: pm clear, cold launch, onboarding')
    ed.mon.allow_death = True
    mark = ed.log_mark()
    ed.dev.sh('pm clear com.myzesty', timeout=30)
    ed.require_log(r'com\.myzesty.*clear data', 15, since=mark, why='field sessions start as a first install')
    ed.dev.sh('pm grant com.myzesty android.permission.POST_NOTIFICATIONS 2>/dev/null')
    time.sleep(1)
    ed.dev.launch()
    ed.mon.allow_death = False
    ed.require_log(r'Displayed com\.myzesty/', 40, since=mark, why='first-install cold start')
    ev_on = bool(ed.wait_log(r'Event: ', 8, since=mark))
    ed.log(f'    analytics Event lines in logcat: {ev_on}')
    unknown = 0
    for i in range(45):
        if ed.wait_log(_4D_ACT.format('TaskActivity'), 0.3, since=mark):
            break
        s = _4d05f9e7_dump(ed)
        if s is not None and (s.has(('id:tv_skip',)) or s.has(('textc:sample',))):
            break                                    # bg-remover task screen
        if _4d05f9e7_paywall(s):
            _4d05f9e7_tap(ed, s, _4D_CLOSE) or ed.dev.key('KEYCODE_BACK')
        elif _4d05f9e7_tap(ed, s, _4D_ONB):
            unknown = 0
        else:
            unknown += 1
            ed.log(f'    onboarding page {i} unknown:\n{s.summary()[:1500] if s else "no dump"}')
            if unknown >= 3:
                raise UIError('onboarding page with no known button (see dump above)')
            ed.dev.swipe(900, 1200, 150, 1200, 250)
        time.sleep(1.5)
    ed.require_log(_4D_ACT.format('TaskActivity'), 10, since=mark, why='field went into the bg-remover task (TaskActivity)')
    if ev_on:
        ed.require_log(_4D_EV.format('onboarding_task_bg_remover_show'), 5, since=mark, why='bg-remover task shown')
    ed.idle(1.5)
    return ev_on


def _4d05f9e7_sample(ed, ev_on, slow):
    """'Try a sample image' -> PhotoActivity -> real model load + processing on a slow CPU."""
    mark = ed.log_mark()
    ed.dev.slow_phone(slow)
    if not _4d05f9e7_tap(ed, _4d05f9e7_dump(ed), (('textc:sample',), ('id:btn_try_sample',))):
        raise UIError('"Try a sample image" not on the bg-remover task')
    ed.require_log(_4D_ACT.format('PhotoActivity'), 30, since=mark, why='task opened PhotoActivity')
    return mark


def _4d05f9e7_done(ed, ev_on, mark):
    if ev_on:
        ed.require_log(_4D_EV.format('LOAD_MODEL_DONE_complete'), 60, since=mark, why='model really loaded')
        ed.require_log(_4D_EV.format('process_image_done_complete'), 60, since=mark, why='image really processed')
        ed.require_log(_4D_EV.format('onboarding_task_complete'), 20, since=mark, why='HUAWEI 07:14 / OnePlus 06:56 T-0')
    else:
        ed.idle(15)                                  # no analytics in logcat: give the field 0.6-1.4 s load + 3.5-5.5 s run


def _4d05f9e7_to_paywall(ed, ev_on):
    """ai_bg_remover_cancel -> MainActivity -> t3 paywall auto-shows."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    for _ in range(20):
        s = _4d05f9e7_dump(ed)
        if _4d05f9e7_paywall(s) or (ev_on and ed.wait_log(_4D_EV.format(r'pro_screen_show_t\d'), 0.2, since=mark)):
            break
        if not ed.wait_log(_4D_ACT.format('MainActivity'), 0.2, since=mark):
            ed.dev.key('KEYCODE_BACK')               # still on PhotoActivity / discard dialog
        time.sleep(1)
    ed.require_log(_4D_ACT.format('MainActivity'), 5, since=mark, why='back on MainActivity after the bg remover')
    if ev_on:
        ed.require_log(_4D_EV.format(r'pro_screen_show_t3'), 5, since=mark, why='t3 paywall auto-shows')
    elif not _4d05f9e7_paywall(_4d05f9e7_dump(ed)):
        raise UIError('t3 paywall did not show on MainActivity')


def _4d05f9e7_close(ed, ev_on):
    mark = ed.log_mark()
    if not _4d05f9e7_tap(ed, _4d05f9e7_dump(ed), _4D_CLOSE):
        ed.dev.key('KEYCODE_BACK')
    if ev_on:
        ed.require_log(_4D_EV.format(r'pro_screen_cancel_t\d'), 8, since=mark, why='field closed the t3 paywall')


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l4_1_a(ed, r):
    """OPPO CPH2579 + Nokia 5.4 + realme (FOREGROUND): day-0 sample bg removal, back, t3 paywall closed at once, then reopened/closed in a fast storm."""
    try:
        ev_on = _4d05f9e7_day0(ed)
        _4d05f9e7_done(ed, ev_on, _4d05f9e7_sample(ed, ev_on, r.randint(25, 40)))
        ed.idle(r.uniform(3, 5))
        ed.dev.slow_phone(r.randint(40, 48))         # paywall built on a busy low-end CPU
        _4d05f9e7_to_paywall(ed, ev_on)
        ed.idle(r.uniform(0.1, 0.6))                 # Nokia T-0 = show, OPPO T-0 = close: close while it is still building
        _4d05f9e7_close(ed, ev_on)
        for k in range(6):                           # storm: the same sheet shown and cancelled over and over
            ed.step(f'paywall reopen/close storm {k + 1}/6')
            mark = ed.log_mark()
            ed.ui.tap(('id:home_premium_pill',), timeout=5)
            if ev_on:
                ed.wait_log(_4D_EV.format(r'pro_screen_show_t\d'), 6, since=mark)
            ed.idle(r.uniform(0.05, 0.5))
            _4d05f9e7_close(ed, False)
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l4_1_b(ed, r):
    """HUAWEI 07:14/30 + OnePlus 06:56 + OPPO CPH2591 (bg-remover result): key input queued all through model load and result step on a slow CPU."""
    try:
        ev_on = _4d05f9e7_day0(ed)
        mark = _4d05f9e7_sample(ed, ev_on, r.randint(40, 48))
        if ev_on:
            ed.require_log(_4D_EV.format('LOAD_MODEL_start'), 30, since=mark, why='model load starts (CPH2591 window)')
        end = time.time() + 25
        while time.time() < end:                     # input waits on main exactly while the model/result run
            ed.dev.key('KEYCODE_SHIFT_LEFT')         # no-op key: an input-dispatch timeout if main is blocked
            time.sleep(r.uniform(0.1, 0.3))
            if ev_on and ed.wait_log(_4D_EV.format('onboarding_task_complete'), 0.05, since=mark):
                break
        _4d05f9e7_done(ed, ev_on, mark)
        ed.settle(r.uniform(7, 10))                  # field ANR recorded 6.6-7.3 s after process_image_done
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_l4_1_c(ed, r):
    """OnePlus8Pro 07:16:54/58, 07:44, 07:01 + HUAWEI 06:57 (BACKGROUND): Ads Creator tapped, Home the moment AiFeatureActivity starts, 4 times."""
    try:
        ev_on = _4d05f9e7_day0(ed)
        _4d05f9e7_tap(ed, _4d05f9e7_dump(ed), (('id:tv_skip',),))   # skip the task to reach home
        for _ in range(15):
            s = _4d05f9e7_dump(ed)
            if s is not None and s.has(('textc:ads creator',)):
                break
            if _4d05f9e7_paywall(s):
                _4d05f9e7_tap(ed, s, _4D_CLOSE) or ed.dev.key('KEYCODE_BACK')
            elif s is not None and s.has(('id:home_logo',)):
                ed.dev.swipe(540, 1500, 540, 900, 300)   # AI Studio row sits below the CTA row
            time.sleep(1.5)
        for k in range(4):                           # field ANRs come in pairs ~3 s apart
            ed.step(f'Ads Creator -> Home as AiFeatureActivity starts ({k + 1}/4)')
            ed.dev.slow_phone(r.randint(35, 48))
            mark = ed.log_mark()
            ed.ui.tap(('textc:ads creator',), timeout=10)
            ed.require_log(r'START u0.*AiFeatureActivity', 5, since=mark, why='field ended at screen_view AiFeatureActivity')
            if ev_on:
                ed.require_log(_4D_EV.format('home_ai_ads_tap'), 3, since=mark, why='field tapped the home AI tool')
            ed.idle(r.uniform(0.0, 0.4))
            ed.dev.key('KEYCODE_HOME')               # process BACKGROUND right as the screen starts
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_CRITICAL')
            ed.idle(r.uniform(3, 6))
            ed.dev.slow_phone(0)
            ed.dev.launch()
            ed.idle(2)
            ed.dev.key('KEYCODE_BACK')               # AiFeatureActivity -> home for the next round
            ed.idle(r.uniform(1, 2))
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 07:31 level 4 attempt 2
_4D_SEEK = r'VideoPlayer::seek requested'


def _4d05f9e7_seek_bursts(ed, r, bursts):
    """Xiaomi 21091116UI: bursts of 2-14 scrubs with ~0.1-1.5 s gaps (gen 165..194 in 5 s)."""
    for _ in range(bursts):
        ed.seek_storm(r.randint(2, 6), min_ms=30, max_ms=120, pause=(0, 0.05))
        ed.idle(r.uniform(0.1, 0.4))


def _4d05f9e7_back_save(ed, r, why):
    """Hardware back in PlayerActivity (videoeditor_backcalled) -> saveProject -> MsgSaveDraft while seeks are in flight."""
    mark = ed.log_mark()
    ed.dev.key('KEYCODE_BACK')
    ed.require_log(r'MsgSaveDraft', 10, since=mark, why=why)
    ed.settle(r.uniform(6, 9))                        # the input/late-ANR window right after MsgSaveDraft


@scenario('nightshift')
def ns_4d05f9e7_l4_2_a(ed, r):
    """Xiaomi 21091116UI (FOREGROUND, PlayerActivity): freeze on, seek bursts on a slow phone, back in the last burst -> MsgSaveDraft under the edit lease."""
    try:
        ed.set_playing(False)
        mark = ed.log_mark()
        ed.freeze()                                   # field: MsgFreezeLoader / MsgActivateFreeze before the seeks
        ed.require_log(r'MsgActivateFreeze|MsgFreezeLoader', 15, since=mark, why='field had a freeze item active')
        ed.main_nav()
        ed.dev.slow_phone(r.randint(30, 45))          # low-end Xiaomi: lockContextForEdit waits 181-450 ms
        mark = ed.log_mark()
        _4d05f9e7_seek_bursts(ed, r, r.randint(6, 10))
        ed.require_log(_4D_SEEK, 5, since=mark, why='field seek bursts after the freeze')
        ed.seek_swipe(r.uniform(-0.8, 0.8), r.randint(30, 80))   # last scrub still decoding as back lands
        _4d05f9e7_back_save(ed, r, 'back must save the draft as in the field (MsgSaveDraft at T-0)')
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift')
def ns_4d05f9e7_l4_2_b(ed, r):
    """vivo V2207 (FOREGROUND, PlayerActivity): playback of a long clip with audio on a starved CPU + slow storage, play/pause storm."""
    ed.leave_editor()
    ed.open_fixture('6e2486dd')                       # ~35 s clip with AAC audio
    try:
        ed.dev.busy_storage(True)                     # audio decoder runs dry (field: null frames, underfill)
        ed.dev.slow_phone(r.randint(38, 48))          # field: render_current_frames 457 ms
        mark = ed.log_mark()
        ed.set_playing(True)
        ed.require_log(r'MsgResumePlaying', 10, since=mark, why='field was playing (ve_play_pause_btn)')
        ed.idle(r.uniform(3, 5))
        for _ in range(r.randint(10, 18)):            # field last action: ve_play_pause_btn while the engine stalls
            ed.ui.tap_cached('id:play')
            ed.idle(r.uniform(0.15, 0.6))
            if r.random() < 0.3:
                ed.seek_swipe(r.uniform(-0.6, 0.6), r.randint(40, 120))
        ed.set_playing(True)
        ed.idle(r.uniform(2, 4))
        ed.ui.tap_cached('id:play')
        ed.settle(10)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)


@scenario('nightshift')
def ns_4d05f9e7_l4_2_c(ed, r):
    """Xiaomi 21091116UI (FOREGROUND): back pressed within ~50 ms of a scrub storm while playing, reopen and repeat 4x (save-draft vs. seek/render race)."""
    try:
        for i in range(4):
            ed.step(f'back-during-seek cycle {i + 1}/4')
            ed.set_playing(r.random() < 0.5)
            ed.dev.slow_phone(r.randint(30, 45))
            mark = ed.log_mark()
            ed.seek_storm(r.randint(15, 25), min_ms=30, max_ms=100, pause=(0, 0.03))
            ed.require_log(_4D_SEEK, 5, since=mark, why='seek storm reached the engine')
            _4d05f9e7_back_save(ed, r, 'back right after the seeks saved the draft')
            ed.dev.slow_phone(0)
            ed.open_draft()
            ed.idle(r.uniform(1.5, 3))
    finally:
        ed.dev.slow_phone(0)
