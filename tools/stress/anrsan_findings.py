#!/usr/bin/env python3
"""
anrsan_findings.py — turn the ANRSan output of many stress runs into one ranked list of findings.

  python3 tools/stress/anrsan_findings.py stress_results/20261002-150800      # one run
  python3 tools/stress/anrsan_findings.py stress_results                       # every run, merged
  python3 tools/stress/anrsan_findings.py anrsan_run.txt                       # a plain ANRSan log

For every scenario logcat it:
  1. symbolizes the ANRSAN lines with tools/anrsan/anrsan_symbolize.py (cached as anrsan.sym.txt),
  2. splits them into reports and fingerprints each one by rule + the app frames of every stack
     (function names only, so the same issue matches across call sites, runs and rebuilds),
  3. merges duplicates across all scenarios, ranks them, and records which scenario and which
     stress step (ZSTRESS marker) first triggered each finding.

Writes <out>/anrsan_findings.md, .csv and .json (out = the first directory given, or --out).
Run it from the repo root on the Mac (the symbolizer needs the NDK and the unstripped .so).
"""
import argparse, csv, glob, hashlib, json, os, re, subprocess, sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SYMBOLIZER = os.path.join(REPO, 'tools', 'anrsan', 'anrsan_symbolize.py')
APP_LIBS = ('libMYJNILIB26.so', 'libSoundTouch.so')

LOG = re.compile(r'^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(\S+)\s*: ?(.*)$')
HEADER = re.compile(r'==== ANRSAN #(\d+) (\w+) ====\s*(.*)')
SECTION = re.compile(r'^\s*\[([^\]]+)\]\s*(.*)')
FRAME = re.compile(r'#(\d+) pc ([0-9a-fA-F]+)\s+(\S+)(?:\s+\((.+)\))?')

# ── how bad is each rule ──
SEVERITY = {
    'DEADLOCK': 'CRITICAL', 'POSSIBLE_DEADLOCK': 'CRITICAL', 'MAIN_BLOCKED': 'CRITICAL',
    'SELF_DEADLOCK': 'CRITICAL', 'LOCK_ORDER_INVERSION': 'CRITICAL',
    'MAIN_UNTIMED_WAIT': 'HIGH', 'MAIN_LOCK_WAIT': 'HIGH', 'MAIN_LONG_TIMED_WAIT': 'HIGH',
    'CRITICAL_JOIN': 'HIGH', 'CRITICAL_BLOCKED': 'HIGH', 'LOCK_BLOCKED': 'HIGH', 'JOIN_BLOCKED': 'HIGH',
    'LONG_HOLD': 'HIGH',
    'CRITICAL_UNTIMED_WAIT': 'MEDIUM', 'JOIN_UNDER_LOCK': 'MEDIUM', 'WAIT_UNDER_LOCK': 'MEDIUM',
}
RANK = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
RUNTIME = {'DEADLOCK', 'POSSIBLE_DEADLOCK', 'MAIN_BLOCKED', 'CRITICAL_BLOCKED', 'LOCK_BLOCKED',
           'JOIN_BLOCKED', 'LONG_HOLD', 'MAIN_LOCK_WAIT'}

# Waits inside Android media/GL code (every NDK MediaCodec/MediaMuxer call is a post-and-wait to the
# codec looper). Real, but structurally identical and not fixable by a timeout -> category "framework-sync".
FRAMEWORK_WAITS = ('ALooper13awaitResponse', 'ALooper::awaitResponse', 'MediaAdapter', 'AudioStreamAAudio',
                   'AudioStream12joinThread', 'joinThread_l', 'osup_sync_object_wait', 'eglDestroySurface',
                   'eglSwapBuffers', 'MPEG4Writer', 'requestExitAndWait')
# A thread parked on its own work queue is idle, not blocked (ANRSan's idle heuristic can miss these).
IDLE_SITES = ('ProcessMessages', 'seekThreadFunc', 'tryAndPop', 'pop_for', 'ALooper4loop', 'ALooper::loop',
              '_threadLoop')
GENERIC_APP = ('MsgLooper::ProcessMessages', 'MsgLooper::MsgLooper', 'ThreadWorker::ThreadWorker',
               'ThreadWorker::run', '__thread_proxy', '_ZN9MsgLooper15ProcessMessages', '_ZN12ThreadWorker')


def short_fn(fn):
    fn = fn.replace('std::__ndk1::', '').replace('[abi:v170000]', '')
    fn = re.sub(r'basic_string<char, char_traits<char>, allocator<char>>', 'string', fn)
    fn = re.sub(r'\((?:[^()]|\([^()]*\))*\)', '()', fn)        # drop argument lists
    return fn.replace(' const', '').strip()


