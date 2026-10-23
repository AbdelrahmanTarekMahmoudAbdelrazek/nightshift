"""Cross-match Google Play and Firebase Crashlytics issues (same crash seen by both consoles?).

For every issue on both lists it collects up to 20 sample events (device, date, build, crashed-thread frames),
then pairs a Play cluster with a Crashlytics issue when their crashed threads share program counters in the
app's own libraries (exact proof: same build => same pc), or the same top Java frame, backed by devices/dates.

Writes Firestore `merged/<id>`: one row per real problem with both consoles side by side, the proof, devices with
dates, and a link to the Crashlytics case (Pull / Reproduce / Fix run there). `pr` and `note` are kept across syncs.
Read-only on both consoles.
"""
import datetime as dt
import hashlib
import re
from collections import Counter

from . import crashlytics as cl
from . import groups as sgroups
from . import symbolize
from . import sync
from . import timeline

APP_LIBS = ('libMYJNILIB26.so', 'libc++_shared.so')          # pcs here are the app's own code: equal pc = same code


def _hex(a):
    try:
        return '0x%x' % int(str(a), 0 if str(a).startswith('0x') else 10)
    except (TypeError, ValueError):
        return ''


def _day(t):
    return (t or '')[:10]


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


# ------------------------------------------------------------------ Crashlytics samples

def fb_samples(cfg, issue_id, names, n=20):
    app = cfg['sources']['crashlytics_app_id']
    days = int(cfg['sources'].get('crashlytics_days', 30))
    out = []
    for e in cl.list_events(app, issue_id, names, days, n):
        s = cl.summarise_event(e)
        dev = e.get('device') or {}
        fr = s['frames'][:12]
        try:                                         # name the engine frames with that build's own .so
            symbolize.symbolize_frames(fr, s.get('version_code'), 'libMYJNILIB26.so', (s.get('version') or '').split(' ')[0])
        except Exception:
            pass
        out.append({'time': s['time'] or '', 'version': s['version'] or '', 'os': s['os'] or '',
                    'device': dev.get('displayName') or s['device'], 'model': dev.get('model') or '',
                    'maker': dev.get('manufacturer') or '', 'marketing': dev.get('marketingName') or '',
                    'pcs': [(f['lib'], _hex(f['address'])) for f in fr if f.get('lib') in APP_LIBS and f.get('address')],
                    'java': [f['func'] for f in fr if f.get('func') and '.' in f['func'] and '::' not in f['func']
                             and not f['func'].startswith('[') and ' ' not in f['func'] and not str(f.get('lib') or '').endswith('.so')][:5],
                    'funcs': [(f"{f['lib']} {f['func']}" if f.get('lib', '').endswith('.so') else f['func']) for f in fr if f.get('func')][:6],
                    'stack': [(f"{f['lib']} {f['func']}" + (' [Play symbols]' if f.get('named_by') == 'google-play' else '')) if f.get('func')
                              else f"{f.get('lib', '')} {_hex(f.get('address'))}  (no symbol)" for f in fr][:12],
                    'signal': s['signal'], 'subtitle': s['subtitle'], 'sig': timeline.signature(fr),
                    'frames': [{'lib': f.get('lib'), 'func': f.get('func')} for f in fr]})
    return out


def split_groups(fid, samples):
    """One Crashlytics issue can hold several different crashes (it groups unsymbolized frames together).
    Split it by stack group: the biggest group keeps the issue id, the others get '<id>~<hash>'."""
    cnt = Counter(x.get('sig') or 'unknown' for x in samples)
    if len(cnt) <= 1:
        return [(fid, next(iter(cnt), None), samples, dict(cnt))]
    out = []
    for i, (g, _) in enumerate(cnt.most_common()):
        uid = fid if i == 0 else f"{fid}~{hashlib.sha1(g.encode()).hexdigest()[:8]}"
        out.append((uid, g, [x for x in samples if (x.get('sig') or 'unknown') == g], dict(cnt)))
    return out


# ------------------------------------------------------------------ Play samples

