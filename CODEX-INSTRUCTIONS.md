# 給 Codex 的執行指令：NBA 預測網站上線與自動更新

> 這份文件是「照著打就能完成」的操作手冊。請依序執行，每一步都有預期輸出。
> 遇到不同結果時，先看最後的「常見錯誤對照表」，不要自行更改模型參數或資料源。

---

## 0. 目標

| 項目 | 內容 |
| --- | --- |
| 網站 | NBA 賽前預測 + 新人榜（4 個頁面，靜態網站） |
| 部署平台 | Cloudflare Pages，專案名稱 **`nba-prediction-00`** |
| 帳號 | Cloudflare Account ID `fccf86dabdc8bdbd5770ad7fcdb14b7d`（`Lolochen86@gmail.com's Account`） |
| 正式網址 | `https://nba-prediction-00.pages.dev` |
| 更新頻率 | 台灣時間 **07:00 / 14:00 / 21:00** |
| 專案根目錄 | 解壓後的 `nba-prediction/`（內含 `pipeline/`、`templates/`、`site/`…） |

網站每次建置都會即時抓取：ESPN API、Basketball-Reference、CBS Sports、Yahoo Sports（傷病三源交叉比對）、NBA CDN 大頭貼。**不需要任何付費 API。**

---

## 1. 環境需求

```bash
node -v      # 需要 >= 18（wrangler 用）
python3 -V   # 需要 >= 3.11
git --version
```

若缺少，macOS 用 `brew install node python@3.11`，Ubuntu 用 `sudo apt install nodejs npm python3.11 python3-pip`。

---

## 2. 解壓並安裝依賴

```bash
unzip nba-prediction-source.zip -d ~/nba-prediction
cd ~/nba-prediction

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3. 本機先跑一次，確認流程正常

```bash
export NBA_CACHE="$HOME/nba-cache"
python -m pipeline.build
```

**預期輸出**（數字會隨日期變動）：

```
[1/7] 抓取球隊與名單（球季 2027）…
[2/7] 球員 per-36 數據（Basketball-Reference）…
[3/7] 傷病三源交叉比對…
[4/7] 球隊統計與本季戰績…
[5/7] 今日賽程預測…
      完成 10 場
[6/7] 新人榜（一年級＋二年級）…
[7/7] 賽後回測評分…
[done] 10 場比賽、22 位新人
       更新 2026-10-31 07:33 (UTC+8)
```

檢查產出：

```bash
ls site/                    # 應該有 index.html rookies.html backtest.html method.html style.css data/
open site/index.html        # 或 xdg-open，確認畫面正常
```

> 若第 3 步失敗，**不要往下做**，直接回報錯誤訊息。

---

## 4. 建立 Cloudflare API 權杖

**必須是「使用者 API 權杖」**（值不是 `cfat` 開頭）。帳戶權杖打 Pages API 會回 `Authentication error 10000`。

1. 開 `https://dash.cloudflare.com/profile/api-tokens`（個人資料 → API 權杖）
2. **建立權杖** → 捲到底 **建立自訂權杖**
3. 名稱：`nba-prediction-deploy`
4. 權限加三列：

| 第 1 欄 | 第 2 欄 | 第 3 欄 |
| --- | --- | --- |
| 帳戶 Account | Cloudflare Pages | **編輯 Edit** |
| 帳戶 Account | 帳戶設定 Account Settings | 讀取 Read |
| 使用者 User | 使用者詳細資料 User Details | 讀取 Read |

5. 帳戶資源：**包括** → `Lolochen86@gmail.com's Account`
6. 到期：**無到期時間**
7. 建立 → 複製權杖值（只顯示一次）

設定環境變數（**不要寫進任何檔案或 commit**）：

```bash
export CLOUDFLARE_API_TOKEN="貼上權杖值"
export CLOUDFLARE_ACCOUNT_ID="fccf86dabdc8bdbd5770ad7fcdb14b7d"
```

**權杖由使用者本人提供，不可從文件、對話或任何 repo 取得。** 交付方式只有兩種：
1. 使用者在自己終端機先 `export CLOUDFLARE_API_TOKEN=...`，再啟動 Codex（子行程會繼承）
2. 使用者自行執行部署指令（見第 5 步），Codex 只負責檢查結果

若拿不到權杖：**跳過第 5、6 步**，只做第 1–3 步與第 7 步的本機驗收（`site/` 已可用），不要嘗試猜測或硬編碼任何權杖值。

---

## 5. 首次部署

