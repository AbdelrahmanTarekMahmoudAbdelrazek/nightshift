# Night Shift live-agent recipes for ga78c36e (turbo)

# 2026-10-15 12:39

@scenario('nightshift', 'auto', 'nodraft')
def ns_ga78c36e_live1(ed, r):
    """Through the real UI, get the engine to run the replay order: pause, preview state 0, save the draft, and a speed curve put on clip 0. Then scrub and p (live agent run, replayed)"""
    live_replay(ed, [{'args': {}, 'do': 'open_draft', 'result': 'editor open (test project)', 't': 4.6},
     {'args': {'target': 'id:next_button'}, 'do': 'tap', 'result': 'tapped', 't': 20.9},
     {'args': {'target': 'desc:ve_tab_edit'}, 'do': 'tap', 'result': 'tapped', 't': 26.3},
     {'args': {'target': 'desc:ve_tab_clip_speed'}, 'do': 'tap', 'result': 'tapped', 't': 32.4},
     {'args': {'pattern': 'MsgSetMediaCurveSpeed layer 0 media_id 0 index [1-9]', 'then': 'none', 'timeout': 10},
      'do': 'arm',
      'result': 'armed: MsgSetMediaCurveSpeed layer 0 media_id 0 index [1-9] -> none',
      't': 40.3},
     {'args': {},
      'do': 'back',
      'result': 'ok | ARMED WATCH FIRED: saw  24479 24951 I MsgLooper.cpp: MsgSetMediaCurveSpeed layer 0 '
                'media_id 0 index 1 -> none',
      't': 46.2},
     {'args': {'target': 'id:previous_button'}, 'do': 'tap', 'result': 'tapped', 't': 51.0},
     {'args': {'target': 'id:previous_button'}, 'do': 'tap', 'result': 'tapped', 't': 56.2},
     {'args': {'target': 'id:next_button'}, 'do': 'tap', 'result': 'tapped', 't': 62.2}])
