# -*- coding: utf-8 -*-
"""仿写选书评分：数据驱动的多维评分模型（方寸真金白银验证过的资产）。

两套评分：
  1. rank_books / score_book —— 完结短书（女频主体）：六维 + 加成。
  2. rank_serial           —— 男频连载母本：连载体量 × 在读 × 更新活跃 × 吸量 × 套路 × 金手指。

设计原则（与方寸研发规范一致）：
  - 数据驱动，不发明静态池子。所有阈值来自实测而非拍脑袋（见各函数 docstring 的调研出处）。
  - 评分维度归一化到 0-100，加权求和；缺失值用「观测中位数」中性填补，保证分数可比。
  - 纯标准库，零第三方依赖。

字段约定（来自 schema.normalize_book 后的单本）：
  title, author, category, reads(int), words(int), status, intro, gender,
  可选：boards(list[str]), days(int 持续在榜天数), peak(bool), peak_female(bool)
"""
from __future__ import annotations

import math
from collections import defaultdict

# ── 体量适配：目标区间（字）──
# 仿写产出 90-200 章 × 2250 字 = 20-45 万字，episodes 默认与源书章数 1:1（纯扩写原则）
# → 源书体量≈产出体量。老理想带 40-80 万会制造 0.5-0.85 强缩写——
# 2026-08-31 调研实锤：缩放无显式机制=丢尾/空锚。
# 用户定调：百万字长书不作仿写源（>100 万 = 最低分）。
WORDS_LO, WORDS_BEST_LO, WORDS_BEST_HI, WORDS_HI = 150_000, 200_000, 500_000, 1_000_000

# 套路词典（简介命中数 = 骨架清晰度代理指标）
TROPE = [
    "穿越", "重生", "快穿", "系统", "豪门", "总裁", "替身", "假千金", "联姻", "契约",
    "萌宝", "穿成", "种田", "经商", "发家", "年代", "七零", "军婚", "战神", "赘婿",
    "修真", "修仙", "王妃", "世子", "侯爷", "太子", "宫", "嫡女", "庶女", "虐渣",
    "白月光", "团宠", "万人迷", "马甲", "大佬", "病娇", "偏执", "强制", "开局",
    "签到", "无敌", "升级", "末世", "废柴", "逆袭", "打脸", "复仇", "闪婚",
    "先婚后爱", "带娃", "隐婚", "破镜重圆", "娱乐圈", "直播", "美食", "外卖",
    "玄学", "悬疑", "刑侦", "灵异", "星际", "兽世", "基建", "神豪", "神医",
    "摄政", "女帝", "冲喜", "换亲", "追妻", "火葬场", "双洁", "甜宠", "宠妻",
]

STATUS_DONE = ("已完结", "完结")

# ── 金手指词表（简介命中 = 金手指类型清晰度代理指标）──
# 命中 0 种 = 金手指不明（仿写无从抓核心机制，低分）；1-2 种 = 单一清晰（好仿写，满分）；
# ≥3 种 = 金手指堆叠（结构杂、仿写难，降分）。
GOLDEN_FINGER = [
    "系统", "穿书", "快穿", "重生", "穿越", "读心术", "听心声", "直播", "签到", "无敌",
    "升级", "金手指", "马甲", "神豪", "神医", "囤物资", "规则怪谈", "聊天群", "卡牌",
    "弹幕", "玄学", "鉴宝", "种田", "基建", "御兽", "错位系统", "无系统", "苟道",
    "倒计时", "天幕", "绑定", "空间", "商城", "兑换", "异能", "预知",
]

# ── 女频专属分类（判定巅峰榜书归属频道）──
FEMALE_CATEGORIES = {
    "古风世情", "女频衍生", "玄幻言情", "种田", "年代",
    "现言脑洞", "宫斗宅斗", "古言脑洞", "快穿", "青春甜宠", "星光璀璨",
    "女频悬疑", "职场婚恋", "豪门总裁", "民国言情",
}

