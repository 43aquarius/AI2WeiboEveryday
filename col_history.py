# -*- coding: utf-8 -*-
"""栏目④历史 · 上的今天(每日 18:30)

百度百科 CMS 接口取当日事件(远→近), LLM 挑 4~6 条有聊头的写通俗讲解
(偏科技/文化/人物/冷知识, 每条 40~80 字), 纯文字帖 → #历史上的今天#
"""
import datetime

from copywriter import _STYLE_RULES
from matrix_common import (call_llm, column_done, extract_json,
                           mark_column_done, now_bjt, publish)
from sources import history_today

SYSTEM = (
    "你在微博运营一个'历史上的今天'栏目。给你当日事件清单, 请挑出4~6条"
    "最有聊头的(优先: 科技发明/文化人物/有意思的冷知识/影响深远的事件), "
    "每条用现代人容易懂的方式讲40~80字, 像爱历史的朋友在饭桌上随口讲古, "
    "不背教科书腔。输出纯 JSON, 不要任何多余文字。"
    + _STYLE_RULES
)


def run(dry_run: bool = False) -> dict:
    if column_done("history"):
        print("[防重] 今日历史上的今天已发")
        return {"skipped": True}

    now = now_bjt()
    events = history_today(now.month, now.day)
    if not events:
        raise RuntimeError("百科历史接口无当日事件")
    print(f"[数据] {now.month}月{now.day}日 共{len(events)}条事件")

    lines = "\n".join(
        f"- {e['year']}年 {e['title']}{'；' + e['desc'][:60] if e['desc'] else ''}"
        for e in events)
    raw = call_llm(
        f"今天是{now.month}月{now.day}日。当日历史事件清单:\n{lines}\n\n"
        f"输出JSON: {{\"items\": [{{\"year\": \"年份\", \"title\": \"事件名\", "
        f"\"text\": \"40~80字通俗讲解\"}}]}}, "
        f"按时间从早到近排列。", SYSTEM)
    data = extract_json(raw)
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"LLM 输出解析失败: {raw[:200]}")
    print(f"[LLM] 挑选 {len(items)} 条")

    week = "一二三四五六日"[now.weekday()]
    parts = [f"{now.month}月{now.day}日 · 星期{week}",
             "多少年前的今天——", ""]
    for it in items:
        parts.append(f"{it.get('year', '')}年，{it.get('title', '')}")
        parts.append(it.get("text", ""))
        parts.append("")
    parts.append("#历史上的今天#")
    content = "\n".join(parts).rstrip() + "\n"

    result = publish(content, None, dry_run=dry_run)
    if not dry_run:
        mark_column_done("history",
                         {"items": len(items), "titles":
                          [i.get("title", "") for i in items], **result})
        print(f"[完成] 历史上的今天 → {result.get('url')}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
