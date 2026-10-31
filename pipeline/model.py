"""預測模型：以「實際會上場的球員」為基礎，推算兩隊得分 → 5 分級距 → 不讓分勝率。

模型流程
--------
1. 名單：ESPN 球隊名單（含年資、大頭貼）。
2. 傷病：ESPN / CBS / Yahoo 三源交叉比對，取最嚴重狀態為共識，換算上場時間係數。
3. 球員強度：Basketball-Reference 當季 + 前一季 per-36 數據，依出賽場次做貝氏收縮。
4. 分鐘分配：只給實際會用的 8–11 人輪替，把 240 分鐘依「平常上場時間 × 可用性」重新分配，
   單人上限 40 分鐘；缺陣者的分鐘自然流向替補。
5. 可用性指數：把「今天的分配」與「全員健康時的分配」相比，得到 0.6–1.1 的係數。
6. 球隊效率：收縮後的進攻效率 × 可用性指數，與對手防守效率幾何混合（0.58 / 0.42）。
7. 比賽：預期回合數 × 每回合效率 = 預期得分；主場 ±1.4 分。
8. 不確定性 σ = 10.3 分 + 傷病不確定性 + 開季小樣本懲罰（8–15 分）。
9. 蒙地卡羅 20,000 次 → 勝率、5 分級距機率、最可能比分、信心指數。
"""
from __future__ import annotations

import math

import numpy as np

from .injuries import MINUTES_FACTOR, match_player
from .sources import norm_name

TEAM_MINUTES = 240.0
SIGMA_BASE = 10.3
HOME_EDGE = 1.4
SIMS = 20000
SHRINK_GAMES = 12.0          # 球員層級的收縮強度（場）
TEAM_SHRINK_GAMES = 10.0     # 球隊層級的收縮強度（場）
MAX_PLAYER_MINUTES = 40.0
MIN_ROTATION = 8


def _shrink(cur: float, games: float, prior: float, k: float = SHRINK_GAMES) -> float:
    if games <= 0:
        return prior
    return (games * cur + k * prior) / (games + k)


def league_context(team_stats: dict, results: dict) -> dict:
    """全聯盟基準值。"""
    ppgs = [v["ppg"] for v in team_stats.values() if v.get("ppg")]
    poss = [v["poss"] for v in team_stats.values() if v.get("poss")]
    lg_ppg = sum(ppgs) / len(ppgs) if ppgs else 114.0
    lg_poss = sum(poss) / len(poss) if poss else 100.0
    lg_ortg = 100.0 * lg_ppg / lg_poss if lg_poss else 114.0
    ts_all = [v["ts_pct"] for v in team_stats.values() if v.get("ts_pct")]
    return {
        "ppg": lg_ppg,
        "poss": lg_poss,
        "ortg": lg_ortg,
        "ts": sum(ts_all) / len(ts_all) if ts_all else 0.57,
        "games_played": max([v.get("games") or 0 for v in team_stats.values()] or [0]),
    }


