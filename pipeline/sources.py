"""NBA 資料源層：多重來源抓取 + 正規化。

來源（互相交叉比對）：
  1. ESPN API          - 賽程/比分、球隊名單、球員傷病、球隊統計、球員逐場紀錄
  2. Basketball-Reference - 全聯盟 per-36 球員數據（當季 + 前一季）
  3. CBS Sports        - 傷病報告（第 2 源）
  4. Yahoo Sports      - 傷病報告（第 3 源）
  5. NBA CDN           - 球員大頭貼（視覺資產）
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CACHE_DIR = os.environ.get("NBA_CACHE", "/tmp/nba-cache")
DEFAULT_TTL = int(os.environ.get("NBA_CACHE_TTL", "900"))

ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
ESPN_INJ = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
BR = "https://www.basketball-reference.com"
NBA_CDN = "https://cdn.nba.com/headshots/nba/latest/1040x760/{pid}.png"

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

# Basketball-Reference 與 ESPN 隊名縮寫差異
BR_TO_ESPN = {"BRK": "BKN", "CHO": "CHA", "PHO": "PHX", "NJN": "BKN", "NOH": "NOP", "SEA": "OKC"}


# --------------------------------------------------------------------------- #
# HTTP / 快取
# --------------------------------------------------------------------------- #
def _slug(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def fetch(url: str, ttl: int = DEFAULT_TTL, force: bool = False) -> str:
    """抓取網址內容，帶檔案快取。失敗時回退到過期快取（若有）。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, _slug(url) + ".txt")
    if not force and os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < ttl:
            return open(path, encoding="utf-8", errors="ignore").read()
    last_err = None
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=35)
            if r.status_code == 200 and r.text:
                with open(path, "w", encoding="utf-8", errors="ignore") as fh:
                    fh.write(r.text)
                return r.text
            last_err = RuntimeError(f"HTTP {r.status_code} for {url}")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(1.2 * (attempt + 1))
    if os.path.exists(path):  # 退回舊快取
        return open(path, encoding="utf-8", errors="ignore").read()
    raise last_err


def fetch_json(url: str, ttl: int = DEFAULT_TTL, force: bool = False) -> dict:
    return json.loads(fetch(url, ttl, force))


