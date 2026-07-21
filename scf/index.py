"""腾讯云函数(SCF)入口。

部署方式:在线编辑 + requirements.txt
函数入口: index.main_handler
运行时: Python 3.11

环境变量:
  DEEPSEEK_API_KEY  DeepSeek API Key
  GITHUB_REPO       GitHub 仓库(如 Yaaaaaaa233/a-stock-brief)
  PUBLIC_REPO       是否公开仓库(默认 true,用 jsDelivr 加速)
"""
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone

import requests

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Yaaaaaaa233/a-stock-brief")
PUBLIC_REPO = os.environ.get("PUBLIC_REPO", "true").lower() == "true"

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _resp(status, body_dict):
    return {
        "statusCode": status,
        "headers": {**CORS, "Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body_dict, ensure_ascii=False),
    }


def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def month_str():
    d = bj_now()
    return f"{d.year}-{d.month:02d}"


# --------------- GitHub 读取 ---------------

def fetch_github(path):
    if PUBLIC_REPO:
        url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{path}"
    else:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"
    headers = {}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def extract_latest_day(logs):
    matches = list(re.finditer(r"\n## (\d{4}-\d{2}-\d{2})", logs))
    if not matches:
        return logs[-3000:]
    return logs[matches[-1].start():].strip()


# --------------- System Prompt ---------------

def build_system_prompt():
    try:
        logs = fetch_github(f"logs/{month_str()}.md")
        brief = extract_latest_day(logs)
    except Exception as e:
        brief = f"(今日早报暂未生成: {e})"

    try:
        sectors = fetch_github("config.yaml")
    except Exception:
        sectors = "(板块配置加载失败)"

    return (
        "你是财经助手,服务 55-70 岁中老年 A 股投资者。\n\n"
        f"## 今日早报\n\n{brief}\n\n"
        f"## 板块配置\n\n{sectors}\n\n"
        "## 回答准则\n\n"
        "1. 通俗:专业词用生活化比喻(降准=银行少交保证金)\n"
        "2. 简洁:≤250 字,先结论后原因\n"
        "3. 客观:不给买卖建议,只解释影响\n"
        "4. 诚实:早报没提的说\"今天早报没提到\"\n"
        "5. 风险提示:提股票时加\"投资有风险,仅供参考\"\n"
        "6. 不预测涨跌:禁止\"会涨/必涨\",改为\"通常被认为是利好\"\n\n"
        "## 政策严格定义\n\n"
        "是政策:国务院/央行/部委正式发文,有发文单位+具体措施\n"
        "不是政策:新闻报道/分析师预测/公司公告/传闻\n\n"
        "## 禁止\n\n"
        "- 禁止\"建议买入/卖出\"\n- 禁止编造股票\n- 禁止把新闻当政策"
    )


# --------------- DeepSeek API ---------------

def call_deepseek(system_prompt, history, message):
    msgs = [{"role": "system", "content": system_prompt}]
    for m in (history or [])[-10:]:
        msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    msgs.append({"role": "user", "content": message})

    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": "deepseek-chat", "messages": msgs, "max_tokens": 800, "temperature": 0.5},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# --------------- Handler ---------------

def main_handler(event, context):
    """腾讯云函数入口。event 是 HTTP 触发器的事件字典。"""
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS}

    # GET /api/health
    if path in ("/api/health", "/health"):
        return _resp(200, {
            "ok": True,
            "service": "a-stock-scf",
            "has_deepseek": bool(DEEPSEEK_KEY),
            "time": bj_now().isoformat(),
        })

    # POST /api/chat
    if path in ("/api/chat", "/chat") and method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except (json.JSONDecodeError, TypeError):
            return _resp(400, {"error": "请求格式错误"})

        message = (body.get("message") or "").strip()
        if not message:
            return _resp(400, {"error": "缺少 message"})
        if not DEEPSEEK_KEY:
            return _resp(500, {"error": "服务未配置 DEEPSEEK_API_KEY"})

        try:
            prompt = build_system_prompt()
            reply = call_deepseek(prompt, body.get("history", []), message)
            return _resp(200, {"reply": reply})
        except Exception as e:
            return _resp(502, {"error": str(e)})

    return _resp(404, {"error": "Not Found"})
