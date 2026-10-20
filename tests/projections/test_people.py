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
    return pd.DataFrame(rows, columns=["espn_player_id", "birth_date", "name"])


def test_a_unique_name_matches():
    ours = pd.DataFrame([{"player_id": 1, "player_name": "Nikola Jokic", "draft_year": 2014}])
    out = match(ours, wiki([(3112335, dt.date(1995, 2, 19), "Nikola Jokić")]))
    assert out.to_dict("records") == [
        {"player_id": 1, "espn_player_id": 3112335, "birth_date": dt.date(1995, 2, 19)}
    ]


def test_a_shared_name_is_settled_by_draft_year():
    ours = pd.DataFrame([{"player_id": 1, "player_name": "Marcus Williams", "draft_year": 2007}])
    out = match(
        ours,
        wiki(
            [
                (100, dt.date(1985, 12, 3), "Marcus Williams"),  # drafted at 21: him
                (200, dt.date(1960, 1, 1), "Marcus Williams"),  # would have been 47
            ]
        ),
    )
    assert out["espn_player_id"].tolist() == [100]


def test_an_unsettled_shared_name_is_left_unmatched():
    ours = pd.DataFrame([{"player_id": 1, "player_name": "Chris Johnson", "draft_year": None}])
    out = match(
        ours,
        wiki(
            [
                (100, dt.date(1985, 1, 1), "Chris Johnson"),
                (200, dt.date(1990, 1, 1), "Chris Johnson"),
            ]
        ),
    )
    assert out.empty


def test_one_espn_id_never_goes_to_two_players():
    ours = pd.DataFrame(
        [
            {"player_id": 1, "player_name": "Same Name", "draft_year": 2010},
            {"player_id": 2, "player_name": "Same Name", "draft_year": 2010},
        ]
    )
    assert match(ours, wiki([(100, dt.date(1989, 1, 1), "Same Name")])).empty
