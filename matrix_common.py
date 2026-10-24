# -*- coding: utf-8 -*-
"""五栏目矩阵共享层: 配置/state 防重/发布/图片生成与搜索

栏目清单(2026-10-22 转型, 替代原科技日报方向):
  morning  07:30  早安 · AI壁纸     z-ai image 生成壁纸 + 早安文案
  yiyan    12:00  一言 · 午间签     本地语料 → 文字卡片图
  pet      15:00  萌宠 · 午后图签   z-ai image-search 真实萌宠照
  history  18:30  历史 · 上的今天   百科CMS接口 + LLM 通俗讲解
  hot      21:30  热榜 · 晚间聚合   四平台热榜 + LLM 跨平台点评
"""
import datetime
import json
import os
import random
import subprocess
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
STATE_PATH = os.path.join(BASE, "state.json")
OUTPUT_DIR = os.path.join(BASE, "output")
SECRETS_PATH = "/home/z/.secrets/weibo_config.json"   # 项目外持久层(重启免疫)

BJT = datetime.timezone(datetime.timedelta(hours=8))


def today_bjt() -> str:
    return datetime.datetime.now(BJT).strftime("%Y-%m-%d")


def now_bjt() -> datetime.datetime:
    return datetime.datetime.now(BJT)


def load_config() -> dict:
    """加载配置: config.json → /home/z/.secrets/weibo_config.json 逐层回退。

    沙箱重启会清除快照点之后新建/修改的文件(config.json 是 .gitignore 的,
    从不进快照) — 项目外 .secrets 副本不受该机制管辖, 作为凭据持久层,
    缺失时自动回写自愈。"""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            print("[config] config.json 丢失, 已从 .secrets 自愈")
        except OSError:
            pass
        return cfg
    raise FileNotFoundError(
        f"config.json 与 {SECRETS_PATH} 均缺失 — "
        f"运行 scripts/rebuild_weibo_config.py 重建")


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"history": []}


