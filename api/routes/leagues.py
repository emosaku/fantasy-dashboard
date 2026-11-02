"""One league's pages: Overview, Matchups, Players, Activity, plus its history and an
on-demand refresh. Each answers in the league's format (categories or points); the
`format` field says which shape the rows have."""

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query

import onboarding
import tenancy
from api import engine, services
from api.context import LeagueContext, league_context, store
from api.services import LeagueData
from points import model

router = APIRouter(prefix="/leagues/{league_id}")
rows = engine.records


def data(ctx: LeagueContext = Depends(league_context), store=Depends(store)) -> LeagueData:
    return LeagueData(store, ctx)


def body(d: LeagueData, **fields) -> dict:
    return {"league_id": d.ctx.league_id, "format": d.ctx.format,
            "data_as_of": d.ctx.version, **fields}  # fmt: skip


@router.get("")
def league(d: LeagueData = Depends(data)):
    """The league's rules and teams: what the header, switcher and pickers need."""
    ctx = d.ctx
    ready = tenancy.refresh_available_at(ctx.doc)
    return body(
        d,
        name=ctx.name, season=ctx.season, scoring_type=ctx.scoring_type,
        teams=[{"team_id": t, "team_name": n} for t, n in sorted(ctx.teams.items())],
        my_team=ctx.my_team, role=ctx.role,
        current_week=ctx.current_week, last_week=ctx.last_week,
        categories=[{"key": c.key, "kind": c.kind, "lower_is_better": c.lower_is_better}
                    for c in ctx.cats],
        scoring=[{"stat": s["stat"], "points": s["points"]} for s in ctx.scoring],
        uncounted=onboarding.uncounted_labels(ctx.scoring) if ctx.is_points else [],
        lineup_slots=ctx.lineup_slots, windows=d.windows(),
        refresh_available_at=ready.isoformat() if ready else None,
    )  # fmt: skip


@router.get("/standings")
def standings(d: LeagueData = Depends(data)):
    teams = d.table("teams").sort_values(["standing", "team_id"])
    cols = ["team_id", "team_name", "owner", "wins", "losses", "ties", "standing",
            "points_for", "points_against"]  # fmt: skip
    return body(d, teams=rows(teams[[c for c in cols if c in teams]]))


@router.get("/power-rankings")
def power_rankings(window: str | None = None, d: LeagueData = Depends(data)):
    """All-play power rankings and each team's projected finish."""
    ctx = d.ctx
    if ctx.is_points:
        window = d.window(window)
        results = model.played_results(d.table("matchup_scores"), ctx.current_week)
        table = model.season_table(results)
        if not table.empty:
            table["power_rank"] = table["ap_win_pct"].rank(ascending=False,
                                                           method="min").astype(int)  # fmt: skip
        finish = engine.pts_projected_finish(d.setup(window), d.table("matchup_scores"),
                                             d.table("pro_schedule"), ctx.current_week,
                                             ctx.last_week, services.today())  # fmt: skip
        return body(d, window=window, rankings=rows(table, "team_id"),
                    projected_finish=rows(finish, "team_id"))  # fmt: skip
    ranks = d.table("m_power_rankings")
    latest = ranks.loc[ranks["matchup_period"] == ranks["matchup_period"].max()] if len(ranks) \
        else ranks  # fmt: skip
    finish = engine.cat_projected_finish(
        d.table("m_player_pool"), d.table("m_all_play"), ctx.cats, ctx.current_week,
        ctx.last_week, ctx.data_as_of.date(), list(ctx.teams), ctx.each_category,
    )  # fmt: skip
    return body(d, rankings=rows(latest.sort_values("power_rank")),
                projected_finish=rows(finish))  # fmt: skip


@router.get("/luck")
def luck(d: LeagueData = Depends(data)):
    """Actual vs expected (all-play) results, week by week."""
    if d.ctx.is_points:
        results = model.played_results(d.table("matchup_scores"), d.ctx.current_week)
        return body(d, weeks=rows(model.luck_by_week(results)),
                    season=rows(model.season_table(results), "team_id"))  # fmt: skip
    return body(d, weeks=rows(d.table("m_luck").sort_values(["matchup_period", "team_id"])))


def _week(d: LeagueData, week: int | None) -> int:
    week = d.ctx.current_week if week is None else week
    if not 1 <= week <= max(d.ctx.last_week, d.ctx.current_week):
        raise HTTPException(422, "No such week.")
    return week


