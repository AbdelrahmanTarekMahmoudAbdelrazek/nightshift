#!/bin/bash
# Night Shift: install your worker on this computer (macOS, Linux, or Windows through WSL2).
# Safe to run again: it skips what is already done and never deletes anything.
#   ./setup.sh                      # finds your video_gles3jni checkout, or offers to clone the app for you
#   ./setup.sh ~/video_gles3jni
#   ./setup.sh --create             # your own private board instead of the team board
set -u
KIT="$(cd "$(dirname "$0")" && pwd)"
CONF="$HOME/.config/nightshift"
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$*"; exit 1; }
ask()  { local q="$1" d="${2:-}" a; if [ -n "$d" ]; then read -r -p "  $q [$d]: " a; echo "${a:-$d}"; else read -r -p "  $q: " a; echo "$a"; fi; }
yes()  { local a; read -r -p "  $1 [y/N]: " a; case "$a" in y|Y|yes|YES) return 0;; *) return 1;; esac; }
step() { printf "\n\033[1m%s\033[0m\n" "$*"; }
OS="$(uname -s)"; WSL=0
grep -qi microsoft /proc/version 2>/dev/null && WSL=1
case "$OS" in Darwin) PLAT="macOS";; Linux) [ $WSL = 1 ] && PLAT="Windows (WSL2)" || PLAT="Linux";; *) PLAT="$OS";; esac
printf "Night Shift setup on %s\n" "$PLAT"
openurl() {
  if [ "$OS" = Darwin ]; then open "$1"
  elif [ $WSL = 1 ]; then (command -v wslview >/dev/null && wslview "$1") || cmd.exe /c start "" "$(echo "$1" | sed 's/&/^\&/g')" >/dev/null 2>&1
  else xdg-open "$1" >/dev/null 2>&1 || true; fi
}

step "1/9  The app (video_gles3jni with its modules)"
CREATE=0; REPO=""
for x in "$@"; do case "$x" in --create) CREATE=1;; *) [ -z "$REPO" ] && REPO="$x";; esac; done
if [ -z "$REPO" ]; then
  for c in "$HOME/video_gles3jni" "$HOME/AndroidStudioProjects/video_gles3jni" "$HOME/.nightshift_app/video_gles3jni"; do
    [ -d "$c/app/src/main/cpp/JNI" ] && { REPO="$c"; break; }; done
fi
REPO="${REPO/#\~/$HOME}"
if [ -z "$REPO" ] || [ ! -d "$REPO/app/src/main/cpp/JNI" ]; then
  echo "    No video_gles3jni checkout found${REPO:+ at $REPO}. Night Shift can clone the app for its own use"
  echo "    (in ~/.nightshift_app, not your work folders). It is large (several GB with all modules)."
  yes "Clone it now?" || die "run ./setup.sh <path of your video_gles3jni checkout>"
  command -v git >/dev/null || die "git is missing"
  if ! ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -T git@bitbucket.org 2>&1 | grep -qi "authenticated"; then
    echo "    Bitbucket needs your SSH key once:"
    [ -f "$HOME/.ssh/id_ed25519.pub" ] || ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -C "nightshift" >/dev/null
    echo "    1) copy this line:"; echo; cat "$HOME/.ssh/id_ed25519.pub"; echo
    echo "    2) bitbucket.org → (your avatar) Personal settings → SSH keys → Add key → paste → Save"
    read -r -p "  Press Enter when it is added... " _
    ssh -o BatchMode=yes -T git@bitbucket.org 2>&1 | grep -qi "authenticated" || die "Bitbucket still refuses the key"
  fi
  REPO="$HOME/.nightshift_app/video_gles3jni"; mkdir -p "$HOME/.nightshift_app"
  if [ ! -d "$REPO/.git" ]; then
    git -c url."git@bitbucket.org:".insteadOf="https://bitbucket.org/" clone --recurse-submodules --jobs 4 \
        git@bitbucket.org:mitrotek/video_gles3jni.git "$REPO" || die "clone failed (see above)"
  fi
  ok "app cloned to $REPO"