def save_state(st: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def column_done(col: str) -> bool:
    """该栏目今日是否已发(state 防重)"""
    return load_state().get(f"matrix_{col}_last_date") == today_bjt()


def mark_column_done(col: str, rec: dict):
    st = load_state()
    st[f"matrix_{col}_last_date"] = today_bjt()
    st.setdefault("history", []).append(
        {"column": col, "date": today_bjt(), **rec})
    save_state(st)


# ---------------------------------------------------------------- 发布

def publish(content: str, image_paths=None, dry_run=False) -> dict:
    """发微博; dry_run 只打印。返回 {ok, url} 或 {dry_run}"""
    if dry_run:
        print("[dry-run] 未发布。内容:")
        print("----------")
        print(content)
        if image_paths:
            print(f"---------- 配图 {len(image_paths)} 张: "
                  + ", ".join(os.path.basename(p) for p in image_paths))
        return {"dry_run": True}
    from weibo_client import WeiboClient
    client = WeiboClient(load_config()["weibo_cookie"])
    d = client.post(content, image_paths)
    return {"ok": True, "id": d.get("id"),
            "url": f"https://weibo.com/{client.uid}/{d.get('mblogid')}"}


# ---------------------------------------------------------------- AI 能力

def gen_image(prompt: str, out_path: str, size: str = "1344x768",
              timeout: int = 300) -> str:
    """z-ai 图片生成; 生成服务故障时降级为图片搜索+下载(2026-10-24 405事件)"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        subprocess.run(["z-ai", "image", "-p", prompt, "-o", out_path,
                        "-s", size],
                       capture_output=True, timeout=timeout, check=True)
        if os.path.exists(out_path) and os.path.getsize(out_path) >= 10_000:
            print(f"[img] 已生成 → {os.path.basename(out_path)}")
            return out_path
    except Exception as e:
        print(f"[img] 生成失败({str(e)[:80]}), 降级图片搜索")
    # ---- 降级: 用提示词前段搜真实图片, 多候选中优先横版 ----
    q = prompt.split(",")[0].strip()[:60]
    want_wide = size and "x" in str(size) and \
        int(str(size).split("x")[0]) >= int(str(size).split("x")[1])
    try:
        cands = search_images(q, count=6) or []
    except Exception as e:
        print(f"[img] 搜索降级也失败: {str(e)[:80]}")
        cands = []
    best = None
    for url in cands:
        try:
            download_image(url, out_path, min_bytes=10_000)
            if not want_wide:
                print(f"[img] 搜索降级图 → {os.path.basename(out_path)}")
                return out_path
            from PIL import Image
            with Image.open(out_path) as im:
                if im.size[0] >= im.size[1]:      # 横版 ✓
                    print(f"[img] 搜索降级图(横版{im.size[0]}x{im.size[1]})"
                          f" → {os.path.basename(out_path)}")
                    return out_path
            if best is None:
                best = url                        # 先留一张竖版兜底
        except Exception:
            continue
    if best:
        try:
            download_image(best, out_path, min_bytes=10_000)
            print(f"[img] 搜索降级图(竖版兜底) → {os.path.basename(out_path)}")
            return out_path
        except Exception:
            pass
    if cands:
        raise RuntimeError(f"搜索降级候选全部下载失败: {out_path}")
    raise RuntimeError(f"图片生成与搜索降级均失败: {out_path}")


def search_images(query: str, count: int = 6, timeout: int = 120) -> list:
    """z-ai 图片搜索: 返回 [{url, caption...}]

    完整查询失败(如网关502)时自动降级: 逗号前片段 → 前4词"""
    import re
    attempts = [query]
    if "," in query:
        attempts.append(query.split(",")[0].strip())
    words = query.split()
    if len(words) > 4:
        attempts.append(" ".join(words[:4]))
    last_err = None
    for q in dict.fromkeys(attempts):            # 去重保序
        try:
            r = subprocess.run(
                ["z-ai", "image-search", "-q", q, "-c", str(count)],
                capture_output=True, timeout=timeout, check=False)
            out = r.stdout.decode("utf-8", "ignore")
            urls = []
            for m in re.finditer(r'https?://[^\s"\']+?\.(?:jpg|jpeg|png|webp)',
                                 out, re.I):
                u = m.group(0)
                if u not in urls:
                    urls.append(u)
            if urls:
                if q != query:
                    print(f"[search] 完整查询失败, 降级 '{q}' 命中")
                print(f"[search] '{q}' → {len(urls)} 张"
                      + (" (exit=%d 但有结果)" % r.returncode
                         if r.returncode else ""))
                return urls
            last_err = RuntimeError(
                f"图片搜索无结果: {q} (exit={r.returncode})")
        except Exception as e:
            last_err = e
            print(f"[search] '{q}' 失败, 尝试降级: {str(e)[:120]}")
    raise RuntimeError(f"图片搜索全部失败: {last_err}")


def download_image(url: str, out_path: str, min_bytes: int = 30_000) -> str:
    """下载搜索结果图到本地(发微博需要本地文件)"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    if len(data) < min_bytes:
        raise RuntimeError(f"图片太小({len(data)}B), 疑似无效: {url[:80]}")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"[dl] {len(data) // 1024}KB → {os.path.basename(out_path)}")
    return out_path


def call_llm(prompt: str, system: str, timeout: int = 420) -> str:
    """z-ai chat(纯文本返回)"""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    try:
        subprocess.run(["z-ai", "chat", "--prompt", prompt,
                        "--system", system, "-o", out_path],
                       capture_output=True, timeout=timeout, check=True)
        with open(out_path) as f:
            data = json.load(f)
        return ((data.get("choices") or [{}])[0]
                .get("message", {}).get("content", "")).strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def extract_json(text: str) -> dict:
    """LLM 输出 → dict(容错围栏/未转义引号, 复用 copywriter 三件套)"""
    from copywriter import _extract_json, _repair_truncated_json
    return _extract_json(text) or _repair_truncated_json(text) or {}


# 日期种子(同日可复现, 每日轮换)
def date_seed() -> str:
    return today_bjt().replace("-", "")