def norm_name(name: str) -> str:
    """正規化姓名：去重音、標點、後綴，用於跨來源比對。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- #
# 1. ESPN：球隊 / 賽程 / 名單 / 傷病 / 球隊統計 / 逐場
# --------------------------------------------------------------------------- #
def espn_teams() -> dict:
    data = fetch_json(f"{ESPN_SITE}/teams", ttl=6 * 3600)
    out = {}
    for sport in data.get("sports", []):
        for league in sport.get("leagues", []):
            for entry in league.get("teams", []):
                t = entry["team"]
                out[str(t["id"])] = {
                    "id": str(t["id"]),
                    "abbrev": t.get("abbreviation"),
                    "name": t.get("displayName"),
                    "short": t.get("shortDisplayName") or t.get("name"),
                    "location": t.get("location"),
                    "logo": (t.get("logos") or [{}])[0].get("href"),
                    "color": "#" + (t.get("color") or "1d4ed8"),
                }
    return out


def espn_scoreboard(dates: str | None = None, ttl: int = 600) -> list:
    """dates: 'YYYYMMDD' 或 'YYYYMMDD-YYYYMMDD'。"""
    url = f"{ESPN_SITE}/scoreboard" + (f"?dates={dates}" if dates else "")
    data = fetch_json(url, ttl=ttl)
    games = []
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        comps = comp.get("competitors") or []
        if len(comps) != 2:
            continue
        home = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
        away = next((c for c in comps if c.get("homeAway") == "away"), comps[1])
        status = (comp.get("status") or {}).get("type", {})
        games.append(
            {
                "event_id": ev.get("id"),
                "date_utc": ev.get("date"),
                "name": ev.get("name"),
                "status": status.get("name"),
                "completed": bool(status.get("completed")),
                "status_detail": (comp.get("status") or {}).get("type", {}).get("detail"),
                "venue": (comp.get("venue") or {}).get("fullName"),
                "home": _competitor(home),
                "away": _competitor(away),
            }
        )
    return games


def _competitor(c: dict) -> dict:
    t = c.get("team") or {}
    score = c.get("score")
    try:
        score = int(float(score)) if score not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    rec = {}
    for r in c.get("records", []) or []:
        if r.get("type") in ("total", "overall"):
            rec = r
            break
    return {
        "id": str(t.get("id")),
        "abbrev": t.get("abbreviation"),
        "name": t.get("displayName"),
        "short": t.get("shortDisplayName") or t.get("name"),
        "logo": (t.get("logo") or t.get("logos", [{}])[0].get("href") if t.get("logos") else t.get("logo")),
        "score": score,
        "winner": bool(c.get("winner")),
        "record": rec.get("summary"),
    }


def espn_rosters(teams: dict) -> dict:
    """回傳 {team_id: [player, ...]}；player 含 ESPN id、年資、大頭貼。"""
    out = {}
    for tid in teams:
        try:
            data = fetch_json(f"{ESPN_SITE}/teams/{tid}/roster", ttl=3 * 3600)
        except Exception:  # noqa: BLE001
            continue
        players = []
        for a in data.get("athletes", []) or []:
            if a.get("status", {}).get("type") == "inactive" and not a.get("fullName"):
                continue
            exp = (a.get("experience") or {}).get("years")
            pos = (a.get("position") or {}).get("abbreviation") or ""
            head = (a.get("headshot") or {}).get("href")
            players.append(
                {
                    "espn_id": str(a.get("id")),
                    "name": a.get("fullName") or a.get("displayName"),
                    "pos": pos,
                    "exp": exp if isinstance(exp, int) else None,
                    "headshot": head,
                    "jersey": a.get("jersey"),
                    "age": a.get("age"),
                    "salary": None,
                }
            )
        out[tid] = players
    return out


def espn_team_stats(teams: dict) -> dict:
    """球隊場均得分/助攻/籃板與 pace 代理值（每場回合數估計）。"""
    out = {}
    for tid in teams:
        try:
            data = fetch_json(f"{ESPN_SITE}/teams/{tid}/statistics", ttl=3 * 3600)
        except Exception:  # noqa: BLE001
            continue
        flat = {}
        for cat in (data.get("results") or {}).get("stats", {}).get("categories", []):
            for s in cat.get("stats", []):
                if s.get("value") is not None:
                    flat[s.get("name")] = s["value"]
        fga = flat.get("avgFieldGoalsAttempted") or 0
        fta = flat.get("avgFreeThrowsAttempted") or 0
        oreb = flat.get("avgOffensiveRebounds") or 0
        tov = flat.get("avgTurnovers") or 0
        poss = fga + 0.44 * fta - oreb + tov
        out[tid] = {
            "ppg": flat.get("avgPoints"),
            "fgm": flat.get("avgFieldGoalsMade"),
            "fga": fga,
            "fg3m": flat.get("avgThreePointFieldGoalsMade"),
            "fg3a": flat.get("avgThreePointFieldGoalsAttempted"),
            "ftm": flat.get("avgFreeThrowsMade"),
            "fta": fta,
            "ast": flat.get("avgAssists"),
            "tov": tov,
            "oreb": oreb,
            "reb": flat.get("avgRebounds"),
            "stl": flat.get("avgSteals"),
            "blk": flat.get("avgBlocks"),
            "ts_pct": _ts(flat),
            "poss": poss if poss > 0 else None,
            "games": flat.get("gamesPlayed") or 0,
        }
    return out


def _ts(flat: dict) -> float | None:
    pts, fga, fta = flat.get("avgPoints"), flat.get("avgFieldGoalsAttempted"), flat.get("avgFreeThrowsAttempted")
    if not pts or not fga:
        return None
    denom = 2 * (fga + 0.44 * (fta or 0))
    return pts / denom if denom else None


def espn_injuries() -> list:
    """ESPN 傷病名單（第 1 源）。"""
    data = fetch_json(ESPN_INJ, ttl=900)
    out = []
    for team in data.get("injuries", []) or []:
        for inj in team.get("injuries", []) or []:
            ath = inj.get("athlete") or {}
            out.append(
                {
                    "player": ath.get("displayName") or ath.get("fullName"),
                    "espn_id": str(ath.get("id")) if ath.get("id") else None,
                    "team": team.get("displayName"),
                    "status": inj.get("status"),
                    "detail": inj.get("shortComment") or inj.get("longComment"),
                    "date": inj.get("date"),
                    "source": "ESPN",
                }
            )
    return out


def current_season_year() -> int:
    """目前球季的結束年度（2026-27 球季 → 2027）。ESPN 的 season 參數用這個值。"""
    now = datetime.now(timezone.utc)
    return now.year + 1 if now.month >= 8 else now.year


def season_label(year: int) -> str:
    return f"{year - 1}-{str(year)[2:]}"


def espn_gamelog(athlete_id: str, season: int | None = None) -> list:
    """球員逐場紀錄（只回傳指定球季的例行賽）。

    season 一定要指定（例如 2027 = 2026-27 球季）。不指定時 ESPN 會回傳「最近有資料的球季」，
    對本季還沒出賽的球員就會抓到上一季（曾出現 81 場這種不可能的數字）。
    """
    season = season or current_season_year()
    try:
        data = fetch_json(f"{ESPN_WEB}/athletes/{athlete_id}/gamelog?season={season}", ttl=3600)
    except Exception:  # noqa: BLE001
        return []
    names = data.get("names") or []
    events = data.get("events") or {}
    rows = []
    seasons = data.get("seasonTypes") or []
    # 只取例行賽，且必須是「最新球季」。
    # 1) 不可退回最後一個分類 —— 那是熱身賽（Preseason），會把只打熱身賽的球員算成有例行賽數據。
    # 2) gamelog 會同時回傳多個球季（例如 2025-26 + 2026-27），舊寫法取第一個，
    #    對部分球員會抓到上一季（出現 40 場這種不可能的數字），必須取 displayName 最新的一組。
    want = season_label(season)
    regs = [
        s
        for s in seasons
        if "Regular" in (s.get("displayName") or "") and (s.get("displayName") or "").startswith(want)
    ]
    regs.sort(key=lambda s: s.get("displayName") or "", reverse=True)
    target = next(
        (s for s in regs if any(c.get("events") for c in s.get("categories", []) or [])),
        None,
    )
    if not target:
        return []
    for cat in target.get("categories", []) or []:
        for ev in cat.get("events", []) or []:
            eid = ev.get("eventId")
            meta = events.get(eid) or {}
            raw = dict(zip(names, ev.get("stats") or []))
            rows.append(
                {
                    "event_id": eid,
                    "date": meta.get("gameDate") or meta.get("date"),
                    "opponent": (meta.get("opponent") or {}).get("abbreviation"),
                    "stats": raw,
                }
            )
    return rows


# --------------------------------------------------------------------------- #
# 2 / 3 / 4. 交叉比對來源
# --------------------------------------------------------------------------- #
def br_per36(season_end_year: int) -> dict:
    """Basketball-Reference 全聯盟 per-36 數據。key = 正規化姓名。"""
    url = f"{BR}/leagues/NBA_{season_end_year}_per_minute.html"
    try:
        html = fetch(url, ttl=6 * 3600)
    except Exception:  # noqa: BLE001
        return {}
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="per_minute_stats")
    if not table:
        return {}
    out = {}
    for tr in table.select("tbody tr"):
        if tr.get("class") and "thead" in tr.get("class"):
            continue
        cells = {}
        for td in tr.find_all(["td", "th"]):
            stat = td.get("data-stat")
            if stat:
                cells[stat] = td.get_text(strip=True)
        name = cells.get("name_display")
        if not name:
            continue
        try:
            games = int(cells.get("games") or 0)
        except ValueError:
            games = 0
        def f(key):
            v = cells.get(key, "")
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        out[norm_name(name)] = {
            "name": name,
            "br_team": BR_TO_ESPN.get(cells.get("team_name_abbr", ""), cells.get("team_name_abbr", "")),
            "pos": cells.get("pos"),
            "age": f("age"),
            "g": games,
            "gs": f("games_started"),
            "mp": f("mp"),
            "mpg": (f("mp") / games) if games else 0.0,
            "pts36": f("pts_per_minute_36"),
            "reb36": f("trb_per_minute_36"),
            "oreb36": f("orb_per_minute_36"),
            "dreb36": f("drb_per_minute_36"),
            "ast36": f("ast_per_minute_36"),
            "stl36": f("stl_per_minute_36"),
            "blk36": f("blk_per_minute_36"),
            "tov36": f("tov_per_minute_36"),
            "pf36": f("pf_per_minute_36"),
            "fgm36": f("fg_per_minute_36"),
            "fga36": f("fga_per_minute_36"),
            "fg3m36": f("fg3_per_minute_36"),
            "fg3a36": f("fg3a_per_minute_36"),
            "ftm36": f("ft_per_minute_36"),
            "fta36": f("fta_per_minute_36"),
            "ts_pct": _ts_from36(f("pts_per_minute_36"), f("fga_per_minute_36"), f("fta_per_minute_36")),
        }
    return out


def _ts_from36(pts: float, fga: float, fta: float) -> float:
    denom = 2 * (fga + 0.44 * fta)
    return (pts / denom) if denom else 0.0


def espn_per36(pairs: list, workers: int = 8) -> dict:
    """用 ESPN 逐場紀錄回推 per-36（Basketball-Reference 無法取得時的備援）。

    pairs: [(espn_id, name), ...]。回傳格式與 br_per36() 相同，可直接混用。
    oreb/dreb 無法從 ESPN gamelog 取得，以 25% / 75% 拆分近似。
    """
    from concurrent.futures import ThreadPoolExecutor

    def pair_of(v):
        s = str(v or "")
        if "-" in s:
            a, b = s.split("-", 1)
            try:
                return float(a), float(b)
            except ValueError:
                return 0.0, 0.0
        try:
            return float(s), float(s)
        except ValueError:
            return 0.0, 0.0

    def minutes_of(v):
        s = str(v or "").strip()
        if not s:
            return 0.0
        if ":" in s:
            m, sec = s.split(":", 1)
            try:
                return float(m) + float(sec) / 60.0
            except ValueError:
                return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def one(item):
        espn_id, name = item
        logs = espn_gamelog(espn_id, season=current_season_year())
        if not logs:
            return None
        tot = {k: 0.0 for k in ("min", "pts", "reb", "ast", "stl", "blk", "tov", "pf", "fgm", "fga", "ftm", "fta")}
        games = 0
        for row in logs:
            st = row.get("stats") or {}
            mins = minutes_of(st.get("minutes"))
            if mins <= 0:
                continue
            games += 1
            fgm, fga = pair_of(st.get("fieldGoalsMade-fieldGoalsAttempted"))
            ftm, fta = pair_of(st.get("freeThrowsMade-freeThrowsAttempted"))
            tot["min"] += mins
            tot["pts"] += num(st.get("points"))
            tot["reb"] += num(st.get("totalRebounds"))
            tot["ast"] += num(st.get("assists"))
            tot["stl"] += num(st.get("steals"))
            tot["blk"] += num(st.get("blocks"))
            tot["tov"] += num(st.get("turnovers"))
            tot["pf"] += num(st.get("fouls"))
            tot["fgm"] += fgm
            tot["fga"] += fga
            tot["ftm"] += ftm
            tot["fta"] += fta
        if games < 1 or tot["min"] <= 0:
            return None

        def p36(key):
            return round(tot[key] / tot["min"] * 36.0, 2)

        ts = (tot["pts"] / (2 * (tot["fga"] + 0.44 * tot["fta"]))) if (tot["fga"] + 0.44 * tot["fta"]) else 0.0
        return norm_name(name), {
            "name": name,
            "br_team": None,
            "pos": None,
            "age": None,
            "g": games,
            "gs": 0.0,
            "mp": round(tot["min"], 1),
            "mpg": round(tot["min"] / games, 2),
            "pts36": p36("pts"),
            "reb36": p36("reb"),
            "oreb36": round(p36("reb") * 0.25, 2),
            "dreb36": round(p36("reb") * 0.75, 2),
            "ast36": p36("ast"),
            "stl36": p36("stl"),
            "blk36": p36("blk"),
            "tov36": p36("tov"),
            "pf36": p36("pf"),
            "fgm36": p36("fgm"),
            "fga36": p36("fga"),
            "ftm36": p36("ftm"),
            "fta36": p36("fta"),
            "ts_pct": round(ts, 4),
        }

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(one, pairs):
            if res:
                out[res[0]] = res[1]
    return out


def cbs_injuries() -> list:
    """CBS Sports 傷病報告（第 2 源）。"""
    try:
        html = fetch("https://www.cbssports.com/nba/injuries/", ttl=1800)
    except Exception:  # noqa: BLE001
        return []
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.select("table"):
        head = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")] or []
        if not any("player" in h for h in head):
            continue
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            name = tds[0].get_text(" ", strip=True)
            name = re.sub(r"^[A-Z]\.\s+", "", name)
            out.append(
                {
                    "player": name,
                    "status": tds[-1].get_text(" ", strip=True),
                    "detail": tds[-1].get_text(" ", strip=True),
                    "date": tds[2].get_text(" ", strip=True),
                    "source": "CBS",
                }
            )
    return out


def yahoo_injuries() -> list:
    """Yahoo Sports 傷病報告（第 3 源）。"""
    try:
        html = fetch("https://sports.yahoo.com/nba/injuries/", ttl=1800)
    except Exception:  # noqa: BLE001
        return []
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.select("table"):
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            out.append(
                {
                    "player": tds[0].get_text(" ", strip=True),
                    "status": tds[2].get_text(" ", strip=True),
                    "detail": tds[2].get_text(" ", strip=True),
                    "date": tds[3].get_text(" ", strip=True) if len(tds) > 3 else "",
                    "source": "Yahoo",
                }
            )
    return out


def headshot_url(espn_id: str | None, fallback_name: str = "") -> str:
    if espn_id:
        return f"https://a.espncdn.com/i/headshots/nba/players/full/{espn_id}.png"
    return ""
