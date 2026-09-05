# -*- coding: utf-8 -*-
"""看板 server 冒烟测试：线程内起 HTTPServer，验证静态页 + /api 路由。"""
import os
import sys
import json
import threading
import urllib.request
from pathlib import Path
from http.server import HTTPServer
from functools import partial
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = str(ROOT / "examples" / "sample_data")
os.environ["FANQIE_INDEX_DATA_DIRS"] = SAMPLE
sys.path.insert(0, str(ROOT / "src"))

from fanqie_index import web as W


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), partial(W.Handler, data_dir=SAMPLE))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read()


def test_index_html(server):
    st, body = _get(server, "/")
    assert st == 200 and b"<html" in body and "番茄指数".encode("utf-8") in body


def test_static_assets(server):
    st, body = _get(server, "/static/style.css")
    assert st == 200 and b"--bg" in body
    st, body = _get(server, "/static/app.js")
    assert st == 200 and b"render" in body


def test_api_meta(server):
    st, body = _get(server, "/api/meta")
    d = json.loads(body)
    assert d["available"] is True and d["snapshots"] >= 3


def test_api_score(server):
    st, body = _get(server, "/api/score?channel=female&rank=read&top=3")
    d = json.loads(body)
    assert d["count"] >= 1
    assert 0 <= d["items"][0]["score"] <= 100


def test_api_heat(server):
    st, body = _get(server, "/api/heat")
    assert json.loads(body)["count"] >= 1


def test_api_trend(server):
    st, body = _get(server, "/api/trend")
    d = json.loads(body)
    assert d["available"] is True
    assert "entered" in d and "dropped" in d


def test_api_hotwords(server):
    st, body = _get(server, "/api/hotwords")
    assert json.loads(body)["count"] >= 1


def test_api_find(server):
    st, body = _get(server, "/api/find?q=" + quote("金枝"))
    d = json.loads(body)
    assert d["count"] >= 1


def test_api_book(server):
    st, body = _get(server, "/api/book?book_id=1000000004")
    d = json.loads(body)
    assert d["available"] is True
    assert d["item"]["intro"]  # 看板单本详情带简介全文（仅本地看板，MCP 对外仍不放开）
    st, body = _get(server, "/api/book?book_id=9999999999")
    assert json.loads(body)["available"] is False
