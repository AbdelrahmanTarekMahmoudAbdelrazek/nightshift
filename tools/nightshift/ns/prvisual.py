"""PR review, visual part: turn the pr-visual model answer into the data the six-page PR page (board/pr.html) shows.
All code shown on the page is read from the PR head checkout and the diff here, never written by the model: the model
only picks files, line ranges and lines. Pure functions, no network and no model calls."""
import os
import re

SEVS = ('blocker', 'major', 'minor', 'suggestion')
MAX_CODE = 400_000          # bytes of whole-diff data kept on the Firestore row (the row limit is 1 MB)


def parse_diff(diff):
    """[{path, name, add, del, hunks: [{h, l: [[mark, newLine|'' , text]]}], added: [n], removed: {n: [text]}}]"""
    files, cur, h, o, n = [], None, None, 0, 0
    for line in (diff or '').split('\n'):
        if line.startswith('diff --git '):
            m = re.match(r'diff --git a/(\S+) b/(\S+)', line)
            path = m.group(2) if m else line.split()[-1][2:]
            cur = {'path': path, 'name': path.split('/')[-1], 'add': 0, 'del': 0, 'hunks': []}
            files.append(cur)
            h = None
            continue
        if cur is None:
            continue
        m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if m:
            o, n = int(m.group(1)), int(m.group(2))
            h = {'h': line[:200], 'l': []}
            cur['hunks'].append(h)
            continue
        if h is None or line.startswith('\\'):
            continue
        if line.startswith('+'):
            h['l'].append(['+', n, line[1:]]); n += 1; cur['add'] += 1
        elif line.startswith('-'):
            h['l'].append(['-', '', line[1:]]); o += 1; cur['del'] += 1
        elif line.startswith(' '):
            h['l'].append([' ', n, line[1:]]); o += 1; n += 1
    for f in files:
        added, removed, pend = [], {}, []
        for hh in f['hunks']:
            for mk, ln, tx in hh['l']:
                if mk == '-':
                    pend.append(tx)
                    continue
                if pend:
                    removed.setdefault(str(ln), []).extend(pend)
                    pend = []
                if mk == '+':
                    added.append(ln)
        f['added'], f['removed'] = added, removed
    return files


class Src:
    """Files of the PR head checkout, matched by path or by file name, plus the diff markers for each."""

    def __init__(self, wt, files):
        self.wt, self.files, self.cache = wt, {f['path']: f for f in files}, {}

    def path(self, name):
        name = str(name or '').strip().lstrip('./')
        if name in self.files:
            return name
        hits = [p for p in self.files if p.endswith('/' + name) or p == name]
        if hits:
            return hits[0]
        if self.wt and os.path.isfile(os.path.join(self.wt, name)):
            return name
        return None

    def lines(self, path):
        if path not in self.cache:
            try:
                self.cache[path] = open(os.path.join(self.wt, path), encoding='utf-8', errors='replace').read().split('\n')
            except OSError:
                self.cache[path] = []
        return self.cache[path]

    def marks(self, path):
        f = self.files.get(path) or {}
        return set(f.get('added') or []), f.get('removed') or {}


def code_lines(src, ranges, hot=(), cap=400):
    """Excerpt for ranges [[file, a, b], ...]: [mark, line, text, 'hot'?]; gaps between ranges are '…' rows."""
    hotset = {(src.path(h[0]), int(h[1])) for h in (hot or []) if isinstance(h, (list, tuple)) and len(h) >= 2
              and str(h[1]).lstrip('-').isdigit()}
    out, last_path = [], None
    for r in ranges or []:
        if not (isinstance(r, (list, tuple)) and len(r) >= 3):
            continue
        p = src.path(r[0])
        if not p:
            continue
        L = src.lines(p)
        try:
            a, b = max(1, int(r[1])), min(len(L), int(r[2]))
        except (TypeError, ValueError):
            continue
        if b < a:
            continue
        added, removed = src.marks(p)
        if out:
            out.append([' ', '', '…' + ('  ' + p.split('/')[-1] if p != last_path else '')])
        elif len({src.path(x[0]) for x in ranges if isinstance(x, (list, tuple)) and x}) > 1:
            out.append([' ', '', p.split('/')[-1]])
        last_path = p
        for n in range(a, b + 1):
            for t in removed.get(str(n), []):
                out.append(['-', '', t])
            row = ['+' if n in added else ' ', n, L[n - 1]]
            if (p, n) in hotset:
                row.append('hot')
            out.append(row)
            if len(out) >= cap:
                out.append([' ', '', '… (cut: open the whole PR diff below)'])
                return out
    return out


