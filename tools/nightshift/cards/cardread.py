#!/usr/bin/env python3
"""Night Shift tool 3, Card Issue (phase 1): read a Jira card, download its screen recording, cut it into frames,
let Claude watch them frame by frame, and write steps. Publishes to Firestore cards/<KEY>; the frames go under
board/public/v/<token>/ so the board can play them frame by frame. Read-only towards Jira.

usage: cardread.py --id <job id> --card <KEY or link> [--by <email>]"""
import argparse, glob, json, os, re, secrets, shutil, subprocess, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NS = os.path.dirname(HERE)
sys.path.insert(0, NS)
from ns import config, fire, jira, llm          # noqa: E402

OUT = os.path.join(NS, 'out', 'cards')
PUBLIC_V = os.path.join(NS, 'board', 'public', 'v')
STEPS = ['Read the card', 'Download the video', 'Watch it frame by frame', 'Write the steps', 'Find the root cause']
WT_ROOT = os.path.expanduser('~/.nightshift_cards')
VIDEO = re.compile(r'\.(mp4|mov|webm|mkv|3gp|m4v)$', re.I)
MAX_FRAMES = 72
SHEET = (4, 3)                                    # 12 frames per contact sheet


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def tool(name):
    for c in [shutil.which(name), f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}']:
        if c and os.path.exists(c):
            return c
    raise RuntimeError(f'{name} is not installed on the Mac (brew install ffmpeg)')


def run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError(f'{os.path.basename(cmd[0])} failed: {(r.stderr or r.stdout).strip()[-400:]}')
    return r.stdout


