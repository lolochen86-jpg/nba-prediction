# HoopsLab — NBA 賽前預測 + 新人榜

以「今天真的會上場的球員」為基礎的 NBA 賽前預測網站，加上一年級／二年級新人排行。
每天自動更新三次（台灣時間 07:00 / 14:00 / 21:00），網站上另有手動更新按鈕。

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
```

輸出在 `site/`，直接用瀏覽器開 `site/index.html` 即可。

## 部署到 Vercel

1. 把這個資料夾推上 GitHub（private 也可以）。
2. GitHub → Settings → Actions → General，確認 Workflow permissions 為 **Read and write**。
3. Vercel → Add New Project → 匯入該 repo（framework 選 **Other**，root 保持預設）。
   專案已附 `vercel.json`，`outputDirectory` 指向 `site/`，不需要建置指令。
4. 在 Vercel 專案 → Settings → Environment Variables 加入：
   - `GITHUB_TOKEN`：fine-grained PAT，權限 `Actions: Read and write`（僅此 repo）
   - `GITHUB_REPO`：`<你的帳號>/<repo 名稱>`
   - `GITHUB_WORKFLOW`（選填）：預設 `update.yml`
5. 重新部署一次，網站右上角的「手動更新」按鈕即可用。

排程由 `.github/workflows/update.yml` 控制，改 `cron` 即可調整更新時間（UTC 時間）。

## 資料夾結構

```
pipeline/      抓資料、模型、新人榜、回測、網站產生
templates/     Jinja2 頁面模板
static/        樣式表
site/          產出的靜態網站（Vercel 的 outputDirectory）
data/predictions/  每次更新的預測快照（回測用，需進版控）
data/results/      賽後評分結果（回測用，需進版控）
api/refresh.js 手動更新 API（Vercel serverless function）
```

> 免責：所有數字為模型估計值，僅供研究與討論，不構成任何投注建議。