def step_code(src, step):
    """The real source at a replay step's file:line (1-3 lines), or ''."""
    try:
        n = int(step.get('line') or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 1:      # 1 Nov: Kotlin/Java steps often give the line only in their note ("FilterResponse.kt:65 runs ...")
        base = str(step.get('file') or '').split('/')[-1]
        for fm, ln in re.findall(r'([\w.\-]+\.(?:kt|java|cpp|cc|c|hpp|h|glsl|frag|vert|json|xml)):(\d+)', f"{step.get('m') or ''} {step.get('label') or ''}"):
            if not base or fm == base:
                n = int(ln)
                if not step.get('file'):
                    step['file'] = fm
                break
    p = src.path(step.get('file')) if step.get('file') else None
    if not p or n < 1:
        return ''
    L = src.lines(p)
    if n > len(L):
        return ''
    got = [L[n - 1]]
    kt = str(p).endswith(('.kt', '.kts'))                # Kotlin has no ';': go on only while the statement is open
    while len(got) < 3 and n + len(got) - 1 < len(L) and (re.search(r'[(,=+\-*/.&|]\s*$', got[-1]) if kt
                                                          else not re.search(r'[;{}]\s*(//.*)?$', got[-1])):
        got.append(L[n + len(got) - 1])
    pad = min(len(x) - len(x.lstrip()) for x in got if x.strip()) if any(x.strip() for x in got) else 0
    return '\n'.join(x[pad:] for x in got)


def _steps(src, mode, hunk_ids):
    if not isinstance(mode, dict):
        return None
    st = [s for s in (mode.get('steps') or []) if isinstance(s, dict)]
    if not st:
        return None
    for s in st:
        for k in ('from', 'to'):
            try:
                s[k] = int(s.get(k) or 0)
            except (TypeError, ValueError):
                s[k] = 0
        if s.get('hunk') not in hunk_ids:
            s.pop('hunk', None)
        code = step_code(src, s)
        if code:
            s['code'] = code
        else:
            s.pop('code', None)
        if s.get('line') and not s.get('hunk'):
            s.pop('line', None)
        s.setdefault('cap', s.get('label') or '')
        s['c'] = s.get('c') if s.get('c') in ('ink', 'ok', 'risk', 'bad', 'mut') else 'ink'
    bars = [b for b in (mode.get('bars') or []) if isinstance(b, dict) and b.get('cls') in ('bar-hold', 'bar-wait', 'bar-ok', 'bar-risk')]
    return _tidy({'steps': st, 'bars': bars})


def _tidy(m):
    """Keep replays readable whatever the model wrote: max 9 steps, 2 chips a step, labels and tags capped, at most 4
    tags (the last ones: the outcome) and 3 bars."""
    st = m['steps'][:9]
    for s in st:
        s['chips'] = [str(c)[:40] for c in (s.get('chips') or [])][:2]
        if s.get('label') and len(str(s['label'])) > 48:
            s['label'] = str(s['label'])[:46].rstrip() + '…'
        if s.get('crashText'):
            s['crashText'] = str(s['crashText'])[:90]
        if isinstance(s.get('tag'), dict):
            s['tag']['text'] = str(s['tag'].get('text') or '')[:64]
            if not s['tag']['text']:
                s.pop('tag')
    tagged = [s for s in st if s.get('tag')]
    for s in tagged[:-4]:
        s.pop('tag')
    bars = [b for b in m['bars'] if int(b.get('from') or 0) < len(st)][:3]
    for b in bars:
        b['from'] = int(b.get('from') or 0)
        b['to'] = min(int(b.get('to') or 0), len(st) - 1)
        b['text'] = str(b.get('text') or '')[:56]
        if b.get('end'):
            b['end'] = str(b['end'])[:28]
    return {'steps': st, 'bars': bars}


def _replay(src, r, hunk_ids, default_modes):
    if not isinstance(r, dict):
        return None
    cols = [c for c in (r.get('cols') or []) if isinstance(c, (list, tuple)) and c][:5]
    if len(cols) < 2:
        return None
    cols = [[str(c[0]), str(c[1]) if len(c) > 1 else ''] for c in cols]
    out = {'cols': cols, 'modes': {}}
    modes = r.get('modes') if isinstance(r.get('modes'), dict) else {}
    for k in ('bug', 'fix'):
        m = _steps(src, r.get(k), hunk_ids)
        if m:
            for s in m['steps']:
                s['from'] = min(max(s['from'], 0), len(cols) - 1)
                s['to'] = min(max(s['to'], 0), len(cols) - 1)
                if isinstance(s.get('tag'), dict):
                    try:
                        s['tag']['col'] = min(max(int(s['tag'].get('col') or 0), 0), len(cols) - 1)
                    except (TypeError, ValueError):
                        s.pop('tag')
            for b in m['bars']:
                try:
                    b['col'] = min(max(int(b.get('col') or 0), 0), len(cols) - 1)
                    b['from'], b['to'] = int(b.get('from') or 0), int(b.get('to') or 0)
                except (TypeError, ValueError):
                    b['col'] = 0
            out[k] = m
            out['modes'][k] = str(modes.get(k) or default_modes[k])
    if 'bug' not in out:
        if 'fix' not in out:
            return None
        out['bug'] = out.pop('fix')
        out['modes'] = {'bug': out['modes'].get('fix', default_modes['fix'])}
    return out


def link_sc(flow, scs):
    """A replay step that shows a scenario's problem carries "sc": that id. Keep only real ids (never a scenario's own),
    and colour the step and its tag by that scenario's tier: red when Verified, orange when Suspected."""
    tier = {s['id']: s['verdict'] for s in scs}
    for rp in [flow] + list(scs):
        for k in ('bug', 'fix'):
            for st in ((rp or {}).get(k) or {}).get('steps') or []:
                sc = str(st.get('sc') or '')
                if sc not in tier or (rp is not flow and sc == rp.get('id')):
                    st.pop('sc', None)
                    continue
                st['sc'] = sc
                if tier[sc] in ('verified', 'suspected'):
                    c = 'bad' if tier[sc] == 'verified' else 'risk'
                    st['c'] = c
                    if isinstance(st.get('tag'), dict):
                        st['tag']['c'] = c


def _repro(rp):
    """QA's steps to reproduce: {setup, steps[], expected, actual}; dropped when there are no steps."""
    if not isinstance(rp, dict):
        return None
    steps = [str(x).strip()[:220] for x in (rp.get('steps') or []) if str(x).strip()][:9]
    if not steps:
        return None
    out = {'setup': str(rp.get('setup') or '')[:300], 'steps': steps, 'expected': str(rp.get('expected') or '')[:300],
           'actual': str(rp.get('actual') or '')[:300]}
    for k, n in (('when', 300), ('math', 400), ('control', 400)):     # the exact trigger (card reviews)
        if str(rp.get(k) or '').strip():
            out[k] = str(rp[k]).strip()[:n]
    ed = [{k: str(e.get(k) or '')[:200] for k in ('case', 'numbers', 'result', 'line')} for e in (rp.get('edges') or [])
          if isinstance(e, dict) and (e.get('case') or e.get('numbers'))][:6]
    if ed:
        out['edges'] = ed
    return out


def _fix_code(fc):
    """The suggested fix as a small diff: {file, line, diff: '- old\n+ new'}; anything else is dropped."""
    if not isinstance(fc, dict) or not str(fc.get('diff') or '').strip():
        return None
    lines = [l.rstrip() for l in str(fc['diff']).replace('\r', '').split('\n')][:24]
    try:
        n = int(fc.get('line') or 0)
    except (TypeError, ValueError):
        n = 0
    return {'file': str(fc.get('file') or '')[:120], 'line': n, 'diff': '\n'.join(l[:160] for l in lines),
            'note': str(fc.get('note') or '')[:240]}


KINDS = ('always', 'timing', 'condition')
SEV = ('blocker', 'major', 'minor', 'suggestion')


def judged_severity(js, fallback=None):
    """Severity is graded by the judges, not the hunters. Of the confirming judges' grades the HIGHER counts, except
    that "blocker" needs every grading judge to say blocker (one judge alone cannot block a merge); then major.
    A judge that gave no grade does not count; with no grades at all the hunter's stays."""
    g = [x[5] for x in js if len(x) > 5 and x[5] in SEV]
    if not g:
        return fallback
    top = min(g, key=SEV.index)
    if top == 'blocker' and any(x != 'blocker' for x in g):
        top = 'major'
    return top
TIER_OF = {'verified': 'verified', 'suspected': 'suspected', 'safe': 'safe', 'unsafe': 'verified', 'unproven': 'suspected'}


def _proof_in(proof):
    """The hunter's evidence chain: [{file, line, code, text}] or [{text}] -> raw steps kept for the line check."""
    out = []
    for x in proof or []:
        if not isinstance(x, dict):
            continue
        try:
            n = int(x.get('line') or 0)
        except (TypeError, ValueError):
            n = 0
        out.append({'file': str(x.get('file') or '').strip(), 'line': n, 'code': str(x.get('code') or ''), 'text': str(x.get('text') or '')[:200]})
    return out[:14]


class Repo(Src):
    """Src that also finds files outside the diff by name (callers, headers, Kotlin) in the PR checkout."""

    def __init__(self, wt, files):
        super().__init__(wt, files)
        self._names = None

    def path(self, name):
        p = super().path(name)
        if p or not self.wt:
            return p
        name = str(name or '').strip().lstrip('./')
        if self._names is None:                       # tracked files only: no build output, backups or tool copies
            self._names = {}
            try:
                import subprocess
                tracked = subprocess.run(['git', '-C', self.wt, 'ls-files'], capture_output=True, text=True, timeout=60).stdout.split('\n')
            except Exception:
                tracked = []
            for rel in tracked:
                if rel and not rel.startswith('tools/'):
                    self._names.setdefault(rel.split('/')[-1], []).append(rel)
        hits = [h for h in self._names.get(name.split('/')[-1], []) if h.endswith(name)]
        if len(hits) == 1:
            return hits[0]
        if not hits and EXTRA_ROOTS:                  # the app's Kotlin/Java repos (read for this review): absolute path
            global _EXTRA_IDX
            if _EXTRA_IDX is None:
                _EXTRA_IDX = {}
                for root in EXTRA_ROOTS:
                    for d, dirs, fs in os.walk(root):
                        dirs[:] = [x for x in dirs if x not in ('build', '.git', '.gradle', 'node_modules')]
                        for fn in fs:
                            if fn.endswith(('.kt', '.java', '.xml', '.glsl', '.frag', '.h', '.json')):
                                _EXTRA_IDX.setdefault(fn, []).append(os.path.join(d, fn))
            k = [h for h in _EXTRA_IDX.get(name.split('/')[-1], []) if h.endswith(name)]
            return k[0] if len(k) == 1 else None
        return None


EXTRA_ROOTS = []        # set by the PR review: folders of the app's Kotlin repos, so Kotlin file:line refs can be checked
_EXTRA_IDX = None


def _norm(t):
    return re.sub(r'\s+', ' ', str(t or '')).strip()


def check_line(src, file, line, code):
    """No model: does file:line exist and contain the quoted code? -> (ok, ref, what is really there)."""
    p = src.path(file) if file else None
    ref = (p.split('/')[-1] if p else str(file or '?').split('/')[-1]) + ':' + str(line or '?')
    if not p:
        return False, ref, 'file not found in the PR checkout'
    L = src.lines(p)
    if not line or line < 1 or line > len(L):
        return False, ref, f'the file has {len(L)} lines'
    got = L[line - 1]
    if not _norm(code):
        return False, ref, 'no code quoted to check'
    return (_norm(code) in _norm(got)), ref, got.strip()[:120]


def pathcheck(view, wt, diff, why_prefix=''):
    """Code-path check (no AI). For every scenario, every cited file:line must exist and contain the quoted code.
    A scenario with a cited line that does not match is dropped (by 'Code-path check'); nothing else is judged here.
    Steps that are not code stay as 'not code (judges only)'. Returns the number of lines checked."""
    src = Repo(wt, parse_diff(diff))
    keep, dropped, n = [], list(view.get('dropped') or []), 0
    for s in view.get('scenarios') or []:
        raw = (s.get('proof') or {}).get('steps') or []
        if raw and isinstance(raw[0], list):          # already checked once (old review): re-check its refs
            raw = [{'file': x[0].rsplit(':', 1)[0], 'line': int(x[0].rsplit(':', 1)[1]) if x[0] and ':' in x[0] and x[0].rsplit(':', 1)[1].isdigit() else 0,
                    'code': x[3] if len(x) > 3 else '', 'text': x[1]} if x[0] else {'text': x[1]} for x in raw]
        steps, bad = [], None
        for x in raw:
            if x.get('file') and x.get('line'):
                n += 1
                ok, ref, got = check_line(src, x['file'], x['line'], x.get('code'))
                steps.append([ref, x.get('text') or x.get('code') or '', ok, x.get('code') or ''])
                if not ok and bad is None:
                    bad = f"Line did not match: cited {ref} for \"{_norm(x.get('code'))[:60]}\", but " + \
                          (f":{x['line']} is \"{got}\"." if got and not got.startswith(('file not', 'the file', 'no code')) else got + '.')
            else:
                steps.append([None, x.get('text') or '', None, ''])
        s['proof'] = {'steps': steps, 'judges': (s.get('proof') or {}).get('judges') or []}
        if bad:
            dropped.append({'by': 'Code-path check', 'title': s.get('title', ''), 'why': why_prefix + bad, 'id': s.get('id')})
        elif not any(st[0] for st in steps) and s.get('verdict') == 'verified':
            s['verdict'] = 'suspected'                # nothing checkable: it cannot be Verified
            s['proof']['note'] = 'No code line cited, so it cannot be Verified.'
            keep.append(s)
        else:
            keep.append(s)
    view['scenarios'], view['dropped'] = keep, dropped
    return n


def check_findings(findings, view, wt, diff):
    """No model: a finding that no scenario proves gets its own line check: its file:line must exist and contain a
    line of its quoted evidence. No quote or no line -> 'unchecked' (shown, labelled, never blocks). A quote that does
    not match -> dropped. Returns the indexes of findings that need the judges."""
    src = Repo(wt, parse_diff(diff))
    linked = {s.get('finding') for s in view.get('scenarios') or [] if s.get('finding') is not None}
    need = []
    for i, f in enumerate(findings or []):
        f.pop('dropped', None)
        if i in linked:
            f['tier'] = 'linked'
            continue
        try:
            n = int(f.get('line') or 0)
        except (TypeError, ValueError):
            n = 0
        quotes = [q for q in re.split(r'\n|\.\.\.|…', str(f.get('evidence') or '')) if len(_norm(q)) >= 8]
        if not f.get('file') or not n or not quotes:
            f['tier'], f['check'] = 'unchecked', 'no file:line with quoted code to check'
            continue
        res = [check_line(src, f['file'], n, q) for q in quotes[:4]]
        ok = [r for r in res if r[0]]
        if ok:
            f['check'] = ok[0][1]
            need.append(i)
        else:
            f['tier'], f['dropped'] = 'dropped', True
            view.setdefault('dropped', []).append({'by': 'Code-path check', 'title': f.get('title', ''), 'finding': i,
                                                   'why': f"Line did not match: cited {res[0][1]}, but it is \"{res[0][2]}\"."})
    return need


def finding_tiers(findings, view, votes, judge_names, wt, diff):
    """Tier of every finding: from its scenario if one proves it, else from its own line check and the judges' votes
    (same rule as scenarios). Dropped ones are listed under 'Dropped by the checks'."""
    src = Repo(wt, parse_diff(diff))
    by_sc = {}                                       # several scenarios can prove one finding: the strongest one counts
    rank = {'verified': 0, 'suspected': 1, 'safe': 2}
    for s in view.get('scenarios') or []:
        k = s.get('finding')
        if k is not None and (k not in by_sc or rank.get(s.get('verdict'), 3) < rank.get(by_sc[k].get('verdict'), 3)):
            by_sc[k] = s
    gone = {d.get('id'): d for d in view.get('dropped') or [] if d.get('id')}
    for i, f in enumerate(findings or []):
        if f.get('tier') == 'linked':
            s = by_sc.get(i)
            if s and s.get('severity') in SEV:
                f['severity_hunter'], f['severity'] = f.get('severity'), s['severity']
            if s:
                if s.get('pre_existing'):
                    f['pre_existing'] = True
                f['tier'] = s['verdict'] if s['verdict'] != 'safe' else 'dropped'
                if f['tier'] == 'dropped':
                    f['dropped'] = True
                    view.setdefault('dropped', []).append({'by': 'Judges', 'title': f.get('title', ''), 'finding': i,
                                                           'why': 'Its scenario was checked and holds (Safe).'})
                elif s['verdict'] == 'verified':
                    f['kind'] = s.get('kind', '')
            else:                                     # its scenario was dropped
                f['tier'], f['dropped'] = 'dropped', True
            continue
        if f.get('tier') in ('unchecked', 'dropped'):
            continue
        js = _votes(src, votes, judge_names, 'f%d' % i)
        f['judges'] = [{'judge': x[0], 'vote': x[1], 'note': x[2], 'refs': x[3]} for x in js]   # dicts: Firestore rejects arrays in arrays
        conf = sum(1 for x in js if x[1] == 'confirmed')
        ref = sum(1 for x in js if x[1] == 'refuted')
        if not js:
            f['tier'] = 'suspected'
        elif ref and not conf:
            f['tier'], f['dropped'] = 'dropped', True
            view.setdefault('dropped', []).append({'by': 'Judges', 'title': f.get('title', ''), 'finding': i,
                                                   'why': 'Refuted: ' + ' '.join(x[2] for x in js if x[1] == 'refuted')[:400]})
        else:
            fx = next((x[6] for x in js if len(x) > 6 and x[6] and x[1] == 'confirmed'), None) or \
                 next((x[6] for x in js if len(x) > 6 and x[6] and x[1] == 'unsure'), None) or {}
            if fx.get('title'):                       # the judges set the scope: text rewritten to what they confirmed
                f['title_hunter'], f['title'] = f.get('title'), fx['title'][:200]
            if fx.get('problem'):
                f['problem_hunter'], f['problem'] = f.get('problem'), fx['problem']
            same = fx.get('same_as')
            if same and any(sc.get('id') == same for sc in view.get('scenarios') or []):
                f['tier'], f['dropped'] = 'dropped', True     # the same user outcome as a scenario: counted once, there
                view.setdefault('dropped', []).append({'by': 'Judges', 'title': f.get('title', ''), 'finding': i,
                                                       'why': f'Same outcome as scenario {same}: merged into it.'})
                continue
            # no scenario, no Verified: a finding proves a user outcome only through a scenario with its own proof
            f['tier'] = 'suspected'
            if conf == len(js):
                f['note'] = 'Both judges confirmed it, but it has no scenario of its own, so it is not Verified.'
            sv = judged_severity(js)
            if sv:
                f['severity_hunter'], f['severity'] = f.get('severity'), sv
    return findings


def weakest_kind(kinds):
    """'timing' (a race) beats 'condition' (only if X) beats 'always': never claim more certainty than anyone gave."""
    k = [x for x in kinds if x in KINDS]
    return 'timing' if 'timing' in k else 'condition' if 'condition' in k else 'always'


def code_pack(wt, diff, cmap, cap=45000):
    """The code every hunter needs, read once from the checkout (no model): each changed function's body and a few
    lines around each caller the change map found. Saves every hunter re-reading the same files with tools."""
    src = Repo(wt, parse_diff(diff))
    out, seen, size = [], set(), 0

    def add(path, a, b, label):
        nonlocal size
        key = (path, a, b)
        if key in seen or size > cap:
            return
        seen.add(key)
        L = src.lines(path)
        a, b = max(1, a), min(len(L), b)
        if b < a:
            return
        block = f"// {label}: {path}:{a}-{b}\n" + '\n'.join(f"{n:5d}  {L[n - 1]}" for n in range(a, b + 1))
        out.append(block)
        size += len(block)
    for f in (cmap or {}).get('functions') or []:
        p = src.path(f.get('file'))
        try:
            n = int(f.get('line') or 0)
        except (TypeError, ValueError):
            n = 0
        if not p or n < 1:
            continue
        L = src.lines(p)
        depth, end, opened = 0, min(len(L), n + 120), False   # function body: to the matching brace, max 120 lines
        for k in range(n - 1, min(len(L), n + 120)):
            depth += L[k].count('{') - L[k].count('}')
            opened = opened or '{' in L[k]
            if opened and depth <= 0:
                end = k + 1
                break
        add(p, n - 3, end, 'changed ' + str(f.get('name') or ''))
        for c in (f.get('callers') or [])[:6]:
            m = re.match(r'\s*([\w./-]+):(\d+)', str(c))
            q = src.path(m.group(1)) if m else None
            if q:
                add(q, int(m.group(2)) - 8, int(m.group(2)) + 8, 'caller of ' + str(f.get('name') or ''))
    return '\n\n'.join(out)


def _votes(src, votes, judge_names, item):
    js = []
    for j in judge_names:
        v = (votes.get(j) or {}).get(item) or {}
        ev = [e for e in (v.get('evidence') or []) if isinstance(e, str) and ':' in e]
        good = [e for e in ev if e.rsplit(':', 1)[1].isdigit() and src.path(e.rsplit(':', 1)[0])
                and 0 < int(e.rsplit(':', 1)[1]) <= len(src.lines(src.path(e.rsplit(':', 1)[0])))]
        vote = v.get('vote') if v.get('vote') in ('confirmed', 'refuted', 'unsure') else 'unsure'
        note = str(v.get('note') or '')[:300]
        if vote != 'unsure' and not good:
            vote, note = 'unsure', (note + ' (vote ignored: no evidence line that exists)').strip()
        fix = {k: str(v[k]).strip()[:600] for k in ('title', 'q', 'problem', 'same_as', 'when') if isinstance(v.get(k), str) and v[k].strip()}
        js.append([j, vote, note, good[:4], v.get('kind') if v.get('kind') in KINDS else '',
                   v.get('severity') if v.get('severity') in SEV and vote in ('confirmed', 'unsure') else '', fix])
    return js


def tiers(view, votes, judge_names, wt, diff, findings=None):
    """Final tier from the hunter's claim and the judges' votes. votes: {judge: {scenario id: vote}}.
    A vote counts only with evidence lines that exist. Verified needs both judges to confirm; a refutation with no
    confirmation drops it; Safe needs a confirmation and no refutation; everything else is Suspected."""
    src = Repo(wt, parse_diff(diff))
    keep, dropped = [], list(view.get('dropped') or [])
    for s in view.get('scenarios') or []:
        if (s.get('proof') or {}).get('judged'):
            keep.append(s)                            # judged in an earlier run and its lines still match
            continue
        js = _votes(src, votes, judge_names, s.get('id'))
        conf = sum(1 for x in js if x[1] == 'confirmed')
        ref = sum(1 for x in js if x[1] == 'refuted')
        claim = s.get('verdict')
        s['proof']['judges'] = [x[:4] for x in js]
        s['proof']['judged'] = bool(js)
        if not js:
            if claim == 'verified':
                s['verdict'] = 'suspected'
            s['proof']['note'] = 'The judges did not answer, so nothing here is Verified.'
        elif claim in ('verified', 'suspected'):
            if ref and not conf:
                dropped.append({'by': 'Judges', 'title': s.get('title', ''), 'why': 'Refuted: ' + ' '.join(x[2] for x in js if x[1] == 'refuted')[:400], 'id': s.get('id')})
                continue
            s['verdict'] = 'verified' if conf == len(js) and len(js) >= 2 else 'suspected'   # two confirmations, any claim
            s['severity'] = judged_severity(js, s.get('severity'))
            if not any(w[0] in ('bad', 'risk') for w in s.get('why') or [] if w):
                s['verdict'] = 'safe'                 # a GOOD or harmless outcome ("1 pass instead of 3", "costs two getters")
                s['proof']['note'] = 'No problem in its reasons: shown as Safe' + (' (the effect is unmeasured)' if not conf else '') + '.'
            fx = next((x[6] for x in js if len(x) > 6 and x[6] and x[1] == 'confirmed'), None) or \
                 next((x[6] for x in js if len(x) > 6 and x[6] and x[1] == 'unsure'), None)
            if fx:                                    # a judge corrected the hunter's wording: the page shows the corrected one
                s['title'] = fx.get('title', s.get('title'))[:160]
                s['q'] = fx.get('q', s.get('q'))
                if fx.get('when') and isinstance(s.get('repro'), dict):   # a judge corrected the trigger condition
                    s['repro']['when'] = fx['when'][:300]
                    s['repro']['whenBy'] = 'corrected by a judge'
            if s['verdict'] == 'verified':
                s['kind'] = weakest_kind([s.get('kind')] + [x[4] for x in js])
        else:                                         # the hunter said Safe
            calm = not any(w[0] in ('bad', 'risk') for w in s.get('why') or [] if w)
            s['verdict'] = 'safe' if (conf or calm) and not ref else 'suspected'
            if s['verdict'] == 'safe' and not conf:
                s['proof']['note'] = 'No problem in its reasons and no judge refuted it: shown as Safe (not proven by the judges).'
        keep.append(s)
    extra = []                                       # a Safe scenario must not hide a risk inside it: split it out
    for s in keep:
        risky = [w for w in s.get('why') or [] if w and w[0] in ('bad', 'risk')]
        js_ = (s.get('proof') or {}).get('judges') or []
        if js_ and all(j[1] == 'confirmed' for j in js_):
            risky = []                               # every judge confirmed it Safe with that risk in view: not hidden
        if s.get('verdict') == 'safe' and risky:
            s['why'] = [w for w in s['why'] if not (w and w[0] in ('bad', 'risk'))] or s['why'][:1]
            extra.append({'id': s['id'] + 'r', 'title': 'Still open in "' + str(s.get('title', ''))[:90] + '": ' + str(risky[0][1]),
                          'q': risky[0][2], 'verdict': 'suspected', 'kind': s.get('kind'), 'why': risky,
                          'proof': {'steps': (s.get('proof') or {}).get('steps') or [], 'judges': [], 'judged': True,
                                    'note': 'Split out of a Safe scenario: its reasons named this risk, and no judge ruled on it.'},
                          'from': s.get('from'), 'repro': s.get('repro'), 'pre_existing': s.get('pre_existing')})
    view['scenarios'], view['dropped'] = keep + extra, dropped
    return view


def _fallback_replay(src, s):
    """A scenario the replay writer skipped still gets a simple replay: its proof chain, step by step."""
    st = []
    pr = s.get('proof') or []
    if isinstance(pr, dict):                          # already checked: [[ref, text, ok, code]]
        pr = [{'file': r[0].rsplit(':', 1)[0], 'line': int(r[0].rsplit(':', 1)[1]), 'text': r[1]} if r[0] and ':' in r[0]
              and r[0].rsplit(':', 1)[1].isdigit() else {'text': r[1]} for r in pr.get('steps') or []]
    for x in pr:
        if not isinstance(x, dict):
            continue
        txt = x.get('text') or x.get('code') or ''
        step = {'from': 0, 'to': 1, 'label': 'step %d' % (len(st) + 1), 'c': 'ink', 'cap': txt, 'm': txt}   # long text wraps in m
        if x.get('file') and x.get('line'):
            step.update({'file': x['file'], 'line': x['line'], 'label': str(x['file']).split('/')[-1] + ':' + str(x['line'])})
        st.append(step)
    if not st:
        return None
    st[-1]['c'] = 'bad' if s.get('claim', s.get('verdict')) in ('verified', 'unsafe') else 'risk' if s.get('claim', s.get('verdict')) != 'safe' else 'ok'
    return {'cols': [['What happens', ''], ['Code', 'cited lines']], 'bug': {'steps': st, 'bars': []}, 'modes': {'bug': 'Proof'}}


def build(view, wt, diff, findings, given=None):
    """Validate and complete the pr-visual answer. Returns (view, code).
    given: the hunters' merged scenarios. Then they ARE the scenarios (claim, kind, why, proof untouched) and the
    visual answer only supplies each one's replay, matched by id; one it skipped gets its proof chain as a replay."""
    files = parse_diff(diff)
    src = Repo(wt, files)          # 1 Nov: also finds files outside the diff (callers, Kotlin/Java) for the replay code lines
    v = dict(view or {})
    hunks = []
    for i, h in enumerate(v.get('hunks') or []):
        if not isinstance(h, dict):
            continue
        hid = str(h.get('id') or f'h-{i + 1}')
        lines = code_lines(src, h.get('show') or h.get('full'), h.get('hot'))
        if not lines:
            continue
        full = code_lines(src, h.get('full'), h.get('hot'), cap=300) if h.get('full') else []
        hunks.append({'id': hid, 'n': str(h.get('n') or ('–' if h.get('skip') else len(hunks) + 1)),
                      'title': str(h.get('title') or hid), 'file': str(h.get('file') or ''), 'range': str(h.get('range') or ''),
                      'note': str(h.get('note') or ''), 'skip': bool(h.get('skip')), 'lines': lines,
                      'fullLines': full if len(full) > len(lines) else [],
                      'links': [l for l in (h.get('links') or []) if isinstance(l, (list, tuple)) and len(l) >= 2]})
    hids = {h['id'] for h in hunks}
    v['hunks'] = hunks
    flow = _replay(src, v.get('flow'), hids, {'bug': 'Before', 'fix': 'With this PR'})
    if flow:
        flow['title'] = str((v.get('flow') or {}).get('title') or 'The main flow')
        flow['lead'] = str((v.get('flow') or {}).get('lead') or '')
    v['flow'] = flow
    scs = []
    if given is not None:
        rp = {str(x.get('id')): x for x in v.get('scenarios') or [] if isinstance(x, dict)}
        merged = []
        for i, g in enumerate(given):
            if not isinstance(g, dict):
                continue
            r = dict(rp.get(str(g.get('id'))) or _fallback_replay(src, g) or {})
            if not r:
                continue
            r.update({k: g.get(k) for k in ('id', 'title', 'q', 'finding', 'why', 'kind', 'proof', 'from', 'severity', 'repro', 'pre_existing', 'entry', 'needs', 'reach', 'severity_code', 'field', 'uiGate', 'blockerGate')})
            r['verdict'] = g.get('claim') or g.get('verdict')
            merged.append(r)
        v['scenarios'] = merged
    for i, s in enumerate(v.get('scenarios') or []):
        r = _replay(src, s, hids, {'bug': 'This PR', 'fix': 'Suggested fix'}) if isinstance(s, dict) else None
        if not r:
            continue
        verdict = TIER_OF.get(s.get('verdict'), 'suspected')
        try:
            fi = int(s.get('finding')) if s.get('finding') is not None else None
        except (TypeError, ValueError):
            fi = None
        r.update({'id': str(s.get('id') or f's{i + 1}'), 'title': str(s.get('title') or ''), 'q': str(s.get('q') or ''),
                  'verdict': verdict, 'finding': fi if fi is not None and 0 <= fi < len(findings or []) else None,
                  'why': [w for w in (s.get('why') or []) if isinstance(w, (list, tuple)) and len(w) >= 3],
                  'kind': s.get('kind') if s.get('kind') in KINDS else '',
                  'proof': s.get('proof') if isinstance(s.get('proof'), dict) else {'steps': _proof_in(s.get('proof')), 'judges': []},
                  'from': [str(x) for x in s.get('from') or []][:6], 'severity': s.get('severity') if s.get('severity') in SEV else None})
        if s.get('pre_existing'):
            r['pre_existing'] = True
        for k_ in ('reach', 'uiGate', 'blockerGate'):  # 29-30 Oct: the code checks' results survive a rebuild
            if isinstance(s.get(k_), dict):
                r[k_] = s[k_]
        if isinstance(s.get('field'), list) and s['field']:
            r['field'] = s['field']
        rp = _repro(s.get('repro'))
        if rp:
            r['repro'] = rp
        fc = _fix_code(s.get('fixCode'))
        if fc and verdict != 'safe':
            r['fixCode'] = fc
        scs.append(r)
    v['scenarios'] = scs
    sids = {s['id'] for s in scs} | {'flow'}
    link_sc(flow, scs)
    for h in hunks:
        h['links'] = [l for l in h['links'] if l[0] in sids]
    v['paths'] = [p for p in (v.get('paths') or []) if isinstance(p, dict) and p.get('steps')]
    for p in v['paths']:
        if p.get('cov') not in sids:
            p['cov'] = None
    for f in v.get('files') or []:
        for fn in (f.get('fns') or []) if isinstance(f, dict) else []:
            if isinstance(fn, dict) and fn.get('hunk') not in hids:
                fn.pop('hunk', None)
        if isinstance(f, dict):                      # real +/- counts from the diff, not the model's
            p = src.path(f.get('name'))
            if p and p in src.files:
                f['add'], f['del'] = src.files[p]['add'], src.files[p]['del']
    for r in v.get('ready') or []:
        if isinstance(r, dict) and r.get('sc') not in sids:
            r.pop('sc', None)
    links = {}
    for fl in v.get('finding_links') or []:
        try:
            k = int(fl.get('finding'))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= k < len(findings or []):
            links[k] = {'scenario': fl.get('scenario') if fl.get('scenario') in sids else None,
                        'hunk': fl.get('hunk') if fl.get('hunk') in hids else None, 'comment': str(fl.get('comment') or '')}
    v['finding_links'] = [dict(finding=k, **x) for k, x in sorted(links.items())]
    v['order'] = [o for o in (v.get('order') or []) if isinstance(o, dict) and o.get('hunk') in hids]
    code = {'files': [{'path': f['path'], 'name': f['name'], 'add': f['add'], 'del': f['del'], 'hunks': f['hunks']} for f in files]}
    size = len(str(code))
    if size > MAX_CODE:                              # keep the biggest files out first; the page links to Bitbucket for them
        for f in sorted(code['files'], key=lambda x: -len(str(x['hunks']))):
            if len(str(code)) <= MAX_CODE:
                break
            f['hunks'], f['cut'] = [], True
    return v, code


GATED = ('debug-only', 'no-ui', 'flag-off')


def reach(view, votes, judge_names, wt, diff, findings=None):
    """29 Oct (PR #3189: three 'major' scenarios, none happened in the app). After the tiers: can a user of the
    RELEASE build get there, and in what state? No model here, only the judges' answers:
    - a judge shows the only way in is debug-only / has no UI / is behind an off flag (an evidence line that exists)
      -> 'latent': severity capped at minor, so it never asks for changes;
    - no judge gives a release path for a major/blocker -> it cannot stay Verified (Suspected, 'path not shown');
    - 'needs' (a job still running, an empty cache, a first run) goes into the repro, so a tester sets that state."""
    src = Repo(wt, parse_diff(diff))

    def ok(e):
        if not (isinstance(e, str) and ':' in e and e.rsplit(':', 1)[1].isdigit()):
            return False
        p = src.path(e.rsplit(':', 1)[0])
        return bool(p) and 0 < int(e.rsplit(':', 1)[1]) <= len(src.lines(p))
    for s in view.get('scenarios') or []:
        if s.get('verdict') not in ('verified', 'suspected'):
            continue
        rs = [(votes.get(j) or {}).get(s.get('id')) or {} for j in judge_names]
        gate = [v for v in rs if v.get('reach') in GATED and any(ok(e) for e in v.get('reach_evidence') or [])]
        path = next((str(v.get('reach_path')).strip() for v in rs
                     if v.get('reach') == 'release' and str(v.get('reach_path') or '').strip()), '')
        needs = [str(v.get('needs')).strip() for v in rs if str(v.get('needs') or '').strip()]
        proof = s.setdefault('proof', {})
        if needs and isinstance(s.get('repro'), dict):
            s['repro']['needs'] = needs[0][:300]
            if needs[0][:60] not in str(s['repro'].get('setup') or ''):
                s['repro']['setup'] = (str(s['repro'].get('setup') or '') + ' Needs: ' + needs[0][:300]).strip()
        if gate:
            g = gate[0]
            s['reach'] = {'state': 'latent', 'gate': g.get('reach'), 'evidence': [e for e in g['reach_evidence'] if ok(e)][:3]}
            if s.get('severity') in ('blocker', 'major'):
                s['severity_code'] = s['severity']
                s['severity'] = 'minor'
            if not str(s.get('title', '')).startswith('Latent'):
                s['title'] = f"Latent ({g.get('reach')}): " + str(s.get('title', ''))
            proof['note'] = (str(proof.get('note') or '') + f" Not reachable in the release build ({g.get('reach')}: "
                             + ', '.join(s['reach']['evidence']) + '); kept as latent, minor.').strip()
        elif path:
            s['reach'] = {'state': 'release', 'path': path[:300]}
        elif s.get('severity') in ('blocker', 'major'):
            s['reach'] = {'state': 'unproven'}
            if s['verdict'] == 'verified':
                s['verdict'] = 'suspected'
            proof['note'] = (str(proof.get('note') or '') + ' No judge showed how a user reaches this in the release '
                             'build, so it is not Verified.').strip()
        k = s.get('finding')
        if findings and isinstance(k, int) and 0 <= k < len(findings) and s.get('reach'):
            f = findings[k]
            if s['reach']['state'] == 'latent' and f.get('severity') in ('blocker', 'major'):
                f['severity'], f['latent'] = 'minor', True
            if s['reach']['state'] == 'unproven' and f.get('tier') == 'verified':
                f['tier'] = 'suspected'
    return view


def _norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def sim_votes(view, sims, wt, diff):
    """29 Oct: the Simulator walks each problem scenario through the code with concrete values. No model here: every
    step's line must exist and hold the quoted code; the walk becomes the Simulator's vote, so a scenario is Verified
    only when the numbers also reach the outcome. outcome -> confirmed (the matched steps are the evidence); guard ->
    refuted at that line; unknown or a walk whose lines do not match -> unsure. base 'same' marks an old bug."""
    src = Repo(wt, parse_diff(diff))
    byid = {s.get('id'): s for s in view.get('scenarios') or []}
    out = {}

    def line_ok(ref, code=None):
        if not (isinstance(ref, str) and ':' in ref and ref.rsplit(':', 1)[1].isdigit()):
            return False
        p = src.path(ref.rsplit(':', 1)[0])
        n = int(ref.rsplit(':', 1)[1])
        if not p or not 0 < n <= len(src.lines(p)):
            return False
        if code is None:
            return True
        have, want = _norm(src.lines(p)[n - 1]), _norm(code)
        return bool(want) and (have == want or want in have or (len(have) > 8 and have in want))
    for sm in sims or []:
        if not isinstance(sm, dict) or sm.get('id') not in byid:
            continue
        s = byid[sm['id']]
        steps = [x for x in sm.get('steps') or [] if isinstance(x, dict)]
        good = [x for x in steps if line_ok(x.get('line'), x.get('code'))]
        ratio = len(good) / len(steps) if steps else 0
        end = sm.get('end') if sm.get('end') in ('outcome', 'guard', 'unknown') else 'unknown'
        note = str(sm.get('note') or '')[:240]
        if end == 'outcome' and good and ratio >= 0.6:
            vote, ev = 'confirmed', [x['line'] for x in good][-4:]
            note = (note + f" (walked {len(good)}/{len(steps)} lines: {str(sm.get('outcome') or '')[:120]})").strip()
        elif end == 'guard' and line_ok(sm.get('stopped_at')):
            vote, ev = 'refuted', [sm['stopped_at']]
            note = (note + f" (stopped at {sm['stopped_at']})").strip()
        else:
            vote, ev = 'unsure', []
            why = (f"needs: {sm.get('unknown')}" if end == 'unknown' and sm.get('unknown') else
                   f"only {len(good)}/{len(steps)} walked lines match the code" if steps else 'no walk')
            note = (note + f" ({why})").strip()
        out[sm['id']] = {'vote': vote, 'evidence': ev, 'note': note, 'kind': s.get('kind')}
        s.setdefault('proof', {})['sim'] = {
            'start': sm.get('start') if isinstance(sm.get('start'), dict) else {},
            'steps': [{k: x.get(k) for k in ('line', 'code', 'thread', 'state', 'branch')} for x in good][:25],
            'end': end, 'outcome': str(sm.get('outcome') or '')[:700], 'stopped_at': sm.get('stopped_at') or '',
            'unknown': str(sm.get('unknown') or '')[:400], 'base': sm.get('base') or '', 'matched': f"{len(good)}/{len(steps)}"}
        start = ', '.join(f"{k}={v}" for k, v in list((s['proof']['sim']['start'] or {}).items())[:6])
        s['proof']['note'] = (str(s['proof'].get('note') or '') + f" Simulator ({start}): " +
                              {'confirmed': 'reached the outcome', 'refuted': 'stopped by ' + str(sm.get('stopped_at')),
                               'unsure': 'could not finish'}[vote] + '.').strip()
        if vote == 'confirmed' and sm.get('base') == 'same':
            s['pre_existing'] = True
    return out


_FN_RX = re.compile(r'(?:^|[\s*&])((?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const)?\s*(?:noexcept)?\s*(?:->\s*[\w:<>]+\s*)?\{?\s*$')
_KT_RX = re.compile(r'\bfun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(')
_NOT_FN = {'if', 'for', 'while', 'switch', 'catch', 'return', 'sizeof', 'else'}


def enclosing_function(src, path, line):
    """Name of the function a cited line sits in (C++ 'Class::name' or Kotlin 'name'), by scanning up; '' if unknown."""
    p = src.path(path)
    if not p:
        return ''
    L = src.lines(p)
    for k in range(min(line, len(L)) - 1, max(-1, line - 400), -1):
        s = L[k]
        m = _KT_RX.search(s)
        if m:
            return m.group(1)
        if not s.startswith((' ', '\t')) or s.startswith(('[[', 'template')):
            m = _FN_RX.search(s.strip()) if '(' in s else None
            if m and m.group(1).split('::')[-1] not in _NOT_FN:
                return m.group(1)
    return ''


def _short(fn):
    fn = re.sub(r'\(.*$', '', str(fn or '')).strip()
    return fn.split('::')[-1].split('.')[-1]


def field_match(view, wt, diff, field):
    """30 Oct, smarter 1 Nov: see field_match_src."""
    return field_match_src(view, Repo(wt, parse_diff(diff)), field)


# 1 Nov: the user action a scenario is about, as the engine logs it (Crashlytics keeps the last native log lines of
# every crash: 'MsgChangeVisualMediaLayer: media_id 0 old_layer 2 new_layer 1' right before 2bc43cd6~e6a57918).
_ACT_WORDS = [(r'\bsplit', ('splitmedia', 'splitvideo', 'splitoverlay')),
              (r'\bdrag|\brow\b|another (timeline )?row|\blayer move|moves? .*to another layer', ('changevisualmedialayer', 'changemedialayer', 'moveitemtolayer')),
              (r'\bduplicat', ('duplicatemedia', 'duplicateoverlay')),
              (r'\bundo|\brestore', ('restoremedia', 'undo')),
              (r'\bdelet|\bremoves? the (clip|overlay)', ('deletemedia', 'detachmedia')),
              (r'\bsort|\breorder', ('sortmedia',)),
              (r'\btrim', ('trimmedia', 'trimvideo')),
              (r'\bspeed', ('changespeed', 'setspeed')),
              (r'\bleave|\bexit|\bback\b|destroy', ('destroyvideoenginecontext', 'ondestroy'))]
_LOGACT = re.compile(r'\bMsg([A-Z][A-Za-z]+)|VideoEngine::([a-z_A-Z]+)|Player\.([a-zA-Z]+)')


def _anorm(x):
    return re.sub(r'[^a-z]', '', str(x or '').lower())


def scenario_actions(s):
    """Normalised names of the user actions a scenario is about (from its title/question and its proof steps)."""
    txt = ' '.join([str(s.get('title') or ''), str(s.get('q') or '')]).lower()
    acts = set()
    for rx, names in _ACT_WORDS:
        if re.search(rx, txt):
            acts |= set(names)
    for st in (s.get('proof') or {}).get('steps') or []:
        for m in re.finditer(r'([A-Za-z_][A-Za-z0-9_]*(?:\.|::)?[A-Za-z_][A-Za-z0-9_]*)\s*\(', str(st[1] if len(st) > 1 else '')):
            n = _anorm(m.group(1).split('.')[-1].split('::')[-1])
            if any(n.startswith(a[:6]) for _, names in _ACT_WORDS for a in names):
                acts.add(n)
    return acts


def log_actions(lines):
    """[(normalised action, the log line)] from a crash's last log lines, newest last."""
    out = []
    for l in lines or []:
        l = l.get('message') if isinstance(l, dict) else str(l)
        for m in _LOGACT.finditer(l or ''):
            a = _anorm(next(g for g in m.groups() if g))
            if any(a.startswith(x[:8]) or x.startswith(a) for _, names in _ACT_WORDS for x in names):   # user actions only
                out.append((a, (l or '')[:160]))
    return out


def field_match_src(view, src, field):
    """A scenario is 'seen in the field' when the top frame of a crash users ALREADY had is a function its walk goes
    through. 1 Nov, two strengths instead of one:
      path      the crash's last log lines (before it crashed) show THIS scenario's user action (split, row move,
                duplicate, undo, delete...): users very likely took this path;
      function  only the crashing function is shared: the crash backs the scenario but does not tell which path.
    Frames below the top that are also in the walk raise the score. field = [{card, title, events, frames, actions}]."""
    n = 0
    for s in view.get('scenarios') or []:
        s.pop('field', None)
        if s.get('verdict') not in ('verified', 'suspected', 'unsafe', 'unproven'):
            continue
        refs = []
        for st in (s.get('proof') or {}).get('steps') or []:
            r = st[0] if st and isinstance(st[0], str) else ''
            if ':' in r and r.rsplit(':', 1)[1].isdigit():
                refs.append(r)
        refs += [x.get('line') for x in ((s.get('proof') or {}).get('sim') or {}).get('steps') or [] if x.get('line')]
        fns = []
        for r in refs:
            try:
                f = enclosing_function(src, r.rsplit(':', 1)[0], int(r.rsplit(':', 1)[1]))
            except Exception:
                f = None
            if f and _short(f) not in fns:
                fns.append(_short(f))
        if not fns:
            continue
        acts = scenario_actions(s)
        hits = []
        for c in field or []:
            top = [_short(x) for x in (c.get('frames') or [])[:3] if x]
            if not top or top[0] not in fns:
                continue
            chain = sum(1 for x in top if x in fns)
            la = log_actions(c.get('logs'))[-12:]
            # only the LAST user action before the crash counts (an older delete does not make an 'undo' path)
            seen = [(a, l) for a, l in la[-1:] if a in acts or any(a.startswith(x[:8]) or x.startswith(a[:8]) for x in acts)]
            other = [a for a, _ in la if a not in {x for x, _ in seen}]
            h = {'card': c.get('card'), 'title': str(c.get('title') or '')[:120], 'events': c.get('events'), 'frame': top[0],
                 'chain': chain, 'strength': 'path' if seen else 'function'}
            if seen:
                h['log'] = seen[-1][1]
            elif la:
                h['lastAction'] = la[-1][1]          # what the users did instead, right before the crash
            hits.append(h)
        if hits:
            hits.sort(key=lambda h: (h['strength'] != 'path', -h['chain'], -(h.get('events') or 0)))
            s['field'] = hits[:3]
            s['fieldStrength'] = hits[0]['strength']
            n += 1
    return n


def gate_checks(view, votes, judge_names, wt, diff, findings=None):
    """30 Oct. Two code rules after the judges:
    UI GATE: a judge showed (evidence line that exists) that the screen does not let the user do the action in the
      state the scenario needs (disabled control, blocking dialog, input locked while a job runs) and no judge showed it
      open -> not Verified, severity at most minor.
    BLOCKER GATE: a blocker stays a blocker only with ALL of: Verified (every judge), the Simulator reached the outcome
      with every walked line matching, reachable in the release build, new with this PR (not pre-existing, base walk not
      'same'), the screen allows it (some judge: ui_gate open), and likely (a judge says often, or the field already
      had it). Anything missing -> major, and the page says what was missing."""
    src = Repo(wt, parse_diff(diff))

    def ok(e):
        if not (isinstance(e, str) and ':' in e and e.rsplit(':', 1)[1].isdigit()):
            return False
        p = src.path(e.rsplit(':', 1)[0])
        return bool(p) and 0 < int(e.rsplit(':', 1)[1]) <= len(src.lines(p))
    for s in view.get('scenarios') or []:
        if s.get('verdict') not in ('verified', 'suspected'):
            continue
        vs = [(votes.get(j) or {}).get(s.get('id')) or {} for j in judge_names]
        blocked = [v for v in vs if v.get('ui_gate') == 'blocked' and any(ok(e) for e in v.get('ui_gate_evidence') or [])]
        opened = [v for v in vs if v.get('ui_gate') == 'open']
        proof = s.setdefault('proof', {})
        if blocked and not opened:
            ev = [e for e in blocked[0]['ui_gate_evidence'] if ok(e)][:2]
            s['uiGate'] = {'state': 'blocked', 'evidence': ev}
            s['verdict'] = 'suspected'
            if s.get('severity') in ('blocker', 'major'):
                s['severity'] = 'minor'
            proof['note'] = (str(proof.get('note') or '') + f" The screen does not allow this while the needed state holds ({', '.join(ev)}).").strip()
            continue
        if opened:
            s['uiGate'] = {'state': 'open'}
        if s.get('severity') != 'blocker':
            continue
        sim = proof.get('sim') or {}
        m = str(sim.get('matched') or '0/1').split('/')
        lik = [v.get('likelihood') for v in vs if v.get('likelihood')]
        need = {
            'verified by every judge': s.get('verdict') == 'verified',
            'the Simulator reached the crash on every walked line': sim.get('end') == 'outcome' and len(m) == 2 and m[0] == m[1] and m[0] != '0',
            'reachable in the release build': (s.get('reach') or {}).get('state') == 'release',
            'new with this PR': not s.get('pre_existing') and sim.get('base') != 'same',
            'the screen allows the action': bool(opened),
            'likely (often, or already seen in the field)': bool(s.get('field')) or ('often' in lik and 'rare' not in lik),
        }
        miss = [k for k, v in need.items() if not v]
        s['blockerGate'] = {'kept': not miss, 'missing': miss}
        if miss:
            s['severity'] = 'major'
            proof['note'] = (str(proof.get('note') or '') + ' Not a blocker: missing ' + '; '.join(miss) + '.').strip()
            k = s.get('finding')
            if findings and isinstance(k, int) and 0 <= k < len(findings) and findings[k].get('severity') == 'blocker':
                findings[k]['severity'] = 'major'
    return view
