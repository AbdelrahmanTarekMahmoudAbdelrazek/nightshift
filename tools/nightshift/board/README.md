# Case board — Firebase (free Spark plan)

One-time setup (console, ~10 minutes), then everything is `firebase deploy`.

1. Create a **new** Firebase project (e.g. `nightshift-myzesty`). Keep it separate from the production app project.
2. Build → Authentication → Sign-in method → **Email/Password** → enable **Email link (passwordless sign-in)**.
   Authentication → Settings → Authorized domains: add your Hosting domain (`<project>.web.app`).
3. Build → Firestore Database → create (production mode; the rules file below replaces the defaults).
4. Project settings → Your apps → add a **Web app**; copy the `firebaseConfig` into `nightshift.yaml` under `firebase:`.
5. Project settings → Service accounts → **Generate new private key** → save OUTSIDE the repo, e.g.
   `~/.config/nightshift/service-account.json`, and set `NIGHTSHIFT_SA=~/.config/nightshift/service-account.json` for the worker.
6. On this Mac: `npm i -g firebase-tools && firebase login`, then in `tools/nightshift/board/`:
   `cp .firebaserc.example .firebaserc` (edit the project id) and `python3 ../sentinel.py board --live` to build `public/`, then
   `firebase deploy --only hosting,firestore`.
7. Allowlist (optional): add documents `staff/<email>` and set `config/board.requireAllowlist = true`
   (`sentinel.py staff add you@msd-my.com`).

Data flow: the worker on this Mac writes `cases`, `findings`, `runlog` with the Admin SDK; the browser only reads them
and may create `jobs`. `sentinel.py worker` listens for `jobs` with `status == queued`, runs them, and streams
`status`/`log` back so the page updates live.
