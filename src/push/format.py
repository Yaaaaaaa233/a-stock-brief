"""简报格式化器(资讯+建议双板块)。

设计原则:
1. 总字数 < 600(企业微信单条 4096 字节够用)
2. 两大板块:📰 资讯 + 💡 关注建议
3. 资讯段:每条新闻 2 行(标题行 + 内容行带链接)
4. 建议段:聚合所有 paired news 涉及的板块,从 config 读龙头股
5. 龙头股从 config 读(LLM 不能编),避免幻觉
6. 市场数据默认不显示(config: push.include_market_data)
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from ..sources.base import Analysis, Item, MarketSnapshot

BEIJING_TZ = timezone(timedelta(hours=8))
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"

IMPACT_ICON = {
    "利好": "🟢",
    "利空": "🔴",
    "中性": "⚪",
    "待观察": "❓",
}


def _load_sector_leaders() -> dict[str, list[str]]:
    """从 config.yaml 读板块 -> 龙头股映射。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    sectors = cfg.get("sectors", {}) or {}
    return {name: data.get("leaders", []) for name, data in sectors.items()}


def _stars(n: int) -> str:
    return "⭐" * max(0, min(5, n))


def _source_link(item: Item) -> str:
    if item.url:
        return f"[{item.source}]({item.url})"
    return item.source


def _format_news_item(item: Item, an: Analysis) -> str:
    """单条新闻:2 行紧凑格式。"""
    stars = _stars(an.importance)
    icon = IMPACT_ICON.get(an.impact, "❓")
    sectors = "/".join(an.sectors) if an.sectors else ""
    sector_part = f"{icon}{sectors}" if sectors else icon

    head = f"{stars} **{item.title[:40]}** {sector_part}"
    one_line = (an.one_line or item.title)[:55]
    body = f"{one_line} 🔗 {_source_link(item)}"
    return head + "\n" + body


def _build_suggestions(
    paired: list[tuple[Item, Analysis]],
    sector_leaders: dict[str, list[str]],
) -> list[dict]:
    """聚合 paired news 涉及的板块,生成建议列表。

    返回:[{sector, impact, leaders, reasons}]
    - 同一板块合并(只显示一次)
    - impact 取该板块下所有新闻的综合(利好优先)
    - reasons 聚合多条新闻的逻辑
    """
    bucket: OrderedDict[str, dict] = OrderedDict()
    for item, an in paired:
        for s in an.sectors:
            if s not in sector_leaders:
                continue
            if s not in bucket:
                bucket[s] = {
                    "sector": s,
                    "impact_score": 0,
                    "leaders": sector_leaders[s][:3],
                    "reasons": [],
                    "news_count": 0,
                }
            b = bucket[s]
            b["news_count"] += 1
            if an.impact == "利好":
                b["impact_score"] += 1
            elif an.impact == "利空":
                b["impact_score"] -= 1
            if an.reason and an.reason not in b["reasons"]:
                b["reasons"].append(an.reason)

    suggestions = list(bucket.values())
    suggestions.sort(key=lambda x: (-x["impact_score"], -x["news_count"]))
    return suggestions


def _format_suggestion(s: dict) -> str:
    """单条建议格式:3 行。"""
    if s["impact_score"] > 0:
        icon = "🟢"
    elif s["impact_score"] < 0:
        icon = "🔴"
    else:
        icon = "🟡"
    leaders = "、".join(s["leaders"][:3])
    reason = s["reasons"][0] if s["reasons"] else "—"
    return f"{icon} **{s['sector']}**\n  龙头:{leaders}\n  逻辑:{reason}"


def format_brief(
    items: list[Item],
    analyses: list,
    market: MarketSnapshot | None,
    title_prefix: str = "📊 A股财经早报",
    disclaimer: str = "",
    include_market: bool = False,
    max_items: int = 8,
    min_importance: int = 3,
    max_headline: int = 3,
    max_important: int = 3,
    max_normal: int = 2,
) -> str:
    """生成简报:资讯段 + 建议段。"""
    paired = [
        (it, an) for it, an in zip(items, analyses)
        if an is not None and an.importance >= min_importance
    ]
    paired.sort(key=lambda x: x[1].importance, reverse=True)

    headline = [(it, an) for it, an in paired if an.importance >= 5][:max_headline]
    important = [(it, an) for it, an in paired if an.importance == 4][:max_important]
    normal = [(it, an) for it, an in paired if an.importance == 3][:max_normal]
    shown = headline + important + normal

    has_analysis = any(an is not None for an in analyses)

    today = datetime.now(BEIJING_TZ)
    weekday = "周" + "一二三四五六日"[today.weekday()]
    lines: list[str] = [
        f"# {title_prefix}",
        f"{today:%m-%d} {weekday}",
    ]

    if not has_analysis:
        lines.append("\n_⚠️ AI 未启用,降级为原始新闻列表_\n")
        for it in items[:max_items]:
            try:
                t = it.published_at.astimezone(BEIJING_TZ).strftime("%H:%M")
            except Exception:
                t = "??:??"
            lines.append(f"• **{t}** {it.title[:40]} 🔗 {_source_link(it)}")
    else:
        lines.append("\n## 📰 资讯")
        if headline:
            lines.append("")
            for it, an in headline:
                lines.append(_format_news_item(it, an))
        if important:
            lines.append("")
            for it, an in important:
                lines.append(_format_news_item(it, an))
        if normal:
            lines.append("")
            for it, an in normal:
                lines.append(_format_news_item(it, an))

        sector_leaders = _load_sector_leaders()
        suggestions = _build_suggestions(shown, sector_leaders)
        if suggestions:
            lines.append("\n## 💡 关注建议\n")
            for s in suggestions[:5]:
                lines.append(_format_suggestion(s))

    if not paired and not has_analysis:
        lines.append("\n今日无重要资讯。")

    lines.append("")
    if disclaimer:
        lines.append(f"_{disclaimer}_")

    return "\n".join(lines)
