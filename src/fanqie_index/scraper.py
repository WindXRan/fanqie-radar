# -*- coding: utf-8 -*-
"""番茄小说榜单采集器：用 Playwright 无头浏览器抓取公开榜单数据。

数据来源：fanqienovel.com 公开排行榜页面（任何人可在浏览器中查看）。
输出格式：fanqie_{gender}_{rank}_ranks_{YYYYMMDD}.json（与 schema.py 契约一致）。

合规设计：
  - 固定延迟（默认每分类 5 秒），可配置
  - User-Agent 轮换
  - 只采集公开榜单信息（书名/作者/在读数/简介/封面/链接），不碰个人数据
  - 输出存入本地 data/ 目录，不上传不外传

使用：
  pip install fanqie-radar[scrape]
  fanqie-radar-scrape                    # 抓取全部 4 个榜
  fanqie-radar-scrape --gender female    # 只抓女频
  fanqie-radar-scrape --rank read        # 只抓阅读榜
  fanqie-radar-scrape --limit 30 --sleep 5
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows 控制台 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 番茄字体加密解码 ──────────────────────────────────────────────
_START_CODE = 58344  # 0xE3E0
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


def _extract_bookid(url: str) -> str:
    m = _URL_ID.search(url or "")
    return m.group(1) if m else ""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def ensure_dependencies(on_log=None):
    """检查并自动安装 Playwright + Chromium。返回 True 表示就绪。"""
    def log(msg):
        if on_log:
            on_log(msg)
        else:
            print(msg)

    # 1. 检查 playwright 包
    try:
        import playwright
        log("✓ Playwright 已安装")
    except ImportError:
        log("正在安装 Playwright（仅需一次）...")
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "playwright>=1.40"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log("✓ Playwright 安装完成")
        except Exception as e:
            log(f"✗ Playwright 安装失败: {e}")
            return False

    # 2. 检查 chromium 浏览器
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                p.chromium.launch(headless=True).close()
                log("✓ Chromium 浏览器已就绪")
            except Exception:
                log("正在下载 Chromium 浏览器（仅需一次，约 150MB）...")
                subprocess.check_call(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                log("✓ Chromium 下载完成")
    except Exception as e:
        log(f"✗ Chromium 安装失败: {e}")
        return False

    return True


def _scrape_rank_type(page, rank_config, limit=30, sleep_sec=5, on_log=None):
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
    for attempt in range(1, max_retries + 1):
        try:
            page.goto(init_url, wait_until="load", timeout=15000)
            page.wait_for_selector('a[href^="/page/"]', timeout=5000)
            break
        except Exception as e:
            if attempt < max_retries:
                log(f"  访问失败（第{attempt}次），重试...")
                time.sleep(3)
            else:
                log(f"  ✗ {rank_name} 访问失败（已重试{max_retries}次）")
                return

    categories_js = """
    () => {
        return Array.from(document.querySelectorAll('a'))
            .filter(a => a.href.includes('/rank/""" + str(gender) + "_" + str(rank_type) + """_'))
            .map(a => ({ name: a.innerText.trim(), href: a.getAttribute('href') }));
    }
    """
    categories = page.evaluate(categories_js)
    log(f"  {rank_name}: {len(categories)} 个分类")

    all_categories = []
    for ci, cat in enumerate(categories):
        cat_name = cat["name"]
        cat_href = cat["href"]
        log(f"[{_ts()}] {rank_name} ({ci+1}/{len(categories)}) {cat_name}")

        max_cat_retries = 3
        cat_switch_success = False
        for cat_attempt in range(max_cat_retries):
            try:
                page.locator(f"a[href='{cat_href}']").click()
                time.sleep(2)
                page.wait_for_selector('a[href^="/page/"]', timeout=5000)
                cat_switch_success = True
                break
            except Exception as e:
                if cat_attempt < max_cat_retries - 1:
                    time.sleep(2)
                else:
                    log(f"  跳过 {cat_name}")

        if not cat_switch_success:
            continue

        max_scrolls = 25
        target_count = limit + 10
        scroll_count = 0
        no_new_count = 0

        while scroll_count < max_scrolls:
            try:
                current_count = page.evaluate("() => document.querySelectorAll('a[href^=\"/page/\"]').length")
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(2)
                scroll_count += 1
                new_count = page.evaluate("() => document.querySelectorAll('a[href^=\"/page/\"]').length")
                if new_count > current_count:
                    no_new_count = 0
                else:
                    no_new_count += 1
                if new_count >= target_count or no_new_count >= 5:
                    break
            except Exception:
                break

        extract_js = """
        () => {
            const bookMap = new Map();
            const links = document.querySelectorAll('a[href^="/page/"]');
            links.forEach(link => {
                let container = link.parentElement;
                let depth = 0;
                while (container && depth < 6) {
                    if (container.querySelector('img') && container.innerText.includes('在读')) {
                        const href = link.getAttribute('href');
                        if (!bookMap.has(href)) bookMap.set(href, container);
                        break;
                    }
                    container = container.parentElement;
                    depth++;
                }
            });
            const cards = Array.from(bookMap.values());
            const results = [];
            for (const item of cards) {
                let imgNode = item.querySelector('img');
                let cover = "";
                if (imgNode) {
                    cover = imgNode.getAttribute('src') || imgNode.getAttribute('data-src') || "";
                    if (!cover || cover.startsWith('data:')) {
                        const style = imgNode.getAttribute('style') || '';
                        const bgMatch = style.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/);
                        if (bgMatch) cover = bgMatch[1];
                    }
                    if (!cover || cover.startsWith('data:')) {
                        let parent = imgNode.parentElement;
                        for (let i = 0; i < 3 && parent; i++) {
                            const ps = parent.getAttribute('style') || '';
                            const pm = ps.match(/background-image:\\s*url\\(["']?([^"')]+)["']?\\)/);
                            if (pm) { cover = pm[1]; break; }
                            parent = parent.parentElement;
                        }
                    }
                }
                let title = imgNode && imgNode.getAttribute('alt') ? imgNode.getAttribute('alt').trim() : "";
                if (!title) {
                    let tn = item.querySelector('h4, .title, h1') || item.querySelector('a[href^="/page/"]');
                    if (tn) {
                        let text = tn.innerText.trim();
                        if (text && !/^\\d+$/.test(text)) title = text;
                    }
                }
                if (!title) title = "未知";
                if (title.includes("榜单说明")) continue;
                let authorNode = item.querySelector('.author, .author-name') || item.querySelector('a[href^="/author-page/"]');
                let author = authorNode ? authorNode.innerText.trim() : "未知";
                let reads = "未知";
                const lines = item.innerText.split('\\n');
                for (const line of lines) {
                    if (line.includes('在读')) { reads = line; break; }
                }
                let introNode = item.querySelector('.intro, .abstract, .desc');
                let intro = introNode ? introNode.innerText.trim() : "暂无简介";
                results.push({ title, author, reads, intro, cover, url: item.querySelector('a[href^="/page/"]').getAttribute('href') });
            }
            return results;
        }
        """

        try:
            books_data = page.evaluate(extract_js)
        except Exception:
            books_data = []

        category_books = []
        for b in books_data[:limit]:
            t = decode_text(b.get("title", ""))
            a = decode_text(b.get("author", ""))
            r_raw = decode_text(b.get("reads", ""))
            i = decode_text(b.get("intro", "")).replace("\n", " ")
            c = b.get("cover", "")

            if "在读" in r_raw:
                parts = r_raw.split("在读")
                cleaned_r = parts[1].replace(":", "").replace("：", "").strip() if len(parts) > 1 else r_raw
            else:
                cleaned_r = r_raw

            raw_url = b.get("url", "")
            if not raw_url:
                url = ""
            elif raw_url.startswith("http"):
                url = raw_url
            else:
                url = "https://fanqienovel.com" + raw_url

            category_books.append({
                "title": t, "author": a, "reads": cleaned_r,
                "intro": i, "cover": c, "url": url,
                "bookid": _extract_bookid(url),
            })

        all_categories.append({"name": cat_name, "books": category_books})
        log(f"  {cat_name}: {len(category_books)} 本")
        time.sleep(sleep_sec)

    snapshot = {"date": date_str, "rank_type": rank_name, "categories": all_categories}
    output_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(c["books"]) for c in all_categories)
    log(f"  ✓ {rank_name} 完成：{len(all_categories)} 分类，{total} 本")


def run_scraper(limit=30, sleep_sec=5, gender_filter="", rank_filter="", on_log=None):
    """抓取排行榜数据。gender_filter/rank_filter 为空时抓全部。on_log(msg) 回调进度。"""
    def log(msg):
        if on_log:
            on_log(msg)
        else:
            print(msg)

    # 自动检查/安装依赖
    if not ensure_dependencies(on_log=on_log):
        log("✗ 依赖安装失败，请手动运行: pip install fanqie-radar[scrape] && playwright install chromium")
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("✗ Playwright 仍不可用")
        return False

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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ua = random.choice(_USER_AGENTS)
            context = browser.new_context(user_agent=ua)
            page = context.new_page()
            for rc in configs:
                _scrape_rank_type(page, rc, limit, sleep_sec, on_log=on_log)
        finally:
            browser.close()

    log("✓ 全部采集完成！刷新看板即可查看新数据")
    return True


def main():
    ap = argparse.ArgumentParser(description="番茄小说榜单采集（Playwright 无头浏览器）")
    ap.add_argument("--gender", choices=["female", "male", "女频", "男频", "女", "男"], default="", help="只抓指定频道（默认全抓）")
    ap.add_argument("--rank", choices=["read", "new", "阅读榜", "新书榜"], default="", help="只抓指定榜单类型（默认全抓）")
    ap.add_argument("--limit", type=int, default=30, help="每个分类抓取上限（默认 30）")
    ap.add_argument("--sleep", type=float, default=5, help="每个分类间延迟秒数（默认 5）")
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