RE_NATIVE = re.compile(r'#\d+\s+pc\s+(0x)?([0-9a-fA-F]+)\s+(\S+)(.*)$', re.M)
RE_JAVA = re.compile(r'^\s*at\s+([\w$.<>]+)\s*\(', re.M)        # Play writes "at a.b.C.m (File.java:12)"
GENERIC = re.compile(r'^(android\.os\.(MessageQueue|Looper|Handler)|java\.lang\.(Object\.wait|Thread)|com\.android\.internal\.os|'
                     r'android\.app\.ActivityThread\.main|java\.lang\.reflect)')
SYSTEM_LIBS = ('libc.so', 'libart.so', 'libbase.so', 'libutils.so', 'libbinder.so', 'libandroid_runtime.so')


def best_title(funcs, java):
    for f in funcs:                                  # our engine first
        if 'libMYJNILIB26' in f:
            return f
    for j in java:                                   # then the first non-framework Java frame
        if not j.startswith(('android.', 'java.', 'javax.', 'kotlin.', 'kotlinx.', 'dalvik.', 'com.android.')):
            return j
    for f in funcs:
        if f.split(' ')[0] not in SYSTEM_LIBS:
            return f
    return (java or funcs or [''])[0]


def parse_play(text, learn=None):
    pcs, funcs, java = [], [], RE_JAVA.findall(text or '')[:5]
    for m in RE_NATIVE.finditer(text or ''):
        lib = m.group(3).split('/')[-1]
        if learn is not None and lib == 'libMYJNILIB26.so':     # Play's own symbols for this build: pc -> name
            bm = re.search(r'BuildId:\s*([0-9a-f]{16,})', m.group(4) or '')
            r0 = (m.group(4) or '').split(' (BuildId')[0].strip()
            fn0 = re.sub(r'\+\d+$', '', r0[1:-1] if r0.startswith('(') and r0.endswith(')') else r0).strip()
            if bm and fn0 and not fn0.startswith('???'):
                learn.append((bm.group(1), '0x%x' % int(m.group(2), 16), fn0))
        rest = (m.group(4) or '').split(' (BuildId')[0].strip()
        fn = re.sub(r'\+\d+$', '', rest[1:-1] if rest.startswith('(') and rest.endswith(')') else rest).strip()
        if lib in APP_LIBS:
            pcs.append((lib, '0x%x' % int(m.group(2), 16)))
        if fn and len(funcs) < 6:
            funcs.append(f'{lib} {fn}')
    return pcs[:12], funcs, java


LEARN = []


def play_samples(cfg, pid, tok, quota, n=20):
    pkg = cfg['app']['package']
    rep = sync._play_get(f'apps/{pkg}/errorReports:search',
                         sync._play_interval(28) + [('filter', f'errorIssueId = {pid}'), ('pageSize', n)], tok, quota)
    out = []
    for r in rep.get('errorReports', []) or []:
        dm = r.get('deviceModel') or {}
        did = dm.get('deviceId') or {}
        pcs, funcs, java = parse_play(r.get('reportText', ''), LEARN)
        t = r.get('eventTime') or ''
        if isinstance(t, dict):                       # google.type.DateTime form
            t = '%04d-%02d-%02dT%02d:00:00Z' % (t.get('year', 0), t.get('month', 0), t.get('day', 0), t.get('hours', 0))
        out.append({'time': t, 'version': str((r.get('appVersion') or {}).get('versionCode', '')),
                    'os': 'Android API %s' % ((r.get('osVersion') or {}).get('apiLevel', '?')),
                    'device': dm.get('marketingName') or ' '.join(x for x in (did.get('buildBrand'), did.get('buildDevice')) if x),
                    'model': did.get('buildDevice', ''), 'maker': did.get('buildBrand', ''), 'marketing': dm.get('marketingName', ''),
                    'pcs': pcs, 'java': java, 'funcs': funcs, 'text': (r.get('reportText') or '')[:200000]})
    return out


# ------------------------------------------------------------------ matching

def _same_device(a, b):
    ka = {_norm(a.get('model')), _norm(a.get('marketing')), _norm(a.get('device'))} - {''}
    kb = {_norm(b.get('model')), _norm(b.get('marketing')), _norm(b.get('device'))} - {''}
    return bool(ka & kb) or any(x and y and (x in y or y in x) and min(len(x), len(y)) >= 4 for x in ka for y in kb)