```bash
# 5-1 驗證權杖
npx --yes wrangler@latest whoami
# 預期：列出 Account Name / Account ID，且沒有 "Unable to get membership roles" 錯誤

# 5-2 確認專案存在
npx --yes wrangler@latest pages project list
# 預期：看到 nba-prediction-00

# 5-3 部署
npx --yes wrangler@latest pages deploy site \
  --project-name nba-prediction-00 \
  --branch main \
  --commit-dirty=true
```

**預期輸出結尾**：

```
✨ Deployment complete! Take a peek over at https://xxxx.nba-prediction-00.pages.dev
```

驗證：

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://nba-prediction-00.pages.dev
curl -sL -o /dev/null -w "%{http_code}\n" https://nba-prediction-00.pages.dev/rookies
# 兩個都要是 200
```

> 若 `wrangler pages project list` 顯示找不到專案，先執行：
> `npx --yes wrangler@latest pages project create nba-prediction-00 --production-branch main`

---

## 6. 設定自動更新（三選一，建議方案 A）

### 方案 A：GitHub Actions（建議，電腦關機也會跑）

```bash
cd ~/nba-prediction
git init -b main
git add -A
git commit -m "init: NBA 預測網站"

# 建立 repo（需要 gh CLI 已登入：gh auth login）
gh repo create nba-prediction --public --source=. --remote=origin --push

# 設定 repo secrets
gh secret set CLOUDFLARE_API_TOKEN --body "貼上權杖值"
gh secret set CLOUDFLARE_ACCOUNT_ID --body "fccf86dabdc8bdbd5770ad7fcdb14b7d"

# 立刻手動觸發一次測試
gh workflow run update.yml
gh run list --limit 3
```

`.github/workflows/update.yml` 已包含排程 `cron: "0 23,6,13 * * *"`（= 台灣時間 07:00 / 14:00 / 21:00），會執行：
抓資料 → `python -m pipeline.build` → `wrangler pages deploy` → commit 回 repo。

> 注意：GitHub Actions 的 cron 是 UTC 時間，且免費方案在尖峰時段可能延遲 5–15 分鐘，屬正常。

**沒有 `gh` CLI 時的做法**（不需要安裝，全用網頁）：

```bash
cd ~/nba-prediction
git init -b main
git add -A
git commit -m "init: NBA 預測網站"
git remote add origin https://github.com/<你的帳號>/nba-prediction.git
```

1. 到 GitHub 網頁建一個**空的** public repo：`nba-prediction`（**不要**勾選 Add README，否則會 push 衝突）
2. 回終端機：`git push -u origin main`
3. 網頁進 repo → **Settings → Secrets and variables → Actions → New repository secret**，新增兩個：
   - `CLOUDFLARE_API_TOKEN`　→ 貼上權杖值
   - `CLOUDFLARE_ACCOUNT_ID` → `fccf86dabdc8bdbd5770ad7fcdb14b7d`
4. 網頁進 **Actions** 分頁 → 左側「更新 NBA 預測網站」→ 右側 **Run workflow** → 跑一次確認綠燈

### 方案 B：本機 cron / launchd（沒有 GitHub 時用）

```bash
chmod +x tools/update_and_deploy.sh
# 先手動跑一次確認可用
bash tools/update_and_deploy.sh
```

macOS 用 launchd（`~/Library/LaunchAgents/com.nba.update.plist`）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.nba.update</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>/Users/你的帳號/nba-prediction/tools/update_and_deploy.sh</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CLOUDFLARE_API_TOKEN</key><string>貼上權杖值</string>
    <key>CLOUDFLARE_ACCOUNT_ID</key><string>fccf86dabdc8bdbd5770ad7fcdb14b7d</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/tmp/nba-update.log</string>
  <key>StandardErrorPath</key><string>/tmp/nba-update.err</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.nba.update.plist
```

Linux 用 crontab（`crontab -e`）：

```cron
0 7,14,21 * * * cd $HOME/nba-prediction && CLOUDFLARE_API_TOKEN=xxx CLOUDFLARE_ACCOUNT_ID=fccf86dabdc8bdbd5770ad7fcdb14b7d NBA_CACHE=$HOME/nba-cache bash tools/update_and_deploy.sh >> /tmp/nba-update.log 2>&1
```

### 方案 C：Cloudflare 原生排程
**不可行，請勿嘗試。** Pages 直傳專案沒有 build hook、沒有 cron；Workers Cron 只能跑 JS，跑不了這條 Python 流程。這就是為什麼排程要放在 GitHub Actions 或本機。

---

## 7. 驗收清單

