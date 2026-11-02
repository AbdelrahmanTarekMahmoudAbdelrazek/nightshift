#!/usr/bin/env python3
"""One-off (30 Oct): give the cards read before today a playable video for the new card page.
For each out/cards/<KEY>/card.json, writes board/public/v/<token>/v<n>.mp4 (the token of its frames) from out/cards/<KEY>/video<n>.*.
usage: python3 cards/webvideos.py   (then rebuild + deploy hosting)"""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cardread  # noqa: E402

for p in sorted(glob.glob(os.path.join(cardread.OUT, '*', 'card.json'))):
    c, d = json.load(open(p)), os.path.dirname(p)
    fr = c.get('frames') or []
    if not fr or not str(fr[0].get('url', '')).startswith('/v/'):
        continue
    gdir = os.path.join(cardread.PUBLIC_V, fr[0]['url'].split('/')[2])
    for vd in c.get('videos') or []:
        src = [x for x in glob.glob(os.path.join(d, f"video{vd['v']}.*")) if cardread.VIDEO.search(x)]
        if not src or not os.path.isdir(gdir):
            print(c.get('key'), 'video', vd['v'], 'skipped (source or frames folder missing)'); continue
        out = cardread.web_video(src[0], gdir, vd['v'])
        print(c.get('key'), 'video', vd['v'], '->', os.path.relpath(out, cardread.NS), f'{os.path.getsize(out) / 1e6:.1f} MB')