def _fname(f):
    """'libMYJNILIB26.so Sticker::add_triggered_keyframe(unsigned long, ...) + 88' -> 'Sticker::add_triggered_keyframe'"""
    if not f.startswith('libMYJNILIB26.so '):
        return ''
    n = f.split(' ', 1)[1].split(' + ')[0]
    depth, out = 0, ''
    for ch in n:                                     # drop the parameter list, keep templates
        if ch == '(' and depth == 0:
            break
        depth += ch == '<'; depth -= ch == '>'; out += ch
    return out.strip()


def score(fb, play):
    """(score, proof lines). Exact pcs in the app's libraries are the strongest proof (same build = same code)."""
    fpcs = {p for e in fb for p in e['pcs'][:8]}
    ppcs = {p for e in play for p in e['pcs'][:8]}
    shared = fpcs & ppcs
    ftop = {e['pcs'][0] for e in fb if e['pcs']}
    ptop = {e['pcs'][0] for e in play if e['pcs']}
    fjava = {e['java'][0] for e in fb if e['java'] and not GENERIC.match(e['java'][0])}
    pjava = {e['java'][0] for e in play if e['java'] and not GENERIC.match(e['java'][0])}
    fj5 = {j for e in fb for j in e['java'][:5] if not GENERIC.match(j)}
    pj5 = {j for e in play for j in e['java'][:5] if not GENERIC.match(j)}
    s, proof = 0, []
    top = ftop & ptop
    eng_shared = {p for p in shared if p[0] == 'libMYJNILIB26.so'}
    if any(l == 'libMYJNILIB26.so' for l, _ in top):         # same crashing pc in our engine: same code, same build
        s += 60
        proof.append('same crashing pc ' + ', '.join(f'{l} {pc}' for l, pc in sorted(top)))
    elif top and eng_shared:                                  # libc++ (mutex/futex) top is shared by many crashes:
        s += 45                                               # only counts together with an engine pc
        proof.append('same crashing pc ' + ', '.join(f'{l} {pc}' for l, pc in sorted(top)) + ' + engine pcs')
    elif top:
        s += 10
    if shared:
        s += min(30, 10 * len(eng_shared) + 2 * (len(shared) - len(eng_shared)))
        proof.append(f'{len(shared)} shared app pcs: ' + ' → '.join(pc for _, pc in sorted(shared, key=lambda x: x[1])[:6]))
    if fjava & pjava:
        s += 50
        proof.append('same top Java frame ' + sorted(fjava & pjava)[0])
    elif len(fj5 & pj5) >= 2:
        s += 35
        proof.append(f'{len(fj5 & pj5)} shared Java frames: ' + ', '.join(sorted(fj5 & pj5)[:3]))
    # engine function names: builds 800054867 and 800054869/71 have different .so files (pcs move), names do not
    ffn = {n for e in fb for n in map(_fname, e['funcs'][:6]) if n}
    pfn = {n for e in play for n in map(_fname, e['funcs'][:6]) if n}
    ftopn = {next((n for n in map(_fname, e['funcs']) if n), '') for e in fb} - {''}
    ptopn = {next((n for n in map(_fname, e['funcs']) if n), '') for e in play} - {''}
    if ftopn & ptopn and not any(l == 'libMYJNILIB26.so' for l, _ in top):
        s += 55
        proof.append('same engine function on top: ' + sorted(ftopn & ptopn)[0])
    if len(ffn & pfn) >= 2:
        s += min(20, 6 * len(ffn & pfn))
        proof.append(f'{len(ffn & pfn)} shared engine functions: ' + ' → '.join(sorted(ffn & pfn)[:4]))
    devs = [(a, b) for a in fb for b in play if _same_device(a, b)]
    if devs:
        s += 15
        a, b = devs[0]
        try:
            same_day = abs((dt.date.fromisoformat(_day(a['time'])) - dt.date.fromisoformat(_day(b['time']))).days) <= 1
        except ValueError:
            same_day = False
        proof.append(f"same phone {b['device']} = {a['device']}" + (f" on {_day(a['time'])}" if same_day else ''))
    return s, proof


