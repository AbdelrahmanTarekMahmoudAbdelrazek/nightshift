#!/bin/bash
# Night Shift: install YOUR OWN copy on this Mac (own board, own worker, own phone, own Claude account).
# Safe to run again: it skips what is already done and never deletes anything.
#   ./setup.sh                      # asks where your video_gles3jni checkout is
#   ./setup.sh ~/video_gles3jni
set -u
KIT="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/nightshift"
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$*"; exit 1; }
ask()  { local q="$1" d="${2:-}" a; if [ -n "$d" ]; then read -r -p "  $q [$d]: " a; echo "${a:-$d}"; else read -r -p "  $q: " a; echo "$a"; fi; }
yes()  { local a; read -r -p "  $1 [y/N]: " a; case "$a" in y|Y|yes|YES) return 0;; *) return 1;; esac; }
step() { printf "\n\033[1m%s\033[0m\n" "$*"; }

step "1/9  Your app checkout"
REPO="${1:-}"
[ -z "$REPO" ] && REPO="$(ask 'Path of your video_gles3jni checkout' "$HOME/video_gles3jni")"
REPO="${REPO/#\~/$HOME}"
[ -d "$REPO/app/src/main/cpp/JNI" ] || die "$REPO is not the video_gles3jni app repo (no app/src/main/cpp/JNI)"
ok "$REPO"

step "2/9  Tools on this Mac"
miss=0
for t in python3 git adb ffmpeg node npm firebase claude; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t"; else warn "$t is missing"; miss=1; fi
done
if [ $miss = 1 ]; then
  echo "    Install what is missing, then run ./setup.sh again:"
  echo "      adb + ffmpeg:  brew install android-platform-tools ffmpeg"
  echo "      firebase:      npm install -g firebase-tools"
  echo "      claude:        https://docs.claude.com/en/docs/claude-code  (then run 'claude' once and sign in with YOUR company account)"
  die "missing tools"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "python3 3.9 or newer is needed"
[ -x "$REPO/gradlew" ] && ok "gradle wrapper" || warn "no ./gradlew in the checkout (repro builds need it)"
[ -n "${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}" ] || [ -f "$REPO/local.properties" ] && ok "Android SDK configured" || warn "Android SDK not found (set ANDROID_HOME or open the project once in Android Studio)"
if ! python3 -c 'import firebase_admin, numpy, matplotlib, PIL' 2>/dev/null; then
  warn "Python packages missing: $(tr '\n' ' ' < "$KIT/requirements.txt")"
  if yes "Install them now with pip3 (user install)?"; then
    python3 -m pip install --user -r "$KIT/requirements.txt" || die "pip install failed"
  else die "install them with: python3 -m pip install --user -r $KIT/requirements.txt"; fi
fi
ok "Python packages"

step "3/9  Put Night Shift into your checkout (links, so 'git pull' in the kit updates it)"
for d in tools/nightshift tools/stress; do
  if [ -L "$REPO/$d" ]; then ok "$d already linked"
  elif [ -e "$REPO/$d" ]; then
    mv "$REPO/$d" "$REPO/$d.before-kit.$(date +%Y%m%d%H%M%S)" && warn "your old $d was moved aside (kept, not deleted)"
    mkdir -p "$(dirname "$REPO/$d")"; ln -s "$KIT/$d" "$REPO/$d" && ok "$d linked"
  else mkdir -p "$(dirname "$REPO/$d")"; ln -s "$KIT/$d" "$REPO/$d" && ok "$d linked"; fi
done
if [ -d "$REPO/app/src/debug" ]; then ok "app/src/debug exists (lab remote control: left as it is)"
else cp -R "$KIT/app-overlay/app/src/debug" "$REPO/app/src/debug" && ok "app/src/debug added (LabControl: debug builds only, never in release)"; fi
mkdir -p "$KIT/tools/nightshift/out/batch"
grep -qs "^tools/$" "$REPO/.git/info/exclude" || { echo "tools/" >> "$REPO/.git/info/exclude"; echo "app/src/debug/" >> "$REPO/.git/info/exclude"; ok "tools/ and app/src/debug/ hidden from your git status (local only)"; }

