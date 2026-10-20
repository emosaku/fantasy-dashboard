"""Birth dates and ESPN ids for BallDontLie's players, from Wikidata.

BallDontLie has no birth dates (the model's aging needs them), and its player ids
aren't ESPN's (League Lab's rosters are). Wikidata has both for nearly every NBA
player -- property P3685 (ESPN.com NBA player ID) and P569 (date of birth) -- and its
data is CC0, public domain, so a paid product can use it freely.

Players are matched by name: accents, punctuation and suffixes (Jr., III) stripped.
When two Wikidata players share a name, the one whose birth year fits the BallDontLie
player's draft year (drafted at 17-25) wins; if that still doesn't settle it, the
player is left unmatched rather than guessed.
"""

import re
import unicodedata

import pandas as pd
import requests

SPARQL = "https://query.wikidata.org/sparql"
QUERY = """SELECT ?item ?espn ?born ?name WHERE {
  ?item wdt:P3685 ?espn .
  OPTIONAL { ?item wdt:P569 ?born }
  OPTIONAL { ?item rdfs:label ?name FILTER(LANG(?name) = "en") }
}"""
USER_AGENT = "LeagueLabWhop/0.1 (fantasy basketball analytics)"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
DRAFT_AGES = (17, 25)


def normalize(name: str) -> str:
    """'Nikola Jokić' -> 'nikola jokic'; 'Jaren Jackson Jr.' -> 'jaren jackson'."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z ]", "", text.lower().replace("-", " ")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def fetch_wikidata(session: requests.Session | None = None) -> pd.DataFrame:
    """Every Wikidata person with an ESPN NBA id: espn_player_id, birth_date, name."""
    session = session or requests.Session()
    response = session.get(
        SPARQL,
        params={"query": QUERY},
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        timeout=120,
    )
    response.raise_for_status()
    rows = [
        {
            "espn_player_id": int(b["espn"]["value"]),
            "birth_date": b["born"]["value"][:10] if "born" in b else None,
            "name": b.get("name", {}).get("value"),
        }
        for b in response.json()["results"]["bindings"]
        if b["espn"]["value"].isdigit()
    ]
    frame = pd.DataFrame(rows).drop_duplicates("espn_player_id")
    frame["birth_date"] = pd.to_datetime(frame["birth_date"], errors="coerce").dt.date
    return frame


def match(players: pd.DataFrame, wikidata: pd.DataFrame) -> pd.DataFrame:
    """players: BallDontLie's (player_id, player_name, draft_year). Returns one row per
    matched player: player_id, espn_player_id, birth_date."""
    wiki = wikidata.dropna(subset=["name"]).assign(key=lambda f: f["name"].map(normalize))
    ours = players.assign(key=players["player_name"].map(normalize))
    pairs = ours.merge(wiki, on="key", how="inner")

    def fits(row) -> bool:
        if pd.isna(row["draft_year"]) or pd.isna(row["birth_date"]):
            return False
        age = int(row["draft_year"]) - row["birth_date"].year
        return DRAFT_AGES[0] <= age <= DRAFT_AGES[1]

    counts = pairs.groupby("player_id")["espn_player_id"].transform("size")
    single = pairs.loc[counts == 1]
    many = pairs.loc[counts > 1]
    many = many.loc[many.apply(fits, axis=1)] if not many.empty else many
    many = many.loc[many.groupby("player_id")["espn_player_id"].transform("size") == 1]
    matched = pd.concat([single, many], ignore_index=True)
    # one ESPN id can't belong to two BallDontLie players: drop both if it would
    taken = matched.groupby("espn_player_id")["player_id"].transform("size")
    matched = matched.loc[taken == 1]
    return matched[["player_id", "espn_player_id", "birth_date"]].reset_index(drop=True)