def label(s):
    return 'both' if s >= 60 else 'likely' if s >= 25 else ''


# ------------------------------------------------------------------ build + write

# ------------------------------------------------------------------ instances (event level, both consoles)

def _ts(t):
    """ISO time -> (epoch seconds, precision seconds). Play sometimes only gives the hour."""
    if not t:
        return None, None
    try:
        d = dt.datetime.fromisoformat(str(t).replace('Z', '+00:00'))
    except ValueError:
        return None, None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    hour_only = d.minute == 0 and d.second == 0 and d.microsecond == 0
    return d.timestamp(), (3600 if hour_only else 180)


def _code(v):
    m = re.search(r'\((\d+)\)', str(v or ''))
    return m.group(1) if m else str(v or '').strip()


def _phone_key(x):
    for k in ('marketing', 'model', 'device'):
        n = _norm(x.get(k))
        if n:
            return n
    return '?'


BRANDS = {'redmi': 'xiaomi', 'poco': 'xiaomi', 'mi': 'xiaomi', 'xiaomi': 'xiaomi', 'samsung': 'samsung', 'oppo': 'oppo',
          'realme': 'realme', 'oneplus': 'oneplus', 'vivo': 'vivo', 'iqoo': 'vivo', 'honor': 'honor', 'huawei': 'huawei',
          'motorola': 'motorola', 'moto': 'motorola', 'google': 'google', 'tecno': 'tecno', 'infinix': 'infinix'}


def _brand(x):
    for k in ('maker', 'device', 'marketing'):
        w = re.split(r'[\s(]', str(x.get(k) or '').strip().lower())[0]
        if w:
            return BRANDS.get(w, w)
    return ''


def instances(fs, ps):
    """Every crash instance of one problem, from both consoles. A Firebase event and a Play report are the SAME
    physical crash (duplicate) when they are the same phone model, the same build and the same moment (within the
    precision of the Play timestamp). Returns (rows, summary)."""
    fb = [{'src': 'firebase', 'time': e.get('time'), 'build': _code(e.get('version')), 'device': e.get('device'),
           'model': e.get('model', ''), 'marketing': e.get('marketing', ''), 'maker': e.get('maker', ''), 'os': e.get('os')} for e in fs]
    pl = [{'src': 'play', 'time': e.get('time'), 'build': _code(e.get('version')), 'device': e.get('device'),
           'model': e.get('model', ''), 'marketing': e.get('marketing', ''), 'maker': e.get('maker', ''), 'os': e.get('os')} for e in ps]
    pairs = []
    for i, a in enumerate(fb):
        ta, _ = _ts(a['time'])
        for j, b in enumerate(pl):
            tb, prec = _ts(b['time'])
            if ta is None or tb is None or a['build'] != b['build']:
                continue
            same = _same_device(a, b)
            if not same and _brand(a) != _brand(b):    # Play may give a codename ('garnet') where Firebase gives a
                continue                                # model number ('24116RACCG'): same brand family = 'likely'
            d = abs(ta - tb)
            if d <= prec:
                pairs.append((d + (0 if same else 10 ** 6), i, j, 'exact' if same else 'likely'))
    pairs.sort()
    used_f, used_p, rows = set(), set(), []
    for d, i, j, how in pairs:
        if i in used_f or j in used_p:
            continue
        used_f.add(i); used_p.add(j)
        a, b = fb[i], pl[j]
        d = d % (10 ** 6)
        rows.append({'src': 'both', 'dup': True, 'dupMatch': how, 'time': a['time'], 'build': a['build'],
                     'device': a['device'] if a['device'] and a['device'] != '?' else b['device'],
                     'alias': b['device'] if _norm(b['device']) != _norm(a['device']) else '', 'os': a['os'] or b['os'],
                     'fbTime': a['time'], 'playTime': b['time'], 'deltaS': int(d),
                     'model': a['model'] or b['model'], 'marketing': a['marketing'] or b['marketing']})
    rows += [dict(x, dup=False) for k, x in enumerate(fb) if k not in used_f]
    rows += [dict(x, dup=False) for k, x in enumerate(pl) if k not in used_p]
    rows.sort(key=lambda r: r.get('time') or '', reverse=True)
    # phones: merge rows that are the same phone model (by name, model or a both-console alias)
    phones = []
    for r in rows:
        hit = next((ph for ph in phones if any(_same_device(r, q) for q in ph)), None)
        (hit.append(r) if hit is not None else phones.append([r]))
    repeat = []
    for ph in phones:
        if len(ph) > 1:
            times = sorted(_ts(x['time'])[0] or 0 for x in ph)
            if times[-1] - times[0] > 600:                 # same phone model crashing again later
                repeat.append({'device': ph[0]['device'], 'crashes': len(ph)})
        for x in ph:
            x['phone'] = phones.index(ph) + 1
    summ = {'crashes': len(rows), 'phones': len(phones), 'both': sum(1 for r in rows if r['src'] == 'both'),
            'firebaseOnly': sum(1 for r in rows if r['src'] == 'firebase'), 'playOnly': sum(1 for r in rows if r['src'] == 'play'),
            'repeatPhones': repeat, 'note': 'Play returns at most 20 sample reports and Crashlytics 50 events per issue; '
                                            'counts above are of those samples.'}
    return rows, summ


