# Night Shift auto repros for 2bc43cd6d24a25e5305f8167703618a8~a30bf155


# 2026-11-01 02:29 level 3 attempt 1
def _ga30bf15_overlay_path(ed, mark):
    """Path of the layer-1 overlay, read from the fixture's own MsgAddVideo line."""
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .*ga30bf15_ovl', 20, since=mark,
                          why='fixture must restore its layer-1 overlay video')
    return line.split('path: ', 1)[1].rsplit(', start_time', 1)[0].strip()


def _ga30bf15_reopen_and_check(ed, mark):
    """Reopen the draft from My Projects; the restore re-adds the dead overlay and sets its volume."""
    ed.open_fixture('ga30bf15')
    ed.require_log(r'MsgAddVideo: media_layer 0 path:', 20, since=mark, why='layer 0 restored (checkpoint 2)')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: .*ga30bf15_ovl', 20, since=mark, why='overlay re-added (checkpoint 3)')
    ed.require_log(r'add_video Failed to create Visual Media Object.*ga30bf15_ovl', 10, since=mark,
                   why='overlay file must fail to open (checkpoint 4)')
    ed.require_log(r'JNICalled_updateOverlayVideoVolume vol: \d+, layer: 1', 10, since=mark,
                   why='restore sends overlay volume for layer 1 (checkpoint 5)')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_1_a(ed, r):
    """Crashlytics ga30bf15, instances 06:32:21/06:32:52/06:33:57: overlay's download file moved away (VidMate), draft reopened."""
    mark = ed.log_mark()
    ed.open_fixture('ga30bf15')
    path = _ga30bf15_overlay_path(ed, mark)
    ed.idle(2)
    ed.leave_editor()
    hidden = path + '.ns_moved'
    ed.dev.sh(f"mv '{path}' '{hidden}'")
    try:
        ed.idle(1)
        _ga30bf15_reopen_and_check(ed, ed.log_mark())
    finally:
        ed.dev.sh(f"mv '{hidden}' '{path}'")


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_1_b(ed, r):
    """Crashlytics ga30bf15, instances 06:32:21/06:32:52/06:33:57: Android 14+ limited media access (video access revoked), draft reopened."""
    mark = ed.log_mark()
    ed.open_fixture('ga30bf15')
    _ga30bf15_overlay_path(ed, mark)
    ed.idle(2)
    ed.leave_editor()
    ed.mon.allow_death = True                        # pm revoke kills the process, as Android does
    pkg = 'com.myzesty'
    try:
        ed.dev.sh(f'pm revoke {pkg} android.permission.READ_MEDIA_VIDEO')
        ed.dev.sh(f'pm revoke {pkg} android.permission.READ_EXTERNAL_STORAGE')
        ed.dev.sh(f'pm grant {pkg} android.permission.READ_MEDIA_VISUAL_USER_SELECTED')
        ed.idle(2)
        ed.dev.launch()
        ed.idle(4)
        ed.mon.allow_death = False
        _ga30bf15_reopen_and_check(ed, ed.log_mark())
    finally:
        ed.mon.allow_death = False
        ed.dev.sh(f'pm grant {pkg} android.permission.READ_MEDIA_VIDEO')
        ed.dev.sh(f'pm grant {pkg} android.permission.READ_EXTERNAL_STORAGE')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_1_c(ed, r):
    """Crashlytics ga30bf15, instances 06:32:21/06:32:52/06:33:57: overlay file left as a broken partial download, cold start under memory pressure, reopen."""
    mark = ed.log_mark()
    ed.open_fixture('ga30bf15')
    path = _ga30bf15_overlay_path(ed, mark)
    ed.idle(2)
    ed.leave_editor()
    hidden = path + '.ns_moved'
    ed.dev.sh(f"mv '{path}' '{hidden}' && head -c {r.randint(2048, 16384)} '{hidden}' > '{path}'")
    try:
        ed.kill_bg()                                 # system reclaims the app; the user comes back cold
        ed.dev.launch()
        ed.idle(4)
        ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        _ga30bf15_reopen_and_check(ed, ed.log_mark())
    finally:
        ed.dev.sh(f"mv '{hidden}' '{path}'")


