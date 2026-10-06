# Step 7: Deploy and share

The dashboard is live on Cloud Run as the service **`fantasy-dash`** (region
`us-west1`), on its default `*.run.app` address. Every manager signs in with their
own login, on a phone or a computer. The address isn't written here on purpose —
the repo is public — and is shown by:

```bash
gcloud run services describe fantasy-dash --region us-west1 --project fantasy-dash-emk \
  --format='value(status.url)'
```

A plain-language walkthrough of how the site was created, for anyone in the league:
[How the league website was built](https://claude.ai/code/artifact/de41d72f-b068-4fb9-ba28-da3f14d43773)
(a private doc; ask the commissioner for access). This file is the technical record.

## What was built

### 1. The image (`Dockerfile` at the repo root)

`python:3.12-slim`, the pinned `requirements.txt`, `app/` and
`.streamlit/config.toml`, running
`streamlit run app/Home.py --server.port=$PORT --server.address=0.0.0.0`. It's built
from the repo root because it needs the theme file next to `app/`; the ingest job
keeps its own image in `ingest/`.

**`.gcloudignore` decides what gets uploaded to Cloud Build** — only the Dockerfile,
requirements, `app/` and `.streamlit/config.toml`. It excludes `.env` (ESPN cookies),
`.streamlit/secrets.toml` (login hashes) and `manager-logins.csv` (passwords) by
name; `gcloud meta list-files-for-upload .` confirms the upload set before a deploy.
`.dockerignore` mirrors it for local builds.

`.streamlit/config.toml` sets `toolbarMode = "viewer"`, which hides Streamlit's
developer "Deploy" button and menu items from the league.

### 2. Logins, from Secret Manager

The login hashes live in the secret **`dashboard-logins`** (a copy of the local,
git-ignored `.streamlit/secrets.toml`), mounted into the container as Streamlit's
global secrets file, `/root/.streamlit/secrets.toml`. Not inside the app's own
`.streamlit/` folder: a Cloud Run secret mount takes over its whole directory and
would hide `config.toml`.

**After adding or resetting logins** with `scripts/manage_logins.py`, publish the new
file and roll the service so it reads it:

```bash
gcloud secrets versions add dashboard-logins --data-file=.streamlit/secrets.toml
gcloud run services update fantasy-dash --region us-west1 --project fantasy-dash-emk \
  --update-labels=logins-updated=$(date +%s)
```

**Stay signed in.** Phones reload a page whenever you switch back to the browser,
which would otherwise mean signing in again each time. Signing in now stores a signed
30-day token in a cookie (`app/auth.py`, `app/login.py`): an HMAC over the username,
expiry and part of the password hash, keyed with `cookie_secret` from the logins
file. It can't be forged or extended, log out clears it, and resetting a password
invalidates it.

### 3. Permissions: two narrow grants to `dashboard-sa`

The service runs as `dashboard-sa`, which already had BigQuery Data Viewer and Job
User. Step 7 added only:

| Grant | On | For |
|---|---|---|
| `roles/secretmanager.secretAccessor` | the `dashboard-logins` secret only | reading the logins |
| `roles/run.invoker` | the `espn-ingest` job only | the Refresh data button |

The Refresh button starts the job, then waits for the data rather than watching the
job: watching would need `run.operations.get`, which can only be granted
project-wide. Ingest writes `league_status` last, so a newer timestamp there means
the whole refresh has landed. `dashboard-sa` still can't read the ESPN cookie
secrets; the job runs as `ingest-sa`.

### 4. The deploy command

```bash
gcloud run deploy fantasy-dash --project fantasy-dash-emk \
  --source . --region us-west1 \
  --service-account dashboard-sa@fantasy-dash-emk.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 2 \
  --session-affinity --timeout 3600 \
  --memory 1Gi --cpu 1 \
  --set-secrets /root/.streamlit/secrets.toml=dashboard-logins:latest \
  --set-env-vars GCP_PROJECT_ID=fantasy-dash-emk,BIGQUERY_DATASET=fantasy
```

- `--allow-unauthenticated` lets the link reach the app; the app itself requires a
  login on every page.
- `--min-instances 0` scales to zero when nobody's using it: about $0 at league
  scale, at the cost of a few seconds' wake-up on the first visit after a quiet spell.
- `--session-affinity` and `--timeout 3600`: Streamlit holds a websocket open for the
  whole visit. Affinity keeps a viewer on one instance; the default 5-minute request
  timeout would cut every session off after 5 minutes.
- `--set-env-vars` replaces the whole list — re-run it complete.

To redeploy after code changes, run the same command from the repo root.

### 5. Phones

Streamlit pages adapt to the screen on their own: columns stack, the sidebar
becomes a menu button, charts resize. Checked on the live site at iPhone width
(390 px): every page renders with no errors and nothing scrolls sideways. Fixed
along the way: the Roster Strength category chart's value labels were cut off or ran
into team names, and pre-season scoreboards said "Tied 0-0-0" (now "Not played
yet"). Managers can use **Add to Home Screen** for an app-like icon.

## Verified on the live site

- Sign-in page loads; signing in works; **a reload keeps you signed in**; log out
  signs you out and a reload stays signed out.
- Home and all 6 pages render with no errors at phone width and on desktop.
- **Refresh data** started the real ingest job from the live site, waited for the
  new data (last update 20:46 → 21:21 UTC on Oct 5) and reloaded with it.

## GitHub Actions: what each one is for, and what's built

None of these is required for the site to work. Everything they do can be done by
hand with a few commands, which is how the project has run so far. Each one
automates a step that's easy to forget or get slightly wrong.

| Action | What it does | Why it matters | Status |
|---|---|---|---|
| **`ci.yml`** — test on every push | On every push and pull request: lint, formatting check, and all tests on Python 3.12 (the version production runs). No Google Cloud access needed. | Catches broken code within about a minute of pushing it. Before this, tests only ran when someone remembered to, and only on a laptop running Python 3.14 — not the 3.12 production uses. | **Built** |
| **Pinned library versions** (`requirements*.txt`) — not an Action, but CI depends on it | Every library is fixed to the exact version the tests passed on. | Without pins, every deploy installs whatever is newest that day, so a library release — or a change to the unofficial `espn-api` — could break the site or the daily data pull with no code change on our side. Upgrading becomes a deliberate change that CI tests first. | **Done** |
| `deploy-ingest.yml` — auto-deploy the ingest job | On pushes to `main` that change `ingest/`: test, deploy `espn-ingest`, run it once as a check. | The ingest job was redeployed by hand about ten times. The command is easy to get subtly wrong — leaving out one `--set-env-vars` setting silently removes it. Worth it if the ingest code keeps changing. | Not built — stub |
| `deploy-app.yml` — auto-deploy the dashboard | On pushes to `main` that change `app/`: test, run the deploy command above, check the health endpoint. | Same, for the website. | Not built — stub |
| `deploy-views.yml` — keep BigQuery views in sync | On pushes that change `sql/views/`: re-create all 12 views in dependency order. | Stops BigQuery drifting from the repo. Views rarely change, so low priority. | Not planned |
| Dependabot — weekly update pull requests | Opens a pull request when a pinned library has a new version; CI tests it. | Keeps pins from going stale without surprises. | Not planned |

**What the deploy workflows would need first:** enable the STS API; a Workload
Identity Federation pool and provider only `emosaku/fantasy-dashboard` on
`refs/heads/main` can use (the repo is public, so this is what stops forks and other
branches deploying); a `github-deployer` service account with only deploy rights; and
two GitHub repository variables (not secrets).

**Never automated:** table schema changes (`ALTER TABLE`, applied by hand before
pushing code that needs them), manager logins and their secret (passwords must never
pass through GitHub), and the ESPN cookies.

## Optional next steps

- **A custom domain** (e.g. `ourleague.com`, ~$10-20/year). The `run.app` link works
  the same; a domain is only easier to share and remember. Cloud Run's built-in
  domain mapping works in some regions only; otherwise Firebase Hosting in front
  (free at this size).
- **Stronger passwords.** Every manager currently has the same password, chosen by
  the commissioner, and usernames follow a predictable pattern. Anyone who learns the
  address and one manager's name can sign in as them.
  `python scripts/manage_logins.py --reset-all` issues random ones.

## Done when

Someone in the league opens the link on their phone and sees today's data. **Done**:
live, signed-in, phone-checked, with the Refresh button working end to end.
