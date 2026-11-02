import datetime as dt

import pandas as pd
from ingest.projections.people import match, normalize


def test_names_lose_accents_punctuation_and_suffixes():
    assert normalize("Nikola Jokić") == "nikola jokic"
    assert normalize("Jaren Jackson Jr.") == "jaren jackson"
    assert normalize("Shai Gilgeous-Alexander") == "shai gilgeous alexander"
    assert normalize("De'Aaron Fox") == "deaaron fox"
    assert normalize("Gary Trent Jr") == normalize("Gary Trent")


def wiki(rows):
    """(espn id or None, birth date, name) -> Wikidata rows, one item each."""
    frame = pd.DataFrame(
        [
            {"item": f"Q{i}", "espn_player_id": e, "birth_date": b, "name": n}
            for i, (e, b, n) in enumerate(rows)
        ],
        columns=["item", "espn_player_id", "birth_date", "name"],
    )
    frame["espn_player_id"] = frame["espn_player_id"].astype("Int64")
    return frame


def ours(*rows):
    return pd.DataFrame(rows, columns=["player_id", "player_name", "draft_year"])


def records(out):
    return [
        {
            "player_id": r.player_id,
            "espn_player_id": None if pd.isna(r.espn_player_id) else int(r.espn_player_id),
            "birth_date": None if pd.isna(r.birth_date) else r.birth_date,
        }
        for r in out.itertuples()
    ]


JOKIC = (3112335, dt.date(1995, 2, 19), "Nikola Jokić")


def test_a_unique_name_gets_birth_date_and_espn_id():
    out = match(ours((1, "Nikola Jokic", 2014)), wiki([JOKIC]))
    assert records(out) == [
        {"player_id": 1, "espn_player_id": 3112335, "birth_date": dt.date(1995, 2, 19)}
    ]


def test_a_shared_name_is_settled_by_draft_year():
    candidates = wiki([
        (100, dt.date(1985, 12, 3), "Marcus Williams"),  # drafted at 21: him
        (200, dt.date(1960, 1, 1), "Marcus Williams"),  # would have been 47
    ])  # fmt: skip
    out = match(ours((1, "Marcus Williams", 2007)), candidates)
    assert records(out)[0]["espn_player_id"] == 100


def test_an_unsettled_shared_name_is_left_unmatched():
    candidates = wiki([
        (100, dt.date(1985, 1, 1), "Chris Johnson"),
        (200, dt.date(1990, 1, 1), "Chris Johnson"),
    ])  # fmt: skip
    assert match(ours((1, "Chris Johnson", None)), candidates).empty


def test_espns_list_fills_a_missing_espn_id():
    espn = pd.DataFrame([{"espn_player_id": 3202, "name": "Kevin Durant"}])
    candidates = wiki([(None, dt.date(1988, 9, 29), "Kevin Durant")])
    out = match(ours((1, "Kevin Durant", 2007)), candidates, espn)
    assert records(out) == [
        {"player_id": 1, "espn_player_id": 3202, "birth_date": dt.date(1988, 9, 29)}
    ]


def test_espns_list_alone_gives_an_id_without_a_birth_date():
    espn = pd.DataFrame([{"espn_player_id": 77, "name": "New Guy"}])
    out = match(ours((1, "New Guy", 2026)), wiki([]), espn)
    assert records(out) == [{"player_id": 1, "espn_player_id": 77, "birth_date": None}]


def test_one_espn_id_never_goes_to_two_players():
    candidates = wiki([(100, dt.date(1989, 1, 1), "Same Name")])
    assert match(ours((1, "Same Name", 2010), (2, "Same Name", 2010)), candidates).empty


def test_columns_already_on_the_players_table_are_ignored():
    players = ours((1, "Nikola Jokic", 2014)).assign(birth_date=None, espn_player_id=None)
    assert records(match(players, wiki([JOKIC])))[0]["espn_player_id"] == 3112335


