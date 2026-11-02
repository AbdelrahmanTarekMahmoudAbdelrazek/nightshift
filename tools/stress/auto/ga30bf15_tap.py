# Night Shift tap repros for 2bc43cd6d24a25e5305f8167703618a8~a30bf155 (from the engine repro + full field log)


# 2026-11-01 02:11 attempt 1
def _q(p):
    return "'" + p.replace("'", "'\\''") + "'"


def _overlay_path(line):
    """Overlay source path from the engine's 'MsgAddVideo: media_layer 1 path: <p> start_time: ...' line."""
    return line.split('path: ', 1)[1].split(' start_time', 1)[0].strip()


def _hide(ed, p):
    """The field's VidMate download vanished: make the saved overlay path unopenable (reversible move)."""
    pre = 'run-as com.myzesty ' if p.startswith('/data/') else ''
    ed.dev.sh(f'{pre}mv {_q(p)} {_q(p + ".nsgone")}')


def _unhide(ed, p):
    pre = 'run-as com.myzesty ' if p.startswith('/data/') else ''
    ed.dev.sh(f'{pre}mv {_q(p + ".nsgone")} {_q(p)} 2>/dev/null')


def _reopen_tap(ed, p, wait=12):
    """TRIGGER: tap the project in My Projects -> draft restore re-adds the layer-1 overlay -> volume -> SIGSEGV."""
    ed.step('reopen the project from My Projects (draft restore re-adds the missing overlay)')
    if not ed.ui.tap(T.DRAFT_FIRST, timeout=15):
        raise UIError('first project thumbnail (ve_thumb_draft_first) not found')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: .*' + re.escape(p.rsplit('/', 1)[-1][:20]), timeout=40,
                   why='restore re-adds the saved layer-1 overlay (field T-0.03 s)')
    ed.require_log(r'add_video Failed to create Visual Media Object|Cannot open file', timeout=10,
                   why='overlay file cannot be opened, layer 1 stays empty')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=10,
                   why='restore still sends the overlay volume -> getAudioOverlayId(1,0)')
    ed.idle(wait)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_1_a(ed, r):
    """FULL: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: new project + video overlay by taps, overlay file vanishes, reopen draft."""
    ed.dev.restore_env()
    ed.fixture_begin()
    ed.create_draft()                                    # own project: never pollute the shared test draft
    ed.require_log(r'MsgAddVideo: media_layer 0', timeout=40, why='new project base clip on layer 0')
    ed.set_playing(False)
    ed.main_nav()
    ed.dev.fresh_video('ovl', duration_s=15)             # newest in the gallery = first tile of the picker
    ed.tap_tool('overlay')                               # ve_tab_overlay
    ed.ui.tap('desc:ve_btn_overlay_add', timeout=5)      # panel's Add (some builds open the picker directly)
    s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is None:
        raise UIError('overlay gallery did not open')
    if s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed._picker_confirm()
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', timeout=60,
                          why='video overlay added on layer 1 (OverlayManager.addOverlay)')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=15,
                   why='overlay volume sent right after the add')
    p = _overlay_path(line)
    ed.idle(3)
    ed.save_fixture('ga30bf15', f'project with a layer-1 video overlay at {p}')   # leaves editor: draft saved
    _hide(ed, p)
    try:
        _reopen_tap(ed, p)
    finally:
        _unhide(ed, p)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_1_b(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: overlay fixture opened by lab, file hidden, reopen by real tap."""
    ed.dev.restore_env()
    ed.open_fixture('ga30bf15')                                                  # HYBRID
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', timeout=40,
                          why='fixture restores its layer-1 overlay (file still present)')
    p = _overlay_path(line)
    ed.idle(3)
    ed.leave_editor()                                    # saved -> newest in My Projects
    _hide(ed, p)                                                                 # HYBRID
    try:
        _reopen_tap(ed, p)
    finally:
        _unhide(ed, p)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_1_c(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: as b on a slow low-end phone (LAVA LXX528) with busy storage."""
    ed.dev.restore_env()
    ed.open_fixture('ga30bf15')                                                  # HYBRID
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', timeout=40,
                          why='fixture restores its layer-1 overlay (file still present)')
    p = _overlay_path(line)
    ed.idle(3)
    ed.leave_editor()
    _hide(ed, p)                                                                 # HYBRID
    ed.dev.slow_phone(r.randint(25, 40))
    ed.dev.busy_storage(True)
    try:
        _reopen_tap(ed, p, wait=20)
    finally:
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)
        _unhide(ed, p)


