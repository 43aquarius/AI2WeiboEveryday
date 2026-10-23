# -*- coding: utf-8 -*-
"""微博 Web API 客户端(2026-10-19 逆向)

全部接口实测打通:
  ① whoami      GET  https://weibo.com/                       → 首页 $CONFIG(uid/screen_name)
  ② upload      POST https://picupload.weibo.com/interface/upload.php
                 ⚠ cs = CRC32(文件字节) 签名(非随机数! 缺了报 errno:-2)
                 ⚠ Content-Type: application/octet-stream, 必须禁用 Expect:100-continue
                 body = 原始图片字节 → {"ret":true,"pic":{"pid":"..."}}
  ③ post        POST https://weibo.com/ajax/statuses/update   (form-urlencoded)
                 content/visible/pic_id=[{type,pid}...]  fp 指纹可省略
                 长文(>140字)自动 isLongText, 全文折叠可见; #话题# 直接写在 content 里
  ④ destroy     POST https://weibo.com/ajax/statuses/destroy  JSON {"id":"..."}
  ⑤ myblog      GET  https://weibo.com/ajax/statuses/mymblog?uid=&page=1&feature=0
"""
import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.request
import zlib
from typing import Dict, List, Optional

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class WeiboClient:
    def __init__(self, cookie: str):
        self.cookie = cookie.strip()
        m = re.search(r"XSRF-TOKEN=([^;]+)", self.cookie)
        if not m:
            raise ValueError("cookie 里找不到 XSRF-TOKEN")
        self.xsrf = m.group(1).strip()
        self._uid: Optional[str] = None
        self._nick: Optional[str] = None

    # ---------------------------------------------------------------- 底层

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {
            "Cookie": self.cookie,
            "User-Agent": UA,
            "Referer": "https://weibo.com/",
            "Accept": "application/json, text/plain, */*",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, url: str, body: bytes = None,
                 content_type: str = "application/json;charset=UTF-8",
                 xsrf: bool = True, timeout: int = 60,
                 allow_empty: bool = False) -> Dict:
        """统一请求: 返回 (status, json); 非 2xx 或 JSON 解析失败时抛异常"""
        headers = self._headers({"Content-Type": content_type}
                                if body is not None else {})
        if xsrf:
            headers["X-Xsrf-Token"] = self.xsrf
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        # urllib 默认对大 body 发 Expect:100-continue, picupload 会拒收(-2)
        class _NoExpect(urllib.request.HTTPHandler):
            def do_request(self, r):
                r = super().do_request(r)
                r.add_unredirected_header("Expect", "")
                return r
        import urllib.request as _ur
        opener = _ur.build_opener(_NoExpect)
        last_err = None
        for attempt in range(3):
            try:
                with opener.open(req, timeout=timeout) as resp:
                    raw = resp.read()
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                if not raw.strip():
                    if allow_empty:
                        return {}
                    raise RuntimeError("空响应")
                return json.loads(raw.decode("utf-8", "ignore"))
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"微博请求失败({method} {url[:80]}): {last_err}")

    # ------------------------------------------------------------ ① 登录态

    def whoami(self) -> Dict[str, str]:
        """首页 $CONFIG 验证登录, 返回 {uid, nick}"""
        req = urllib.request.Request(
            "https://weibo.com/", headers={"Cookie": self.cookie,
                                           "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        html = raw.decode("utf-8", "ignore")
        m = re.search(r'"idstr":"(\d+)".{0,80}?"screen_name":"([^"]+)"',
                      html)
        if not m:
            raise RuntimeError("cookie 失效或未登录(首页无用户信息)")
        self._uid, self._nick = m.group(1), m.group(2)
        print(f"[weibo] 登录身份: {self._nick} (uid={self._uid})")
        return {"uid": self._uid, "nick": self._nick}

    @property
    def uid(self) -> str:
        if not self._uid:
            self.whoami()
        assert self._uid
        return self._uid

    # ------------------------------------------------------------ ② 传图

    def upload_image(self, path: str) -> str:
        """上传图片, 返回 pid"""
        data = open(path, "rb").read()
        md5 = hashlib.md5(data).hexdigest()
        crc = zlib.crc32(data)             # ← 签名: 文件 CRC32
        t = int(time.time() * 1000)
        url = ("https://picupload.weibo.com/interface/upload.php"
               f"?file_source=1&cs={crc}&ent=miniblog&appid=339644097"
               f"&uid={self.uid}&raw_md5={md5}&ori=1&mpos=1"
               f"&nick=%40%E9%98%BF%E5%BA%93%E5%B0%94%E6%96%AF&pri=0"
               f"&request_id={t}&file_size={len(data)}")
        r = self._request("POST", url, body=data,
                          content_type="application/octet-stream",
                          xsrf=False, timeout=180, allow_empty=False)
        if not r.get("ret"):
            raise RuntimeError(f"图片上传失败: {json.dumps(r)[:200]}")
        pid = r["pic"]["pid"]
        print(f"[weibo] 图片上传成功: {os.path.basename(path)} → pid={pid}")
        return pid

    # ------------------------------------------------------------ ③ 发帖

    def post(self, content: str, image_paths: Optional[List[str]] = None,
             visible: int = 0) -> Dict:
        """发微博(文字 + 可选图片列表)。返回帖子数据(含 id/mblogid/text_raw)"""
        from urllib.parse import quote
        if len(content) > 5000:
            content = content[:4990] + "…"
        pids: List[Dict] = []
        for p in (image_paths or [])[:9]:
            pid = self.upload_image(p)
            mime = "image/png" if p.lower().endswith(".png") else "image/jpeg"
            pids.append({"type": mime, "pid": pid})
        form = {
            "content": content,
            "visible": str(visible),
            "share_id": "", "vote": "", "media": "",
            "need_transcode": "1",
            "pic_id": json.dumps(pids, ensure_ascii=False,
                                 separators=(",", ":")) if pids else "",
        }
        body = "&".join(f"{k}={quote(str(v), safe='')}"
                        for k, v in form.items()).encode()
        r = self._request("POST", "https://weibo.com/ajax/statuses/update",
                          body=body,
                          content_type="application/x-www-form-urlencoded")
        if not r.get("ok"):
            raise RuntimeError(f"发微博失败: {json.dumps(r, ensure_ascii=False)[:300]}")
        d = r["data"]
        print(f"[weibo] ✅ 发布成功: https://weibo.com/{self._uid}/{d['mblogid']}"
              f"  (id={d['id']}, 图 {len(d.get('pic_ids') or [])} 张, "
              f"长文 {'是' if d.get('isLongText') else '否'})")
        return d

    # ------------------------------------------------------------ ④ 删帖

    def destroy(self, post_id) -> bool:
        r = self._request(
            "POST", "https://weibo.com/ajax/statuses/destroy",
            body=json.dumps({"id": str(post_id)}).encode())
        ok = bool(r.get("id") or r.get("idstr"))
        print(f"[weibo] 删除 {post_id}: {'✅' if ok else '❌'}")
        return ok

    # ------------------------------------------------------------ ⑤ 我的微博

    def my_posts(self, page: int = 1) -> List[Dict]:
        r = self._request(
            "GET", f"https://weibo.com/ajax/statuses/mymblog"
                   f"?uid={self.uid}&page={page}&feature=0", xsrf=True)
        if not r.get("ok"):
            return []
        return r["data"]["list"]

