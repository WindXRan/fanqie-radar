# -*- coding: utf-8 -*-
"""番茄小说榜单采集器：直接 HTTP 请求 + __INITIAL_STATE__ 解析。

数据来源：fanqienovel.com 公开排行榜页面（任何人可在浏览器中查看）。
采集方式：urllib HTTP 请求（标准库，零第三方依赖），解析页面内嵌的 __INITIAL_STATE__ JSON。
输出格式：fanqie_{gender}_{rank}_ranks_{YYYYMMDD}.json（与 schema.py 契约一致）。

合规设计：
  - 固定延迟（默认 1s/分类），可配置
  - User-Agent 轮换
  - 只采集公开榜单信息（书名/作者/在读数/简介/封面/链接），不碰个人数据
  - 输出存入本地 data/ 目录，不上传不外传

使用：
  fanqie-radar-scrape                    # 抓取全部 4 个榜
  fanqie-radar-scrape --gender female    # 只抓女频
  fanqie-radar-scrape --rank read        # 只抓阅读榜
  fanqie-radar-scrape --limit 30 --sleep 1
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 番茄字体加密解码 ──────────────────────────────────────────────
_START_CODE = 58344
_CHAR_SEQUENCE = [
    "D", "在", "主", "特", "家", "军", "然", "表", "场", "4", "要", "只", "v", "和", "\uFFFD", "6", "别", "还", "g", "现", "儿", "岁", "\uFFFD", "\uFFFD", "此", "象", "月", "3", "出", "战", "工", "相", "o", "男", "直", "失", "世", "F", "都", "平", "文", "什", "V", "O", "将", "真", "T", "那", "当", "\uFFFD", "会", "立", "些", "u", "是", "十", "张", "学", "气", "大", "爱", "两", "命", "全", "后", "东", "性", "通", "被", "1", "它", "乐", "接", "而", "感", "车", "山", "公", "了", "常", "以", "何", "可", "话", "先", "p", "i", "叫", "轻", "M", "士", "w", "着", "变", "尔", "快", "l", "个", "说", "少", "色", "里", "安", "花", "远", "7", "难", "师", "放", "t", "报", "认", "面", "道", "S", "\uFFFD", "克", "地", "度", "I", "好", "机", "U", "民", "写", "把", "万", "同", "水", "新", "没", "书", "电", "吃", "像", "斯", "5", "为", "y", "白", "几", "日", "教", "看", "但", "第", "加", "候", "作", "上", "拉", "住", "有", "法", "r", "事", "应", "位", "利", "你", "声", "身", "国", "问", "马", "女", "他", "Y", "比", "父", "x", "A", "H", "N", "s", "X", "边", "美", "对", "所", "金", "活", "回", "意", "到", "z", "从", "j", "知", "又", "内", "因", "点", "Q", "三", "定", "8", "R", "b", "正", "或", "夫", "向", "德", "听", "更", "\uFFFD", "得", "告", "并", "本", "q", "过", "记", "L", "让", "打", "f", "人", "就", "者", "去", "原", "满", "体", "做", "经", "K", "走", "如", "孩", "c", "G", "给", "使", "物", "\uFFFD", "最", "笑", "部", "\uFFFD", "员", "等", "受", "k", "行", "一", "条", "果", "动", "光", "门", "头", "见", "往", "自", "解", "成", "处", "天", "能", "于", "名", "其", "发", "总", "母", "的", "死", "手", "入", "路", "进", "心", "来", "h", "时", "力", "多", "开", "已", "许", "d", "至", "由", "很", "界", "n", "小", "与", "Z", "想", "代", "么", "分", "生", "口", "再", "妈", "望", "次", "西", "风", "种", "带", "J", "\uFFFD", "实", "情", "才", "这", "\uFFFD", "E", "我", "神", "格", "长", "觉", "间", "年", "眼", "无", "不", "亲", "关", "结", "0", "友", "信", "下", "却", "重", "己", "老", "2", "音", "字", "m", "呢", "明", "之", "前", "高", "P", "B", "目", "太", "e", "9", "起", "稜", "她", "也", "W", "用", "方", "子", "英", "每", "理", "便", "四", "数", "期", "中", "C", "外", "样", "a", "海", "们", "任",
]


def decode_text(text: str) -> str:
    if not text:
        return ""
    result = []
    for char in text:
        code = ord(char)
        idx = code - _START_CODE
        if 0 <= idx < len(_CHAR_SEQUENCE):
            result.append(_CHAR_SEQUENCE[idx])
        else:
            result.append(char)
    return "".join(result)


# ── 排行榜配置 ────────────────────────────────────────────────────
RANK_CONFIGS = [
    {"gender": 1, "type": 1, "name": "男频新书榜", "prefix": "male_new",   "entry_cat": "1141"},
    {"gender": 1, "type": 2, "name": "男频阅读榜", "prefix": "male_read",  "entry_cat": "1141"},
    {"gender": 0, "type": 1, "name": "女频新书榜", "prefix": "female_new", "entry_cat": "1139"},
    {"gender": 0, "type": 2, "name": "女频阅读榜", "prefix": "female_read","entry_cat": "1139"},
]

_URL_ID = re.compile(r"/page/(\d+)")
_OUTPUT_DIR = Path.cwd() / "data"

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.DOTALL)


def _extract_bookid(url: str) -> str:
    m = _URL_ID.search(url or "")
    return m.group(1) if m else ""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _fetch(url: str, timeout: int = 15) -> str:
    """HTTP GET，返回 HTML 文本。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": random.choice(_USER_AGENTS),
        "Referer": "https://fanqienovel.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_state(html: str) -> dict:
    """从 HTML 中提取 window.__INITIAL_STATE__ JSON。"""
    m = _STATE_RE.search(html)
    if not m:
        m2 = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;", html, re.DOTALL)
        if not m2:
            return {}
        try:
            return json.loads(m2.group(1))
        except Exception:
            return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def _extract_categories(state: dict, gender: int, rank_type: int) -> list[dict]:
    """从 __INITIAL_STATE__ 中提取分类列表。"""
    cats = []
    try:
        rank = state.get("rank", {})
        cat_list = rank.get("category_list") or rank.get("categoryList") or []
        for c in cat_list:
            cid = str(c.get("category_id") or c.get("categoryId") or "")
            cname = c.get("category_name") or c.get("categoryName") or ""
            if cname and cid:
                cats.append({"name": cname, "id": cid})
    except Exception:
        pass

    if not cats:
        try:
            for key, val in state.items():
                if isinstance(val, dict):
                    for k2, v2 in val.items():
                        if isinstance(v2, list):
                            for item in v2:
                                if isinstance(item, dict):
                                    cid = str(item.get("category_id") or item.get("categoryId") or "")
                                    cname = item.get("category_name") or item.get("categoryName") or ""
                                    if cname and cid and cname not in [c["name"] for c in cats]:
                                        cats.append({"name": cname, "id": cid})
        except Exception:
            pass

    return cats


