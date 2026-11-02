"""Which ESPN league formats and scoring League Lab supports.

A league is either a head-to-head categories league or a head-to-head points league
(its *format*, read from ESPN's scoringType and locked for the season at sign-up).

Categories leagues:

A league's categories come from its ESPN settings (scoringSettings.scoringItems):
an ESPN stat id, plus isReverseItem for categories where lower wins (turnovers).
Each supported category is either:
  * count -- one per-game stat (PTS, REB, TO ...), or
  * ratio -- one total over another (FG% = FGM / FGA, A/TO = AST / TO), always
             recomputed from the totals, never averaged.
Everything is built from per-game averages of our own box scores. Beyond the 15 core
stats, the extra stats (EXTRA_COUNT: double-, triple- and quadruple-doubles, personal
fouls, foul-outs, missed shots) are counted game by game, so they work as categories
too (docs/whopDocs/bonus-stats.md). A category we can't count at all (ejections,
technical fouls ...) is refused at registration with a clear message.

Points leagues: every stat is worth a set number of points (scoringItems[].points)
and the higher weekly total wins. League Lab computes each player's fantasy points
from our stats and the league's point values, and checks them against ESPN's. A
scored stat we can't count (uncounted_stats) doesn't refuse the league: it's shown at
sign-up and recorded on the league. A league whose point values change by lineup slot
(pointsOverrides) is refused.
"""

from dataclasses import dataclass

from espn_api.basketball.constant import STATS_MAP


@dataclass(frozen=True)
class CategoryDef:
    category: str  # ESPN's abbreviation, e.g. "3PT%"
    kind: str  # "count" | "ratio"
    num_stat: str
    den_stat: str | None = None


COUNT = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FGM", "FGA", "FTM", "FTA", "3PA",
         "OREB", "DREB", "MIN"]  # fmt: skip
# Stats beyond the 15 that our box scores can count (ingest/projections/games.py)
EXTRA_COUNT = ["DD", "TD", "QD", "PF", "DQ", "FGMI", "FTMI", "3PMI"]
# Stats ESPN offers that our stats source doesn't report, for people
UNAVAILABLE = {"EJ": "ejections", "FF": "flagrant fouls", "TF": "technical fouls",
               "GS": "games started", "TW": "team wins"}  # fmt: skip
RATIO = {
    "FG%": ("FGM", "FGA"),
    "FT%": ("FTM", "FTA"),
    "3PT%": ("3PM", "3PA"),
    "A/TO": ("AST", "TO"),
}

CATALOG = {c: CategoryDef(c, "count", c) for c in [*COUNT, *EXTRA_COUNT]} | {
    c: CategoryDef(c, "ratio", num, den) for c, (num, den) in RATIO.items()
}

# Per-game stats ingest keeps for every player: every catalog input plus games played.
PLAYER_STATS = sorted(
    {d.num_stat for d in CATALOG.values()}
    | {d.den_stat for d in CATALOG.values() if d.den_stat}
    | {"GP"}
)

SUPPORTED_SCORING_TYPES = {"H2H_MOST_CATEGORIES", "H2H_EACH_CATEGORY"}
POINTS_SCORING_TYPE = "H2H_POINTS"
CATEGORIES, POINTS = "categories", "points"

# ESPN's scoringType -> League Lab's name. ESPN calls Each Category "H2H_CATEGORY" (the
# key espn-api's box scores use); League Lab stores the clearer H2H_EACH_CATEGORY and
# accepts it as input too.
ESPN_SCORING_TYPES = {
    "H2H_MOST_CATEGORIES": "H2H_MOST_CATEGORIES",
    "H2H_CATEGORY": "H2H_EACH_CATEGORY",
    "H2H_EACH_CATEGORY": "H2H_EACH_CATEGORY",
    "H2H_POINTS": "H2H_POINTS",
}


class UnsupportedLeague(Exception):
    """The league's format or categories can't be handled yet; message is for people."""