# ── 非虚构识别 ──
# 番茄榜单/搜索池里混有大量出版类实操书（运营教程、行业分析、创业指南）。
# 这类书没有人物/情节/事件线，拆不出结构参照，也无法仿写，进池纯属污染。
NONFIC_TITLE = ("一本通", "步法", "7步", "心法", "秘笈", "攻略", "指南", "宝典",
                "手册", "教程", "实战", "运营", "营销", "管理学", "创业", "开店",
                "进化逻辑", "成长逻辑", "之道", "法则", "图解", "入门", "进阶",
                "全书", "解读", "案例", "白皮书", "方法论", "商学")
NONFIC_ABS = ("本书", "该书", "全书", "作者在", "读者", "章节", "内容分为",
              "实操", "干货", "方法论", "案例分析", "行业", "企业", "市场份额",
              "数据分析", "经验总结", "讲解", "教你", "帮助你", "出版", "编著",
              "本书的内容", "为您进行解答", "一一为", "系统性图书", "从业者")
FICTION_ABS = ("系统", "宿主", "重生", "穿越", "金手指", "打脸", "恭喜宿主",
               "我竟然", "没想到", "醒来", "前世", "退婚", "废物", "老祖",
               "修为", "冷笑", "咬牙", "他说", "她说", "剧情", "主角",
               "小说", "故事", "叶", "陆", "林", "苏")
NONFIC_AUTHOR = ("美团", "饿了么", "编辑部出版", "营销铁军", "出版社", "研究院",
                 "商学院", "课题组")


def is_nonfiction(b: dict) -> tuple[bool, str]:
    """判定是否为非虚构（出版实操/行业分析类），返回 (bool, 证据串)。

    加权规则：书名信号权重 2、简介信号权重 1、作者机构信号权重 3。
    小说反信号按 1 抵扣。阈值 >=3 且净值为正。
    """
    t = b.get("title") or ""
    ab = b.get("intro") or b.get("abstract") or ""
    au = b.get("author") or ""
    hit_t = [k for k in NONFIC_TITLE if k in t]
    hit_a = [k for k in NONFIC_ABS if k in ab]
    hit_u = [k for k in NONFIC_AUTHOR if k in au]
    hit_f = [k for k in FICTION_ABS if k in ab]
    score = len(hit_t) * 2 + len(hit_a) + len(hit_u) * 3 - len(hit_f)
    ev = "/".join(hit_t + hit_u + hit_a[:3]) or "-"
    return (score >= 3, ev)


# ── 女频完结短书评分维度 ──

def score_words(w: int) -> float:
    """体量适配：20-50 万 = 100 分，两侧线性衰减；>100 万最低分。"""
    if w <= 0:
        return 30.0
    if WORDS_BEST_LO <= w <= WORDS_BEST_HI:
        return 100.0
    if w < WORDS_BEST_LO:
        if w < WORDS_LO:
            return 25.0
        return 40 + 60 * (w - WORDS_LO) / (WORDS_BEST_LO - WORDS_LO)
    if w > WORDS_HI:
        return 15.0
    return 100 - 70 * (w - WORDS_BEST_HI) / (WORDS_HI - WORDS_BEST_HI)


def score_reads(r: int, rmax: int) -> float:
    """市场验证：对数归一（避免头部一本吃掉全部分数）。"""
    if r <= 0 or rmax <= 0:
        return 20.0
    return 100 * math.log10(1 + r) / math.log10(1 + rmax)


def score_trope(intro: str) -> float:
    """套路密度：命中 6 个及以上 = 满分。"""
    if not intro:
        return 20.0
    n = sum(1 for k in TROPE if k in intro)
    return min(100.0, 20 + n * 14)


