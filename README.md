# HoopsLab — NBA 賽前預測 + 新人榜

以「今天真的會上場的球員」為基礎的 NBA 賽前預測網站，加上一年級／二年級新人排行。
提供中文與英文版本，右上角可切換並記住語言。GitHub workflow 已設定台灣時間 07:00 / 14:00 / 21:00 排程；執行部署前必須先設定下方 Cloudflare secret。

## 網站內容

| 頁面 | 內容 |
| --- | --- |
| `/` | 今日全部比賽：預測比分、5 分一級的得分級距機率、不讓分勝率、缺陣影響、預期輪替 |
| `/rookies` | 一年級＋二年級合併排行（Game Score / 36）、近 7 天進步榜、觀察名單 |
| `/backtest` | 預測存檔與賽後評分：勝負命中率、級距命中率、總分 MAE、Brier 分數 |
| `/method` | 模型流程、資料源交叉比對狀態、更新時程、已知限制 |

## 資料源（互相交叉比對）

1. **ESPN API** — 賽程、比分、球隊名單（年資／大頭貼）、球隊統計、球員逐場紀錄
2. **Basketball-Reference** — 全聯盟 per-36 球員數據（當季＋前一季）
3. **CBS Sports** — 傷病報告
4. **Yahoo Sports** — 傷病報告
5. **NBA CDN** — 球員大頭貼

傷病採三源交叉比對，取最嚴重狀態為共識（寧可少算，不要錯算上場）：

| 狀態 | 上場時間係數 |
| --- | --- |
| Out / Suspended | 0% |
| Doubtful | 15% |
| Questionable | 50% |
| Day-to-day | 75% |
| Probable | 95% |

## 模型

1. 名單 → 剔除不能上場者
2. per-36 數據依出賽場次向「前一季」做貝氏收縮（k = 12 場）
3. 240 分鐘分配給 8–11 人輪替（權重＝平常上場時間 × 可用性，單人上限 40 分鐘）
4. 可用性指數＝今天陣容預期得分 ÷ 全員健康預期得分
5. 預期得分 = 預期回合數 × (進攻效率 × 可用性)^0.58 × (對手防守效率)^0.42 / 100，主場 ±1.4 分
6. σ = 10.3 + 傷病不確定性 + 開季小樣本懲罰（8–15 分）
7. 20,000 次蒙地卡羅 → 勝率、5 分級距機率、最可能比分

## 本機執行

```bash
pip install -r requirements.txt
python -m pipeline.build            # 完整建置（含賽後評分）
python -m pipeline.build --no-grade # 只跑預測
python -m pipeline.validate          # 驗證兩個新人年級、場次與八個中英文頁面
python -m unittest discover -s tests -v
```

輸出在 `site/`，直接用瀏覽器開 `site/index.html` 即可。

## 中英文與手動更新

- 中文：`https://nba-prediction-00.pages.dev/`
- English: `https://nba-prediction-00.pages.dev/en/`
- 各頁面右上角的「中文 / English」會保留目前頁面，語言偏好儲存在本機瀏覽器。
- 「手動更新資料 / Update data」會展開更新面板。按 Open GitHub，使用有此 repo 寫入權限的帳號，選 `main` 再按 **Run workflow**。
- 網站只讀取公開的執行狀態，不持有 GitHub 或 Cloudflare 權杖。流程成功與新快照實際上線會分別顯示；新快照可按「載入新資料」。
- 「重新整理 / Reload page」只載入現有資料，不會啟動重算。

## Cloudflare Pages 與 GitHub Actions 設定

1. 在 GitHub repo **Settings → Secrets and variables → Actions** 新增 `CLOUDFLARE_API_TOKEN`。
2. 權杖需有此 Cloudflare 帳戶的 **Cloudflare Pages → Edit** 權限。請透過 GitHub Secrets 填入，不寫進程式、JSON 或網頁。
3. 帳戶 ID 已在 workflow 提供預設值；如需覆寫，可設定 `CLOUDFLARE_ACCOUNT_ID` secret。
4. 開啟 **Actions → 更新 NBA 預測網站 → Run workflow**，選 `main` 執行。
5. 手動執行使用全新的資料快取；排程執行則沿用快取。建置後會跑測試與資料驗證，通過才部署 `nba-prediction-00`，並驗證正式站 JSON 與八個頁面。

排程由 `.github/workflows/update.yml` 控制。GitHub 排程可能延遲；以 workflow 執行紀錄與網站「最後更新」為準。

本機已授權 Wrangler 時也可部署：

```bash
npx --yes wrangler@latest pages deploy site --project-name nba-prediction-00 --branch main --commit-dirty=true
```

## 資料夾結構

```
pipeline/      抓資料、模型、新人榜、回測、網站產生
templates/     Jinja2 頁面模板
static/        樣式表、語言記憶與手動更新狀態介面
site/          Cloudflare Pages 部署目錄（含 en/ 英文頁）
data/predictions/  每次更新的預測快照（回測用，需進版控）
data/results/      賽後評分結果（回測用，需進版控）
tests/         語言連結與資料驗證回歸測試
```

> 免責：所有數字為模型估計值，僅供研究與討論，不構成任何投注建議。
