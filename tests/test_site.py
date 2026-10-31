import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from pipeline.build import render
from pipeline.i18n import english_page
from pipeline.validate import validate


ROOT = Path(__file__).resolve().parents[1]


class SiteTests(unittest.TestCase):
    def test_english_links_preserve_page_and_assets_resolve(self):
        for name in ("index", "rookies", "backtest", "method"):
            html = (ROOT / "site" / f"{name}.html").read_text(encoding="utf-8")
            en = BeautifulSoup(english_page(html, name), "html.parser")
            self.assertEqual(en.html["lang"], "en")
            self.assertEqual(en.find(id="langZh")["href"], f"../{name}.html")
            self.assertEqual(en.find(id="langEn")["href"], f"{name}.html")
            self.assertTrue(en.find("link", rel="stylesheet")["href"].startswith("../style.css"))
            self.assertTrue(en.find("script", src=True)["src"].startswith("../app.js"))

    def test_validation_rejects_previous_season_game_counts(self):
        payload = json.loads((ROOT / "site/data/app.json").read_text(encoding="utf-8"))
        payload["rookies"]["combined"][0]["g"] = 81
        with tempfile.TemporaryDirectory(prefix=".site-test-", dir=ROOT) as directory:
            site = Path(directory)
            (site / "data").mkdir()
            (site / "data/app.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid season game count"):
                validate(site)

    def test_fallback_and_nonempty_backtest_translate(self):
        payload = json.loads((ROOT / "site/data/app.json").read_text(encoding="utf-8"))
        payload["health"][1].update(name="ESPN 逐場（BR 備援）", role="BR 被封鎖，改用逐場紀錄回推 per-36")
        summary = {"games": 1, "winner_acc": 100, "home_bucket_acc": 0, "away_bucket_acc": 0,
                   "both_bucket_acc": 0, "mae_total": 10, "brier": 0.2}
        record = {"date": "2026-10-30", "away": "BOS", "home": "NY", "pred_away": 100,
                  "pred_home": 110, "act_away": 100, "act_home": 120, "winner_hit": True,
                  "both_bucket_hit": False, "home_bucket_hit": False, "away_bucket_hit": True,
                  "abs_err_total": 10}
        payload["backtest"] = {"summary": summary, "records": [record], "rolling7": summary, "rolling30": summary}
        original = copy.deepcopy(payload)
        with tempfile.TemporaryDirectory(prefix=".site-test-", dir=ROOT) as directory, patch("pipeline.build.SITE", directory):
            render(payload)
            site = Path(directory)
            (site / "data/app.json").write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate(site)["status"], "PASS")
            english = (site / "en/backtest.html").read_text(encoding="utf-8")
            self.assertIn("Rolling performance", english)
            self.assertIn("ESPN game logs (BR fallback)", english)
        self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()
