"""30 Oct: "Still open?" for a reviewed PR's verified findings.

A review judges ONE commit (the PR head). Later code can fix a finding somewhere else: a newer commit on the target
branch, a newer release branch (CPP-1.25.2 -> CPP-1.26.0), or another PR (open or merged) that never mentions this one.
Nothing in Bitbucket links them, so the link is the CODE: each finding is anchored to the functions its cited lines sit
in, and every later piece of code that changes one of those functions is re-checked.

  1. anchors   : the functions of the finding's own line and of its scenario's proof and Simulator steps (review head)
  2. targets   : the head of the PR's target branch and of every NEWER release branch, plus PRs (open, or merged in the
                 last `days`) into those branches whose diff changes an anchor function. Plain code, no model.
  3. re-check  : the anchor functions identical to the reviewed code -> still open (no model). Changed -> the Simulator
                 walks the same scenario with the same start values on that code (~$1-2): it reaches the bug -> still
                 open; a line of the new code stops it -> fixed there; anything else -> changed, needs a look.
  4. result    : saved on the PR row as stillOpenJson (the PR page shows it on the scenario and the finding).

Read-only: Bitbucket is only read, nothing is posted. Results are cached by (finding, target commit, code) so the daily
run pays only for code that changed since the last check."""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess

from . import config, prvisual

OUT = os.path.join(config.REPO, 'tools/nightshift/out/pr')
CACHE = os.path.join(OUT, 'stillopen_cache.json')
REL = re.compile(r'^CPP-(\d+)\.(\d+)\.(\d+)$')
MAX_WALKS = 8                     # Simulator re-walks per run (cost guard); the rest say "changed, needs a look"


def _git(args, cwd, timeout=600, text=True):
    return subprocess.run(['git'] + args, cwd=cwd, capture_output=True, text=text, timeout=timeout)


def _bb_base(rec):
    u = str(rec.get('url') or '')
    return u.split('/pull-requests')[0] if '/pull-requests' in u else ''


def _commits(gd, head, tip, paths, base, n=5):
    """[{sha, subject, author, date, url}] of the commits after the reviewed head that changed `paths` (newest first)."""
    if not head or not tip or not paths:
        return []
    try:
        r = _git(['log', '--no-merges', '--format=%H%x09%s%x09%an%x09%ad', '--date=short', '-n', str(n), f'{head}..{tip}', '--'] + list(paths),
                 cwd=gd, timeout=120)
    except Exception:
        return []
    out = []
    for ln in (r.stdout or '').splitlines():
        p = ln.split('\t')
        if len(p) == 4:
            out.append({'sha': p[0][:12], 'subject': p[1][:120], 'author': p[2], 'date': p[3], 'url': f'{base}/commits/{p[0]}' if base else ''})
    return out


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class GitSrc:
    """Files of one commit straight from git (no checkout): the .path / .lines interface prvisual uses."""

    def __init__(self, gd, commit):
        self.gd, self.c, self._ls, self._cache = gd, commit, None, {}

    def files(self):
        if self._ls is None:
            r = _git(['ls-tree', '-r', '--name-only', self.c], self.gd)
            self._ls = r.stdout.split('\n') if r.returncode == 0 else []
        return self._ls

    def path(self, name):
        name = str(name or '').strip().lstrip('./')
        if not name:
            return ''
        fs = self.files()
        if name in fs:
            return name
        hits = [f for f in fs if f.endswith('/' + name)]
        return hits[0] if len(hits) == 1 else (min(hits, key=len) if hits else '')

    def lines(self, p):
        if p not in self._cache:
            r = _git(['show', f'{self.c}:{p}'], self.gd, text=False)
            self._cache[p] = r.stdout.decode('utf-8', 'replace').split('\n') if r.returncode == 0 else []
        return self._cache[p]


def _norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def function_line(src, path, fn):
    """1 Nov: line number (1-based) where `fn` is defined in `path` at src's commit, 0 if not found."""
    body = function_body(src, path, fn)
    p = src.path(path) if body else None
    if not p:
        return 0
    first = body.split('\n', 1)[0]
    for i, s in enumerate(src.lines(p)):
        if s == first:
            return i + 1
    return 0


