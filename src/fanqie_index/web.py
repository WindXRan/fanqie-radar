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
import threading
import time
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


_SAFE_FIELDS = ("book_id", "title", "author", "category", "reads", "status", "chapters", "url", "gender", "date", "cover")

# 可选章节/状态缓存（<data>/meta_cache.json，由用户自备的外部补全工具产出，本仓库不抓取）
# 格式：{"<book_id>": {"chapters": 158, "status": "已完结"}}
_META_CACHE: dict | None = None
_META_CACHE_MTIME = 0.0


def _meta_cache() -> dict:
    """读 meta_cache.json（带 mtime 热更新，改文件无需重启）。"""
    global _META_CACHE, _META_CACHE_MTIME
    import os
    paths = []
    for d in S.data_dirs():
        p = d / "meta_cache.json"
        if p.is_file():
            paths.append(p)
    src = paths[0] if paths else None
    if src is None:
        return _META_CACHE or {}
    try:
        mt = src.stat().st_mtime
        if _META_CACHE is None or mt != _META_CACHE_MTIME:
            _META_CACHE = json.loads(src.read_text(encoding="utf-8"))
            _META_CACHE_MTIME = mt
    except Exception:
        pass
    return _META_CACHE or {}


def _project(b: dict) -> dict:
    out = {k: b.get(k) for k in _SAFE_FIELDS}
    mc = _meta_cache().get(str(b.get("book_id") or ""))
    if mc:
        # 快照缺字段时用缓存补（章节/状态）；快照有值不覆盖
        if not out.get("chapters") and mc.get("chapters"):
            out["chapters"] = mc["chapters"]
        if not out.get("status") and mc.get("status"):
            out["status"] = mc["status"]
    return out


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
        d["breakdown"] = {k: b.get(k) for k in ("s_done", "s_size", "s_reads", "s_heat", "s_trope", "s_gf", "s_stable")}
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


# 单本详情索引（book_id → 书目，全快照建一次；本地看板专用，MCP 对外投影不放开 intro）
_BOOK_IDX: dict[str, dict] = {}
_BOOK_IDX_BUILT = False


def _book_index() -> dict[str, dict]:
    global _BOOK_IDX_BUILT
    if not _BOOK_IDX_BUILT:
        for f in S.snapshot_files():  # 文件名升序，新快照覆盖旧快照
            for b in S.load_books(f):
                if b["book_id"]:
                    _BOOK_IDX[b["book_id"]] = b
        _BOOK_IDX_BUILT = True
    return _BOOK_IDX


def _api_book(q: dict) -> dict:
    """单本详情（含 intro 简介全文）：看板点击书名时按需拉取。"""
    bid = (q.get("book_id") or "").strip()
    if not bid:
        return {"available": False, "hint": "book_id 必填"}
    b = _book_index().get(bid)
    if b is None:
        return {"available": False, "hint": "未在任何快照中找到该书"}
    out = _project(b)
    out["intro"] = b.get("intro") or ""
    out["rank_pos"] = b.get("rank_pos")
    return {"available": True, "item": out}


def _api_books(q: dict) -> dict:
    """扫榜工作台主数据：书目列表 + 人类扫榜过滤器（搜索/品类/状态/在读/套路词）。"""
    books = _load(q.get("channel", "female"), q.get("rank", "read"))
    cat = q.get("category", "")
    if cat:
        books = [b for b in books if b.get("category") == cat]
    kw = (q.get("q") or "").strip().lower()
    if kw:
        books = [b for b in books if kw in (b.get("title") or "").lower()
                 or kw in (b.get("author") or "").lower()
                 or kw in (b.get("intro") or "").lower()]
    status = q.get("status", "")
    if status == "done":
        books = [b for b in books if "完结" in (b.get("status") or "")]
    elif status == "serial":
        books = [b for b in books if b.get("status") and "完结" not in (b.get("status") or "")]
    min_reads = int(q.get("min_reads", 0) or 0)
    if min_reads:
        books = [b for b in books if (b.get("reads") or 0) >= min_reads]
    trope = (q.get("trope") or "").strip()
    if trope:
        # 热词按书名统计（/api/hotwords），这里也按书名过滤，口径一致；原先匹配简介，
        # 导致点击热词后经常搜出 0 本（书名含该词的书简介未必含）
        books = [b for b in books if trope in (b.get("title") or "")]
    sort = q.get("sort", "reads")
    if sort == "pos":
        books.sort(key=lambda b: b.get("rank_pos") or 9999)
    else:
        books.sort(key=lambda b: -(b.get("reads") or 0))
    top = int(q.get("top", 200))
    books = books[:top]
    items = []
    for b in books:
        d = _project(b)
        d["intro_preview"] = (b.get("intro") or "")[:100]
        d["trope_hits"] = sum(1 for k in SC.TROPE if k in (b.get("intro") or ""))
        items.append(d)
    return {"count": len(items), "items": items}


# ── 扫榜采集状态管理 ──────────────────────────────────────────────
_SCRAPE_STATE = {
    "running": False,
    "logs": [],
    "started_at": 0,
    "finished_at": 0,
    "error": "",
    "total_cats": 0,
    "done_cats": 0,
    "total_books": 0,
}
_SCRAPE_LOCK = threading.Lock()

_INSTALL_STATE = {
    "running": False,
    "logs": [],
    "done": False,
    "error": "",
}
_INSTALL_LOCK = threading.Lock()


