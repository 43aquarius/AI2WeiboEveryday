# -*- coding: utf-8 -*-
"""数据源模块: 热榜(微博/知乎/抖音/头条) + 历史上的今天 + 一言本地池

全部为公开直连接口(2026-10-22 实测), 不依赖第三方聚合服务:
  - 微博热搜: weibo.com/ajax/side/hotSearch  (需登录 cookie, 52条)
  - 知乎热榜: api.zhihu.com/topstory/hot-lists/total?limit=30
  - 抖音热榜: aweme-lq.snssdk.com/aweme/v1/hot/search/list
  - 头条热榜: www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc
  - 历史上的今天: baike.baidu.com/cms/home/eventsOnHistory/{MM}.json
  - 一言: 本地 data/hitokoto.json (3386条, 零运行时依赖)
"""
import json
import os
import random
import re
import urllib.request
from typing import List, Tuple

BASE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _get_json(url: str, cookie: str = "", timeout: int = 12) -> dict:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
        headers["Referer"] = "https://weibo.com/"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


# ---------------------------------------------------------------- 热榜

def weibo_hot(cookie: str, limit: int = 10) -> List[Tuple[str, str]]:
    """微博热搜(需登录cookie): [(话题, 热度)]"""
    d = _get_json("https://weibo.com/ajax/side/hotSearch", cookie=cookie)
    out = []
    for it in (d.get("data", {}).get("realtime") or [])[:limit]:
        word = it.get("word", "").strip()
        num = it.get("num", 0)
        if word:
            label = f"{word}({num // 10000}万热度)" if num > 10000 else word
            out.append((word, label))
    return out


def zhihu_hot(limit: int = 6) -> List[Tuple[str, str]]:
    """知乎热榜: [(标题, 带热度标注)]"""
    d = _get_json("https://api.zhihu.com/topstory/hot-lists/total?limit=30")
    out = []
    for it in (d.get("data") or [])[:limit]:
        t = (it.get("target") or {})
        title = (t.get("title") or "").strip()
        detail = (it.get("detail_text") or "").strip().replace(" 万热度", "万热度")
        if title:
            out.append((title, f"{title}({detail})" if detail else title))
    return out


def douyin_hot(limit: int = 6) -> List[Tuple[str, str]]:
    """抖音热榜: [(话题, 带热度)]"""
    d = _get_json("https://aweme-lq.snssdk.com/aweme/v1/hot/search/list/"
                  "?aid=1128&version_code=880")
    out = []
    for it in (d.get("data", {}).get("word_list") or [])[:limit]:
        w = it.get("word", "").strip()
        hv = it.get("hot_value", 0)
        if w:
            out.append((w, f"{w}({hv // 10000}万热度)" if hv else w))
    return out


def toutiao_hot(limit: int = 6) -> List[Tuple[str, str]]:
    """头条热榜: [(标题, 标注)]"""
    d = _get_json("https://www.toutiao.com/hot-event/hot-board/"
                  "?origin=toutiao_pc")
    out = []
    for it in (d.get("data") or [])[:limit]:
        t = (it.get("Title") or "").strip()
        if t:
            out.append((t, t))
    return out


# ---------------------------------------------------------------- 历史

def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def history_today(month: int, day: int) -> List[dict]:
    """百度百科"历史上的今天": [{year, title, desc, link}]
    数据按年排序(远→近), 上游为百科官方 CMS 接口。"""
    url = f"https://baike.baidu.com/cms/home/eventsOnHistory/{month:02d}.json"
    d = _get_json(url)
    events = (d.get(f"{month:02d}", {}) or {}).get(f"{month:02d}{day:02d}", [])
    out = []
    for e in events:
        title = _strip_html(e.get("title", ""))
        if not title:
            continue
        out.append({
            "year": str(e.get("year", "")).strip(),
            "title": title,
            "desc": _strip_html(e.get("desc", ""))[:120],
            "link": e.get("link", ""),
        })
    return out


# ---------------------------------------------------------------- 一言

_HITO_POOL = None


def hitokoto(seed: str) -> str:
    """本地一言池(3386条), 按日期种子选取保证同日可复现"""
    global _HITO_POOL
    if _HITO_POOL is None:
        path = os.path.join(BASE, "data", "hitokoto.json")
        with open(path, encoding="utf-8") as f:
            _HITO_POOL = json.load(f)
    rng = random.Random(seed)
    return rng.choice(_HITO_POOL)
