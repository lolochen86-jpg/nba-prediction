#!/usr/bin/env bash
# Cloudflare Pages 直傳部署（Direct Upload，不經 GitHub）
# 需要的環境變數：CLOUDFLARE_API_TOKEN、CLOUDFLARE_ACCOUNT_ID
set -euo pipefail
cd "$(dirname "$0")/.."

: "${CLOUDFLARE_API_TOKEN:?需要 CLOUDFLARE_API_TOKEN}"
: "${CLOUDFLARE_ACCOUNT_ID:?需要 CLOUDFLARE_ACCOUNT_ID}"

PROJECT="${CF_PROJECT:-nba-prediction}"
BRANCH="${CF_BRANCH:-main}"

if ! command -v wrangler >/dev/null 2>&1; then
  echo "[deploy] 安裝 wrangler…"
  npm install --no-fund --no-audit --prefix /home/user/.cfcli wrangler@latest >/dev/null 2>&1
  export PATH="/home/user/.cfcli/node_modules/.bin:$PATH"
fi

echo "[deploy] 上傳 site/ 到 Cloudflare Pages 專案 ${PROJECT}（分支 ${BRANCH}）"
wrangler pages deploy site \
  --project-name "$PROJECT" \
  --branch "$BRANCH" \
  --commit-dirty=true
