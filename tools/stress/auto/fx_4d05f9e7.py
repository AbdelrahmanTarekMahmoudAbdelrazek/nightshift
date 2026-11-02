# Night Shift lab fixture builder for 4d05f9e7 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_4d05f9e7_fx(ed, r):
    """Fixture for Crashlytics ANR 'MessageQueue.nativePollOnce' (4d05f9e7): plain lab test draft, no trigger."""
    ed.fixture_begin()
    # The field state at checkpoint 1 is a first-run app with no project in it. The recipes reset the
    # app themselves (pm clear / onboarding), so this project is only a neutral anchor: one video on layer 0.
    # Last run, open_draft() could not get from the developer-menu launcher to My Projects.
    # This run reaches the editor through the debug build's lab control: list projects -> open by id.
    ed.step('find or make the lab test draft through lab control')
    drafts = ed.drafts(timeout=20) or []
    if not any(d.get('videos', 0) >= 1 for d in drafts):
        ed.remake_test_draft()
        drafts = ed.drafts(timeout=20) or []
    target = next((d for d in drafts if d.get('videos', 0) >= 1), None)
    if target is None:
        target = drafts[0] if drafts else None
    if target is None:
        ed.create_draft()
    else:
        mark = ed.log_mark()
        ed.step('open the test draft by id (lab door, no home navigation)')
        ed.open_draft_id(target['id'], timeout=60)
        ed.require_log(r'MsgAddVideo.*(media_layer|layer)\D*0', 30, since=mark,
                       why='the project opens in the editor and its layer-0 video clip reaches the engine')
    ed.settle(2)
    ed.save_fixture('4d05f9e7', 'Lab test draft: one video clip on layer 0, no overlays/text/freeze '
                    '(neutral anchor; field state is a first-run app before onboarding)')
