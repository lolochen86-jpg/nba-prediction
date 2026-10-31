"""Fail deployment when the generated snapshot violates acceptance checks."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Comment


def validate(site: Path = Path("site")) -> dict:
    data = json.loads((site / "data/app.json").read_text(encoding="utf-8"))
    built = datetime.fromisoformat(data["updated_utc"])
    board = data["rookies"]
    counts = board["counts"]
    if not (counts["rookies"] > 0 and counts["sophomores"] > 0):
        raise ValueError(f"Both rookie classes must be populated: {counts}")
    limit = 15 if built.month == 10 else 82
    maxima = {}
    for name in ("combined", "watch", "trend"):
        rows = board.get(name, [])
        if name == "combined" and not rows:
            raise ValueError("Empty combined rookie board")
        for player in rows:
            games = player.get("g")
            if not isinstance(games, (int, float)) or not 0 <= games <= limit:
                raise ValueError(f"Invalid season game count: {player.get('name')} g={games}, limit={limit}")
        maxima[name] = max((p["g"] for p in rows), default=0)
    for name in ("index", "rookies", "backtest", "method"):
        for prefix, lang in (("", "zh-Hant"), ("en/", "en")):
            html = (site / prefix / f"{name}.html").read_text(encoding="utf-8")
            soup = BeautifulSoup(html, "html.parser")
            if soup.html.get("lang") != lang or data["updated_tpe"] not in html:
                raise ValueError(f"Invalid page language/timestamp: {prefix}{name}")
            if not soup.find(id="manualUpdateBtn") or not soup.find(id="langEn"):
                raise ValueError(f"Missing update/language controls: {prefix}{name}")
            if lang == "en":
                for node in soup.find_all(string=True):
                    if isinstance(node, Comment) or node.parent.name in ("script", "style") or str(node).strip() == "中文":
                        continue
                    if re.search(r"[\u4e00-\u9fff]", str(node)):
                        raise ValueError(f"Untranslated English-page text in {name}: {str(node).strip()}")
            for tag in soup.select('script[src], link[rel="stylesheet"]'):
                asset = (site / prefix / tag.get("src", tag.get("href")).split("?")[0]).resolve()
                if not asset.is_relative_to(site.resolve()) or not asset.is_file():
                    raise ValueError(f"Missing asset in {prefix}{name}: {asset}")
    return {"status": "PASS", "updated_tpe": data["updated_tpe"], "counts": counts, "max_g": maxima, "bilingual_pages": 8}


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
