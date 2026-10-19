# -*- coding: utf-8 -*-
"""微博《AI 情报站》系列: aihot.news 公开 API → 微博资讯串烧

数据源: https://aihot.news/api/v1 (匿名只读, v2.0.0)
  主路: /items?mode=selected&window=24h&limit=20 → 24h 精选资讯(按 score 挑头部)
  降级: /hot-topics → 当前热点榜 Top10
资讯自带中文标题/摘要/来源, LLM 只做微博化润色(去AI味+节奏)。

礼貌条款: 帖尾注明"资讯整理自 AIHOT", 分类标签映射成中文。

防重: state.json weibo_ai_last_date 记录已发日期(每天最多一条)。
用法:
    python ai_news.py --dry-run
    python ai_news.py
    python ai_news.py --force
"""
import argparse
import datetime
import json
import os
import re
import sys
import time as _time
import traceback
import urllib.request
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from copywriter import (WEIBO_SYSTEM, _STYLE_RULES, _call_llm,
                        _extract_json, _repair_truncated_json)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

ACTOR_UA = "aihot-api/2.0.0 aihot-actor/weibo-agi-poster"

CAT_CN = {
    "ai-models": "模型", "ai-products": "产品", "industry": "行业",
    "paper": "论文", "tip": "教程", "opinion": "观点",
}

NUM_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
             6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- Step 1: 数据


def _get_json(url: str, timeout: int = 30, retries: int = 3) -> Dict:
    """aihot API GET(带匿名 actor UA, 官方礼貌要求)"""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ACTOR_UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip as _gzip
                import io as _io
                raw = _gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                _time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"aihot 请求失败: {url[:90]} ({last_err})")


def fetch_selected_news(want: int = 7) -> List[Dict]:
    """24h 精选资讯, 按 score 降序取头部 want 条"""
    d = _get_json("https://aihot.news/api/v1/items"
                  "?mode=selected&window=24h&limit=20")
    items = d.get("items") or []
    if not items:
        raise RuntimeError("精选列表为空")
    items.sort(key=lambda x: x.get("score") or 0, reverse=True)
    picked = []
    seen_titles = set()
    for it in items:
        t = (it.get("title") or "").strip()
        if not t or t in seen_titles:
            continue
        seen_titles.add(t)
        picked.append({
            "title": t,
            "summary": (it.get("summary") or "").strip(),
            "source": ((it.get("source") or {}).get("name") or "").strip(),
            "category": CAT_CN.get(it.get("category") or "", "资讯"),
            "url": ((it.get("links") or {}).get("aihot") or "").strip(),
            "original": ((it.get("links") or {}).get("original") or "").strip(),
            "score": it.get("score") or 0,
        })
        if len(picked) >= want:
            break
    if len(picked) < 4:
        raise RuntimeError(f"精选不足4条(只得{len(picked)})")
    return picked


def fetch_hot_topics(want: int = 6) -> List[Dict]:
    """降级数据源: 热点榜 Top N"""
    d = _get_json("https://aihot.news/api/v1/hot-topics")
    items = d.get("items") or []
    picked = []
    for it in items[:want]:
        picked.append({
            "title": (it.get("title") or "").strip(),
            "summary": "",
            "source": ((it.get("source") or {}).get("name") or "").strip(),
            "category": "热点",
            "url": ((it.get("links") or {}).get("aihot") or "").strip(),
            "original": ((it.get("links") or {}).get("original") or "").strip(),
            "score": it.get("rank") or 0,
            "source_count": it.get("sourceCount") or 0,
        })
    if len(picked) < 4:
        raise RuntimeError("热点榜条目不足")
    return picked


def fetch_news(want: int = 7) -> tuple:
    """主路精选 → 降级热点榜, 返回 (items, mode)"""
    try:
        return fetch_selected_news(want), "selected"
    except Exception as e:
        print(f"   [warn] 精选列表获取失败({e}), 降级用热点榜")
        return fetch_hot_topics(want), "hot-topics"


# ---------------------------------------------------------------- Step 2: LLM

AI_EXTRA_RULES = """
【AI 情报站特有红线(叠加在通用红线之上)】
- 事实铁律: 只能使用输入 summary/标题里的事实, 一个新事实都不许编;
  输入没有的信息(参数/数字)宁可不说
- 输入的中文摘要已经是事实基准, 你做的是"微博化改写":
  更短的句子、更口语的节奏、去掉新闻腔, 不是扩写
- 每条 55~90字(比 AGI 日报更短, 资讯快节奏)
- 禁新闻腔: "据悉""值得关注的是""引发了广泛关注"
- 话题标签我会自己加, 你不要在文案里写任何 # 标签
"""

