"""Entry point for the espn-ingest Cloud Run Job (Step 4).

Will: build the espn_api League object from LEAGUE_ID/SEASON/ESPN_S2/SWID (injected as
env vars via Cloud Run's --set-secrets, not read from Secret Manager directly), pull
the five data sources described in docs/proposal.md (Step 3), transform each into a
DataFrame, and MERGE into its BigQuery target table via a staging table for
idempotency. Not implemented yet -- Step 1-3 (GCP project, local data access proof,
BigQuery schema) come first.
"""


def main() -> None:
    raise NotImplementedError("Step 4: ingest job")


if __name__ == "__main__":
    main()
