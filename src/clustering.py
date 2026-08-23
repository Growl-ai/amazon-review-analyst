from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils import safe_json_loads


@dataclass(frozen=True)
class Cluster:
    """
    文本聚类结果。

    输入：
    - name/summary/count/representative_quotes

    输出：
    - Cluster 实例
    """

    name: str
    summary: str
    count: int
    representative_quotes: List[str]


def build_clustering_prompt(sentiment_label: str, reviews: List[Dict[str, Any]], max_clusters: int = 6) -> str:
    """
    构建 LLM 聚类提示词。

    输入：
    - sentiment_label: "好评" 或 "差评"
    - reviews: [{"id":..,"text":..}, ...]
    - max_clusters: 最大簇数量

    输出：
    - prompt: str
    """
    items = [{"id": r.get("id"), "text": r.get("text")} for r in (reviews or []) if r.get("text")]
    payload = json.dumps(items, ensure_ascii=False)
    return f"""
你是跨境电商评论洞察分析师。请对以下“{sentiment_label}”评论做主题聚类，并输出结构化 JSON。

要求：
- 簇数量不超过 {int(max_clusters)}
- 每个簇给出：主题名、主题含义、该簇评论数、2-3 条代表性原句（原文引用）
- 只输出 JSON，不要任何解释文字

输出 JSON 结构：
{{
  "clusters": [
    {{
      "name": "主题名",
      "summary": "主题含义",
      "count": 12,
      "representative_quotes": ["原句1", "原句2"]
    }}
  ]
}}

评论数据（JSON）：
{payload}
""".strip()


def parse_clusters(llm_text: str) -> List[Cluster]:
    """
    解析 LLM 输出为 Cluster 列表。

    输入：
    - llm_text: 模型输出文本

    输出：
    - clusters: List[Cluster]
    """
    obj = safe_json_loads(llm_text)
    clusters = obj.get("clusters") if isinstance(obj, dict) else None
    if not isinstance(clusters, list):
        return []
    out: List[Cluster] = []
    for c in clusters:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        summary = str(c.get("summary") or "").strip()
        count = c.get("count")
        try:
            count_i = int(count)
        except Exception:
            count_i = 0
        quotes = c.get("representative_quotes") or []
        if not isinstance(quotes, list):
            quotes = []
        quotes = [str(q).strip() for q in quotes if str(q).strip()]
        if not name:
            continue
        out.append(Cluster(name=name, summary=summary, count=count_i, representative_quotes=quotes[:3]))
    return out


def clusters_to_markdown(title: str, clusters: List[Cluster]) -> str:
    """
    将聚类结果转为 Markdown 片段。

    输入：
    - title: 标题
    - clusters: Cluster 列表

    输出：
    - markdown: str
    """
    md = f"## {title}\n\n"
    if not clusters:
        return md + "暂无聚类结果。\n"
    for c in clusters:
        md += f"### {c.name}（{c.count}）\n\n"
        if c.summary:
            md += f"- 含义：{c.summary}\n"
        if c.representative_quotes:
            md += "- 代表性原句：\n"
            for q in c.representative_quotes:
                md += f"  - {q}\n"
        md += "\n"
    return md.strip() + "\n"


if __name__ == "__main__":
    demo = '{"clusters":[{"name":"易用","summary":"操作简单","count":2,"representative_quotes":["easy","simple"]}]}'
    print(clusters_to_markdown("好评聚类", parse_clusters(demo)))