def score_gf(intro: str) -> float:
    """金手指清晰度（可仿写性）：1-2 种满分；0 种低分；≥3 种堆叠降分。"""
    if not intro:
        return 20.0
    n = sum(1 for k in GOLDEN_FINGER if k in intro)
    if n == 0:
        return 25.0
    if n <= 2:
        return 100.0
    return max(30.0, 100 - (n - 2) * 25)


def category_heat(books: list[dict]) -> dict:
    """题材吸量指数：按类目聚合榜单信号（数据驱动，不发明判据）。

    heat = 在读总量对数归一 × 上榜本数因子 × (1 + 0.3×新书榜占比)。
    返回 {category: 0-100}。"""
    agg = defaultdict(lambda: {"n": 0, "reads": 0, "new": 0})
    for b in books:
        c = b.get("category") or "未分类"
        a = agg[c]
        a["n"] += 1
        a["reads"] += max(0, int(b.get("reads") or 0))
        if any(str(bd).endswith("_new") for bd in (b.get("boards") or [])):
            a["new"] += 1
    rmax = max((a["reads"] for a in agg.values()), default=1)
    heat = {}
    for c, a in agg.items():
        if a["n"] == 0 or rmax <= 0:
            continue
        nf = min(2.0, a["n"] / 10.0)
        rf = math.log10(1 + a["reads"]) / math.log10(1 + rmax)
        nw = 1 + 0.3 * a["new"] / a["n"]
        heat[c] = round(100 * nf * rf * nw, 1)
    return heat


def score_book(b: dict, rmax: int, dmax: int, heat: dict) -> dict:
    """六维评分单本（含加成），返回带 breakdown 的副本。

    权重（吸量与可仿写优先）：
      完结度 20 / 体量适配 20 / 单本热度 15 / 题材吸量 15 / 套路密度 15 / 金手指清晰 15
    """
    has_r = int(b.get("reads") or 0) > 0
    s_done = 100.0 if any(k in (b.get("status") or "") for k in STATUS_DONE) else 40.0
    s_r = score_reads(int(b.get("reads") or 0), rmax) if has_r else _median_reads(rmax)
    s_t = score_trope(b.get("intro") or "")
    s_gf = score_gf(b.get("intro") or "")
    s_w = score_words(int(b.get("words") or 0))
    s_heat = heat.get(b.get("category"), _median_heat(heat))

    total = s_done * 0.20 + s_w * 0.20 + s_r * 0.15 + s_heat * 0.15 + s_t * 0.15 + s_gf * 0.15

    # 稳定性加成：持续在榜天数（长期霸榜=套路耐看），最高 +8
    dstab = min(8.0, 8.0 * int(b.get("days", 0)) / max(dmax, 1))
    total += dstab
    # 新书榜优先：近期起量爆款信号，+6
    if any(str(bd).endswith("_new") for bd in (b.get("boards") or [])):
        total += 6
    # 跨榜加成：同时命中阅读榜+新书榜，+4
    if len(b.get("boards") or []) >= 2:
        total += 4
    # 巅峰榜加成：平台月度精选，+8；女频专属再 +4
    if b.get("peak"):
        total += 8
    if b.get("peak_female"):
        total += 4

    out = dict(b)
    out["score"] = round(min(100.0, total), 1)
    out["s_done"] = round(s_done)
    out["s_words"] = round(s_w)
    out["s_reads"] = round(s_r)
    out["s_heat"] = round(s_heat)
    out["s_trope"] = round(s_t)
    out["s_gf"] = round(s_gf)
    out["s_stable"] = round(dstab, 1)
    out["trope_hits"] = sum(1 for k in TROPE if k in (b.get("intro") or ""))
    out["gf_hits"] = sum(1 for k in GOLDEN_FINGER if k in (b.get("intro") or ""))
    return out


def _median_reads(rmax: int) -> float:
    """缺乏数据时返回中性分（与 rank() 中位数填补一致）。"""
    return 50.0


