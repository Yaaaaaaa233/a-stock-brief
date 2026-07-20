"""财联社电报数据源。

财联社是国内财经快讯最快的来源之一。接口版本经常变更,
失败时会降级返回空列表,不影响整体流程。
当前使用 v5 接口;若失效请到 https://www.cls.cn/telegraph 抓包更新。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .base import BaseSource, Item

logger = logging.getLogger(__name__)

CLS_API_CANDIDATES = [
    "https://www.cls.cn/v5/telegraph/telegraph-list",
    "https://www.cls.cn/nodeapi/updateTelegraphList",
]
CLS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.cls.cn/telegraph",
}


class CLSSource(BaseSource):
    name = "cls"
    category = "news"
    credibility = 5

    def __init__(self, timeout: int = 15, max_items: int = 50):
        self.timeout = timeout
        self.max_items = max_items

    def fetch(self, since: datetime) -> list[Item]:
        for api in CLS_API_CANDIDATES:
            items = self._try_fetch(api, since)
            if items:
                return items
        logger.warning("[cls] 所有候选接口均失败")
        return []

    def _try_fetch(self, api: str, since: datetime) -> list[Item]:
        items: list[Item] = []
        try:
            params: dict[str, Any] = {
                "app": "CailianpressWeb",
                "os": "web",
                "sv": "7.7.5",
                "rn": self.max_items,
                "category": "",
                "lastTime": "",
            }
            resp = requests.get(
                api, params=params, headers=CLS_HEADERS, timeout=self.timeout
            )
            if resp.status_code != 200:
                logger.warning(f"[cls] {api} 返回 {resp.status_code}")
                return []
            data = resp.json() or {}
            raw_list = self._extract_list(data)
            if not raw_list:
                logger.warning(f"[cls] {api} 列表为空,字段可能变更")
                return []

            for entry in raw_list:
                try:
                    item = self._parse_entry(entry, since)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.debug(f"[cls] 单条解析跳过: {e}")
                    continue
        except requests.RequestException as e:
            logger.warning(f"[cls] {api} 网络异常: {e}")
        except Exception as e:
            logger.warning(f"[cls] {api} 解析异常: {e}")
        return items

    @staticmethod
    def _extract_list(data: dict) -> list:
        for path in (("data", "roll_data"), ("data", "list"), ("roll_data",), ("data",)):
            cur: Any = data
            ok = True
            for key in path:
                if not isinstance(cur, dict) or key not in cur:
                    ok = False
                    break
                cur = cur[key]
            if ok and isinstance(cur, list):
                return cur
        return []

    @staticmethod
    def _parse_entry(entry: dict, since: datetime) -> Item | None:
        if not isinstance(entry, dict):
            return None
        ctime = entry.get("ctime") or entry.get("created_at") or entry.get("sort")
        try:
            if isinstance(ctime, str):
                published = datetime.fromisoformat(ctime.replace("Z", ""))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            else:
                published = datetime.fromtimestamp(int(ctime or 0), tz=timezone.utc)
        except (OSError, ValueError, TypeError):
            return None
        if published < since:
            return None

        title = (entry.get("title") or "").strip()
        content = (entry.get("content") or entry.get("brief") or "").strip()
        if not title and not content:
            return None
        if not title:
            title = content[:40]

        shareurl = (
            entry.get("shareurl")
            or entry.get("url")
            or f"https://www.cls.cn/detail/{entry.get('id','')}"
        )
        return Item(
            source="cls",
            title=title,
            content=content or title,
            url=shareurl,
            published_at=published,
            category="news",
            credibility=5,
            raw=entry,
        )
