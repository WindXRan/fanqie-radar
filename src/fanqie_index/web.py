# -*- coding: utf-8 -*-
"""fanqie-index 本地看板：零依赖静态页 + JSON API（标准库 http.server）。

数据来源同 MCP 层（本地快照），不抓取、不内置任何平台数据。

启动：
  python -m fanqie_index.web --data examples/sample_data --port 8401
  （装包后）fanqie-index-web --data <你的数据目录>

浏览器打开 http://127.0.0.1:8401
"""
from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import schema as S
from . import scoring as SC
from . import analysis as AN

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"

_CT = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}


def _channel_gender(channel: str) -> tuple[str, str]:
    ch = (channel or "female").lower()
    if ch in ("女频", "female"):
        return "female", "female"
    if ch in ("男频", "male"):
        return "male", "male"
    return "", ""


def _load(channel: str, rank: str, top: int | None = None) -> list[dict]:
    prefix, gender = _channel_gender(channel)
    books = S.all_books(rank_type=rank, gender=gender if gender else "")
    if top:
        books = books[:top]
    return books


_SAFE_FIELDS = ("book_id", "title", "author", "category", "reads", "status", "words", "url", "gender", "date")


def _project(b: dict) -> dict:
    return {k: b.get(k) for k in _SAFE_FIELDS}


def _api_meta(q: dict | None = None) -> dict:
    st = S.stats()
    latest = S.latest()
    return {
        "available": st["snapshots"] > 0,
        "snapshots": st["snapshots"],
        "books": st["books"],
        "with_book_id": st["with_book_id"],
        "last_date": latest["date"] if latest else "",
        "data_dirs": st["dirs"],
    }


def _api_ranks(q: dict) -> dict:
    books = _load(q.get("channel", "female"), q.get("rank", "read"), None)
    cat = q.get("category", "")
    if cat:
        books = [b for b in books if cat in (b.get("category") or "")]
    top = int(q.get("top", 20))
    books = books[:top]
    return {"count": len(books), "items": [_project(b) for b in books]}


def _api_score(q: dict) -> dict:
    books = _load(q.get("channel", "female"), q.get("rank", "read"))
    serial = q.get("serial", "false") == "true"
    ranked = SC.rank_serial(books, int(q.get("top", 30))) if serial else SC.rank_books(books, int(q.get("top", 30)))
    items = []
    for b in ranked:
        d = _project(b)
        d["score"] = b.get("score")
        d["breakdown"] = {k: b.get(k) for k in ("s_done", "s_words", "s_reads", "s_heat", "s_trope", "s_gf", "s_stable")}
        d["trope_hits"] = b.get("trope_hits")
        d["gf_hits"] = b.get("gf_hits")
        items.append(d)
    return {"count": len(items), "serial": serial, "items": items}


def _api_heat(q: dict) -> dict:
    books = _load(q.get("channel", "female"), q.get("rank", "read"))
    return {"count": len(books), "items": AN.category_heat(books)[:int(q.get("top", 15))]}


def _api_trend(q: dict) -> dict:
    prefix, gender = _channel_gender(q.get("channel", "female"))
    rank_type = q.get("rank", "read")
    files = sorted(f for f in S.snapshot_files() if f.name.startswith(f"fanqie_{prefix}_{rank_type}_") or
                   (not prefix and rank_type in f.name))
    if len(files) < 2:
        return {"available": False, "hint": "趋势差分需要至少两份同一榜单的快照（不同日期）"}
    now = S.load_books(files[-1])
    prev = S.load_books(files[-2])
    top = int(q.get("top", 30))
    return {"available": True, "now_date": files[-1].name, "prev_date": files[-2].name,
            **AN.trend(now[:top], prev[:top])}


def _api_find(q: dict) -> dict:
    rows = S.find(q.get("q", ""), int(q.get("limit", 20)))
    return {"count": len(rows), "items": [_project(b) for b in rows]}


def _api_hotwords(q: dict) -> dict:
    books = _load(q.get("channel", "female"), q.get("rank", "read"))
    return {"count": len(books), "items": AN.hotwords(books, top=int(q.get("top", 20)))}


_ROUTES = {
    "/api/meta": _api_meta,
    "/api/ranks": _api_ranks,
    "/api/score": _api_score,
    "/api/heat": _api_heat,
    "/api/trend": _api_trend,
    "/api/find": _api_find,
    "/api/hotwords": _api_hotwords,
}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, data_dir=None, **kw):
        self.data_dir = data_dir
        super().__init__(*args, **kw)

    def log_message(self, *a):  # 静默默认日志
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path in _ROUTES:
                out = json.dumps(_ROUTES[path](qs), ensure_ascii=False)
                return self._send(200, out.encode("utf-8"))
            return self._send(404, b'{"error":"not found"}')
        except Exception as e:  # 不让单请求异常拖垮 server
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode("utf-8"))

    def _static(self, rel: str):
        # 防目录穿越
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            return self._send(404, b"not found")
        ctype = _CT.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)


def main():
    ap = argparse.ArgumentParser(description="fanqie-index 本地看板（零依赖）")
    ap.add_argument("--data", default=os_env_data(), help="快照目录（多目录用 ; 分隔）")
    ap.add_argument("--port", type=int, default=8401, help="监听端口")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    a = ap.parse_args()

    if a.data:
        import os
        os.environ["FANQIE_INDEX_DATA_DIRS"] = a.data

    handler = partial(Handler, data_dir=a.data)
    httpd = HTTPServer((a.host, a.port), handler)
    url = f"http://{a.host}:{a.port}"
    print(f"📊 番茄指数看板已启动：{url}  （Ctrl+C 退出）")
    print(f"   数据目录：{S.data_dirs()}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


def os_env_data() -> str:
    import os
    return os.environ.get("FANQIE_INDEX_DATA_DIRS", "")


if __name__ == "__main__":
    main()
