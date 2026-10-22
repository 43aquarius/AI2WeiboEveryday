# AI2WeiboEveryday · 微博五栏目内容矩阵机器人

**2026-10-22 转型**：科技日报方向停更（平台特性不适配，详见文末转型说明），
改为「五栏目生活方式矩阵」日更运营——用五类轻内容把账号养成每日多更的
活跃矩阵，AI 负责生产，人只管审方向。

## 五个日更栏目

| 栏目 | 档期(北京) | 内容形态 | 数据/生产链路 |
|------|-----------|---------|--------------|
| **早安·AI壁纸** `#早安# #AI绘画#` | 07:30 | 1344x768 AI 壁纸 + 40~80字早安文案 | 14 套主题按日轮换 → z-ai 文生图 → LLM 文案 |
| **一言·午间签** `#一言# #句子控#` | 12:00 | 1080x1350 文字卡片 + 20~45字随感 | 本地 3386 条语料按日轮换 → playwright 渲染卡片(七套配色按星期轮换) → LLM 随感 |
| **萌宠·午后图签** `#萌宠# #治愈#` | 15:00 | 真实萌宠照 + 30~60字拟人短句 | 12 种题材按日轮换 → z-ai 图片搜索(自动降级查询) → 下载 → LLM 文案 |
| **历史·上的今天** `#历史上的今天#` | 18:30 | 纯文字(4~6条, 每条40~80字) | 百度百科当日事件 → LLM 挑选+通俗讲解 |
| **热榜·晚间聚合** `#今日热榜#` | 21:30 | 纯文字(6~8条, 每条25~60字点评) | 微博/知乎/抖音/头条四平台热榜(单源降级, ≥2源才发) → LLM 跨平台精选 |

## 架构

```
scheduler.py ─── 常驻调度(档期对表 + 启动对账 + 失败重试)
   ├─ col_morning.py ┐
   ├─ col_yiyan.py   │ 五栏目各自独立脚本(subprocess 隔离, 单栏目崩不影响其他)
   ├─ col_pet.py     │ 全部支持 --dry-run 干跑
   ├─ col_history.py │
   └─ col_hot.py     ┘
matrix_common.py ── 共享层: 三层凭据加载 / state 防重 / 发布
                    / z-ai 图片生成·搜索·下载 / LLM 调用 / JSON 容错解析
card_renderer.py ── playwright 文字卡片渲染器
sources.py ─────── 数据源: 四平台热榜 + 百科历史 + 一言本地池
weibo_client.py ── 微博 Web API 客户端(2026-10 逆向, 见下)
copywriter.py ──── LLM 文案基建(风格红线 _STYLE_RULES + JSON 三件套容错)
```

## 自愈与防重设计

- **启动对账**：调度器启动时拉取「我的微博」，当日已有对应话题标签的帖子
  则补写 state 标记——**环境重启丢 state 也不会双发**（2026-10-22 修复了
  `created_at` 字符串解析 bug，此前对账永远失败）。
- **失败重试**：档期失败后每 30 分钟重试，单栏目每日最多 3 次。
- **图片搜索降级**：完整查询失败(如网关 502)自动降级逗号前片段 → 前 4 词。
- **凭据三层持久化**：`config.json` → `/home/z/.secrets/weibo_config.json`
  （项目外，沙箱重启免疫）逐层回退自动自愈；cookie 另嵌入
  `scripts/rebuild_weibo_config.py`（受快照追踪）作为第三重保险。

## 用法

```bash
python3 main.py status                 # 登录态 + 各栏目防重状态
python3 main.py post morning --dry-run # 单栏目干跑
python3 main.py post all --dry-run     # 五栏目顺序干跑
python3 main.py post hot               # 单栏目正式发布
python3 main.py scheduler              # 启动常驻调度器
```

## 微博 Web API 逆向要点(2026-10)

全部接口用浏览器 cookie 即可调用，无第三方依赖：

| 功能 | 接口 | 关键坑 |
|------|------|--------|
| 登录验证 | `GET weibo.com/` 首页 `$CONFIG` | 无 |
| 发帖 | `POST /ajax/statuses/update` (form-urlencoded) | `pic_id` 是 JSON 数组字符串; `fp` 指纹可省; >140字自动长文折叠 |
| 图片上传 | `POST picupload.weibo.com/interface/upload.php` | **`cs` = 文件 CRC32(非随机数, 错了报 errno:-2)**; `Content-Type: application/octet-stream`; 必须禁用 `Expect: 100-continue`; body 为原始图片字节 |
| 删帖 | `POST /ajax/statuses/destroy` | JSON body `{"id":"..."}` (query 参数会 400) |
| 我的微博 | `GET /ajax/statuses/mymblog?uid=&page=1&feature=0` | `created_at` 是 `"Wed Oct 22 08:33:35 +0800 2026"` 格式字符串，**不是** Unix 时间戳 |
| 热搜 | `GET /ajax/side/hotSearch` | 需登录 cookie |

公开数据源直连（免第三方聚合服务）：

| 源 | 接口 |
|----|------|
| 知乎热榜 | `api.zhihu.com/topstory/hot-lists/total?limit=30` |
| 抖音热榜 | `aweme-lq.snssdk.com/aweme/v1/hot/search/list` |
| 头条热榜 | `www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc` |
| 历史上的今天 | `baike.baidu.com/cms/home/eventsOnHistory/{MM}.json` |

## 配置

`config.json`（`.gitignore`，永不入库）：

```json
{
  "weibo_cookie": "PC_TOKEN=...; SUB=...; ...",
  "weibo_post": {"agi_enabled": false, "ai_enabled": false},
  "matrix": {
    "morning_enabled": true, "yiyan_enabled": true, "pet_enabled": true,
    "history_enabled": true, "hot_enabled": true
  }
}
```

各栏目可独立开关（`matrix.{col}_enabled`），关掉即跳过该档期。

## 转型说明（2026-10-22）

原「AGI 日报 + AI 情报站」科技资讯方向停更：微博平台对资讯长文的分发
不如小黑盒（垂直社区），且双平台发同源内容边际收益低。科技资讯主阵地
保留在 [AGI2iaoHeiHeiEveryday](https://github.com/43aquarius/AGI2iaoHeiHeiEveryday)，
微博转向轻量、高频、生活方式向的五栏目矩阵。旧管线代码（agi_daily.py /
ai_news.py / image_maker.py）保留在仓库中备查。

## 声明

- 仅供个人学习与自动化记录，请遵守微博服务条款，控制发布频率。
- `config.json` / `state.json` / `output/` 已在 `.gitignore` 中，**cookie 永不入库**。
