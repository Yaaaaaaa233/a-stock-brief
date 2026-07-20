"""钉钉自定义群机器人推送。

钉钉机器人支持两种安全模式:
1. 自定义关键词(最简单):消息内容必须包含指定关键词。
   建议设置关键词为「早报」或「A股」(本简报标题天然包含)。
2. 加签(更安全):需要 secret 计算签名。

webhook URL 形如:
  https://oapi.dingtalk.com/robot/send?access_token=xxxxx

加签模式下还需要额外的 secret(创建机器人时会一起显示)。

消息频率限制:每个机器人 20 条/分钟,足够日常使用。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse

import requests

logger = logging.getLogger(__name__)


def _build_signed_url(webhook: str, secret: str) -> str:
    """计算加签 URL。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{webhook}&timestamp={timestamp}&sign={sign}"


def push_markdown(
    webhook: str,
    content: str,
    title: str = "A股财经早报",
    secret: str | None = None,
    timeout: int = 10,
) -> bool:
    """推送 markdown 到钉钉群。

    Args:
        webhook: 钉钉机器人 webhook URL
        content: markdown 正文(<=5000 字节)
        title: 通知栏预览标题(必填)
        secret: 加签模式下的 secret,None 表示用关键词模式
    """
    if not webhook:
        logger.error("[dingtalk] webhook URL 为空")
        return False

    url = _build_signed_url(webhook, secret) if secret else webhook

    if len(content.encode("utf-8")) > 5000:
        content = content[:1500]
        logger.warning("[dingtalk] 正文超过 5000 字节,已截断")

    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content},
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("[dingtalk] 推送成功")
            return True
        logger.error(f"[dingtalk] 推送失败: {data}")
        if data.get("errcode") == 310000:
            logger.error(
                "[dingtalk] 关键词不匹配:请确认机器人关键词设置包含「早报」或「A股」"
            )
        elif data.get("errcode") == 310002:
            logger.error("[dingtalk] 签名错误:请检查 DINGTALK_SECRET 是否正确")
        return False
    except Exception as e:
        logger.error(f"[dingtalk] 推送异常: {e}")
        return False


def push_text(
    webhook: str,
    content: str,
    secret: str | None = None,
    timeout: int = 10,
) -> bool:
    """推送纯文本(用于错误兜底)。"""
    if not webhook:
        return False
    url = _build_signed_url(webhook, secret) if secret else webhook
    payload = {
        "msgtype": "text",
        "text": {"content": content},
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.json().get("errcode") == 0
    except Exception as e:
        logger.error(f"[dingtalk] 文本推送异常: {e}")
        return False


def push_alert(webhook: str, message: str, secret: str | None = None) -> None:
    """异常告警(给你看,不是给父母)。"""
    push_text(webhook, f"⚠️ [系统告警] {message}", secret=secret)
