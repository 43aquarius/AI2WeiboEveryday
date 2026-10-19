# -*- coding: utf-8 -*-
"""微博《AGI 日报》系列: 腾讯研究院 AI 速递(微信合集页实时源) → 微博图文

与小黑盒版同源同数据, 但微博形态:
  - 开头 #AGI日报# 话题标签, 长文自动折叠全文可见
  - 每条新闻 90~130 字(比小黑盒版精炼), 不放微信原文链接
    (微博对站外链接敏感, 且 feed 里链接观感差)
  - 配 1 张长图(微博版式, 4 主题按期号轮换)

⚠ 内容红线: 全文不出现 ima/知识库/腾讯研究院, 只说"数据来源于网络整理"。
防重: state.json weibo_agi_last_issue 记录已发期号。

用法:
    python agi_daily.py --dry-run   # 只构造不发布
    python agi_daily.py             # 最新期未发过时发布
    python agi_daily.py --force     # 忽略防重强制发
"""
import argparse
import datetime
import json
import os
import re
import sys
import time as _time
import traceback
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from copywriter import (WEIBO_SYSTEM, _STYLE_RULES, _call_llm,
                        _extract_json, _repair_truncated_json)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

# 微信合集页(腾讯研究院AI速递): 实时, T-1 日 16:01 发布次日刊
WX_ALBUM_URL = ("https://mp.weixin.qq.com/mp/appmsgalbum"
                "?__biz=MjM5OTE0ODA2MQ==&action=getalbum"
                "&album_id=3349853949226418182")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

NUM_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
             6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟",
             11: "1️⃣1️⃣", 12: "1️⃣2️⃣"}

# ---------------------------------------------------------------- 通用工具


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


def _http_get(url: str, timeout: int = 30, retries: int = 3) -> str:
    """GET + gzip 自动解压 + 重试"""
    import gzip as _gzip
    import io as _io
    import urllib.request as _ur
    last_err = None
    for attempt in range(retries):
        try:
            req = _ur.Request(url, headers={"User-Agent": UA,
                                            "Accept-Encoding": "gzip, deflate"})
            with _ur.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = _gzip.GzipFile(fileobj=_io.BytesIO(raw)).read()
            return raw.decode("utf-8", "ignore")
        except Exception as e:
            last_err = e
            print(f"   [warn] 请求失败(第{attempt+1}次): {e}")
    raise RuntimeError(f"GET 重试{retries}次仍失败: {url[:80]} ({last_err})")


def _js_unescape(s: str) -> str:
    """JS 字符串字面量 → 实际字符串(中文原样保留)"""
    def rep(mo):
        body = mo.group(1)
        if mo.group(2) == "u":
            return chr(int(body, 16))
        return chr(int(body, 16))
    s = s.replace("\\x26", "&")
    return re.sub(r"\\(u|x)([0-9a-fA-F]{2,4})", rep, s)


# ------------------------------------------------- Step 1: 最新一期元数据

def _latest_issue_from_album(album_url: str = WX_ALBUM_URL) -> Dict:
    """微信合集页 → 最新一期元数据(合集倒序, 解析前若干期取期号最大者)"""
    import datetime as _dt
    html = _http_get(album_url, timeout=30)
    pat = re.compile(
        r"title:\s*'([^']*)',\s*"
        r"create_time:\s*'(\d+)',\s*"
        r"cover_img_1_1:\s*'([^']*)',\s*"
        r"url:\s*'([^']*)'", re.S)
    best = None
    for title, ts, cover, url in pat.findall(html):
        title = _js_unescape(title).strip()
        m = re.search(r"(\d{8})", title)
        if not m:
            continue
        pub = _dt.datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M")
        url = _html_unescape(_js_unescape(url)).replace("\\x26", "&")
        cand = {"date": m.group(1), "title": title,
                "source_url": url, "abstract": "", "introduction": "",
                "img_url": cover, "ts_ms": ts, "publish_time": pub}
        if best is None or cand["date"] > best["date"]:
            best = cand
    if not best:
        raise RuntimeError("合集页未解析到带日期的期数")
    if not best["source_url"]:
        raise RuntimeError("合集页最新一期缺少原文链接")
    return best


def _html_unescape(s: str) -> str:
    for a, b in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&nbsp;", " "), ("&mdash;", "—"),
                 ("&ndash;", "–"), ("&hellip;", "…"), ("&ldquo;", "“"),
                 ("&rdquo;", "”"), ("&middot;", "·")]:
        s = s.replace(a, b)
    return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)


# --------------------------------------------- Step 2: 微信原文 → 章节

_JS_NOISE = re.compile(
    r"^(var |if \(|document\.|window\.|function|setTimeout|require\(|"
    r"Object\.defineProperty|try \{|})")


