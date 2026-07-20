"""去重与聚类。

同一事件常被多个源报道(央行发了、新华社转了、财联社报了)。
不去重会导致简报冗余、信息过载。

策略(轻量、无外部依赖):
1. 精确指纹去重(标题归一化后相同)
2. 标题相似度聚类(字符级 Jaccard + 关键词重合)
3. 每个聚类保留 credibility 最高 + 内容最长的一条
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..sources.base import Item


def _normalize_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_title(title: str) -> str:
    """标题归一化:去标点、去空白、小写(对英文)。"""
    return "".join(c for c in title if c.isalnum()).lower()


def _char_jaccard(a: str, b: str) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _keyword_overlap(a: str, b: str) -> float:
    """关键实体词(数字、英文、≥3 字连续中文片段)重合度。"""
    tokens_a = set(_extract_tokens(a))
    tokens_b = set(_extract_tokens(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def _extract_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"\d+\.?\d*%?", text))
    tokens |= set(re.findall(r"[A-Za-z]+", text))
    cn_chunks = re.findall(r"[\u4e00-\u9fa5]{3,}", text)
    for chunk in cn_chunks:
        for i in range(0, len(chunk) - 2, 2):
            tokens.add(chunk[i : i + 3])
    return tokens


def _similarity(a: Item, b: Item) -> float:
    na = _normalize_title(a.title)
    nb = _normalize_title(b.title)
    if na and na == nb:
        return 1.0
    j = _char_jaccard(na, nb)
    k = _keyword_overlap(a.title + a.content[:200], b.title + b.content[:200])
    return max(j, k * 0.85)


def dedupe(items: list[Item], threshold: float = 0.55) -> list[Item]:
    """相似度去重,返回去重后的列表(按发布时间倒序)。"""
    clusters: list[list[Item]] = []
    for item in items:
        placed = False
        for cluster in clusters:
            if any(_similarity(item, ex) >= threshold for ex in cluster):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    result = [_pick_representative(c) for c in clusters]
    result.sort(key=lambda x: _normalize_dt(x.published_at), reverse=True)
    return result


def _pick_representative(cluster: list[Item]) -> Item:
    """从聚类里选一条代表:优先 credibility 高,其次内容更长。"""
    return max(
        cluster,
        key=lambda x: (x.credibility, len(x.content), x.published_at),
    )