def test_spaced_initials_umlauts_and_suffixes_still_match():
    candidates = wiki([
        (1, dt.date(1992, 3, 25), "T. J. McConnell"),
        (2, dt.date(1995, 10, 15), "Jakob Pöltl"),
        (3, dt.date(1992, 7, 23), "Gary Payton II"),
        (4, dt.date(1968, 7, 23), "Gary Payton"),
    ])  # fmt: skip
    players = ours((10, "T.J. McConnell", 2015), (11, "Jakob Poeltl", 2016),
                   (12, "Gary Payton II", None), (13, "Gary Payton", 1990))  # fmt: skip
    got = {r["player_id"]: r["espn_player_id"] for r in records(match(players, candidates))}
    assert got == {10: 1, 11: 2, 12: 3, 13: 4}


def test_short_first_names_and_nicknames_match():
    candidates = wiki([
        (1, dt.date(1999, 4, 17), "Nic Claxton"),
        (2, dt.date(2005, 7, 21), "Bub Carrington"),
    ])  # fmt: skip
    players = ours((10, "Nicolas Claxton", 2019), (11, "Carlton Carrington", 2024))
    got = {r["player_id"]: r["espn_player_id"] for r in records(match(players, candidates))}
    assert got == {10: 1, 11: 2}


def test_a_short_form_is_not_guessed_when_two_could_fit():
    candidates = wiki([
        (1, dt.date(1990, 1, 1), "Chris Smith"),
        (2, dt.date(1991, 1, 1), "Christian Smith"),
    ])  # fmt: skip
    assert match(ours((10, "Chr Smith", None)), candidates).empty


def test_a_father_is_never_taken_for_his_son():
    candidates = wiki([
        (1, dt.date(1956, 1, 16), "Gerald Henderson"),
        (2, dt.date(1987, 12, 9), "Gerald Henderson Jr."),
    ])  # fmt: skip
    got = records(match(ours((10, "Gerald Henderson", 2009)), candidates))
    assert got == [{"player_id": 10, "espn_player_id": 2, "birth_date": dt.date(1987, 12, 9)}]


def test_undrafted_players_are_checked_against_their_first_season():
    candidates = wiki([(1, dt.date(1961, 3, 6), "Ray McCallum")])
    players = ours((10, "Ray McCallum", None)).assign(first_season=2014)
    assert match(players, candidates).empty


def team_ours(*rows):
    return pd.DataFrame(rows, columns=["player_id", "player_name", "team"])


def team_espn(*rows):
    return pd.DataFrame(rows, columns=["espn_player_id", "name", "team"])


def test_a_shared_name_is_settled_by_team():
    from ingest.projections.people import match_by_team

    espn = team_espn((4431776, "Jaylin Williams", None), (4432823, "Jaylin Williams", "OKC"))
    out = match_by_team(team_ours((1, "Jaylin Williams", "OKC")), espn)
    assert out.to_dict("records") == [{"player_id": 1, "espn_player_id": 4432823}]


def test_a_longer_espn_name_on_the_same_team_matches():
    from ingest.projections.people import match_by_team

    espn = team_espn((4713010, "David Jones Garcia", "SAS"), (9, "Tre Jones", "SAS"))
    out = match_by_team(team_ours((1, "David Jones", "SAS")), espn)
    assert out.to_dict("records") == [{"player_id": 1, "espn_player_id": 4713010}]


def test_team_matching_never_guesses():
    from ingest.projections.people import match_by_team

    two_fit = team_espn((1, "Chris Smith", "LAL"), (2, "Christian Smith", "LAL"))
    assert match_by_team(team_ours((10, "C. Smith", "LAL")), two_fit).empty
    other_team = team_espn((1, "David Jones Garcia", "UTA"))
    assert match_by_team(team_ours((10, "David Jones", "SAS")), other_team).empty
    no_team = team_espn((1, "David Jones Garcia", "SAS"))
    assert match_by_team(team_ours((10, "David Jones", None)), no_team).empty
    shared = team_espn((1, "Jalen Smith", "CHI"))
    assert match_by_team(team_ours((10, "Jalen Smith", "CHI"), (11, "Jalen Smith", "CHI")),
                         shared).empty  # fmt: skip


def test_espn_team_codes_become_balldontlies():
    from ingest.projections.people import espn_team

    assert (espn_team(25), espn_team(20), espn_team(21), espn_team(0)) == (
        "OKC",
        "PHI",
        "PHX",
        None,
    )
