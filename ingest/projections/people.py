"""Birth dates and ESPN ids for BallDontLie's players.

BallDontLie has no birth dates (the model's aging needs them), and its player ids
aren't ESPN's (League Lab's rosters are). Two sources fill the gap:

* **Wikidata** (CC0, public domain, so a paid product can use it freely): every person
  with an NBA.com, Basketball-Reference or ESPN NBA id, with their birth date (P569)
  and, when recorded, their ESPN id (P3685). Names come from the English label, or
  Wikidata's language-neutral "mul" label, where many people's names now live.
* **ESPN's player list** (names and ids only, the same link League Lab's rosters use),
  for the ESPN id when Wikidata doesn't record one.

Players are matched by name in passes, strictest first, each only for players still
unmatched: the exact name (accents, punctuation and spaces ignored, so "T. J." is
"T.J."), then without suffixes (Jr., II), then with German umlauts spelled out (Pöltl
= Poeltl), then a first name that's a short form of the other (Nic / Nicolas) with
the same last name; a short alias list covers true nicknames (Bub, Bones, Ace). When
two candidates share a name, the one whose birth year fits the BallDontLie player's
draft year (drafted at 17-25) wins; if that doesn't settle it, the player is left
unmatched rather than guessed. And in every pass, a candidate whose birth date can't
be our player's is never taken, even alone (Gerald Henderson Sr. for his son). Only
players with NBA games should be passed in: BallDontLie's player list also holds other
leagues' players with the same names.

In season, a last pass uses the player's current team (match_by_team): among ESPN's
players on the same NBA team, one whose name is ours, contains ours or shares our last
name and first initial. That settles two players sharing a name (Jaylin Williams of
OKC, not the free agent) and a name ESPN writes longer ("David Jones Garcia").
"""

import json
import re
import unicodedata

import pandas as pd
import requests

SPARQL = "https://query.wikidata.org/sparql"
QUERY = """SELECT ?item ?espn ?born ?name WHERE {
  { ?item wdt:P3647 [] } UNION { ?item wdt:P2685 [] } UNION { ?item wdt:P3685 [] }
  ?item wdt:P569 ?born .
  OPTIONAL { ?item wdt:P3685 ?espn }
  OPTIONAL { ?item rdfs:label ?en FILTER(LANG(?en) = "en") }
  OPTIONAL { ?item rdfs:label ?mul FILTER(LANG(?mul) = "mul") }
  BIND(COALESCE(?en, ?mul) AS ?name)
}"""
ESPN_PLAYERS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/players"
USER_AGENT = "LeagueLabWhop/0.1 (fantasy basketball analytics)"
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
DRAFT_AGES = (17, 25)
COLUMNS = ["player_id", "espn_player_id", "birth_date"]


