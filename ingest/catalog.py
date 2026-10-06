"""Which ESPN scoring categories League Lab supports, and how each is computed.

A league's categories come from its ESPN settings (scoringSettings.scoringItems):
an ESPN stat id, plus isReverseItem for categories where lower wins (turnovers).
Each supported category is either:
  * count -- one per-game stat (PTS, REB, TO ...), or
  * ratio -- one total over another (FG% = FGM / FGA, A/TO = AST / TO), always
             recomputed from the totals, never averaged.
Everything is built from the per-game averages ESPN gives for each player, so a
category ESPN doesn't average (double-doubles, triple-doubles ...) can't be supported
yet: a league scoring one is refused at registration with a clear message.
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
RATIO = {
    "FG%": ("FGM", "FGA"),
    "FT%": ("FTM", "FTA"),
    "3PT%": ("3PM", "3PA"),
    "A/TO": ("AST", "TO"),
}

CATALOG = {c: CategoryDef(c, "count", c) for c in COUNT} | {
    c: CategoryDef(c, "ratio", num, den) for c, (num, den) in RATIO.items()
}

# Per-game stats ingest keeps for every player: every catalog input plus games played.
PLAYER_STATS = sorted(
    {d.num_stat for d in CATALOG.values()}
    | {d.den_stat for d in CATALOG.values() if d.den_stat}
    | {"GP"}
)

SUPPORTED_SCORING_TYPES = {"H2H_MOST_CATEGORIES", "H2H_EACH_CATEGORY"}


class UnsupportedLeague(Exception):
    """The league's format or categories can't be handled yet; message is for people."""


def league_categories(scoring_settings: dict) -> list[dict]:
    """The league's categories from its raw ESPN scoringSettings, in ESPN's order:
    [{category, kind, num_stat, den_stat, lower_is_better, display_order}].
    Raises UnsupportedLeague for a format or category League Lab can't compute."""
    scoring_type = scoring_settings.get("scoringType")
    if scoring_type not in SUPPORTED_SCORING_TYPES:
        raise UnsupportedLeague(
            f"This league scores by {scoring_type or 'an unknown format'}. League Lab "
            "supports head-to-head categories leagues (Most Categories or Each "
            "Category) for now."
        )
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
