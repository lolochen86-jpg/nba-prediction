"""Verify that the production domain serves this exact validated snapshot."""
import hashlib
import time
from pathlib import Path

import requests

BASE = "https://nba-prediction-00.pages.dev"
expected = Path("site/data/app.json").read_bytes()
for attempt in range(6):
    response = requests.get(BASE + "/data/app.json", headers={"Cache-Control": "no-cache"}, timeout=35)
    if response.ok and response.content == expected:
        break
    if attempt == 5:
        raise RuntimeError("Production app.json does not match the validated build")
    time.sleep(10)
for path in ("/", "/rookies", "/backtest", "/method", "/en/", "/en/rookies", "/en/backtest", "/en/method"):
    page = requests.get(BASE + path, timeout=35)
    page.raise_for_status()
    if 'id="manualUpdateBtn"' not in page.text:
        raise RuntimeError(f"Missing controls in {path}")
print("Production snapshot and 8 pages verified:", hashlib.sha256(expected).hexdigest())
