# League Lab: cost guardrails and the kill switch

League Lab runs in its own Google Cloud project, **`league-lab-emk`** ("League Lab",
billed to Eni's Billing), so its costs and its shutdown never touch the original
league's site in `fantasy-dash-emk`. Three guardrails keep it near $0:

| Guardrail | Setting | What happens |
|---|---|---|
| Budget | **$5/month**, project `league-lab-emk` only | Emails at 50%, 90% and 100%; every update goes to the kill switch |
| Kill switch | Cloud Run function `killswitch` on Pub/Sub topic `budget-alerts` | At 100% of budget: pauses every Cloud Scheduler job and removes public access from every Cloud Run service |
| BigQuery cap | **30 GiB of queries a day** (quota preference `bq-daily-query-cap`) | Queries fail for the rest of the day instead of costing money. 30 GiB/day stays inside the free 1 TB/month |

## How the kill switch works

Cloud Billing publishes the month's cost to `budget-alerts` several times a day. The
function (`ops/killswitch/`) checks it; under budget, it logs and does nothing. At or
over budget it:

1. **Pauses every enabled Cloud Scheduler job** in `us-west1` — no more ESPN pulls.
2. **Removes `allUsers` from `roles/run.invoker`** on every Cloud Run service in
   `us-west1` — the site stops accepting visitors, so it can't start instances or
   run up a bill. Services without public access (the function itself) are untouched.

It runs as `killswitch-sa`, whose custom role `killSwitch` allows exactly five things:
list and pause Scheduler jobs; list services and read/set their access policy. It
can't deploy, delete or read data.

Budget data reaches the switch with some delay (Cloud Billing reports cost a few
times a day), so it caps a runaway bill at roughly the budget plus a few hours of
spend — not to the cent.

## Is it tripped?

```bash
gcloud logging read 'resource.labels.service_name="killswitch"' \
  --project league-lab-emk --freshness=7d --format="value(timestamp,textPayload)"
```

A `KILL SWITCH TRIPPED` line lists what was paused and closed.

## Turning things back on (deliberate, manual)

Find out why spend hit the budget first. Then:

```bash
# Re-open the site to visitors (repeat per service)
gcloud run services add-iam-policy-binding SERVICE --region us-west1 \
  --project league-lab-emk --member=allUsers --role=roles/run.invoker
# Resume the scheduled jobs (repeat per job)
gcloud scheduler jobs resume JOB --location us-west1 --project league-lab-emk
```

If the month's spend is still at or over budget, the next budget update trips it
again — raise the budget or wait for the new month.

## Testing it safely

Publishing a fake budget message exercises the whole path. **An over-budget test
really trips it** — only do that when re-opening afterwards is fine.

```bash
gcloud pubsub topics publish budget-alerts --project league-lab-emk \
  --message='{"costAmount":1.10,"budgetAmount":5.0,"currencyCode":"USD"}'
```

Tested Oct 5, 2026, before anything else existed in the project: an under-budget
message was ignored ("under budget, nothing to do"), and an over-budget one tripped
it ("Paused []; closed []" — nothing to act on yet).

## Changing the limits

- **Budget:** Billing > Budgets & alerts > "League Lab monthly" in the console, or
  `gcloud billing budgets update`.
- **BigQuery cap:** `gcloud beta quotas preferences update bq-daily-query-cap
  --service=bigquery.googleapis.com --project=league-lab-emk
  --billing-project=league-lab-emk --preferred-value=<MiB>`.
