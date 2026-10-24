# -*- coding: utf-8 -*-
"""文字卡片渲染器: 一言签 → PNG (playwright)

1080x1350 (微博 4:5 标准), 七套配色按日轮换, 竖排大字 + 日期角标。
"""
import datetime
import os

# 七套主题(按星期轮换): (背景, 正文, 角标)
THEMES = [
    ("#F7F4EE", "#2F2B26", "#9C9284"),   # 一 · 米白暖灰
    ("#22302B", "#EDE8DD", "#7FA08F"),   # 二 · 墨绿
    ("#1E2A3A", "#E8EDF4", "#7E93B0"),   # 三 · 黛蓝
    ("#F5EBEA", "#3A2E2C", "#B08E88"),   # 四 · 藕粉
    ("#2B2B2B", "#EDEDED", "#8F8F8F"),   # 五 · 暖灰黑
    ("#F7F1E1", "#3B342A", "#B0A37E"),   # 六 · 鹅黄
    ("#2D2534", "#ECE6F2", "#9B8BB0"),   # 日 · 黛紫
]

_CSS = """
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 1080px; height: 1350px;
        background: {bg}; font-family: "Noto Sans SC", "PingFang SC",
        "Microsoft YaHei", sans-serif; position: relative; }}
.quote {{ position: absolute; left: 120px; right: 120px; top: 50%;
          transform: translateY(-50%);
          font-size: {fsize}px; line-height: 1.9; color: {fg};
          font-weight: 500; letter-spacing: 2px; }}
.mark {{ position: absolute; left: 120px; bottom: 96px;
         font-size: 30px; color: {sub}; letter-spacing: 8px; }}
.date {{ position: absolute; right: 120px; bottom: 96px;
         font-size: 30px; color: {sub}; letter-spacing: 3px; }}
.topline {{ position: absolute; left: 120px; top: 110px;
            width: 64px; height: 6px; background: {sub}; opacity: .55; }}
"""


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_quote_card(text: str, out_path: str, date_str: str = "") -> str:
    """一言卡片 → PNG。date_str: YYYY-MM-DD(决定配色轮换)"""
    if not date_str:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.date.fromisoformat(date_str).weekday()
    bg, fg, sub = THEMES[weekday]
    # 句子长度自适应字号
    n = len(text or "")
    if n <= 24:
        fsize = 64
    elif n <= 40:
        fsize = 54
    elif n <= 60:
        fsize = 46
    else:
        fsize = 40
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_CSS.format(bg=bg, fg=fg, sub=sub, fsize=fsize)}</style></head>
<body>
  <div class="topline"></div>
  <div class="quote">{_esc(text)}</div>
  <div class="mark">一 言</div>
  <div class="date">{date_str}</div>
</body></html>"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350})
        page.set_content(html)
        page.wait_for_timeout(400)
        page.screenshot(path=out_path, full_page=False)
        browser.close()
    print(f"[card] 卡片已渲染 → {os.path.basename(out_path)}")
    return out_path


if __name__ == "__main__":
    import sys
    render_quote_card(sys.argv[1] if len(sys.argv) > 1 else "测试一句话卡片",
                      "/tmp/quote_card_test.png")
