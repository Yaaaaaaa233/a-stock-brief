"""本地测试脚本 - 不实际推送,只生成简报到本地文件。

用法:
    cd Toolbox/A
    python tests/test_dry_run.py           # 完整流程(包含 LLM)
    python tests/test_dry_run.py --no-llm  # 跳过 LLM,只看抓取效果
    python tests/test_dry_run.py --push    # 真实推送到企业微信(慎用)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analyzer.fact_check import FactChecker
from src.analyzer.llm import LLMAnalyzer
from src.main import build_sources, fetch_all, fetch_market, get_pusher, load_config
from src.push.format import format_brief
from src.utils.dedupe import dedupe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test")

BEIJING_TZ = timezone(timedelta(hours=8))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 分析")
    parser.add_argument("--push", action="store_true", help="真实推送到企业微信")
    parser.add_argument("--hours", type=int, default=24, help="抓取时间窗口")
    args = parser.parse_args()

    cfg = load_config()
    now = datetime.now(BEIJING_TZ)
    since = now - timedelta(hours=args.hours)

    logger.info(f"=== 测试运行,窗口 {since:%Y-%m-%d %H:%M} → {now:%H:%M} ===")

    sources = build_sources(cfg)
    items = fetch_all(sources, since)
    logger.info(f"共抓取 {len(items)} 条原始")

    items = dedupe(items)
    logger.info(f"去重后 {len(items)} 条")

    market = None
    if cfg.get("push", {}).get("include_market_data", False):
        market = fetch_market(cfg)
        if market:
            logger.info(
                f"市场数据: 指数 {len(market.index_data)} 个, "
                f"龙虎榜 {len(market.top_list)} 条"
            )
    else:
        logger.info("配置已关闭市场数据,跳过")

    analyses = []
    if not args.no_llm and os.environ.get("DEEPSEEK_API_KEY"):
        analyzer = LLMAnalyzer()
        for it in items:
            try:
                analyses.append(analyzer.analyze(it))
            except Exception as e:
                logger.error(f"分析异常: {e}")
                analyses.append(None)
    else:
        logger.info("跳过 LLM 分析(无 API_KEY 或 --no-llm)")

    push_cfg = cfg.get("push", {})
    brief_cfg = cfg.get("brief", {})
    brief = format_brief(
        items=items,
        analyses=analyses,
        market=market,
        title_prefix=brief_cfg.get("title_prefix", "📊 A股财经早报"),
        disclaimer=brief_cfg.get("disclaimer", ""),
        include_market=push_cfg.get("include_market_data", False),
        max_items=push_cfg.get("max_items", 8),
        min_importance=push_cfg.get("min_importance", 3),
        max_headline=push_cfg.get("max_headline", 3),
        max_important=push_cfg.get("max_important", 3),
        max_normal=push_cfg.get("max_normal", 2),
    )

    checker = FactChecker()
    result = checker.check(brief, items, analyses, market, now=now)
    logger.info(f"fact-check: {result.level}")
    for issue in result.issues:
        logger.info(f"  - {issue}")

    out_path = Path(__file__).resolve().parents[1] / "state" / "preview.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(brief)
    logger.info(f"简报预览已保存: {out_path}")

    print("\n" + "=" * 60)
    print(brief)
    print("=" * 60)

    if args.push:
        pusher = get_pusher()
        if pusher is None:
            logger.error("未配置推送渠道:请设置 DINGTALK_WEBHOOK 或 WECOM_WEBHOOK")
            return 1
        ok = pusher.markdown(brief, title="A股财经早报")
        logger.info(f"推送结果({pusher.name}): {'成功' if ok else '失败'}")
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
