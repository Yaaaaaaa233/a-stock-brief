"""政策样本测试 - 用典型政策测试 LLM 分析能力。

不依赖数据源,直接构造典型政策新闻测试。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzer.fact_check import FactChecker
from src.analyzer.llm import LLMAnalyzer
from src.main import load_config
from src.push.format import format_brief
from src.sources.base import Analysis, Item, MarketSnapshot

POLICY_SAMPLES = [
    Item(
        source="pbc_gov",
        title="中国人民银行决定下调存款准备金率0.5个百分点",
        content=(
            "中国人民银行决定于2026年8月15日起下调金融机构存款准备金率0.5个百分点"
            "(不含已执行5%存款准备金率的金融机构)。本次下调后,金融机构加权平均存款准备金率"
            "约为7.8%。此次降准预计释放长期资金约1万亿元。"
        ),
        url="http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/example.html",
        published_at=datetime.now(timezone.utc),
        category="policy",
        credibility=5,
    ),
    Item(
        source="state_council",
        title="财政部等三部门:新能源车购置税减免政策延长至2027年底",
        content=(
            "财政部、税务总局、工业和信息化部联合发布公告,将新能源汽车车辆购置税减免政策"
            "延长至2027年12月31日。其中2024-2025年免税,2026-2027年减半征收。预计对新能源车"
            "消费持续形成支撑。"
        ),
        url="https://www.gov.cn/zhengce/zhengceku/202407/example.html",
        published_at=datetime.now(timezone.utc),
        category="policy",
        credibility=5,
    ),
    Item(
        source="state_council",
        title="住建部:推进城中村改造,因城施策支持刚性和改善性住房需求",
        content=(
            "住房和城乡建设部表示,将在超大特大城市积极稳步推进城中村改造,带动有效投资和消费。"
            "继续因城施策,支持刚性和改善性住房需求,促进房地产市场平稳健康发展。"
        ),
        url="https://www.gov.cn/lianbo/bumen/202407/example.html",
        published_at=datetime.now(timezone.utc),
        category="policy",
        credibility=5,
    ),
    Item(
        source="csrc_gov",
        title="证监会:阶段性收紧IPO节奏,完善一二级市场逆周期调节",
        content=(
            "证监会新闻发言人表示,将根据近期市场情况,阶段性收紧IPO节奏,促进投融资两端的"
            "动态平衡。同时完善一二级市场逆周期调节机制,引导资金更多流向实体经济。"
        ),
        url="http://www.csrc.gov.cn/pub/newsite/example.html",
        published_at=datetime.now(timezone.utc),
        category="policy",
        credibility=5,
    ),
    Item(
        source="ndrc_gov",
        title="发改委等部门:支持商业航天发展,鼓励民营企业参与卫星互联网建设",
        content=(
            "国家发改委、国防科工局等部门联合印发指导意见,提出加大商业航天领域政策支持力度,"
            "鼓励民营企业参与卫星互联网、火箭制造等产业链建设,培育新的经济增长点。"
        ),
        url="https://www.ndrc.gov.cn/example.html",
        published_at=datetime.now(timezone.utc),
        category="policy",
        credibility=5,
    ),
]


def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("错误:未设置 DEEPSEEK_API_KEY")
        return 1

    cfg = load_config()
    analyzer = LLMAnalyzer()

    print("=" * 60)
    print("【政策样本逐条分析】")
    print("=" * 60)

    analyses = []
    for item in POLICY_SAMPLES:
        print(f"\n>>> 输入政策: {item.title}")
        an = analyzer.analyze(item)
        if an is None:
            print("  分析失败")
            analyses.append(None)
            continue
        print(f"  重要度:   {'⭐' * an.importance}({an.importance})")
        print(f"  板块:     {an.sectors}")
        print(f"  影响:     {an.impact}")
        print(f"  一句话:   {an.one_line}")
        print(f"  证据:     {an.evidence}")
        print(f"  逻辑:     {an.reason}")
        print(f"  置信度:   {an.confidence}")
        analyses.append(an)

    print("\n" + "=" * 60)
    print("【生成的简报】")
    print("=" * 60)
    brief = format_brief(
        items=POLICY_SAMPLES,
        analyses=analyses,
        market=None,
        title_prefix=cfg.get("brief", {}).get("title_prefix", "📊 A股财经早报"),
        disclaimer=cfg.get("brief", {}).get("disclaimer", ""),
        include_market=False,
        max_items=10,
        min_importance=3,
    )
    print(brief)

    print("\n" + "=" * 60)
    print("【fact-check 校验】")
    print("=" * 60)
    checker = FactChecker()
    result = checker.check(brief, POLICY_SAMPLES, analyses, None)
    print(f"级别: {result.level}")
    for issue in result.issues:
        print(f"  - {issue}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