step "4/9  Your keys (stay in $CONF, never in the kit)"
mkdir -p "$CONF" && chmod 700 "$CONF"
if [ -f "$CONF/bitbucket.json" ]; then ok "bitbucket.json"
else
  echo "    Bitbucket API token: bitbucket.org → Personal settings → API tokens, scopes read:repository + read:pullrequest"
  BE="$(ask 'Your Atlassian email')"; BT="$(ask 'The API token (input is visible; it is only written to your Mac)')"
  python3 - "$CONF/bitbucket.json" "$BE" "$BT" <<'PY'
import json, os, sys
p, e, t = sys.argv[1:4]
json.dump({'email': e, 'token': t, 'workspace': 'mitrotek', 'repo': 'video_gles3jni'}, open(p, 'w'), indent=1)
os.chmod(p, 0o600)
PY
  ok "bitbucket.json written (also used for Jira)"
fi

step "5/9  Your board"
echo "    j) JOIN the team board: you got a join pack (nightshift-join-<you>.zip) from its owner  [recommended]"
echo "    c) CREATE your own private board (nobody else sees it)"
MODE="$(ask 'Join or create (j/c)' j)"
if [ "$MODE" = "j" ] || [ "$MODE" = "J" ]; then
  ZIP="$(ls -t "$HOME"/Downloads/nightshift-join-*.zip 2>/dev/null | head -1)"
  ZIP="$(ask 'Path of your join pack' "$ZIP")"; ZIP="${ZIP/#\~/$HOME}"
  [ -f "$ZIP" ] || die "no join pack at $ZIP (ask the board owner: python3 tools/nightshift/joinpack.py <your email>)"
  TMPJ="$(mktemp -d)"; unzip -q -o "$ZIP" -d "$TMPJ" || die "the join pack is damaged"
  cp "$TMPJ/service-account.json" "$CONF/service-account.json" && chmod 600 "$CONF/service-account.json"
  eval "$(python3 - "$TMPJ/board.json" <<'PY'
import json, shlex, sys
b = json.load(open(sys.argv[1]))
for k, v in (('APIKEY', 'apiKey'), ('PROJ', 'projectId'), ('APPID', 'appId'), ('ME', 'for'), ('BURL', 'url')):
    print(f"{k}={shlex.quote(str(b.get(v, '')))}")
PY
)"
  rm -rf "$TMPJ"
  ROLE=join
  firebase login:list 2>/dev/null | grep -q "@" || warn "for 'Sync now' and crash data your Firebase login needs read access to the MyZesty Firebase project: run 'firebase login' later"
  ok "joining board $PROJ as $ME (worker key saved in $CONF; delete the zip now: rm \"$ZIP\")"
else
  ROLE=create
firebase login:list 2>/dev/null | grep -q "@" || { echo "    Sign in to Firebase with your Google account:"; firebase login || die "firebase login failed"; }
ME="$(ask 'Your company email (only you can sign in at first)')"
case "$ME" in *@msd-my.com) ;; *) die "use your @msd-my.com address";; esac
SHORT="$(echo "${ME%%@*}" | tr -cd 'a-z0-9' | cut -c1-14)"
PROJ="$(grep -E '^\s+projectId:' "$KIT/tools/nightshift/nightshift.yaml" 2>/dev/null | sed -E 's/.*projectId:[[:space:]]*"?([a-z0-9-]*)"?.*/\1/')"
[ -z "$PROJ" ] && PROJ="$(ask 'Board project id (lowercase, unique)' "nightshift-$SHORT")"
if firebase projects:list 2>/dev/null | grep -q " $PROJ "; then ok "project $PROJ exists"
else
  yes "Create the free Firebase project $PROJ now?" || die "stopped"
  firebase projects:create "$PROJ" --display-name "Night Shift $SHORT" || die "could not create $PROJ (the id may be taken: run again with another id)"
