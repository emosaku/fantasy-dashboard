# Step 7: Deploy and share

Step 7 takes the Streamlit app and puts it on a URL the league can actually open.
It's the last step, and — as of Step 6 finishing — the only one left with nothing
blocking it.

## What already exists for this step

- `dashboard-sa` service account — BigQuery Data Viewer, BigQuery Job User. Created
  back in Step 1, unused until now; this is the step where it actually gets
  attached to a running service (and gets the two narrow grants below).
- The Cloud Run + Cloud Build + Artifact Registry deploy pattern Step 4 already
  proved out end-to-end for `espn-ingest` (including the real gotchas documented in
  `docs/step4-ingest.md` — schema pinning, the Cloud Run v2 Jobs API, etc.).
- **Step 6 is done and tested.** Home plus 6 pages (Compare, Power Rankings,
  Matchups and Luck, Transactions, Roster Strength, Trade Analyzer) read live
  BigQuery views through `queries.py`, behind manager logins; the trade/waiver
  analyzer and season projection live in `app/analysis/`. 61 tests pass across the
  repo. See [step6-dashboard.md](step6-dashboard.md).
- Manager logins: `scripts/manage_logins.py` writes the password hashes to
  `.streamlit/secrets.toml` (git-ignored) — the deployed service needs that file.
- The Refresh data button (`app/refresh.py`) calls the Cloud Run API to run
  `espn-ingest` — the deployed service needs permission to.
- `.streamlit/config.toml` sets the app's theme (blue accent, since red reads as
  "below average"/"unlucky" on these pages — it shouldn't also mean "selected").

What's missing is everything Step 7 itself builds: no `Dockerfile` for `app/` yet,
nothing deployed, no CI/CD wired up.

## What Step 7 builds

### 1. Containerize and deploy as a Cloud Run **Service** (not a Job)

A Job runs once and exits (`espn-ingest`); a Service stays up and serves requests —
what a dashboard needs.

```bash
gcloud run deploy fantasy-dash \
  --source app/ --region us-west1 \
  --project fantasy-dash-emk \
  --service-account dashboard-sa@fantasy-dash-emk.iam.gserviceaccount.com \
  --allow-unauthenticated --min-instances 0 --max-instances 2 \
  --session-affinity \
  --set-env-vars GCP_PROJECT_ID=fantasy-dash-emk,BIGQUERY_DATASET=fantasy
```

The Dockerfile runs
`streamlit run Home.py --server.port=$PORT --server.address=0.0.0.0`.
`--session-affinity` matters specifically here: Streamlit holds a websocket open
for live updates, and without affinity Cloud Run could bounce a viewer to a
different container instance mid-session and break the connection.

**Two things the image must carry from outside `app/`:** the theme in
`.streamlit/config.toml` (Streamlit reads `.streamlit/` from the working directory,
which is the repo root locally), and nothing else — the logins come in at runtime
(section 2). Either copy `config.toml` into the image's working directory, or build
from the repo root with a Dockerfile that copies `app/` and `.streamlit/config.toml`.

