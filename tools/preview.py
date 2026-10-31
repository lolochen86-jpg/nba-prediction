"""產生單檔預覽（把四個頁面 + CSS 全部內嵌），方便在聊天視窗直接檢視成品。"""
from __future__ import annotations

import os
import re

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
OUT_DIR = os.environ.get("PREVIEW_OUT", os.path.join(ROOT, "..", "..", "files"))

PAGES = [
    ("index", "今日預測", "index.html"),
    ("rookies", "新人榜", "rookies.html"),
    ("backtest", "命中率回測", "backtest.html"),
    ("method", "方法與資料源", "method.html"),
]


def main() -> str:
    css = open(os.path.join(SITE, "style.css"), encoding="utf-8").read()
    tab_btns, tab_bodies = [], []

    for i, (key, label, filename) in enumerate(PAGES):
        html = open(os.path.join(SITE, filename), encoding="utf-8").read()
        soup = BeautifulSoup(html, "lxml")
        main = soup.find("main")
        body = main.decode_contents() if main else ""
        body = re.sub(r'<img ([^>]*?)src="(?!https?:|data:)', r'<img \1src="', body)
        tab_btns.append(
            f'<button class="ptab {"on" if i == 0 else ""}" data-t="{key}">{label}</button>'
        )
        hidden = "" if i == 0 else ' style="display:none"'
        tab_bodies.append(f'<section class="ppage" id="p-{key}"{hidden}>{body}</section>')

    header = BeautifulSoup(open(os.path.join(SITE, "index.html"), encoding="utf-8").read(), "lxml").find("header")
    health = header.decode_contents() if header else ""

    out = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HoopsLab 預覽</title><style>{css}
.pnav{{position:sticky;top:0;z-index:50;background:#0b1017;border-bottom:1px solid var(--line);display:flex;gap:.4rem;padding:.6rem 4vw;flex-wrap:wrap}}
.ptab{{border:1px solid var(--line2);background:#16202e;color:var(--dim);border-radius:999px;padding:.35rem .9rem;font-size:.8rem;font-weight:700;cursor:pointer;font-family:inherit}}
.ptab.on{{background:linear-gradient(120deg,var(--acc2),var(--acc));color:#0b1017;border-color:transparent}}
.preview-note{{font-size:.72rem;color:#67788f;padding:.4rem 4vw 0}}
</style></head><body>
<div class="pnav">{''.join(tab_btns)}</div>
<p class="preview-note">靜態預覽：頭像與隊徽來自 ESPN／NBA CDN，若此視窗未載入屬正常，部署後會正常顯示。</p>
{health}
{''.join(tab_bodies)}
<script>
document.querySelectorAll('.ptab').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.ptab').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.ppage').forEach(p => p.style.display = (p.id === 'p-' + b.dataset.t) ? '' : 'none');
  window.scrollTo(0, 0);
}}));
</script></body></html>"""

    out_dir = os.path.abspath(OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "nba-site-preview.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return path


if __name__ == "__main__":
    print(main())