def _extract_books(state: dict) -> list[dict]:
    """从 __INITIAL_STATE__ 中提取书目列表。"""
    books = []
    try:
        rank = state.get("rank", {})
        book_list = rank.get("book_list") or rank.get("bookList") or []
        for b in book_list:
            books.append(b)
    except Exception:
        pass

    if not books:
        try:
            for key, val in state.items():
                if isinstance(val, dict):
                    for k2, v2 in val.items():
                        if isinstance(v2, list):
                            for item in v2:
                                if isinstance(item, dict) and ("book_name" in item or "bookName" in item):
                                    books.append(item)
        except Exception:
            pass

    return books


def _normalize_book(b: dict) -> dict:
    """从 __INITIAL_STATE__ 的原始书目数据归一化为快照格式。"""
    def get(*keys):
        for k in keys:
            if k in b and b[k]:
                return b[k]
        return ""

    title = decode_text(str(get("book_name", "bookName", "title")))
    author = decode_text(str(get("author", "author_name", "authorName")))
    raw_reads = str(get("reading_count", "readingCount", "reads", "read_count"))
    reads = decode_text(raw_reads)
    intro = decode_text(str(get("abstract", "intro", "description", "brief")))
    cover = str(get("cover_url", "coverUrl", "cover", "thumb_url", "thumbUrl"))
    bid = str(get("book_id", "bookId"))
    url = str(get("url", "page_url", "pageUrl"))
    if not url and bid:
        url = f"https://fanqienovel.com/page/{bid}"
    if not bid:
        bid = _extract_bookid(url)

    return {
        "title": title,
        "author": author,
        "reads": reads,
        "intro": intro.replace("\n", " "),
        "cover": cover,
        "url": url,
        "bookid": bid,
    }