_GEN_PROMPT = """你要发一条《AI 情报站》微博: 过去24小时 AI 圈最值得知道的资讯速览。
今天是{today}。

输入素材(JSON, 每条 title=标题, summary=事实基准摘要, source=信源, category=分类):
{sections_json}

输出 JSON:
{{
  "hook": "微博第一行钩子, 20~40字, 含至少一个具体细节(产品名/数字), 像朋友发微博的口吻",
  "items": [
    {{
      "num": 与输入一致的序号,
      "headline": "标题改写, ≤22字, 保留关键主体名",
      "summary": "微博化改写, 55~90字, 短句节奏, 事实不增不减",
      "tagline": "10~14字短标语, 长图卡片用",
      "img_points": ["长图卡片要点1, 8~16字", "长图卡片要点2, 8~16字"]
    }}
  ],
  "outro": "收尾, 30~60字, 平实收束或抛个讨论问题",
  "keywords": ["本期关键词3~5个, 每个2~6字"]
}}

{style_rules}
{extra_rules}"""

_REVIEW_TMPL = """下面是准备发到微博的《AI 情报站》文案(JSON)。请做"去AI味"终审编辑。

【终审要点】
1. 逐句检查写作红线, 有问题就重写该句
2. 事实核对: 与输入素材对照, 不许有素材之外的编造
3. 每条 summary 保持 55~90字, 微博短句节奏
4. 不要出现任何 # 话题标签

【输出】重写后的完整 JSON(结构不变), 不要其他文字。

【输入素材(事实基准)】
{slim}

【待审文案】
{draft}

{style_rules}"""


def generate_post_content(news: List[Dict]) -> Dict:
    today = datetime.date.today().isoformat()
    slim = [{"num": i + 1, "title": n["title"],
             "summary": n["summary"] or "(无摘要,从标题扩展)",
             "source": n["source"], "category": n["category"]}
            for i, n in enumerate(news)]
    prompt = _GEN_PROMPT.format(
        today=today,
        sections_json=json.dumps(slim, ensure_ascii=False, indent=1),
        style_rules=_STYLE_RULES, extra_rules=AI_EXTRA_RULES)

    data = None
    best_partial = None
    want = max(3, int(len(slim) * 0.7))
    for attempt in range(4):
        print(f"   [LLM] 生成文案中(第{attempt+1}次)...")
        raw = _call_llm(prompt, system=WEIBO_SYSTEM)
        data = _extract_json(raw)
        if data and data.get("items") and len(data["items"]) >= 3:
            break
        data = _repair_truncated_json(raw)
        if data and data.get("items"):
            data["items"] = [it for it in data["items"]
                             if (it.get("headline") or "").strip()
                             and (it.get("summary") or "").strip()]
        n_fix = len((data or {}).get("items") or [])
        if data and n_fix >= 3:
            if n_fix >= want:
                print(f"   [warn] JSON 被截断, 修复后得 {n_fix} 条(≥70%), 采用")
                break
            if not best_partial or n_fix > len(best_partial.get("items") or []):
                best_partial = data
            data = None
        data = None
        wait = 20 * (attempt + 1)
        print(f"   [warn] 输出不完整({len(raw)}字, 修复得{n_fix}条), {wait}s 后重试")
        _time.sleep(wait)
    if not data or not data.get("items"):
        if best_partial and len(best_partial.get("items") or []) >= 3:
            data = best_partial
        else:
            raise RuntimeError(f"LLM 输出解析失败(4次): {raw[:300]}")

    # 对齐
    if len(data["items"]) != len(slim):
        by_num = {it.get("num"): it for it in data["items"]}
        fixed = []
        for s in slim:
            it = by_num.get(s["num"])
            if it:
                it["num"] = s["num"]
                fixed.append(it)
        if len(fixed) < 3:
            raise RuntimeError("LLM 条目对齐后不足3条")
        data["items"] = fixed

    # 终审
    review = _call_llm(_REVIEW_TMPL.format(
        slim=json.dumps(slim, ensure_ascii=False, indent=1),
        draft=json.dumps(data, ensure_ascii=False, indent=1),
        style_rules=_STYLE_RULES), system=WEIBO_SYSTEM)
    fixed = _extract_json(review)
    if not (fixed and fixed.get("items")):
        fixed = _repair_truncated_json(review)
    if fixed and fixed.get("items") and len(fixed["items"]) == len(data["items"]):
        for a, b in zip(data["items"], fixed["items"]):
            fs = (b.get("summary") or "").strip()
            if len(fs) >= 40:
                a["summary"] = fs
            if (b.get("tagline") or "").strip():
                a["tagline"] = b["tagline"].strip()
            bpts = [str(p).strip() for p in (b.get("img_points") or [])
                    if str(p).strip()]
            if bpts:
                a["img_points"] = bpts[:2]
        if (fixed.get("hook") or "").strip() and len(fixed["hook"]) >= 12:
            data["hook"] = fixed["hook"].strip()
        if (fixed.get("outro") or "").strip():
            data["outro"] = fixed["outro"].strip()
        fkws = [str(k).strip() for k in (fixed.get("keywords") or [])
                if str(k).strip()]
        if fkws:
            data["keywords"] = fkws[:5]

    # 兜底
    for i, it in enumerate(data["items"]):
        if not (it.get("tagline") or "").strip():
            it["tagline"] = (it.get("headline") or "")[:13]
        pts = [str(p).strip() for p in (it.get("img_points") or [])
               if str(p).strip()]
        if not pts:
            s = (it.get("summary") or "").replace("\n", "")
            m = re.match(r"(.+?[。！？])", s)
            short = ((m.group(1) if m else s)[:16]) or "详见长图"
            pts = [short]
            src = news[i]["title"][:16] if i < len(news) else ""
            if src:
                pts.append(src)
        it["img_points"] = pts[:2]
        it.setdefault("category", news[i]["category"] if i < len(news) else "资讯")
    kws = [str(k).strip() for k in (data.get("keywords") or [])
           if str(k).strip()]
    if not kws:
        kws = list({n["category"] for n in news[:5]})[:4]
    data["keywords"] = kws[:5]
    return data