class Report:
    def __init__(self, num, rule, extra, ts, source, step):
        self.num, self.rule, self.extra, self.ts = int(num), rule, extra.strip(), ts
        self.source, self.step = source, step
        self.lines = []          # raw text lines (logcat prefix stripped)
        self.sections = []       # [label, text, frames]; frame = dict(lib, sym, fns=[(fn, loc)])

    def add(self, text):
        self.lines.append(text)
        m = SECTION.match(text)
        if m and ('tid ' in text or 'thread' in text):
            self.sections.append([m.group(1), m.group(2), []])
            return
        f = FRAME.search(text)
        if f and self.sections:
            self.sections[-1][2].append(dict(lib=os.path.basename(f.group(3)), sym=f.group(4) or '',
                                             pc=f.group(2), fns=[]))
            return
        s = text.strip()
        if s.startswith('->') and self.sections and self.sections[-1][2]:
            body = s[2:].strip()
            fn, _, loc = body.partition('  ')
            self.sections[-1][2][-1]['fns'].append((fn.strip(), loc.strip()))

    # ── fingerprint pieces ──
    @staticmethod
    def app_frames(frames):
        out = []
        for fr in frames:
            if fr['fns']:
                for fn, loc in fr['fns']:
                    if 'app/src/main/cpp/' in loc:
                        out.append((short_fn(fn), loc.split('app/src/main/cpp/')[-1].rsplit(':', 1)[0]))
            elif fr['lib'] in APP_LIBS:            # not symbolized: exported symbol or pc
                sym = fr['sym'].split('+')[0] if fr['sym'] and not fr['sym'].startswith('JNI_getVideoFrameRate') else ''
                out.append((sym or f'{fr["lib"]}@{fr["pc"].lstrip("0")}', ''))
        return out

    @staticmethod
    def sys_top(frames):
        for fr in frames:
            if fr['lib'] not in APP_LIBS and not fr['lib'].startswith('libc') and fr['sym']:
                return fr['sym'].split('+')[0]
        return ''

    def signature(self):
        cat = self.category()
        parts = [self.rule]
        for i, (label, _, frames) in enumerate(self.sections):
            app = [f for f, _ in self.app_frames(frames) if not any(g in f for g in GENERIC_APP)]
            if cat in ('framework-sync', 'likely-idle'):
                if i:                           # coarse: the waiting thread only, nearest 2 app frames
                    break
                app = app[:2]
            else:
                app = app[:4]
            kind = re.sub(r'\d+', '#', label)
            parts.append(f'{kind}|{self.sys_top(frames)}|{" < ".join(app)}')
        return '\n'.join(parts)

    def first_wait_site(self):
        """Innermost app frame + top system frame of the thread the report is about."""
        if not self.sections:
            return ''
        _, text, frames = self.sections[0]
        a = self.app_frames(frames)
        return f'{a[0][0] if a else ""} {self.sys_top(frames)} {text}'

    def category(self):
        first = self.sections[0][2] if self.sections else []
        top = self.sys_top(first)
        if self.rule in ('CRITICAL_UNTIMED_WAIT', 'CRITICAL_BLOCKED', 'POSSIBLE_DEADLOCK', 'LOCK_BLOCKED',
                         'JOIN_BLOCKED') and any(s in self.first_wait_site() for s in IDLE_SITES):
            return 'likely-idle'           # the "blocked" thread is parked on its own work queue
        if self.rule in ('WAIT_UNDER_LOCK', 'CRITICAL_UNTIMED_WAIT', 'JOIN_UNDER_LOCK') and \
                any(w in top for w in FRAMEWORK_WAITS):
            return 'framework-sync'
        if 'CYCLE (guessed)' in '\n'.join(self.lines):
            return 'guessed-cycle'
        return 'app'

    def severity(self):
        sev = SEVERITY.get(self.rule, 'MEDIUM')
        cat = self.category()
        if cat == 'likely-idle':
            return 'INFO'
        if cat == 'framework-sync':
            return 'LOW'
        if cat == 'guessed-cycle' and sev == 'CRITICAL':
            return 'HIGH'
        return sev

    def headline(self):
        for l in self.lines:
            s = l.strip()
            if s and not s.startswith('['):
                return re.sub(r'0x[0-9a-f]+', '0x…', s)[:220]
        return self.extra

    def pretty(self, max_lines=80):
        out = []
        for l in self.lines:
            s = l.rstrip()
            if re.search(r'-> (std::|decltype|void std|bool std|void\* std)|sysroot/usr/include', s):
                continue
            s = re.sub(r'/data/app/\S+?/lib/arm64/', '', s)
            out.append(s)
        return '\n'.join(out[:max_lines]) + ('\n…' if len(out) > max_lines else '')