fi
[ -d "$REPO/app/src/main/cpp/JNI" ] || die "$REPO is not the video_gles3jni app repo (no app/src/main/cpp/JNI)"
ok "$REPO"

step "2/9  Tools on this computer"
miss=0
for t in python3 git adb ffmpeg node npm firebase claude; do
  if command -v "$t" >/dev/null 2>&1; then ok "$t"; else warn "$t is missing"; miss=1; fi
done
if [ $miss = 1 ]; then
  echo "    Install what is missing, then run ./setup.sh again:"
  if [ "$OS" = Darwin ]; then
    echo "      adb + ffmpeg + node:  brew install android-platform-tools ffmpeg node"
  else
    echo "      adb + ffmpeg + node:  sudo apt update && sudo apt install -y adb ffmpeg nodejs npm python3-pip unzip git"
  fi
  echo "      firebase:      npm install -g firebase-tools"
  echo "      claude:        https://docs.claude.com/en/docs/claude-code  (then run 'claude' once and sign in with YOUR company account)"
  die "missing tools"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "python3 3.9 or newer is needed"
[ -x "$REPO/gradlew" ] && ok "gradle wrapper" || warn "no ./gradlew in the checkout (repro builds need it)"
SDKD="$(python3 -c "import sys; sys.path.insert(0, '$KIT/tools/nightshift'); from ns import config; config.REPO = '$REPO'; print(config.android_sdk())" 2>/dev/null)"
if [ -n "$SDKD" ] && [ -d "$SDKD/platform-tools" -o -d "$SDKD/build-tools" ]; then ok "Android SDK at $SDKD"
else warn "no Android SDK: PR Review and Card Issue work; Reproduce, Draft fix and Audio Check need it to build the app"
  [ "$OS" = Darwin ] && echo "      install Android Studio once (it installs the SDK), or set ANDROID_HOME" \
                     || echo "      Linux/WSL2: install Android Studio for Linux or the command-line tools, then: export ANDROID_HOME=~/Android/Sdk"
fi
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