# --------------------------------------------------------- Step 3: 组装微博

def build_weibo_content(news: List[Dict], data: Dict) -> str:
    today = datetime.date.today()
    lines = []
    lines.append(f"#AI情报站# {today.month}月{today.day}日 · {len(data['items'])} 条 "
                 f"| {(data.get('hook') or '').strip()}")
    lines.append("")
    for it in data["items"]:
        n = it.get("num") or 0
        emoji = NUM_EMOJI.get(n, f"{n}.")
        lines.append(f"{emoji} {(it.get('headline') or '').strip()}")
        lines.append((it.get("summary") or "").strip())
        lines.append("")
    outro = (data.get("outro") or "").strip()
    if outro:
        lines.append(outro)
    lines.append("")
    lines.append("资讯整理自 AIHOT（aihot.news），每个工作日中午更新。")
    return "\n".join(lines).strip()


# ------------------------------------------------------------ Step 4: 主流程

def already_posted_today() -> bool:
    state = load_state()
    return state.get("weibo_ai_last_date") == _time.strftime("%Y-%m-%d")


def mark_posted(mblogid: str, content: str):
    state = load_state()
    state["weibo_ai_last_date"] = _time.strftime("%Y-%m-%d")
    hist = state.setdefault("weibo_ai_history", [])
    hist.append({"date": state["weibo_ai_last_date"], "mblogid": mblogid,
                 "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
                 "head": content[:60]})
    state["weibo_ai_history"] = hist[-30:]
    save_state(state)


def _cleanup_images(keep: int = 3):
    if not os.path.isdir(OUTPUT_DIR):
        return
    files = [os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
             if f.startswith("ai-") and f.endswith(".png")]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for p in files[keep:]:
        try:
            os.unlink(p)
        except OSError:
            pass


def run(dry_run: bool, force: bool, no_image: bool = False) -> bool:
    from weibo_client import WeiboClient
    from image_maker import render_ai_news_image

    print("=" * 62)
    print("微博《AI 情报站》")
    print("=" * 62)
    if already_posted_today() and not force:
        print("   今天已发布过, 跳过。")
        return False

    news, mode = fetch_news(want=7)
    print(f"   [数据源] {mode}: {len(news)} 条")
    for n in news[:5]:
        print(f"     · [{n['category']}] {n['title'][:36]}")

    data = generate_post_content(news)
    content = build_weibo_content(news, data)
    print(f"   正文 {len(content)} 字, {len(data['items'])} 条资讯")

    images: List[str] = []
    if not no_image:
        today = _time.strftime("%Y%m%d")
        out_png = os.path.join(OUTPUT_DIR, f"ai-{today}.png")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        render_ai_news_image(
            title="AI 情报站", items=data["items"], out_path=out_png,
            keywords=data.get("keywords"), date_str=_time.strftime("%Y-%m-%d"))
        images.append(out_png)

    with open(os.path.join(OUTPUT_DIR, f"ai-{_time.strftime('%Y%m%d')}.md"),
              "w", encoding="utf-8") as f:
        f.write(f"# 微博 AI 情报站 {_time.strftime('%Y-%m-%d')}\n\n"
                f"```\n{content}\n```\n")

    if dry_run:
        print("\n---- 干跑预览(正文) ----")
        print(content)
        print("---- 干跑结束, 未发布 ----")
        return False

    cfg = load_config()
    client = WeiboClient(cfg["weibo_cookie"])
    post = client.post(content, images)
    mark_posted(post["mblogid"], content)
    _cleanup_images()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-image", action="store_true")
    args = ap.parse_args()
    try:
        run(args.dry_run, args.force, args.no_image)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