# 2026-11-01 02:15 attempt 2
def _q(p):
    return "'" + p.replace("'", "'\\''") + "'"


def _mv(ed, a, b):
    pre = 'run-as com.myzesty ' if a.startswith('/data/') else ''
    ed.dev.sh(f'{pre}mv {_q(a)} {_q(b)} 2>/dev/null')


def _add_video_overlay(ed):
    """Real taps: Overlay tab -> Add -> picker (newest = fresh 15 s clip) -> confirm. Returns the overlay path."""
    ed.set_playing(False)
    ed.main_nav()
    ed.dev.fresh_video('ns_ovl', duration_s=15)           # newest in the gallery = first picker tile
    mark = ed.log_mark()
    ed.tap_tool('overlay')                                # desc ve_tab_overlay
    s = ed.ui.wait(('desc:ve_btn_overlay_add', 'id:gridrl', 'id:mediaList'), timeout=10)
    if s is None:
        raise UIError('overlay tab opened neither its menu nor the picker')
    if s.has('desc:ve_btn_overlay_add'):
        ed.ui.tap('desc:ve_btn_overlay_add', timeout=5)   # AutomationTags.Overlay.ADD -> pickMediaOverlay()
        s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is None:
        raise UIError('overlay picker did not open')
    if s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed._picker_confirm()
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', timeout=90, since=mark,
                          why='overlay added on layer 1 (OverlayManager.addOverlay)')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=15, since=mark,
                   why='addOverlay -> updateVolume right after the add')
    ed.idle(3)
    return line.split('path: ', 1)[1].split(' start_time', 1)[0].strip()


def _back_out(ed):
    """Back out of the editor (the draft is saved on exit). The lab door opened it over the dev menu."""
    for _ in range(6):
        s = ed.screen()
        if s is not None and not ed.in_editor(s) and s.has(T.HOME_TO_PROJECTS + (T.DRAFT_FIRST,)):
            return
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
    raise UIError('could not leave the editor')


