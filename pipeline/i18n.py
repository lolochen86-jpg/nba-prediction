"""Generate complete English pages from the shared, rendered Chinese templates."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment


TRANSLATIONS = {
    "NBA 賽前預測": "NBA pregame predictions",
    "今日賽前預測": "Today's predictions",
    "今日預測": "Predictions",
    "新人榜": "Rookie rankings",
    "命中率回測": "Backtesting",
    "方法與資料源": "Method & sources",
    "最後更新": "Last updated",
    "（台灣時間）· 球季": " (Taipei) · Season",
    "（美東球日）": "(US Eastern game date)",
    "語言": "Language",
    "手動更新資料": "Update data",
    "手動更新": "Manual update",
    "更新資料": "Update data",
    "重新整理": "Reload page",
    "重新載入本頁": "Reload this page",
    "更新方式": "How updates work",
    "使用你的 GitHub 帳號啟動更新：開啟下方連結，選 main 分支，再按 Run workflow。系統會重新抓取資料、驗證新人榜並部署；完成後此頁會提示載入新資料。": "Start an update with your GitHub account: open the link below, select the main branch, then choose Run workflow. The workflow fetches fresh data, validates the rookie rankings and deploys the site. This page will tell you when new data is live.",
    "開啟 GitHub · Run workflow ↗": "Open GitHub · Run workflow ↗",
    "查看執行紀錄 ↗": "View run logs ↗",
    "讀取最近一次更新狀態…": "Checking the latest update…",
    "只有擁有儲存庫寫入權限的 GitHub 帳號可以啟動更新。重新整理只會載入現有資料。": "Only GitHub accounts with write access to this repository can start updates. Reloading the page only loads the existing snapshot.",
    "賽程・名單・球隊數據": "Schedules, rosters & team statistics",
    "per-36 球員數據": "Player statistics per 36 minutes",
    "傷病報告": "Injury reports",
    "球員大頭貼": "Player headshots",
    "ESPN 逐場（BR 備援）": "ESPN game logs (BR fallback)",
    "BR 被封鎖，改用逐場紀錄回推 per-36": "BR unavailable; per-36 statistics calculated from game logs",
    "三源傷病報告比對後不一致的球員數": "Players with conflicting reports across the three injury sources",
    "傷病衝突": "Injury conflicts",
    "資料來源：ESPN · Basketball-Reference · CBS Sports · Yahoo Sports · NBA CDN（多重來源交叉比對）。": "Sources: ESPN · Basketball-Reference · CBS Sports · Yahoo Sports · NBA CDN (cross-checked across sources).",
    "所有數字為模型估計值，僅供研究與討論，不構成任何投注建議。": "All figures are model estimates for research and discussion, and are not betting advice.",
    "建置時間": "Snapshot built",
    "UTC · 每次更新自動重新抓取名單、傷病與 per-36 數據後重算。": "UTC · Each update fetches rosters, injury reports and per-36 statistics, then recalculates the model.",
    "NBA 賽前預測：依實際會上場球員推算兩隊得分級距與不讓分勝率，附新人（一年級＋二年級）每 36 分鐘排行榜。": "NBA pregame predictions based on available lineups: scoring ranges, straight-up win probabilities and per-36 rankings for rookies and sophomores.",
    "一年級＋二年級合併": "Rookies & sophomores combined",
    "排名用": "Ranked by",
    "Game Score / 36 分鐘": "Game Score / 36 minutes",
    "（Hollinger Game Score 標準化到 36 分鐘），避免上場時間多寡直接決定名次。右側另有「近 7 天進步榜」，看誰正在升溫。": " (Hollinger Game Score normalized to 36 minutes), so playing time alone does not determine rank. The seven-day improvement list highlights players who are trending upward.",
    "一年級（達標）": "Qualified rookies",
    "二年級（達標）": "Qualified sophomores",
    "進步榜天數": "Trend window (days)",
    "綜合排行": "Combined rankings",
    "出賽 ≥3 場、平均 ≥8 分鐘": "At least 3 games & 8 minutes per game",
    "全部": "All",
    "一年級": "Rookie",
    "二年級": "Sophomore",
    "球員": "Player",
    "年級": "Class",
    "近 7 天進步榜": "Seven-day improvement",
    "GS/36 變化": "GS/36 change",
    "近期無足夠出賽樣本。": "Not enough recent games to calculate trends.",
    "觀察名單": "Watch list",
    "樣本不足": "Small sample",
    "數據為每 36 分鐘。": "Statistics per 36 minutes. ",
    "依「實際會上場的球員」推算兩隊得分，換算成 5 分一級的得分級距與": "Scores are estimated from available lineups, then converted into five-point scoring ranges and ",
    "不讓分勝率": "Straight-up win probability",
    "。傷病、停賽、個人因素缺陣者一律先從陣容剔除，其分鐘數自動分配給替補。": ". Players absent through injury, suspension or personal reasons are removed; their minutes are redistributed to available teammates.",
    "今日場次": "Games today",
    "聯盟場均得分": "League points per game",
    "聯盟場均回合": "League possessions per game",
    "今日沒有排定比賽": "No games scheduled today",
    "NBA 休兵日或球季尚未開打。下一次更新會自動抓取新的賽程。": "It may be an off day or the season has not started. The next update will fetch the latest schedule.",
    "已結束": "Final",
    "進行中": "Live",
    "未開賽": "Pregame",
    "預測比分（客 : 主）": "Predicted score (away : home)",
    "預期分差": "Expected margin",
    "信心": "Confidence",
    "得分級距": "Scoring range",
    "預測總分": "Predicted total",
    "兩隊級距同時命中": "Both scoring ranges hit",
    "最可能比分": "Most likely score",
    "預期輪替與分鐘分配": "Expected rotation & minutes",
    "來源不一致": "Sources disagree",
    "主要輪替無傷病回報。": "No injuries reported for the main rotation.",
    "模型假設：球員 per-36 產出可轉移、缺陣分鐘由替補吸收且效率下降、主場優勢 1.4 分。實際傷病名單以開賽前 30 分鐘官方公布為準，本站每次更新都會重抓。": "Model assumptions: per-36 production transfers across minutes, replacements absorb unavailable minutes with lower efficiency, and home advantage is 1.4 points. Check official injury reports 30 minutes before tipoff. Reports are fetched again during each update.",
    "每一次更新都會把當日預測存檔；比賽結束後自動用官方比分評分，不做任何事後修改。全部紀錄公開，含失準的場次。": "Each update archives predictions. Completed games are graded against official scores. Published results include incorrect predictions as well as correct ones.",
    "已評分場次": "Graded games",
    "勝負命中率": "Winner accuracy",
    "總分平均誤差": "Mean total-score error",
    "回測從今天開始累積": "Backtesting starts with saved predictions",
    "為了不做事後校準（避免後見之明偏誤），系統只記錄「更新當下」的預測，等比賽結束後再評分。目前還沒有已完成的比賽，下一次更新後就會出現第一批成績。": "To avoid hindsight calibration, predictions are saved at update time and graded after games finish. There are currently no graded games; results will appear after a subsequent update processes completed games.",
    "勝負命中": "Winner accuracy",
    "主隊級距命中": "Home range accuracy",
    "客隊級距命中": "Away range accuracy",
    "兩隊同時命中": "Both ranges correct",
    "總分 MAE": "Total-score MAE",
    "Brier 分數": "Brier score",
    "越低越好": "Lower is better",
    "近期場次": "Recent games",
    "日期": "Date",
    "對戰": "Matchup",
    "預測": "Predicted",
    "實際": "Actual",
    "勝負": "Winner",
    "級距": "Range",
    "誤差": "Error",
    "滾動表現": "Rolling performance",
    "近 7 天": "Last 7 days",
    "近 30 天": "Last 30 days",
    "兩隊級距": "Both ranges",
    "更新流程：抓名單 → 比對傷病 → 更新 per-36 數據 → 分配上場分鐘 → 算兩隊得分 → 蒙地卡羅出勝率與級距 → 產生網頁 → 部署。": "Update pipeline: fetch rosters → reconcile injuries → update per-36 statistics → allocate minutes → estimate scores → simulate win probabilities and scoring ranges → generate pages → deploy.",
    "預測流程": "Prediction pipeline",
    "可用球員名單": "Available roster",
    "— ESPN 球隊名單（含年資、位置、大頭貼），只算「今天真的能上場的人」。": "— ESPN team rosters include experience, position and headshots; only available players enter the lineup.",
    "傷病剔除": "Injury adjustments",
    "— ESPN／CBS／Yahoo 三份傷病報告交叉比對，取最嚴重狀態為共識：": "— Injury reports from ESPN, CBS and Yahoo are compared; the most restrictive reported status determines availability:",
    "Out / Suspended → 0 分鐘": "Out / Suspended → 0 minutes",
    "。三源不一致時在卡片上標記": ". Conflicting reports are flagged on the game card with",
    "球員強度": "Player strength",
    "— Basketball-Reference 當季 per-36 數據，依出賽場次向「前一季 per-36」做貝氏收縮（k=12 場），避免開季小樣本爆衝。": "— Current-season Basketball-Reference per-36 statistics are shrunk toward previous-season values (k=12 games) to reduce early-season small-sample volatility. Missing current players are supplemented with current-season ESPN regular-season logs.",
    "分鐘分配": "Minutes allocation",
    "— 以「每分鐘潛在產出 × per-36 得分權重」把 240 分鐘分給可用球員，單人上限 40 分鐘。缺陣者的分鐘自然轉給替補，替補效率較低也一併反映。": "— Allocate 240 team minutes using potential output per minute and scoring weights, capped at 40 minutes per player. Unavailable minutes shift to replacements, including their lower projected efficiency.",
    "球隊效率": "Team efficiency",
    "— 用「可用陣容預期得分 ÷ 整季陣容預期得分」得到可用性指數，乘上收縮後的進攻效率，再與對手防守效率幾何混合（0.58／0.42），得到每次球權預期得分。": "— Available-lineup scoring divided by full-lineup scoring produces an availability index. Adjusted offensive efficiency is geometrically blended with opposing defensive efficiency (0.58 / 0.42) to estimate points per possession.",
    "比賽預測": "Game prediction",
    "— 預期回合數 × 每回合效率 = 預期得分；主場 ±1.4 分。": "— Expected possessions × points per possession gives expected points, with a ±1.4-point home-court adjustment.",
    "不確定性": "Uncertainty",
    "— σ = 10.3 分 + 傷病不確定性 + 開季小樣本懲罰（上限 15 分）。": "— σ = 10.3 points plus injury uncertainty and an early-season small-sample penalty, capped at 15 points.",
    "蒙地卡羅": "Monte Carlo simulation",
    "— 20,000 次模擬 → 不讓分勝率、各 5 分級距機率、最可能比分。": "— 20,000 simulations produce straight-up win probabilities, five-point scoring-range probabilities and the most likely score.",
    "得分級距怎麼看": "Reading scoring ranges",
    "級距固定以 5 分為單位：101–105、106–110、111–115…。卡片上每隊列出機率最高的四個級距，並標出最可能的一格。兩隊級距是分開算的，所以「兩隊同時命中」的機率會低於單隊命中率，回測頁也分開統計。": "Scoring ranges use five-point intervals: 101–105, 106–110, 111–115, etc. Each card shows the four most likely ranges for each team. Hitting both teams' ranges is less likely than hitting one; backtesting reports these separately.",
    "新人榜指標": "Rookie ranking metrics",
    "一年級與二年級合併排名，用每 36 分鐘的 Game Score 標準化，避免上場時間多的人自動第一。": "Rookies and sophomores are ranked together by Game Score per 36 minutes so playing time alone does not determine rank.",
    "則比較「近 7 天 GS/36」與「本季 GS/36」，取進步幅度前 15 名，樣本需至少 2 場。": "compares GS/36 over the last seven days with season GS/36, showing the 15 biggest improvements with at least two recent games.",
    "資料源交叉比對": "Cross-checking sources",
    "無法取得": "Unavailable",
    "本站目前是": "This site serves a",
    "靜態快照": "static snapshot",
    "：每次更新都重新抓名單、三家傷病報告與 per-36 數據，整份重算後重新部署。頁面上方的「最後更新」就是這份快照的產生時間。": ": each update fetches rosters, three injury feeds and per-36 statistics, recalculates the model and redeploys. Last updated at the top is the snapshot's generation time.",
    "點「手動更新資料」→ GitHub → Run workflow": "Select Update data → GitHub → Run workflow",
    "台灣時間（可設定自動）": "Taipei time (scheduled workflow)",
    "台灣時間（開賽前最終版，可設定自動）": "Taipei time (scheduled pregame update)",
    "GitHub 更新流程需要在儲存庫 Secrets 設定 CLOUDFLARE_API_TOKEN（Cloudflare Pages 編輯權限）。手動更新會使用全新快取重新抓取資料；驗證失敗時不會部署。": "The GitHub workflow requires CLOUDFLARE_API_TOKEN in repository Secrets with Cloudflare Pages edit access. Manual updates use a fresh cache to fetch current data. Failed validation stops deployment.",
    "已知限制": "Known limitations",
    "沒有使用盤口／賠率資料，純粹由陣容與效率推導。": "No betting lines or odds are used; predictions are based on lineups and efficiency.",
    "不看背靠背、長途客場、輪休（load management）等未公布資訊。": "Back-to-back games, travel and unannounced load management are not modeled.",
    "開季前 10 場樣本偏小，σ 會自動放大、信心指數下降。": "Samples are small during the first 10 games; uncertainty increases and confidence falls.",
    "交易／雙向合約球員若 BR 尚無當季數據，會以聯盟平均或前一季代入。": "Where current data are unavailable, traded or two-way players may use prior-season statistics or league-average estimates.",
    "手動": "Manual",
    "分": "points",
}


def translate_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    # Whole sentences first; fragments then cover dynamic counts and labels.
    for zh, en in sorted(TRANSLATIONS.items(), key=lambda pair: -len(pair[0])):
        if zh in text:
            text = text.replace(zh, en)
    text = re.sub(r"缺陣與上場狀態（(\d+) 位影響輪替）", r"Absences & availability (\1 rotation players affected)", text)
    text = re.sub(r"預估少 ([\d.]+) points（可用性 ([\d.]+)%）", r"Estimated loss: \1 points (availability \2%)", text)
    text = re.sub(r"影響 −([\d.]+) points", r"Impact −\1 points", text)
    text = re.sub(r"近 (\d+) 場", r"last \1 games", text)
    text = re.sub(r"(\d+) 場", r"\1 games", text)
    text = re.sub(r"(.+) 勝$", r"\1 win", text)
    text = re.sub(r"傷病記錄本輪：ESPN (\d+) 筆、CBS (\d+) 筆、Yahoo (\d+) 筆；比對衝突 (\d+) 位。",
                  r"Injury reports: ESPN \1, CBS \2, Yahoo \3; \4 conflicting players.", text)
    text = text.replace("。", ".").replace("、", ", ")
    return (" " if value[:1].isspace() else "") + text + (" " if value[-1:].isspace() else "")


def english_page(html: str, page: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    soup.html["lang"] = "en"
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment) or node.parent.name in ("script", "style"):
            continue
        if re.search(r"[\u4e00-\u9fff]", str(node)) and str(node).strip() != "中文":
            node.replace_with(translate_text(str(node)))
    for tag in soup.find_all(True):
        for attr in ("title", "aria-label", "content", "alt"):
            if isinstance(tag.get(attr), str) and re.search(r"[\u4e00-\u9fff]", tag[attr]):
                tag[attr] = translate_text(tag[attr])
    for tag in soup.select('link[rel="stylesheet"]'):
        tag["href"] = "../" + tag["href"]
    for tag in soup.select('script[src]'):
        tag["src"] = "../" + tag["src"]
    zh, en = soup.find(id="langZh"), soup.find(id="langEn")
    zh["href"], en["href"] = f"../{page}.html", f"{page}.html"
    zh.attrs.pop("aria-current", None)
    en["aria-current"] = "true"
    return str(soup)