def function_body(src, path, fn):
    """Text of function `fn` (C++ 'Class::name' or a bare name, or Kotlin) in `path` at src's commit, '' if not found.
    The definition line is found by name, the body by brace matching."""
    p = src.path(path)
    if not p or not fn:
        return ''
    L = src.lines(p)
    short = fn.split('::')[-1]
    rx = re.compile(r'(?:^|[\s*&:])' + re.escape(fn if '::' in fn else short) + r'\s*\(')
    for i, s in enumerate(L):
        if not rx.search(s) or s.rstrip().endswith(';'):
            continue
        if not (s.startswith(('fun ', 'override fun', 'private fun', 'internal fun', 'public fun')) or re.search(r'\bfun\s', s)
                or not s.startswith((' ', '\t')) or '::' in fn):
            continue
        depth, seen, out = 0, False, []
        for j in range(i, min(len(L), i + 1500)):
            t = L[j]
            out.append(t)
            if j > i + 3 and not seen:
                break                                   # a declaration or a call, not a definition
            depth += t.count('{') - t.count('}')
            seen = seen or '{' in t
            if seen and depth <= 0:
                return '\n'.join(out)
    return ''


def _has_pr_code(gd, head, base, tsrc, tcommit, refs):
    """1 Nov (#3189 on #3218, a Tone-map PR without AI BG): a target that does not contain the reviewed PR cannot have
    'fixed' its bug. True when the PR head is an ancestor of the target, or most of the finding's cited lines are there
    (a squash merge keeps the code, not the commits). -> (bool, found, total)"""
    try:
        if head and tcommit and _git(['merge-base', '--is-ancestor', head, tcommit], gd).returncode == 0:
            return True, 0, 0
    except Exception:
        pass
    found = total = 0
    for path, line, _c in refs:
        bp = base.path(path)
        if not bp:
            continue
        L = base.lines(bp)
        t = L[line - 1].strip() if 0 < line <= len(L) else ''
        if len(t) < 10 or t in ('{', '}', '};') or t.startswith(('//', '/*', '*')):
            continue
        total += 1
        tp = tsrc.path(path)
        if tp and t in {x.strip() for x in tsrc.lines(tp)}:
            found += 1
    return (total == 0 or found * 2 >= total), found, total


def _ref(r):
    """'VideoEngine.cpp:378' -> ('VideoEngine.cpp', 378) or None."""
    if not isinstance(r, str) or ':' not in r or not r.rsplit(':', 1)[1].isdigit():
        return None
    return r.rsplit(':', 1)[0], int(r.rsplit(':', 1)[1])


def items_of(rec):
    """Verified findings with their scenario and cited lines: [{finding, title, scenario, refs: [(path, line, code)]}]."""
    view = rec.get('view') or {}
    sc = {s.get('id'): s for s in view.get('scenarios') or []}
    link = {l.get('finding'): l.get('scenario') for l in view.get('finding_links') or [] if isinstance(l, dict)}
    out = []
    for i, f in enumerate(rec.get('findings') or []):
        if not isinstance(f, dict) or f.get('dropped') or f.get('tier') not in ('verified', 'suspected'):   # 1 Nov: suspected too
            continue
        sid = link.get(i) or next((k for k, s in sc.items() if s.get('finding') == i), None)
        s = sc.get(sid) or {}
        refs = []
        if f.get('file') and f.get('line'):
            refs.append((f['file'], int(f['line']), ''))
        npri = len(refs) or 1                            # the finding's own line (else the scenario's first proof step)
        for st in (s.get('proof') or {}).get('steps') or []:
            r = _ref(st[0] if st else None)
            if r:
                refs.append((r[0], r[1], st[3] if len(st) > 3 else ''))
        for st in ((s.get('proof') or {}).get('sim') or {}).get('steps') or []:
            r = _ref(st.get('line'))
            if r:
                refs.append((r[0], r[1], st.get('code') or ''))
        fc = s.get('fixCode') or {}
        fix = (fc.get('file'), int(fc['line']), '') if fc.get('file') and str(fc.get('line') or '').isdigit() else None
        if fix:
            refs.insert(0, fix); npri += 1                 # 1 Nov: the function the suggested fix edits leads the check
        out.append({'finding': i, 'title': f.get('title', ''), 'scenario': sid if s else None, 'refs': refs, 'sc': s, 'npri': npri,
                    'fixref': fix})
    return out


