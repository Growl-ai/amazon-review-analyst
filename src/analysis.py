from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from utils import iter_tag_triples


@dataclass(frozen=True)
class Overview:
    """
    数据概览统计。

    输入：
    - total_reviews/pos_reviews/neg_reviews/satisfaction/rating_distribution

    输出：
    - Overview 实例
    """

    total_reviews: int
    pos_reviews: int
    neg_reviews: int
    satisfaction: float
    rating_distribution: Dict[int, int]


def classify_sentiment(rating: float | None) -> str:
    """
    通过星级粗粒度划分情绪。

    输入：
    - rating: float|None

    输出：
    - sentiment: "pos" | "neg" | "neu"
    """
    if rating is None:
        return "neu"
    if rating >= 4:
        return "pos"
    if rating <= 3:
        return "neg"
    return "neu"


def compute_overview(raw_reviews: List[Dict[str, Any]]) -> Overview:
    """
    计算数据概览。

    输入：
    - raw_reviews: 抓取到的结构化评论列表

    输出：
    - Overview
    """
    dist: Dict[int, int] = {i: 0 for i in range(1, 6)}
    pos = 0
    neg = 0
    for r in raw_reviews or []:
        rating = r.get("rating")
        if isinstance(rating, (int, float)):
            star = int(round(float(rating)))
            star = min(5, max(1, star))
            dist[star] += 1
        s = classify_sentiment(rating if isinstance(rating, (int, float)) else None)
        if s == "pos":
            pos += 1
        elif s == "neg":
            neg += 1
    total = len(raw_reviews or [])
    satisfaction = (pos / total) if total else 0.0
    return Overview(total_reviews=total, pos_reviews=pos, neg_reviews=neg, satisfaction=satisfaction, rating_distribution=dist)


def compute_tag_frequency(tagged_reviews: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """
    统计标签频次（一级→二级→三级）。

    输入：
    - tagged_reviews: [{"original_review": {...}, "tag_map": {...}}, ...]

    输出：
    - counts: {level1: {level2: {level3: count}}}
    """
    counts: Dict[str, Dict[str, Dict[str, int]]] = {}
    for item in tagged_reviews or []:
        tag_map = item.get("tag_map") or {}
        for l1, l2, l3 in iter_tag_triples(tag_map):
            counts.setdefault(l1, {}).setdefault(l2, {})
            counts[l1][l2][l3] = counts[l1][l2].get(l3, 0) + 1
    return counts


def compute_tag_by_sentiment(tagged_reviews: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Dict[str, int]]]]:
    """
    统计标签在不同情绪/星级组中的出现次数。

    输入：
    - tagged_reviews: [{"original_review": {"rating":...}, "tag_map": {...}}, ...]

    输出：
    - counts: {l1:{l2:{l3:{"pos":x,"neg":y,"neu":z,"total":t}}}}
    """
    counts: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    for item in tagged_reviews or []:
        review = item.get("original_review") or {}
        rating = review.get("rating")
        s = classify_sentiment(rating if isinstance(rating, (int, float)) else None)
        tag_map = item.get("tag_map") or {}
        for l1, l2, l3 in iter_tag_triples(tag_map):
            counts.setdefault(l1, {}).setdefault(l2, {}).setdefault(l3, {"pos": 0, "neg": 0, "neu": 0, "total": 0})
            counts[l1][l2][l3][s] += 1
            counts[l1][l2][l3]["total"] += 1
    return counts


def _parse_date(date_str: str | None) -> _dt.date | None:
    date_str = (date_str or "").strip()
    if not date_str:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(date_str, fmt).date()
        except Exception:
            continue
    for fmt in ("%d-%b-%y", "%d-%b-%Y"):
        try:
            return _dt.datetime.strptime(date_str, fmt).date()
        except Exception:
            continue
    return None


