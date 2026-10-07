# League Lab — Phase 2: Private leagues

**Status: built, deployed and tested live (October 5, 2026).** Private ESPN leagues
can be registered with a manager's ESPN login. Like Phase 1, nobody outside can use it
until Google sign-in is set up (see [phase1.md](phase1.md#whats-left)).

## How a private league is registered

The Register page tries the league without a login first. If ESPN refuses, it asks for
the commissioner's ESPN login — the browser cookies `espn_s2` and `SWID` — with
instructions for Chrome/Edge, Safari and Firefox, and a required consent checkbox.
Before anything is saved (`app/onboarding.py`):

| Check | Refusal |
|---|---|
| Both values look like ESPN cookies (spaces/quotes stripped, URL-encoding kept, SWID braced) | "That doesn't look like an espn_s2 / SWID cookie" |
| Consent ticked; league not already registered; caps allow it | as in Phase 1 |
| ESPN accepts the login for this league | "ESPN didn't accept this login for this league" |
| `SWID` (the ESPN account id) is a team owner or member of this league | "This ESPN login belongs to an account that isn't in this league" |

The last check also finds the registrant's own team, so there's no team picker. Then
the login is saved, the league registered (`credentials: "secret:league-<id>-espn"`)
and its first load started. If registration fails after saving, the login is deleted.

## Where the login lives

One Secret Manager secret per league, `league-<id>-espn`, holding only
`{"espn_s2", "SWID"}`. Saving a new login adds a version and destroys the others
(`app/espn_login.py`).

| Account | Save / remove | Read |
|---|---|---|
| `dashboard-sa` (website) | yes — custom role `leagueSecretWriter` (secrets.create/get/delete, versions.add/list/destroy), conditioned on `league-*` | **no** |
| `ingest-sa` (data pull) | yes, `league-*` only | yes — the only reader |

Verified live by impersonating `dashboard-sa`: create, add, destroy and delete worked
on a `league-*` secret; reading it, reading the real league's login, and creating any
other name were all refused. (The impersonation grant was removed afterwards.)

The cookies pass through the website's memory once (forms clear on submit; never
cached, logged or displayed). Removing the login or deleting the league deletes the
secret at once; the purge deletes it again if it's still there.

## Expired or removed logins

- `ingest/credentials.py` raises `NeedsLogin` for a removed or missing login; ingest
  turns an ESPN refusal of a saved login into the same. The league is recorded
  `status: needs_login` (`registry.record_needs_login`) — **not a job failure**, so
  no alert — and the daily schedule skips it until it's reconnected.
- Its data stays visible with a banner on every page.
- League settings → **ESPN login**: the commissioner saves a new login (same checks as
  registration; league set back to `pending` and refreshed at once) or removes it.

## Changes, by file

| File | Change |
|---|---|
| `app/onboarding.py` | `NeedsLogin`, `clean_cookies`, login checks, own-team detection |
| `app/espn_login.py` | new: write-only save/remove of a league's login |
| `app/tenancy.py` | `check_can_register`, `credentials` on register, `set_login`, `remove_login` |
| `app/views/register.py`, `league_admin.py` | private registration; ESPN login section; delete removes the login |
| `app/league.py` | needs-login banner |
| `app/views/privacy.py`, `Home.py`, `ui.py` | policy covers the saved login; public-only wording removed |
| `ingest/credentials.py`, `main.py`, `registry.py` | `NeedsLogin`, needs_login status, skip until reconnected, purge tolerant of a removed secret |
| IAM | custom role `leagueSecretWriter` on `dashboard-sa`, condition `league-*` |

## Verification

| Check | Result |
|---|---|
| Tests | 113 pass (20 new: cookie cleaning, login checks, own team, outsider refused, write-only store, version destroy, tenancy login rules, needs_login skip, credential reads) |
| Real ESPN | With your login, your league previewed and found team 10; without it, "needs login"; a tampered cookie was refused |
| Live cycle on your league | Remove login → secret deleted, needs_login, banner; data pull exits cleanly ("needs a new ESPN login"); wrong login refused; real login reconnected → fresh secret (one enabled version), data refreshed, active |

## Risks and decisions

- **ESPN's terms**: storing members' ESPN logins is the step most likely to draw
  ESPN's attention, and it raises the stakes of a breach. Mitigations: read-only use,
  write-only website, explicit consent, one-click removal, the teardown script deletes
  every login first.
- **Expiry**: commissioners will need to reconnect from time to time; the banner and
  settings page make that a 1-minute job on a computer (not possible on a phone).
- **One login per league**: if that manager leaves the league, their login stops
  working; any other manager can connect theirs — but only the League Lab commissioner
  can save it today.