step "4/9  Your Bitbucket and Jira access (stays in $CONF on this computer)"
mkdir -p "$CONF" && chmod 700 "$CONF"
JIRA_URL="$(grep -E '^\s+jira_base_url:' "$KIT/tools/nightshift/nightshift.example.yaml" | sed -E 's/.*jira_base_url:[[:space:]]*"?([^" #]+)"?.*/\1/')"
bb_ok() { python3 - "$1" "$2" <<'PY'
# The token must do exactly what the reviews do: read the repo, list PRs, read one PR's commits and diff.
import base64, json, sys, urllib.request
e, t = sys.argv[1:3]
H = {'Authorization': 'Basic ' + base64.b64encode(f'{e}:{t}'.encode()).decode()}
API = 'https://api.bitbucket.org/2.0/repositories/mitrotek/video_gles3jni'
def get(u, what):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read()
    except Exception as x:
        print(f"    ✗ cannot {what} ({getattr(x, 'code', x)})", file=sys.stderr); sys.exit(1)
get(API, 'read the repository: tick read:repository')
prs = json.loads(get(API + '/pullrequests?pagelen=1&state=OPEN', 'list pull requests: tick read:pullrequest'))
v = prs.get('values') or []
if v:
    n = v[0]['id']
    get(f'{API}/pullrequests/{n}/commits?pagelen=1', f'read PR #{n} commits: tick read:repository AND read:pullrequest')
    get(f'{API}/pullrequests/{n}/diff', f'read PR #{n} diff: tick read:repository')
PY
}
if [ -f "$CONF/bitbucket.json" ]; then
  SBE="$(python3 -c "import json;print(json.load(open('$CONF/bitbucket.json'))['email'])" 2>/dev/null)"
  SBT="$(python3 -c "import json;print(json.load(open('$CONF/bitbucket.json'))['token'])" 2>/dev/null)"
  if bb_ok "$SBE" "$SBT"; then ok "Bitbucket token saved and working"
  else warn "your saved Bitbucket token cannot do everything PR Review needs: make a new one"
    mv "$CONF/bitbucket.json" "$CONF/bitbucket.json.old.$(date +%s)"; fi
fi
if [ ! -f "$CONF/bitbucket.json" ]; then
  TOK_URL="https://id.atlassian.com/manage-profile/security/api-tokens"
  echo
  echo "    Bitbucket token (needed, 1 minute). This page opens in your browser now:"
  printf "      \033[4m%s\033[0m\n" "$TOK_URL"
  echo "      1. Click  Create API token with scopes  → Name: Night Shift → Next"
  echo "      2. Choose  Bitbucket  → Next"
  echo "      3. Tick  read:repository  and  read:pullrequest  → Next → Create → Copy"
  echo
  openurl "$TOK_URL"
  BE="$(ask 'Your company email (the one you use for Jira/Bitbucket)')"
  while true; do
    read -r -s -p "  Paste the Bitbucket token here (it stays hidden) and press Enter: " BT; echo
    if bb_ok "$BE" "$BT"; then break; fi
    warn "Not accepted (see the ✗ line). Make a new token with BOTH read:repository and read:pullrequest, then paste it again."
  done
  python3 - "$CONF/bitbucket.json" "$BE" "$BT" <<'PY'
import json, os, sys
p, e, t = sys.argv[1:4]
json.dump({'email': e, 'token': t, 'workspace': 'mitrotek', 'repo': 'video_gles3jni'}, open(p, 'w'), indent=1)
os.chmod(p, 0o600)
PY
  ok "Bitbucket token works and is saved"
fi
if [ -f "$CONF/jira.json" ]; then ok "Jira token already saved"
else
  TOK_URL="https://id.atlassian.com/manage-profile/security/api-tokens"
  echo
  echo "    Jira token (optional, for Card Issue, 1 minute). This page opens in your browser now:"
  printf "      \033[4m%s\033[0m\n" "$TOK_URL"
  echo "      1. Click  Create API token  (the plain button, not 'with scopes')"
  echo "      2. Name: Night Shift Jira → Create"
  echo "      3. Click Copy, come back here, paste (Cmd+V / Ctrl+Shift+V) and press Enter"
  echo "      Don't need Card Issue? Just press Enter to skip."
  echo
  openurl "$TOK_URL"
  while true; do
    read -r -s -p "  Paste the Jira token here (it stays hidden), or just Enter to skip: " JT; echo
    [ -z "$JT" ] && { warn "Jira skipped: Card Issue will not work until you add it"; break; }
    if python3 - "$JIRA_URL" "${BE:-$(python3 -c "import json;print(json.load(open('$CONF/bitbucket.json'))['email'])")}" "$JT" <<'PY'
import base64, sys, urllib.request
u, e, t = sys.argv[1:4]
r = urllib.request.Request(u.rstrip('/') + '/rest/api/3/myself', headers={'Authorization': 'Basic ' + base64.b64encode(f'{e}:{t}'.encode()).decode(), 'Accept': 'application/json'})
try:
    urllib.request.urlopen(r, timeout=20); sys.exit(0)
except Exception:
    sys.exit(1)
PY
    then
      python3 - "$CONF/jira.json" "$JIRA_URL" "${BE:-$(python3 -c "import json;print(json.load(open('$CONF/bitbucket.json'))['email'])")}" "$JT" <<'PY'
import json, os, sys
p, u, e, t = sys.argv[1:5]
json.dump({'base_url': u, 'email': e, 'token': t}, open(p, 'w'), indent=1)
os.chmod(p, 0o600)
PY
      ok "Jira token works and is saved"; break
    fi
    warn "Jira did not accept it. Try again, or press Enter to skip."
  done
fi

step "5/9  Connect to the team board"
if [ $CREATE = 0 ]; then
  [ -f "$KIT/tools/nightshift/team_board.json" ] || die "this kit has no team board address (team_board.json): ask the board owner"
  CONN="$(cd "$KIT/tools/nightshift" && python3 connect.py)" || die "not connected (see above). Run ./setup.sh again; it is safe to rerun"
  eval "$CONN"
  ROLE=join
  ok "connected to $BURL as $ME"
  firebase login:list 2>/dev/null | grep -q "@" || warn "for 'Sync now' and crash data your Firebase login needs read access to the MyZesty Firebase project: run 'firebase login' later"
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
if [ -n "$SERIAL" ]; then ok "phone found: $SERIAL ($(adb -s "$SERIAL" shell getprop ro.product.model 2>/dev/null | tr -d '\r'))"
else warn "no phone connected: PR Review and Card Issue work without one; connect it later for Reproduce and Audio Check"
  if [ $WSL = 1 ]; then
    echo "      WSL2 cannot see USB by itself. Either:"
    echo "       - Wi-Fi: phone → Developer options → Wireless debugging → Pair with code, then here: adb pair <ip:port> and adb connect <ip:port>"
    echo "       - USB: in Windows PowerShell (admin): winget install usbipd; usbipd list; usbipd bind --busid <id>; usbipd attach --wsl --busid <id>"
  fi
fi
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
      f"  serve_others: {'true' if role == 'create' else 'false'}      # true = also runs jobs of people whose computer is off\n"
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

step "9/9  Start your worker (runs in the background)"
RUN="cd \"$REPO\" && exec python3 -u tools/nightshift/sentinel.py worker"
if yes "Install the background worker now?"; then
  if [ "$OS" = Darwin ]; then
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
    launchctl bootstrap "gui/$(id -u)" "$P" && ok "worker running, starts at login (restart: launchctl kickstart -k gui/\$(id -u)/com.nightshift.worker)"
  elif systemctl --user show-environment >/dev/null 2>&1; then
    U="$HOME/.config/systemd/user"; mkdir -p "$U"
    cat > "$U/nightshift-worker.service" <<SV
[Unit]
Description=Night Shift worker
After=network-online.target

[Service]
ExecStart=/bin/bash -lc '$RUN'
Restart=always
RestartSec=30
StandardOutput=append:/tmp/nightshift-worker.log
StandardError=append:/tmp/nightshift-worker.log

[Install]
WantedBy=default.target
SV
    systemctl --user daemon-reload && systemctl --user enable --now nightshift-worker.service && ok "worker running (restart: systemctl --user restart nightshift-worker)"
    loginctl enable-linger "$USER" 2>/dev/null && ok "it keeps running after you log out" || true
  else
    S="$HOME/.local/bin/nightshift-worker"; mkdir -p "$HOME/.local/bin"
    printf '#!/bin/bash\n# Night Shift worker: start it in the background (WSL2 without systemd)\npgrep -f "^python3 -u tools/nightshift/sentinel.py worker" >/dev/null && { echo "already running"; exit 0; }\nnohup bash -lc %q >> /tmp/nightshift-worker.log 2>&1 &\necho "worker started (log: tail -f /tmp/nightshift-worker.log)"\n' "$RUN" > "$S"
    chmod +x "$S"; "$S"
    grep -qs "nightshift-worker" "$HOME/.bashrc" || echo '[ -x "$HOME/.local/bin/nightshift-worker" ] && "$HOME/.local/bin/nightshift-worker" >/dev/null' >> "$HOME/.bashrc"
    ok "worker running; it starts again whenever you open your WSL terminal"
    [ $WSL = 1 ] && echo "      (to keep it running with no terminal open, turn on systemd in WSL: add '[boot]\nsystemd=true' to /etc/wsl.conf, run 'wsl --shutdown' in Windows, then ./setup.sh again)"
  fi
else warn "start it yourself: $RUN"; fi

printf "\n\033[1mDone.\033[0m Board: \033[4mhttps://%s.web.app\033[0m  (sign in with %s). Jobs you queue run on THIS computer.\n" "$PROJ" "$ME"
echo "Update later:  cd $KIT && ./update.sh $REPO   (not git pull: it keeps what Night Shift learned on this computer)"
