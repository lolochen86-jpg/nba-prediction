"""傷病三源交叉比對 → 共識上場狀態與上場機率。"""
from __future__ import annotations

import re

from .sources import cbs_injuries, espn_injuries, norm_name, yahoo_injuries

# 嚴重度排序（數字越大越不可能上場）
SEVERITY = {
    "OUT": 4.0,
    "SUSPENDED": 3.8,
    "DOUBTFUL": 3.0,
    "QUESTIONABLE": 2.0,
    "DAY_TO_DAY": 1.5,
    "PROBABLE": 1.0,
    "AVAILABLE": 0.0,
    "UNKNOWN": 0.0,
}

# 上場時間折扣係數（依共識狀態）
MINUTES_FACTOR = {
    "OUT": 0.0,
    "SUSPENDED": 0.0,
    "DOUBTFUL": 0.15,
    "QUESTIONABLE": 0.5,
    "DAY_TO_DAY": 0.75,
    "PROBABLE": 0.95,
    "AVAILABLE": 1.0,
    "UNKNOWN": 1.0,
}

OUTLIKE = {"OUT", "SUSPENDED"}


def classify(status_text: str) -> str:
    """把各家自由文字的傷病狀態映射到標準狀態。"""
    s = (status_text or "").lower()
    if not s:
        return "UNKNOWN"
    if any(k in s for k in ("suspended", "suspend")):
        return "SUSPENDED"
    if "doubtful" in s:
        return "DOUBTFUL"
    if "questionable" in s:
        return "QUESTIONABLE"
    if "probable" in s:
        return "PROBABLE"
    if "day-to-day" in s or "day to day" in s or "gtd" in s:
        return "DAY_TO_DAY"
    if any(
        k in s
        for k in (
            "out for the season",
            "out for season",
            "expected to be out",
            "out until",
            "will not play",
            "ruled out",
            "out",
            "not with team",
            "g league",
            "g-league",
            "personal reasons",
        )
    ):
        return "OUT"
    if "available" in s or "active" in s:
        return "AVAILABLE"
    return "UNKNOWN"


def gather() -> dict:
    """抓三家傷病報告並合併。

    回傳 {player_key: {...}}，player_key 優先用 ESPN id，否則正規化姓名。
    每筆記錄各來源原始狀態、共識狀態、來源數（可信度）。
    """
    espn = espn_injuries()
    cbs = cbs_injuries()
    yahoo = yahoo_injuries()

    merged: dict[str, dict] = {}

    def ensure(key: str, name: str, espn_id: str | None = None):
        if key not in merged:
            merged[key] = {
                "key": key,
                "name": name,
                "espn_id": espn_id,
                "sources": {},
                "statuses": {},
                "details": {},
            }
        return merged[key]

    for rec in espn:
        name = rec.get("player") or ""
        key = rec.get("espn_id") or norm_name(name)
        item = ensure(key, name, rec.get("espn_id"))
        st = classify(rec.get("status"))
        item["sources"]["ESPN"] = rec.get("status") or ""
        item["statuses"]["ESPN"] = st
        item["details"]["ESPN"] = (rec.get("detail") or "")[:220]
        item["team"] = rec.get("team")
        item["date"] = rec.get("date")

    for src, rows in (("CBS", cbs), ("Yahoo", yahoo)):
        for rec in rows:
            name = rec.get("player") or ""
            key = norm_name(name)
            item = ensure(key, name)
            st = classify(rec.get("status") or rec.get("detail"))
            item["sources"][src] = rec.get("status") or ""
            item["statuses"][src] = st
            item["details"][src] = (rec.get("detail") or "")[:220]

    for item in merged.values():
        statuses = [s for s in item["statuses"].values() if s != "UNKNOWN"]
        if not statuses:
            item["consensus"] = "UNKNOWN"
        else:
            # 共識 = 最嚴重狀態（寧可少算，不要錯算上場）
            item["consensus"] = max(statuses, key=lambda s: SEVERITY.get(s, 0))
        item["n_sources"] = len(item["statuses"])
        item["n_agree"] = sum(1 for s in item["statuses"].values() if s == item["consensus"])
        item["conflict"] = len({s for s in statuses}) > 1
    return merged


def match_player(player: dict, consensus: dict) -> dict | None:
    """把名單中的球員對到傷病記錄。"""
    key = player.get("espn_id") or norm_name(player.get("name") or "")
    rec = consensus.get(key)
    if not rec:
        rec = consensus.get(norm_name(player.get("name") or ""))
    return rec