def symbolized_lines(logpath, symbolize=True):
    """ANRSAN + ZSTRESS lines of a logcat, symbolized once and cached next to it."""
    cache = os.path.join(os.path.dirname(logpath), 'anrsan.sym.txt')
    if logpath.endswith('.gz'):
        import gzip
        src_lines = gzip.open(logpath, 'rt', errors='replace').read().split('\n')
    else:
        src_lines = open(logpath, errors='replace').read().split('\n')
    if any(l.lstrip().startswith('->') for l in src_lines[:5000]):
        return src_lines                                    # already symbolized (live symbolizer output)
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(logpath):
        return open(cache, errors='replace').read().split('\n')
    keep = [l for l in src_lines if ' ANRSAN ' in l or ' ZSTRESS ' in l]
    if not keep:
        return []
    if symbolize and os.path.exists(SYMBOLIZER):
        r = subprocess.run([sys.executable, SYMBOLIZER], input='\n'.join(keep) + '\n',
                           capture_output=True, text=True, errors='replace')
        if r.stderr.strip():
            print(f'   symbolizer: {r.stderr.strip()[:200]}', file=sys.stderr)
        out = r.stdout.split('\n') if r.stdout.strip() else keep
    else:
        out = keep
    try:
        open(cache, 'w').write('\n'.join(out))
    except OSError:
        pass
    return out


def parse(lines, source):
    reports, cur, step, anrsan_tid = [], None, '(before first step)', None
    for raw in lines:
        if raw.lstrip().startswith('->'):
            if cur:
                cur.add(raw)
            continue
        m = LOG.match(raw)
        if not m:
            continue
        ts, pid, tid, lvl, tag, msg = m.groups()
        if tag == 'ZSTRESS':
            step = msg.strip()
            continue
        if tag != 'ANRSAN':
            continue
        h = HEADER.search(msg)
        if h:
            cur = Report(h.group(1), h.group(2), h.group(3), ts, source, step)
            anrsan_tid = tid
            reports.append(cur)
            continue
        if msg.startswith('*** ***'):
            cur = None
            continue
        if cur and tid == anrsan_tid:
            cur.add(msg)
    return reports


def scenario_name(source):
    base = os.path.basename(source.rstrip('/'))
    return base.split('__')[0] if '__' in base else base


def collect(paths):
    logs = []
    for p in paths:
        if os.path.isfile(p):
            logs.append(p)
        else:
            logs += sorted(glob.glob(os.path.join(p, '**', 'logcat.txt'), recursive=True))
            logs += sorted(glob.glob(os.path.join(p, '**', 'logcat.txt.gz'), recursive=True))
    return logs


def build(paths, out_dir=None, symbolize=True, quiet=False):
    logs = collect(paths)
    if not logs:
        print('no logcat.txt found')
        return None
    out_dir = out_dir or (paths[0] if os.path.isdir(paths[0]) else os.path.dirname(os.path.abspath(paths[0])))
    findings = OrderedDict()
    discovery = []
    total = 0
    for log in sorted(logs, key=os.path.getmtime):
        src = os.path.dirname(log) if os.path.basename(log) in ('logcat.txt', 'logcat.txt.gz') else log
        reps = parse(symbolized_lines(log, symbolize), src)
        total += len(reps)
        new = 0
        for r in reps:
            sig = r.signature()
            f = findings.get(sig)
            if f is None:
                new += 1
                f = findings[sig] = dict(id='', sig=sig, rule=r.rule, severity=r.severity(), category=r.category(),
                                         headline=r.headline(), first=r, count=0, scenarios=OrderedDict())
            f['count'] += 1
            n = scenario_name(src)
            f['scenarios'][n] = f['scenarios'].get(n, 0) + 1
        discovery.append((os.path.relpath(src, out_dir) if src.startswith(out_dir) else src, len(reps), new))
    ranked = sorted(findings.values(), key=lambda f: (RANK[f['severity']], -len(f['scenarios']), -f['count']))
    for i, f in enumerate(ranked, 1):
        f['id'] = f'F{i:03d}-' + hashlib.sha1(f['sig'].encode()).hexdigest()[:6]
    write(out_dir, ranked, discovery, total, logs)
    if not quiet:
        print_summary(ranked, total, out_dir)
    return ranked