def check_dependencies() -> tuple[bool, bool]:
    """HTTP 采集方式零第三方依赖，始终返回 (True, True)。"""
    return True, True


def ensure_dependencies(on_log=None) -> bool:
    """HTTP 采集方式零第三方依赖，无需安装。"""
    if on_log:
        on_log("✓ 无需安装依赖（使用标准库 urllib）")
    else:
        print("✓ 无需安装依赖（使用标准库 urllib）")
    return True


def _scrape_rank_type(rank_config, limit=30, sleep_sec=1, on_log=None):
    """采集单个榜单类型。"""
    def log(msg):
        if on_log:
            on_log(msg)
        else:
            print(msg)

    gender = rank_config["gender"]
    rank_type = rank_config["type"]
    rank_name = rank_config["name"]
    prefix = rank_config["prefix"]
    entry_cat = rank_config.get("entry_cat", "1139")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    output_file = _OUTPUT_DIR / f"fanqie_{prefix}_ranks_{date_str}.json"

    init_url = f"https://fanqienovel.com/rank/{gender}_{rank_type}_{entry_cat}"
    log(f"[{_ts()}] 开始 {rank_name}")

    max_retries = 3
    html = ""
    for attempt in range(1, max_retries + 1):
        try:
            html = _fetch(init_url)
            break
        except Exception as e:
            if attempt < max_retries:
                log(f"  访问失败（第{attempt}次），重试...")
                time.sleep(2)
            else:
                log(f"  ✗ {rank_name} 访问失败（已重试{max_retries}次）: {e}")
                return

    if not html:
        log(f"  ✗ {rank_name} 页面为空")
        return

    state = _parse_state(html)
    if not state:
        log(f"  ✗ {rank_name} 无法解析 __INITIAL_STATE__")
        return

    # 提取分类列表
    categories = _extract_categories(state, gender, rank_type)

    # 如果从 __INITIAL_STATE__ 没找到分类列表，从 HTML 的 <a> 标签中提取
    if not categories:
        cat_links = re.findall(
            rf'href="(/rank/{gender}_{rank_type}_(\d+))"[^>]*>([^<]+)</a>',
            html
        )
        for href, cid, name in cat_links:
            name = name.strip()
            if name and name not in [c["name"] for c in categories]:
                categories.append({"name": name, "id": cid})

    log(f"  {rank_name}: {len(categories)} 个分类")

    # 初始页面的书籍
    init_books = _extract_books(state)

    all_categories = []

    # 如果初始页面有书籍且分类列表只有一个或没有分类列表，直接用初始数据
    if init_books and not categories:
        cat_name = "全部"
        books = [_normalize_book(b) for b in init_books[:limit]]
        all_categories.append({"name": cat_name, "books": books})
        log(f"  {cat_name}: {len(books)} 本")
    elif init_books and categories:
        # 初始页面的书籍属于第一个分类
        first_cat = categories[0]
        books = [_normalize_book(b) for b in init_books[:limit]]
        all_categories.append({"name": first_cat["name"], "books": books})
        log(f"[{_ts()}] {rank_name} (1/{len(categories)}) {first_cat['name']}")
        log(f"  {first_cat['name']}: {len(books)} 本")

        # 遍历剩余分类
        for ci, cat in enumerate(categories[1:], 2):
            cat_name = cat["name"]
            cat_id = cat["id"]
            log(f"[{_ts()}] {rank_name} ({ci}/{len(categories)}) {cat_name}")

            cat_url = f"https://fanqienovel.com/rank/{gender}_{rank_type}_{cat_id}"
            cat_html = ""
            for cat_attempt in range(3):
                try:
                    cat_html = _fetch(cat_url)
                    break
                except Exception:
                    if cat_attempt < 2:
                        time.sleep(2)
                    else:
                        log(f"  跳过 {cat_name}")

            if not cat_html:
                continue

            cat_state = _parse_state(cat_html)
            cat_books_raw = _extract_books(cat_state)

            if not cat_books_raw:
                time.sleep(sleep_sec)
                continue

            books = [_normalize_book(b) for b in cat_books_raw[:limit]]
            all_categories.append({"name": cat_name, "books": books})
            log(f"  {cat_name}: {len(books)} 本")
            time.sleep(sleep_sec)
    else:
        log(f"  ✗ {rank_name} 未找到书籍数据")
        return

    snapshot = {"date": date_str, "rank_type": rank_name, "categories": all_categories}
    output_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(c["books"]) for c in all_categories)
    log(f"  ✓ {rank_name} 完成：{len(all_categories)} 分类，{total} 本")


