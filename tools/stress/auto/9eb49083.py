# Night Shift auto repros for 9eb490831317f4944e7f1f9d3374fda0


# 2026-10-26 03:37 level 2 attempt 1
_9EB_PHOTO = r'Displayed com\.myzesty/com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_bg_removed(ed, choose_bg=True):
    """Field T-63..T-20: home -> AI background remover -> refuse media permission -> sample image -> Standard -> done."""
    ed.open_fixture('9eb49083')
    ed.leave_editor()
    mark = ed.log_mark()
    ed.step('bg remover entry -> sample image (permission refused)')
    _9eb49083_soft_tap(ed, ('textc:remove bg', 'textc:background remover', 'textc:remove background'), 10)
    _9eb49083_soft_tap(ed, ('textc:select photo', 'textc:choose photo'), 5)
    _9eb49083_soft_tap(ed, ('text:Cancel', 'textc:not now', "textc:don't allow"), 5)   # permission_pop_cancel
    _9eb49083_soft_tap(ed, ('textc:sample image', 'textc:try sample'), 8)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    ed.idle(1.8)
    ed.step('standard AI background remover')
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)                                      # ai_bg_remover_standard_btn
    ed.ui.wait(('textc:start editing', 'textc:choose background') + _9EB_ERASER, timeout=60)
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:start editing',), 5)
    if choose_bg:
        ed.idle(2.5)
        _9eb49083_soft_tap(ed, ('textc:choose background', 'textc:background'), 5)
        ed.idle(2.5)
        _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 5)                          # start_done -> pe_removebg_complete
    ed.ui.wait(_9EB_ERASER, timeout=20)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): standard remover, Choose Background, Done, ~20 s idle, Eraser -> JNI_GetIntValueFromFilter."""
    _9eb49083_bg_removed(ed, choose_bg=True)
    ed.idle(r.uniform(18, 22))                         # field: 20.8 s with nothing logged, no pause/recreate
    ed.step('tap Eraser (field trigger)')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_b(ed, r):
    """Instance 1/1, short path: Eraser tapped right after the removal result shows (no Choose Background step)."""
    _9eb49083_bg_removed(ed, choose_bg=False)
    ed.idle(r.uniform(1, 3))
    ed.step('tap Eraser soon after removal')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    ed.settle(8)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_1_c(ed, r):
    """Instance 1/1, field path then the eraser opened, closed and reopened at human speed (filter value re-read)."""
    _9eb49083_bg_removed(ed, choose_bg=True)
    ed.idle(r.uniform(15, 20))
    for k in range(3):
        ed.step(f'Eraser open {k + 1}/3')
        ed.ui.tap(_9EB_ERASER, timeout=10)
        ed.idle(r.uniform(1.5, 3))
        if not _9eb49083_soft_tap(ed, ('textc:restore', 'textc:brush'), 3):
            ed.dev.key('KEYCODE_BACK')                 # leave the eraser panel, stay on PhotoActivity
        ed.idle(r.uniform(1.5, 3))
    ed.settle(8)


# 2026-10-26 03:42 level 2 attempt 2
_9EB_PHOTO = r'Displayed com\.myzesty/com\.photo\.myzesty\.ui\.activity\.photo\.PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_first_session(ed, choose_bg=True):
    """Field T-63..T-20: first install -> onboarding -> bg-remover task -> refuse media -> sample image -> Standard."""
    ed.step('preflight: installed APK has the photo app (PhotoActivity)')
    if 'PhotoActivity' not in ed.dev.sh('dumpsys package com.myzesty | grep -i photoactivity'):
        raise UIError('lab APK has no com.photo.myzesty PhotoActivity / libImageFilter: install the shipped 1.25.2 '
                      '(800054890) build with the photo module; this field path does not exist in the lab build')
    ed.step('first install state: pm clear (media permission not granted)')
    ed.mon.allow_death = True
    ed.dev.force_stop()
    ed.dev.sh('pm clear com.myzesty')
    for p in ('READ_MEDIA_IMAGES', 'READ_MEDIA_VIDEO', 'READ_EXTERNAL_STORAGE'):
        ed.dev.sh(f'pm revoke com.myzesty android.permission.{p} 2>/dev/null')
    mark = ed.log_mark()
    ed.dev.launch()
    ed.mon.allow_death = False
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field: first session after install')
    ed.idle(3)
    ed.step('onboarding: continue, skip -> bg remover task')
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field: onboarding bg-remover task shows')
    ed.idle(2.2)
    ed.ui.tap(('textc:select photo', 'textc:choose photo', 'textc:upload'), timeout=10)
    ed.idle(3.4)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)       # app's own permission popup
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field: media permission refused')
    ed.idle(1.8)
    ed.ui.tap(('textc:sample image', 'textc:try sample', 'textc:sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    ed.step('standard AI background remover')
    ed.idle(1.5)
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field: background removed')
    ed.idle(3)
    ed.ui.tap(('textc:start editing',), timeout=15)
    _9eb49083_ev(ed, 'onboarding_task_start_editing', 10, mark, 'field: start editing')
    if choose_bg:
        ed.idle(2.6)
        ed.ui.tap(('textc:choose background',), timeout=10)
        _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field: choose background')
        ed.idle(2.5)
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')
    return mark


def _9eb49083_eraser(ed, mark):
    ed.step('tap Eraser (field trigger)')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field: eraser clicked')
    ed.settle(10)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_2_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): onboarding sample image, Standard, Choose Background, Done, ~20 s idle, Eraser."""
    mark = _9eb49083_first_session(ed, choose_bg=True)
    ed.idle(r.uniform(19, 22))                      # field: 20.8 s, nothing logged, no pause/recreate
    _9eb49083_eraser(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_2_b(ed, r):
    """Instance 1/1, same first session but Eraser tapped within a few seconds of the removebg commit (filter just set up)."""
    mark = _9eb49083_first_session(ed, choose_bg=True)
    ed.idle(r.uniform(1.5, 4))
    _9eb49083_eraser(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_2_c(ed, r):
    """Instance 1/1, first session without the Choose Background step: Start editing, Done, ~20 s idle, Eraser."""
    mark = _9eb49083_first_session(ed, choose_bg=False)
    ed.idle(r.uniform(18, 22))
    _9eb49083_eraser(ed, mark)


# 2026-10-26 03:44 level 2 attempt 3
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_photo_pkg(ed):
    """The field crash lives in the separate photo app (PhotoActivity + libImageFilter.so), not in com.myzesty."""
    for line in ed.dev.sh('pm list packages | grep -i -e photo -e zesty').split():
        pkg = line.replace('package:', '').strip()
        if pkg and 'PhotoActivity' in ed.dev.sh(f'dumpsys package {pkg} | grep -m1 PhotoActivity'):
            return pkg
    raise UIError('SETUP: no installed package has PhotoActivity/libImageFilter.so; the lab worktree (CPP-1.25.2) '
                  'builds only the video editor. Install the shipped photo app 1.25.2 (800054890) from Play first')


def _9eb49083_first_session(ed, choose_bg=True):
    """Field T-63..T-20: fresh install -> onboarding -> bg-remover task -> refuse media -> sample image -> Standard."""
    ed.open_fixture('9eb49083')                        # lab rule; the video draft itself is not used
    ed.step('preflight: find the photo app')
    pkg = _9eb49083_photo_pkg(ed)
    ed.step(f'first session of {pkg}: pm clear, media permission not granted')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    ed.mon.allow_death = False
    ed.require_log(r'Displayed ' + pkg.replace('.', r'\.') + '/', 40, since=mark, why='field: first launch after install')
    ed.idle(4)
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)       # onboarding_continue
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)                                 # onboarding_1_skip -> TaskActivity
    ed.idle(2.2)
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=15)       # onboarding_task_select_photo
    ed.idle(3.4)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', "textc:don't allow", 'textc:deny'), 8)
    ed.idle(1.8)
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)          # onboarding_task_try_sample_image
    ed.require_log(r'Displayed \S+PhotoActivity', 45, since=mark, why='field: PhotoActivity opens with the sample image')
    ed.step('standard AI background remover on the sample image')
    ed.idle(1.5)
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    ed.ui.wait(('textc:start editing',), timeout=60)                           # process_image_done_complete
    ed.idle(3)
    ed.ui.tap(('textc:start editing',), timeout=10)
    if choose_bg:
        ed.idle(2.6)
        ed.ui.tap(('textc:choose background', 'textc:background'), timeout=10)
        ed.idle(2.5)
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)                    # start_done -> pe_removebg_complete
    ed.ui.wait(_9EB_ERASER, timeout=20)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): sample image, Standard, Choose Background, Done, ~20 s idle, Eraser."""
    _9eb49083_first_session(ed, choose_bg=True)
    ed.idle(r.uniform(19, 22))                        # field: 20.8 s with nothing logged, no pause/recreate
    ed.step('tap Eraser (field trigger)')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    ed.settle(10)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_b(ed, r):
    """Instance 1/1, same first session, Eraser tapped 1.5-4 s after the removebg commit (filter just built)."""
    _9eb49083_first_session(ed, choose_bg=True)
    ed.idle(r.uniform(1.5, 4))
    ed.step('tap Eraser soon after commit')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    ed.settle(10)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l2_3_c(ed, r):
    """Instance 1/1, field path, then Eraser and Restore toggled at human speed (filter value read each time)."""
    _9eb49083_first_session(ed, choose_bg=True)
    ed.idle(r.uniform(15, 20))
    for k in range(3):
        ed.step(f'Eraser {k + 1}/3')
        ed.ui.tap(_9EB_ERASER, timeout=10)
        ed.idle(r.uniform(1.5, 3))
        _9eb49083_soft_tap(ed, ('textc:restore', 'textc:brush'), 3)
        ed.idle(r.uniform(1.5, 3))
    ed.settle(10)


# 2026-10-26 03:52 level 3 attempt 1
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_photo_pkg(ed):
    """The installed package that really has PhotoActivity (the CPP-1.25.2 lab build only names it by reflection)."""
    out = ed.dev.sh("for p in $(pm list packages | grep -iE 'zesty|photo' | cut -d: -f2); do "
                    "dumpsys package $p | grep -q 'photo/PhotoActivity\\|activity.photo.PhotoActivity' && echo PKG=$p; done")
    pk = [l[4:].strip() for l in out.splitlines() if l.startswith('PKG=')]
    if not pk:
        raise UIError('SETUP: no installed package has PhotoActivity/libImageFilter.so (lab build is video-only); '
                      'install the shipped 1.25.2 (800054890) photo-capable build from Play, then rerun')
    return pk[0]


def _9eb49083_first_session(ed, r):
    """Field T-63..T-20: pm clear -> onboarding -> bg-remover task -> refuse media -> sample image -> Standard -> Done."""
    pkg = _9eb49083_photo_pkg(ed)
    ed.step(f'first install state of {pkg}: pm clear, media permission revoked')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    for p in ('READ_MEDIA_IMAGES', 'READ_MEDIA_VIDEO', 'READ_EXTERNAL_STORAGE'):
        ed.dev.sh(f'pm revoke {pkg} android.permission.{p} 2>/dev/null')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field: onboarding bg-remover task')
    ed.idle(2.2)
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3.4)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field: media permission refused')
    ed.idle(1.8)
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    ed.idle(1.5)
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field: background removed')
    ed.idle(3)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.6)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field: choose background')
    ed.idle(2.5)
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')
    return pkg, mark


def _9eb49083_eraser(ed, mark):
    ed.step('tap Eraser (field trigger)')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field: eraser clicked')
    ed.settle(10)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): field first session on a low-end-speed phone (slow_phone), ~20 s idle, Eraser."""
    pkg, mark = _9eb49083_first_session(ed, r)
    try:
        ed.dev.slow_phone(r.randint(25, 40))
        ed.idle(r.uniform(19, 22))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_b(ed, r):
    """Instance 1/1: field first session, memory-pressure trims (no pause/recreate) during the 20 s idle, then Eraser."""
    pkg, mark = _9eb49083_first_session(ed, r)
    for lvl in ('RUNNING_MODERATE', 'RUNNING_LOW', 'RUNNING_CRITICAL'):
        ed.dev.sh(f'am send-trim-memory {pkg} {lvl}')
        ed.idle(r.uniform(5, 7))
    _9eb49083_eraser(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_1_c(ed, r):
    """Instance 1/1: field first session with the network cut after the removal (fresh-install user offline), Eraser."""
    pkg, mark = _9eb49083_first_session(ed, r)
    try:
        ed.dev.network(False)
        ed.idle(r.uniform(18, 22))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.network(True)


# 2026-10-26 03:53 level 3 attempt 2
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_photo_pkg(ed):
    """Preflight BEFORE anything destructive: the installed package that really declares PhotoActivity."""
    out = ed.dev.sh("for p in $(pm list packages | grep -iE 'zesty|photo' | cut -d: -f2); do "
                    "dumpsys package $p | grep -q 'PhotoActivity' && echo PKG=$p; done")
    pk = [l[4:].strip() for l in out.splitlines() if l.startswith('PKG=')]
    if not pk:
        raise UIError('SETUP: no installed package declares PhotoActivity (CPP-1.25.2 lab build is video-only, no '
                      'libImageFilter.so); install the shipped photo-capable 1.25.2 (800054890) from Play, then rerun')
    return pk[0]


def _9eb49083_first_session(ed, r):
    """Field T-63..T-20: true first run (pm clear) -> onboarding -> bg-remover task -> refuse media -> sample image ->
    Standard -> Start editing -> Choose Background -> Done (pe_removebg_complete)."""
    pkg = _9eb49083_photo_pkg(ed)
    ed.step(f'first install state of {pkg}: pm clear, media permission not granted')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field: onboarding bg-remover task')
    ed.idle(2.2)
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3.4)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field: media permission refused')
    ed.idle(1.8)
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    ed.idle(1.5)
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field: background removed')
    ed.idle(3)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.6)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field: choose background')
    ed.idle(2.5)
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')
    return pkg, mark