def _median_heat(heat: dict) -> float:
    vals = sorted(v for v in heat.values() if v > 0)
    return vals[len(vals) // 2] if vals else 50.0


def rank_books(books: list[dict], top: int | None = None) -> list[dict]:
    """完结短书六维评分 + 排序。"""
    if not books:
        return []
    rmax = max((int(b.get("reads") or 0) for b in books), default=1)
    dmax = max((int(b.get("days", 0)) for b in books), default=1)
    heat = category_heat(books)
    out = [score_book(b, rmax, dmax, heat) for b in books]
    out.sort(key=lambda x: -x["score"])
    return out[:top] if top else out


# ── 男频连载母本评分 ──

SERIAL_WORDS_LO, SERIAL_WORDS_BEST = 500_000, 1_000_000


def score_serial_words(w: int) -> float:
    """连载母本体量：50 万起步，100 万+ 满分（与女频 20-50 万最优相反）。"""
    if w <= 0:
        return 30.0
    if w >= SERIAL_WORDS_BEST:
        return 100.0
    if w <= SERIAL_WORDS_LO:
        return 30 + 70 * max(0.0, w - 200_000) / (SERIAL_WORDS_LO - 200_000)
    return 70 + 30 * (w - SERIAL_WORDS_LO) / (SERIAL_WORDS_BEST - SERIAL_WORDS_LO)


def score_update_fresh(last_ts, now_ts) -> float:
    """更新活跃度：7 天内更新=满分；超 30 天未更=低分（大概率弃坑）。"""
    try:
        last = float(last_ts)
    except (TypeError, ValueError):
        return 60.0
    if last <= 0:
        return 60.0
    age_days = (now_ts - last) / 86400
    if age_days <= 7:
        return 100.0
    if age_days <= 30:
        return max(40.0, 100 - (age_days - 7) * 2.4)
    return 25.0


def rank_serial(books: list[dict], top: int | None = None) -> list[dict]:
    """男频连载母本：连载体量 × 在读 × 更新活跃 × 题材吸量 × 套路 × 金手指。

    权重：连载体量 25 / 在读 25 / 更新活跃 15 / 题材吸量 15 / 套路 10 / 金手指 10。
    """
    import time
    if not books:
        return []
    heat = category_heat(books)
    rmax = max((int(b.get("reads") or 0) for b in books), default=1)
    now_ts = time.time()
    h_impute = _median_heat(heat)
    r_obs = sorted(score_reads(b["reads"], rmax) for b in books if b.get("reads", 0) > 0)
    r_impute = r_obs[len(r_obs) // 2] if r_obs else 50.0
    out = []
    for b in books:
        s_w = score_serial_words(int(b.get("words") or 0))
        s_r = score_reads(int(b.get("reads") or 0), rmax) if b.get("reads", 0) > 0 else r_impute
        s_up = score_update_fresh(b.get("last_update_time"), now_ts)
        s_heat = heat.get(b.get("category"), h_impute)
        s_t = score_trope(b.get("intro") or "")
        s_gf = score_gf(b.get("intro") or "")
        total = s_w * 0.25 + s_r * 0.25 + s_up * 0.15 + s_heat * 0.15 + s_t * 0.10 + s_gf * 0.10
        if any(str(bd).endswith("_new") for bd in (b.get("boards") or [])):
            total += 6
        if b.get("peak"):
            total += 6
        b2 = dict(b)
        b2["score"] = round(min(100.0, total), 1)
        b2["s_serial_words"] = round(s_w)
        b2["s_update"] = round(s_up)
        b2["s_reads"] = round(s_r)
        b2["s_heat"] = round(s_heat)
        b2["trope_hits"] = sum(1 for k in TROPE if k in (b.get("intro") or ""))
        b2["gf_hits"] = sum(1 for k in GOLDEN_FINGER if k in (b.get("intro") or ""))
        out.append(b2)
    out.sort(key=lambda x: -x["score"])
    return out[:top] if top else out
