# -*- coding: utf-8 -*-
"""LLM 文案层(微博版): z-ai CLI 调用 + JSON 容错 + 截断修复 + 微博风格红线

复用自小黑盒项目 summarizer.py 的三件套(实测稳定):
  _call_llm / _extract_json / _repair_truncated_json
写作红线同样来自 humanizer/Humanizer-zh 的 AI 痕迹清单, 按微博短文场景精简。
"""
import json
import os
import re
import subprocess
import tempfile
from typing import Optional

# ----------------------------------------------------------------- 基础三件套


def _call_llm(prompt: str, system: str = "", timeout: int = 420) -> str:
    """调用 z-ai CLI, 返回 completion 文本"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    try:
        cmd = ["z-ai", "chat", "--prompt", prompt, "-o", out_path]
        if system:
            cmd += ["--system", system]
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
        with open(out_path) as f:
            data = json.load(f)
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return content.strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def _fix_unescaped_quotes(text: str) -> str:
    """转义字符串值内部未转义的 ASCII 双引号(2026-10-21 实测根因)

    LLM 写中文引语时直接输出 "..."(U+0022) 不转义, json.loads 报
    "Expecting ',' delimiter"。判定规则(字符串内遇到 "):
      跳过其后空白 → 若到结尾 / 下一字符是 : } ] → 收尾引号;
      若是 , 且逗号后(跳空白)是 " { [ (下一键/下一项) → 收尾引号;
      其余(中文字文/标点/数字等) → 内容引号, 转义为 \" 。
    与 summarizer.py 同步维护。
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if not in_str:
            if ch == '"':
                in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "\\":                    # 已转义, 原样保留转义对
            out.append(ch)
            if i + 1 < n:
                out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j >= n or text[j] in ":}]":
                in_str = False
                out.append('"')
                i += 1
                continue
            if text[j] == ",":
                k = j + 1
                while k < n and text[k] in " \t\r\n":
                    k += 1
                if k < n and text[k] in '"{[':  # , "key": / , {…} / , […]
                    in_str = False
                    out.append('"')
                    i += 1
                    continue
            out.append('\\"')               # 内容引号 → 转义
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON(容错: ```json 围栏/前后杂文字)"""
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        if text[end - 1] != "}":
            continue
        frag = text[start:end]
        try:
            return json.loads(frag)
        except json.JSONDecodeError:
            pass
        try:                          # 未转义引号修复后再试
            return json.loads(_fix_unescaped_quotes(frag))
        except json.JSONDecodeError:
            continue
    return None


def _repair_truncated_json(text: str) -> Optional[dict]:
    """修复被截断的 JSON: 迭代回退到干净的语法边界, 补齐闭合括号后尝试解析"""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    # 与 _extract_json 对齐: 容忍 JSON 前的前导文字/残缺围栏
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    if not text.startswith("{"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fixed = _fix_unescaped_quotes(text)
    if fixed != text:                # 未转义引号: 修复后再试
        try:
            parsed = json.loads(fixed)
            print("   [fix] 未转义引号已修复, JSON 完整解析")
            return parsed
        except json.JSONDecodeError:
            pass
        text = fixed                 # 截断+引语并用: 回退闭合也基于修复文本

    def _try_close(frag: str) -> Optional[dict]:
        frag = frag.rstrip()
        while frag.endswith(","):
            frag = frag[:-1].rstrip()
        if frag.endswith(":") or frag.endswith('"'):
            return None
        stack, in_str, escape = [], False, False
        for ch in frag:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()
        if in_str or not stack:
            return None
        closers = {"{": "}", "[": "]"}
        try:
            return json.loads(frag + "".join(closers[c] for c in reversed(stack)))
        except json.JSONDecodeError:
            return None

    frag = text
    for _ in range(600):
        data = _try_close(frag)
        if data is not None:
            return data
        frag = frag[:-1]
        if len(frag) < 10:
            return None
    return None


# ----------------------------------------------------------------- 微博风格

WEIBO_SYSTEM = (
    "你在微博运营一个 AI 资讯账号, 粉丝是对 AI 感兴趣的普通网友。"
    "你的文风像懂行的朋友发微博: 短句、口语、信息密度高、偶尔吐槽, "
    "完全不像新闻稿。输出必须是纯 JSON, 不要任何多余文字。"
)

# 红线: 小黑盒版 _STYLE_RULES 的微博精简版(短文场景删掉长文专属条款)
_STYLE_RULES = """【写作红线(出现任何一条都会被退稿)】
- 禁假对比:"不仅…更是…""不是…而是…""与其说…不如说…"
- 禁单句金句收尾:如"这才是AI的魅力。""这,就是技术的意义。"
- 禁意义拔高:"标志着""开启了新篇章""改变了…方式""里程碑"
- 禁四字词排比堆砌:"功能强大、性能卓越、前景广阔"
- 禁互联网黑话:"赋能""闭环""抓手""打造""深耕""护城河"
- 禁空转连接语:"值得注意的是""值得一提的是""不得不说""众所周知"
- 禁热度套词:"引爆全网""炸裂""强势登顶""刷屏";热度要用具体细节说话
- 禁万能比喻:"相当于给XX装上了XX"(全篇至多1次)
- 禁导游腔:"让我们来看看""废话不多说"
- 禁客服腔:"希望对你有帮助""总的来说"
- 收尾方式必须轮换:平铺直叙/问句/场景/一句建议交替,不许每条一个模子
- 句子长短交替;同一种开头方式全篇至多出现2次
- 禁万能受益句:"能有效提升/帮助"——收益写具体:省了什么/快了多少
- 中文表达:别堆"的"字长定语,别说"进行+动词"
"""
