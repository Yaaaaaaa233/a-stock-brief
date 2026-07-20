"""LLM 分析器:对每条 Item 做结构化判断,带防幻觉校验。

核心防幻觉机制:
1. 每条 Item 单独分析(不让 LLM 自由发挥写整篇简报)
2. 强制输出 JSON,带 evidence 字段
3. 程序校验 evidence 是否真的在原文中
4. 校验板块名是否在白名单
5. 校验失败则降级或丢弃,绝不带病输出
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests
import yaml

from ..sources.base import Analysis, Item

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "analyzer.md"
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_prompt_template() -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _strip_json(text: str) -> str:
    """从 LLM 输出中提取 JSON(可能被 ```json ... ``` 包裹)。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        text = brace.group(0)
    return text


class LLMAnalyzer:
    """对 Item 做结构化分析的 LLM 客户端。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        cfg = _load_config().get("llm", {})
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL")
                         or "https://api.deepseek.com")
        self.model = cfg.get("model", "deepseek-chat")
        self.max_tokens = cfg.get("max_tokens", 2000)
        self.temperature = cfg.get("temperature", 0.1)
        self.timeout = cfg.get("timeout", 60)
        self.retry = cfg.get("retry", 2)
        self.valid_sectors = list(_load_config().get("sectors", {}).keys())
        self._prompt_tpl = _load_prompt_template()

    def analyze(self, item: Item) -> Analysis | None:
        """分析单条 Item,返回 Analysis 或 None(分析失败/被丢弃)。"""
        prompt = self._build_prompt(item)
        raw = self._call_llm(prompt)
        if not raw:
            return None

        analysis = self._parse(raw)
        if analysis is None:
            logger.warning(f"[analyzer] JSON 解析失败: {item.title[:40]}")
            return None

        ok, reason = analysis.validate(item, self.valid_sectors)
        if not ok:
            logger.warning(f"[analyzer] 校验失败({reason}): {item.title[:40]}")
            return self._fallback_analysis(item, reason)

        if item.credibility >= 5 and analysis.importance >= 5:
            analysis.confidence = "high_credibility"
        elif item.credibility >= 4:
            analysis.confidence = "single_source"
        else:
            analysis.confidence = "low_credibility"
        return analysis

    def _build_prompt(self, item: Item) -> str:
        body = self._prompt_tpl.replace("{sectors}", ", ".join(self.valid_sectors))
        body = body.replace("{title}", item.title)
        body = body.replace("{content}", item.content[:2000])
        body = body.replace("{source}", item.source)
        body = body.replace("{published_at}", item.published_at.isoformat())
        return body

    def _call_llm(self, prompt: str) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        last_err = None
        for attempt in range(self.retry + 1):
            try:
                resp = requests.post(
                    url, headers=headers, json=payload, timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = e
                logger.warning(f"[analyzer] LLM 调用失败({attempt+1}): {e}")
        logger.error(f"[analyzer] LLM 调用最终失败: {last_err}")
        return ""

    @staticmethod
    def _parse(raw: str) -> Analysis | None:
        try:
            cleaned = _strip_json(raw)
            obj = json.loads(cleaned)
            return Analysis(
                importance=int(obj.get("importance", 0)),
                sectors=obj.get("sectors", []) or [],
                impact=obj.get("impact", "待观察"),
                one_line=obj.get("one_line", ""),
                evidence=obj.get("evidence", ""),
                reason=obj.get("reason", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(f"[analyzer] JSON 解析异常: {e}")
            return None

    @staticmethod
    def _fallback_analysis(item: Item, reason: str) -> Analysis:
        """校验失败的降级处理:返回最低置信度的占位分析。"""
        return Analysis(
            importance=2,
            sectors=[],
            impact="待观察",
            one_line=item.title[:30],
            evidence=item.title[:50],
            confidence="ai_uncertain",
        )
