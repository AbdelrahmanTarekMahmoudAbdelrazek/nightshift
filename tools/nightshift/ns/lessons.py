"""Night Shift learns: after every lab job a retro turns what happened (rounds, misses, tool errors) into short GENERIC
lessons (lab, tooling, repro, fix, review). Later jobs get the most relevant lessons in their prompts, and each lesson
keeps score: used / helped (the job that used it succeeded). Lessons never carry a crash id or the crash's own frames, and
a job never sees lessons learned on its own crash (so blind tests stay blind). Store: knowledge/lessons.jsonl."""
import datetime as dt
import json
import os
import re

from . import config, llm

STORE = os.path.join(config.REPO, 'tools/nightshift/knowledge/lessons.jsonl')
KINDS = ('lab', 'tooling', 'repro', 'fix', 'review')


def load():
    out = []
    try:
        for l in open(STORE, encoding='utf-8'):
            l = l.strip()
            if l:
                out.append(json.loads(l))
    except FileNotFoundError:
        pass
    return out


def save(items):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + '\n')
    os.replace(tmp, STORE)


def _words(t):
    return {w for w in re.findall(r'[a-z][a-z0-9_]{3,}', (t or '').lower())}


def _clean(text, case_id, frames):
    """Drop a lesson that names its crash (id, 8-char id, its own stack functions): it would leak into a blind test."""
    t = text or ''
    if re.search(r'\b[0-9a-f]{8,32}\b', t) or case_id[:8] in t:
        return None
    for f in frames or []:
        fn = f.split('::')[-1].split('(')[0]
        if len(fn) > 5 and fn in t:
            return None
    return t.strip()[:400] or None


def retro(cfg, case_id, frames, job_lines, outcome, log=print):
    """Ask the model for 0-6 generic lessons from one job's log. Returns the lessons added."""
    text = '\n'.join(job_lines)[-30000:]
    prompt = ('# Retro after a Night Shift lab job\nBelow is the job log of an automated crash repro/fix run on an Android '
              f'lab phone (outcome: {outcome}). Write 0 to 6 LESSONS that would make the NEXT job on a DIFFERENT crash faster '
              'or more reliable. Good lessons are about the lab phone, the automation harness, how to reach screens, how '
              'to make races fire, what makes a fix pass the lab check or the code review, and tool mistakes to avoid. '
              'Each lesson: one or two plain sentences, generic (NO crash ids, NO names of this crash\'s stack functions, '
              'NO hex addresses), actionable, true according to the log. Skip anything only true for this one crash.\n\n'
              f'# Job log\n```\n{text}\n```\n'
              '# Answer: ONLY a ```json block: {"lessons": [{"kind": "lab|tooling|repro|fix|review", "text": "...", '
              '"keywords": ["3-6 words a later job would contain"]}]}')
    ans = llm.run('crash-analysis', prompt, cfg, os.path.join(config.REPO, 'tools/nightshift/out/lessons'),
                  f'retro.{case_id[:8]}.{dt.datetime.now():%m%d-%H%M}', timeout=600)
    m = re.findall(r'```json\n(.*?)```', ans or '', re.S)
    try:
        got = json.loads(m[-1] if m else ans).get('lessons') or []
    except (ValueError, TypeError, AttributeError):
        got = []
    items, added = load(), []
    have = [_words(i['text']) for i in items]
    for g in got[:6]:
        t = _clean(g.get('text'), case_id, frames)
        kind = g.get('kind') if g.get('kind') in KINDS else 'tooling'
        if not t:
            continue
        w = _words(t)
        if any(len(w & h) >= 0.7 * max(1, min(len(w), len(h))) for h in have):   # near-duplicate: keep the older one
            continue
        it = {'id': f'L{len(items) + 1:03d}', 'kind': kind, 'text': t,
              'keywords': [k.lower() for k in (g.get('keywords') or [])][:6], 'source': case_id,
              'added': dt.datetime.now().isoformat(timespec='minutes'), 'used': 0, 'helped': 0}
        items.append(it)
        have.append(w)
        added.append(it)
    if added:
        save(items)
    log(f'lessons: {len(added)} new lesson(s) learned from this job (library: {len(items)})')
    if added and len(items) > 20:
        consolidate(cfg, log)
    return added


