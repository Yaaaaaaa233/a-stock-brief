"""东方财富要闻数据源。

注:东财无标准 RSS,使用其公开 JSON 接口。接口字段可能变更,
失败时会降级返回空列表,不影响整体流程。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from .base import BaseSource, Item

logger = logging.getLogger(__name__)


class EastMoneySource(BaseSource):
    name = "eastmoney_news"
    category = "news"
    credibility = 4

    API = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://finance.eastmoney.com/",
    }

    def __init__(self, timeout: int = 15, max_items: int = 30):
        self.timeout = timeout
        self.max_items = max_items

    def fetch(self, since: datetime) -> list[Item]:
        items: list[Item] = []
        try:
            params = {
                "client": "web",
                "biz": "web_news_col",
                "column": "350",
                "order": "1",
                "needInteractData": "0",
                "page_index": "1",
                "page_size": str(self.max_items),
            }
            resp = requests.get(
                self.API, params=params, headers=self.HEADERS, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json() or {}
            data_obj = data.get("data") or {}
            news_list = data_obj.get("list") or []
            if not news_list:
                logger.warning("[eastmoney] 接口返回空,字段可能变更")
                return items

            for entry in news_list:
                published = self._parse_time(entry.get("showTime") or entry.get("time"))
                if published is None or published < since:
                    continue

                title = (entry.get("title") or "").strip()
                if not title:
                    continue
                art_code = entry.get("art_code") or ""
                url = (
                    f"https://finance.eastmoney.com/a/{art_code}.html"
                    if art_code
                    else entry.get("url", "")
                )
                digest = (entry.get("digest") or "").strip() or title

                items.append(
                    Item(
                        source=self.name,
                        title=title,
                        content=digest,
                        url=url,
                        published_at=published,
                        category=self.category,
                        credibility=self.credibility,
                        raw=entry,
                    )
                )
        except requests.RequestException as e:
            logger.error(f"[eastmoney] 网络异常: {e}")
        except Exception as e:
            logger.error(f"[eastmoney] 解析异常: {e}")
        return items

    @staticmethod
    def _parse_time(raw):
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(str(raw).strip(), fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
        return None
