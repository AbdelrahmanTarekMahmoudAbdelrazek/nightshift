# Night Shift lab fixture builder for 9eb49083 (try 3)

# Night Shift lab fixture builder for 9eb49083 (try 3)

import re

_FX_9EB49083_EV = r'(Event: |name=)(test_)?%s\b'


def _fx_9eb49083_photo_pkg(ed):
    """The installed package that declares PhotoActivity (the photo app with libImageFilter.so), or ''."""
    for line in (ed.dev.sh('pm list packages', 20) or '').split():
        pkg = line.replace('package:', '').strip()
        if re.search(r'zesty|photo', pkg, re.I) and 'PhotoActivity' in (
                ed.dev.sh('dumpsys package %s | grep -m1 PhotoActivity' % pkg, 20) or ''):
            return pkg
    return ''


def _fx_9eb49083_tap_text(ed, pats):
    """uiautomator dump, tap the first node whose text|id|desc matches a pattern (patterns in priority order)."""
    xml = ed.dev.sh('uiautomator dump /sdcard/ns_fx.xml >/dev/null 2>&1; cat /sdcard/ns_fx.xml', 15) or ''
    nodes = re.findall(r'<node [^>]*?text="([^"]*)"[^>]*?resource-id="([^"]*)"[^>]*?content-desc="([^"]*)"'
                       r'[^>]*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    for pat in pats:
        for txt, rid, desc, x1, y1, x2, y2 in nodes:
            if re.search(pat, '%s|%s|%s' % (txt, rid.split('/')[-1], desc), re.I):
                ed.dev.tap((int(x1) + int(x2)) // 2, (int(y1) + int(y2)) // 2)
                return pat
    return None


@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_fx(ed, r):
    """Fixture for [libImageFilter.so] JNI_GetIntValueFromFilter: photo app first session, sample image in PhotoActivity."""
    ed.fixture_begin()                                   # video test draft stays untouched (it is what save_fixture records)
    ed.step('fixture: find the installed photo app (PhotoActivity + libImageFilter.so)')
    pkg = _fx_9eb49083_photo_pkg(ed)
    if not pkg:
        raise UIError('SETUP: no installed package declares PhotoActivity; the CPP-1.25.2 lab build is video-only. '
                      'Install the shipped photo app 1.25.2 (800054890) from the Play internal-test track first')
    q = re.escape(pkg)
    ed.step('fixture: %s cleared to first run, no media permission, analytics events in logcat' % pkg)
    ed.dev.sh('am force-stop %s; pm clear %s' % (pkg, pkg), 30)
    for perm in ('READ_MEDIA_IMAGES', 'READ_MEDIA_VIDEO', 'READ_EXTERNAL_STORAGE', 'READ_MEDIA_VISUAL_USER_SELECTED'):
        ed.dev.sh('pm revoke %s android.permission.%s 2>/dev/null' % (pkg, perm), 10)
    ed.dev.setprop('debug.firebase.analytics.app', pkg)
    ed.dev.setprop('log.tag.FA', 'VERBOSE')
    ed.dev.setprop('log.tag.FA-SVC', 'VERBOSE')
    mark = ed.log_mark()
    ed.dev.sh('monkey -p %s -c android.intent.category.LAUNCHER 1' % pkg, 20)
    ed.require_log(r'Displayed %s/' % q, 40, since=mark, why='photo app cold start (dies here if PairIP rejects a sideload)')
    ed.require_log(_FX_9EB49083_EV % 'app_opened_first_time', 30, since=mark, why='cleared app runs a first session')
    ed.step('fixture: onboarding -> bg-remover task -> refuse media -> try sample image')
    for _ in range(40):
        if ed.wait_log(r'Displayed %s/\S*PhotoActivity' % q, 1, since=mark):
            break
        task = ed.wait_log(_FX_9EB49083_EV % 'onboarding_task_bg_remover_show', 1, since=mark)
        pats = [r'sample', r'^(cancel|not now|don.t allow|deny)\|', r'select.*photo|choose.*photo',
                r'^continue\||get started|next'] + ([] if task else [r'^skip\|'])
        _fx_9eb49083_tap_text(ed, pats)
        time.sleep(1.5)
    ed.require_log(_FX_9EB49083_EV % 'onboarding_task_bg_remover_show', 5, since=mark, why='bg-remover task offered')
    ed.require_log(_FX_9EB49083_EV % 'permission_pop_cancel', 5, since=mark, why='media permission refused')
    ed.require_log(_FX_9EB49083_EV % 'onboarding_task_try_sample_image', 5, since=mark, why='sample image chosen')
    ed.require_log(r'Displayed %s/\S*PhotoActivity' % q, 20, since=mark, why='PhotoActivity up with the sample image')
    ed.dev.sh('am force-stop %s' % pkg, 20)              # recipes redo pm clear: a first session cannot be saved
    ed.open_draft()                                      # back in the video app so save_fixture records the test draft
    ed.save_fixture('9eb49083', 'no video project: photo app %s cleared to first run, no media permission; onboarding '
                                'bg-remover task -> try sample image -> PhotoActivity proven; recipes must pm clear it again' % pkg)