def run_scraper(limit=30, sleep_sec=1, gender_filter="", rank_filter="", on_log=None):
    """抓取排行榜数据。gender_filter/rank_filter 为空时抓全部。on_log(msg) 回调进度。"""
    def log(msg):
        if on_log:
            on_log(msg)
        else:
            print(msg)

    log("✓ HTTP 采集模式（零依赖，无需安装）")

    configs = RANK_CONFIGS
    if gender_filter:
        g = 0 if gender_filter in ("female", "女频", "女") else 1
        configs = [c for c in configs if c["gender"] == g]
    if rank_filter:
        r = 1 if rank_filter in ("new", "新书榜", "新书") else 2
        configs = [c for c in configs if c["type"] == r]

    log(f"开始采集 {len(configs)} 个榜单，每分类延迟 {sleep_sec}s，每分类上限 {limit} 本")
    log(f"输出目录：{_OUTPUT_DIR}")
    log("-" * 40)

    for rc in configs:
        _scrape_rank_type(rc, limit, sleep_sec, on_log=on_log)

    log("✓ 全部采集完成！刷新看板即可查看新数据")
    return True


def main():
    ap = argparse.ArgumentParser(description="番茄小说榜单采集（HTTP + __INITIAL_STATE__ 解析）")
    ap.add_argument("--gender", choices=["female", "male", "女频", "男频", "女", "男"], default="", help="只抓指定频道（默认全抓）")
    ap.add_argument("--rank", choices=["read", "new", "阅读榜", "新书榜"], default="", help="只抓指定榜单类型（默认全抓）")
    ap.add_argument("--limit", type=int, default=30, help="每个分类抓取上限（默认 30）")
    ap.add_argument("--sleep", type=float, default=1, help="每个分类间延迟秒数（默认 1）")
    ap.add_argument("--data", default="", help="输出目录（默认 ./data）")
    a = ap.parse_args()

    global _OUTPUT_DIR
    if a.data:
        _OUTPUT_DIR = Path(a.data)
    else:
        _OUTPUT_DIR = Path.cwd() / "data"

    run_scraper(limit=a.limit, sleep_sec=a.sleep, gender_filter=a.gender, rank_filter=a.rank)


if __name__ == "__main__":
    main()
