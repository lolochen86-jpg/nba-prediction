"""回測：每日預測快照 + 賽後自動評分 → 命中率統計。"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta, timezone

from .sources import espn_scoreboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRED_DIR = os.path.join(ROOT, "data", "predictions")
RESULT_DIR = os.path.join(ROOT, "data", "results")

TPE = timezone(timedelta(hours=8))


def _ensure():
    os.makedirs(PRED_DIR, exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)


def save_predictions(et_date: str, games: list) -> str:
    """et_date: 'YYYY-MM-DD'（美東日期，用於對應賽程日）。"""
    _ensure()
    slim = []
    for g in games:
        slim.append(
            {
                "event_id": g["event_id"],
                "date_utc": g["date_utc"],
                "status": g["status"],
                "home_abbrev": g["home"]["team"]["abbrev"],
                "away_abbrev": g["away"]["team"]["abbrev"],
                "home_pred": g["home"]["pred_pts"],
                "away_pred": g["away"]["pred_pts"],
                "home_sigma": g["home"]["sigma"],
                "away_sigma": g["away"]["sigma"],
                "home_bucket": g["sim"]["home_buckets"][0][0],
                "away_bucket": g["sim"]["away_buckets"][0][0],
                "home_win_prob": g["sim"]["home_win_prob"],
                "pred_total": g["pred_total"],
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
    path = os.path.join(PRED_DIR, f"{et_date}.json")
    existing = {}
    if os.path.exists(path):
        try:
            for rec in json.load(open(path, encoding="utf-8")):
                existing[rec["event_id"]] = rec
        except Exception:  # noqa: BLE001
            existing = {}
    for rec in slim:
        existing[rec["event_id"]] = rec  # 同一天重跑：以最新一次為準（並保留第一次）
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(existing.values()), fh, ensure_ascii=False, indent=1)
    return path


def _buckets(pts: float) -> str:
    lo = int((int(pts) - 1) // 5 * 5 + 1)
    return f"{lo}-{lo + 4}"


def grade_all(lookback_days: int = 45) -> dict:
    """把已開打的預測快照與實際比分比對，寫入 data/results。"""
    _ensure()
    graded = []
    files = sorted(glob.glob(os.path.join(PRED_DIR, "*.json")))
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=lookback_days)

    for path in files:
        day = os.path.basename(path).replace(".json", "")
        try:
            day_date = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day_date < cutoff:
            continue
        result_path = os.path.join(RESULT_DIR, f"{day}.json")
        if os.path.exists(result_path):
            try:
                graded.extend(json.load(open(result_path, encoding="utf-8")))
                continue
            except Exception:  # noqa: BLE001
                pass
        preds = json.load(open(path, encoding="utf-8"))
        try:
            games = espn_scoreboard(day.replace("-", ""), ttl=3600)
        except Exception:  # noqa: BLE001
            continue
        actual = {g["event_id"]: g for g in games}
        day_records = []
        for p in preds:
            g = actual.get(p["event_id"])
            if not g or not g.get("completed"):
                continue
            hs, as_ = g["home"].get("score"), g["away"].get("score")
            if hs is None or as_ is None:
                continue
            home_won = hs > as_
            pred_home_win = p["home_win_prob"] > 0.5
            hb = _buckets(hs)
            ab = _buckets(as_)
            day_records.append(
                {
                    "event_id": p["event_id"],
                    "date": day,
                    "home": p["home_abbrev"],
                    "away": p["away_abbrev"],
                    "pred_home": p["home_pred"],
                    "pred_away": p["away_pred"],
                    "act_home": hs,
                    "act_away": as_,
                    "pred_winner": p["home_abbrev"] if pred_home_win else p["away_abbrev"],
                    "act_winner": p["home_abbrev"] if home_won else p["away_abbrev"],
                    "winner_hit": pred_home_win == home_won,
                    "home_win_prob": p["home_win_prob"],
                    "pred_home_bucket": p["home_bucket"],
                    "pred_away_bucket": p["away_bucket"],
                    "act_home_bucket": hb,
                    "act_away_bucket": ab,
                    "home_bucket_hit": p["home_bucket"] == hb,
                    "away_bucket_hit": p["away_bucket"] == ab,
                    "both_bucket_hit": p["home_bucket"] == hb and p["away_bucket"] == ab,
                    "abs_err_home": round(abs(p["home_pred"] - hs), 1),
                    "abs_err_away": round(abs(p["away_pred"] - as_), 1),
                    "abs_err_total": round(abs(p["pred_total"] - (hs + as_)), 1),
                }
            )
        if day_records:
            with open(result_path, "w", encoding="utf-8") as fh:
                json.dump(day_records, fh, ensure_ascii=False, indent=1)
            graded.extend(day_records)
    return {"records": graded, "summary": summarize(graded)}


def summarize(records: list) -> dict:
    n = len(records)
    if not n:
        return {"games": 0}
    def rate(key):
        return round(100.0 * sum(1 for r in records if r.get(key)) / n, 1)
    mae = sum(r["abs_err_total"] for r in records) / n
    brier = sum((r["home_win_prob"] - (1.0 if r["act_home"] > r["act_away"] else 0.0)) ** 2 for r in records) / n
    return {
        "games": n,
        "winner_acc": rate("winner_hit"),
        "home_bucket_acc": rate("home_bucket_hit"),
        "away_bucket_acc": rate("away_bucket_hit"),
        "both_bucket_acc": rate("both_bucket_hit"),
        "mae_total": round(mae, 1),
        "brier": round(brier, 4),
    }


def rolling(records: list, days: int) -> dict:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    subset = [r for r in records if datetime.strptime(r["date"], "%Y-%m-%d").date() >= cutoff]
    return summarize(subset)
