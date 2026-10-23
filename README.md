# AI2WeiboEveryday · 微博五栏目内容矩阵机器人

> **Agent 交接文档**（2026-10-23 版）· 读完本文即可全权接管本项目的发布、调度与运维。

## 0. 三十秒了解

微博账号的日更内容矩阵，五个栏目覆盖全天时段，从配图文案到发布全自动，常驻调度器驱动 + 断点补发。

代码目录（沙箱内）：`/home/z/my-project/weibo-agi-poster/`

## 1. 栏目与节奏

| 栏目 | 时刻（北京时间） | 模块 | 内容形态 |
|------|------|------|------|
| 早报 morning | 07:30 | `col_morning.py` | 雪原/晨间场景配图 + 问候文案 |
| 一言 yiyan | 12:00 | `col_yiyan.py` | 一句话签文风 + 配图 |
| 萌宠 pet | 15:00 | `col_pet.py` | 萌宠图 + 轻文案 |
| 历史上的今天 history | 18:30 | `col_history.py` | 当日历史事件图文 |
| 热榜 hot | 21:30 | `col_hot.py` | 四源热榜聚合 + 精选 8 条 |

- `col_hot.py` 已做**时段自适应**：白天 catch-up 补发自动用「日间」框架文案，21:30 正常档期仍用「晚间」框架。
- 调度器带 catch-up：进程重启后错过档期会自动补发当日栏目。

## 2. 环境与安装

```bash
cd /home/z/my-project/weibo-agi-poster
pip install -r requirements.txt
python3 main.py status          # 登录态 + 各栏目防重状态
python3 main.py post morning --dry-run
```

## 3. 凭据体系（三层持久化）

```
config.json                           ← 运行时读取（.gitignore；weibo_cookie 字段）
/home/z/.secrets/weibo_config.json    ← 项目外持久层
secrets_backup.json                   ← 项目内兜底
```

需要的外部凭据：微博 Web cookie。
重建通道：`python3 /home/z/my-project/scripts/rebuild_weibo_config.py`（cookie 内嵌在脚本中，沙箱重启后运行即恢复）。
沙箱重启后统一跑 `python3 /home/z/my-project/scripts/boot_heal.py` 自愈（凭据回写 + 调度器拉起）。

## 4. 完整发布流程

```
各栏目模块(col_*.py) 独立产出: 选题/文案/配图
  → matrix_common.py 公共组装
  → weibo_client.py 上传图片(微博图床) + 发博(2026-10 逆向的 Web API)
  → 回读验证 → state 防重标记
```

- 文案生成复用 `copywriter.py`（LLM 风格管线）。
- 热榜数据：`sources.py` 四源聚合（多源交叉，单源失败降级）。

## 5. 调度器与自愈

```bash
python3 main.py scheduler    # 前台运行
nohup python3 scheduler.py >/dev/null 2>&1 &   # 常驻(run_scheduler.sh)
```

- 60s tick；`scheduler.log` 超 5MB 自动清空；`run_daemon.py` + watchdog 双保险。
- 沙箱重启后：`python3 /home/z/my-project/scripts/boot_heal.py`（三平台统一恢复入口）。
- 长任务用 `/home/z/my-project/scripts/detached_run.py` 启动（Bash 工具会清理 nohup 子进程，双 fork 脱离才能常驻）。

## 6. 微博 Web API 逆向要点（2026-10）

- 发布走微博 Web 端 `ajax` 接口族，`weibo_client.py` 已封装上传与发博全流程。
- 登录态探测与防重状态：`python3 main.py status` 一次看全。
- 具体接口签名/参数细节见 `weibo_client.py` 源码头部注释与 `/home/z/my-project/worklog.md` 微博章节。

## 7. 常用命令速查

```bash
python3 main.py status                  # 登录态+五栏目防重
python3 main.py post hot --dry-run      # 单栏目干跑
python3 main.py post all --dry-run      # 全部栏目干跑
python3 main.py post yiyan              # 正式发一言
python3 main.py scheduler               # 前台调度器
python3 /home/z/my-project/scripts/rebuild_weibo_config.py  # 凭据重建
python3 /home/z/my-project/scripts/boot_heal.py             # 一键自愈
tail -50 scheduler.log                  # 调度日志
```

## 8. 接管 checklist

1. `boot_heal.py` → 确认「凭据: OK | 调度器: 已拉起」
2. `python3 main.py status` → 登录态、当日各栏目发布状态
3. 对照微博个人主页核实当日已发栏目（**勿重复发**）
4. 读 `/home/z/my-project/worklog.md` 最新两节（含当日五栏目补发记录）
5. 每次发布/改动后在 worklog.md 追加记录