def anchors(item, src):
    """{(path, function)} of the item's cited lines at the reviewed commit (lines in other repos are left out)."""
    out = set()
    for path, line, _code in item['refs']:
        p = src.path(path)
        if not p:
            continue
        fn = prvisual.enclosing_function(src, p, line)
        if fn:
            out.add((p, fn))
    return out


_CALL = re.compile(r'([A-Za-z_]\w*)\s*\(')
_GENERIC = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'get', 'set', 'size', 'run', 'start', 'stop', 'load', 'store',
            'push_back', 'insert', 'erase', 'find', 'begin', 'end', 'move', 'lock', 'unlock', 'LOGI', 'LOGE', 'LOGW', 'LOGD'}


def called(diff):
    """Names of the functions a diff's changed lines call (a PR that changes a CALLER of an anchor is linked too)."""
    out = set()
    for f in prvisual.parse_diff(diff):
        for hk in f.get('hunks') or []:
            for l in hk.get('l') or []:
                if l and l[0] in ('+', '-'):
                    out |= {m for m in _CALL.findall(str(l[2] if len(l) > 2 else '')) if m not in _GENERIC and len(m) > 5}
    return out


def touched(diff, src):
    """{(path, function)} a unified diff changes, the functions read at the diff's new side (src)."""
    out = set()
    for f in prvisual.parse_diff(diff):
        p = src.path(f['path'])
        if not p:
            continue
        lines = set(f.get('added') or []) | {int(k) for k in (f.get('removed') or {}).keys() if str(k).isdigit()}
        for n in sorted(lines):
            fn = prvisual.enclosing_function(src, p, n)
            if fn:
                out.add((p, fn))
    return out


def release_after(dest, names):
    """Release branches at or after `dest` (CPP-x.y.z by version), oldest first; `dest` itself first even if not CPP."""
    m = REL.match(dest or '')
    rel = sorted((tuple(int(x) for x in REL.match(n).groups()), n) for n in names if REL.match(n))
    newer = [n for v, n in rel if m and v > tuple(int(x) for x in m.groups())]
    return [dest] + newer


# ---------------------------------------------------------------- Bitbucket + git (the worker's machine)

def _fetch(gd, branch, ref, log):
    from . import kotlinctx
    src = kotlinctx._remote_base() + (config.profile().get('main_repo') or 'video_gles3jni') + '.git'
    r = _git(['fetch', '--no-tags', src, f'+refs/heads/{branch}:{ref}'], gd, timeout=1800)
    if r.returncode:
        log(f'still-open: fetch of {branch} failed ({r.stderr.strip()[-160:]})')
        return ''
    return _git(['rev-parse', ref], gd).stdout.strip()


def targets_live(rec, days, log):
    """Branch heads (target + newer releases) and recent PRs into them, from Bitbucket; commits fetched into git."""
    from . import bitbucket
    gd = config.REPO
    names = [b['name'] for b in bitbucket.branches(limit=60, query='CPP-')]
    dests = release_after(rec.get('dest') or '', names)
    out = []
    for b in dests:
        h = _fetch(gd, b, f'refs/nightshift/so/{b}', log)
        if h:
            out.append({'kind': 'branch', 'label': b, 'branch': b, 'commit': h})
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S')
    for p in bitbucket.recent_prs(dests, since):
        if str(p.get('num')) == str(rec.get('num') or rec.get('id')):
            continue
        if p.get('state') == 'OPEN' and p.get('source'):
            if not _fetch(gd, p['source'], f"refs/nightshift/so/pr-{p['num']}", log):
                continue
        out.append({'kind': 'pr', 'label': f"#{p['num']}", 'num': p['num'], 'title': p.get('title', ''), 'state': p.get('state', ''),
                    'branch': p.get('dest', ''), 'commit': p.get('head', ''), 'url': p.get('url', ''), 'author': p.get('author', ''),
                    'files': None, '_diff': lambda n=p['num']: bitbucket.pr_diff(n)})
    return gd, out


