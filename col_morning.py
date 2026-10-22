# -*- coding: utf-8 -*-
"""栏目①早安 · AI壁纸(每日 07:30)

十四套壁纸主题按日轮换(date-seed 可复现), z-ai 生成 1344x768 横版壁纸,
LLM 写 40~80 字早安文案(呼应主题), 配 #早安# #AI绘画# 双话题。
"""
import os
import random

from matrix_common import (OUTPUT_DIR, call_llm, column_done, date_seed,
                           gen_image, mark_column_done, publish, today_bjt)
from copywriter import _STYLE_RULES

# (主题名, 英文生成提示词) — 轮换池, 生成模型对英文提示更稳
THEMES = [
    ("晨雾山峦", "misty mountain ranges at dawn, soft golden light breaking through fog, layered peaks fading into distance, serene atmosphere, ultra detailed landscape painting, wallpaper composition"),
    ("海边日出", "sunrise over calm ocean, warm orange and pink sky reflecting on gentle waves, minimalist composition, a few seabirds in distance, peaceful mood, high quality digital painting"),
    ("星空银河", "milky way galaxy over silent valley, thousands of stars, deep blue and purple night sky, distant mountains silhouette, tiny warm tent light in foreground, astrophotography style"),
    ("极光之夜", "aurora borealis dancing over snow field, green and violet ribbons of light, starry sky, small cozy cabin with warm window light, dreamy atmosphere, ultra detailed"),
    ("水彩森林", "watercolor illustration of morning forest, sunlight rays through trees, deer drinking at a stream, soft pastel greens and golds, hand painted texture, storybook style"),
    ("晨光城市", "quiet city street in early morning, soft sunlight on wet pavement after rain, warm cafe lights still on, bicycle leaning on wall, lofi aesthetic, cozy illustration"),
    ("云海日出", "sea of clouds at sunrise viewed from mountain top, golden light flooding over cloud layers, distant sun rising, majestic and calm, high detail landscape"),
    ("雪原清晨", "snow covered plain at dawn, pale blue and soft pink sky, single line of animal footprints in snow, leafless tree silhouette, minimal and quiet, fine art photography style"),
    ("樱花溪流", "cherry blossom branches over small stream, petals floating on water, soft morning light, spring pastel palette, japanese woodblock print influence, peaceful"),
    ("湖面倒影", "perfectly still alpine lake mirroring mountains at sunrise, morning mist on water surface, warm and cool color contrast, symmetrical composition, landscape photography"),
    ("田野晨光", "golden wheat field at early morning, dew drops on grass in foreground, sun flare low on horizon, rolling hills in distance, warm nostalgic tone, film photography style"),
    ("雨后苔庭", "zen garden after rain, moss and stone lantern with water drops, maple leaves, soft diffused morning light, japanese garden aesthetic, tranquil and green"),
    ("沙丘晨光", "desert sand dunes at dawn, clean curving shadows, gradient from gold to lavender sky, single desert plant, minimal composition, fine art"),
    ("山涧清晨", "mountain stream in early morning, clear water over rounded stones, sunbeams through pine forest, small waterfall, lush greens, detailed nature painting"),
]

SYSTEM = (
    "你在微博运营一个生活方式向的账号, 每天早上发一条'AI绘画壁纸+早安问候'。"
    "文风: 像一个早起后心情不错的人在跟关注者打招呼, 自然、有画面感、不油腻。"
    + _STYLE_RULES
)


def run(dry_run: bool = False) -> dict:
    if column_done("morning"):
        print("[防重] 今日早安壁纸已发")
        return {"skipped": True}

    seed = date_seed()
    theme_name, theme_prompt = random.Random(seed).choice(THEMES)
    print(f"[主题] {theme_name}")

    ts = today_bjt().replace("-", "")
    img = os.path.join(OUTPUT_DIR, f"morning_{ts}.png")
    gen_image(theme_prompt, img, size="1344x768")

    raw = call_llm(
        f"今天的AI壁纸主题是「{theme_name}」。写一段40~80字的早安微博文案, "
        f"可以描述这幅画面的感觉, 或从清晨的一个小场景切入, 结尾一句自然的问候。"
        f"不要解释这是AI画的, 不要用'愿'字开头, 直接输出文案正文。",
        SYSTEM)
    # 清洗: 去引号包裹/多余空行
    text = raw.strip().strip('"“”').strip()
    content = f"{text}\n\n#早安# #AI绘画#"
    print("[文案]", text)

    result = publish(content, [img], dry_run=dry_run)
    if not dry_run:
        mark_column_done("morning",
                         {"theme": theme_name, "text": text, **result})
        print(f"[完成] 早安壁纸 → {result.get('url')}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
