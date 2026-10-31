#!/usr/bin/env bash
# 一鍵更新：抓資料 → 跑模型 → 產生網站 → 部署到 Cloudflare Pages
# 用法：bash tools/update_and_deploy.sh
# 需要環境變數：CLOUDFLARE_API_TOKEN、CLOUDFLARE_ACCOUNT_ID
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="${CF_PROJECT:-nba-prediction-00}"
BRANCH="${CF_BRANCH:-main}"

echo "=== [1/3] 安裝 Python 依賴"
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo "=== [2/3] 抓資料並重算網站"
export NBA_CACHE="${NBA_CACHE:-$HOME/nba-cache}"
python3 -m pipeline.build

echo "=== [3/3] 部署到 Cloudflare Pages（專案 ${PROJECT}）"
if ! command -v wrangler >/dev/null 2>&1; then
  npx --yes wrangler@latest --version >/dev/null
  WRANGLER="npx --yes wrangler@latest"
else
  WRANGLER="wrangler"
fi

$WRANGLER pages deploy site \
  --project-name "$PROJECT" \
  --branch "$BRANCH" \
  --commit-dirty=true

echo "=== 完成：https://${PROJECT}.pages.dev"