# ---------------------------------------------------------------- the check

def _walk(item, rec, tgt, gd, cfg, log):
    """The Simulator walks the item's scenario on the target commit. Returns (state, note, stopped_at)."""
    from . import prreview
    s = item['sc'] or {}
    sim = (s.get('proof') or {}).get('sim') or {}
    wt = os.path.join(prreview.TREES, 'so-' + tgt['commit'][:12])
    if not os.path.isdir(wt):
        r = _git(['worktree', 'add', '--detach', '--force', wt, tgt['commit']], gd)
        if r.returncode:
            return 'changed', f'could not check out {tgt["commit"][:10]}: {r.stderr.strip()[:120]}', ''
    item_json = {'id': s.get('id'), 'title': s.get('title'), 'q': s.get('q'), 'kind': s.get('kind'), 'why': s.get('why'),
                 'entry': s.get('entry'), 'needs': s.get('needs'),
                 'proof': [{'line': q[0], 'text': q[1]} for q in (s.get('proof') or {}).get('steps') or []]}
    prompt = ("# Your role: Simulator\n## Re-check on newer code\n"
              f"This scenario was verified in PR #{rec.get('num') or rec.get('id')} ({rec.get('title', '')}) at commit "
              f"{str(rec.get('head', ''))[:12]}. The code on disk is now {tgt['label']} ({tgt.get('title') or tgt.get('branch')}) "
              f"at {tgt['commit'][:12]}, which changed the functions this scenario runs through. Walk the SAME scenario with "
              "the SAME start values on THIS code. If the new code makes the bad outcome impossible, end with \"guard\" and "
              "stopped_at = the file:line that stops it. Do not invent a new scenario.\n\n"
              "## The walk on the reviewed code\n```json\n" + json.dumps(sim, indent=1)[:12000] + "\n```\n\n"
              "## Scenarios to simulate\n```json\n" + json.dumps([item_json], indent=1)[:20000] + "\n```\n")
    tag = f"pr{rec.get('id')}.stillopen.{s.get('id')}.{tgt['commit'][:8]}"
    txt = prreview._call('pr-simulate', prompt, cfg, tag, wt, tools='Read,Grep,Glob', timeout=1500)
    sims = [x for x in (prreview._json(txt).get('sims') or []) if isinstance(x, dict)]
    if not sims:
        return 'changed', 'the Simulator gave no walk', ''
    sm = sims[0]
    src = GitSrc(gd, tgt['commit'])

    def ok(ref, code=None):
        r = _ref(ref)
        p = src.path(r[0]) if r else ''
        if not p or not 0 < r[1] <= len(src.lines(p)):
            return False
        return code is None or (_norm(code) and _norm(code) in _norm(src.lines(p)[r[1] - 1]) or _norm(src.lines(p)[r[1] - 1]) in _norm(code))
    steps = [x for x in sm.get('steps') or [] if isinstance(x, dict)]
    good = [x for x in steps if ok(x.get('line'), x.get('code'))]
    end = sm.get('end')
    if end == 'outcome' and steps and len(good) / len(steps) >= 0.6:
        return 'open', str(sm.get('outcome') or '')[:300], ''
    if end == 'guard' and ok(sm.get('stopped_at')):
        return 'fixed', str(sm.get('note') or sm.get('outcome') or '')[:300], sm.get('stopped_at')
    why = f"needs: {sm.get('unknown')}" if end == 'unknown' else f"only {len(good)}/{len(steps)} walked lines match"
    return 'changed', why[:300], ''


