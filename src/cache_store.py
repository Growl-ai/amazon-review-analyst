from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def compute_run_key(payload: Dict[str, Any]) -> str:
    """
    计算缓存 key，用于同一批数据/同一配置的可复用结果定位。

    输入：
    - payload: dict（建议包含 asin/input_csv/tag_schema/model 等影响输出的要素）

    输出：
    - run_key: str（sha1 前 12 位）
    """
    text = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def get_cache_dir(run_key: str, base_dir: str | Path | None = None) -> Path:
    """
    获取缓存目录路径。

    输入：
    - run_key: 缓存 key
    - base_dir: 基础目录（默认 agents/review-analyst/output/cache）

    输出：
    - cache_dir: Path
    """
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent / "output" / "cache"
    return base / run_key


def load_tag_cache(cache_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """
    读取已缓存的打标结果。

    输入：
    - cache_dir: 缓存目录

    输出：
    - tag_by_review_id: {review_id: tag_map}
    """
    cache_dir = Path(cache_dir)
    path = cache_dir / "tagged_reviews.jsonl"
    if not path.exists():
        return {}

    tag_by_review_id: Dict[str, Dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        rid = str(obj.get("review_id") or "").strip()
        tag_map = obj.get("tag_map")
        if not rid or not isinstance(tag_map, dict):
            continue
        tag_by_review_id[rid] = tag_map
    return tag_by_review_id


def append_tag_cache(cache_dir: str | Path, review_id: str, tag_map: Dict[str, Any]) -> None:
    """
    追加写入单条评论的打标结果（JSONL），用于断点续跑。

    输入：
    - cache_dir: 缓存目录
    - review_id: 评论 ID
    - tag_map: 打标结果

    输出：
    - None
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "tagged_reviews.jsonl"
    record = {"review_id": str(review_id), "tag_map": tag_map}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_meta(cache_dir: str | Path, meta: Dict[str, Any]) -> None:
    """
    写入缓存元信息（便于追溯本次运行配置）。

    输入：
    - cache_dir: 缓存目录
    - meta: 元信息 dict

    输出：
    - None
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "meta.json").write_text(json.dumps(meta or {}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    key = compute_run_key({"asin": "B000TEST", "model": "demo"})
    d = get_cache_dir(key)
    write_meta(d, {"run_key": key})