def _devices(samples, src):
    return [{'device': e['device'], 'date': _day(e['time']), 'version': e['version'], 'os': e['os'], 'src': src} for e in samples]


def per_build(P, F):
    """{versionCode: {'play': events, 'fb': events}} from each console's per-build counts."""
    out = {}
    for k, v in (P.get('sync_versions') or {}).items():
        m = re.search(r'(\d{6,})', str(k))
        if m and int(v or 0) > 0:                  # a build with 0 events is not a build this problem is on
            out.setdefault(m.group(1), {})['play'] = v
    for k, v in (F.get('sync_versions') or {}).items():
        m = re.search(r'\((\d+)\)', str(k))
        if m and int(v or 0) > 0:
            out.setdefault(m.group(1), {})['fb'] = v
    return out


def write_cards(db, cases, units, real, cardinfo, run_id):
    """cases/<issue>~<fp8> for every split card (own events, versions, devices; own lab/repro/fix fields later).
    The plain issue card gets the same summary fields. Nothing a card already has (analysis, lab results) is touched."""
    from firebase_admin import firestore
    batch, n = db.batch(), 0
    for uid, smp in units.items():
        ci = cardinfo.get(uid) or {}
        if ci.get('cards', 1) <= 1:
            continue
        if (cases.get(uid) or {}).get('retired'):   # a hidden trial card (stackgroups/_retired_cards.json) never comes back
            continue
        F = cases.get(real[uid]) or {}
        vers = Counter(x.get('version') or '?' for x in smp)
        doc = {'parentIssue': real[uid], 'card_title': ci['title'], 'groupKey': ci['key'], 'groupStack': ci.get('stack3', ''), 'stackCards': ci['cards'],
               'newStack': ci['newStack'], 'groupSampled': len(smp)}
        if uid != real[uid]:
            old = cases.get(uid) or {}
            doc.update({'id': uid, 'src': 'crashlytics', 'sync_run': run_id or '', 'sync_at': firestore.SERVER_TIMESTAMP,
                        'sync_events': len(smp), 'sync_users': None, 'sync_versions': dict(vers),
                        'title': F.get('title') or '', 'subtitle': F.get('subtitle') or '', 'console_url': F.get('console_url') or '',
                        'kind': F.get('kind') or 'CRASH'})
            if not old.get('verdict') or old.get('verdict') in ('new', 'pending'):
                doc.update({'verdict': 'new', 'confidence': '', 'events': len(smp), 'real_users': 0, 'versions': dict(vers),
                            'status': old.get('status') or 'new', 'last_date': max((_day(x['time']) for x in smp), default='')})
        batch.set(db.collection('cases').document(uid), doc, merge=True)
        n += 1
        if n >= 400:
            batch.commit(); batch, n = db.batch(), 0
    for cid, c in cases.items():                     # a card no registry knows any more (an earlier trial keying): off the board
        if c.get('parentIssue') and sgroups.is_card(cid) and cid not in units and not c.get('retired'):
            batch.set(db.collection('cases').document(cid), {'retired': True, 'sync_run': 'retired', 'stackCards': 0}, merge=True)
            n += 1
    if n:
        batch.commit()