**One simplification `app/`'s Dockerfile gets that `ingest/`'s didn't need:**
`app/`'s modules already use flat imports (`import queries`, `from categories import
...`) rather than package-qualified ones, because that's how Streamlit itself runs
the app (`streamlit run app/Home.py` puts `app/` directly on `sys.path` —
`tests/app/conftest.py` recreates that same path setup for pytest). `ingest/`'s
Dockerfile needed the self-nesting `COPY . ./ingest` trick specifically to keep
`from ingest.transform import ...` working inside the container; `app/`'s
Dockerfile can just be a plain `COPY . .` with the build context pointed at `app/`
directly — no trick needed, because there's no package prefix to preserve.

### 2. Access control: logins and two narrow grants

`--allow-unauthenticated` only lets the link reach the app; every page sits behind a
manager login (Step 6). The deployed service needs:

1. **The login hashes**, from Secret Manager:
   ```bash
   gcloud secrets create dashboard-logins --data-file=.streamlit/secrets.toml
   gcloud secrets add-iam-policy-binding dashboard-logins \
     --member=serviceAccount:dashboard-sa@fantasy-dash-emk.iam.gserviceaccount.com \
     --role=roles/secretmanager.secretAccessor
   ```
   Mount it with `--set-secrets` as a file. **Gotcha:** a Cloud Run secret mount
   takes over its whole directory, so mounting at `<workdir>/.streamlit/secrets.toml`
   would hide `config.toml` next to it. Mount it as Streamlit's global secrets file
   instead (`/root/.streamlit/secrets.toml`, i.e. the container user's home), which
   Streamlit also reads. After `manage_logins.py` adds or resets a login, add a new
   secret version and redeploy (or restart) the service.
2. **Permission to run the ingest job** for the Refresh data button — on that job only:
   ```bash
   gcloud run jobs add-iam-policy-binding espn-ingest --region us-west1 \
     --member=serviceAccount:dashboard-sa@fantasy-dash-emk.iam.gserviceaccount.com \
     --role=roles/run.invoker
   ```

`dashboard-sa` still can't read the ESPN cookie secrets: the Refresh button starts
the job, and the job runs as `ingest-sa`.

### 3. GitHub Actions: what each one is for, and what's built

None of these is required for the dashboard to work. Everything they do can be done
by hand with a few commands, which is how the project has run so far. Each one
automates a step that's easy to forget or get slightly wrong. They're listed by
how much they matter here.

| Action | What it does | Why it matters | Status |
|---|---|---|---|
| **`ci.yml`** — test on every push | On every push and pull request: lint, formatting check, and all tests on Python 3.12 (the version production runs). No Google Cloud access needed. | Catches broken code within about a minute of pushing it, before it's deployed. Before this, tests only ran when someone remembered to, and only on a laptop running Python 3.14 — not the 3.12 production uses. | **Built** |
| **Pinned library versions** (`requirements*.txt`) — not an Action, but CI depends on it | Every library is fixed to the exact version the tests passed on. | Without pins, every deploy installs whatever is newest that day, so a library release — or a change to the unofficial `espn-api` — could break the daily data pull with no code change on our side. Pinned, the job keeps running on tested versions; upgrading becomes a deliberate change that CI tests first. | **Done** |
| `deploy-ingest.yml` — auto-deploy the ingest job | On pushes to `main` that change `ingest/`: run the tests, deploy `espn-ingest`, run it once as a check. | The ingest job was redeployed by hand about ten times in Step 6. The deploy command is easy to get subtly wrong — leaving out one `--set-env-vars` setting silently removes it, since the flag replaces the whole list. Worth it if the ingest code keeps changing. | Not built — stub |
| `deploy-app.yml` — auto-deploy the dashboard | On pushes to `main` that change `app/`: run the tests, deploy the dashboard, check its health endpoint. | Same as ingest, for the website. Only possible after the first manual deploy below. | Not built — stub |
| `deploy-views.yml` — keep BigQuery views in sync | On pushes that change `sql/views/`: re-create all 12 views in dependency order. | Stops the views in BigQuery drifting from the files in the repo. Views rarely change once built, so this is low priority. | Not planned |
| Dependabot — weekly update pull requests | Opens a pull request when a pinned library has a new version; CI tests it. | Keeps pins from going stale without surprises. Mostly useful if `espn-api` ever needs a fix for an ESPN change. | Not planned |

**What the deploy workflows would need first** (one-time setup, the bulk of the
work): enable the STS API; a Workload Identity Federation pool and provider that
only `emosaku/fantasy-dashboard` on `refs/heads/main` can use (the repo is public, so
this condition is what stops forks and other branches deploying); a
`github-deployer` service account with only deploy rights; and two GitHub
repository variables (the provider and the deployer's email — not secrets). GitHub
then signs in to Google Cloud without any stored key.

**Never automated:** table schema changes (`ALTER TABLE`, applied by hand before
pushing code that needs them — they're one-way), manager logins and their secret
(the passwords must never pass through GitHub), and the ESPN cookies.

### 4. Custom domain (optional)

Map a domain you own via Cloud Run domain mapping or a load balancer, instead of
the default `*.run.app` URL. Not required for the league to use the dashboard.

## Done when

Someone in the league opens the link on their phone and sees today's actual data —
not a placeholder, not a localhost demo.

## Suggested order

1. Write `app/Dockerfile`, deploy manually with the `gcloud run deploy` command
   above (plus the logins secret and the two grants), and confirm the live Cloud Run
   URL lets a manager sign in, renders every page against real BigQuery data, and
   the Refresh button works (the same "prove it manually first" approach Step 4 used
   before touching Scheduler or CI/CD).
2. Optional: if the deploy workflows are wanted, do the one-time Workload Identity
   Federation setup above, then flesh out the `deploy-{ingest,app}.yml` stubs.
3. Custom domain only if wanted — it's cosmetic, not blocking.
