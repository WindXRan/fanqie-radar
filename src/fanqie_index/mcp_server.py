# -*- coding: utf-8 -*-
"""fanqie-radar（番茄雷达）：番茄榜单阅读 + 仿写选书评分 MCP 服务（stdio，零第三方依赖）。

传输：MCP stdio = newline-delimited JSON-RPC 2.0（符合 MCP 规范，Claude Desktop /
Cursor / 任意 MCP 客户端可直接挂载）。不依赖 mcp SDK，纯标准库实现。

安全红线（开源版铁律）：
  - 不抓取、不内置任何平台数据；数据由用户自备的本地快照提供（包内仅附虚构示例数据供零配置试跑）。
  - 不提供任何「下载整本小说」能力；只返回 book_id / url（让用户自己处理）。
  - 不向外部返回 intro 简介全文 / cover 版权图 URL（避免通过 MCP 扩散第三方版权内容）。
    对外书目只含：book_id, title, author, category, reads, status, chapters, url。

用法：
  python -m fanqie_index.mcp_server
或（装包后）：
  fanqie-radar
数据目录：环境变量 FANQIE_INDEX_DATA_DIRS（os.pathsep 分隔）或 ./data；
未配置时自动落到包内示例数据（零配置即用）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import schema as S
from . import scoring as SC
from . import analysis as AN

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "fanqie-radar", "version": "0.2.0"}

# 对外书目投影（剔除 intro/cover 等版权内容）
_SAFE_FIELDS = ("book_id", "title", "author", "category", "reads", "status", "chapters", "url", "gender", "date")


def _project(b: dict) -> dict:
    return {k: b.get(k) for k in _SAFE_FIELDS}


def _channel_gender(channel: str) -> tuple[str, str]:
    """channel 参数（female/male/女频/男频）→ rank_type 前缀 + gender 过滤值。"""
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


# ── 工具实现 ──

def t_ranks(channel: str, rank: str, category: str = "", top: int = 20) -> dict:
    books = _load(channel, rank, top=None)
    if category:
        books = [b for b in books if category in (b.get("category") or "")]
    books = books[:top]
    return {"count": len(books), "items": [_project(b) for b in books]}


def t_find(query: str, limit: int = 20) -> dict:
    rows = S.find(query, limit)
    return {"count": len(rows), "items": [_project(b) for b in rows]}


def t_trend(channel: str, rank: str, top: int = 30) -> dict:
    prefix, gender = _channel_gender(channel)
    rank_type = f"{prefix}_{rank}" if prefix else rank
    files = [f for f in S.snapshot_files() if f.name.startswith(f"fanqie_{rank_type}_") or
             (not prefix and rank_type in f.name)]
    files = sorted(files, key=lambda p: p.name)
    if len(files) < 2:
        return {"available": False, "hint": "趋势差分需要至少两份同一榜单的快照（不同日期）"}
    now = S.load_books(files[-1])
    prev = S.load_books(files[-2])
    if top:
        now, prev = now[:top], prev[:top]
    return {"available": True, "now_date": files[-1].name, "prev_date": files[-2].name,
            **AN.trend(now, prev)}


def t_genre_heat(channel: str, rank: str = "read", top: int = 15) -> dict:
    books = _load(channel, rank)
    return {"count": len(books), "items": AN.category_heat(books)[:top]}


def t_imitation_score(channel: str = "female", rank: str = "read", top: int = 30,
                      serial: bool = False) -> dict:
    """核心工具：仿写选书六维评分（或男频连载母本评分）。"""
    books = _load(channel, rank)
    if serial:
        ranked = SC.rank_serial(books, top)
    else:
        ranked = SC.rank_books(books, top)
    items = []
    for b in ranked:
        d = _project(b)
        d["score"] = b.get("score")
        # 评分拆解（不泄露 intro，只给命中计数）
        d["breakdown"] = {k: b.get(k) for k in
                          ("s_done", "s_size", "s_reads", "s_heat", "s_trope", "s_gf", "s_stable")}
        d["trope_hits"] = b.get("trope_hits")
        d["gf_hits"] = b.get("gf_hits")
        items.append(d)
    return {"count": len(items), "serial": serial, "items": items}


def t_hotwords(channel: str, rank: str = "read", top: int = 20) -> dict:
    books = _load(channel, rank)
    return {"count": len(books), "items": AN.hotwords(books, top=top)}


def t_stats() -> dict:
    return S.stats()


# ── MCP 协议层 ──

TOOLS = [
    {
        "name": "fanqie_ranks",
        "description": "读取最新番茄榜单（按频道/榜型/品类）。返回书名、作者、在读、状态、章节数、book_id——不含简介全文与版权图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["female", "male", "女频", "男频"],
                            "description": "频道，默认 female", "default": "female"},
                "rank": {"type": "string", "enum": ["read", "new", "peak", "completed"],
                         "description": "榜单类型：阅读榜/新书榜/巅峰榜/完结池", "default": "read"},
                "category": {"type": "string", "description": "品类关键词过滤（可选），如 '豪门总裁'"},
                "top": {"type": "integer", "description": "返回条数", "default": 20},
            },
        },
    },
    {
        "name": "fanqie_find",
        "description": "跨全部快照按书名/作者模糊查找，返回 book_id 与书目信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "书名或作者关键词"},
                "limit": {"type": "integer", "description": "返回条数", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fanqie_trend",
        "description": "多日趋势差分：对比同一榜单最新两份快照，给出新上榜/掉榜/排名变化/在读增长。需 data/ 下存在至少两份同榜快照。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["female", "male", "女频", "男频"],
                            "default": "female"},
                "rank": {"type": "string", "enum": ["read", "new", "peak", "completed"], "default": "read"},
                "top": {"type": "integer", "description": "参与差分的榜单条数（取前 N）", "default": 30},
            },
        },
    },
    {
        "name": "fanqie_genre_heat",
        "description": "题材热度聚合（按在读总量排序），识别当前吸量赛道。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["female", "male", "女频", "男频"],
                            "default": "female"},
                "rank": {"type": "string", "enum": ["read", "new"], "default": "read"},
                "top": {"type": "integer", "default": 15},
            },
        },
    },
    {
        "name": "fanqie_imitation_score",
        "description": "【核心】仿写选书六维评分（完结度/体量适配/单本热度/题材吸量/套路密度/金手指清晰 + 稳定性/跨榜/巅峰加成）。也可切男频连载母本评分。用于在读爆款里筛出'最适合仿写'的书，并给出每本的分数拆解。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["female", "male", "女频", "男频"],
                            "default": "female"},
                "rank": {"type": "string", "enum": ["read", "new", "completed"], "default": "read"},
                "top": {"type": "integer", "description": "返回评分 Top N", "default": 30},
                "serial": {"type": "boolean", "description": "true=男频连载母本评分（连载体量×在读×更新活跃×吸量×套路×金手指）", "default": False},
            },
        },
    },
    {
        "name": "fanqie_hotwords",
        "description": "书名热词频次统计（基于套路词表），快速看当前书名流行词。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["female", "male", "女频", "男频"],
                            "default": "female"},
                "rank": {"type": "string", "enum": ["read", "new"], "default": "read"},
                "top": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "fanqie_stats",
        "description": "数据概览：快照数量、书目总数、book_id 覆盖率、被探测到的数据目录。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_DISPATCH = {
    "fanqie_ranks": lambda a: t_ranks(a.get("channel", "female"), a.get("rank", "read"),
                                      a.get("category", ""), int(a.get("top", 20))),
    "fanqie_find": lambda a: t_find(a.get("query", ""), int(a.get("limit", 20))),
    "fanqie_trend": lambda a: t_trend(a.get("channel", "female"), a.get("rank", "read"),
                                      int(a.get("top", 30))),
    "fanqie_genre_heat": lambda a: t_genre_heat(a.get("channel", "female"), a.get("rank", "read"),
                                                int(a.get("top", 15))),
    "fanqie_imitation_score": lambda a: t_imitation_score(a.get("channel", "female"),
                                                           a.get("rank", "read"),
                                                           int(a.get("top", 30)),
                                                           bool(a.get("serial", False))),
    "fanqie_hotwords": lambda a: t_hotwords(a.get("channel", "female"), a.get("rank", "read"),
                                           int(a.get("top", 20))),
    "fanqie_stats": lambda a: t_stats(),
}


def _respond(req_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        req_id = req.get("id")
        is_notification = req_id is None
        params = req.get("params") or {}

        if method == "initialize":
            _respond(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _respond(req_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {}) or {}
            fn = _DISPATCH.get(name)
            if fn is None:
                _respond(req_id, error={"code": -32601, "message": f"unknown tool: {name}"})
                continue
            try:
                result = fn(args)
                _respond(req_id, {"content": [{"type": "text",
                                               "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                                 "isError": False})
            except Exception as e:  # 不让单个工具异常拖垮 server
                _respond(req_id, error={"code": -32000, "message": f"{type(e).__name__}: {e}"})
        else:
            if not is_notification:
                _respond(req_id, error={"code": -32601, "message": f"unsupported method: {method}"})


if __name__ == "__main__":
    main()