_DEF = re.compile(r'^[\w:<>,\*&\s]*?\b([A-Z]\w*)::(\w+)\s*\([^;]*$')


def action_anchors(item, src, files):
    """1 Nov: the engine functions of the scenario's user ACTION (split_media, changeVisualMediaLayer, restore_media...).
    A fix often lands there (CPP-1.26.0 drops the build jobs in split_media), not on the lines the bug cites."""
    acts = prvisual.scenario_actions(item.get('sc') or {})
    if not acts:
        return set()
    out = set()
    for p in files:
        for ln in src.lines(p) if p else []:
            m = _DEF.match(ln)
            if m and prvisual._anorm(m.group(2)) in acts:
                out.add((p, f'{m.group(1)}::{m.group(2)}'))
    return out


def check(rec, cfg, log=print, targets=None, gd=None, days=14, walk=True, field=None):
    """Still-open result for every verified finding of `rec` (a saved PR review). targets/gd given -> no Bitbucket
    (tests); walk=False -> no model (changed code says 'changed, needs a look')."""
    items = items_of(rec)
    if not items:
        return {'at': _now(), 'items': [], 'targets': [], 'note': 'no verified findings'}
    if targets is None:
        gd, targets = targets_live(rec, days, log)
    base = GitSrc(gd, rec['head'])
    cache = {}
    try:
        cache = json.load(open(CACHE))
    except Exception:
        pass
    walks = 0
    eng = [x for x in base.files() if x.endswith(('player/VideoEngine.cpp', 'player/VisualTimeLine.cpp'))]
    for it in items:
        it['anchors'] = sorted(anchors(it, base) | action_anchors(it, base, sorted({p for p, _ in anchors(it, base)} | set(eng))))
        # a PR is linked through a CALLER only for the finding's main functions (its own line, the first proof step),
        # not for helpers every edit calls (enter_edit_state...)
        it['primary'] = sorted(anchors(dict(it, refs=it['refs'][:it['npri']]), base))
    want = {a for it in items for a in it['anchors']}
    for t in targets:                                   # which anchor functions each PR changes (plain code)
        if t['kind'] != 'pr':
            continue
        try:
            diff = t['_diff']() if callable(t.get('_diff')) else t.get('_diff') or ''
            tsrc0 = GitSrc(gd, t['commit']) if t.get('commit') else None
            allt = touched(diff, tsrc0) if tsrc0 else set()
            t['touch'] = sorted(allt & want)
            # a PR that changes a function which CALLS an anchor, or a same-named wrapper (VideoEngine::duplicate_media
            # around VisualTimeLine::duplicate_media), is linked too: the fix is often one level up
            t['callmap'] = {fn: sorted({m for m in _CALL.findall(function_body(tsrc0, p, fn)) if m not in _GENERIC and len(m) > 5}
                                       | {fn.split('::')[-1]}) for p, fn in allt}
        except Exception as e:
            log(f"still-open: {t['label']}: diff not read ({str(e)[:100]})")
            t['touch'] = []
    out = []
    for it in items:
        res = []
        for t in targets:
            via = ''
            if t['kind'] == 'pr':
                if set(map(tuple, t.get('touch') or [])) & set(it['anchors']):
                    via = 'changes ' + ', '.join(sorted({fn for _, fn in set(map(tuple, t['touch'])) & set(it['anchors'])}))
                else:
                    hit = sorted({(tf, fn) for _, fn in it['primary'] for tf, cs in (t.get('callmap') or {}).items()
                                  if fn.split('::')[-1] in cs and tf != fn})
                    if not hit:
                        continue
                    via = '; '.join(f'changes {tf}, which calls {fn}' for tf, fn in hit[:2])
            tsrc = GitSrc(gd, t['commit'])
            diffs = []
            for p, fn in it['anchors']:
                a, b = function_body(base, p, fn), function_body(tsrc, p, fn)
                if _norm(a) != _norm(b):
                    diffs.append({'path': p, 'fn': fn, 'gone': not b})
            r = {'kind': t['kind'], 'label': t['label'], 'branch': t.get('branch', ''), 'commit': t['commit'][:12],
                 'url': t.get('url') or (f"{_bb_base(rec)}/branch/{t.get('branch')}" if t.get('branch') and _bb_base(rec) else ''),
                 'title': t.get('title', ''), 'prState': t.get('state', ''), 'author': t.get('author', ''),
                 'changed': [d['fn'] for d in diffs], 'via': via}
            has, nf, nt = _has_pr_code(gd, rec.get('head'), base, tsrc, t['commit'], it['refs'])
            if not has:
                r.update(state='absent', note=f"does not contain this PR's code ({nt - nf} of {nt} cited lines missing), so fixed/open cannot be judged there")
                res.append(r)
                continue
            if not it['anchors']:
                r.update(state='changed', note='no cited line in this repo to compare')
            elif not diffs:
                r.update(state='open', note='same code as in the review')
            elif all(d['gone'] for d in diffs):
                # 1 Nov: the reviewed code is not on that branch at all (e.g. a branch without this PR merged): nothing to compare
                r.update(state='absent', note="this branch does not have the reviewed code (" + ', '.join(d['fn'].split('::')[-1] for d in diffs[:3]) + ')')
            else:
                key = hashlib.sha1(json.dumps([rec.get('id'), it['finding'], t['commit'],
                                               [function_body(tsrc, p, fn) for p, fn in it['anchors']]]).encode()).hexdigest()
                if key in cache:
                    r.update(cache[key], cached=True)
                elif walk and it['sc'] and walks < MAX_WALKS:
                    walks += 1
                    log(f"still-open: finding {it['finding']}: re-walking {it['scenario']} on {t['label']} ({t['commit'][:10]})")
                    try:
                        st, note, at = _walk(it, rec, t, gd, cfg, log)
                    except Exception as e:
                        st, note, at = 'changed', f'walk failed: {str(e)[:120]}', ''
                    ra = _ref(at)                                # keep 'stops at' only when it is a real code line there
                    if ra:
                        tp = tsrc.path(ra[0]); TL = tsrc.lines(tp) if tp else []
                        if not (0 < ra[1] <= len(TL)) or len(TL[ra[1] - 1].strip()) < 2 or TL[ra[1] - 1].strip() in ('{', '}'):
                            at = ''
                    r.update(state=st, note=note, stoppedAt=at)
                    cache[key] = {'state': st, 'note': note, 'stoppedAt': at}
                else:
                    r.update(state='changed', note='changed: ' + ', '.join(d['fn'] for d in diffs)
                             + ('' if walk else ' (not re-walked in this run)'))
            if diffs and r.get('state') != 'absent':           # 1 Nov: where (function + file:line on that branch) the code changed
                r['where'] = [{'fn': d['fn'], 'file': os.path.basename(d['path']), 'line': function_line(tsrc, d['path'], d['fn'])}
                              for d in diffs if not d['gone']][:4]
            if diffs and r.get('state') != 'absent':           # the commits that changed those files since the review
                r['commits'] = _commits(gd, rec.get('head'), t['commit'], sorted({d['path'] for d in diffs}), _bb_base(rec))
            if it.get('fixref') and diffs:
                fp = base.path(it['fixref'][0]); ffn = prvisual.enclosing_function(base, fp, it['fixref'][1]) if fp else None
                r['fixFn'] = ffn or ''; r['fixFnChanged'] = bool(ffn and any(d['fn'] == ffn for d in diffs))
            res.append(r)
        fixed = [r for r in res if r['state'] == 'fixed']
        on_dest = next((r for r in res if r['kind'] == 'branch' and r['branch'] == rec.get('dest')), None)
        summary = ('fixed' if fixed and on_dest and on_dest['state'] == 'fixed' else 'fixed-elsewhere' if fixed
                   else 'changed' if any(r['state'] == 'changed' for r in res) else 'open')
        # where it was fixed, for the page: branch / PR / commit links
        fixedOn = [{'label': r['label'], 'kind': r['kind'], 'url': r.get('url', ''), 'commit': r['commit'],
                    'commits': (r.get('commits') or [])[:3], 'where': r.get('where') or [], 'stoppedAt': r.get('stoppedAt', '')} for r in fixed]
        out.append({'finding': it['finding'], 'title': it['title'], 'scenario': it['scenario'],
                    'anchors': [fn for _, fn in it['anchors']], 'summary': summary, 'results': res, 'fixedOn': fixedOn})
    try:
        os.makedirs(OUT, exist_ok=True)
        json.dump(cache, open(CACHE, 'w'), indent=0)
    except Exception:
        pass
    nfield = None
    if field is not None:                            # 1 Nov: refresh 'seen in the field' with today's crashes and their logs
        try:
            nfield = prvisual.field_match_src(rec.get('view') or {}, base, field)
        except Exception as e:
            log(f'field match skipped: {str(e)[:160]}')
    return {'at': _now(), 'dest': rec.get('dest', ''), 'walks': walks, 'field': nfield,
            'targets': [{'kind': t['kind'], 'label': t['label'], 'branch': t.get('branch', ''), 'commit': t['commit'][:12],
                         'touch': [fn for _, fn in t.get('touch') or []] if t['kind'] == 'pr' else None} for t in targets],
            'items': out}