| # | 檢查 | 指令 / 方式 | 通過標準 |
| --- | --- | --- | --- |
| 1 | 首頁可開 | `curl -s -o /dev/null -w "%{http_code}" https://nba-prediction-00.pages.dev` | `200` |
| 2 | 四個頁面都可開 | 逐一 `curl -L` `/`、`/rookies`、`/backtest`、`/method` | 全部 `200` |
| 3 | 資料有內容 | `curl -s https://nba-prediction-00.pages.dev/data/app.json \| head -c 200` | 看到 `updated_tpe`、`games` |
| 4 | 今日場次數 | 同上，`games` 陣列長度 | 等於當天 NBA 場次數 |
| 4b | 新人榜非空 | `curl -s .../data/app.json` 看 `rookies.combined` 長度 | >= 10（若為 0，看 `br_fallback` 是否為 true） |
| 5 | 頁面顯示更新時間 | 開網站看頁首「最後更新」 | 與剛才建置時間一致（台灣時間） |
| 6 | 排程生效 | 隔天 07:00 後再看「最後更新」 | 時間有變 |
| 7 | 回測頁開始累積 | 開 `/backtest` | 「已評分場次」> 0（賽後才會有） |

---

## 8. 常見錯誤對照表

| 錯誤訊息 | 原因 | 解法 |
| --- | --- | --- |
| `Authentication error [code: 10000]`（Pages API） | 權杖不是「使用者權杖」或缺少 Pages 權限 | 重新建立使用者權杖，權限加 `Account › Cloudflare Pages › Edit` |
| `Unable to get membership roles` | 權杖缺 `User › User Details › Read` | 補上該權限，或重新建立權杖 |
| `ModuleNotFoundError: No module named 'jinja2'` | 沒啟用 venv 或沒安裝依賴 | `source .venv/bin/activate && pip install -r requirements.txt` |
| `[5/7] 完成 0 場` | 當天沒有比賽，或時區判斷到休兵日 | 正常現象，隔天恢復 |
| `requests.exceptions.ConnectionError`（某個來源） | 對方站台暫時阻擋 | 重跑一次；`build.sh` 會沿用快取。連續失敗才需處理 |
| `[done] ... 0 位新人` 且 BR 回 0 筆 | Basketball-Reference 封鎖機房／雲端 IP | **已內建備援**：偵測到少於 200 筆會自動改用 ESPN 逐場紀錄回推 per-36，重跑即可。若備援後仍 0 筆，代表 ESPN 也不通，檢查網路 |
| 部署成功但網址 522 | 專案沒有「正式環境」部署 | `wrangler pages deploy ... --branch main` 會產生 Production 部署 |
| 頁面樣式跑掉 | 只上傳了 zip 未解壓或上傳錯目錄 | `site/` 的內容要放在專案根目錄（`index.html` 在最上層） |

---

## 9. 不要做的事

- ❌ 不要把 `CLOUDFLARE_API_TOKEN` 寫進 repo、`.env` 或任何會被 commit 的檔案
- ❌ 不要修改 `pipeline/model.py` 的模型參數（κ=12、σ=10.3、主場 1.4）除非明確要求
- ❌ 不要改動 `--project-name nba-prediction-00`（改名等於換網址）
- ❌ 不要刪除 `data/predictions/`、`data/results/`（回測歷史，刪了命中率會歸零）
- ❌ 不要用 Selenium / Playwright 取代現有抓取（現有四個來源都可用，且已做快取與退路）

---

## 10. 專案結構速查

```
nba-prediction/
├── pipeline/
│   ├── sources.py     # 五個資料源抓取（ESPN / B-Ref / CBS / Yahoo / NBA CDN）
│   ├── injuries.py    # 三家傷病交叉比對 → 共識狀態 → 上場時間係數
│   ├── model.py       # 分鐘分配、球隊效率、蒙地卡羅、級距機率
│   ├── rookies.py     # 新人榜（GS/36）＋近 7 天進步榜
│   ├── backtest.py    # 預測快照存檔與賽後評分
│   └── build.py       # 主流程：抓資料 → 算 → 產生 site/
├── templates/         # 4 個頁面的 Jinja2 模板
├── static/style.css
├── site/              # 產出（部署這個目錄）
├── data/predictions/  # 每日預測快照（回測用，需保留）
├── data/results/      # 賽後評分結果（需保留）
├── tools/
│   ├── update_and_deploy.sh   # 一鍵：建置 + 部署
│   └── preview.py             # 產生單檔預覽
├── .github/workflows/update.yml
└── requirements.txt
```