def player_rows(roster: list, per36_cur: dict, per36_prev: dict, consensus: dict, lg: dict) -> list:
    """把名單球員補上 per-36 數據、傷病狀態與上場時間係數。"""
    rows = []
    for p in roster:
        key = norm_name(p["name"])
        cur = per36_cur.get(key)
        prev = per36_prev.get(key)
        inj = match_player(p, consensus)

        g = float(cur["g"]) if cur else 0.0
        prior_g = float(prev["g"]) if prev else 0.0

        def stat(field, default=0.0):
            c = cur.get(field) if cur else None
            pv = prev.get(field) if prev else None
            if c is None:
                c = pv
            if pv is None:
                pv = default
            if c is None:
                c = pv
            return _shrink(float(c), g, float(pv))

        mpg = stat("mpg", default=6.0)
        pts36 = stat("pts36", default=max(5.0, lg["ppg"] / 9.0))
        ts = stat("ts_pct", default=lg["ts"])

        status = inj["consensus"] if inj else "AVAILABLE"
        factor = MINUTES_FACTOR.get(status, 1.0)
        srcs = (inj or {}).get("statuses", {})

        rows.append(
            {
                "espn_id": p.get("espn_id"),
                "name": p["name"],
                "pos": p.get("pos"),
                "exp": p.get("exp"),
                "headshot": p.get("headshot"),
                "age": p.get("age"),
                "status": status,
                "status_sources": srcs,
                "status_detail": (inj or {}).get("details", {}),
                "injury_conflict": bool((inj or {}).get("conflict")),
                "minutes_factor": factor,
                "base_mpg": mpg,
                "games": int(g or prior_g),
                "pts36": pts36,
                "reb36": stat("reb36", default=4.5),
                "ast36": stat("ast36", default=2.2),
                "stl36": stat("stl36", default=0.7),
                "blk36": stat("blk36", default=0.35),
                "tov36": stat("tov36", default=1.3),
                "pf36": stat("pf36", default=2.0),
                "fgm36": stat("fgm36", default=2.8),
                "fga36": stat("fga36", default=6.5),
                "ftm36": stat("ftm36", default=1.0),
                "fta36": stat("fta36", default=1.4),
                "oreb36": stat("oreb36", default=0.9),
                "dreb36": stat("dreb36", default=3.6),
                "ts": ts,
            }
        )
    return rows


def assign_minutes(rows: list, weight_fn) -> dict:
    """依權重挑出輪替球員並把 240 分鐘分配完，回傳 {id(row): 分鐘}。"""
    pool = [r for r in rows if weight_fn(r) > 0]
    pool.sort(key=weight_fn, reverse=True)
    rotation, cum = [], 0.0
    for r in pool:
        rotation.append(r)
        cum += weight_fn(r)
        if cum >= TEAM_MINUTES and len(rotation) >= MIN_ROTATION:
            break
    if not rotation:
        return {}

    scale = TEAM_MINUTES / cum if cum > 0 else 0.0
    mins = {id(r): min(MAX_PLAYER_MINUTES, weight_fn(r) * scale) for r in rotation}

    # 上限裁切後把不足的分鐘補回其他輪替球員
    for _ in range(4):
        deficit = TEAM_MINUTES - sum(mins.values())
        if abs(deficit) < 0.4:
            break
        adjustable = [
            r
            for r in rotation
            if (deficit < 0 and mins[id(r)] > 0.5) or (deficit > 0 and mins[id(r)] < MAX_PLAYER_MINUTES)
        ]
        wsum = sum(weight_fn(r) for r in adjustable) or 1.0
        for r in adjustable:
            mins[id(r)] = max(0.0, min(MAX_PLAYER_MINUTES, mins[id(r)] + deficit * weight_fn(r) / wsum))
    return mins


