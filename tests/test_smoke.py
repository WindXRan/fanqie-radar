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
    rows = S.find("金枝")
    assert len(rows) >= 1
    assert rows[0]["book_id"] == "1000000004"


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
    b = {"title": "x", "reads": 100000, "words": 300000, "status": "已完结", "intro": "", "category": "c"}
    out = SC.score_book(b, 1000000, 1, {})
    assert 0 <= out["score"] <= 100


def test_category_heat():
    books = S.all_books(rank_type="read", gender="female")
    heat = SC.category_heat(books)
    assert isinstance(heat, dict) and len(heat) > 0


def test_cross_signal():
    new_b = S.all_books(rank_type="new", gender="female")
    read_b = S.all_books(rank_type="read", gender="female")
    cross = AN.cross_signal(new_b, read_b)
    # 新书榜里有 逆袭：前夫跪求复合 也在阅读榜
    assert any(c["title"].startswith("逆袭") for c in cross)


def test_hotwords():
    books = S.all_books(rank_type="read", gender="female")
    hw = AN.hotwords(books, top=5)
    assert len(hw) > 0 and "count" in hw[0]


def test_trend():
    now = S.all_books(rank_type="read", gender="female",
                      file="fanqie_female_read_ranks_20260905.json")
    prev = S.all_books(rank_type="read", gender="female",
                       file="fanqie_female_read_ranks_20260904.json")
    t = AN.trend(now, prev)
    # 京圈公主抢我男友 在第1天数据、第2天掉出 → dropped 应含它
    dropped_titles = [d["title"] for d in t["dropped"]]
    assert any("京圈" in tt for tt in dropped_titles)
    # 逆袭：前夫跪求复合 第2天新进 → entered 应含它
    entered_titles = [e["title"] for e in t["entered"]]
    assert any("逆袭" in tt for tt in entered_titles)
    assert t["summary"]["now_count"] == len(now)


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