# 2026-11-01 02:43 level 3 attempt 2
def _ga30bf15_check_restore(ed, mark, ovl=r'.*transcoding-'):
    """Checkpoints 2-5: layer 0 restored, overlay re-added by the restore, add fails, overlay volume still sent."""
    ed.require_log(r'MsgAddVideo: media_layer 0 path:', 20, since=mark, why='layer 0 restored (checkpoint 2)')
    ed.require_log(r've_draft_media_applied_complete', 20, since=mark, why='draft applied (checkpoint 2)')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: ' + ovl, 20, since=mark,
                   why='restore re-adds the layer-1 overlay (checkpoint 3)')
    ed.require_log(r'add_video Failed to create Visual Media Object', 10, since=mark,
                   why='overlay file must fail to open (checkpoint 4)')
    ed.require_log(r'JNICalled_updateOverlayVideoVolume vol: \d+, layer: 1', 10, since=mark,
                   why='restore still sends the layer-1 overlay volume (checkpoint 5)')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_2_a(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: the overlay's stored file is gone (outputs/ hidden), draft reopened -> SIGSEGV getAudioOverlayId."""
    ed.dev.clear_app_files('outputs')                # overlay is stored as outputs/transcoding-*.mp4; layer 0 lives in DCIM
    mark = ed.log_mark()
    ed.open_fixture('ga30bf15')
    _ga30bf15_check_restore(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_2_b(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: the overlay file is a truncated/unreadable partial, draft reopened -> SIGSEGV getAudioOverlayId."""
    mark = ed.log_mark()
    ed.open_fixture('ga30bf15')
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .*transcoding-', 20, since=mark,
                          why='fixture must restore its layer-1 overlay')
    path = line.split('path: ', 1)[1].rsplit(', start_time', 1)[0].strip()
    ed.idle(2)
    ed.leave_editor()
    keep = path + '.ns_moved'
    ed.dev.sh(f"run-as com.myzesty sh -c \"mv '{path}' '{keep}' && head -c {r.randint(2048, 16384)} '{keep}' > '{path}'\"")
    try:
        ed.idle(1)
        mark = ed.log_mark()
        ed.open_fixture('ga30bf15')
        _ga30bf15_check_restore(ed, mark, ovl=r'.*' + path.rsplit('/', 1)[-1].replace('.', r'\.'))
    finally:
        ed.dev.sh(f"run-as com.myzesty sh -c \"mv '{keep}' '{path}'\"")


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l3_2_c(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: overlay file gone + cold start after the system reclaimed the app, memory pressure, slow low-end CPU."""
    ed.dev.clear_app_files('outputs')
    ed.kill_bg()                                     # the user comes back to a cold app, as on the LAVA phone
    ed.dev.launch()
    ed.idle(4)
    ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
    mark = ed.log_mark()
    ed.dev.slow_phone(r.randint(20, 35))
    try:
        ed.open_fixture('ga30bf15')
        _ga30bf15_check_restore(ed, mark)
    finally:
        ed.dev.slow_phone(0)


# 2026-11-01 02:48 level 3 attempt 3
def _ga30bf15_q(p):
    return "'" + p.replace("'", "'\\''") + "'"


def _ga30bf15_mv(ed, a, b):
    """Move a file as the field's cleaner did (run-as for the app's own files/outputs copies)."""
    pre = 'run-as com.myzesty ' if a.startswith('/data/') else ''
    ed.dev.sh(f'{pre}mv {_ga30bf15_q(a)} {_ga30bf15_q(b)} 2>/dev/null')


def _ga30bf15_add_overlay(ed):
    """Real taps on the open test draft: Overlay tab -> Add -> newest ~15 s clip -> confirm. Returns the saved overlay path."""
    ed.set_playing(False)
    ed.main_nav()
    ed.dev.fresh_video('ns_ovl_ga30', duration_s=15)       # field overlay range 0..14977000 us
    mark = ed.log_mark()
    ed.tap_tool('overlay')                                 # ve_tab_overlay
    s = ed.ui.wait(('desc:ve_btn_overlay_add', 'id:gridrl', 'id:mediaList'), timeout=10)
    if s is not None and s.has('desc:ve_btn_overlay_add'):
        ed.ui.tap('desc:ve_btn_overlay_add', timeout=5)    # Overlay.ADD -> pickMediaOverlay
        s = ed.ui.wait(('id:gridrl', 'id:mediaList'), timeout=20)
    if s is None:
        raise UIError('overlay picker did not open')
    if s.has('id:video_tab'):
        ed.ui.tap('id:video_tab', timeout=5)
        s = ed.ui.wait('id:gridrl', timeout=10) or s
    ed.dev.tap(*s.find_all('id:gridrl')[0].center)
    ed._picker_confirm()
    line = ed.require_log(r'MsgAddVideo: media_layer 1 path: .* start_time', 120, since=mark,
                          why='video overlay added on layer 1 (OverlayManager.addOverlay)')
    ed.require_log(r'MsgUpdateOverlayVideoVolume level \S+ layer 1 mediaId 0', 15, since=mark,
                   why='addOverlay -> updateVolume (the call the restore repeats)')
    ed.idle(3)
    return line.split('path: ', 1)[1].split(', start_time', 1)[0].split(' start_time', 1)[0].strip()


def _ga30bf15_reopen(ed, blip=False, wait=12):
    """My Projects -> TRIGGER: tap the project; restore re-adds the dead overlay and still sets its volume."""
    for _ in range(10):
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
    ed.step('TRIGGER: tap the project in My Projects (draft restore)')
    mark = ed.log_mark()
    ed.ui.tap(T.DRAFT_FIRST, timeout=10)
    ed.require_log(r've_draft_project_start', 30, since=mark, why='checkpoint 1: draft opened from My Projects')
    ed.require_log(r'MsgAddVideo: media_layer 0 path:', 90, since=mark, why='checkpoint 2: layer 0 restored')
    if blip:                                               # field ve_on_pause/ve_on_resume during the load
        ed.dev.sh('cmd statusbar expand-notifications; sleep 0.15; cmd statusbar collapse')
    ed.require_log(r'MsgAddVideo: media_layer 1 path:', 90, since=mark, why='checkpoint 3: restore re-adds the overlay')
    ed.require_log(r'add_video Failed to create Visual Media Object|Cannot open file', 15, since=mark,
                   why='checkpoint 4: overlay file cannot be opened, layer 1 stays empty')
    ed.require_log(r'JNICalled_updateOverlayVideoVolume vol: \d+, layer: 1', 15, since=mark,
                   why='checkpoint 5: restore still sends the layer-1 overlay volume')
    ed.idle(wait)


def _ga30bf15_run(ed, r, cold=False, slow=False):
    ed.dev.restore_env()
    ed.snapshot_app_db('ga30bf15_pre')                     # the test draft gets its pre-overlay state back afterwards
    p = None
    try:
        p = _ga30bf15_add_overlay(ed)
        mark = ed.log_mark()
        ed.leave_editor()                                  # draft saved with the overlay
        ed.require_log(r'MsgSaveDraft', 15, since=mark, why='draft with the overlay saved')
        ed.idle(2)
        if cold:
            ed.kill_bg()                                   # the system reclaims the app; the user comes back cold
        _ga30bf15_mv(ed, p, p + '.nsgone')                 # the overlay's source file is gone (VidMate cleanup)
        if cold:
            ed.dev.launch()
            ed.idle(5)
            ed.dev.sh('am send-trim-memory com.myzesty RUNNING_LOW')
        if slow:
            ed.dev.slow_phone(r.randint(25, 40))           # LAVA LXX528-class CPU
            ed.dev.busy_storage(True)
        _ga30bf15_reopen(ed, blip=slow, wait=20 if slow else 12)
    finally:
        if slow:
            ed.dev.slow_phone(0)
            ed.dev.busy_storage(False)
        if p:
            _ga30bf15_mv(ed, p + '.nsgone', p)
        ed.restore_app_db('ga30bf15_pre')


@scenario('nightshift', 'auto')
def ns_ga30bf15_l3_3_a(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: video overlay added by taps, its file removed, draft reopened from My Projects."""
    _ga30bf15_run(ed, r)


@scenario('nightshift', 'auto')
def ns_ga30bf15_l3_3_b(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: same, but the app is reclaimed in the background and reopened cold under memory pressure."""
    _ga30bf15_run(ed, r, cold=True)


@scenario('nightshift', 'auto')
def ns_ga30bf15_l3_3_c(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: cold reopen on a slow LAVA-class phone with busy storage and a pause/resume blip during load."""
    _ga30bf15_run(ed, r, cold=True, slow=True)


# 2026-11-01 02:55 level 4 attempt 1
def _ga30bf15_q(p):
    return "'" + p.replace("'", "'\\''") + "'"


def _ga30bf15_sh(ed, path, cmd):
    """Shell on the overlay's file; run-as for the app's own files/outputs transcode."""
    pre = 'run-as com.myzesty ' if path.startswith('/data/') else ''
    ed.dev.sh(f'{pre}sh -c {_ga30bf15_q(cmd)}')


def _ga30bf15_find_overlay(ed):
    """Open the draft that restores a layer-1 video overlay; return its saved path (the restore's own MsgAddVideo)."""
    mark = ed.log_mark()
    ed.open_draft()
    line = ed.wait_log(r'MsgAddVideo: media_layer 1 path: ', 15, since=mark)
    if not line:
        ed.leave_editor()
        mark = ed.log_mark()
        ed.open_fixture('ga30bf15')
        line = ed.require_log(r'MsgAddVideo: media_layer 1 path: ', 20, since=mark,
                              why='draft must restore a saved layer-1 overlay video')
    ed.idle(2)
    ed.leave_editor()                                # saved again with the overlay, as the field draft was
    return line.split('path: ', 1)[1].rsplit(', start_time', 1)[0].strip()


def _ga30bf15_reopen(ed, path, blip=False):
    """TRIGGER: reopen from My Projects; restore re-adds the dead overlay, fails, still sets its volume."""
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'MsgAddVideo: media_layer 0 path:', 30, since=mark, why='checkpoint 2: layer 0 restored')
    if blip:                                         # field ve_on_pause/ve_on_resume pair during the load
        ed.dev.sh('cmd statusbar expand-notifications; sleep 0.12; cmd statusbar collapse')
    ed.require_log(r'draft_media_applied_complete', 30, since=mark, why='checkpoint 2: draft applied')
    name = path.rsplit('/', 1)[-1].replace('.', r'\.')
    ed.require_log(r'MsgAddVideo: media_layer 1 path: .*' + name, 20, since=mark,
                   why='checkpoint 3: restore re-adds the saved overlay')
    ed.require_log(r'add_video Failed to create Visual Media Object', 10, since=mark,
                   why='checkpoint 4: overlay file cannot be opened, layer 1 stays empty')
    ed.require_log(r'JNICalled_updateOverlayVideoVolume vol: \d+, layer: 1', 10, since=mark,
                   why='checkpoint 5: restore still sends the layer-1 overlay volume')
    ed.idle(4)


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l4_1_a(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: overlay's saved file removed, draft reopened from My Projects (pause/resume blip in the load)."""
    path = _ga30bf15_find_overlay(ed)
    _ga30bf15_sh(ed, path, f'mv {_ga30bf15_q(path)} {_ga30bf15_q(path + ".nsgone")}')
    try:
        ed.idle(1)
        _ga30bf15_reopen(ed, path, blip=True)
    finally:
        _ga30bf15_sh(ed, path, f'mv {_ga30bf15_q(path + ".nsgone")} {_ga30bf15_q(path)}')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l4_1_b(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: overlay file present but a truncated partial (cannot open), reopened on a slow phone."""
    path = _ga30bf15_find_overlay(ed)
    keep = path + '.nskeep'
    _ga30bf15_sh(ed, path, f'mv {_ga30bf15_q(path)} {_ga30bf15_q(keep)} && '
                           f'head -c {r.randint(2048, 16384)} {_ga30bf15_q(keep)} > {_ga30bf15_q(path)}')
    try:
        ed.dev.slow_phone(r.randint(20, 35))         # LAVA LXX528-class CPU right before the reopen
        _ga30bf15_reopen(ed, path, blip=True)
    finally:
        ed.dev.slow_phone(0)
        _ga30bf15_sh(ed, path, f'mv {_ga30bf15_q(keep)} {_ga30bf15_q(path)}')


@scenario('nightshift', 'auto', 'nodraft')
def ns_ga30bf15_l4_1_c(ed, r):
    """Instances 06:32:21/06:32:52/06:33:57: overlay file unreadable (mode 000), draft reopened back-to-back like the 3 crashes in 96 s."""
    path = _ga30bf15_find_overlay(ed)
    _ga30bf15_sh(ed, path, f'chmod 000 {_ga30bf15_q(path)}')
    try:
        for _ in range(3):                           # the field user reopened the same draft again and again
            _ga30bf15_reopen(ed, path, blip=r.random() < 0.5)
            ed.leave_editor()
            ed.idle(r.uniform(0.5, 2))
    finally:
        _ga30bf15_sh(ed, path, f'chmod 600 {_ga30bf15_q(path)}')