def _scrape_thread(limit, sleep_sec, gender, rank):
    """后台采集线程。"""
    global _BOOK_IDX_BUILT, _BOOK_IDX
    try:
        from . import scraper as SCR
        SCR._OUTPUT_DIR = Path.cwd() / "data"

        def on_log(msg):
            with _SCRAPE_LOCK:
                _SCRAPE_STATE["logs"].append(msg)
                # 解析进度：形如 "(3/19)" 的分类进度
                import re
                m = re.search(r"\((\d+)/(\d+)\)", msg)
                if m:
                    _SCRAPE_STATE["done_cats"] = int(m.group(1))
                    _SCRAPE_STATE["total_cats"] = int(m.group(2))
                # 解析 "xxx: N 本" 的书籍计数
                m2 = re.search(r"(\d+)\s*本", msg)
                if m2 and "完成" not in msg:
                    _SCRAPE_STATE["total_books"] += int(m2.group(1))

        SCR.run_scraper(
            limit=limit, sleep_sec=sleep_sec,
            gender_filter=gender, rank_filter=rank,
            on_log=on_log,
        )
    except Exception as e:
        with _SCRAPE_LOCK:
            _SCRAPE_STATE["error"] = f"{type(e).__name__}: {e}"
            _SCRAPE_STATE["logs"].append(f"✗ 错误: {e}")
    finally:
        with _SCRAPE_LOCK:
            _SCRAPE_STATE["running"] = False
            _SCRAPE_STATE["finished_at"] = time.time()
            # 重建书目索引以加载新数据
            _BOOK_IDX.clear()
            _BOOK_IDX_BUILT = False


def _install_thread():
    """后台安装依赖线程（HTTP 采集零依赖，仅做检查）。"""
    try:
        from . import scraper as SCR

        def on_log(msg):
            with _INSTALL_LOCK:
                _INSTALL_STATE["logs"].append(msg)

        ok = SCR.ensure_dependencies(on_log=on_log)
        with _INSTALL_LOCK:
            _INSTALL_STATE["done"] = True
            if not ok:
                _INSTALL_STATE["error"] = "检查失败"
            else:
                _INSTALL_STATE["logs"].append("✓ 采集环境就绪")
    except Exception as e:
        with _INSTALL_LOCK:
            _INSTALL_STATE["error"] = f"{type(e).__name__}: {e}"
            _INSTALL_STATE["logs"].append(f"✗ 错误: {e}")
    finally:
        with _INSTALL_LOCK:
            _INSTALL_STATE["running"] = False


def _api_scrape_status(q: dict) -> dict:
    with _SCRAPE_LOCK:
        return {
            "running": _SCRAPE_STATE["running"],
            "logs": list(_SCRAPE_STATE["logs"][-80:]),
            "log_count": len(_SCRAPE_STATE["logs"]),
            "started_at": _SCRAPE_STATE["started_at"],
            "finished_at": _SCRAPE_STATE["finished_at"],
            "error": _SCRAPE_STATE["error"],
            "progress": {
                "total_cats": _SCRAPE_STATE["total_cats"],
                "done_cats": _SCRAPE_STATE["done_cats"],
                "total_books": _SCRAPE_STATE["total_books"],
            },
        }


def _api_install_status(q: dict) -> dict:
    with _INSTALL_LOCK:
        return {
            "running": _INSTALL_STATE["running"],
            "done": _INSTALL_STATE["done"],
            "logs": list(_INSTALL_STATE["logs"][-30:]),
            "log_count": len(_INSTALL_STATE["logs"]),
            "error": _INSTALL_STATE["error"],
            "playwright": True,
            "chromium": True,
        }


_ROUTES = {
    "/api/meta": _api_meta,
    "/api/ranks": _api_ranks,
    "/api/score": _api_score,
    "/api/heat": _api_heat,
    "/api/trend": _api_trend,
    "/api/find": _api_find,
    "/api/hotwords": _api_hotwords,
    "/api/book": _api_book,
    "/api/books": _api_books,
    "/api/scrape/status": _api_scrape_status,
    "/api/install/status": _api_install_status,
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

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/scrape":
                # 检查是否已在运行
                with _SCRAPE_LOCK:
                    if _SCRAPE_STATE["running"]:
                        return self._send(409, '{"error":"已有采集任务在运行"}'.encode("utf-8"))
                    # 重置状态
                    _SCRAPE_STATE["running"] = True
                    _SCRAPE_STATE["logs"] = []
                    _SCRAPE_STATE["error"] = ""
                    _SCRAPE_STATE["started_at"] = time.time()
                    _SCRAPE_STATE["finished_at"] = 0
                    _SCRAPE_STATE["total_cats"] = 0
                    _SCRAPE_STATE["done_cats"] = 0
                    _SCRAPE_STATE["total_books"] = 0

                # 解析请求体
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                params = json.loads(body) if body else {}
                limit = int(params.get("limit", 30))
                sleep_sec = float(params.get("sleep", 5))
                gender = params.get("gender", "")
                rank = params.get("rank", "")

                # 启动后台线程
                t = threading.Thread(
                    target=_scrape_thread,
                    args=(limit, sleep_sec, gender, rank),
                    daemon=True,
                )
                t.start()
                return self._send(200, '{"ok":true,"msg":"采集已启动"}'.encode("utf-8"))

            if path == "/api/install":
                # 一键安装依赖
                with _INSTALL_LOCK:
                    if _INSTALL_STATE["running"]:
                        return self._send(409, '{"error":"安装进行中"}'.encode("utf-8"))
                    _INSTALL_STATE["running"] = True
                    _INSTALL_STATE["logs"] = []
                    _INSTALL_STATE["done"] = False
                    _INSTALL_STATE["error"] = ""

                t = threading.Thread(target=_install_thread, daemon=True)
                t.start()
                return self._send(200, '{"ok":true,"msg":"安装已启动"}'.encode("utf-8"))

            return self._send(404, b'{"error":"not found"}')
        except Exception as e:
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
    print(f"📊 番茄雷达看板已启动：{url}  （Ctrl+C 退出）")
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