def _9eb49083_eraser(ed, mark):
    ed.step('tap Eraser (field trigger), stay 12 s for a delayed abort')
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field: eraser clicked')
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): true first session, low-end CPU (slow_phone) for the 20 s idle and the Eraser tap."""
    pkg, mark = _9eb49083_first_session(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.idle(r.uniform(19, 22))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_b(ed, r):
    """Instance 1/1: true first session, trim-memory callbacks (no pause/recreate) during the 20 s idle, then Eraser."""
    pkg, mark = _9eb49083_first_session(ed, r)
    for lvl in ('RUNNING_MODERATE', 'RUNNING_LOW', 'RUNNING_CRITICAL'):
        ed.dev.sh(f'am send-trim-memory {pkg} {lvl}')
        ed.idle(r.uniform(6, 7.5))
    _9eb49083_eraser(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_2_c(ed, r):
    """Instance 1/1: true first session, low-end CPU plus memory pressure, Eraser tapped right after a CRITICAL trim."""
    pkg, mark = _9eb49083_first_session(ed, r)
    try:
        ed.idle(r.uniform(15, 18))
        ed.dev.slow_phone(r.randint(35, 48))
        ed.dev.sh(f'am send-trim-memory {pkg} RUNNING_CRITICAL')
        ed.idle(r.uniform(0.5, 2))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.slow_phone(0)


# 2026-10-26 03:54 level 3 attempt 3
_9EB_PHOTO_ACT = 'com.photo.myzesty.ui.activity.photo.PhotoActivity'
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_soft(ed, sel, timeout=6):
    try:
        ed.ui.tap(sel, timeout=timeout)
    except UIError:
        pass


def _9eb49083_preflight(ed):
    """Non-destructive: PhotoActivity must resolve, the APK must carry libImageFilter.so, versionCode 800054890."""
    for pkg in [l.split(':', 1)[1].strip() for l in ed.dev.sh('pm list packages').splitlines() if ':' in l]:
        if 'zesty' not in pkg and 'photo' not in pkg:
            continue
        if _9EB_PHOTO_ACT not in ed.dev.sh(f'cmd package resolve-activity -n {pkg}/{_9EB_PHOTO_ACT} 2>&1'):
            continue
        apk = ed.dev.sh(f'pm path {pkg}').splitlines()[0].replace('package:', '').strip()
        if 'libImageFilter.so' not in ed.dev.sh(f'unzip -l {apk} 2>/dev/null | grep libImageFilter'):
            continue
        vc = ed.dev.sh(f"dumpsys package {pkg} | grep -m1 versionCode")
        ed.log(f'    photo app: {pkg} {vc.strip()}')
        if '800054890' not in vc:
            raise UIError(f'SETUP: {pkg} has PhotoActivity but is not 1.25.2 (800054890): {vc.strip()}')
        return pkg
    raise UIError('SETUP: no package resolves PhotoActivity with libImageFilter.so; install Play 1.25.2 (800054890) '
                  'replacing the video-only lab build (uninstall first), then rerun. Nothing was cleared.')


def _9eb49083_to_removebg_done(ed, r):
    """Field T-63..T-20: first session -> bg-remover task -> refuse media -> sample image -> Standard -> Done."""
    pkg = _9eb49083_preflight(ed)
    ed.step(f'{pkg}: first-session state (pm clear), launcher start')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_soft(ed, ('textc:continue', 'textc:get started'))
    ed.idle(1.3)
    _9eb49083_soft(ed, ('textc:skip',))
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field: onboarding bg-remover task')
    ed.idle(2)
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3)
    _9eb49083_soft(ed, ('textc:cancel', 'textc:not now', 'textc:later'))
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field: media permission refused')
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    _9eb49083_soft(ed, ('textc:standard',))
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field: background removed')
    ed.idle(3)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.5)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field: choose background')
    ed.idle(2.5)
    _9eb49083_soft(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')
    return pkg, mark


def _9eb49083_eraser(ed, mark):
    ed.step('tap Eraser (field trigger), stay for a delayed abort')
    ed.ui.tap(('textc:eraser', 'textc:erase'), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field: eraser clicked')
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_3_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): verified 1.25.2 photo app, first session, low-end CPU for the 20 s idle + Eraser."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.idle(r.uniform(19, 22))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_3_b(ed, r):
    """Instance 1/1: verified 1.25.2 photo app, first session, trim-memory up to CRITICAL (no pause) in the idle, Eraser."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    for lvl in ('RUNNING_MODERATE', 'RUNNING_LOW', 'RUNNING_CRITICAL'):
        ed.dev.sh(f'am send-trim-memory {pkg} {lvl}')
        ed.idle(r.uniform(6, 7.5))
    _9eb49083_eraser(ed, mark)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l3_3_c(ed, r):
    """Instance 1/1: verified 1.25.2 photo app, first session offline after removal + slow storage, Eraser after ~20 s."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    try:
        ed.dev.network(False)
        ed.dev.busy_storage(True)
        ed.idle(r.uniform(18, 22))
        _9eb49083_eraser(ed, mark)
    finally:
        ed.dev.busy_storage(False)
        ed.dev.network(True)


# 2026-10-26 03:56 level 4 attempt 1
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_photo_pkg(ed):
    """Non-destructive preflight: a package that resolves PhotoActivity AND ships libImageFilter.so."""
    out = ed.dev.sh("for p in $(pm list packages | grep -iE 'zesty|photo' | cut -d: -f2); do "
                    "d=$(pm path $p | head -1 | cut -d: -f2); "
                    "dumpsys package $p | grep -q 'PhotoActivity' && unzip -l $d 2>/dev/null | grep -q libImageFilter.so "
                    "&& echo PKG=$p; done")
    pk = [l[4:].strip() for l in out.splitlines() if l.startswith('PKG=')]
    if not pk:
        raise UIError('SETUP: no package has PhotoActivity + libImageFilter.so. The CPP-1.25.2 lab build is video-only; '
                      'uninstall it and install Play 1.25.2 (800054890) on this phone, then rerun. Nothing was cleared.')
    return pk[0]


def _9eb49083_to_choose_bg(ed):
    """Field T-63..T-23: pm clear -> onboarding -> bg-remover task -> refuse media -> sample -> Standard -> Choose bg."""
    pkg = _9eb49083_photo_pkg(ed)
    ed.step(f'first session of {pkg} (pm clear)')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field: onboarding bg-remover task')
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field: media permission refused')
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field: PhotoActivity opens with the sample image')
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field: background removed')
    ed.idle(2.5)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.5)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field: choose background')
    return pkg, mark


def _9eb49083_done(ed, mark):
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')


def _9eb49083_eraser_storm(ed, r, mark, n):
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field: eraser clicked')
    for _ in range(n):                                   # toggle the eraser tool fast: GetIntValueFromFilter per entry
        ed.idle(r.uniform(0.05, 0.3))
        _9eb49083_soft_tap(ed, _9EB_ERASER, 2)
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_1_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): field first session, Eraser hit the instant pe_removebg_complete lands, then storm."""
    pkg, mark = _9eb49083_to_choose_bg(ed)
    ed.idle(2.5)
    _9eb49083_done(ed, mark)
    ed.step('eraser inside the removebg commit window')
    _9eb49083_eraser_storm(ed, r, mark, r.randint(8, 15))


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_1_b(ed, r):
    """Instance 1/1: field first session, the field's ~20 s idle, then one Eraser tap on a low-end-speed CPU."""
    pkg, mark = _9eb49083_to_choose_bg(ed)
    ed.idle(2.5)
    _9eb49083_done(ed, mark)
    ed.idle(r.uniform(18, 21))
    try:
        ed.dev.slow_phone(r.randint(35, 48))
        ed.step('eraser at field timing, slow CPU')
        _9eb49083_eraser_storm(ed, r, mark, 0)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_1_c(ed, r):
    """Instance 1/1: field first session, Eraser tapped while the Choose-background result is still being committed."""
    pkg, mark = _9eb49083_to_choose_bg(ed)
    try:
        ed.dev.slow_phone(r.randint(30, 45))
        ed.idle(r.uniform(0.3, 1.2))
        _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 5)
        ed.step('eraser before/at pe_removebg_complete (filter state mid-commit)')
        _9eb49083_eraser_storm(ed, r, mark, r.randint(6, 12))
        _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field: removebg committed on PhotoActivity')
    finally:
        ed.dev.slow_phone(0)