def scoring_type(scoring_settings: dict) -> str | None:
    """League Lab's name for the league's scoring type, from its raw ESPN
    scoringSettings. A format League Lab doesn't know comes back as ESPN sent it."""
    raw = scoring_settings.get("scoringType")
    return ESPN_SCORING_TYPES.get(raw, raw)


def league_format(scoring_settings: dict) -> str:
    """ "categories" or "points"; raises UnsupportedLeague for any other format."""
    kind = scoring_type(scoring_settings)
    if kind in SUPPORTED_SCORING_TYPES:
        return CATEGORIES
    if kind == POINTS_SCORING_TYPE:
        return POINTS
    raise UnsupportedLeague(
        f"This league scores by {kind or 'an unknown format'}. League Lab supports "
        "head-to-head leagues: points, or categories (Most Categories or Each Category)."
    )


def stat_name(stat_id) -> str:
    return STATS_MAP.get(str(stat_id), f"stat {stat_id}") or f"stat {stat_id}"


def league_scoring(scoring_settings: dict) -> list[dict]:
    """A points league's point values, in ESPN's order: [{stat, stat_id, points,
    display_order}], stats worth 0 left out. Raises UnsupportedLeague if the league
    isn't head-to-head points or a value changes by lineup slot."""
    if league_format(scoring_settings) != POINTS:
        raise UnsupportedLeague("This league doesn't score by points.")
    out, by_slot = [], []
    for order, item in enumerate(scoring_settings.get("scoringItems", [])):
        points = float(item.get("points") or 0)
        overrides = {float(v) for v in (item.get("pointsOverrides") or {}).values()}
        if overrides - {points}:
            by_slot.append(stat_name(item["statId"]))
        if points:
            out.append(
                {
                    "stat": stat_name(item["statId"]),
                    "stat_id": int(item["statId"]),
                    "points": points,
                    "display_order": order,
                }
            )
    if by_slot:
        raise UnsupportedLeague(
            "This league's point values change by lineup slot ("
            + ", ".join(by_slot)
            + "). League Lab doesn't support that yet."
        )
    if not out:
        raise UnsupportedLeague("This league gives no points for any stat.")
    return out


COUNTED = set(COUNT) | set(EXTRA_COUNT) | {"GP"}


def uncounted_stats(scoring: list[dict]) -> list[str]:
    """The stats a points league scores that League Lab can't count: they add 0 to
    every player's fantasy points, so the league is told at sign-up."""
    return [s["stat"] for s in scoring if s["stat"] not in COUNTED]


def describe_stat(stat: str) -> str:
    return UNAVAILABLE.get(stat, stat)


def league_categories(scoring_settings: dict) -> list[dict]:
    """The league's categories from its raw ESPN scoringSettings, in ESPN's order:
    [{category, kind, num_stat, den_stat, lower_is_better, display_order}].
    Raises UnsupportedLeague for a format or category League Lab can't compute."""
    if league_format(scoring_settings) != CATEGORIES:
        raise UnsupportedLeague("This league doesn't score by categories.")
    out, unsupported = [], []
    for order, item in enumerate(scoring_settings.get("scoringItems", [])):
        abbreviation = STATS_MAP.get(str(item["statId"]), f"stat {item['statId']}")
        definition = CATALOG.get(abbreviation)
        if definition is None:
            unsupported.append(abbreviation)
            continue
        out.append(
            {
                "category": definition.category,
                "kind": definition.kind,
                "num_stat": definition.num_stat,
                "den_stat": definition.den_stat,
                "lower_is_better": bool(item.get("isReverseItem", False)),
                "display_order": order,
            }
        )
    if unsupported:
        raise UnsupportedLeague(
            "League Lab can't compute these categories yet: " + ", ".join(unsupported) + "."
        )
    if not out:
        raise UnsupportedLeague("This league has no scoring categories.")
    return out
