"""数据源统一接口与数据模型。所有数据源必须实现 BaseSource,返回 Item 列表。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Item:
    """标准化后的信息单元,贯穿整个流水线。"""

    source: str
    title: str
    content: str
    url: str
    published_at: datetime
    category: str = "news"
    credibility: int = 3
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """用于去重的指纹。基于标题归一化。"""
        normalized = "".join(c for c in self.title if c.isalnum())[:60]
        return normalized.lower()


@dataclass
class MarketSnapshot:
    """市场数据快照(不经过 LLM,直接结构化展示)。"""

    index_data: dict = field(default_factory=dict)
    northbound: Optional[dict] = None
    top_list: list = field(default_factory=list)
    limit_up_down: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class Analysis:
    """LLM 对单条 Item 的结构化判断。"""

    importance: int
    sectors: list[str]
    impact: str
    one_line: str
    evidence: str
    confidence: str = "single_source"
    reason: str = ""

    def validate(self, item: Item, valid_sectors: list[str]) -> tuple[bool, str]:
        """校验分析结果是否可信,返回 (是否通过, 原因)。"""
        if self.impact not in ("利好", "利空", "中性", "待观察"):
            return False, f"impact 字段非法: {self.impact}"
        if not 0 <= self.importance <= 5:
            return False, f"importance 越界: {self.importance}"
        if self.importance == 0:
            return True, "irrelevant"
        for s in self.sectors:
            if s not in valid_sectors:
                return False, f"板块名不在白名单: {s}"
        if len(self.sectors) > 2:
            return False, f"板块过多({len(self.sectors)}个),判断不聚焦"
        if not self.evidence or len(self.evidence) < 4:
            return False, "evidence 为空或过短"
        if not _evidence_matches_source(self.evidence, item):
            return False, "evidence 未在原文中出现,疑似幻觉"
        return True, "ok"


def _evidence_matches_source(evidence: str, item: Item, threshold: float = 0.6) -> bool:
    """检查 evidence 是否在原文/标题中。允许模糊匹配(LLM 经常改写)。

    策略:把 evidence 拆成 4 字片段,看有多少比例出现在原文中。
    """
    if evidence in item.content or evidence in item.title:
        return True
    pool = (item.content or "") + " " + (item.title or "")
    tokens = [evidence[i : i + 4] for i in range(max(1, len(evidence) - 3))]
    if not tokens:
        return False
    matched = sum(1 for t in tokens if t in pool)
    return matched / len(tokens) >= threshold


class BaseSource(ABC):
    """所有数据源的抽象基类。"""

    name: str = "base"
    category: str = "news"
    credibility: int = 3

    @abstractmethod
    def fetch(self, since: datetime) -> list[Item]:
        """抓取 since 之后的所有 Item。失败应返回空列表,不抛异常。"""
        ...
