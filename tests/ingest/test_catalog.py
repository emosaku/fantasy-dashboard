"""Reading a league's categories from its ESPN scoring settings (ingest/catalog.py)."""

import pytest
from ingest.catalog import (
    CATEGORIES,
    PLAYER_STATS,
    POINTS,
    UnsupportedLeague,
    league_categories,
    league_format,
    league_scoring,
    scoring_type,
)

# ESPN stat ids: 19 FG%, 20 FT%, 17 3PM, 6 REB, 3 AST, 2 STL, 1 BLK, 11 TO, 0 PTS.
NINE_CAT = [19, 20, 17, 6, 3, 2, 1, 11, 0]


def settings(ids, reverse=(11,), scoring_type="H2H_MOST_CATEGORIES"):
    return {
        "scoringType": scoring_type,
        "scoringItems": [{"statId": i, "isReverseItem": i in reverse} for i in ids],
    }


def test_standard_nine_cat_league():
    cats = league_categories(settings(NINE_CAT))
    assert [c["category"] for c in cats] == [
        "FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "TO", "PTS",
    ]  # fmt: skip
    fg = cats[0]
    assert (fg["kind"], fg["num_stat"], fg["den_stat"]) == ("ratio", "FGM", "FGA")
    to = cats[7]
    assert to["lower_is_better"] and to["kind"] == "count"
    assert [c["display_order"] for c in cats] == list(range(9))


def test_each_category_is_supported_and_a_to_is_a_ratio():
    # 35 is ESPN's A/TO
    cats = league_categories(settings([0, 35], scoring_type="H2H_EACH_CATEGORY"))
    a_to = cats[1]
    assert (a_to["category"], a_to["num_stat"], a_to["den_stat"]) == ("A/TO", "AST", "TO")


@pytest.mark.parametrize(
    ("espn", "ours"),
    [
        ("H2H_CATEGORY", "H2H_EACH_CATEGORY"),  # ESPN's name for Each Category
        ("H2H_EACH_CATEGORY", "H2H_EACH_CATEGORY"),
        ("H2H_MOST_CATEGORIES", "H2H_MOST_CATEGORIES"),
        ("H2H_POINTS", "H2H_POINTS"),  # unknown to League Lab: passed through
    ],
)
def test_scoring_type_uses_league_labs_names(espn, ours):
    assert scoring_type({"scoringType": espn}) == ours


def test_espns_each_category_name_is_supported():
    cats = league_categories(settings(NINE_CAT, scoring_type="H2H_CATEGORY"))
    assert len(cats) == 9


@pytest.mark.parametrize("scoring_type", ["H2H_POINTS", "ROTISSERIE", None])
def test_other_formats_are_refused(scoring_type):
    with pytest.raises(UnsupportedLeague):
        league_categories(settings(NINE_CAT, scoring_type=scoring_type))


def test_unsupported_categories_are_named():
    with pytest.raises(UnsupportedLeague, match="DD"):
        league_categories(settings([0, 37]))  # 37: double-doubles


def test_every_category_input_is_ingested():
    assert {"FGM", "FGA", "3PA", "TO", "GP"} <= set(PLAYER_STATS)


# --- Points leagues -----------------------------------------------------------------


def points_settings(items, scoring_type="H2H_POINTS"):
    return {"scoringType": scoring_type, "scoringItems": items}


def test_format_comes_from_espns_scoring_type():
    assert league_format(settings(NINE_CAT)) == CATEGORIES
    assert league_format(settings(NINE_CAT, scoring_type="H2H_CATEGORY")) == CATEGORIES
    assert league_format(points_settings([])) == POINTS
    with pytest.raises(UnsupportedLeague, match="head-to-head"):
        league_format(settings(NINE_CAT, scoring_type="ROTISSERIE"))


def test_point_values_keep_espns_order_and_skip_zeros():
    items = [{"statId": 0, "points": 1}, {"statId": 14, "points": -1},
             {"statId": 20, "points": 0}, {"statId": 38, "points": 10}]  # fmt: skip
    scoring = league_scoring(points_settings(items))
    assert [(s["stat"], s["points"], s["stat_id"]) for s in scoring] == [
        ("PTS", 1.0, 0), ("FGA", -1.0, 14), ("TD", 10.0, 38),
    ]  # fmt: skip


def test_an_override_equal_to_the_base_value_is_fine():
    items = [{"statId": 0, "points": 1, "pointsOverrides": {"11": 1.0}}]
    assert league_scoring(points_settings(items))[0]["points"] == 1.0


def test_categories_and_points_readers_refuse_the_other_format():
    with pytest.raises(UnsupportedLeague):
        league_categories(points_settings([{"statId": 0, "points": 1}]))
    with pytest.raises(UnsupportedLeague):
        league_scoring(settings(NINE_CAT))
