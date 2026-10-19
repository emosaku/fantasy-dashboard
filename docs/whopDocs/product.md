# LeagueLabWhop: from personal tool to product

**Status: plan (October 18, 2026); the GCP project is set up and running (section 1).**
League Lab was built for 3-4 of Eni's own leagues: a sign-in allowlist, small caps
and a $5 kill switch. Selling it on Whop means real signups, payment, support and a
public face. This doc covers everything that isn't the data model
([projections.md](projections.md), [espn-data.md](espn-data.md)).

## 1. Its own Google Cloud project

| | |
|---|---|
| Project | `league-lab-whop` ("LeagueLabWhop", project number 239690658888) |
| Billing | "Eni's Billing". It allows 5 linked projects, so "My First Project" (`graphite-wave-466600-a1`, one empty bucket) was unlinked to make room |
| Site | `league-lab`: https://league-lab-239690658888.us-west1.run.app (built from `WhopVersion`; sign-in not set up yet) |
| Why separate | League Lab stays the personal tool. Paying customers' data, the public sign-in screen and the product's costs stay apart from it, and teardown of either never touches the other |

**Copied from `league-lab-emk`** on October 18, everything in
[phase0.md](../multiLeagueDocs/phase0.md) and [killswitch.md](../multiLeagueDocs/killswitch.md):
region `us-west1`; Firestore native `(default)`; BigQuery dataset `league_lab` from
`scripts/apply_sql.py` (now without the Draft tables); `ingest-sa`, `dashboard-sa`,
`killswitch-sa` and the custom roles `killSwitch` and `leagueSecretWriter` with the same
bindings; Cloud Run service `league-lab` and job `league-ingest` (2 tasks) built from
`WhopVersion`; Scheduler `league-ingest-daily` (05:30 America/Phoenix); budget, Pub/Sub
`budget-alerts`, the `killswitch` function, the 30 GiB/day BigQuery cap and the
"ingest failed" email alert ("LeagueLabWhop ingest failed").

**Checked:** a manual `league-ingest` run succeeded on both tasks (no leagues yet); the
site's health check returns 200; an under-budget test message reached the kill switch
("Budget check: 1.1 of 5.0 -- under budget, nothing to do"). One step the docs didn't
record: `killswitch-sa` needs `roles/run.invoker` on the `killswitch` service, because
its Pub/Sub trigger runs as that account.

**Still to do:** the sign-in client and secret `league-lab-auth` (section 2), created in
the Cloud Console, then mounted with `gcloud run services update league-lab --region
us-west1 --project league-lab-whop --update-secrets
/root/.streamlit/secrets.toml=league-lab-auth:latest` after granting `dashboard-sa`
Secret Accessor on it.

**Not copied, on purpose:**

| Left behind | Why |
|---|---|
| Firestore registry, users and memberships | League Lab's users; the product starts empty |
| BigQuery data | Same |
| Secret `league-383633368-espn` | Eni's own ESPN login for DON FOOLIO |
| Secret `league-lab-auth` (the Google sign-in client) | It belongs to League Lab's sign-in screen, in Testing mode. The product gets its own (section 2) |

## 2. Sign-in

League Lab's Google sign-in is in "Testing" mode: at most 100 test users, and the
test-user list is the allowlist. For the product:

- **Option A, Google sign-in plus a Whop check.** A new sign-in client in
  `league-lab-whop`, published to production. Needs a privacy policy, a home page and a
  domain we own on the sign-in screen (so a custom domain for the site, not the
  `run.app` address). After sign-in, match the email to an active Whop membership.
- **Option B, sign in with Whop.** If Whop's OAuth works as an OpenID Connect provider,
  Streamlit's `st.login` can use it directly (it only needs `server_metadata_url`), and
  membership comes with the sign-in. One account, no Google verification.

**Recommendation: check B first (phase 0); fall back to A.**

## 3. Payment through Whop

- **Plans.** Price by number of leagues (for example 1 league, or up to 3), monthly
  and per season. A short free trial helps people see their own league before paying.
- **Membership state.** Whop sends webhooks when a membership starts, renews or ends. A
  small Cloud Run function (`whop-webhook`, new) verifies each one and writes
  `subscriptions/{user}` in Firestore. A daily reconcile against Whop's API catches
  missed webhooks.
- **The gate.** `app/tenancy.py` checks for an active subscription where it checks the
  allowlist today. When a membership lapses, the user's leagues stop refreshing and,
  after a grace period, are purged (the existing "deleting" path).

Exact Whop event names, signature checks and OAuth details get confirmed against
Whop's docs in phase 0.

## 4. Caps, cost and the kill switch

| Today (League Lab) | Product |
|---|---|
| `MAX_LEAGUES` 10, `MAX_LEAGUES_PER_USER` 3 | Per-user cap from the plan; total cap raised step by step with real cost data |
| $5 budget; the kill switch closes the site at 100% | Closing a paid site cuts off paying customers. Budget alerts email first; the kill switch moves to a much higher hard ceiling |
| 30 GiB/day BigQuery cap | Raised with the league count |
| Per-league DML not batched (dropped as scaling work) | **Back in scope:** one load per table per task for all its leagues. League Lab measured ~1.7 GB of BigQuery per league per run, mostly per-statement minimums; the free 1 TB/month covers ~18 leagues |

Past the free tier, BigQuery on demand is about $6.25 per TB, so a league costs
roughly $0.30 a month in queries at today's rate, less after batching and the Draft
Tool's removal. Cloud Run scales to zero between visits.

## 5. The public face

- **Name and domain.** "LeagueLabWhop" is the project's name; the product name on Whop,
  the sign-in screen and the site can differ. Buy the domain once that's settled.
- **Privacy policy and terms.** Rewrite `app/views/privacy.py` for paying users: what we
  store (email, league ids, nothing from ESPN beyond the league), how to delete it,
  refunds, "not affiliated with ESPN".
- **Support.** A support email on the Whop listing and the site.
- **A projections methodology page** ([projections.md](projections.md), phase 4).

## Questions for a lawyer

One short consult before charging anyone:

1. Is reading a customer's own ESPN league with their permission, from ESPN's
   unofficial API, acceptable risk for a paid product? What would ESPN's terms let them
   do (block, demand to stop)?
2. Can we say "works with ESPN leagues" and name ESPN at all?
3. Showing actual NBA stats served by ESPN, versus from a licensed source: does it matter?
4. What the privacy policy and terms must say for US customers (and anywhere else Whop
   sells to).
5. Should this run under a business entity (LLC) rather than personally?

## Order of work

0. **Check.** Confirm
   Whop's OAuth and webhooks; pick the stats source; book the lawyer.
1. **Data:** drop the outlook and build the projection model to its ship bar.
2. **Accounts and payment:** sign-in, the webhook, the subscription gate, plan caps.
3. **Public face:** domain, privacy policy and terms, support, methodology page.
4. **Launch** on Whop with a small first group, then raise caps as cost data comes in.