@router.get("/matchups")
def matchups(week: int | None = None, d: LeagueData = Depends(data)):
    week = _week(d, week)
    if d.ctx.is_points:
        scores = d.table("matchup_scores")
        return body(d, week=week, matchups=rows(scores.loc[scores["matchup_period"] == week]
                                                .sort_values("team_id")))  # fmt: skip
    cats = d.table("m_team_week_cats")
    luck = d.table("m_luck")
    return body(d, week=week,
                categories=rows(cats.loc[cats["matchup_period"] == week]),
                results=rows(luck.loc[luck["matchup_period"] == week]))  # fmt: skip


@router.get("/matchups/compare")
def compare(a: int, b: int, week: int | None = None, d: LeagueData = Depends(data)):
    """Two teams side by side: every week (or one) of category values or points."""
    for team in (a, b):
        if team not in d.ctx.teams:
            raise HTTPException(404, "No such team in this league.")
    name = "matchup_scores" if d.ctx.is_points else "m_team_week_cats"
    table = d.table(name)
    picked = table.loc[table["team_id"].isin([a, b])]
    if week is not None:
        picked = picked.loc[picked["matchup_period"] == _week(d, week)]
    return body(d, a=a, b=b, rows=rows(picked.sort_values(["matchup_period", "team_id"])))


@router.get("/roster-strength")
def roster_strength(window: str | None = None, d: LeagueData = Depends(data)):
    """Categories: each team's strength and rank per category, with Lock / Swing / Punt
    tiers (analysis.weights). Points: projected weekly points and their sources."""
    window = d.window(window)
    if d.ctx.is_points:
        return body(d, window=window, **pts_strength(d, window))
    players, totals = d.cat_league(window)
    strength = d.table("m_roster_strength")
    ranks = d.table("m_category_ranks")
    tiers = []
    for team in totals.index:
        w = engine.compute_weights(totals, team).reset_index(names="category")
        tiers += [{"team_id": int(team), **r} for r in rows(w)]
    return body(d, window=window,
                strength=rows(strength.loc[strength["stat_window"] == window]),
                ranks=rows(ranks.loc[(ranks["stat_window"] == window)
                                     | ranks["stat_window"].isna()]),
                tiers=tiers)  # fmt: skip


def pts_strength(d: LeagueData, window: str) -> dict:
    """The points Roster Strength page's table and points-by-source, per team."""
    setup = d.setup(window)
    players = setup.players
    lines = engine.pts_stat_lines(d.table("m_player_pool"), window)
    by_stat = model.points_by_stat(lines.reindex(players.index), d.ctx.scoring)
    sources = model.points_by_source(by_stat, d.ctx.scoring, players["fpg"])
    week_games = model.week_games(d.table("pro_schedule"),
                                  [d.ctx.current_week])[d.ctx.current_week]  # fmt: skip
    teams, by_source = [], []
    for team in setup.teams:
        roster = setup.roster(team)
        sim = setup.full_weeks(roster)
        starts = pd.Series(sim["starts"], dtype="float64").reindex(roster).fillna(0) / len(
            setup.weeks
        )
        healthy_now = players.loc[roster, "back"] <= d.ctx.current_week
        games_now = players.loc[roster, "pro_team"].map(week_games).fillna(0) * healthy_now
        bench = players.loc[roster, "fpg"].sort_values(ascending=False).iloc[setup.starting :]
        teams.append({"team_id": team, "projected_points": setup.full_mu(roster),
                      "this_week": sim["weeks"].get(d.ctx.current_week, 0.0),
                      "games_this_week": int(games_now.sum()),
                      "bench_fpg": float(bench.mean()) if len(bench) else None})  # fmt: skip
        by_source.append({"team_id": team, **sources.loc[roster].mul(starts, axis=0).sum()})
    frame = pd.DataFrame(teams).set_index("team_id")
    frame["expected_wins"] = model.expected_wins(frame["projected_points"], setup.sigma)
    return {"teams": rows(frame.sort_values("projected_points", ascending=False), "team_id"),
            "sources": rows(pd.DataFrame(by_source))}  # fmt: skip