fi
APPID="$(firebase apps:list WEB --project "$PROJ" 2>/dev/null | grep -oE '1:[0-9]+:web:[0-9a-f]+' | head -1)"
if [ -z "$APPID" ]; then firebase apps:create WEB "Night Shift board" --project "$PROJ" >/dev/null || die "could not add the web app"
  APPID="$(firebase apps:list WEB --project "$PROJ" | grep -oE '1:[0-9]+:web:[0-9a-f]+' | head -1)"; fi
SDK="$(firebase apps:sdkconfig WEB "$APPID" --project "$PROJ" 2>/dev/null)"
APIKEY="$(echo "$SDK" | grep -oE '"?apiKey"?: *"[^"]+"' | sed -E 's/.*"([^"]+)"$/\1/')"
[ -n "$APIKEY" ] || die "could not read the web config (firebase apps:sdkconfig WEB $APPID --project $PROJ)"
ok "web app $APPID"
firebase firestore:databases:list --project "$PROJ" 2>/dev/null | grep -q "(default)" && ok "database exists" || {
  firebase firestore:databases:create "(default)" --location eur3 --project "$PROJ" >/dev/null 2>&1 && ok "database created (eur3)" || warn "create the database by hand: https://console.firebase.google.com/project/$PROJ/firestore (Production mode, eur3)"; }
echo
echo "    Two clicks in the Firebase console (the CLI cannot do these):"
echo "     a) Sign-in: https://console.firebase.google.com/project/$PROJ/authentication/providers"
echo "        → Get started → Email/Password → enable BOTH switches (incl. 'Email link (passwordless sign-in)') → Save"
echo "     b) Worker key: https://console.firebase.google.com/project/$PROJ/settings/serviceaccounts/adminsdk"
echo "        → Generate new private key → save it as  $CONF/service-account.json"
while [ ! -f "$CONF/service-account.json" ] || ! grep -q "\"$PROJ\"" "$CONF/service-account.json"; do
  read -r -p "  Press Enter when $CONF/service-account.json (of $PROJ) is saved... " _
done
chmod 600 "$CONF/service-account.json"; ok "worker key in place"

fi

step "6/9  Your settings (tools/nightshift/nightshift.yaml, never pushed)"
Y="$KIT/tools/nightshift/nightshift.yaml"
[ -f "$Y" ] || cp "$KIT/tools/nightshift/nightshift.example.yaml" "$Y"
SERIAL="$(adb devices | awk 'NR>1 && $2=="device" && $1 !~ /^emulator-/ {print $1; exit}')"
[ -n "$SERIAL" ] && ok "phone found: $SERIAL ($(adb -s "$SERIAL" shell getprop ro.product.model 2>/dev/null | tr -d '\r'))" || warn "no phone connected: PR Review and Card Issue work without one; plug it in later for repro and Audio Check"
BASE="$(ask 'Branch your crash builds start from' "$(grep -E '^\s+base_branch:' "$Y" | sed -E 's/.*base_branch:[[:space:]]*([^ #]+).*/\1/')")"
python3 - "$Y" "$APIKEY" "$PROJ" "$APPID" "$SERIAL" "$BASE" "$ROLE" "$ME" <<'PY'
import re, sys
p, key, proj, app, serial, base = sys.argv[1:7]
s = open(p, encoding='utf-8').read()
def put(k, v, quote=True):
    global s
    s = re.sub(rf'^(\s+{k}:\s*)[^#\n]*', lambda m: m.group(1) + (f'"{v}"' if quote else v) + ' ', s, count=1, flags=re.M)
put('apiKey', key); put('authDomain', f'{proj}.firebaseapp.com'); put('projectId', proj); put('appId', app)
put('phone_serial', serial, quote=False) if serial else None
put('base_branch', base, quote=False)
role, me = sys.argv[7], sys.argv[8]
s = re.sub(r'\nworker:.*?(?=\n\S|\Z)', '', s, flags=re.S)        # one worker: section, rewritten
s += (f"\nworker:                                   # shared board: whose jobs this worker runs\n  owner: {me}\n"
      f"  serve_others: {'true' if role == 'create' else 'false'}      # true = also runs jobs of people whose Mac is off\n"
      f"  deploy_board: {'true' if role == 'create' else 'false'}      # only the board host publishes the website\n")