def normalize(name: str) -> str:
    """'Nikola Jokić' -> 'nikola jokic'; 'Jaren Jackson Jr.' -> 'jaren jackson'."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z ]", "", text.lower().replace("-", " ")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def fetch_wikidata(session: requests.Session | None = None) -> pd.DataFrame:
    """Every Wikidata person with an NBA id and a birth date: item, name, birth_date,
    espn_player_id (when recorded)."""
    session = session or requests.Session()
    response = session.get(
        SPARQL,
        params={"query": QUERY},
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        timeout=180,
    )
    response.raise_for_status()
    rows = [
        {
            "item": b["item"]["value"].rsplit("/", 1)[-1],
            "name": b.get("name", {}).get("value"),
            "birth_date": b["born"]["value"][:10],
            "espn": b.get("espn", {}).get("value"),
        }
        for b in response.json()["results"]["bindings"]
    ]
    frame = pd.DataFrame(rows)
    frame["espn_player_id"] = pd.to_numeric(frame.pop("espn"), errors="coerce").astype("Int64")
    frame["birth_date"] = pd.to_datetime(frame["birth_date"], errors="coerce").dt.date
    # one row per person: a person with two recorded birth dates or ESPN ids keeps the first
    return frame.drop_duplicates("item").reset_index(drop=True)


# ESPN's team codes that differ from BallDontLie's
ESPN_TEAMS = {"PHL": "PHI", "PHO": "PHX"}


def espn_team(pro_team_id) -> str | None:
    """BallDontLie's code for ESPN's proTeamId; None for a free agent (0) or unknown."""
    from espn_api.basketball.constant import PRO_TEAM_MAP

    code = PRO_TEAM_MAP.get(int(pro_team_id or 0))
    return None if code in (None, "FA") else ESPN_TEAMS.get(code, code)


def fetch_espn_players(season: int) -> pd.DataFrame:
    """ESPN's full player list for a season: espn_player_id, name, team (BallDontLie's
    code; None for a free agent)."""
    from ingest.espn_client import _get

    # without the filter header ESPN returns only 50 players
    headers = {"x-fantasy-filter": json.dumps({"filterActive": None})}
    data = _get(ESPN_PLAYERS.format(season=season), {"view": "players_wl"}, headers, None)
    return pd.DataFrame(
        [
            {
                "espn_player_id": int(p["id"]),
                "name": p.get("fullName"),
                "team": espn_team(p.get("proTeamId")),
            }
            for p in data
        ]  # fmt: skip
    ).drop_duplicates("espn_player_id")


FIRST_SEASON_AGES = (18, 40)  # age in his first NBA season, for undrafted players


def _fits(draft_year, birth_date) -> bool:
    if pd.isna(draft_year) or birth_date is None or pd.isna(birth_date):
        return False
    return DRAFT_AGES[0] <= int(draft_year) - birth_date.year <= DRAFT_AGES[1]


def _impossible(row) -> bool:
    """A candidate whose birth date can't be our player's (his father, say): drafted
    outside 17-25, or outside 18-40 in his first NBA season. Unknown = possible."""
    born = row.get("birth_date")
    if born is None or pd.isna(born):
        return False
    if pd.notna(row.get("draft_year")):
        return not _fits(row["draft_year"], born)
    first = row.get("first_season")
    if first is not None and pd.notna(first):
        return not FIRST_SEASON_AGES[0] <= int(first) - born.year <= FIRST_SEASON_AGES[1]
    return False


# Nicknames no rule can derive: BallDontLie's name -> the name others use
ALIASES = {
    "carlton carrington": "bub carrington",
    "nahshon hyland": "bones hyland",
    "airious bailey": "ace bailey",
    "hansen yang": "yang hansen",
}
TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _letters(name: str, suffix: bool) -> str:
    """Accents and punctuation stripped, and all spaces too ('T. J.' = 'T.J.')."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z ]", "", text.lower().replace("-", " ")).split()
    return "".join(w for w in words if suffix or w not in SUFFIXES)


def _ours(name: str, suffix: bool) -> str:
    base = _letters(name, suffix)
    alias = ALIASES.get(normalize(name))
    return _letters(alias, suffix) if alias else base


# The passes, strictest first; each only for players still unmatched. A pass is
# (key for our names, key for theirs).
PASSES = [
    (lambda n: _ours(n, True), lambda n: _letters(n, True)),  # exact, suffix kept
    (lambda n: _ours(n, False), lambda n: _letters(n, False)),  # suffix dropped
    (lambda n: _ours(n, False), lambda n: _letters(n.translate(TRANSLIT), False)),  # Pöltl
]


def _short_form(ours: pd.DataFrame, named: pd.DataFrame, key: str) -> pd.DataFrame:
    """Last pass: same last name, and one first name starts the other (Nic / Nicolas,
    Cam / Cameron, Mo / Mohamed); 2+ letters, unique on both sides."""

    def split(name):
        words = normalize(name).split()
        return (words[0], words[-1]) if len(words) >= 2 else (None, None)

    left = ours.assign(first=[split(n)[0] for n in ours["player_name"]],
                       last=[split(n)[1] for n in ours["player_name"]])  # fmt: skip
    right = named.assign(first=[split(n)[0] for n in named["name"]],
                         last=[split(n)[1] for n in named["name"]])  # fmt: skip
    pairs = left.dropna(subset=["last"]).merge(right.dropna(subset=["last"]), on="last")
    short = [
        len(min(a, b, key=len)) >= 2 and (a.startswith(b) or b.startswith(a))
        for a, b in zip(pairs["first_x"], pairs["first_y"], strict=True)
    ]
    return pairs.loc[short]


