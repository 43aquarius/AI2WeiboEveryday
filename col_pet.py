# -*- coding: utf-8 -*-
"""栏目③萌宠 · 午后图签(每日 15:00)

十二种萌宠题材按日轮换, z-ai image-search 搜真实照片(自动转存OSS),
取首个有效图下载 → LLM 写 30~60 字拟人短句 → #萌宠# #治愈#
"""
import os
import random

from copywriter import _STYLE_RULES
from matrix_common import (OUTPUT_DIR, call_llm, column_done, date_seed,
                           download_image, mark_column_done, publish,
                           search_images, today_bjt)

PETS = [
    ("橘猫幼崽", "cute orange tabby kitten closeup, big eyes, soft fur, warm light"),
    ("布偶猫", "ragdoll cat with blue eyes lying relaxed, fluffy fur"),
    ("柯基幼犬", "corgi puppy with short legs, happy face, grass background"),
    ("柴犬微笑", "smiling shiba inu dog, head tilt, sunny outdoor"),
    ("英短银渐层", "british shorthair silver shaded cat, round face, copper eyes"),
    ("金毛幼犬", "golden retriever puppy sleeping, tiny paws, soft blanket"),
    ("熊猫幼崽", "baby giant panda cub playing, rolly polly, bamboo forest"),
    ("小水獭", "cute baby otter floating on water, holding paws"),
    ("兔兔", "fluffy little bunny with erect ears, clover grass"),
    ("仓鼠", "tiny hamster stuffing cheeks with food, palm of hand"),
    ("矮脚猫", "munchkin kitten with short legs standing, curious look"),
    ("萨摩耶微笑", "smiling samoyed dog white fluffy, head tilt"),
]

SYSTEM = (
    "你在微博运营一个'每日萌宠'栏目, 每天发一张萌宠照片配一句短文案。"
    "文案要求: 30~60字, 从照片里的小细节切入, 可以轻微拟人(想象它在想什么/"
    "在干什么), 俏皮有画面感, 不许说'好治愈''好可爱'这种直白总结。"
    "直接输出文案正文。" + _STYLE_RULES
)


def run(dry_run: bool = False) -> dict:
    if column_done("pet"):
        print("[防重] 今日萌宠图签已发")
        return {"skipped": True}

    seed = date_seed()
    pet_name, pet_query = random.Random(seed).choice(PETS)
    print(f"[题材] {pet_name}")

    urls = search_images(pet_query, count=6)
    ts = today_bjt().replace("-", "")
    ext = ".jpg"
    img = os.path.join(OUTPUT_DIR, f"pet_{ts}{ext}")
    last_err = None
    for u in urls[:4]:                     # 逐个尝试下载, 失败换下一张
        try:
            download_image(u, img)
            break
        except Exception as e:
            last_err = e
            print(f"[dl] 失败换下一张: {e}")
    else:
        raise RuntimeError(f"萌宠图全部下载失败: {last_err}")

    text = call_llm(
        f"今日萌宠照片主角: {pet_name}。写一段30~60字的微博文案。",
        SYSTEM).strip().strip('"“”').strip()
    print("[文案]", text)

    content = f"{text}\n\n#萌宠# #治愈#"
    result = publish(content, [img], dry_run=dry_run)
    if not dry_run:
        mark_column_done("pet", {"pet": pet_name, "text": text, **result})
        print(f"[完成] 萌宠图签 → {result.get('url')}")
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