open(p, 'w', encoding='utf-8').write(s)
PY
ok "nightshift.yaml: board $PROJ, phone ${SERIAL:-none}, base $BASE"

step "7/9  Publish your board"
if [ "$ROLE" = "join" ]; then ok "joined the team board: nothing to publish (its owner publishes it)"; else
B="$KIT/tools/nightshift/board"
printf '{ "projects": { "default": "%s" } }\n' "$PROJ" > "$B/.firebaserc"
python3 - "$B/firebase.json" "$PROJ" <<'PY'
import json, sys
p, proj = sys.argv[1:3]
nc = [{'key': 'Cache-Control', 'value': 'no-cache'}]
json.dump({'hosting': {'site': proj, 'public': 'public', 'ignore': ['firebase.json', '**/.*'],
                       'rewrites': [{'source': '**', 'destination': '/index.html'}],
                       'headers': [{'source': '**', 'headers': [{'key': 'X-Frame-Options', 'value': 'DENY'}, {'key': 'Referrer-Policy', 'value': 'no-referrer'}]},
                                   {'source': '/', 'headers': nc}, {'source': '**/*.@(html)', 'headers': nc}, {'source': '/v/**', 'headers': nc}]},
           'firestore': {'rules': 'firestore.rules', 'indexes': 'firestore.indexes.json'}}, open(p, 'w'), indent=2)
PY
( cd "$REPO" && python3 tools/nightshift/sentinel.py board --live >/dev/null ) || die "board build failed"
firebase hosting:sites:list --project "$PROJ" 2>/dev/null | grep -q "$PROJ" || firebase hosting:sites:create "$PROJ" --project "$PROJ" >/dev/null 2>&1 || true
( cd "$B" && firebase deploy --only hosting,firestore --project "$PROJ" --non-interactive ) || die "deploy failed (see above)"
( cd "$REPO" && python3 tools/nightshift/sentinel.py staff add "$ME" --note owner >/dev/null ) && ok "you are on your board's allowlist"
python3 - "$CONF/service-account.json" <<'PY'
import sys, firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(sys.argv[1]))
firestore.client().collection('config').document('board').set({'requireAllowlist': True}, merge=True)
PY
ok "board is private: only addresses you add can open it (sentinel.py staff add <email>)"
fi

step "8/9  Claude reviewers (your own Claude account)"
claude -p "reply with OK" 2>/dev/null | grep -qi ok && ok "claude is signed in" || warn "run 'claude' once and sign in with your company account, then ./setup.sh again"
( cd "$REPO" && python3 tools/nightshift/plugsetup.py >/dev/null 2>&1 ) && ok "review plugins installed" || warn "plugins: run python3 tools/nightshift/plugsetup.py and read out/batch/plugsetup.txt"

step "9/9  Start your worker (runs in the background, starts at login)"
if yes "Install the background worker now?"; then
  P="$HOME/Library/LaunchAgents/com.nightshift.worker.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$P" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nightshift.worker</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>-ilc</string>
    <string>cd "$REPO" &amp;&amp; exec python3 -u tools/nightshift/sentinel.py worker</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>/tmp/nightshift-worker.log</string><key>StandardErrorPath</key><string>/tmp/nightshift-worker.log</string>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/com.nightshift.worker" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$P" && ok "worker running (log: tail -f /tmp/nightshift-worker.log; stop: launchctl bootout gui/\$(id -u)/com.nightshift.worker)"
else warn "start it yourself: cd $REPO && python3 tools/nightshift/sentinel.py worker"; fi

printf "\n\033[1mDone.\033[0m Board: \033[4mhttps://%s.web.app\033[0m  (sign in with %s). Jobs you queue run on THIS Mac.\n" "$PROJ" "$ME"
echo "Update later:  cd $KIT && git pull && ./setup.sh $REPO"
