# Night Shift lab fixture builder for a34175e5 (try 3)

# Night Shift lab fixture builder for a34175e5 (try 3)

def _fx_a34175e5_paywall_up(s):
    return s is not None and (s.has('btn_continue') or s.has('rv_packages') or s.has('tv_tab_premium'))


def _fx_a34175e5_close_paywall(ed):
    """The auto pro screen opens on launches of a kept-data install and covers My Projects."""
    for _ in range(3):
        s = ed.ui.dump()
        if not _fx_a34175e5_paywall_up(s):
            return
        if s.has('btn_close'):
            ed.ui.tap('btn_close', timeout=3)
        else:
            ed.dev.key(4)
        time.sleep(1.5)


@scenario('nightshift', 'auto', 'nodraft')
def ns_a34175e5_fx(ed, r):
    """Fixture for Crashlytics 'Preconditions.outOfBounds' (PremiumScreenBottomSheet.buySubscription): plain project, no edits."""
    ed.fixture_begin()
    ed.step('wait for the launch paywall, close it')
    ed.wait_log(r'pro_screen_show|Displayed com\.myzesty', 12)
    time.sleep(2)
    _fx_a34175e5_close_paywall(ed)

    ed.step('open the lab test draft')
    mark = ed.log_mark()
    ed.open_draft()
    ed.require_log(r'wm_on_resume_called.*BaseVideoEditorActivity', 30, since=mark,
                   why='the editor opened a project (the paywall Continue race needs no clips or edits)')
    ed.idle(2)

    ed.save_fixture('a34175e5', 'untouched lab test draft; the paywall Continue race needs no project edits (first-run state comes from pm clear in the recipe)')
