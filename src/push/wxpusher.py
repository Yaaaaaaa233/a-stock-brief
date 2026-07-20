"""WxPusher 微信推送服务。

通过 WxPusher 桥接,把消息推送到父母微信(微信公众号「WxPusher 消息服务」)。
父母只需扫一次二维码关注公众号并绑定应用,后续推送直接到微信。

文档: https://wxpusher.zjiecode.com/docs/

环境变量:
  WXPUSHER_TOKEN  应用 appToken(AT_xxx),创建应用后获得
  WXPUSHER_UIDS   订阅用户的 UID 列表,逗号分隔(UID_xxx,UID_yyy)

免费额度:每日 100 条,够用。
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

API_URL = "https://wxpusher.zjiecode.com/api/send/message"


def _parse_uids() -> list[str]:
    raw = os.environ.get("WXPUSHER_UIDS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


def push_markdown(
    token: str,
    content: str,
    uids: list[str],
    summary: str = "A股财经早报",
    timeout: int = 10,
) -> bool:
    """推送 markdown 到 WxPusher,会转发到所有 uids 的微信。

    Args:
        token: appToken(AT_xxx)
        content: markdown 正文(<5KB 比较稳)
        uids: 用户 UID 列表
        summary: 消息摘要(微信通知栏预览,<=20 字)
    """
    if not token or not uids:
        logger.error("[wxpusher] token 或 uids 为空")
        return False

    if len(content.encode("utf-8")) > 5000:
        content = content[:1500]
        logger.warning("[wxpusher] 正文过长,已截断")

    payload = {
        "appToken": token,
        "content": content,
        "summary": summary[:20],
        "contentType": 3,
        "uids": uids,
    }
    try:
        resp = requests.post(API_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 1000:
            logger.info(f"[wxpusher] 推送成功,触达 {len(uids)} 个用户")
            return True
        logger.error(f"[wxpusher] 推送失败: {data}")
        return False
    except Exception as e:
        logger.error(f"[wxpusher] 推送异常: {e}")
        return False


def push_text(
    token: str,
    content: str,
    uids: list[str],
    timeout: int = 10,
) -> bool:
    """推送纯文本(用于错误兜底)。"""
    if not token or not uids:
        return False
    payload = {
        "appToken": token,
        "content": content,
        "summary": content[:20],
        "contentType": 1,
        "uids": uids,
    }
    try:
        resp = requests.post(API_URL, json=payload, timeout=timeout)
        return resp.json().get("code") == 1000
    except Exception as e:
        logger.error(f"[wxpusher] 文本推送异常: {e}")
        return False


def push_alert(token: str, message: str, uids: list[str]) -> None:
    """异常告警。"""
    push_text(token, f"⚠️ [系统告警] {message}", uids)


def from_env():
    """从环境变量读取配置,返回 (token, uids) 或 None。"""
    token = os.environ.get("WXPUSHER_TOKEN", "").strip()
    uids = _parse_uids()
    if token and uids:
        return token, uids
    return None
