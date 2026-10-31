"""建置入口：抓資料 → 跑模型 → 產生靜態網站。

用法：
    python -m pipeline.build            # 完整建置
    python -m pipeline.build --no-grade  # 略過賽後評分
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import traceback
from datetime import datetime, timedelta, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import backtest, model, rookies, sources
from .injuries import gather as gather_injuries

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
TPL = os.path.join(ROOT, "templates")
STATIC = os.path.join(ROOT, "static")

TPE = timezone(timedelta(hours=8))
ET = timezone(timedelta(hours=-4))


def season_year(now: datetime) -> int:
    """NBA 球季以結束年度命名（2026-27 → 2027）。"""
    return now.year + 1 if now.month >= 8 else now.year


def team_results(teams: dict, start: datetime, today: datetime) -> dict:
    """用本季已完成的比賽累計每隊場均得分 / 失分 / 防守效率。"""
    agg: dict[str, dict] = {}
    d = start.date()
    while d <= today.date():
        try:
            games = sources.espn_scoreboard(d.strftime("%Y%m%d"), ttl=30 * 86400 if d < today.date() else 600)
        except Exception:  # noqa: BLE001
            games = []
        for g in games:
            if not g.get("completed"):
                continue
            hs, as_ = g["home"].get("score"), g["away"].get("score")
            if hs is None or as_ is None:
                continue
            for tid, own, other in ((g["home"]["id"], hs, as_), (g["away"]["id"], as_, hs)):
                rec = agg.setdefault(tid, {"for": 0, "against": 0, "games": 0})
                rec["for"] += own
                rec["against"] += other
                rec["games"] += 1
        d += timedelta(days=1)

    out = {}
    for tid, rec in agg.items():
        g = rec["games"]
        if not g:
            continue
        out[tid] = {
            "ppg": rec["for"] / g,
            "opp_ppg": rec["against"] / g,
            "games": g,
            "drtg": None,
        }
    return out


def source_health(inj_counts: dict, extra: dict) -> list:
    br_ok = extra.get("br", 0) > 0
    return [
        {"name": "ESPN API", "role": "賽程・名單・球隊數據", "count": extra.get("espn", 0), "ok": extra.get("espn", 0) > 0},
        {
            "name": "Basketball-Reference" if not extra.get("br_fb") else "ESPN 逐場（BR 備援）",
            "role": "per-36 球員數據" if not extra.get("br_fb") else "BR 被封鎖，改用逐場紀錄回推 per-36",
            "count": extra.get("br", 0),
            "ok": br_ok,
        },
        {"name": "CBS Sports", "role": "傷病報告", "count": inj_counts.get("CBS", 0), "ok": inj_counts.get("CBS", 0) > 0},
        {"name": "Yahoo Sports", "role": "傷病報告", "count": inj_counts.get("Yahoo", 0), "ok": inj_counts.get("Yahoo", 0) > 0},
        {"name": "NBA CDN", "role": "球員大頭貼", "count": extra.get("headshots", 0), "ok": extra.get("headshots", 0) > 0},
    ]


def main(grade: bool = True) -> None:
    now_utc = datetime.now(timezone.utc)
    now_tpe = now_utc.astimezone(TPE)
    today_et = now_utc.astimezone(ET)
    sy = season_year(today_et)

    print(f"[1/7] 抓取球隊與名單（球季 {sy}）…")
    teams = sources.espn_teams()
    rosters = sources.espn_rosters(teams)

    print("[2/7] 球員 per-36 數據（Basketball-Reference）…")
    per36_cur = sources.br_per36(sy)
    per36_prev = sources.br_per36(sy - 1)
    if os.environ.get("NBA_FORCE_BR_FALLBACK") == "1":   # 測試用：模擬 BR 被封鎖
        per36_cur, per36_prev = {}, per36_prev
    br_fallback = False
    # per-36 數據採「BR 優先、ESPN 補齊」：
    #  a) BR 被機房 IP 封鎖 → 回 0 筆，全部改用 ESPN 逐場回推
    #  b) BR 正常但收錄不全（本季約 432 人，缺部分主力）→ 只補缺少的球員
    pairs = [(p["espn_id"], p["name"]) for ps in rosters.values() for p in ps if p.get("espn_id")]
    if len(per36_cur) < 200:
        print(f"      來源只有 {len(per36_cur)} 筆 → 啟用 ESPN 逐場資料備援（約 1–2 分鐘）")
        fb = sources.espn_per36(pairs)
        for k, v in fb.items():
            per36_cur.setdefault(k, v)
        br_fallback = True
        print(f"      備援完成，合計 {len(per36_cur)} 筆")
    else:
        missing = [(eid, name) for eid, name in pairs if sources.norm_name(name) not in per36_cur]
        if missing:
            print(f"      BR 收錄 {len(per36_cur)} 筆，缺少 {len(missing)} 位 → 用 ESPN 補齊")
            fb = sources.espn_per36(missing)
            added = 0
            for k, v in fb.items():
                if k not in per36_cur:
                    per36_cur[k] = v
                    added += 1
            print(f"      補齊 {added} 位，合計 {len(per36_cur)} 筆")

    print("[3/7] 傷病三源交叉比對…")
    consensus = gather_injuries()
    inj_counts = {"ESPN": 0, "CBS": 0, "Yahoo": 0}
    for rec in consensus.values():
        for src in rec["statuses"]:
            inj_counts[src] = inj_counts.get(src, 0) + 1

    print("[4/7] 球隊統計與本季戰績…")
    team_stats = sources.espn_team_stats(teams)
    season_start = datetime(sy - 1, 9, 20, tzinfo=timezone.utc)
    if today_et.month < 9:
        season_start = datetime(sy - 1, 9, 20, tzinfo=timezone.utc)
    results = team_results(teams, season_start, today_et) if (today_et - season_start).days < 200 else {}
    lg = model.league_context(team_stats, results)

    print("[5/7] 今日賽程預測…")
    # 以美東球日為準；若當日全部打完（例如台灣時間下午更新），自動往後找下一個比賽日
    games_today, game_day = [], today_et
    for offset in range(0, 3):
        cand = today_et + timedelta(days=offset)
        try:
            games = sources.espn_scoreboard(cand.strftime("%Y%m%d"), ttl=300)
        except Exception:  # noqa: BLE001
            games = []
        if games and any(not g.get("completed") for g in games):
            games_today, game_day = games, cand
            break
        if games and offset == 0:
            games_today, game_day = games, cand
    if not games_today:
        # 美東球日已換日時，回退到 UTC 當日
        games_today = sources.espn_scoreboard(now_utc.strftime("%Y%m%d"), ttl=300)

    predictions = []
    for g in games_today:
        try:
            predictions.append(
                model.predict_game(g, teams, rosters, per36_cur, per36_prev, consensus, team_stats, results, lg)
            )
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    predictions.sort(key=lambda x: x["date_utc"] or "")
    print(f"      完成 {len(predictions)} 場")

    print("[6/7] 新人榜（一年級＋二年級）…")
    board = rookies.build_board(rosters, teams, per36_cur, per36_prev, with_trend=True, trend_days=7)

    recheck = {"summary": {"games": 0}, "records": [], "rolling7": {}, "rolling30": {}}
    if grade:
        print("[7/7] 賽後回測評分…")
        try:
            graded = backtest.grade_all()
            records = graded["records"]
            recheck = {
                "summary": graded["summary"],
                "rolling7": backtest.rolling(records, 7),
                "rolling30": backtest.rolling(records, 30),
                "records": sorted(records, key=lambda r: r["date"], reverse=True)[:80],
            }
            if predictions:
                backtest.save_predictions(today_et.strftime("%Y-%m-%d"), predictions)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    else:
        if predictions:
            backtest.save_predictions(today_et.strftime("%Y-%m-%d"), predictions)

    print("[render] 產生網站…")
    conflicts = [r for r in consensus.values() if r.get("conflict")]
    payload = {
        "updated_utc": now_utc.isoformat(timespec="seconds"),
        "updated_tpe": now_tpe.strftime("%Y-%m-%d %H:%M"),
        "game_date": game_day.strftime("%Y-%m-%d"),
        "season": f"{sy - 1}-{str(sy)[2:]}",
        "league": {k: round(v, 2) if isinstance(v, float) else v for k, v in lg.items()},
        "health": source_health(
            inj_counts,
            {
                "espn": len(teams) + len(rosters),
                "br": len(per36_cur),
                "br_fb": br_fallback,
                "headshots": sum(1 for ps in rosters.values() for p in ps if p.get("headshot")),
            },
        ),
        "br_fallback": br_fallback,
        "injury_counts": inj_counts,
        "conflicts": len(conflicts),
        "players_tracked": len(consensus),
        "games": predictions,
        "rookies": board,
        "backtest": recheck,
    }
    render(payload)
    with open(os.path.join(SITE, "data", "app.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(f"[done] {len(predictions)} 場比賽、{len(board['combined'])} 位新人\n       更新 {payload['updated_tpe']} (UTC+8)")


def render(payload: dict) -> None:
    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)
    if os.path.isdir(STATIC):
        for name in os.listdir(STATIC):
            shutil.copyfile(os.path.join(STATIC, name), os.path.join(SITE, name))
    env = Environment(
        loader=FileSystemLoader(TPL),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pct"] = lambda v: f"{v * 100:.1f}%"
    env.filters["stars"] = lambda v: "★" * int(round(v)) + "☆" * (5 - int(round(v)))

    def tpe_time(iso):
        """UTC ISO → 台灣時間 MM/DD HH:MM。"""
        if not iso:
            return "時間未定"
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return iso
        return dt.astimezone(TPE).strftime("%m/%d %H:%M")

    env.filters["tpe"] = tpe_time
    for tpl, out in (
        ("index.html", "index.html"),
        ("rookies.html", "rookies.html"),
        ("backtest.html", "backtest.html"),
        ("method.html", "method.html"),
    ):
        html = env.get_template(tpl).render(**payload, page=out.replace(".html", ""))
        with open(os.path.join(SITE, out), "w", encoding="utf-8") as fh:
            fh.write(html)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-grade", action="store_true")
    args = ap.parse_args()
    main(grade=not args.no_grade)
