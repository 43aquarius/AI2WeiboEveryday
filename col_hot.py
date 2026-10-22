# -*- coding: utf-8 -*-
"""栏目⑤热榜 · 晚间聚合(每日 21:30)

四平台热榜(微博/知乎/抖音/头条)各取头部, LLM 跨平台挑 6~8 条
最有讨论度的写晚间速览(每条 25~60 字点评), 纯文字帖 → #今日热榜#
单源失败自动降级(至少两源可用才发)。
"""
import random

from copywriter import _STYLE_RULES
from matrix_common import (call_llm, column_done, extract_json, load_config,
                           mark_column_done, publish)
from sources import douyin_hot, toutiao_hot, weibo_hot, zhihu_hot

SYSTEM = (
    "你在微博运营一个'晚间热榜速览'栏目。给你四个平台的热榜条目, "
    "请挑出6~8条全网络最有讨论度的(跨平台重复出现的话题优先), "
    "每条写25~60字的点评: 交代这事为什么值得知道, 语气像刷了一晚上"
    "手机的朋友给你划重点, 平实带点态度, 不吃瓜式狂欢。"
    "输出纯 JSON, 不要任何多余文字。" + _STYLE_RULES
)


def _fetch_all() -> list:
    """四源抓取(容错降级), 返回 [(平台, 标注文本)]"""
    cfg = load_config()
    jobs = [
        ("微博", lambda: weibo_hot(cfg["weibo_cookie"], limit=12)),
        ("知乎", lambda: zhihu_hot(limit=8)),
        ("抖音", lambda: douyin_hot(limit=8)),
        ("头条", lambda: toutiao_hot(limit=8)),
    ]
    entries = []
    ok_sources = []
    for name, fn in jobs:
        try:
            rows = fn()
            if rows:
                entries += [(name, label) for _, label in rows]
                ok_sources.append(name)
        except Exception as e:
            print(f"[源] {name} 失败(降级): {e}")
    if len(ok_sources) < 2:
        raise RuntimeError(f"热榜源可用数不足: {ok_sources}")
    print(f"[数据] 可用源: {ok_sources}, 共 {len(entries)} 条")
    return entries


def run(dry_run: bool = False) -> dict:
    if column_done("hot"):
        print("[防重] 今日热榜聚合已发")
        return {"skipped": True}

    entries = _fetch_all()
    random.Random(len(entries)).shuffle(entries)      # 打散平台聚簇
    lines = "\n".join(f"- 【{plat}】{label}" for plat, label in entries)

    raw = call_llm(
        f"今晚的热榜素材(平台+条目):\n{lines}\n\n"
        f"输出JSON: {{\"intro\": \"开头一句,20~40字,今天整体的浏览印象\", "
        f"\"items\": [{{\"plat\": \"平台名\", \"topic\": \"话题\", "
        f"\"text\": \"25~60字点评\"}}]}}", SYSTEM)
    data = extract_json(raw)
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"LLM 输出解析失败: {raw[:200]}")
    print(f"[LLM] 精选 {len(items)} 条")

    parts = []
    if data.get("intro"):
        parts += [data["intro"], ""]
    for it in items:
        parts.append(f"【{it.get('plat', '')}】{it.get('topic', '')}")
        parts.append(it.get("text", ""))
        parts.append("")
    parts.append("数据来源于网络整理。\n#今日热榜#")
    content = "\n".join(parts).rstrip() + "\n"

    result = publish(content, None, dry_run=dry_run)
    if not dry_run:
        mark_column_done("hot",
                         {"items": len(items),
                          "topics": [i.get("topic", "") for i in items],
                          **result})
        print(f"[完成] 热榜聚合 → {result.get('url')}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
