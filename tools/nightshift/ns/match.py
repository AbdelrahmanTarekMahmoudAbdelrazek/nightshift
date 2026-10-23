"""Map field evidence (breadcrumbs, native log sites, last screen) to stress scenarios.

Reads `@scenario(tags)` + function name + docstring straight from tools/stress/scenarios.py (no import, so no adb
needed). Scoring is a plain keyword table; the skill `scenario-match` may propose a NEW scenario when nothing
scores, and that proposal is reviewed like code.
"""
import re
from typing import Dict, List, Tuple

RE_DECO = re.compile(r"^@scenario\((.*)\)\s*$")
RE_DEF = re.compile(r"^def (\w+)\(")

# evidence token -> scenario tags (left side is matched case-insensitively against the evidence text)
KEYWORDS: Dict[str, Tuple[str, ...]] = {
    'split': ('split',), 'trim': ('split',), 'duration': ('split', 'seek'),
    'seek': ('seek',), 'scrub': ('seek',), 'getframe': ('seek',), 'get_frame': ('seek', 'play'),
    'export': ('export',), 'muxer': ('export',), 'encoder': ('export',), 'abort': ('abort',), 'cancel': ('abort',),
    'effect': ('effects',), 'webp': ('effects',), 'filter': ('effects',), 'renderer': ('effects', 'play'),
    'pause': ('play',), 'play': ('play',), 'render': ('play',), 'audio': ('audio',), 'oboe': ('audio',), 'soundtouch': ('audio',),
    'speed': ('speed',),
    'add_video': ('media', 'nightshift'), 'amediacodec_configure': ('media', 'nightshift'), 'media_add': ('media',),
    'failed to create visual media': ('media', 'nightshift'), 'out of range': ('media',), 'undo': ('undo',), 'redo': ('undo',),
    'destroy': ('lifecycle',), 'teardown': ('lifecycle',), 'onpause': ('lifecycle',), 'background': ('lifecycle',),
    'trim_memory': ('lifecycle',), 'msglooper': ('lifecycle', 'split'), '~': ('lifecycle',),
}


def load_scenarios(path: str) -> List[dict]:
    out, tags = [], None
    for line in open(path, encoding='utf-8'):
        m = RE_DECO.match(line)
        if m:
            tags = [t.strip().strip('\'"') for t in m.group(1).split(',') if t.strip()]
            continue
        m = RE_DEF.match(line)
        if m and tags is not None:
            out.append({'name': m.group(1), 'tags': set(tags)})
            tags = None
    return out


def evidence_tags(evidence: List[str]) -> Dict[str, int]:
    """Each keyword counts once however many log lines repeat it (log noise must not outvote a specific clue)."""
    text = '\n'.join(evidence).lower()
    score: Dict[str, int] = {}
    for kw, tags in KEYWORDS.items():
        if kw in text:
            for t in tags:
                score[t] = score.get(t, 0) + 1
    return score


def rank(scenarios: List[dict], tag_scores: Dict[str, int], top=5):
    """Score = sum over the scenario's tags of evidence x rarity (a tag on 1 scenario says more than one on 15)."""
    import math
    n = max(len(scenarios), 1)
    df: Dict[str, int] = {}
    for s in scenarios:
        for t in s['tags']:
            df[t] = df.get(t, 0) + 1
    ranked = []
    for s in scenarios:
        sc = sum(tag_scores.get(t, 0) * math.log(1 + n / df[t]) for t in s['tags'])
        if sc:
            ranked.append((round(sc, 1), s['name'], sorted(s['tags'])))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[:top]
