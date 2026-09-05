# -*- coding: utf-8 -*-
"""榜单分析：题材热度、跨榜强信号、书名热词、多日趋势差分。

全部为接收「归一化书目列表」的纯函数，不关心数据从哪来（MCP 层负责加载）。
纯标准库，零第三方依赖。
"""
from __future__ import annotations

from collections import Counter

from .scoring import TROPE

DEFAULT_HOTWORDS = list(TROPE)


def _key(b: dict) -> str:
    """书目主键：book_id 优先，缺失回退 title（兼容旧快照）。"""
    bid = (b.get("book_id") or "").strip()
    return bid if bid else (b.get("title") or "").strip()


def category_heat(books: list[dict]) -> list[dict]:
    """题材热度（阅读榜）：按在读总量排序，返回 [{category,count,total_reads,avg_reads}]。"""
    by_cat: dict[str, list[dict]] = {}
    for b in books:
        by_cat.setdefault(b.get("category") or "未分类", []).append(b)
    stats = []
    for name, bs in by_cat.items():
        tr = sum(int(b.get("reads") or 0) for b in bs)
        stats.append({
            "category": name,
            "count": len(bs),
            "total_reads": tr,
            "avg_reads": int(tr / len(bs)) if bs else 0,
        })
    stats.sort(key=lambda x: -x["total_reads"])
    return stats


def cross_signal(new_books: list[dict], read_books: list[dict]) -> list[dict]:
    """跨榜强信号：新书榜 ∩ 阅读榜 = 新书即爆款。

    返回按阅读榜在读降序的 [{title, new_reads, read_reads, book_id}]。
    """
    nk = {_key(b): b for b in new_books}
    rk = {_key(b): b for b in read_books}
    both = [k for k in nk if k in rk and k]
    both.sort(key=lambda k: -int(rk[k].get("reads") or 0))
    return [
        {
            "title": rk[k].get("title"),
            "book_id": rk[k].get("book_id"),
            "new_reads": int(nk[k].get("reads") or 0),
            "read_reads": int(rk[k].get("reads") or 0),
        }
        for k in both
    ]


def hotwords(books: list[dict], kws: list[str] | None = None, top: int = 20) -> list[dict]:
    """书名热词频次（默认用 TROPE 套路词表），返回 [{word, count}] 降序。"""
    kws = kws or DEFAULT_HOTWORDS
    kc: Counter = Counter()
    for b in books:
        t = b.get("title") or ""
        for k in kws:
            if k in t:
                kc[k] += 1
    return [{"word": w, "count": c} for w, c in kc.most_common(top)]


def trend(now_books: list[dict], prev_books: list[dict]) -> dict:
    """多日趋势差分：对比两个时间点的同一榜单。

    返回：
      entered   —— 新上榜 [{title, book_id, now_pos, reads}]
      dropped   —— 掉出榜单 [{title, book_id, prev_pos, prev_reads}]
      moved     —— 仍在榜但排名变化 [{title, book_id, prev_pos, now_pos, delta_pos, reads, delta_reads}]
      summary   —— 统计
    排名以列表顺序（rank_pos）为准；无 rank_pos 时按传入顺序索引。
    """
    now = {_key(b): (i + 1, b) for i, b in enumerate(now_books)}
    prev = {_key(b): (i + 1, b) for i, b in enumerate(prev_books)}

    entered, dropped, moved = [], [], []
    for k, (np_, b) in now.items():
        nb = int(b.get("reads") or 0)
        if k not in prev:
            entered.append({"title": b.get("title"), "book_id": b.get("book_id"),
                            "now_pos": np_, "reads": nb})
        else:
            pp_, pb = prev[k]
            delta = pp_ - np_  # 正数=排名上升
            moved.append({
                "title": b.get("title"), "book_id": b.get("book_id"),
                "prev_pos": pp_, "now_pos": np_, "delta_pos": delta,
                "reads": nb, "delta_reads": nb - int(pb.get("reads") or 0),
            })
    for k, (pp_, b) in prev.items():
        if k not in now:
            dropped.append({"title": b.get("title"), "book_id": b.get("book_id"),
                            "prev_pos": pp_, "prev_reads": int(b.get("reads") or 0)})

    moved.sort(key=lambda x: -x["delta_reads"])
    entered.sort(key=lambda x: -x["reads"])
    dropped.sort(key=lambda x: -x["prev_reads"])

    return {
        "entered": entered,
        "dropped": dropped,
        "moved": moved,
        "summary": {
            "now_count": len(now),
            "prev_count": len(prev),
            "entered": len(entered),
            "dropped": len(dropped),
            "moved": len(moved),
        },
    }