def _reopen_by_tap(ed, p, wait=12):
    """Real taps: (Revamp UI ->) My Projects -> first project. TRIGGER: the draft restore re-adds the missing overlay."""
    for _ in range(8):
        s = ed.screen()
        if s is not None and s.has(T.DRAFT_FIRST):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)
        ed.idle(2)
    else:
        raise UIError('My Projects (ve_thumb_draft_first) not reached')
    ed.step('TRIGGER: tap the project in My Projects (newest = the one with the overlay)')
    mark = ed.log_mark()
    ed.ui.tap(T.DRAFT_FIRST, timeout=10)
    ed.require_log(r'MsgAddVideo: media_layer 0', timeout=60, since=mark, why='restore: base clip layer 0')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: .*' + re.escape(p.rsplit('/', 1)[-1][:24]), timeout=60,
                   since=mark, why='restore re-adds the saved layer-1 overlay (field T-0.03 s)')
    ed.require_log(r'Cannot open file', timeout=10, since=mark, why='overlay file gone: add_video -1, layer 1 empty')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=10, since=mark,
                   why='restore still sends the overlay volume -> getAudioOverlayId(1,0)')
    ed.idle(wait)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_2_a(ed, r):
    """FULL: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: video overlay by taps, its file vanishes, reopen the draft by tap."""
    ed.dev.restore_env()
    ed.open_fixture('6e2486dd')                           # snapshot-restored single-clip project
    p = _add_video_overlay(ed)
    _back_out(ed)
    _mv(ed, p, p + '.nsgone')                             # the field's VidMate download is gone
    try:
        _reopen_by_tap(ed, p)
    finally:
        _mv(ed, p + '.nsgone', p)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_2_b(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: overlay by taps, new app process + file removed, reopen by tap."""
    ed.dev.restore_env()
    ed.open_fixture('6e2486dd')                                                  # HYBRID
    p = _add_video_overlay(ed)
    _back_out(ed)
    ed.idle(2)
    ed.mon.allow_death = True
    ed.dev.force_stop()                                                          # HYBRID
    _mv(ed, p, p + '.nsgone')                                                    # HYBRID
    try:
        ed.dev.launch()
        ed.idle(5)
        ed.mon.allow_death = False
        _reopen_by_tap(ed, p)
    finally:
        ed.mon.allow_death = False
        _mv(ed, p + '.nsgone', p)


@scenario('nightshift', 'auto', 'tapflow', 'nodraft')
def tf_ga30bf15_2_c(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: as b on a slow low-end phone (LAVA LXX528) with busy storage."""
    ed.dev.restore_env()
    ed.open_fixture('6e2486dd')                                                  # HYBRID
    p = _add_video_overlay(ed)
    _back_out(ed)
    ed.idle(2)
    ed.mon.allow_death = True
    ed.dev.force_stop()                                                          # HYBRID
    _mv(ed, p, p + '.nsgone')                                                    # HYBRID
    try:
        ed.dev.launch()
        ed.idle(5)
        ed.mon.allow_death = False
        ed.dev.slow_phone(r.randint(25, 40))
        ed.dev.busy_storage(True)
        _reopen_by_tap(ed, p, wait=20)
    finally:
        ed.mon.allow_death = False
        ed.dev.slow_phone(0)
        ed.dev.busy_storage(False)
        _mv(ed, p + '.nsgone', p)


# 2026-11-01 02:17 attempt 3
def _q(p):
    return "'" + p.replace("'", "'\\''") + "'"


def _mv(ed, a, b):
    pre = 'run-as com.myzesty ' if a.startswith('/data/') else ''
    ed.dev.sh(f'{pre}mv {_q(a)} {_q(b)} 2>/dev/null')


def _overlay_by_taps(ed):
    """Overlay tab -> Add -> picker (newest = fresh 15 s clip) -> confirm. Returns the saved overlay path."""
    ed.set_playing(False)
    ed.main_nav()
    ed.dev.fresh_video('ns_ovl', duration_s=15)            # field range 0..14977000 us
    mark = ed.log_mark()
    ed.tap_tool('overlay')                                 # AutomationTags OVERLAY = ve_tab_overlay
    s = ed.ui.wait(('desc:ve_btn_overlay_add', 'id:gridrl', 'id:mediaList'), timeout=10)
    if s is None:
        raise UIError('overlay tab opened neither its menu nor the picker')
    if s.has('desc:ve_btn_overlay_add'):
        ed.ui.tap('desc:ve_btn_overlay_add', timeout=5)    # pickMediaOverlay -> openGallery(OVERLAY_REQ)
        s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is None:
        raise UIError('overlay picker did not open')
    if s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed._picker_confirm()
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', timeout=120, since=mark,
                          why='overlay added on layer 1 (OverlayManager.addOverlay)')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=15, since=mark,
                   why='addOverlay -> updateVolume right after the add')
    ed.idle(3)
    return line.split('path: ', 1)[1].split(' start_time', 1)[0].strip()


def _leave_and_save(ed):
    """Back out of the editor (draft saved on exit); the lab door opened it over the dev menu."""
    mark = ed.log_mark()
    for _ in range(6):
        s = ed.screen()
        if s is not None and not ed.in_editor(s) and s.has(T.HOME_TO_PROJECTS + (T.DRAFT_FIRST,)):
            break
        ed.dev.key('KEYCODE_BACK')
        ed.idle(1.5)
    ed.require_log(r'wm_on_destroy_called: \[[\d,]+com\.video\.myzesty\.PlayerActivity', timeout=15, since=mark,
                   why='editor closed: project with the overlay saved')
    ed.idle(2)


