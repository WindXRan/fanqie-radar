# -*- coding: utf-8 -*-
"""番茄榜单快照：目录探测 + 元数据解析 + 书目归一 + 查找/统计。

数据格式（本地快照，用户自备，本库不抓取也不内置）：

  文件名约定（这是接入本库的契约）：
    fanqie_{channel}_{rank}_ranks_{YYYYMMDD}.json
      channel: female | male
      rank:    read(阅读榜) | new(新书榜) | peak(巅峰榜-可选) | completed(完结池-可选)

  文件内容（两种都兼容）：
    主格式（分类聚合）：
      {"date":"20260905","rank_type":"女频阅读榜",
       "categories":[{"name":"古风世情","books":[{书名叶子...}]}]}
    兼容格式（平铺）：
      {"date":"20260905","rank_type":"女频阅读榜","books":[{书名叶子...}]}

  书名叶子字段（自描述，缺什么算什么）：
    title, author, reads("24.1万"或整数), intro(简介,可选),
    url(fanqienovel.com/page/{book_id}), cover(封面URL,可选),
    status("已完结"/"连载中"), chapters(章节数,公开可获取,可选), bookid(可选, 缺失则从 url 提取),
    category(平铺格式下每本自带；分类格式由所在 category.name 注入)

设计铁律：
  - 纯标准库，零第三方依赖。
  - book_id 是唯一主键：bookid 字段优先，缺失自动从 url 提取，全量书目可寻址。
  - 不返回 intro 完整全文给外部（MCP 层遵守）；本层只负责加载。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

__all__ = [
    "data_dirs", "snapshot_files", "snapshots", "latest", "load_books",
    "all_books", "find", "stats", "parse_reads", "normalize_book",
]

_URL_ID = re.compile(r"/page/(\d+)")


def parse_reads(s) -> int:
    """番茄在读数 → int：'50.6万'→506000、'1.2亿'→120000000、'3000'→3000、None→0。

    兼容 int/float 输入；无单位纯数字按原值返回；解析失败返回 0。
    """
    if isinstance(s, (int, float)):
        return int(s)
    if not s:
        return 0
    s = str(s).strip()
    m = re.match(r"([\d.]+)\s*(万|亿)?", s)
    if not m:
        return 0
    v = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        v *= 10_000
    elif unit == "亿":
        v *= 100_000_000
    return int(v)


def data_dirs() -> list[Path]:
    """快照目录探测序（首个含 fanqie_*_ranks_*.json 者生效，可 env 覆盖）。

    探测顺序：
      1. $FANQIE_INDEX_DATA_DIRS（os.pathsep 分隔，可放多个）
      2. 环境变量 FANQIE_INDEX_DATA_DIR（单目录）
      3. ./data（运行目录下的 data/）
      4. 包内置示例数据（零配置兜底：装完即用，无需任何配置）
    """
    pkg = Path(__file__).parent / "sample_data"
    env = os.environ.get("FANQIE_INDEX_DATA_DIRS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p.strip()]
    single = os.environ.get("FANQIE_INDEX_DATA_DIR")
    dirs = [Path(d) for d in (single,) if d]
    dirs.append(Path.cwd() / "data")
    dirs.append(pkg)
    # 只认真有快照的目录（空的 ./data 不挡包内兜底）
    has_snap = [d for d in dirs if d.is_dir() and any(d.glob("fanqie_*_ranks_*.json"))]
    return has_snap or [pkg]


def snapshot_files(dirs: list[Path] | None = None) -> list[Path]:
    """全部指数快照（去重、按文件名排序=日期序）。dirs=None 自动探测。"""
    seen, out = set(), []
    for d in (dirs or data_dirs()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("fanqie_*_ranks_*.json")):
            key = f.name
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
    return sorted(out, key=lambda p: p.name)


def _parse_meta(fname: str, data: dict) -> dict:
    """从文件名+内容解析 rank_type/gender/date（文件名为准，内容兜底）。"""
    base = Path(fname).stem  # fanqie_female_read_ranks_20260905 或 fanqie_peak_female_ranks_20260820
    # 约定（gender 在前）：fanqie_{gender}_{rank}_ranks_{YYYYMMDD}
    # 兼容（gender 在后）：fanqie_{rank}_{gender}_ranks_{YYYYMMDD}
    gender, rank_type, date = "", "", str(data.get("date") or "")
    m = re.match(r"fanqie_(female|male)_([a-z_]+?)_ranks_(\d{8})$", base)
    if m:
        gender, rank_type, date = m.group(1), m.group(2), m.group(3)
    else:
        m = re.match(r"fanqie_([a-z_]+?)_(female|male)_ranks_(\d{8})$", base)
        if m:
            rank_type, gender, date = m.group(1), m.group(2), m.group(3)
    return {"rank_type": rank_type or str(data.get("rank_type") or ""),
            "gender": gender or str(data.get("gender") or ""),
            "date": date}


def normalize_book(b: dict, meta: dict, idx: int, category: str = "") -> dict:
    """归一化单本：book_id 必有（bookid → url 提取）。"""
    bid = str(b.get("bookid") or "").strip()
    url = b.get("url") or ""
    if not bid:
        m = _URL_ID.search(url)
        bid = m.group(1) if m else ""
    cat = category or b.get("category") or ""
    raw_reads = b.get("raw_reads")
    reads = int(raw_reads) if isinstance(raw_reads, (int, float)) and raw_reads > 0 else parse_reads(b.get("reads"))
    return {
        "book_id": bid,
        "title": (b.get("title") or "").strip(),
        "author": (b.get("author") or "").strip(),
        "category": cat.strip(),
        "reads": reads,
        "reads_raw": (b.get("reads") or "") if isinstance(b.get("reads"), str) else "",
        "status": (b.get("status") or "").strip(),
        "chapters": int(b.get("chapters") or 0) or 0,
        "intro": (b.get("intro") or "").strip(),
        "url": url,
        "cover": b.get("cover") or "",
        "rank_type": meta["rank_type"],
        "gender": meta["gender"],
        "date": meta["date"],
        "source_file": meta["file"],
        "rank_pos": idx + 1,
    }


def load_books(file: Path) -> list[dict]:
    """读单个快照 → 归一化 flat 书目（book_id 全量可寻址，category 已注入）。"""
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    meta = {**_parse_meta(Path(file).name, data), "file": Path(file).name}
    books: list[dict] = []
    for cat in (data.get("categories") or []):
        cname = cat.get("name") or ""
        for i, b in enumerate(cat.get("books") or []):
            books.append(normalize_book(b, meta, i, cname))
    # 兼容平铺 books
    flat = data.get("books")
    if flat is not None:
        for i, b in enumerate(flat):
            books.append(normalize_book(b, meta, i, b.get("category") or ""))
    return books


def snapshots(dirs: list[Path] | None = None) -> list[dict]:
    """全部快照（含元信息，文件名序）。"""
    out = []
    for f in snapshot_files(dirs):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"file": f.name, "path": str(f),
                    **_parse_meta(f.name, data),
                    "books": data.get("books") or []})
    return out


def latest(rank_type: str = "", gender: str = "",
           dirs: list[Path] | None = None) -> dict | None:
    """最新一份匹配快照（rank_type/gender 可选过滤，空=不过滤）。"""
    for s in reversed(snapshots(dirs)):
        if rank_type and s["rank_type"] != rank_type:
            continue
        if gender and s["gender"] != gender:
            continue
        return s
    return None


def all_books(rank_type: str = "", gender: str = "", file: str = "",
              dirs: list[Path] | None = None) -> list[dict]:
    """归一化书目：指定快照或最新匹配快照。"""
    if file:
        f = next((x for x in snapshot_files(dirs) if x.name == file), None)
        return load_books(f) if f else []
    s = latest(rank_type, gender, dirs)
    if s is None:
        return []
    f = next(x for x in snapshot_files(dirs) if x.name == s["file"])
    return load_books(f)


def find(query: str, limit: int = 20,
         dirs: list[Path] | None = None) -> list[dict]:
    """跨全部快照按书名/作者模糊查找（去重取最新，book_id 必有）。"""
    q = (query or "").strip().lower()
    if not q:
        return []
    best: dict[str, dict] = {}
    for f in snapshot_files(dirs):
        for b in load_books(f):
            hay = (b["title"] + " " + b["author"]).lower()
            if q in hay and b["book_id"]:
                key = b["book_id"]
                old = best.get(key)
                if old is None or b["date"] >= old["date"]:
                    best[key] = b
    rows = sorted(best.values(), key=lambda b: -int(b["date"] or 0))
    return rows[:max(1, min(int(limit), 100))]


def stats(dirs: list[Path] | None = None) -> dict:
    """数据概览。books 按 book_id 去重（同一本书在多日快照重复在榜只计一次，
    否则跨天累计行数会虚高数倍）；books_rows 保留原始累计行数备查。"""
    files = snapshot_files(dirs)
    ids: set[str] = set()
    rows = 0
    for f in files:
        for b in load_books(f):
            rows += 1
            if b["book_id"]:
                ids.add(b["book_id"])
    return {"snapshots": len(files), "books": len(ids), "books_rows": rows,
            "with_book_id": len(ids),
            "dirs": [str(d) for d in (dirs or data_dirs()) if d.is_dir()]}
