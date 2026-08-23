from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Tuple


def safe_json_loads(text: str) -> Any:
    """
    更健壮地解析 LLM 输出的 JSON。

    输入：
    - text: 可能包含前后解释文字的 JSON 文本

    输出：
    - obj: 解析后的 Python 对象（dict/list 等）
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty json")
    try:
        return json.loads(text)
    except Exception:
        pass

    list_match = re.search(r"\[[\s\S]*\]", text)
    if list_match:
        return json.loads(list_match.group(0))
    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        return json.loads(obj_match.group(0))
    raise ValueError("invalid json")


def build_tag_columns(tag_schema: Dict[str, Any]) -> List[str]:
    """
    根据标签体系生成 CSV 列名（一级-二级）。

    输入：
    - tag_schema: {"一级": {"二级": ["三级1", ...]}}

    输出：
    - columns: ["一级-二级", ...]，按 tag_schema 的遍历顺序生成
    """
    columns: List[str] = []
    if not isinstance(tag_schema, dict):
        return columns
    for level1, level2_map in tag_schema.items():
        if not isinstance(level2_map, dict):
            continue
        for level2 in level2_map.keys():
            columns.append(f"{level1}-{level2}")
    return columns


def iter_tag_triples(tag_map: Dict[str, Any]) -> Iterable[Tuple[str, str, str]]:
    """
    遍历单条评论的打标结果，展开为 (一级, 二级, 三级) 三元组。

    输入：
    - tag_map: {"一级": {"二级": ["三级1","三级2"]}}

    输出：
    - iterable of (level_1, level_2, level_3)
    """
    if not isinstance(tag_map, dict):
        return []
    triples: List[Tuple[str, str, str]] = []
    for level1, level2_map in tag_map.items():
        if not isinstance(level2_map, dict):
            continue
        for level2, level3_list in level2_map.items():
            if not isinstance(level3_list, list):
                continue
            for level3 in level3_list:
                if not level3:
                    continue
                triples.append((str(level1), str(level2), str(level3)))
    return triples


def build_analysis_markdown(tagged_reviews: List[Dict[str, Any]]) -> str:
    """
    生成符合项目说明的“标签频次统计”Markdown。

    输入：
    - tagged_reviews: [{"original_review": {...}, "tag_map": {...}}, ...]

    输出：
    - markdown: str
    """
    counts: Dict[str, Dict[str, Dict[str, int]]] = {}
    for item in tagged_reviews or []:
        tag_map = item.get("tag_map") or {}
        for l1, l2, l3 in iter_tag_triples(tag_map):
            counts.setdefault(l1, {}).setdefault(l2, {})
            counts[l1][l2][l3] = counts[l1][l2].get(l3, 0) + 1

    if not counts:
        return "# 标签频次统计\n\n未能从评论中提取到有效标签。"

    md = "# 标签频次统计\n\n"
    for level1, level2_map in counts.items():
        md += f"## {level1}\n"
        for level2, level3_counts in level2_map.items():
            md += f"### {level2}\n\n"
            md += "| 三级标签 | 频次 |\n"
            md += "| ---- | --- |\n"
            for level3, c in sorted(level3_counts.items(), key=lambda x: x[1], reverse=True):
                md += f"| {level3} | {c} |\n"
            md += "\n"
        md += "\n"
    return md.strip() + "\n"


if __name__ == "__main__":
    demo = [{"original_review": {"id": "r1", "text": "x"}, "tag_map": {"功能价值": {"核心功能": ["理毛效果"]}}}]
    print(build_analysis_markdown(demo))
