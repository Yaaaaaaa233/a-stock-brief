"""A 股财经简报 - 主入口。

执行流程:
  抓取数据源 → 去重 → LLM 分析 → 生成简报 → fact-check 校验 → 推送

异常兜底:
- 任何环节失败都不沉默,推一条降级版通知到群里
- LLM 挂了 → 推原始新闻列表
- 数据源全挂 → 推"今日数据异常"
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .analyzer.fact_check import FactChecker
from .analyzer.llm import LLMAnalyzer
from .push.format import format_brief
from .sources.base import BaseSource, Item, MarketSnapshot
from .sources.eastmoney import EastMoneySource
from .sources.market import MarketSource
from .sources.rss import RSSHubSource, make_default_sources
from .utils.dedupe import dedupe


@dataclass
class Pusher:
    """统一的推送封装,屏蔽钉钉/企微差异。"""

    name: str
    push_markdown_fn: callable
    push_text_fn: callable
    push_alert_fn: callable
    webhook: str
    secret: str | None = None

    def markdown(self, content: str, title: str = "A股财经早报") -> bool:
        if self.secret is not None:
            return self.push_markdown_fn(self.webhook, content, title, self.secret)
        return self.push_markdown_fn(self.webhook, content, title)

    def text(self, content: str) -> bool:
        if self.secret is not None:
            return self.push_text_fn(self.webhook, content, self.secret)
        return self.push_text_fn(self.webhook, content)

    def alert(self, message: str) -> None:
        if self.secret is not None:
            self.push_alert_fn(self.webhook, message, self.secret)
        else:
            self.push_alert_fn(self.webhook, message)


def get_pusher() -> Pusher | None:
    """根据环境变量自动选择推送渠道。优先级:WxPusher > 钉钉 > 企业微信。"""
    from .push import dingtalk, wecom, wxpusher

    wxp = wxpusher.from_env()
    if wxp:
        token, uids = wxp
        return Pusher(
            name="wxpusher",
            push_markdown_fn=lambda w, c, t, **kw: wxpusher.push_markdown(
                token, c, uids, summary=t
            ),
            push_text_fn=lambda w, c, **kw: wxpusher.push_text(token, c, uids),
            push_alert_fn=lambda w, m, **kw: wxpusher.push_alert(token, m, uids),
            webhook="",
        )

    ding_webhook = os.environ.get("DINGTALK_WEBHOOK", "")
    if ding_webhook:
        return Pusher(
            name="dingtalk",
            push_markdown_fn=dingtalk.push_markdown,
            push_text_fn=dingtalk.push_text,
            push_alert_fn=dingtalk.push_alert,
            webhook=ding_webhook,
            secret=os.environ.get("DINGTALK_SECRET") or None,
        )

    wecom_webhook = os.environ.get("WECOM_WEBHOOK", "")
    if wecom_webhook:
        return Pusher(
            name="wecom",
            push_markdown_fn=lambda w, c, t, **kw: wecom.push_markdown(w, c),
            push_text_fn=lambda w, c, **kw: wecom.push_text(w, c),
            push_alert_fn=lambda w, m, **kw: wecom.push_alert(w, m),
            webhook=wecom_webhook,
        )
    return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
STATE_PATH = ROOT / "state" / "last_run.json"
LOGS_DIR = ROOT / "logs"
BEIJING_TZ = timezone(timedelta(hours=8))


def archive_brief(brief: str, now: datetime) -> Path:
    """把简报归档到 logs/YYYY-MM.md,每月一个文件,每天一段。"""
    LOGS_DIR.mkdir(exist_ok=True)
    month_file = LOGS_DIR / f"{now:%Y-%m}.md"
    is_new = not month_file.exists()
    with open(month_file, "a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# A股财经早报归档 - {now:%Y-%m}\n\n")
        f.write(f"\n## {now:%Y-%m-%d %a} {now:%H:%M}\n\n")
        f.write(brief)
        f.write("\n\n---\n")
    return month_file


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_trading_day(cfg: dict, now: datetime) -> bool:
    """简单判断:周末 + 配置的节假日。可后续接入 akshare 交易日历。"""
    if now.weekday() >= 5:
        return False
    holidays = set(cfg.get("holidays", []) or [])
    if now.strftime("%Y-%m-%d") in holidays:
        return False
    return True


def build_sources(cfg: dict) -> list[BaseSource]:
    """根据 config.sources 启用状态构建数据源列表。

    财联社已通过 RSSHub 接入(更稳定),独立的 cls.py 作为高级 fallback。
    """
    src_cfg = cfg.get("sources", {})
    sources: list[BaseSource] = []

    rss_names = {
        "cls", "kr37_newsflashes", "wallstreetcn_global",
        "state_council", "pbc_gov",
    }
    for rss_src in make_default_sources():
        name = rss_src.name
        if name in rss_names and src_cfg.get(name, {}).get("enabled", True):
            sources.append(rss_src)

    if src_cfg.get("eastmoney_news", {}).get("enabled", False):
        sources.append(EastMoneySource())

    return sources


def fetch_all(sources: list[BaseSource], since: datetime) -> list[Item]:
    """串行抓取所有源,避免并发触发 RSSHub/源站反爬。"""
    all_items: list[Item] = []
    for src in sources:
        try:
            items = src.fetch(since)
            logger.info(f"[fetch] {src.name}: {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            logger.error(f"[fetch] {src.name} 抓取失败: {e}")
    return all_items


def fetch_market(cfg: dict) -> MarketSnapshot | None:
    if not cfg.get("sources", {}).get("market_data", {}).get("enabled", True):
        return None
    try:
        return MarketSource().fetch_snapshot()
    except Exception as e:
        logger.error(f"[market] 行情数据抓取失败: {e}")
        return None


def save_state(items_count: int, brief: str, result_level: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run_at": datetime.now(BEIJING_TZ).isoformat(),
        "items_count": items_count,
        "result_level": result_level,
        "brief_preview": brief[:200],
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run() -> int:
    cfg = load_config()
    pusher = get_pusher()
    if pusher is None:
        logger.error(
            "未配置推送渠道:请设置以下任一组合:\n"
            "  WXPUSHER_TOKEN + WXPUSHER_UIDS  (推荐,推送到微信)\n"
            "  DINGTALK_WEBHOOK [+ DINGTALK_SECRET]\n"
            "  WECOM_WEBHOOK"
        )
        return 2

    now_beijing = datetime.now(BEIJING_TZ)
    if not is_trading_day(cfg, now_beijing):
        logger.info(f"{now_beijing:%Y-%m-%d} 非交易日,跳过")
        return 0

    since = now_beijing - timedelta(hours=24)
    logger.info(f"=== 开始执行,时间窗口 {since:%Y-%m-%d %H:%M} → {now_beijing:%H:%M} ===")

    sources = build_sources(cfg)
    items = fetch_all(sources, since)
    if not items:
        msg = f"⚠️ {now_beijing:%m-%d} 早报:今日所有数据源均无数据,请检查。"
        pusher.text(msg)
        return 1

    items = dedupe(items)
    logger.info(f"[dedupe] 去重后 {len(items)} 条")

    push_cfg = cfg.get("push", {})
    market = None
    if push_cfg.get("include_market_data", False):
        market = fetch_market(cfg)
    else:
        logger.info("[market] 配置已关闭市场数据,跳过")

    analyzer = LLMAnalyzer()
    analyses: list = []
    if os.environ.get("DEEPSEEK_API_KEY"):
        for it in items:
            try:
                an = analyzer.analyze(it)
                analyses.append(an)
            except Exception as e:
                logger.error(f"[analyzer] 单条分析异常: {e}")
                analyses.append(None)
    else:
        logger.warning("DEEPSEEK_API_KEY 未配置,跳过 LLM 分析(降级为原始新闻)")

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
    result = checker.check(brief, items, analyses, market, now=now_beijing)
    logger.info(f"[factcheck] {result.level}: {result.issues}")

    if result.level == "REJECT":
        warning_note = "\n\n⚠️ **本次 AI 分析存在问题(疑似幻觉或违规),已自动降级为原始新闻列表。**\n"
        brief = brief + warning_note

    if result.level == "WARN":
        warn_block = "\n\n⚠️ **以下内容存在待确认项,请注意甄别:**\n"
        for issue in result.issues[:5]:
            warn_block += f"- {issue}\n"
        brief = brief + warn_block

    ok = pusher.markdown(brief, title="A股财经早报")
    archive_path = archive_brief(brief, now_beijing)
    logger.info(f"[archive] 归档到 {archive_path.name}")
    save_state(len(items), brief, result.level)

    if not ok:
        pusher.alert(f"{now_beijing:%m-%d} 早报推送失败,请检查日志")
        return 1

    logger.info("=== 执行完成 ===")
    return 0


def main() -> int:
    try:
        return run()
    except Exception as e:
        logger.error(f"主流程异常: {e}\n{traceback.format_exc()}")
        pusher = get_pusher()
        if pusher:
            pusher.alert(f"系统异常: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
