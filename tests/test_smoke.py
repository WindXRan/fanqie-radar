# -*- coding: utf-8 -*-
"""冒烟测试：用 examples/sample_data 验证三层（schema/scoring/analysis）跑通。

运行：pytest   （需先 cd 到仓库根，或 pip install -e .）
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = str(ROOT / "examples" / "sample_data")
# 让 schema 的目录探测指向合成示例数据
os.environ["FANQIE_INDEX_DATA_DIRS"] = SAMPLE

sys.path.insert(0, str(ROOT / "src"))

from fanqie_index import schema as S
from fanqie_index import scoring as SC
from fanqie_index import analysis as AN


def test_load_snapshots():
    files = S.snapshot_files()
    assert len(files) >= 3
    books = S.all_books(rank_type="read", gender="female")
    assert len(books) > 0
    # book_id 全量可寻址：示例数据都有 bookid
    assert all(b["book_id"] for b in books)
    # category 已注入
    assert any(b["category"] == "豪门总裁" for b in books)


def test_find():
    # 真实快照含「惹金枝/攀高枝/枝上蘅」等，查「金枝」至少命中一条且 book_id 可寻址
    rows = S.find("金枝")
    assert len(rows) >= 1
    assert all(r.get("book_id") for r in rows)


def test_parse_reads():
    assert S.parse_reads("24.1万") == 241000
    assert S.parse_reads("1.2亿") == 120000000
    assert S.parse_reads(3000) == 3000


def test_scoring_rank():
    books = S.all_books(rank_type="read", gender="female")
    ranked = SC.rank_books(books, top=5)
    assert len(ranked) >= 3
    # 分数在 0-100
    assert all(0 <= b["score"] <= 100 for b in ranked)
    # 已完结且套路清晰的应排前面（新婚渐热：完结+豪门+高在读）
    assert ranked[0]["score"] >= ranked[-1]["score"]
    # breakdown 字段存在
    assert "s_trope" in ranked[0]


def test_scoring_no_intro_safe():
    # 无 intro 的书不应崩，给中性分
    b = {"title": "x", "reads": 100000, "chapters": 130, "status": "已完结", "intro": "", "category": "c"}
    out = SC.score_book(b, 1000000, 1, {})
    assert 0 <= out["score"] <= 100


def test_category_heat():
    books = S.all_books(rank_type="read", gender="female")
    heat = SC.category_heat(books)
    assert isinstance(heat, dict) and len(heat) > 0


def test_cross_signal():
    # 用内存构造同书出现在新书榜+阅读榜的场景，验证跨榜信号正确
    new_b = [{"title": "A", "book_id": "11", "reads": "10000", "category": "c"},
             {"title": "独书", "book_id": "22", "reads": "50", "category": "c"}]
    read_b = [{"title": "A", "book_id": "11", "reads": "300000", "category": "c"},
              {"title": "B", "book_id": "33", "reads": "99999", "category": "c"}]
    cross = AN.cross_signal(new_b, read_b)
    assert [c["title"] for c in cross] == ["A"]
    assert cross[0]["read_reads"] == 300000 and cross[0]["new_reads"] == 10000


def test_hotwords():
    books = S.all_books(rank_type="read", gender="female")
    hw = AN.hotwords(books, top=5)
    assert len(hw) > 0 and "count" in hw[0]


def test_trend():
    # 仓库内置为单日真实快照，趋势差分用内存构造两份数据验证：进/出/排名变化三路
    now = [
        {"title": "新书A", "book_id": "1", "reads": "100"},
        {"title": "仍在榜B", "book_id": "2", "reads": "300"},
    ]
    prev = [
        {"title": "仍在榜B", "book_id": "2", "reads": "200"},
        {"title": "掉出书C", "book_id": "3", "reads": "50"},
    ]
    t = AN.trend(now, prev)
    assert [e["title"] for e in t["entered"]] == ["新书A"]
    assert [d["title"] for d in t["dropped"]] == ["掉出书C"]
    m = t["moved"][0]
    assert m["title"] == "仍在榜B" and m["delta_pos"] == -1 and m["delta_reads"] == 100
    assert t["summary"]["now_count"] == 2


def test_stats():
    st = S.stats()
    assert st["snapshots"] >= 3 and st["with_book_id"] > 0


def test_is_nonfiction():
    # 出版教程书应被识别为非虚构
    book = {"title": "运营一本通", "intro": "本书讲解了行业数据分析方法论",
            "author": "某商学院"}
    assert SC.is_nonfiction(book)[0] is True
    # 正常小说不应被误判
    fic = {"title": "重生豪门娇妻", "intro": "她重生了，前世废物今世打脸",
           "author": "虚构作者"}
    assert SC.is_nonfiction(fic)[0] is False
