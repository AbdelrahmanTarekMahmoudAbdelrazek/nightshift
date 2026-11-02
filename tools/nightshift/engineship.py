#!/usr/bin/env python3
"""Option A (28 Oct): ship a fix as soon as the ENGINE REPLAY proves it, without waiting for the real-tap repro.

When the engine replay crashed with every field frame and the early fix ran the same replay clean
(cases/<id>.earlyFix, out/patches/<id>.early.patch), this writes the normal hand-over for it:
  - an independent code review of the patch (fix-review skill),
  - the PR / Jira / Slack texts (changelog skill), saying plainly "engine-verified, real-tap video pending",
  - out/fix/<id>.json with status "fix-verified-engine" (what shipit.py crash-pr reads),
  - cases/<id>: status fix-verified-engine, engineVerified true, fixVerified stays false (that one means the phone).
Nothing is posted anywhere: the developer still clicks "Create draft PR". The real-tap proof (video + steps) keeps
running or runs later; when it verifies on the phone it overwrites this with status "fix-verified".

Usage:  python3 tools/nightshift/engineship.py <case id>
        (the worker calls run() itself when experiment.json turbo.ship_on_replay is true)"""
import json
import re
import os
import sys
import warnings

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def run(db, cfg, cid, log=print, worker=None, ref=None, rp=None):
    from ns import fixloop
    keep = os.path.join(fixloop.OUT, 'patches', f'{cid}.early.patch')
    if not os.path.exists(keep):
        raise SystemExit(f'no engine-verified fix for {cid}: {keep} is missing (the engine replay or the early fix did not pass)')
    case = (db.collection('cases').document(cid).get().to_dict() or {}) | {'id': cid}
    merged = {}
    for p in ('m-', 'm-play-', ''):
        merged = db.collection('merged').document(p + cid).get().to_dict() or {}
        if merged:
            break
    ef = case.get('earlyFix') or {}
    if case.get('fixVerified') or str(case.get('status', '')) == 'fix-verified':
        log(f'{cid[:8]}: already verified on the phone; nothing to do (the phone result is stronger)')
        return None
    note = ('Verified by ENGINE REPLAY on the lab phone: the unfixed build crashed with every frame of the field stack '
            'when the engine calls of the user were replayed; with this fix the same replay ran clean '
            f"({ef.get('note') or 'replay clean'}). The real-tap repro (video + steps) is still running or pending; "
            'it will be attached when it passes.')
    log(f'{cid[:8]}: independent review of the engine-verified fix ...')
    rev = fixloop.review(case, merged, cfg, keep, 'e')
    log(f"  review: {rev.get('verdict')}; {len(rev.get('blocking') or [])} blocking; {str(rev.get('summary', ''))[:200]}")
    # 28 Oct: up to N more rounds (turbo.ship_rounds, default 2) while the review blocks, or while the owner is the Kotlin
    # app but the fix has no Kotlin part. Each revision must pass the same engine replay again (only inside the worker,
    # which has the phone); the reviewer's points of every earlier round go into the next one.
    kmiss = fixloop._kneeds(case, merged, cfg) and not re.search(r'(?m)^\+\+\+ b/\S+\.(kt|java)$', open(keep, errors='replace').read())
    rounds = int(((worker._turbo() if worker is not None else {}) or {}).get('ship_rounds') or 2)
    hist = []
    for rnd in range(1, rounds + 1):
        if not ((rev.get('blocking') or kmiss) and worker is not None and rp):
            break
        why = []
        if rev.get('blocking'):
            why.append('Code review asked for changes (fix ALL of them):\n' + json.dumps(rev['blocking'], indent=1)[:5000])
        if kmiss:
            why.append('The root cause owner is app-java: add the Kotlin/Java fix at the caller (the cause); keep the engine '
                       'guard as the extra safety net.')
        hist.append(f'## engine-verified fix, round {rnd} (keep what it fixes)\n```diff\n{open(keep, errors="replace").read()[:7000]}\n```\n'
                    + '\n'.join(why))
        log(f'{cid[:8]}: fix round {rnd}/{rounds}: ' + ('review changes' if rev.get('blocking') else '') + (' + Kotlin part' if kmiss else ''))
        p2, _ans, err = fixloop.propose(case, merged, cfg, hist[-2:], f'x{rnd}', '.ship')
        if err or not p2:
            log(f'  revision not usable ({err}); keeping the last verified fix')
            continue
        from ns import author as _author
        c2 = dict(case, repro_dir=rp.get('dir') or '', reproRate='1/1')
        expect = rp.get('expect') or _author.expect_frames(case, (merged or {}).get('analysis') or {})
        ok, note2, _res = fixloop.verify_replay(worker, ref, c2, p2, rp, expect,
                                                int((worker._turbo() or {}).get('replay_verify_runs') or 9))
        log(f"  revision {'REPLAY-VERIFIED' if ok else 'not verified'}: {note2}")
        if not ok:
            hist[-1] += f'\nYour revision did not pass the engine replay: {note2}'
            continue
        import shutil
        shutil.copyfile(p2, keep)
        if os.path.exists(p2 + '.flags'):
            shutil.copyfile(p2 + '.flags', keep + '.flags')
        note = note.replace(str(ef.get('note') or 'replay clean'), note2)
        ef = dict(ef, note=note2)
        rev = fixloop.review(case, merged, cfg, keep, f'e{rnd + 1}')
        log(f"  review of round {rnd}: {rev.get('verdict')}; {len(rev.get('blocking') or [])} blocking")
        kmiss = fixloop._kneeds(case, merged, cfg) and not re.search(r'(?m)^\+\+\+ b/\S+\.(kt|java)$', open(keep, errors='replace').read())
    if worker is None and (rev.get('blocking') or kmiss):
        log('  (fix rounds need the lab phone: they run automatically inside the Reproduce job, not from the terminal)')
    # 28 Oct: the engine replay calls the engine directly, so it tests the ENGINE part only. A Kotlin part is honest-
    # labelled "proposed, not verified" until the real-tap repro + phone check run it.
    has_kt = bool(re.search(r'(?m)^\+\+\+ b/\S+\.(kt|java)$', open(keep, errors='replace').read()))
    if has_kt:
        note += (' IMPORTANT: the engine replay bypasses Kotlin, so it verified the ENGINE guard only; the Kotlin/Java part '
                 'is PROPOSED, NOT VERIFIED until the real-tap repro and the phone check run it.')
    log(f'{cid[:8]}: writing the PR / Jira / Slack hand-over ...')
    ho = fixloop.handover(case, merged, cfg, keep, note, rev)
    diff = open(keep, errors='replace').read()
    status = 'fix-verified-engine' if not rev.get('blocking') else 'fix-verified-engine-review-changes'
    fixloop._save(cid, {'status': status, 'patch': diff, 'note': note, 'review': rev, 'handover': ho,
                        'rounds': [{'round': 'early', 'result': 'replay-verified', 'note': ef.get('note', '')}]})
    db.collection('cases').document(cid).set({
        'status': status, 'patch': diff[:20000], 'fixVerified': False, 'engineVerified': True, 'fixNote': note,
        'kotlinVerified': False if has_kt else None,
        'review': rev, 'handover': ho}, merge=True)
    log(f'{cid[:8]}: READY: {status}. On the board: Ship it -> Create draft PR (nothing was posted). '
        'The real-tap video is attached later by the background proof.')
    return status


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    from ns import config, fire
    run(fire.client(), config.load(), sys.argv[1].strip())
