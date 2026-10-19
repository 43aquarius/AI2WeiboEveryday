# AI2WeiboEveryday · 微博 AI 资讯自动运营机器人

每天自动抓取 AI 资讯、用 LLM 写成"人味"文案、渲染长图、定时发微博。
与小黑盒版 [AGI2iaoHeiHeiEveryday](https://github.com/43aquarius/AGI2iaoHeiHeiEveryday) 同源的姊妹项目，独立运行。

## 两个日更栏目

| 栏目 | 数据源 | 发布时间(北京) | 形态 |
|------|--------|---------------|------|
| **AGI 日报** `#AGI日报#` | 腾讯研究院 AI 速递(微信合集页实时源, T-1 日 16:01 出刊) | 每天 08:30 | 长文(8~9条新闻, 每条90~130字) + 主题长图 |
| **AI 情报站** `#AI情报站#` | [AIHOT](https://aihot.news) 公开 API(`/api/v1`, 24h 精选) | 每天 12:00 | 长文(4~7条资讯, 每条55~90字) + 情报站长图 |

## 数据链路

```
┌─ AGI 日报 ─────────────────────────────────────────────┐
│ 微信合集页(免登录SSR) → 期号/标题/原文链接               │
│   → 微信原文 → 按「一、二、三」切分新闻条目(要点+链接)    │
│   → LLM 微博化改写(两段式: 生成+去AI味终审)              │
│   → 主题长图(4套主题按期号轮换) → 发微博                 │
└────────────────────────────────────────────────────────┘
┌─ AI 情报站 ─────────────────────────────────────────────┐
│ aihot.news /api/v1/items?mode=selected&window=24h        │
│   → 按热度分挑 Top7(降级: /hot-topics 热点榜)            │
│   → LLM 微博化改写(资讯自带中文标题/摘要, 只做润色)       │
│   → 情报站长图 → 发微博                                  │
└────────────────────────────────────────────────────────┘
```

## 微博 Web API 逆向要点(2026-10)

全部接口用浏览器 cookie 即可调用，无第三方依赖：

| 功能 | 接口 | 关键坑 |
|------|------|--------|
| 登录验证 | `GET weibo.com/` 首页 `$CONFIG` | 无 |
| 发帖 | `POST /ajax/statuses/update` (form-urlencoded) | `pic_id` 是 JSON 数组字符串; `fp` 指纹可省; >140字自动长文折叠 |
| 图片上传 | `POST picupload.weibo.com/interface/upload.php` | **`cs` = 文件 CRC32(非随机数, 错了报 errno:-2)**; `Content-Type: application/octet-stream`; 必须禁用 `Expect: 100-continue`; body 为原始图片字节 |
| 删帖 | `POST /ajax/statuses/destroy` | JSON body `{"id":"..."}` (query 参数会 400) |
| 我的微博 | `GET /ajax/statuses/mymblog?uid=&page=1&feature=0` | 无 |

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium     # 长图渲染用

# 配置(填自己的浏览器 cookie)
cp config.example.json config.json
#   weibo_cookie: 从浏览器 F12 → Network → 任意 weibo.com 请求的 Cookie 头整串复制
#   必须包含: SUB / XSRF-TOKEN / SUBP / WBPSESS 等

python main.py status           # 验证 cookie 登录态
python main.py agi --dry-run    # AGI 日报干跑(只构造不发布)
python main.py ai  --dry-run    # AI 情报站干跑
python main.py agi              # 立即发布一次 AGI 日报
nohup python main.py scheduler >/dev/null 2>&1 &   # 常驻调度
```

## 调度器

`scheduler.py` 进程内轮询(容器环境无 cron)，自愈能力：

- **失败重试**：档期任务失败后每 30 分钟重试，单档期每周期最多 3 次
- **逻辑防重**：AGI 日报按期号(`weibo_agi_last_issue`)防重，AI 情报站按日期防重；
  state 丢失时靠数据源自带防重兜底(已发期号不会重发)
- **日志轮转**：`scheduler.log` 超 5MB 自动清空

## 文案质量(反 AI 味)

三道防线，规则来自 [humanizer](https://github.com/blader/humanizer) / [Humanizer-zh](https://github.com/op7418/Humanizer-zh) 的 AI 痕迹清单：

1. **生成红线内嵌**：假对比/金句收尾/意义拔高/四字排比/互联网黑话/热度套词…直接写进 prompt
2. **终审 pass**：LLM 以素材为事实基准重写越线句子(事实不增不减)
3. **确定性兜底**：JSON 截断自动修复(逐字符回退+括号补齐)、条目数对齐、期号防重

内容红线：
- AGI 日报**不提**"ima/知识库/腾讯研究院"，只说"数据来源于网络整理"
- AI 情报站帖尾注明"资讯整理自 AIHOT(aihot.news)"
- 事实铁律：LLM 只改写不编造，数字以素材为准

## 长图

HTML + Playwright 2x 截图(2160px 宽输出)，4 套主题按期号轮换：
`ember` 炉火橙 / `ocean` 深海青 / `violet` 星云紫 / `matrix` 终端绿。
TOP1-3 焦点卡渐变描边，每条新闻带分类 chip + 标语 + 两条要点，页脚关键词标签云。

## 项目结构

```
├── weibo_client.py    # 微博 Web API 客户端(上传CRC32签名/发帖/删帖)
├── agi_daily.py       # AGI 日报系列(微信合集页数据源)
├── ai_news.py         # AI 情报站系列(aihot.news API)
├── copywriter.py      # LLM 层(z-ai CLI + JSON截断修复 + 微博风格红线)
├── image_maker.py     # 长图渲染(HTML + Playwright, 4主题)
├── scheduler.py       # 常驻调度器(失败重试/防重/日志轮转)
├── main.py            # CLI 入口(status/agi/ai/scheduler)
├── config.example.json
└── state.json         # 防重状态(gitignore)
```

## 免责声明

- 本项目仅个人学习用途；微博 cookie 为本人账号凭证，请勿外泄
- aihot.news 数据按其[公开使用规则](https://aihot.news/agent?tab=api)以个人身份匿名调用(≤60次/分钟)
- 内容由 LLM 生成，事实以各信源原文为准