def team_projection(rows: list, team: dict, opp: dict, team_stats: dict, results: dict, lg: dict) -> dict:
    """單隊預期得分與不確定性。"""
    ts_cap = 0.16

    def eff_pts36(r):
        # 真實命中率偏離聯盟平均 → 效率微調（上限 ±16%）
        ts_delta = (r["ts"] or lg["ts"]) - lg["ts"]
        mult = 1.0 + max(-ts_cap, min(ts_cap, 0.6 * ts_delta))
        return r["pts36"] * mult

    # 今天的分配（含傷病係數）與全員健康的分配，兩者相比 = 可用性
    actual = assign_minutes(rows, lambda r: max(r["base_mpg"], 0.0) * r["minutes_factor"])
    healthy = assign_minutes(rows, lambda r: max(r["base_mpg"], 0.0))
    for r in rows:
        r["proj_min"] = round(actual.get(id(r), 0.0), 1)

    lineup_proj = sum(m / 36.0 * eff_pts36(r) for r, m in ((r, actual.get(id(r), 0.0)) for r in rows))
    healthy_proj = sum(m / 36.0 * eff_pts36(r) for r, m in ((r, healthy.get(id(r), 0.0)) for r in rows))
    availability = (lineup_proj / healthy_proj) if healthy_proj > 0 else 1.0
    availability = max(0.60, min(1.0, availability))

    st = team_stats.get(team["id"], {})
    games = float(st.get("games") or 0)
    ppg = st.get("ppg") or results.get(team["id"], {}).get("ppg") or lg["ppg"]
    poss_t = st.get("poss") or lg["poss"]
    ortg_t = _shrink(100.0 * ppg / poss_t if poss_t else lg["ortg"], games, lg["ortg"], TEAM_SHRINK_GAMES)

    res_opp = results.get(opp["id"], {})
    opp_drtg_raw = res_opp.get("drtg")
    opp_games = float(res_opp.get("games") or 0)
    drtg_o = _shrink(opp_drtg_raw if opp_drtg_raw else lg["ortg"], opp_games, lg["ortg"], TEAM_SHRINK_GAMES)

    poss_o = team_stats.get(opp["id"], {}).get("poss") or lg["poss"]
    exp_poss = (poss_t + poss_o) / 2.0

    ortg_adj = ortg_t * availability
    eff = (ortg_adj ** 0.58) * (drtg_o ** 0.42)  # 幾何混合，避免雙重計算
    pred = exp_poss * eff / 100.0

    # 缺陣的淨影響（換算成預測得分）
    gross_total = sum(
        ((max(r["base_mpg"], 0.0) - r["proj_min"]) if r["minutes_factor"] < 1.0 else 0.0)
        * eff_pts36(r) / 36.0
        for r in rows
    )
    # 淨失分 = 「全員健康」預期得分與今日陣容預期得分的差，換算成預測分數尺度
    net_lost = max(0.0, (healthy_proj - lineup_proj) * (pred / lineup_proj if lineup_proj else 1.0))

    # 不確定性
    uncertain_min = sum(
        r["proj_min"] for r in rows if r["status"] in ("QUESTIONABLE", "DAY_TO_DAY", "DOUBTFUL")
    )
    sigma = SIGMA_BASE + 0.09 * uncertain_min + 2.0 * max(0.0, 1.0 - games / 10.0)
    sigma = max(8.0, min(15.0, sigma))

    out_players = sorted(
        [
            {
                "name": r["name"],
                "pos": r["pos"],
                "status": r["status"],
                "est_lost_points": round(
                    net_lost * (((max(r["base_mpg"], 0.0) - r["proj_min"]) * eff_pts36(r) / 36.0) / gross_total), 1
                )
                if gross_total > 0
                else 0.0,
                "detail": (
                    r["status_detail"].get("ESPN")
                    or r["status_detail"].get("CBS")
                    or r["status_detail"].get("Yahoo")
                    or ""
                ),
                "sources": r["status_sources"],
                "conflict": r["injury_conflict"],
            }
            for r in rows
            if r["minutes_factor"] < 1.0 and r["base_mpg"] >= 12.0
        ],
        key=lambda x: -x["est_lost_points"],
    )

    return {
        "team": team,
        "pred_pts": round(pred, 1),
        "sigma": round(sigma, 1),
        "ortg": round(ortg_t, 1),
        "drtg_opp": round(drtg_o, 1),
        "pace": round(exp_poss, 1),
        "availability": round(availability, 3),
        "season_ppg": round(ppg, 1),
        "lost_points": round(net_lost, 1),
        "out_players": out_players[:6],
        "rotation": sorted(
            [
                {
                    "name": r["name"],
                    "pos": r["pos"],
                    "exp": r["exp"],
                    "headshot": r["headshot"],
                    "status": r["status"],
                    "proj_min": r["proj_min"],
                    "proj_pts": round(r["proj_min"] / 36.0 * eff_pts36(r), 1),
                }
                for r in rows
                if r["proj_min"] >= 1.0
            ],
            key=lambda x: -x["proj_min"],
        )[:11],
        "data_games": int(games),
    }


def bucket_of(points: float) -> str:
    lo = int(math.floor((points - 1) / 5.0) * 5 + 1)
    return f"{lo}-{lo + 4}"


