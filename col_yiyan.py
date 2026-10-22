# -*- coding: utf-8 -*-
"""栏目②一言 · 午间签(每日 12:00)

本地 3386 条语料按日轮换 → 渲染 1080x1350 文字卡片(七套配色按星期轮换)
→ LLM 写 20~45 字随感 → #一言# #句子控#
"""
import os
import random

from card_renderer import render_quote_card
from copywriter import _STYLE_RULES
from matrix_common import (OUTPUT_DIR, call_llm, column_done, date_seed,
                           mark_column_done, publish, today_bjt)
from sources import hitokoto

SYSTEM = (
    "你在微博运营一个'每日一言'栏目, 分享一句话并附一句简短随感。"
    "随感要求: 20~45字, 像读完这句话后随手写下的一点触动, "
    "口语自然, 不解释句子含义, 不升华, 不喊口号。直接输出随感正文。"
    + _STYLE_RULES
)


def run(dry_run: bool = False) -> dict:
    if column_done("yiyan"):
        print("[防重] 今日一言签已发")
        return {"skipped": True}

    seed = date_seed()
    sentence = hitokoto(seed)
    print(f"[一言] {sentence}")

    today = today_bjt()
    img = os.path.join(OUTPUT_DIR, f"yiyan_{seed}.png")
    render_quote_card(sentence, img, date_str=today)

    reply = ""
    try:
        reply = call_llm(
            f"今日一言: 「{sentence}」\n写一句20~45字的随感。",
            SYSTEM).strip().strip('"“”').strip()
        print("[随感]", reply)
    except Exception as e:
        print(f"[随感] 生成失败, 纯句子发布: {e}")

    lines = [f"「{sentence}」"]
    if reply:
        lines += ["", reply]
    lines += ["", "#一言# #句子控#"]
    content = "\n".join(lines)

    result = publish(content, [img], dry_run=dry_run)
    if not dry_run:
        mark_column_done("yiyan",
                         {"sentence": sentence, "reply": reply, **result})
        print(f"[完成] 一言签 → {result.get('url')}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
