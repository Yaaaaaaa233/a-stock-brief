"""fact-check skill:事实校验门禁。

在简报生成后、推送前做最后一道事实校验。
混合策略:规则引擎做硬性校验(免费、可靠),LLM 做语义校验(可选)。

校验结果:
- PASS: 通过,正常推送
- WARN:  有警告,推送但标注"⚠️ 待确认"
- REJECT: 拒绝,降级到"原始新闻列表"
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..sources.base import Analysis, Item, MarketSnapshot

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    level: str  # PASS / WARN / REJECT
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.level == "PASS"


FORBIDDEN_TERMS = [
    "建议买入", "建议卖出", "建议加仓", "建议减仓",
    "建议清仓", "满仓", "必涨", "必跌", "稳赚", "包赚",
    "会涨停", "会跌停", "翻倍", "十倍",
]

ANCIENT_DATE_THRESHOLD = timedelta(days=30)


class FactChecker:
    """规则引擎版事实校验。"""

    def check(
        self,
        brief: str,
        items: list[Item],
        analyses: list[Analysis],
        market: MarketSnapshot | None = None,
        now: datetime | None = None,
    ) -> CheckResult:
        now = now or datetime.now()
        issues: list[str] = []

        self._check_forbidden_terms(brief, issues)
        self._check_numbers_against_sources(analyses, items, market, issues)
        self._check_stale_dates(brief, now, issues)
        self._check_evidence_in_original(analyses, items, issues)
        self._check_market_numbers(brief, market, issues)

        if any("违规字眼" in i for i in issues):
            return CheckResult("REJECT", issues)
        if issues:
            return CheckResult("WARN", issues)
        return CheckResult("PASS", issues)

    @staticmethod
    def _check_forbidden_terms(brief: str, issues: list[str]) -> None:
        for term in FORBIDDEN_TERMS:
            if term in brief:
                issues.append(f"违规字眼: 出现「{term}」")

    @staticmethod
    def _check_numbers_against_sources(
        analyses: list,
        items: list[Item],
        market: MarketSnapshot | None,
        issues: list[str],
    ) -> None:
        """只检查 LLM 输出(one_line + evidence)里的数字。

        结构化数据直接拼到简报的数字(如龙虎榜上榜原因里的 7%)不经 LLM,
        不存在幻觉风险,故只校验 LLM 生成的部分。
        """
        for an, item in zip(analyses, items):
            if an is None:
                continue
            text_to_check = (an.one_line or "") + " " + (an.evidence or "")
            nums_in_output = set(re.findall(r"(\d+\.?\d*\s*%)", text_to_check))
            if not nums_in_output:
                continue

            source_pool = (item.content or "") + " " + (item.title or "")
            source_pool_norm = re.sub(r"\s", "", source_pool)

            for num in nums_in_output:
                num_norm = re.sub(r"\s", "", num)
                bare = re.sub(r"[%\s]", "", num)
                if not bare:
                    continue
                if num_norm in source_pool_norm:
                    continue
                if bare in re.sub(r"[%\s]", "", source_pool_norm):
                    continue
                issues.append(
                    f"LLM 输出数字可能为幻觉: 「{num}」不在原文({item.title[:30]})"
                )

    @staticmethod
    def _check_stale_dates(brief: str, now: datetime, issues: list[str]) -> None:
        """检查简报里出现的具体日期,标记过旧的(超过 30 天)。"""
        now_local = now.replace(tzinfo=None) if now.tzinfo else now
        date_patterns = [
            (r"(\d{4})年(\d{1,2})月(\d{1,2})日", lambda m: datetime(m[0], m[1], m[2])),
            (r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: datetime(m[0], m[1], m[2])),
        ]
        for pat, ctor in date_patterns:
            for match in re.finditer(pat, brief):
                try:
                    d = ctor(tuple(int(g) for g in match.groups()))
                except ValueError:
                    continue
                if d > now_local + timedelta(days=1):
                    issues.append(f"未来日期异常: {match.group(0)}")
                elif now_local - d > ANCIENT_DATE_THRESHOLD:
                    issues.append(f"旧闻日期: {match.group(0)}(超过30天)")

    @staticmethod
    def _check_evidence_in_original(
        analyses: list[Analysis], items: list[Item], issues: list[str]
    ) -> None:
        """再次校验 evidence(双重保险)。"""
        for analysis, item in zip(analyses, items):
            if analysis is None or item is None:
                continue
            if analysis.importance >= 4:
                if not analysis.evidence:
                    issues.append(f"重要新闻缺 evidence: {item.title[:30]}")
                elif (
                    analysis.evidence not in item.content
                    and analysis.evidence not in item.title
                ):
                    issues.append(
                        f"evidence 不在原文(重要新闻): {item.title[:30]}"
                    )

    @staticmethod
    def _check_market_numbers(
        brief: str, market: MarketSnapshot | None, issues: list[str]
    ) -> None:
        """检查市场数据段:如果简报提到指数点位,必须来自结构化数据。"""
        if not market or not market.index_data:
            return
        for name, data in market.index_data.items():
            price_str = str(data.get("price", ""))
            if name in brief and price_str and price_str[:4] not in brief:
                issues.append(f"指数数据不一致: {name} 价格未正确显示")


def _flatten_market_values(market: MarketSnapshot | None):
    if not market:
        return []
    out = []
    for v in market.index_data.values():
        out.extend(v.values())
    if market.northbound:
        out.extend(market.northbound.values())
    return out