def simulate(home: dict, away: dict) -> dict:
    """蒙地卡羅：勝率、得分級距機率、最可能比分。"""
    rng = np.random.default_rng(20261030)
    hs = rng.normal(home["pred_pts"] + HOME_EDGE, home["sigma"], SIMS)
    as_ = rng.normal(away["pred_pts"] - HOME_EDGE, away["sigma"], SIMS)
    hs = np.clip(hs, 70, 180)
    as_ = np.clip(as_, 70, 180)
    win = float(np.mean(hs > as_))
    margin = float(np.mean(hs - as_))

    def bucket_dist(sample):
        lo = (np.floor((sample - 1) / 5.0) * 5 + 1).astype(int)
        vals, counts = np.unique(lo, return_counts=True)
        dist = [(f"{int(v)}-{int(v) + 4}", c / len(sample)) for v, c in zip(vals, counts)]
        dist.sort(key=lambda x: -x[1])
        return dist

    hb = bucket_dist(hs)
    ab = bucket_dist(as_)

    # 最可能比分：對四捨五入後的實際比分做二維直方圖，取眾數
    hh = np.rint(hs).astype(int)
    aa = np.rint(as_).astype(int)
    joint = {}
    for h_val, a_val in zip(hh, aa):
        joint[(h_val, a_val)] = joint.get((h_val, a_val), 0) + 1
    top = sorted(joint.items(), key=lambda kv: -kv[1])[:1]
    best = top[0][0] if top else (round(home["pred_pts"]), round(away["pred_pts"]))

    bucket_hit = (hb[0][1] if hb else 0.0) * (ab[0][1] if ab else 0.0)
    # 信心指數 1–5：主要看勝率偏離 50% 的幅度，開季小樣本扣分
    edge = abs(win - 0.5)
    confidence = 1.5 + min(2.6, edge * 11.0)
    if min(home["data_games"], away["data_games"]) < 8:
        confidence -= 0.5
    if min(home["data_games"], away["data_games"]) >= 20:
        confidence += 0.3
    confidence = round(max(1.0, min(5.0, confidence)) * 2) / 2

    return {
        "home_win_prob": round(win, 4),
        "away_win_prob": round(1 - win, 4),
        "exp_margin": round(margin, 1),
        "home_buckets": [(l, round(p, 4)) for l, p in hb[:4]],
        "away_buckets": [(l, round(p, 4)) for l, p in ab[:4]],
        "likely_score": f"{best[1]}-{best[0]}",
        "both_bucket_hit_prob": round(bucket_hit, 4),
        "confidence": confidence,
    }


def predict_game(game: dict, teams: dict, rosters: dict, per36_cur: dict, per36_prev: dict,
                 consensus: dict, team_stats: dict, results: dict, lg: dict) -> dict:
    home_team = teams.get(
        game["home"]["id"],
        {"id": game["home"]["id"], "abbrev": game["home"]["abbrev"], "name": game["home"]["name"]},
    )
    away_team = teams.get(
        game["away"]["id"],
        {"id": game["away"]["id"], "abbrev": game["away"]["abbrev"], "name": game["away"]["name"]},
    )

    home_rows = player_rows(rosters.get(home_team["id"], []), per36_cur, per36_prev, consensus, lg)
    away_rows = player_rows(rosters.get(away_team["id"], []), per36_cur, per36_prev, consensus, lg)

    home = team_projection(home_rows, home_team, away_team, team_stats, results, lg)
    away = team_projection(away_rows, away_team, home_team, team_stats, results, lg)
    sim = simulate(home, away)

    ou = home["pred_pts"] + away["pred_pts"]
    return {
        "event_id": game["event_id"],
        "date_utc": game["date_utc"],
        "status": game["status"],
        "venue": game.get("venue"),
        "home": home,
        "away": away,
        "sim": sim,
        "pred_total": round(ou, 1),
        "pred_total_bucket": bucket_of(ou),
        "pred_margin": round(home["pred_pts"] + HOME_EDGE - (away["pred_pts"] - HOME_EDGE), 1),
    }
