"""A 股市场数据源(akshare)。

【关键】这个源不返回 Item 列表,而是返回 MarketSnapshot。
所有数字、行情、资金面数据都不经过 LLM,直接结构化拼到简报里,
从根本上避免数字幻觉。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .base import BaseSource, Item, MarketSnapshot

logger = logging.getLogger(__name__)


class MarketSource(BaseSource):
    name = "market_data"
    category = "market"
    credibility = 5

    def __init__(self, lookback_days: int = 1):
        self.lookback_days = lookback_days

    def fetch(self, since: datetime) -> list[Item]:
        return []

    def fetch_snapshot(self) -> MarketSnapshot:
        snapshot = MarketSnapshot()
        try:
            import akshare as ak
        except ImportError:
            logger.error("[market] akshare 未安装")
            return snapshot

        snapshot.index_data = self._fetch_indices(ak)
        snapshot.northbound = self._fetch_northbound(ak)
        snapshot.top_list = self._fetch_top_list(ak)
        snapshot.limit_up_down = self._fetch_limit_stats(ak)
        return snapshot

    def _fetch_indices(self, ak) -> dict:
        """主要指数实时行情。东财源失败则降级到新浪源。"""
        result = {}
        wanted = {
            "sh000001": "上证指数",
            "sz399001": "深证成指",
            "sz399006": "创业板指",
            "sh000688": "科创50",
            "sh000016": "上证50",
            "sh000300": "沪深300",
        }
        df = None
        for fetcher_name in ("stock_zh_index_spot_em", "stock_zh_index_spot_sina"):
            try:
                fetcher = getattr(ak, fetcher_name, None)
                if fetcher is None:
                    continue
                df = fetcher() if "sina" in fetcher_name else fetcher(symbol="指数成份")
                if df is not None and not df.empty:
                    break
            except Exception as e:
                logger.warning(f"[market] {fetcher_name} 抓取失败: {e}")
                df = None
        if df is None or df.empty:
            logger.error("[market] 所有指数源均失败")
            return result

        code_col = "代码" if "代码" in df.columns else df.columns[0]
        price_col = "最新价" if "最新价" in df.columns else None
        chg_col = "涨跌幅" if "涨跌幅" in df.columns else None

        for code, name in wanted.items():
            short_code = code[2:]
            row = df[df[code_col].astype(str).str.contains(short_code, na=False)]
            if row.empty:
                continue
            r = row.iloc[0]
            try:
                result[name] = {
                    "code": short_code,
                    "price": float(r.get(price_col, 0) or 0) if price_col else 0.0,
                    "change_pct": float(r.get(chg_col, 0) or 0) if chg_col else 0.0,
                }
            except (ValueError, TypeError) as e:
                logger.warning(f"[market] {name} 解析失败: {e}")
        return result

    def _fetch_northbound(self, ak) -> dict | None:
        """北向资金净流入。"""
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is None or df.empty:
                return None
            latest = df.iloc[0]
            return {
                "date": str(latest.get("日期", "")),
                "north_net": float(latest.get("北向资金", 0) or 0),
                "south_net": float(latest.get("南向资金", 0) or 0),
            }
        except Exception as e:
            logger.error(f"[market] 北向资金抓取失败: {e}")
            return None

    def _fetch_top_list(self, ak) -> list:
        """龙虎榜(最近一个交易日)。"""
        try:
            end = datetime.now()
            start = end - timedelta(days=self.lookback_days + 3)
            df = ak.stock_lhb_detail_em(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            if df is None or df.empty:
                return []
            recent = df.head(10)
            items = []
            for _, r in recent.iterrows():
                items.append(
                    {
                        "code": str(r.get("代码", "")),
                        "name": str(r.get("名称", "")),
                        "reason": str(r.get("上榜原因", "")),
                        "net_buy": float(r.get("龙虎榜净买额", 0) or 0),
                    }
                )
            return items
        except Exception as e:
            logger.error(f"[market] 龙虎榜抓取失败: {e}")
            return []

    def _fetch_limit_stats(self, ak) -> dict:
        """涨跌停统计(从全市场涨跌幅推算)。"""
        stats = {"limit_up": 0, "limit_down": 0, "up": 0, "down": 0}
        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                return stats
            change = df["涨跌幅"]
            stats["limit_up"] = int((change >= 9.8).sum())
            stats["limit_down"] = int((change <= -9.8).sum())
            stats["up"] = int((change > 0).sum())
            stats["down"] = int((change < 0).sum())
        except Exception as e:
            logger.error(f"[market] 涨跌停统计失败: {e}")
        return stats