def _reopen_by_tap(ed, p, blip=False, wait=12):
    """Revamp UI (My Projects) -> TRIGGER: tap the first project; restore re-adds the overlay whose file is gone."""
    for _ in range(10):
        s = ed.screen()
        if s is not None and s.has(T.DRAFT_FIRST):
            break
        if s is not None and s.has(T.DISMISS):
            ed.dev.tap(*s.find(T.DISMISS).center)
        elif s is not None and s.has(T.HOME_TO_PROJECTS):
            ed.dev.tap(*s.find(T.HOME_TO_PROJECTS).center)   # id btn_revamped_ui -> BaseVideoEditorActivity
        ed.idle(2)
    else:
        raise UIError('My Projects (ve_thumb_draft_first) not reached')
    ed.step('TRIGGER: tap the project in My Projects (draft restore)')
    mark = ed.log_mark()
    ed.ui.tap(T.DRAFT_FIRST, timeout=10)
    ed.require_log(r'MsgAddVideo: media_layer 0', timeout=90, since=mark, why='restore: base clip on layer 0')
    if blip:                                               # field: ve_on_pause/ve_on_resume during the draft load
        ed.dev.sh('cmd statusbar expand-notifications; sleep 0.15; cmd statusbar collapse')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: .*' + re.escape(p.rsplit('/', 1)[-1][:24]), timeout=90,
                   since=mark, why='restore re-adds the saved layer-1 overlay (field T-0.03 s)')
    ed.require_log(r'Cannot open file', timeout=15, since=mark, why='overlay file gone: add_video -1, layer 1 empty')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \d+ layer 1 mediaId 0', timeout=15, since=mark,
                   why='restore still sends the overlay volume -> getAudioOverlayId(1,0)')
    ed.idle(wait)


def _run(ed, r, fresh_process=False, slow=False):
    ed.snapshot_app_db('ga30bf15_pre')                     # test draft comes back without the overlay afterwards
    p = None
    try:
        p = _overlay_by_taps(ed)
        _leave_and_save(ed)
        if fresh_process:
            ed.mon.allow_death = True
            ed.dev.force_stop()                                                  # HYBRID
        _mv(ed, p, p + '.nsgone')                                                # HYBRID (VidMate file vanished)
        if fresh_process:
            ed.dev.launch()
            ed.idle(5)
            ed.mon.allow_death = False
        if slow:
            ed.dev.slow_phone(r.randint(25, 40))
            ed.dev.busy_storage(True)
        _reopen_by_tap(ed, p, blip=slow, wait=20 if slow else 12)
    finally:
        ed.mon.allow_death = False
        if slow:
            ed.dev.slow_phone(0)
            ed.dev.busy_storage(False)
        if p:
            _mv(ed, p + '.nsgone', p)
        ed.restore_app_db('ga30bf15_pre')


@scenario('nightshift', 'auto', 'tapflow')
def tf_ga30bf15_3_a(ed, r):
    """FULL: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: video overlay by taps, its file vanishes, reopen the draft by tap."""
    ed.dev.restore_env()
    _run(ed, r)


@scenario('nightshift', 'auto', 'tapflow')
def tf_ga30bf15_3_b(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: overlay by taps, new app process + file removed, reopen by tap."""
    ed.dev.restore_env()
    _run(ed, r, fresh_process=True)


@scenario('nightshift', 'auto', 'tapflow')
def tf_ga30bf15_3_c(ed, r):
    """HYBRID: Crashlytics [libMYJNILIB26.so] getAudioOverlayId: as b on a slow LAVA-class phone, busy storage, pause/resume blip on load."""
    ed.dev.restore_env()
    _run(ed, r, fresh_process=True, slow=True)