def app_chain(r):
    out = []
    for label, text, frames in r.sections:
        app = [f'{fn} ({loc})' if loc else fn for fn, loc in Report.app_frames(frames)
               if not any(g in fn for g in GENERIC_APP)][:5]
        top = Report.sys_top(frames)
        out.append(f'- **[{label}]** {text.strip()[:90]}\n  '
                   + (f'`{top}` ← ' if top else '') + (' ← '.join(f'`{a}`' for a in app) or '_(no app frames)_'))
    return '\n'.join(out)


def write(out_dir, ranked, discovery, total, logs):
    by_sev = OrderedDict((s, 0) for s in RANK)
    for f in ranked:
        by_sev[f['severity']] += 1
    md = [f'# ANRSan findings', '',
          f'{total} reports from {len(logs)} logs → **{len(ranked)} unique findings**: '
          + ', '.join(f'{k} {v}' for k, v in by_sev.items() if v), '',
          'Severity: CRITICAL = deadlock / main thread blocked; HIGH = main-thread untimed wait, '
          'critical-thread join/block; MEDIUM = waits under locks / untimed waits on critical threads; '
          'LOW = the same patterns inside Android media/GL calls (framework-sync); INFO = idle queues '
          'ANRSan mistook for blocking.', '',
          '| id | sev | rule | category | seen | scenarios | first hit (scenario → step) |',
          '|---|---|---|---|---|---|---|']
    for f in ranked:
        r = f['first']
        md.append(f'| [{f["id"]}](#{f["id"].lower()}) | {f["severity"]} | {f["rule"]} | {f["category"]} | '
                  f'{f["count"]} | {len(f["scenarios"])} | {scenario_name(r.source)} → `{r.step}` |')
    md += ['', '## Discovery per log (new unique findings)', '',
           'If later runs stop adding findings, the scenarios have saturated: add new ones or run chaos.', '',
           '| log | reports | new |', '|---|---|---|']
    md += [f'| {s} | {n} | {new} |' for s, n, new in discovery]
    md += ['', '## Details', '']
    for f in ranked:
        r = f['first']
        md += [f'### {f["id"]}', '',
               f'**{f["severity"]} · {f["rule"]} · {f["category"]}** — seen {f["count"]}× in '
               f'{len(f["scenarios"])} scenario(s)', '',
               f'> {f["headline"]}', '',
               f'First hit: `{r.source}` at step **`{r.step}`** ({r.ts}, ANRSan #{r.num})', '',
               'Scenarios: ' + ', '.join(f'{k} ×{v}' for k, v in f['scenarios'].items()), '',
               app_chain(r), '',
               '<details><summary>full report (first occurrence)</summary>', '', '```', r.pretty(), '```',
               '', '</details>', '']
    open(os.path.join(out_dir, 'anrsan_findings.md'), 'w').write('\n'.join(md))
    with open(os.path.join(out_dir, 'anrsan_findings.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'severity', 'rule', 'category', 'count', 'n_scenarios', 'scenarios',
                    'first_source', 'first_step', 'headline', 'signature'])
        for f in ranked:
            w.writerow([f['id'], f['severity'], f['rule'], f['category'], f['count'], len(f['scenarios']),
                        ';'.join(f'{k}:{v}' for k, v in f['scenarios'].items()), f['first'].source,
                        f['first'].step, f['headline'], f['sig']])
    json.dump([dict(id=f['id'], severity=f['severity'], rule=f['rule'], category=f['category'],
                    count=f['count'], scenarios=f['scenarios'], first_source=f['first'].source,
                    first_step=f['first'].step, headline=f['headline'], signature=f['sig'])
               for f in ranked], open(os.path.join(out_dir, 'anrsan_findings.json'), 'w'), indent=1)


def print_summary(ranked, total, out_dir):
    print(f'\nANRSan: {total} reports → {len(ranked)} unique findings')
    shown = [f for f in ranked if f['severity'] in ('CRITICAL', 'HIGH', 'MEDIUM') and f['category'] == 'app']
    for f in shown[:20]:
        r = f['first']
        print(f'  {f["id"]}  {f["severity"]:8} {f["rule"]:22} ×{f["count"]:<4} in {len(f["scenarios"])} scen.  '
              f'first: {scenario_name(r.source)} → {r.step}')
    rest = len(ranked) - len(shown[:20])
    if rest:
        print(f'  … {rest} more (framework-sync / idle / lower) in the report')
    print(f'report: {os.path.join(out_dir, "anrsan_findings.md")}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+', help='results dirs (searched recursively for logcat.txt) or log files')
    ap.add_argument('--out', help='where to write anrsan_findings.* (default: first path)')
    ap.add_argument('--no-symbolize', action='store_true')
    a = ap.parse_args()
    build(a.paths, a.out, symbolize=not a.no_symbolize)


if __name__ == '__main__':
    main()
