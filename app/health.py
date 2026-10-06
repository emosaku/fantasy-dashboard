"""Health and durability: ESPN's injury status, expected return date and games
played in each of the last 3 seasons. One component, shared by the Mock trade's
"Players in this deal" table and Compare's Players mode (both read
queries.player_profile(), indexed by player_id)."""

import pandas as pd

STATUS = {"ACTIVE": "Healthy", "DAY_TO_DAY": "Day-to-day", "OUT": "Out"}


def health_text(row: pd.Series) -> str:
    status = row["injury_status"] or "ACTIVE"
    text = STATUS.get(status, str(status).replace("_", " ").title())
    if pd.notna(row["expected_return_date"]):
        text += f", back about {row['expected_return_date']:%b %-d}"
    return text


def games_by_season_text(row: pd.Series) -> str:
    seasons = [row["gp_3_seasons_ago"], row["gp_2_seasons_ago"], row["gp_last_season"]]
    return " · ".join("–" if pd.isna(g) else f"{g:.0f}" for g in seasons)
