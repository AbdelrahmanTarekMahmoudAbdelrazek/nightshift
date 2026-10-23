"""Self-check for every analysis, before it reaches the board. No human in the loop.

1. Deterministic checks (code, no model): every cited file:line exists, every claim that code is missing is re-checked
   in the repo, every function named appears in the evidence, structure and confidence rules hold, evidence was complete.
2. Independent reviewer pass (skill analysis-review): a second Claude reads evidence + answer and lists factual errors,
   contradictions with team knowledge, missed blocking threads.
3. If anything is wrong, the analysis is redone with the problems listed (max 2 rounds). The board shows the result:
   passed / passed after N fixes / issues remain (with the list).
"""
import json
import os
import re

from . import config, llm, locate

RE_FILELINE = re.compile(r'((?:[\w./-]+/)?[\w.-]+\.(?:cpp|h|hpp|cc|kt|java)):(\d+)')
RE_FUNC = re.compile(r'\b((?:[A-Z][A-Za-z0-9_]*::)+~?[A-Za-z_][A-Za-z0-9_]*)')
RE_MISSING = re.compile(r'(not (?:in|found in|available in|present in) (?:this|the) repo|source (?:is )?not (?:in|available)|'
                        r'not in this repository|cannot see the (?:source|code))', re.I)
TEXT_KEYS = ('summary', 'root_cause', 'trigger', 'evidence', 'fix_direction', 'repro', 'timeline', 'hypotheses', 'open_questions')


def _text(a):
    return json.dumps({k: a.get(k) for k in TEXT_KEYS}, default=str)


def _resolve(path, index):
    """-> (repo path, text of that file as shipped or in the working copy, or None)."""
    p = path.lstrip('./')
    if '/' not in p:
        p = index.get(p, p)
    if locate.sha():
        from . import source
        txt = source.read(p, locate.sha())
        if txt:
            return p, txt
    full = os.path.join(config.REPO, p)
    return p, (open(full, errors='replace').read() if os.path.exists(full) else None)


def checks(a, ev, file_index):
    """Deterministic problems + code the redo should see. Returns (issues, extra_code)."""
    issues, extra = [], []
    text = _text(a)
    evtext = json.dumps(ev, default=str)
    # 1. cited file:line must exist
    for path, ln in set(RE_FILELINE.findall(text)):
        p, txt = _resolve(path, file_index)
        if txt is None and os.path.basename(path) in evtext:
            continue          # cited from the stack itself (Looper.java, MessageQueue.java, SDK files): not ours to check
        if txt is None:
            issues.append({'claim': f'{path}:{ln}', 'problem': 'file does not exist in the shipped code', 'fix': 'cite a real file:line from `code`'})
            continue
        n = txt.count('\n') + 1
        if int(ln) > n:
            issues.append({'claim': f'{path}:{ln}', 'problem': f'line {ln} is past the end of {p} ({n} lines)', 'fix': 'cite the real line'})
    # 2. "not in this repo" claims are re-checked
    sents = re.split(r'(?<=[.;])\s+', text)
    for k, sent in enumerate(sents):
        if RE_MISSING.search(sent):                 # "Its source is not in this repo." -> function named just before
            for fn in set(RE_FUNC.findall((sents[k - 1] if k else '') + ' ' + sent)):
                r = locate.locate_native(fn + '(')
                if r and r.get('found'):
                    issues.append({'claim': sent.strip()[:200], 'problem': f'{fn} IS in the repo at {r["file"]}:{r["line"]} (body added to `code`)',
                                   'fix': f'read {fn} and name the exact statement that faults'})
                    extra.append({'func': fn, 'file': r['file'], 'line': r['line'], 'body': r.get('body', '')[:3500],
                                  'callers': (r.get('callers') or [])[:8]})
    for fn in ev.get('code_not_in_repo') or []:          # the search may have timed out when the evidence was built
        if '::' in fn and not any(x['func'] == fn for x in extra):
            r = locate.locate_native(fn)
            if r and r.get('found'):
                extra.append({'func': fn, 'file': r['file'], 'line': r['line'], 'body': r.get('body', '')[:3500],
                              'callers': (r.get('callers') or [])[:8]})
                issues.append({'claim': f'code for {fn}', 'problem': f'it was missing from the evidence but is at {r["file"]}:{r["line"]} (now added)',
                               'fix': 'use its body'})
    # 3. functions named must be in the evidence (no invented frames)
    facts = json.dumps({k: a.get(k) for k in ('summary', 'root_cause', 'trigger', 'evidence', 'timeline', 'hypotheses')}, default=str)
    for fn in set(RE_FUNC.findall(facts)):         # proposals (fix_direction, open_questions) may name new code
        short = fn.split('::')[-1]
        if fn not in evtext and short not in evtext and not any(fn in x.get('body', '') or short in x.get('body', '') for x in extra):
            issues.append({'claim': fn, 'problem': 'this function is not in the stacks, threads, code or team knowledge', 'fix': 'remove it or show where it comes from'})
    # 4. structure + confidence rules
    hyps = a.get('hypotheses') or []
    if len(hyps) < 2 or not any(str(h.get('verdict')).startswith('reject') for h in hyps if isinstance(h, dict)):
        issues.append({'claim': 'hypotheses', 'problem': 'fewer than two hypotheses or none rejected', 'fix': 'test at least two and reject the weaker with evidence'})
    n_ev = (ev.get('all_events') or {}).get('events_in_this_crash') or 0
    strong = n_ev >= 2 or ev.get('team_knowledge') or ((ev.get('google_play') or {}) and n_ev >= 1)
    if str(a.get('confidence')).lower() == 'high' and not strong:
        issues.append({'claim': 'confidence: high', 'problem': f'only {n_ev} event and no team knowledge', 'fix': 'medium at most'})
    if (ev.get('problem') or {}).get('kind') == 'ANR' and ev.get('all_threads') and not re.search(r'thread', text, re.I):
        issues.append({'claim': 'root_cause', 'problem': 'ANR analysed without naming the thread the main thread waits for', 'fix': 'read all_threads'})
    return issues[:10], extra


def critic(a, ev, cfg, out_dir, tag):
    prompt = ('Review this analysis against its evidence. Answer with the JSON object from your instructions.\n\n'
              'EVIDENCE:\n' + json.dumps(ev, default=str)[:60000] + '\n\nANALYSIS:\n' + json.dumps(a, indent=1, default=str))
    from . import analyse as _an                       # blind test: the reviewer gets the same read block as the analysis
    txt = llm.run('analysis-review', prompt, cfg, out_dir, tag, deny=getattr(_an, 'BLIND_DENY', None))
    from .analyse import _json
    r = _json(txt) or {}
    return [i for i in (r.get('issues') or []) if isinstance(i, dict)][:8], r.get('verdict')
