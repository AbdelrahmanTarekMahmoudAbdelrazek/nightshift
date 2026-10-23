# Night Shift

Your own crash & ANR desk for the MyZesty app: it gathers crashes and ANRs, reviews pull requests, reads Jira cards,
reproduces crashes on **your** phone and checks audio at clip cuts. Each person runs their own copy:
own board website, own worker, own phone, own Claude account. Nothing is shared, so one person's Mac being off never
stops anyone else.

| Tool | Needs a phone | What you get |
|---|---|---|
| Crashes & ANRs | no (yes to reproduce) | Crashlytics + Play in one list, filters, root cause, repro on your phone, a fix checked on the phone |
| PR Review | no | 8 reviewers (Claude) on any PR of the project's repos; a JNI check against the Kotlin side |
| Card Issue | no | the root cause of a Jira card, from its text, video and the code |
| Audio Check | yes | does audio stay clean at clip cuts, branch against today's code, 3 exports, listen per cut |

## Install (about 15 minutes, once)

You need: a Mac, your `video_gles3jni` checkout that builds in Android Studio, Homebrew, and your company Claude account.

```bash
git clone https://github.com/AbdelrahmanTarekMahmoudAbdelrazek/nightshift.git ~/nightshift
cd ~/nightshift && ./setup.sh ~/video_gles3jni
```

`setup.sh` checks your tools, links Night Shift into your checkout (`tools/nightshift`, `tools/stress`; hidden from
your git status), adds the debug-only lab remote control (`app/src/debug`), asks for your Bitbucket token, creates
**your** free Firebase project for your board, publishes it, installs the Claude review plugins and starts your worker.
Two console clicks are needed (sign-in method + worker key); the script shows the exact links and waits.

Then open `https://<your-project>.web.app` and sign in with your @msd-my.com address. Your board is private: add a
teammate with `python3 tools/nightshift/sentinel.py staff add their@msd-my.com` (run in your checkout).

**Crash data**: the daily gathering reads Crashlytics with *your* Firebase login (`firebase login`), so your Google
account needs read access to the MyZesty Firebase project. Play vitals are optional: `sentinel.py play-login` once.

## Update
```bash
cd ~/nightshift && git pull && ./setup.sh ~/video_gles3jni
```
The worker picks up code changes on its next job; `setup.sh` only redoes what is missing.

## Safety
Read-only on production (Crashlytics, Play, Bitbucket, Jira). Nothing is committed, pushed or merged by Night Shift.
Crash builds happen in their own folder (`~/.nightshift_lab`), never in your working copy. Your keys stay in
`~/.config/nightshift/`; this repo contains none. See SECURITY.md in `tools/nightshift`.

Daily use: [SOP.md](SOP.md).
