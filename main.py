# -*- coding: utf-8 -*-
"""微博内容矩阵 · 统一入口(2026-10-22 转型版)

五个日更栏目(替代原科技日报方向):
  morning  早安 · AI壁纸     07:30   z-ai 生成壁纸 + 早安文案
  yiyan    一言 · 午间签     12:00   本地语料 + 文字卡片
  pet      萌宠 · 午后图签   15:00   图片搜索真实萌宠照
  history  历史 · 上的今天   18:30   百科CMS + LLM 通俗讲解
  hot      热榜 · 晚间聚合   21:30   四平台热榜 + LLM 速览

用法:
  python main.py status                 # 登录态 + 各栏目防重状态
  python main.py post morning --dry-run # 单栏目干跑
  python main.py post morning           # 单栏目正式发布
  python main.py post all --dry-run     # 五栏目顺序干跑
  python main.py scheduler              # 启动常驻调度器
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

COLUMNS = ["morning", "yiyan", "pet", "history", "hot"]
COLUMN_NAMES = {"morning": "早安·AI壁纸", "yiyan": "一言·午间签",
                "pet": "萌宠·午后图签", "history": "历史·上的今天",
                "hot": "热榜·晚间聚合"}
SLOTS = {"morning": "07:30", "yiyan": "12:00", "pet": "15:00",
         "history": "18:30", "hot": "21:30"}


def read_json(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def cmd_status():
    from weibo_client import WeiboClient
    from matrix_common import load_config
    cfg = load_config()
    state = read_json(STATE_PATH)
    print("=" * 52)
    print("微博内容矩阵 · 状态")
    print("=" * 52)
    if not cfg.get("weibo_cookie"):
        print("❌ config.json 缺 weibo_cookie")
        return 1
    try:
        client = WeiboClient(cfg["weibo_cookie"])
        me = client.whoami()
        print(f"✅ 登录正常: {me['nick']} (uid={me['uid']})")
    except Exception as e:
        print(f"❌ 登录异常: {e}")
        return 1
    mx = cfg.get("matrix", {})
    for c in COLUMNS:
        sent = state.get(f"matrix_{c}_last_date", "无")
        on = "on" if mx.get(f"{c}_enabled", True) else "off"
        print(f"  {COLUMN_NAMES[c]:<10} {SLOTS[c]}  [{on}]  今日已发: {sent}")
    return 0


def cmd_post(column: str, dry_run: bool):
    import importlib
    cols = COLUMNS if column == "all" else [column]
    for c in cols:
        if c not in COLUMNS:
            print(f"未知栏目: {c}")
            return 1
        print(f"\n===== {COLUMN_NAMES[c]} =====")
        mod = importlib.import_module(f"col_{c}")
        mod.run(dry_run=dry_run)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status", help="登录态与各栏目防重状态")
    p_post = sub.add_parser("post", help="立即执行某栏目")
    p_post.add_argument("column",
                        choices=COLUMNS + ["all"],
                        help="栏目名或 all")
    p_post.add_argument("--dry-run", action="store_true")
    sub.add_parser("scheduler", help="启动常驻调度器")

    args = ap.parse_args()
    if args.cmd == "status":
        sys.exit(cmd_status())
    elif args.cmd == "post":
        sys.exit(cmd_post(args.column, args.dry_run))
    elif args.cmd == "scheduler":
        import scheduler
        scheduler.main()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
