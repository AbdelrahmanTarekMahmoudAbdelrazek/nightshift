# Night Shift live-agent recipes for 501bb526 (turbo)

# 2026-10-21 13:27

@scenario('nightshift', 'auto', 'nodraft')
def ns_501bb526_live2(ed, r):
    """Block the main thread in PlayerActivity.freezeLoader() -> Player.freezeProgress() (JNI_freezeProgrees / MsgLooper::Get<double,int>) for more than 5 s  (live agent run, replayed)"""
    # ed._pin_draft = '1c1ad6f3-a919-4d22-b0ff-66db4cbf2107'   # the project the live run reproduced on (100 s clip, 5 freezes)  -- 2026-10-21: this project is now broken (saved speed applies), pin off
    live_replay(ed, [{'args': {}, 'do': 'open_draft', 'result': 'editor open (test project)', 't': 8.7},
     {'args': {'x': 144, 'y': 1300}, 'do': 'tap_xy', 'result': 'tapped', 't': 23.6},
     {'args': {'x': 144, 'y': 1300}, 'do': 'tap_xy', 'result': 'tapped', 't': 30.8},
     {'args': {'x': 450, 'y': 1300}, 'do': 'tap_xy', 'result': 'tapped', 't': 38.8},
     {'args': {'x': 144, 'y': 1094}, 'do': 'tap_xy', 'result': 'tapped', 't': 46.8},
     {'args': {'x': 300, 'y': 1200}, 'do': 'tap_xy', 'result': 'tapped', 't': 59.2},
     {'args': {'target': 'desc:ve_btn_back'}, 'do': 'tap', 'result': 'tapped', 't': 87.6},
     {'args': {'x': 144, 'y': 1300}, 'do': 'tap_xy', 'result': 'tapped', 't': 93.6},
     {'args': {}, 'do': 'open_draft', 'result': 'editor open (test project)', 't': 108.9},
     {'args': {'x': 144, 'y': 1300}, 'do': 'tap_xy', 'result': 'tapped', 't': 135.1},
     {'args': {'x': 144, 'y': 1100}, 'do': 'tap_xy', 'result': 'tapped', 't': 153.6},
     {'args': {'target': 'desc:ve_tab_clip_speed'}, 'do': 'tap', 'result': 'tapped', 't': 160.4},
     {'args': {'x': 552, 'y': 1272}, 'do': 'tap_xy', 'result': 'tapped', 't': 167.1},
     {'args': {'target': 'desc:ve_btn_apply_changes'}, 'do': 'tap', 'result': 'tapped', 't': 174.8},
     {'args': {'seconds': 5}, 'do': 'idle', 'result': 'ok', 't': 186.7},
     {'args': {}, 'do': 'resume', 'result': 'ok', 't': 208.9},
     {'args': {}, 'do': 'resume', 'result': 'ok', 't': 236.2}])