class Card:
    def __init__(self, a):
        self.a, self.db, self.cfg = a, fire.client(), config.load()
        self.key = jira.card_key(a.card)
        self.card = None
        self.ref = self.db.collection('cards').document(self.key)
        self.steps = [{'name': n, 'state': 'wait', 'note': ''} for n in STEPS]
        self.prev = {}                                # the last reading stays on the board until each part is replaced
        try:
            snap = self.ref.get()
            self.prev = (snap.to_dict() or {}) if snap.exists else {}
        except Exception:
            self.prev = {}
        if not self.prev:
            try:
                self.prev = json.load(open(os.path.join(OUT, self.key, 'card.json')))
            except (OSError, ValueError):
                self.prev = {}
        keep = {k: v for k, v in self.prev.items() if k not in ('steps', 'status', 'error', 'finishedAt', 'job', 'startedAt', 'requestedBy')}
        self.doc = dict(keep, key=self.key, job=a.id, requestedBy=a.by or '', status='running', startedAt=now(), steps=self.steps,
                        previousAt=self.prev.get('finishedAt') or '', branch=a.branch or self.prev.get('branch', ''))
        self.dir = os.path.join(OUT, self.key)
        os.makedirs(self.dir, exist_ok=True)
        self.save()

    def save(self):
        self.ref.set(self.doc)

    def step(self, i, state, note=''):
        self.steps[i].update({'state': state, 'note': note})
        print(f'▶ {STEPS[i]}: {state}{" - " + note if note else ""}', flush=True)
        self.save()

    def go(self):
        try:
            if not llm.claude_ok():                   # fail in seconds, not after downloading and cutting the videos
                raise RuntimeError('the Claude CLI on the lab Mac is not logged in (session expired): on the Mac open Terminal, run claude, type /login, then press Read card again')
            self.step(0, 'run', f'reading {self.key} from Jira')
            card = jira.get_card(self.key)
            self.card = card
            self.doc['card'] = {k: card[k] for k in ('key', 'url', 'title', 'type', 'priority', 'status', 'reporter', 'created',
                                                     'labels', 'versions', 'components', 'description', 'environment', 'comments')}
            self.doc['card']['attachments'] = [{k: x[k] for k in ('name', 'mime', 'size')} for x in card['attachments']]
            self.step(0, 'done', f'{card["type"]} · {card["title"][:90]}')

            pv = self.prev
            same = (not getattr(self.a, 'fresh', False) and pv.get('frames') is not None and pv.get('issues')
                    and [(x['name'], x['size']) for x in card['attachments']] == [(x.get('name'), x.get('size')) for x in (pv.get('card') or {}).get('attachments') or []]
                    and (pv.get('note') or '') == (self.a.note or '') and self.frames_exist(pv.get('frames') or []))
            if same:                                  # same video and note: reuse the reading (no download, no cutting, no watching)
                frames, issues = pv['frames'], pv['issues']
                for k in ('frames', 'issues', 'analysis', 'videos', 'skills'):
                    if k in pv:
                        self.doc[k] = pv[k]
                res = {'card': {k: (pv.get('analysis') or {}).get(k) for k in ('kind', 'area', 'summary', 'platform', 'build', 'device')},
                       'videos': pv.get('videos')}
                when = str(pv.get('finishedAt') or '')[:16].replace('T', ' ')
                for i in (1, 2, 3):
                    self.step(i, 'done', f'reused from the reading of {when}: same video and note (tick "Watch the video again" to redo)')
            else:
                self.step(1, 'run', 'looking for a screen recording')
                vids = [x for x in card['attachments'] if x['mime'].startswith('video/') or VIDEO.search(x['name'])]
                logs = [x for x in card['attachments'] if re.search(r'\.(txt|log)$', x['name'], re.I) and x['size'] < 8_000_000]
                logtext = ''
                for lg in logs[:2]:
                    p = os.path.join(self.dir, re.sub(r'[^\w.-]', '_', lg['name']))
                    jira.download(lg, p, card.get('apiRoot'))
                    lines = open(p, errors='replace').read().splitlines()
                    hits = [l for l in lines if re.search(r'FATAL|ANR in|Exception|SIGSEGV|SIGABRT|backtrace|E AndroidRuntime', l)]
                    logtext += f'\n--- {lg["name"]} ({len(lines)} lines; the error lines) ---\n' + '\n'.join(hits[:120])
                frames, token = [], secrets.token_hex(12)
                self.doc['videos'] = []
                if vids:
                    vids = sorted(vids, key=lambda x: -x['size'])[:3]          # main recording first; a reference clip too
                    got = []
                    for v, att in enumerate(vids, 1):
                        vp = os.path.join(self.dir, f'video{v}' + os.path.splitext(att['name'])[1].lower())
                        n = jira.download(att, vp, card.get('apiRoot'))
                        got.append(f'{att["name"]} · {n / 1e6:.1f} MB')
                        fr = self.cut(vp, token, v, len(frames), MAX_FRAMES if v == 1 else MAX_FRAMES // 2)
                        self.doc['videos'].append({'v': v, 'name': att['name'], 'role': '', **self._vinfo, 'first': len(frames) + 1, 'count': len(fr)})
                        frames += fr
                    self.step(1, 'done', ' + '.join(got))
                else:
                    self.step(1, 'done', 'no video on this card: working from the description only')

                self.step(2, 'run', f'watching {len(frames)} frames' if frames else 'no frames: reading the text only')
                res = self.watch(card, frames, logtext)
                notes = {int(f.get('i', 0)): f for f in res.get('frames') or []}
                for f in frames:
                    n_ = notes.get(f['i']) or {}
                    f['note'], f['bug'], f['screen'], f['issue'] = n_.get('note', ''), bool(n_.get('bug')), n_.get('screen', ''), n_.get('issue', 0)
                self.doc['frames'] = frames
                issues = res.get('issues') or []
                self.doc['issues'] = issues
                nb = sum(f['bug'] for f in frames)
                self.step(2, 'done', (f'{len(issues)} issue{"s" if len(issues) != 1 else ""} · shows in {nb} frame{"s" if nb != 1 else ""}'
                                      if frames else f'{len(issues)} issue{"s" if len(issues) != 1 else ""} from the text'))

                self.step(3, 'run', 'writing steps')
                cd, i1 = res.get('card') or {}, (issues[0] if issues else {})
                self.doc['analysis'] = {'kind': cd.get('kind'), 'area': cd.get('area'), 'summary': cd.get('summary'),
                                        'platform': cd.get('platform'), 'build': cd.get('build'), 'device': cd.get('device'),
                                        'expected': i1.get('expected'), 'actual': i1.get('actual'), 'steps': i1.get('steps'),
                                        'confidence': i1.get('confidence'), 'repro_hint': i1.get('hint'), 'compare': i1.get('compare')}
                roles = {int(x.get('v', 0)): x for x in res.get('videos') or []}
                for vd in self.doc['videos']:
                    vd['role'], vd['what'] = (roles.get(vd['v']) or {}).get('role', ''), (roles.get(vd['v']) or {}).get('what', '')
                    vd['app'] = str((roles.get(vd['v']) or {}).get('app') or '')[:30]
                sk = res.get('_skills') or {}
                self.doc['skills'] = [{'name': n_, 'used': n_ in sk.get('used', []),
                                       'missing': any(n_ in m_ for m_ in sk.get('missing', []))}
                                      for n_ in ['card-reader', 'video-reader', 'crash-reader', 'steps-writer']]
                self.doc['note'] = self.a.note
                self.step(3, 'done', f'{sum(len(x.get("steps") or []) for x in issues)} steps · ' + ', '.join(sorted({x.get("kind", "?") for x in issues})))
            if self.a.branch:
                self.step(4, 'run', f'checking out {self.a.branch} and reading its code')
                self.deep_rootcause(issues, frames, res)
            else:
                self.step(4, 'done', 'skipped: no branch given')
            self.doc['status'], self.doc['finishedAt'] = 'done', now()
            self.save()
        except Exception as e:
            i = next((k for k, s in enumerate(self.steps) if s['state'] == 'run'), 0)
            self.steps[i].update({'state': 'failed', 'note': str(e)[:300]})
            self.doc.update({'status': 'failed', 'error': str(e)[:500], 'finishedAt': now()})
            self.save()
            print(f'ERROR {e}', flush=True)
            raise
        json.dump(self.doc, open(os.path.join(self.dir, 'card.json'), 'w'), indent=1)
        print(f'DONE: {self.key} · {self.doc["analysis"].get("summary", "")}', flush=True)

    def frames_exist(self, frames):
        """The frame images of a reading are still published (first and last)."""
        if not frames:
            return True
        for f in (frames[0], frames[-1]):
            u = str(f.get('url') or '')
            if not u.startswith('/v/') or not os.path.exists(os.path.join(PUBLIC_V, u[3:])):
                return False
        return True

    def cut(self, vp, token, v=1, start=0, maxf=MAX_FRAMES):
        ff, fp = tool('ffmpeg'), tool('ffprobe')
        dur = float(run([fp, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', vp]).strip() or 0)
        fps = min(4.0, maxf / max(dur, 0.5))
        fdir = os.path.join(self.dir, f'frames{v}')
        shutil.rmtree(fdir, ignore_errors=True)
        os.makedirs(fdir)
        run([ff, '-v', 'error', '-i', vp, '-vf', f'fps={fps:.4f},scale=360:-2', '-q:v', '5', '-frames:v', str(maxf),
             os.path.join(fdir, 'f_%03d.jpg')], timeout=900)
        files = sorted(glob.glob(os.path.join(fdir, 'f_*.jpg')))
        gdir = os.path.join(PUBLIC_V, token)
        os.makedirs(gdir, exist_ok=True)
        out = []
        for k, p in enumerate(files, 1):
            name = f'v{v}_{os.path.basename(p)}'
            shutil.copy2(p, os.path.join(gdir, name))
            t = (k - 1) / fps
            out.append({'i': start + k, 'v': v, 't': f'{int(t // 60):02d}:{t % 60:04.1f}', 'url': f'/v/{token}/{name}'})
        c, r = SHEET                                # contact sheets for the model: 12 frames each, in order
        for old in glob.glob(os.path.join(self.dir, f'v{v}_sheet_*.jpg')):
            os.remove(old)
        run([ff, '-v', 'error', '-y', '-framerate', '1', '-i', os.path.join(fdir, 'f_%03d.jpg'), '-vf',
             f'scale=300:-2,tile={c}x{r}:padding=6:margin=6:color=white', os.path.join(self.dir, f'v{v}_sheet_%02d.jpg')], timeout=600)
        self._vinfo = {'seconds': round(dur, 2), 'fps': round(fps, 3)}
        return out

    def checkout(self, branch):
        """Read-only worktree of the branch (own folder; the working copy is never touched)."""
        repo = config.REPO
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', branch)
        def git(*a, t=600):
            r = subprocess.run(['git', *a], cwd=repo, capture_output=True, text=True, timeout=t)
            if r.returncode:
                raise RuntimeError(f'git {a[0]} failed: {(r.stderr or r.stdout).strip()[-300:]}')
            return r.stdout.strip()
        if re.fullmatch(r'[0-9a-f]{7,40}', branch) and subprocess.run(['git', 'cat-file', '-e', branch + '^{commit}'], cwd=repo).returncode == 0:
            h = git('rev-parse', branch + '^{commit}')       # a commit (e.g. the one before a fix)
        else:
            git('fetch', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/nightshift/cards/{safe}')
            h = git('rev-parse', f'refs/nightshift/cards/{safe}')
        wt = os.path.join(WT_ROOT, f'wt-{h[:12]}')
        if not os.path.isdir(os.path.join(wt, 'app')):
            os.makedirs(WT_ROOT, exist_ok=True)
            subprocess.run(['git', 'worktree', 'prune'], cwd=repo, capture_output=True, text=True)
            git('worktree', 'add', '--detach', '--force', wt, h, t=900)
        return h, wt

    def deep_rootcause(self, issues, frames, res):
        """Root-cause review as deep as a PR review (ns/cardreview.py): Kotlin side, map, 3 hunters, line check,
        2 judges, replay from the video to the code, suggested fix. Falls back to the one-call root cause if it fails."""
        h, wt = self.checkout(self.a.branch)
        try:                                          # small code/text files attached to the card (shaders, configs, notes)
            adir = os.path.join(os.path.expanduser('~/.nightshift_server'), re.sub(r'[^\w-]', '_', self.key), 'attach')
            got = []
            for at in (self.card or {}).get('attachments') or []:
                if re.search(r'\.(h|hpp|glsl|frag|vert|fsh|vsh|txt|json|kt|java|cpp|c|xml|md)$', at.get('name', ''), re.I) and 0 < at.get('size', 0) < 500_000:
                    os.makedirs(adir, exist_ok=True)
                    p = os.path.join(adir, re.sub(r'[^\w.-]', '_', at['name']))
                    jira.download(at, p, (self.card or {}).get('apiRoot'))
                    got.append(p)
            if got:
                self.doc['_attach'] = got[:10]
                print(f'  card attachments for the review: {", ".join(os.path.basename(p) for p in got[:10])}', flush=True)
        except Exception as e:
            print(f'  card attachments skipped ({str(e)[:150]})', flush=True)
        try:
            from ns import cardreview
            rv = cardreview.Review(self.doc, self.a.branch, h, wt, self.cfg, self.dir, log=lambda l: print('  ' + l, flush=True),
                                   note=self.a.note, progress=lambda s: self.step(4, 'run', f'{self.a.branch} @ {h[:7]} · {s}'))
            rec = rv.run()
            self.doc['review'] = cardreview.summary_for_card(rec)
            self.doc['rootcause'] = cardreview.legacy_rootcause(rec)
            st = [x.get('status') for x in rec.get('issues') or []]
            self.step(4, 'done', f"{self.a.branch} @ {h[:7]} · root cause verified for {st.count('explained')} of {len(st)} issue"
                                 f"{'s' if len(st) != 1 else ''}" + (f", likely for {st.count('likely')}" if st.count('likely') else '')
                                 + f" · {rec.get('minutes', '?')} min · ${(rec.get('usage') or {}).get('cost_usd', 0):.2f}")
        except Exception as e:
            print(f'  root-cause review failed ({str(e)[:300]}): falling back to the one-step root cause', flush=True)
            self.step(4, 'run', f'review failed ({str(e)[:80]}); one-step root cause instead')
            rc = self.rootcause(issues, frames, res)
            self.doc['rootcause'] = rc
            n_rc = sum(1 for x in rc.get('issues') or [] if not x.get('not_in_code'))
            self.step(4, 'done', f"{self.a.branch} @ {rc.get('commit', '')[:7]} · one-step root cause for {n_rc} of {len(issues)} issue{'s' if len(issues) != 1 else ''}")

    def rootcause(self, issues, frames, res):
        h, wt = self.checkout(self.a.branch)
        bugf = [f for f in frames if f.get('bug')]
        brief = {'card': res.get('card'), 'videos': res.get('videos'),
                 'issues': [{k: x.get(k) for k in ('n', 'title', 'kind', 'expected', 'actual', 'compare', 'crash', 'steps', 'route')} for x in issues],
                 'bug_frames': [{'i': f['i'], 't': f['t'], 'screen': f.get('screen', ''), 'note': f.get('note', '')} for f in bugf[:40]]}
        prompt = (f"# Root cause for Jira card {self.key} in branch {self.a.branch} (commit {h[:10]})\n\n"
                  + (f"## Developer's note (trust it)\n{self.a.note}\n\n" if self.a.note else '')
                  + f"## Title\n{(self.doc.get('card') or {}).get('title', '')}\n\n"
                  f"## What the card reading found\n```json\n{json.dumps(brief, indent=1)[:30000]}\n```\n\n"
                  f"Find the root cause of each issue in THIS checkout (current folder). Read-only.\n")
        txt = llm.run('card-rootcause', prompt, self.cfg, self.dir, 'rootcause', tools='Read,Grep,Glob,Skill', cwd=wt, timeout=2400,
                      block=[f'{t}(/{config.REPO.strip("/")}/**)' for t in ('Read', 'Grep', 'Glob')] + ['Bash', 'WebFetch', 'WebSearch'],
                      model=(self.cfg.get('llm') or {}).get('model_card', 'opus'))
        open(os.path.join(self.dir, 'rootcause.answer.md'), 'w').write(txt)
        m = re.search(r'```json\s*(\{.*\})\s*```', txt, re.S) or re.search(r'(\{.*\})', txt, re.S)
        if not m:
            raise RuntimeError('the root-cause answer had no JSON: ' + txt[:200])
        out = json.loads(m.group(1))
        out.update({'branch': self.a.branch, 'commit': h[:10],
                    'skillUsed': bool(re.search(r'(?m)^\s*SKILL:\s*root-cause', txt)) and 'SKILL-MISSING' not in txt})
        return out

    def plugin(self):
        """Make sure our nightshift-cards plugin is installed for the Claude CLI on this Mac (local marketplace)."""
        claude = shutil.which('claude') or 'claude'
        try:
            lst = subprocess.run([claude, 'plugin', 'list'], capture_output=True, text=True, timeout=120).stdout
            if 'nightshift-cards' in lst:
                subprocess.run([claude, 'plugin', 'marketplace', 'update', 'nightshift'], capture_output=True, text=True, timeout=180)
                subprocess.run([claude, 'plugin', 'update', 'nightshift-cards@nightshift'], capture_output=True, text=True, timeout=180)
                return True
            local = os.path.join(NS, 'claude-plugin')
            subprocess.run([claude, 'plugin', 'marketplace', 'add', local], capture_output=True, text=True, timeout=180)
            subprocess.run([claude, 'plugin', 'marketplace', 'update', 'nightshift'], capture_output=True, text=True, timeout=180)
            r = subprocess.run([claude, 'plugin', 'install', 'nightshift-cards@nightshift'], capture_output=True, text=True, timeout=300)
            print(f'  plugin install nightshift-cards: rc {r.returncode} {(r.stdout + r.stderr).strip()[-200:]}', flush=True)
            return r.returncode == 0
        except Exception as e:
            print(f'  plugin check failed: {e}', flush=True)
            return False

    def field_cases(self):
        """Crash/ANR cases already on the board, so crash-reader can suggest a field match."""
        out = []
        try:
            for d in self.db.collection('cases').limit(60).stream():
                x = d.to_dict() or {}
                t = x.get('title') or x.get('subtitle') or x.get('summary') or ''
                if t:
                    out.append(f"- {d.id[:8]} · {x.get('kind', '')} · {str(t)[:110]} · {x.get('version') or x.get('app_version') or ''}")
        except Exception:
            pass
        return out[:40]

    def watch(self, card, frames, logtext):
        per = SHEET[0] * SHEET[1]
        lines = []
        for vd in self.doc.get('videos') or []:
            vf = [f for f in frames if f['v'] == vd['v']]
            lines.append(f"\n### Video {vd['v']}: {vd['name']} ({vd['seconds']} s, {len(vf)} frames: i = {vd['first']}..{vd['first'] + len(vf) - 1})")
            for s_, path in enumerate(sorted(glob.glob(os.path.join(self.dir, f"v{vd['v']}_sheet_*.jpg")))):
                idx = vf[s_ * per:(s_ + 1) * per]
                lines.append(f'- {os.path.basename(path)}: frames ' + ', '.join(f'{f["i"]} ({f["t"]})' for f in idx))
        cases = self.field_cases()
        note = (f"## Developer's note (trust this over your own reading)\n{self.a.note}\n\n" if self.a.note else '')
        prompt = (note + f"# Jira card {card['key']} · {card['type']} · {card['priority']}\n\n## Title\n{card['title']}\n\n"
                  f"## Description\n{card['description'] or '(empty)'}\n\n## Environment\n{card['environment'] or '(none)'}\n\n"
                  + ('## Comments\n' + '\n'.join(f"- {c['author']}: {c['text'][:600]}" for c in card['comments']) + '\n\n' if card['comments'] else '')
                  + (f'## Log attachments (error lines only)\n```\n{logtext[:12000]}\n```\n\n' if logtext else '')
                  + ('## Contact sheets (open each with Read; frames go left to right, top to bottom)\n' + '\n'.join(lines)
                     + f'\n\nThere are {len(frames)} frames in total: one "frames" entry for each, i = 1..{len(frames)}.\n\n'
                     if frames else '## Video\nThis card has no screen recording: "frames" stays empty; work from the text.\n\n')
                  + ('## Field crash cases on the Night Shift board (for crash-reader)\n' + '\n'.join(cases) + '\n' if cases else ''))
        self.plugin()
        txt = llm.run('card-watch', prompt, self.cfg, self.dir, 'watch', tools='Read,Skill', cwd=self.dir, timeout=1800,
                      model=(self.cfg.get('llm') or {}).get('model_card', 'opus'))
        open(os.path.join(self.dir, 'watch.answer.md'), 'w').write(txt)
        if not txt.strip():
            err = open(os.path.join(self.dir, 'watch.error.txt')).read() if os.path.exists(os.path.join(self.dir, 'watch.error.txt')) else ''
            if 'authenticate' in err or 'login' in err.lower():
                raise RuntimeError('the Claude CLI on the lab Mac is not logged in (session expired): on the Mac open Terminal, run claude, type /login, then press Read card again')
            raise RuntimeError('Claude gave no answer while watching the frames: ' + err.strip().replace('\n', ' ')[:200])
        used = re.findall(r'(?m)^\s*SKILL:\s*([\w-]+)', txt)
        missing = re.findall(r'(?m)^\s*SKILL-MISSING:\s*([\w:-]+)', txt)
        m = re.search(r'```json\s*(\{.*\})\s*```', txt, re.S) or re.search(r'(\{.*\})', txt, re.S)
        if not m:
            raise RuntimeError('the card reading answer had no JSON: ' + txt[:200])
        res = json.loads(m.group(1))
        res['_skills'] = {'used': list(dict.fromkeys(used)), 'missing': missing}
        return res

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--id', required=True)
    ap.add_argument('--card', required=True)
    ap.add_argument('--by', default='')
    ap.add_argument('--note-file', default='')
    ap.add_argument('--branch', default='')
    a = ap.parse_args()
    a.note = open(a.note_file).read().strip()[:1500] if a.note_file and os.path.exists(a.note_file) else ''
    a.fresh = '[fresh]' in a.note                   # "Watch the video again" on the board
    a.note = a.note.replace('[fresh]', '').strip()
    if a.branch and not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', a.branch):
        sys.exit(f'bad branch name: {a.branch}')
    Card(a).go()