def compute_monthly_sentiment_series(raw_reviews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    统计月度正负评论数量（时间维度）。

    输入：
    - raw_reviews: 原始评论列表（需包含 date/rating）

    输出：
    - rows: [{"month":"2024-01","pos":..,"neg":..,"total":..}, ...] 按 month 升序
    """
    by_month: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pos": 0, "neg": 0, "neu": 0, "total": 0})
    for r in raw_reviews or []:
        d = _parse_date(r.get("date"))
        if not d:
            continue
        month = f"{d.year:04d}-{d.month:02d}"
        rating = r.get("rating")
        s = classify_sentiment(rating if isinstance(rating, (int, float)) else None)
        by_month[month][s] += 1
        by_month[month]["total"] += 1
    rows = [{"month": m, **v} for m, v in sorted(by_month.items(), key=lambda x: x[0])]
    return rows


def top_level3_overall(counts: Dict[str, Dict[str, Dict[str, int]]], top_n: int = 12) -> List[Tuple[str, int]]:
    """
    聚合所有三级标签的总频次并取 TopN。

    输入：
    - counts: {l1:{l2:{l3:count}}}
    - top_n: int

    输出：
    - items: [(l3, count)]
    """
    agg: Dict[str, int] = defaultdict(int)
    for _, l2_map in (counts or {}).items():
        for _, l3_map in (l2_map or {}).items():
            for l3, c in (l3_map or {}).items():
                agg[l3] += int(c)
    return sorted(agg.items(), key=lambda x: x[1], reverse=True)[: max(1, int(top_n))]


def top_level3_sentiment(tag_sent: Dict[str, Dict[str, Dict[str, Dict[str, int]]]], top_n: int = 12) -> List[Tuple[str, int, int, int]]:
    """
    取总频次 TopN 的三级标签，并返回 (label, pos, neg, total)。

    输入：
    - tag_sent: {l1:{l2:{l3:{pos,neg,neu,total}}}}

    输出：
    - items: [(l3, pos, neg, total)]
    """
    agg: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pos": 0, "neg": 0, "total": 0})
    for _, l2_map in (tag_sent or {}).items():
        for _, l3_map in (l2_map or {}).items():
            for l3, c in (l3_map or {}).items():
                agg[l3]["pos"] += int(c.get("pos", 0))
                agg[l3]["neg"] += int(c.get("neg", 0))
                agg[l3]["total"] += int(c.get("total", 0))
    ranked = sorted(agg.items(), key=lambda x: x[1]["total"], reverse=True)[: max(1, int(top_n))]
    return [(k, v["pos"], v["neg"], v["total"]) for k, v in ranked]


def build_overview_markdown(overview: Overview) -> str:
    """
    将数据概览转为 Markdown 片段。

    输入：
    - overview: Overview

    输出：
    - markdown: str
    """
    md = "## 一、数据概览\n\n"
    md += f"- 总评论数：{overview.total_reviews}\n"
    md += f"- 正面评价(4-5星)：{overview.pos_reviews}\n"
    md += f"- 负面评价(1-3星)：{overview.neg_reviews}\n"
    md += f"- 满意度：{overview.satisfaction * 100:.1f}%\n\n"
    md += "### 评分分布\n\n"
    md += "| 星级 | 评论数 |\n"
    md += "| ---- | ---- |\n"
    for k in range(5, 0, -1):
        md += f"| {k}★ | {overview.rating_distribution.get(k, 0)} |\n"
    return md.strip() + "\n"


def build_tag_sentiment_markdown(tag_sent: Dict[str, Dict[str, Dict[str, Dict[str, int]]]]) -> str:
    """
    将“标签 × 情绪/星级”统计转为 Markdown 片段。

    输入：
    - tag_sent: {l1:{l2:{l3:{pos,neg,neu,total}}}}

    输出：
    - markdown: str
    """
    if not tag_sent:
        return "## 三、标签 × 情绪/星级\n\n暂无数据。\n"

    md = "## 三、标签 × 情绪/星级\n\n"
    md += "说明：正面=4-5星，负面=1-3星。\n\n"
    for l1, l2_map in tag_sent.items():
        md += f"### {l1}\n\n"
        for l2, l3_map in (l2_map or {}).items():
            md += f"#### {l2}\n\n"
            md += "| 三级标签 | 正面(4-5) | 负面(1-3) | 总计 |\n"
            md += "| ---- | ---- | ---- | ---- |\n"
            rows = []
            for l3, c in (l3_map or {}).items():
                rows.append((l3, int(c.get("pos", 0)), int(c.get("neg", 0)), int(c.get("total", 0))))
            for l3, pos, neg, total in sorted(rows, key=lambda x: x[3], reverse=True):
                md += f"| {l3} | {pos} | {neg} | {total} |\n"
            md += "\n"
        md += "\n"
    return md.strip() + "\n"


def build_monthly_series_markdown(rows: List[Dict[str, Any]]) -> str:
    """
    将月度时间序列统计转为 Markdown 片段。

    输入：
    - rows: [{"month":"YYYY-MM","pos":..,"neg":..,"total":..}, ...]

    输出：
    - markdown: str
    """
    md = "## 四、时间维度（按月）\n\n"
    if not rows:
        return md + "暂无可用日期数据。\n"
    md += "| 月份 | 正面(4-5) | 负面(1-3) | 总计 |\n"
    md += "| ---- | ---- | ---- | ---- |\n"
    for r in rows:
        md += f"| {r.get('month')} | {int(r.get('pos', 0))} | {int(r.get('neg', 0))} | {int(r.get('total', 0))} |\n"
    return md.strip() + "\n"


if __name__ == "__main__":
    demo_reviews = [
        {"rating": 5, "date": "January 1, 2024"},
        {"rating": 2, "date": "January 2, 2024"},
        {"rating": 4, "date": "February 1, 2024"},
    ]
    print(compute_overview(demo_reviews))
    print(compute_monthly_sentiment_series(demo_reviews))