def relevant(case, kinds, exclude_case='', k=6):
    hay = _words(json.dumps({x: case.get(x) for x in ('title', 'subtitle', 'frames', 'last_screens', 'last_events')}, default=str))
    scored = []
    for it in load():
        if it.get('kind') not in kinds or (exclude_case and exclude_case in (it.get('sources') or [it.get('source')])):
            continue
        overlap = len(hay & (_words(it['text']) | set(it.get('keywords') or [])))
        prior = (it.get('helped', 0) + 1) / (it.get('used', 0) + 2)        # Laplace: unproven lessons start at 0.5
        scored.append((overlap + 2 * prior + (1 if it['kind'] in ('lab', 'tooling') else 0), it))
    scored.sort(key=lambda x: -x[0])
    return [it for _, it in scored[:k]]


def prompt_block(case, kinds, exclude_case='', k=6):
    its = relevant(case, kinds, exclude_case, k)
    if not its:
        return '', set()
    lines = '\n'.join(f'- [{it["kind"]}] {it["text"]} (helped {it.get("helped", 0)}/{it.get("used", 0)})' for it in its)
    return ('# Lessons Night Shift learned on OTHER crashes (use what applies; they are hints, not facts about this crash)\n'
            + lines + '\n\n'), {it['id'] for it in its}


def credit(ids, success):
    if not ids:
        return
    items = load()
    for it in items:
        if it['id'] in ids:
            it['used'] = it.get('used', 0) + 1
            it['helped'] = it.get('helped', 0) + (1 if success else 0)
    save(items)


def consolidate(cfg, log=print):
    """Keep the library small and true: merge near-duplicates, drop lessons another lesson contradicts with stronger
    evidence, keep scores (summed). Runs after a retro when the library grows."""
    items = load()
    if len(items) < 8:
        return items
    listing = '\n'.join(f'{it["id"]} [{it["kind"]}] (used {it.get("used",0)}, helped {it.get("helped",0)}) {it["text"]}' for it in items)
    prompt = ('# Consolidate a lessons library of an automated crash repro/fix system\nMerge lessons that say the same thing '
              'into one clear lesson. When two lessons contradict, keep the one that is better supported or more specific '
              'and say why in "dropped". Keep every distinct, useful lesson. Do not invent facts.\n\n'
              f'# Lessons\n{listing}\n\n'
              '# Answer: ONLY a ```json block: {"lessons": [{"from": ["L001","L019"], "kind": "lab|tooling|repro|fix|review", '
              '"text": "...", "keywords": ["..."]}], "dropped": [{"id": "L001", "why": "..."}]}')
    ans = llm.run('crash-analysis', prompt, cfg, os.path.join(config.REPO, 'tools/nightshift/out/lessons'),
                  f'consolidate.{dt.datetime.now():%m%d-%H%M}', timeout=600)
    m = re.findall(r'```json\n(.*?)```', ans or '', re.S)
    try:
        j = json.loads(m[-1] if m else ans)
    except (ValueError, TypeError):
        log('lessons: consolidate answer unreadable, library unchanged')
        return items
    by = {it['id']: it for it in items}
    out, n = [], 0
    for g in j.get('lessons') or []:
        src = [by[i] for i in g.get('from') or [] if i in by]
        if not src or not (g.get('text') or '').strip():
            continue
        n += 1
        out.append({'id': f'L{n:03d}', 'kind': g.get('kind') if g.get('kind') in KINDS else src[0]['kind'],
                    'text': g['text'].strip()[:400], 'keywords': [k.lower() for k in (g.get('keywords') or [])][:6],
                    'source': sorted({s['source'] for s in src})[0] if len({s['source'] for s in src}) == 1 else 'several',
                    'sources': sorted({s['source'] for s in src}), 'merged_from': [s['id'] for s in src],
                    'added': min(s['added'] for s in src), 'used': sum(s.get('used', 0) for s in src),
                    'helped': sum(s.get('helped', 0) for s in src)})
    if len(out) < 3:
        log('lessons: consolidate returned too little, library unchanged')
        return items
    os.makedirs(os.path.join(config.REPO, 'tools/nightshift/out/lessons'), exist_ok=True)
    save_path = os.path.join(config.REPO, 'tools/nightshift/out/lessons', f'before_consolidate.{dt.datetime.now():%m%d-%H%M}.jsonl')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(json.dumps(i, ensure_ascii=False) for i in items) + '\n')
    save(out)
    log(f'lessons: consolidated {len(items)} -> {len(out)} (dropped: '
        + '; '.join(f'{d.get("id")}: {str(d.get("why",""))[:60]}' for d in (j.get("dropped") or [])[:4]) + ')')
    return out
