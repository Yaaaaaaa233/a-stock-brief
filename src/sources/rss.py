"""基于 RSSHub 的通用数据源。

国内政府/主流媒体 RSS 基本停用,改用 RSSHub 开源聚合项目。
公共实例有多个,任何一个能用即可。

RSSHub 文档: https://docs.rsshub.app
常用路径:
  - /cls/telegraph          财联社电报(国内财经快讯,最及时)
  - /36kr/newsflashes       36氪 7x24 快讯
  - /wallstreetcn/news/global  华尔街见闻全球资讯
  - /cls/depth/1000         财联社深度
  - /gov/zhengce/zuixin     国务院最新政策(可能 503,反爬)
  - /pbc/openmarket         央行公开市场(可能不稳定)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import mktime

import feedparser
import requests

from .base import BaseSource, Item

logger = logging.getLogger(__name__)

DEFAULT_RSSHUB_BASES = [
    "https://rsshub.rssforever.com",
    "https://rsshub.app",
]

import time as _time

_TITLE_PREFIX_RE = re.compile(r"^(【[^】]{1,15}】\s*)+")


def _clean_title(title: str) -> str:
    """去除标题里的栏目前缀,如「【公告全知道】」「【风口研报·洞察】」。"""
    return _TITLE_PREFIX_RE.sub("", title).strip()


class RSSHubSource(BaseSource):
    """基于 RSSHub 路径的数据源。会自动尝试多个 RSSHub 实例。"""

    def __init__(
        self,
        name: str,
        path: str,
        credibility: int = 4,
        category: str = "news",
        rsshub_bases: list[str] | None = None,
        timeout: int = 15,
    ):
        self.name = name
        self.path = path
        self.credibility = credibility
        self.category = category
        self.bases = rsshub_bases or DEFAULT_RSSHUB_BASES
        self.timeout = timeout

    def fetch(self, since: datetime) -> list[Item]:
        for base in self.bases:
            for attempt in range(2):
                items = self._try_base(base, since)
                if items:
                    return items
                if attempt == 0:
                    _time.sleep(1.0)
        logger.warning(f"[{self.name}] 所有 RSSHub 实例均失败")
        return []

    def _try_base(self, base: str, since: datetime) -> list[Item]:
        url = f"{base}{self.path}"
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.info(f"[{self.name}] {base} HTTP {resp.status_code}")
                return []
            feed = feedparser.parse(resp.content)
            if not feed.entries:
                logger.info(f"[{self.name}] {base} 无 entries(可能 RSSHub 抓取源站失败)")
                return []
            logger.info(f"[{self.name}] {base} 抓取成功,{len(feed.entries)} 条原始")
            return self._parse_feed(feed, since)
        except Exception as e:
            logger.info(f"[{self.name}] {base} 异常: {e}")
            return []

    def _parse_feed(self, feed, since: datetime) -> list[Item]:
        items: list[Item] = []
        for entry in feed.entries:
            published = self._parse_time(entry)
            if published is None or published < since:
                continue
            title = _clean_title((entry.get("title") or "").strip())
            summary = (entry.get("summary") or entry.get("description") or "").strip()
            if not title:
                continue
            link = entry.get("link") or ""
            items.append(
                Item(
                    source=self.name,
                    title=title,
                    content=summary or title,
                    url=link,
                    published_at=published,
                    category=self.category,
                    credibility=self.credibility,
                    raw=dict(entry),
                )
            )
        return items

    @staticmethod
    def _parse_time(entry) -> datetime | None:
        for field in ("published_parsed", "updated_parsed"):
            t = entry.get(field)
            if t:
                try:
                    return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
                except Exception:
                    continue
        return None


def make_default_sources() -> list[RSSHubSource]:
    """默认 RSSHub 数据源列表。增删改这里即可。"""
    return [
        RSSHubSource(
            name="cls",
            path="/cls/telegraph",
            credibility=5,
            category="news",
        ),
        RSSHubSource(
            name="kr37_newsflashes",
            path="/36kr/newsflashes",
            credibility=4,
            category="news",
        ),
        RSSHubSource(
            name="wallstreetcn_global",
            path="/wallstreetcn/news/global",
            credibility=4,
            category="international",
        ),
        RSSHubSource(
            name="state_council",
            path="/gov/zhengce/zuixin",
            credibility=5,
            category="policy",
        ),
        RSSHubSource(
            name="pbc_gov",
            path="/pbc/openmarket",
            credibility=5,
            category="policy",
        ),
    ]