@router.get("/players")
def players(window: str | None = None, position: str | None = None, q: str | None = None,
            hide_injured: bool = False, d: LeagueData = Depends(data)):  # fmt: skip
    """The Player Rankings heatmap: every pool player ranked, with his team, status and
    (categories) a z per category or (points) fantasy points per game."""
    window = d.window(window)
    if d.ctx.is_points:
        frame = d.pts_players(window).copy()
        frame["rank"] = frame["fpg"].rank(ascending=False, method="min")
        frame = frame.sort_values("rank").reset_index(names="player_id")
        keep = ["player_id", "rank", "player_name", "position", "pro_team", "team_id",
                "injury_status", "is_free_agent", "is_ir", "eligible_slots", "fpg"]  # fmt: skip
        frame = frame[[c for c in keep if c in frame]]
    else:
        frame = engine.cat_rankings(d.table("m_player_z"), window).reset_index()
    if position:
        frame = frame.loc[frame["position"].fillna("").str.contains(position, case=False)]
    if q:
        frame = frame.loc[frame["player_name"].str.contains(q, case=False, regex=False)]
    if hide_injured:
        frame = frame.loc[~frame["injury_status"].isin(model.UNAVAILABLE)]
    return body(d, window=window, players=rows(frame))


@router.get("/players/{player_id}")
def player(player_id: int, d: LeagueData = Depends(data)):
    """One player: every stat window's per-game line, his health and games history,
    and his value in this league per window."""
    pool = d.table("m_player_pool")
    mine = pool.loc[pool["player_id"] == player_id]
    if mine.empty:
        raise HTTPException(404, "No such player in this league's pool.")
    info = mine.iloc[0]
    lines = mine.pivot_table(index="stat_window", columns="stat", values="value",
                             aggfunc="first")  # fmt: skip
    profile = d.table("m_player_profile")
    health = profile.loc[profile["player_id"] == player_id]
    if d.ctx.is_points:
        points = d.table("player_points")
        values = rows(points.loc[points["player_id"] == player_id,
                                 ["stat_window", "fp_per_game", "fp_total", "games"]])  # fmt: skip
    else:
        z = d.table("m_player_z")
        values = rows(z.loc[z["player_id"] == player_id,
                            ["stat_window", "category", "value", "z"]])  # fmt: skip
    keep = ["player_name", "position", "pro_team", "team_id", "lineup_slot", "injury_status",
            "expected_return_date", "eligible_slots", "is_free_agent", "is_ir"]  # fmt: skip
    return body(d, player_id=player_id, info=engine.plain({k: info[k] for k in keep}),
                lines=rows(lines, "stat_window"), values=values,
                health=rows(health)[0] if len(health) else None)  # fmt: skip


@router.get("/history")
def history(metric: str = Query("category_ranks", pattern="^(category_ranks|standings|"
                                "player_values)$"),
            start: dt.date | None = None, end: dt.date | None = None,
            d: LeagueData = Depends(data), store=Depends(store)):  # fmt: skip
    """Day-by-day history from the daily snapshots, with each row's change since the
    same day a week before (the week-over-week deltas). Defaults to the last 4 weeks."""
    end = end or services.today()
    start = start or end - dt.timedelta(days=28)
    if start > end:
        raise HTTPException(422, "start is after end.")
    if metric == "category_ranks" and d.ctx.is_points:
        raise HTTPException(422, "Points leagues have no category ranks; try standings.")
    found = store.history(d.ctx.league_id, d.ctx.version, metric, start, end)
    return body(
        d,
        metric=metric,
        start=start.isoformat(),
        end=end.isoformat(),
        rows=rows(found.sort_values(list(found.columns[:2])) if len(found) else found),
    )


@router.get("/transactions")
def transactions(start: dt.date | None = None, end: dt.date | None = None,
                 team: int | None = None, type: str | None = None,
                 d: LeagueData = Depends(data)):  # fmt: skip
    """The activity log, newest first, filtered by date, team and action type."""
    log = d.table("m_transactions")
    if len(log):
        day = pd.to_datetime(log["txn_date"], utc=True).dt.tz_convert("America/New_York").dt.date
        keep = pd.Series(True, index=log.index)
        if start:
            keep &= day >= start
        if end:
            keep &= day <= end
        if team is not None:
            keep &= log["team_id"] == team
        if type:
            keep &= (log["action_type"].str.lower() == type.lower()) | (
                log["action"].str.lower() == type.lower()
            )
        log = log.loc[keep].sort_values("txn_date", ascending=False)
    return body(d, transactions=rows(log))


@router.post("/refresh", status_code=202)
def refresh(d: LeagueData = Depends(data), store=Depends(store)):
    """Start this league's refresh now (at most hourly, as in the app)."""
    try:
        store.refresh(d.ctx.doc, dt.datetime.now(dt.UTC))
    except tenancy.TenancyError as error:
        raise HTTPException(429, str(error)) from None
    return {"league_id": d.ctx.league_id, "started": True}