def extract_wx_text(html: str) -> str:
    """微信正文 → 带换行纯文本"""
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*)', html, re.S)
    body = m.group(1) if m else html
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    body = re.sub(r"</(p|section|div|h\d|li|blockquote)>", "\n", body)
    body = re.sub(r"<br[^>]*>", "\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = _html_unescape(body)
    lines, stop = [], False
    for ln in body.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if _JS_NOISE.match(ln) or ln.startswith("腾讯研究院AI速递") and len(ln) > 200:
            stop = True
        if stop:
            break
        lines.append(ln)
    return "\n".join(lines)


_WX_NOISE_EXACT = {
    "关注该公众号", "微信扫一扫可打开此内容，", "使用完整服务",
    "，轻点两下取消赞", "，轻点两下取消在看", "预览时标签不可点",
    "喜欢此内容的人还喜欢", "继续访问", "轻点两下取消赞", "轻点两下取消在看",
}


def _is_wx_noise(ln: str) -> bool:
    if ln.startswith("👇") or ln in _WX_NOISE_EXACT:
        return True
    if "加入AGI数据库" in ln or "订阅下方合集" in ln:
        return True
    return False


def split_sections(text: str) -> List[Dict]:
    """按 '一、标题' 切分章节; 每章 = 标题 + 要点行 + 原文链接"""
    pat = re.compile(r"^([一二三四五六七八九十]{1,3})、(.{4,80})$")
    sections, cur = [], None
    for ln in text.split("\n"):
        m = pat.match(ln)
        if m:
            if cur:
                sections.append(cur)
            cur = {"num_cn": m.group(1),
                   "title": m.group(2).strip(), "points": [], "link": ""}
            continue
        if cur is None:
            continue
        if _is_wx_noise(ln):
            continue
        lm = re.match(r"^(https?://\S+)$", ln)
        if lm and "mp.weixin.qq.com" in ln:
            if not cur["link"]:
                cur["link"] = lm.group(1)
            continue
        if re.match(r"^\d+[\.、]", ln) and len(ln) >= 6:
            cur["points"].append(ln)
        elif len(ln) >= 40:
            cur["points"].append(ln)
    if cur:
        sections.append(cur)
    for s in sections:
        if len("".join(s["points"])) > 900:
            s["points"] = s["points"][:6]
    return sections


def fetch_issue_content(meta: Dict) -> List[Dict]:
    """抓微信原文并切分章节"""
    url = meta.get("source_url") or ""
    if not url:
        raise RuntimeError("最新一期没有微信原文链接")
    html = _http_get(url, timeout=40)
    text = extract_wx_text(html)
    sections = split_sections(text)
    if len(sections) < 3:
        raise RuntimeError(f"章节切分异常: 只切出 {len(sections)} 章")
    return sections


# ------------------------------------------------------- Step 3: LLM 文案

AGI_EXTRA_RULES = """
【AGI 日报特有红线(叠加在通用红线之上)】
- 数据来源描述: 全文【禁止】出现 "ima"、"知识库"、"腾讯研究院"字样;
  来源只能模糊表述为 "网络"/"公开报道", 不解释具体来源渠道
- 事实铁律: 只能使用输入要点里的事实(数字/机构名/产品名/结论),
  一个新事实都不许编; 不确定的数字宁可不用
- 禁新闻腔: "据悉""值得关注的是""引发了广泛关注""业界普遍认为"
- 禁翻译腔: "这是…的重要一步""标志着…的时刻"
- 微博短文场景: 每条 summary 90~130字, 句子更短更碎,
  像发微博不像写专栏; 少用长定语, 多用逗号断句
"""

_GEN_PROMPT = """你要发一条《AGI 日报》微博。今天是{today}, 内容是 {issue_date_display} 的 AI 圈新闻速递(数据来源于网络整理)。

输入素材(JSON, sections 每条 = 一条新闻, points 是官方速递的3条要点):
{sections_json}

输出 JSON:
{{
  "hook": "微博第一行钩子, 25~45字, 必须含至少一个具体新闻细节(数字/产品名), 像朋友发微博的口吻, 禁喊口号",
  "items": [
    {{
      "num": 与输入一致的序号数字,
      "headline": "新闻标题(复用或微调素材标题, ≤24字)",
      "summary": "口语化讲解, 90~130字, 覆盖3个要点的核心, 数字必须保留(价格/参数/成绩), 事实不增不减; 语气像懂行的朋友在评论区科普",
      "tagline": "10~16字短标语, 长图卡片用, 有画面感",
      "category": "分类标签, 从集合选最贴切: 大模型/芯片硬件/产品发布/开源项目/研究突破/行业动态/政策监管/投融资",
      "img_points": ["长图卡片要点1, 8~18字, 保留关键数字或主体名", "长图卡片要点2, 8~18字"]
    }}
  ],
  "outro": "收尾, 35~70字, 平实收束或抛一个讨论问题; 禁金句禁拔高",
  "keywords": ["本期关键词3~5个, 每个2~6字, 用于长图页脚标签云"]
}}

{style_rules}
{extra_rules}"""

_REVIEW_TMPL = """下面是准备发到微博的《AGI 日报》文案(JSON)。请做"去AI味"终审编辑。

【终审要点】
1. 逐句检查写作红线, 有问题就重写该句
2. 事实核对: 与输入素材对照, summary 里的数字/产品名/结论不许有素材之外的编造
3. 全文禁止出现 "ima"、"知识库"、"腾讯研究院"字样
4. 每条 summary 保持 90~130字
5. 保持微博口吻: 短句、直接、像朋友聊天

【输出】重写后的完整 JSON(结构不变), 不要其他文字。

【输入素材(事实基准)】
{slim}

【待审文案】
{draft}

{style_rules}"""


def generate_post_content(meta: Dict, sections: List[Dict]) -> Dict:
    """LLM 生成微博文案(生成 + 终审两段; 截断自动修复 + 退避重试)"""
    today = datetime.date.today()
    issue_date_display = (f"{meta['date'][:4]}年{int(meta['date'][4:6])}月"
                          f"{int(meta['date'][6:])}日")
    slim = [{"num": i + 1, "title": s["title"], "points": s["points"],
             "link": s["link"]} for i, s in enumerate(sections)]
    prompt = _GEN_PROMPT.format(
        today=today.isoformat(), issue_date_display=issue_date_display,
        sections_json=json.dumps(slim, ensure_ascii=False, indent=1),
        style_rules=_STYLE_RULES, extra_rules=AGI_EXTRA_RULES)

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
            print(f"   [warn] 4 次均不完整, 采用截断修复的部分结果 "
                  f"({len(best_partial['items'])}/{len(slim)} 条)")
            data = best_partial
        else:
            raise RuntimeError(f"LLM 输出解析失败(4次): {raw[:300]}")

    # 条目对齐
    if len(data["items"]) != len(slim):
        print(f"   [warn] LLM 条目数 {len(data['items'])} != 素材 {len(slim)}, 对齐修复")
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

    # 终审(一轮)
    review = _call_llm(_REVIEW_TMPL.format(
        slim=json.dumps(slim, ensure_ascii=False, indent=1),
        draft=json.dumps(data, ensure_ascii=False, indent=1),
        style_rules=_STYLE_RULES), system=WEIBO_SYSTEM)
    fixed = _extract_json(review)
    if not (fixed and fixed.get("items")):
        fixed = _repair_truncated_json(review)
        if fixed and fixed.get("items"):
            print("   [warn] 终审输出被截断, 修复后采用")
    if fixed and fixed.get("items") and len(fixed["items"]) == len(data["items"]):
        for a, b in zip(data["items"], fixed["items"]):
            fs = (b.get("summary") or "").strip()
            if len(fs) >= 70:
                a["summary"] = fs
            if (b.get("tagline") or "").strip():
                a["tagline"] = b["tagline"].strip()
            if (b.get("category") or "").strip():
                a["category"] = b["category"].strip()
            bpts = [str(p).strip() for p in (b.get("img_points") or [])
                    if str(p).strip()]
            if bpts:
                a["img_points"] = bpts[:2]
        if (fixed.get("hook") or "").strip() and len(fixed["hook"]) >= 15:
            data["hook"] = fixed["hook"].strip()
        if (fixed.get("outro") or "").strip():
            data["outro"] = fixed["outro"].strip()
        fkws = [str(k).strip() for k in (fixed.get("keywords") or [])
                if str(k).strip()]
        if fkws:
            data["keywords"] = fkws[:5]
    else:
        print("   [warn] 终审输出异常, 使用初稿")

    # 兜底补齐
    valid_cat = {"大模型", "芯片硬件", "产品发布", "开源项目",
                 "研究突破", "行业动态", "政策监管", "投融资"}
    for i, it in enumerate(data["items"]):
        if not (it.get("tagline") or "").strip():
            it["tagline"] = (it.get("headline") or "")[:14]
        if (it.get("category") or "").strip() not in valid_cat:
            it["category"] = "行业动态"
        pts = [str(p).strip() for p in (it.get("img_points") or [])
               if str(p).strip()]
        if not pts:
            src = sections[i]["points"] if i < len(sections) else []
            pts = [re.sub(r"^\d+[\.、]\s*", "", p)[:18] for p in src[:2]
                   if p.strip()]
            if not pts:
                s = (it.get("summary") or "").replace("\n", "")
                m = re.match(r"(.+?[。！？])", s)
                pts = [((m.group(1) if m else s)[:18]) or "详见长图"]
        it["img_points"] = pts[:2]
    kws = [str(k).strip() for k in (data.get("keywords") or [])
           if str(k).strip()]
    if not kws:
        kws = [it["category"] for it in data["items"][:4] if it.get("category")]
    data["keywords"] = kws[:5]
    return data


# --------------------------------------------------------- Step 4: 组装微博

def build_weibo_content(meta: Dict, data: Dict) -> str:
    """LLM 结构化结果 → 微博正文文本"""
    issue = meta["date"]
    date_cn = (f"{int(issue[4:6])}月{int(issue[6:])}日"
               if issue.isdigit() and len(issue) == 8 else issue)
    lines = []
    lines.append(f"#AGI日报# {date_cn} · {len(data['items'])} 条 "
                 f"| {(data.get('hook') or '').strip()}")
    lines.append("")
    for it in data["items"]:
        n = it.get("num") or 0
        emoji = NUM_EMOJI.get(n, f"{n}.")
        summary = (it.get("summary") or "").strip()
        lines.append(f"{emoji} {(it.get('headline') or '').strip()}")
        lines.append(summary)
        lines.append("")
    outro = (data.get("outro") or "").strip()
    if outro:
        lines.append(outro)
    lines.append("")
    lines.append("数据来源于网络整理，每天早上更新一期。")
    text = "\n".join(lines).strip()
    # 红线自检(硬防线)
    for banned in ["ima", "知识库", "腾讯研究院"]:
        if banned in text:
            text = text.replace(banned, "网络")
            print(f"   [红线] 正文出现了 '{banned}', 已替换为 '网络'")
    return text


# ------------------------------------------------------------ Step 5: 主流程

def already_posted_issue(issue_date: str) -> bool:
    state = load_state()
    return state.get("weibo_agi_last_issue") == issue_date


def mark_issue_posted(issue_date: str, mblogid: str, content: str):
    state = load_state()
    state["weibo_agi_last_issue"] = issue_date
    hist = state.setdefault("weibo_agi_history", [])
    hist.append({"date": issue_date, "mblogid": mblogid,
                 "ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
                 "head": content[:60]})
    state["weibo_agi_history"] = hist[-30:]
    save_state(state)


def _cleanup_images(keep: int = 3):
    if not os.path.isdir(OUTPUT_DIR):
        return
    files = [os.path.join(OUTPUT_DIR, f) for f in os.listdir(OUTPUT_DIR)
             if f.startswith("agi-") and f.endswith(".png")]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for p in files[keep:]:
        try:
            os.unlink(p)
        except OSError:
            pass


def run(dry_run: bool, force: bool, no_image: bool = False) -> bool:
    """主流程: 取最新期 → 未发过则生成+发布。返回是否发了新内容"""
    from weibo_client import WeiboClient
    from image_maker import render_agi_image

    print("=" * 62)
    print("微博《AGI 日报》")
    print("=" * 62)
    meta = _latest_issue_from_album()
    print(f"   最新期: {meta['date']} 《{meta['title']}》"
          f"(发布于 {meta.get('publish_time', '?')})")

    if already_posted_issue(meta["date"]) and not force:
        print("   本期已发布过, 跳过。")
        return False

    sections = fetch_issue_content(meta)
    print(f"   切出 {len(sections)} 条新闻: "
          + ", ".join(s["title"][:14] for s in sections[:5])
          + ("..." if len(sections) > 5 else ""))

    print("   [LLM] 生成微博文案...")
    data = generate_post_content(meta, sections)
    content = build_weibo_content(meta, data)
    print(f"   正文 {len(content)} 字, {len(data['items'])} 条新闻")

    images: List[str] = []
    if not no_image:
        out_png = os.path.join(OUTPUT_DIR, f"agi-{meta['date']}.png")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        render_agi_image(
            title="AGI 日报", meta={"date": meta["date"]},
            items=data["items"], out_path=out_png,
            keywords=data.get("keywords"))
        images.append(out_png)

    # 预览文件
    with open(os.path.join(OUTPUT_DIR, f"agi-{meta['date']}.md"), "w",
              encoding="utf-8") as f:
        f.write(f"# 微博 AGI 日报 {meta['date']}\n\n```\n{content}\n```\n")

    if dry_run:
        print("\n---- 干跑预览(正文) ----")
        print(content)
        print("---- 干跑结束, 未发布 ----")
        return False

    cfg = load_config()
    client = WeiboClient(cfg["weibo_cookie"])
    post = client.post(content, images)
    mark_issue_posted(meta["date"], post["mblogid"], content)
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