def build(db, cfg, log=print):
    live, names, codes = sync.releases(cfg)
    live_codes = [c for n_, c in zip(names, codes) if n_.split(' ')[0] == live]
    live_sha = None
    if live_codes:
        try:
            from . import source
            src = source.ref_for(live_codes[0], live, cfg)
            live_sha = (src or {}).get('sha')
            log(f'live release {live} ({live_codes[0]}): code read from ' + (f"{src['ref']} @ {live_sha[:10]}" if live_sha else 'unknown commit'))
        except Exception as e:
            log(f'live release commit not found ({str(e)[:120]})')
    from . import fixstate
    cases = {d.id: (d.to_dict() or {}) for d in db.collection('cases').stream()}
    fb_issues = [c for c in cases.values() if (c.get('src') == 'crashlytics' or (not c.get('src') and not c['id'].startswith('play-')))
                 and c.get('sync_events') is not None and not sgroups.is_card(c['id'])]   # cards are made below, not listed
    play_issues = [c for c in cases.values() if c.get('src') == 'play' and c.get('sync_events') is not None]
    fb_cur = (db.collection('config').document('sync').get().to_dict() or {}).get('crashlytics', {}).get('run')
    play_cur = (db.collection('config').document('sync').get().to_dict() or {}).get('play', {}).get('run')
    fb_issues = [c for c in fb_issues if not fb_cur or c.get('sync_run') == fb_cur]
    play_issues = [c for c in play_issues if not play_cur or c.get('sync_run') == play_cur]
    log(f'matching {len(play_issues)} Play clusters against {len(fb_issues)} Crashlytics issues')

    play_ok = True
    try:
        tok, quota = sync.play_token()
    except Exception as e:                           # expired Google login: Crashlytics cards still update; Play pairings are kept as they were
        play_ok, tok, quota = False, None, None
        log(f'Google Play unavailable ({str(e)[:120]}): Crashlytics side updated, earlier Play pairings kept, no Play row hidden')
        play_issues = []
    pls = {}
    for c in play_issues:
        try:
            pls[c['id']] = play_samples(cfg, c['id'][5:], tok, quota)
        except Exception as e:
            pls[c['id']] = []
            log(f'  Play reports {c["id"][5:13]}: {str(e)[:150]}')
    learned = symbolize.add_pcmap(LEARN)
    log(f'symbols: learned {learned} new engine pc names from Google Play stacks (used for frames .dynsym cannot name)')
    LEARN.clear()
    fbs = {}
    for c in fb_issues:
        try:
            fbs[c['id']] = fb_samples(cfg, c['id'], names)
        except SystemExit as e:
            fbs[c['id']] = []
            log(f'  Crashlytics events {c["id"][:8]}: {str(e)[:150]}')

    # one card per real crash: every stack group of an issue gets a stable key (groups.py); the first group keeps the
    # issue id, the others are '<issue>~<fp8>' cards with their own events, root cause, repro and fix
    units, real, groupinfo, cardinfo = {}, {}, {}, {}
    try:                                             # plain-id locks: Firestore keeps a copy; the Mac's file is restored from it
        import json as _json, os as _os
        lp = sgroups._locks_path()
        fsl = (db.collection('stackgroups').document('_plain_locks').get().to_dict() or {})
        loc = _json.load(open(lp)) if _os.path.exists(lp) else {}
        merged_l = {**fsl, **loc}                    # the Mac's entries win; nothing is ever removed
        if merged_l != loc:
            _os.makedirs(_os.path.dirname(lp), exist_ok=True); _json.dump(merged_l, open(lp, 'w'), indent=1)
        if merged_l != fsl:
            db.collection('stackgroups').document('_plain_locks').set(merged_l, merge=True)
    except Exception as e:
        log(f'stack groups: plain-id locks not synced ({str(e)[:120]})')
    for f in fb_issues:
        smp = fbs.get(f['id'], [])
        if 'ANR' in str(f.get('kind', '')).upper():
            reg, by_card = {'groups': []}, {f['id']: smp}
        else:
            reg, by_card = sgroups.assign(f['id'], smp, db=db, log=log)
        gl = reg.get('groups') or []
        allg = {g['fp']: g.get('sampled', 0) for g in gl}          # Firestore map keys: short fingerprints, not frame text
        for uid, s_ in by_card.items():
            g = next((x for x in gl if x['card'] == uid), None)
            units[uid] = s_; real[uid] = f['id']
            groupinfo[uid] = ((g or {}).get('fp'), allg if len(gl) > 1 else {})
            cardinfo[uid] = {'cards': len(gl), 'title': f"{f['id'][:8]} · {g['title']}" if g and len(gl) > 1 else '',
                             'newStack': bool((g or {}).get('newStack')), 'key': (g or {}).get('key'), 'stack3': (g or {}).get('stack3', '')}
    split = sum(1 for u in units if '~' in u)
    if split:
        log(f'stack groups: {split} card(s) split out of Crashlytics issues that mix different crashes')
    write_cards(db, cases, units, real, cardinfo, fb_cur)

    kind = lambda c: 'ANR' if 'ANR' in str(c.get('kind', '')).upper() or 'RESPONDING' in str(c.get('kind', '')).upper() else 'CRASH'
    pairs = []
    for p in play_issues:
        for uid in units:
            f = cases[real[uid]]
            if kind(p) != kind(f):
                continue
            s, proof = score(units[uid], pls[p['id']])
            if label(s):
                pairs.append((s, p['id'], uid, proof))
    pairs.sort(reverse=True)
    used_p, used_f, rows = set(), set(), []
    for s, pid, fid, proof in pairs:                 # best pairs first, each issue used once
        if pid in used_p or fid in used_f:
            continue
        used_p.add(pid); used_f.add(fid)
        rows.append((label(s), pid, fid, proof, s))
    rows += [('play', p['id'], None, [], 0) for p in play_issues if p['id'] not in used_p]
    rows += [('firebase', None, uid, [], 0) for uid in units if uid not in used_f]

    from firebase_admin import firestore
    old = {d.id: (d.to_dict() or {}) for d in db.collection('merged').stream()}
    # rows of the earlier split ('<issue>~<hash of the first engine frame>', fb.id = the issue): their Play pairing, PR and
    # note go to the card whose key is the SAME crashing function (checked frame by frame), never by id alone
    heir = {}
    for oid, d in old.items():
        fbo = d.get('fb') or {}
        if '~' not in oid or fbo.get('card') or not fbo.get('id'):
            continue
        fr = [{'lib': x.split(' ', 1)[0], 'func': (x.split(' ', 1) + [''])[1].replace(' [Play symbols]', '')}
              for x in (fbo.get('top') or []) if 'no symbol' not in x]
        k = sgroups.key_of(fr)
        g = next((g for g in sgroups.load(fbo['id']).get('groups') or [] if k and g['key'] == k), None)
        if g:
            heir[g['card']] = (oid, d)
    batch, n, keep = db.batch(), 0, set()
    for i, (lab, pid, fid, proof, s) in enumerate(rows):
        uid = fid
        fid = real.get(uid) if uid else None
        P, F = cases.get(pid) or {}, cases.get(fid) or {}
        ps, fs = pls.get(pid, []), units.get(uid, [])
        grp, allg = groupinfo.get(uid, (None, {}))
        title = (best_title(ps[0]['funcs'], ps[0]['java']) if ps else '') or \
            (best_title(fs[0]['funcs'], fs[0]['java']) if fs else '') or P.get('title') or F.get('title') or '?'
        inst_rows, inst_sum = instances(fs, ps)
        mid = 'm-' + (uid or pid)
        keep.add(mid)
        prev = old.get(mid, {})
        doc = {
            'id': mid, 'kind': kind(P or F), 'match': lab, 'score': s, 'title': title[:200],
            'subtitle': (F.get('subtitle') or P.get('subtitle') or '')[:200], 'proof': proof,
            'play': {'id': pid[5:], 'events': P.get('sync_events'), 'users': P.get('sync_users'), 'last': _day(P.get('last_report')),
                     'url': P.get('console_url'), 'cause': P.get('title'), 'devices': _devices(ps, 'play'),
                     'top': (ps[0]['funcs'] if ps else [])[:5], 'java': (ps[0]['java'] if ps else [])[:5],
                     'stack': (ps[0]['text'] if ps else P.get('stack', ''))[:(200000 if kind(P or F) == 'ANR' else 6000)]} if pid else None,
            'fb': {'id': uid, 'issue': fid, 'card': uid, 'cardTitle': cardinfo.get(uid, {}).get('title', ''),
                   'groupKey': cardinfo.get(uid, {}).get('key'), 'groupStack': cardinfo.get(uid, {}).get('stack3', ''),
                   'cards': cardinfo.get(uid, {}).get('cards', 1), 'newStack': cardinfo.get(uid, {}).get('newStack', False),
                   'events': F.get('sync_events'), 'users': F.get('sync_users'),
                   'last': max((_day(e['time']) for e in fs), default=''), 'url': F.get('console_url'),
                   'title': F.get('title'), 'devices': _devices(fs, 'firebase'),
                   'pcs': [pc for _, pc in (fs[0]['pcs'] if fs else [])][:8], 'java': (fs[0]['java'] if fs else [])[:5],
                   'top': (fs[0].get('stack') or fs[0]['funcs'] if fs else [])[:12],
                   'verdict': F.get('verdict'), 'status': F.get('status'),
                   'group': grp, 'groupSamples': len(fs), 'issueGroups': allg} if fid else None,
            'caseId': uid or pid, 'builds': names, 'rank': i, 'perBuild': per_build(P, F),
            'onLive': sum(int(v.get('fb') or 0) + int(v.get('play') or 0) for b, v in per_build(P, F).items() if b in live_codes),
            'fixState': fixstate.state([cases.get(uid) if uid else None, cases.get(str(uid or '').split('~')[0]) if uid else None, P],
                                       per_build(P, F), live_codes, f"{live} ({live_codes[0]})" if live_codes else live, live_sha),
            'instances': inst_rows[:80], 'instanceSummary': inst_sum,
            'pr': prev.get('pr', ''), 'note': prev.get('note', ''), 'updatedAt': firestore.SERVER_TIMESTAMP,
        }
        if not play_ok and doc['play'] is None and prev.get('play'):   # Play unreadable today: keep the last pairing
            doc.update({k: prev[k] for k in ('play', 'match', 'proof', 'score') if k in prev})
        if uid in heir and heir[uid][0] != mid:
            hid, h = heir[uid]
            if not play_ok and doc['play'] is None and h.get('play'):
                doc.update({k: h[k] for k in ('play', 'match', 'proof', 'score') if k in h})
                log(f'stack groups: {hid[2:10]}~{hid.split("~")[1]} (old split row) -> card {sgroups.label(uid)}: same crashing '
                    f'function {cardinfo.get(uid, {}).get("key")}; its Play pairing moves with it')
            for k in ('pr', 'note'):
                if h.get(k) and not doc.get(k):
                    doc[k] = h[k]
        for k in ('analysis', 'analysis_key', 'analysis_basis', 'analysedAt', 'noteBy', 'noteAt'):   # a re-sync never throws away analysis
            if k in prev:
                doc[k] = prev[k]
        batch.set(db.collection('merged').document(mid), doc)
        n += 1
        if n >= 400:
            batch.commit(); batch, n = db.batch(), 0
    for mid, d in old.items():                       # rows the consoles no longer list: hide, keep PR/notes
        if not play_ok and d.get('play') and not d.get('fb'):   # Play could not be read: its Play-only rows are not 'gone'
            continue
        if mid not in keep and not d.get('stale'):
            batch.update(db.collection('merged').document(mid), {'stale': True}); n += 1
    if n:
        batch.commit()
    both = sum(1 for r in rows if r[0] == 'both'); likely = sum(1 for r in rows if r[0] == 'likely')
    log(f'merged: {len(rows)} problems — {both} in both, {likely} likely both, '
        f'{sum(1 for r in rows if r[0] == "play")} Play only, {sum(1 for r in rows if r[0] == "firebase")} Firebase only')
    return {'problems': len(rows), 'both': both, 'likely': likely}
