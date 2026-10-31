"""新人榜：一年級生 + 二年級生合併排行（每 36 分鐘數據）、近 7 天進步榜。

排名指標：Game Score / 36（Hollinger Game Score 標準化到 36 分鐘）
  GS = PTS + 0.4*FGM - 0.7*FGA - 0.4*(FTA-FT) + 0.7*OREB + 0.3*DREB
       + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV
以每 36 分鐘計，避免上場時間多寡直接決定排名。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .sources import current_season_year, espn_gamelog, norm_name

KEEP_POS = {"G", "F", "C"}


def game_score_36(p: dict) -> float:
    """用 per-36 數據算 Game Score / 36（完整公式，含 ORB/DRB 拆分）。"""
    return (
        p["pts36"]
        + 0.4 * p["fgm36"]
        - 0.7 * p["fga36"]
        - 0.4 * (p["fta36"] - p["ftm36"])
        + 0.7 * p["oreb36"]
        + 0.3 * p["dreb36"]
        + p["stl36"]
        + 0.7 * p["ast36"]
        + 0.7 * p["blk36"]
        - 0.4 * p["pf36"]
        - p["tov36"]
    )


def _num(v) -> float:
    try:
        return float(str(v).split("-")[0]) if "-" in str(v) else float(v)
    except (TypeError, ValueError):
        return 0.0


def _pair(v) -> tuple[float, float]:
    s = str(v or "")
    if "-" in s:
        a, b = s.split("-", 1)
        return _num(a), _num(b)
    return _num(s), _num(s)


def _minutes(v) -> float:
    """'34:12' 或 '34' → 分鐘。"""
    s = str(v or "").strip()
    if not s:
        return 0.0
    if ":" in s:
        m, sec = s.split(":", 1)
        try:
            return float(m) + float(sec) / 60.0
        except ValueError:
            return 0.0
    return _num(s)


def game_score_from_log(stats: dict) -> tuple[float, float]:
    """單場比賽（ESPN gamelog）→ (Game Score, 出賽分鐘)。"""
    fgm, fga = _pair(stats.get("fieldGoalsMade-fieldGoalsAttempted"))
    ftm, fta = _pair(stats.get("freeThrowsMade-freeThrowsAttempted"))
    pts = _num(stats.get("points"))
    reb = _num(stats.get("totalRebounds"))
    ast = _num(stats.get("assists"))
    blk = _num(stats.get("blocks"))
    stl = _num(stats.get("steals"))
    pf = _num(stats.get("fouls"))
    tov = _num(stats.get("turnovers"))
    gs = (
        pts
        + 0.4 * fgm
        - 0.7 * fga
        - 0.4 * (fta - ftm)
        + 0.4 * reb          # gamelog 未拆 ORB/DRB，以 0.4 加權近似
        + stl
        + 0.7 * ast
        + 0.7 * blk
        - 0.4 * pf
        - tov
    )
    return gs, _minutes(stats.get("minutes"))


def recent_trend(espn_id: str, days: int = 7, today=None) -> dict:
    """近 N 天 game score / 36 與本季平均的差距。"""
    from datetime import date, datetime, timedelta, timezone

    today = today or datetime.now(timezone.utc).date()
    logs = espn_gamelog(espn_id, season=current_season_year())
    if not logs:
        return {}
    parsed = []
    for row in logs:
        d = None
        for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                d = datetime.strptime(str(row.get("date"))[:19].replace(" ", "T"), fmt.replace("Z", ""))
                break
            except (TypeError, ValueError):
                continue
        if d is None:
            try:
                d = datetime.fromisoformat(str(row.get("date")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
        gs, mins = game_score_from_log(row.get("stats") or {})
        parsed.append({"date": d.date() if hasattr(d, "date") else d, "gs": gs, "min": mins})

    if not parsed:
        return {}
    recent = [p for p in parsed if p["min"] > 0 and (today - p["date"]).days <= days]
    season = [p for p in parsed if p["min"] > 0]

    def per36(rows):
        mins = sum(r["min"] for r in rows)
        if mins <= 0:
            return 0.0
        return sum(r["gs"] for r in rows) / mins * 36.0

    s36 = per36(season)
    r36 = per36(recent)
    return {
        "recent_games": len(recent),
        "recent_gs36": round(r36, 2),
        "season_gs36_log": round(s36, 2),
        "delta": round(r36 - s36, 2) if recent else 0.0,
        "recent_min": round(sum(r["min"] for r in recent) / len(recent), 1) if recent else 0.0,
    }


def season_years(exp, has_exp_one: bool):
    """把 ESPN 的 experience.years 換算成「第幾季（0 = 新人）」。

    ESPN 這批名單有一個偏移：新人記 0，但第 2 季記成 2、第 5 季記成 5（= 實際球季數 + 1），
    名單裡完全不會出現 1。同時做防呆：若來源哪天出現 exp == 1（標準慣例），就照標準解讀。
    """
    if exp is None:
        return None
    if exp == 0:
        return 0
    if has_exp_one:
        return exp
    return exp - 1


def build_board(rosters: dict, teams: dict, per36_cur: dict, per36_prev: dict,
                with_trend: bool = True, trend_days: int = 7) -> dict:
    """合併一年級＋二年級排行。"""
    all_exps = {p.get("exp") for ps in rosters.values() for p in ps if p.get("exp") is not None}
    has_exp_one = 1 in all_exps

    rows = []
    for tid, players in rosters.items():
        for p in players:
            seasons = season_years(p.get("exp"), has_exp_one)
            if seasons not in (0, 1):
                continue
            key = norm_name(p["name"])
            cur = per36_cur.get(key)
            prev = per36_prev.get(key)
            if not cur and not prev:
                continue
            src = cur or prev
            games = int(cur["g"]) if cur else 0
            mpg = cur["mpg"] if cur else 0.0
            if mpg <= 0 and prev:
                mpg = prev["mpg"]
            rec = {
                "espn_id": p.get("espn_id"),
                "name": p["name"],
                "class": "一年級" if seasons == 0 else "二年級",
                "exp": seasons,
                "pos": p.get("pos"),
                "age": p.get("age"),
                "headshot": p.get("headshot"),
                "team": teams.get(tid, {}).get("abbrev", ""),
                "team_name": teams.get(tid, {}).get("name", ""),
                "team_logo": teams.get(tid, {}).get("logo"),
                "g": games,
                "mpg": round(mpg, 1),
                "pts36": round(src["pts36"], 1),
                "reb36": round(src["reb36"], 1),
                "ast36": round(src["ast36"], 1),
                "stl36": round(src["stl36"], 1),
                "blk36": round(src["blk36"], 1),
                "ts": round((src.get("ts_pct") or 0) * 100, 1),
                "gs36": round(game_score_36(src), 2),
                "sample": "足夠" if games >= 5 else ("偏少" if games >= 2 else "極少"),
            }
            if games > 0:
                rec["ppg"] = round(src["pts36"] * mpg / 36.0, 1)
                rec["gs_pg"] = round(rec["gs36"] * mpg / 36.0, 2)
            else:
                rec["ppg"] = 0.0
                rec["gs_pg"] = 0.0
            rows.append(rec)

    qualified = [r for r in rows if r["g"] >= 3 and r["mpg"] >= 8]
    qualified.sort(key=lambda r: -r["gs36"])
    for i, r in enumerate(qualified, 1):
        r["rank"] = i
    watch = [r for r in rows if r not in qualified]
    watch.sort(key=lambda r: (-r["g"], -r["mpg"]))
    for i, r in enumerate(watch, 1):
        r["rank"] = i

    trend = []
    if with_trend and qualified:
        def work(r):
            t = recent_trend(r["espn_id"], days=trend_days) if r.get("espn_id") else {}
            return {**r, "trend": t}

        with ThreadPoolExecutor(max_workers=8) as pool:
            enriched = list(pool.map(work, qualified))
        trend = [r for r in enriched if r["trend"].get("recent_games", 0) >= 2]
        trend.sort(key=lambda r: -r["trend"]["delta"])
        for i, r in enumerate(trend, 1):
            r["trend_rank"] = i

    rookies_only = [r for r in qualified if r["exp"] == 0]
    sophs_only = [r for r in qualified if r["exp"] == 1]
    print(f"      一年級 {len(rookies_only)} 位、二年級 {len(sophs_only)} 位（ESPN 年資偏移修正：has_exp_one={has_exp_one}）")
    return {
        "combined": qualified[:30],
        "watch": watch[:12],
        "trend": trend[:15],
        "counts": {
            "rookies": len(rookies_only),
            "sophomores": len(sophs_only),
            "trend_window_days": trend_days,
        },
    }