# 2026-10-26 03:57 level 4 attempt 2
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_soft_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_preflight(ed):
    """Non-destructive: the Play-installed photo-capable 1.25.2 must be there (lab build is video-only; adb installs die to PairIP)."""
    out = ed.dev.sh("for p in $(pm list packages | grep -iE 'zesty|photo' | cut -d: -f2); do d=$(dumpsys package $p); "
                    "echo \"$d\" | grep -q PhotoActivity && echo PKG=$p "
                    "VC=$(echo \"$d\" | grep -o 'versionCode=[0-9]*' | head -1 | cut -d= -f2) "
                    "INST=$(echo \"$d\" | grep -o 'installerPackageName=[^ ]*' | head -1 | cut -d= -f2); done")
    rows = [dict(kv.split('=', 1) for kv in l.split()) for l in out.splitlines() if l.startswith('PKG=')]
    ok = [x for x in rows if x.get('VC') == '800054890' and x.get('INST') == 'com.android.vending']
    if not ok:
        raise UIError(f'SETUP (manual): need Play-installed 1.25.2 (800054890) with PhotoActivity + libImageFilter.so on '
                      f'the physical phone; found {rows or "only the video-only CPP-1.25.2 lab build"}. Nothing was cleared.')
    try:
        ed.open_fixture('9eb49083')                          # unchanged video draft; irrelevant to the photo path
    except UIError:
        ed.log('    fixture 9eb49083 not openable on the Play build (no lab control); photo path needs none')
    return ok[0]['PKG']


