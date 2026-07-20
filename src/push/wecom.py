"""企业微信群机器人推送。

通过 webhook 推送 markdown 消息到企业微信群。
父母只需进群,无需关注任何公众号。

企业微信 markdown 限制:4096 字节,超出会自动拆分多条发送。
"""
from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

MAX_BYTES = 4000  # 留 96 字节余量


def _split_by_bytes(content: str, max_bytes: int) -> list[str]:
    """按章节边界拆分 markdown,保证每块 <= max_bytes 字节。"""
    if len(content.encode("utf-8")) <= max_bytes:
        return [content]

    sections = re.split(r"(?=\n#{1,3} |\n\*\*【)", content)
    sections = [s for s in sections if s.strip()]

    chunks: list[str] = []
    current = ""
    for sec in sections:
        sec_bytes = len(sec.encode("utf-8"))
        if sec_bytes > max_bytes:
            for i in range(0, len(sec), max_bytes * 3 // 4):
                chunks.append(sec[i : i + max_bytes * 3 // 4])
            continue
        cur_bytes = len(current.encode("utf-8"))
        if cur_bytes + sec_bytes > max_bytes:
            if current:
                chunks.append(current)
            current = sec
        else:
            current += sec
    if current:
        chunks.append(current)
    return chunks


def push_markdown(webhook: str, content: str, timeout: int = 10) -> bool:
    """推送 markdown 到企业微信群机器人。超过 4096 字节自动拆分。"""
    if not webhook:
        logger.error("[wecom] webhook URL 为空")
        return False

    chunks = _split_by_bytes(content, MAX_BYTES)
    if len(chunks) > 1:
        logger.info(f"[wecom] 简报 {len(content.encode('utf-8'))} 字节,拆分为 {len(chunks)} 条")

    success = True
    for i, chunk in enumerate(chunks):
        suffix = f"\n\n_(第 {i+1}/{len(chunks)} 段)_" if len(chunks) > 1 else ""
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": chunk + suffix},
        }
        try:
            resp = requests.post(webhook, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                logger.error(f"[wecom] 第 {i+1} 段推送失败: {data}")
                success = False
        except Exception as e:
            logger.error(f"[wecom] 第 {i+1} 段推送异常: {e}")
            success = False

    if success:
        logger.info(f"[wecom] 推送成功({len(chunks)} 段)")
    return success


def push_text(webhook: str, content: str, timeout: int = 10) -> bool:
    """推送纯文本(用于错误兜底)。"""
    if not webhook:
        return False
    payload = {
        "msgtype": "text",
        "text": {"content": content},
    }
    try:
        resp = requests.post(webhook, json=payload, timeout=timeout)
        return resp.json().get("errcode") == 0
    except Exception as e:
        logger.error(f"[wecom] 文本推送异常: {e}")
        return False


def push_alert(webhook: str, message: str) -> None:
    """异常告警(给你看,不是给父母)。"""
    alert = f"⚠️ [系统告警] {message}"
    push_text(webhook, alert)