def run(db, cfg, arg, log=print):
    """Worker entry: arg = '<pr id>|still' (one PR) or 'all|still' (every PR row with a verified finding)."""
    pid = str(arg).split('|', 1)[0]
    ids = [d.id for d in db.collection('prs').stream()] if pid == 'all' else [pid]
    done = 0
    for i in ids:
        d = db.collection('prs').document(i).get()
        rec = d.to_dict() if d.exists else None
        if not rec or rec.get('stage') != 'reviewed':
            continue
        for k in list(rec):
            if k.endswith('Json') and rec[k] and rec.get(k[:-4]) is None:
                try:
                    rec[k[:-4]] = json.loads(rec[k])
                except Exception:
                    pass
        if not items_of(rec):
            continue
        log(f'PR #{i}: still-open check of {len(items_of(rec))} verified finding(s)')
        try:
            from . import prreview as _pr
            field = _pr._field_index(_pr._board_crashes(db))
        except Exception as e:
            field = None
            log(f'field index skipped: {str(e)[:160]}')
        res = check(rec, cfg, log, field=field)
        upd = {'stillOpenJson': json.dumps(res, ensure_ascii=False), 'stillOpenAt': res['at']}
        if res.get('field') is not None and rec.get('view'):
            upd['viewJson'] = json.dumps(rec['view'], ensure_ascii=False)
            try:                                     # the local copy too (a later redraw starts from it)
                lp = os.path.join(_pr.OUT, f'{i}.json')
                if os.path.exists(lp):
                    lr = json.load(open(lp))
                    byid = {x.get('id'): x for x in rec['view'].get('scenarios') or []}
                    for x in (lr.get('view') or {}).get('scenarios') or []:
                        y = byid.get(x.get('id')) or {}
                        for k in ('field', 'fieldStrength'):
                            if k in y:
                                x[k] = y[k]
                            else:
                                x.pop(k, None)
                    json.dump(lr, open(lp, 'w'), ensure_ascii=False)
            except Exception:
                pass
            nf = [s for s in rec['view'].get('scenarios') or [] if s.get('field')]
            log(f"PR #{i}: seen in the field: {sum(1 for s in nf if s.get('fieldStrength') == 'path')} same path, "
                f"{sum(1 for s in nf if s.get('fieldStrength') != 'path')} same function only")
        db.collection('prs').document(i).set(upd, merge=True)
        n = {k: sum(1 for x in res['items'] if x['summary'] == k) for k in ('open', 'fixed', 'fixed-elsewhere', 'changed')}
        log(f"PR #{i}: still open {n['open']} · fixed {n['fixed']} · fixed on another branch {n['fixed-elsewhere']} · "
            f"changed, needs a look {n['changed']} ({res['walks']} Simulator re-walk(s))")
        done += 1
    return done