def _settle(pairs: pd.DataFrame, key: str) -> pd.DataFrame:
    """Keep pairs where each of our players has one candidate (shared names settled by
    draft year when candidates carry a birth date) and each candidate one player."""
    if pairs.empty:
        return pairs
    if "birth_date" in pairs:
        pairs = pairs.loc[[not _impossible(r) for _, r in pairs.iterrows()]]
        if pairs.empty:
            return pairs
    counts = pairs.groupby("player_id")[key].transform("size")
    many = pairs.loc[counts > 1]
    if "birth_date" in many and not many.empty:
        fit = [_fits(d, b) for d, b in zip(many["draft_year"], many["birth_date"], strict=True)]
        many = many.loc[fit]
        many = many.loc[many.groupby("player_id")[key].transform("size") == 1]
    else:
        many = many.iloc[0:0]
    matched = pd.concat([pairs.loc[counts == 1], many], ignore_index=True)
    return matched.loc[matched.groupby(key)["player_id"].transform("size") == 1]


def _by_name(ours: pd.DataFrame, theirs: pd.DataFrame, key: str) -> pd.DataFrame:
    """Each of our players paired with one candidate (`key` names the candidate's id),
    pass by pass. A candidate taken in an earlier pass isn't offered again."""
    named = theirs.dropna(subset=["name"])
    found = []
    left = ours
    for ours_key, their_key in PASSES:
        pairs = left.assign(k=left["player_name"].map(ours_key)).merge(
            named.assign(k=named["name"].map(their_key)), on="k"
        )
        found.append(_settle(pairs, key))
        done = pd.concat(found)
        left = ours.loc[~ours["player_id"].isin(done["player_id"])]
        named = named.loc[~named[key].isin(done[key])]
    found.append(_settle(_short_form(left, named, key), key))
    return pd.concat(found, ignore_index=True)


def match(players: pd.DataFrame, wikidata: pd.DataFrame, espn: pd.DataFrame | None = None):
    """players: BallDontLie's (player_id, player_name, draft_year, and optionally
    first_season: his first NBA season, end year), NBA players only. Returns one row
    per player matched to anything: player_id, espn_player_id, birth_date (either may
    be missing)."""
    keep = ["player_id", "player_name", "draft_year"] + (
        ["first_season"] if "first_season" in players else []
    )
    ours = players[keep]
    wiki = _by_name(ours, wikidata, "item")
    out = ours[["player_id"]].merge(
        wiki[["player_id", "espn_player_id", "birth_date"]], on="player_id", how="left"
    )
    if espn is not None:
        need = ours.loc[ours["player_id"].isin(out.loc[out["espn_player_id"].isna(), "player_id"])]
        taken = out["espn_player_id"].dropna()
        found = _by_name(need, espn.loc[~espn["espn_player_id"].isin(taken)], "espn_player_id")
        fill = out["player_id"].map(found.set_index("player_id")["espn_player_id"])
        out["espn_player_id"] = out["espn_player_id"].fillna(fill.astype("Int64"))
    # an ESPN id can't belong to two players: clear it from both if it would
    shared = out["espn_player_id"].notna() & out.duplicated("espn_player_id", keep=False)
    out.loc[shared, "espn_player_id"] = pd.NA
    out = out.loc[out["espn_player_id"].notna() | out["birth_date"].notna()]
    return out[COLUMNS].reset_index(drop=True)


def _same_person(ours: str, theirs: str) -> bool:
    """Names that can be one person once the team agrees: equal; one contains the
    other's every word (David Jones / David Jones Garcia); or the same last name and
    first initial (Nic / Nicolas)."""
    a, b = normalize(ours).split(), normalize(theirs).split()
    if not a or not b:
        return False
    if a == b or set(a) <= set(b) or set(b) <= set(a):
        return True
    return a[-1] == b[-1] and a[0][0] == b[0][0]


def match_by_team(players: pd.DataFrame, espn: pd.DataFrame) -> pd.DataFrame:
    """players: (player_id, player_name, team) -- his current team; espn: (espn_player_id,
    name, team). Each player linked to the one ESPN player on his team whose name fits
    (_same_person); none when zero or several fit, or when that ESPN player would fit
    two of ours. Returns player_id, espn_player_id."""
    pairs = players.dropna(subset=["team"]).merge(
        espn.dropna(subset=["team"]), on="team", suffixes=("", "_espn")
    )
    pairs = pairs.loc[[_same_person(a, b) for a, b in zip(pairs["player_name"], pairs["name"],
                                                           strict=True)]]  # fmt: skip
    pairs = pairs.loc[pairs.groupby("player_id")["espn_player_id"].transform("size") == 1]
    pairs = pairs.loc[pairs.groupby("espn_player_id")["player_id"].transform("size") == 1]
    return pairs[["player_id", "espn_player_id"]].reset_index(drop=True)
