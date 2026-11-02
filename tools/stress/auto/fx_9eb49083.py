# Night Shift lab fixture builder for 9eb49083 (try 3)

@scenario('nightshift', 'auto', 'nodraft')
def ns_9eb49083_fx(ed, r):
    """Fixture for [libImageFilter.so] JNI_GetIntValueFromFilter: first-run app on the onboarding BG-remover task (TaskActivity)."""
    ed.fixture_begin()
    # The crash path needs no video project: a first-run app (cleared data) on the onboarding BG-remover task.
    ed.step('clear app data (first run)')
    ed.dev.force_stop()
    ed.dev.sh('pm clear com.myzesty', 30)
    ed.step('cold launch as a new user')
    mark = ed.log_mark()
    ed.dev.launch()
    ed.require_log(r'AnalyticsManager.*Event: \w*app_opened_first_time', 40, since=mark,
                   why='first session after a data clear (field: app_opened_first_time)')
    ed.idle(3)
    # RNEditorModule FIRST_OPEN_TASK starts TaskActivity with NO extras (RNEditorModule.java:326-327),
    # which is what the field's onboarding_1_skip led to. Take the mark BEFORE the launch: onCreate logs at once.
    ed.step('open onboarding BG-remover task (TaskActivity)')
    mark = ed.log_mark()
    ed.start_activity('com.myzesty.task.presentation.activity.TaskActivity', extras='', expect_crash=False)
    ed.require_log(r'wm_on_(create|resume)_called.*TaskActivity', 30, since=mark,
                   why='TaskActivity is created and in front')
    ed.require_log(r'AnalyticsManager.*Event: \w*onboarding_task_bg_remover_show', 30, since=mark,
                   why='TaskActivity.onCreate logged onboarding_task_bg_remover_show (TaskActivity.kt:69)')
    ed.idle(2)
    ed.save_fixture('9eb49083', 'no video project: app data cleared (first run), onboarding BG-remover task open in TaskActivity; recipe does select photo -> cancel permission -> try sample image -> sample tile -> PhotoActivity BG remover -> Eraser -> Redo')