def _9eb49083_to_removebg_done(ed, r):
    """Field T-63..T-20: first session -> bg-remover task -> refuse media -> sample -> Standard -> edit -> Choose bg -> Done."""
    pkg = _9eb49083_preflight(ed)
    ed.step(f'first session of {pkg} (pm clear)')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field cp1: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_soft_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field cp1: onboarding bg-remover task')
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3)
    _9eb49083_soft_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field cp1: media permission refused')
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field cp1: PhotoActivity opens with the sample image')
    _9eb49083_soft_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field cp2: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field cp2: background removed')
    ed.idle(2.5)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.5)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field cp3: choose background')
    ed.idle(2.5)
    _9eb49083_soft_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field cp3: removebg committed on PhotoActivity')
    return pkg, mark


def _9eb49083_eraser(ed, mark):
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field cp5: eraser clicked')


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_2_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): field first session, Eraser the instant pe_removebg_complete lands, then re-tap storm."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    ed.step('eraser inside the removebg commit window + storm')
    _9eb49083_eraser(ed, mark)
    for _ in range(r.randint(8, 15)):
        ed.idle(r.uniform(0.05, 0.3))
        _9eb49083_soft_tap(ed, _9EB_ERASER, 2)
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_2_b(ed, r):
    """Instance 1/1: field first session, the field's ~20 s quiet idle, then a double Eraser tap on a low-end-speed CPU."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    ed.idle(r.uniform(18, 21))
    try:
        ed.dev.slow_phone(r.randint(35, 48))
        ed.step('eraser at field timing, slow CPU, double tap')
        _9eb49083_eraser(ed, mark)
        ed.idle(r.uniform(0.03, 0.15))
        _9eb49083_soft_tap(ed, _9EB_ERASER, 2)
        ed.settle(12)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_2_c(ed, r):
    """Instance 1/1: field first session, ~20 s idle, then Eraser open/close (Back) cycles so the filter is set up and torn down fast."""
    pkg, mark = _9eb49083_to_removebg_done(ed, r)
    ed.idle(r.uniform(18, 21))
    ed.step('eraser enter/leave storm')
    _9eb49083_eraser(ed, mark)
    for _ in range(r.randint(6, 10)):
        ed.idle(r.uniform(0.1, 0.5))
        ed.dev.key('KEYCODE_BACK')
        ed.idle(r.uniform(0.1, 0.4))
        _9eb49083_soft_tap(ed, _9EB_ERASER, 3)
    ed.settle(12)


# 2026-10-26 03:59 level 4 attempt 3
_9EB_PHOTO = r'Displayed [\w.]+/[\w.]*PhotoActivity'
_9EB_ERASER = ('textc:eraser', 'textc:erase')


def _9eb49083_tap(ed, sel, timeout=5):
    try:
        ed.ui.tap(sel, timeout=timeout)
        return True
    except UIError:
        return False


def _9eb49083_ev(ed, name, timeout, mark, why):
    return ed.require_log(r'Event: ' + name + r'\b', timeout, since=mark, why=why)


def _9eb49083_photo_pkg(ed):
    """Split-APK-aware check: a package with PhotoActivity whose APKs (base + splits) ship libImageFilter.so, on real hw."""
    if ed.dev.getprop('ro.kernel.qemu') == '1' or 'ranchu' in ed.dev.getprop('ro.hardware'):
        raise UIError('SETUP: emulator; the libImageFilter abort needs the physical arm64 phone')
    out = ed.dev.sh("for p in $(pm list packages | cut -d: -f2 | grep -iE 'zesty|photo'); do "
                    "dumpsys package $p | grep -q PhotoActivity || continue; "
                    "for a in $(pm path $p | cut -d: -f2); do unzip -l $a 2>/dev/null | grep -q libImageFilter.so && echo PKG=$p; done; "
                    "ls /data/app/*/$p*/lib/*/ 2>/dev/null | grep -q libImageFilter && echo PKG=$p; done")
    pk = sorted({l[4:].strip() for l in out.splitlines() if l.startswith('PKG=')})
    if not pk:
        raise UIError('SETUP (manual): no installed package has PhotoActivity + libImageFilter.so (checked base+split APKs). '
                      'The CPP-1.25.2 lab build is video-only. Install Play 1.25.2 (800054890) from the internal-test '
                      'track on the physical phone (adb installs die to PairIP). Nothing was cleared.')
    return pk[0]


def _9eb49083_to_removebg_done(ed):
    """Field T-63..T-20: first session -> bg-remover task -> refuse media -> sample -> Standard -> edit -> Choose bg -> Done."""
    pkg = _9eb49083_photo_pkg(ed)
    ed.open_fixture('9eb49083')                          # unchanged video draft; the photo path needs none
    ed.step(f'first session of {pkg} (pm clear)')
    ed.mon.allow_death = True
    ed.dev.sh(f'am force-stop {pkg}; pm clear {pkg}')
    mark = ed.log_mark()
    ed.dev.sh(f'monkey -p {pkg} -c android.intent.category.LAUNCHER 1')
    _9eb49083_ev(ed, 'app_opened_first_time', 40, mark, 'field cp1: first session after install')
    ed.mon.allow_death = False
    ed.idle(3)
    _9eb49083_tap(ed, ('textc:continue', 'textc:get started'), 10)
    ed.idle(1.3)
    _9eb49083_tap(ed, ('textc:skip',), 8)
    _9eb49083_ev(ed, 'onboarding_task_bg_remover_show', 30, mark, 'field cp1: onboarding bg-remover task')
    ed.ui.tap(('textc:select photo', 'textc:choose photo'), timeout=10)
    ed.idle(3)
    _9eb49083_tap(ed, ('textc:cancel', 'textc:not now', 'textc:later'), 8)
    _9eb49083_ev(ed, 'permission_pop_cancel', 15, mark, 'field cp1: media permission refused')
    ed.ui.tap(('textc:sample image', 'textc:try sample'), timeout=10)
    ed.require_log(_9EB_PHOTO, 45, since=mark, why='field cp1: PhotoActivity opens with the sample image')
    _9eb49083_tap(ed, ('textc:standard',), 8)
    _9eb49083_ev(ed, 'LOAD_MODEL_DONE_complete', 40, mark, 'field cp2: model loads')
    _9eb49083_ev(ed, 'process_image_done_complete', 60, mark, 'field cp2: background removed')
    ed.idle(2.5)
    ed.ui.tap(('textc:start editing',), timeout=15)
    ed.idle(2.5)
    ed.ui.tap(('textc:choose background',), timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_choose_background', 10, mark, 'field cp3: choose background')
    ed.idle(2.5)
    _9eb49083_tap(ed, ('text:Done', 'textc:done'), 10)
    _9eb49083_ev(ed, 'pe_removebg_complete', 15, mark, 'field cp3: removebg committed on PhotoActivity')
    return mark


def _9eb49083_eraser(ed, mark):
    ed.ui.tap(_9EB_ERASER, timeout=10)
    _9eb49083_ev(ed, 'ai_bg_remover_eraser', 10, mark, 'field cp5: eraser clicked')


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_3_a(ed, r):
    """Instance 1/1 (OPPO CPH2127): field first session, Eraser the instant pe_removebg_complete lands, re-tap storm."""
    mark = _9eb49083_to_removebg_done(ed)
    ed.step('eraser inside the removebg commit window + storm')
    _9eb49083_eraser(ed, mark)
    for _ in range(r.randint(10, 18)):
        ed.idle(r.uniform(0.04, 0.25))
        _9eb49083_tap(ed, _9EB_ERASER, 2)
    ed.settle(12)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_3_b(ed, r):
    """Instance 1/1: field first session, the field's ~20 s quiet idle, then Eraser on a low-end-speed CPU (OPPO CPH2127)."""
    mark = _9eb49083_to_removebg_done(ed)
    ed.idle(r.uniform(18, 21))
    try:
        ed.dev.slow_phone(r.randint(38, 48))
        ed.step('eraser at field timing, slow CPU')
        _9eb49083_eraser(ed, mark)
        ed.settle(15)
    finally:
        ed.dev.slow_phone(0)


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_l4_3_c(ed, r):
    """Instance 1/1: field first session, ~20 s idle, Eraser then rapid brush drags/size changes while the filter is read."""
    mark = _9eb49083_to_removebg_done(ed)
    ed.idle(r.uniform(18, 21))
    _9eb49083_eraser(ed, mark)
    ed.step('eraser strokes + tool toggles right after entering the eraser')
    w, h = ed._screen_size()
    for _ in range(r.randint(8, 14)):
        y = int(h * r.uniform(0.3, 0.6))
        ed.dev.swipe(int(w * 0.2), y, int(w * 0.8), y + r.randint(-80, 80), r.randint(60, 200))
        if r.random() < 0.5:
            _9eb49083_tap(ed, _9EB_ERASER + ('textc:restore', 'textc:brush'), 1)
    ed.settle(12)
