"""腾讯云 SCF Web 函数(Flask 格式)。

Web 函数直接用 Flask 处理 HTTP,自动生成访问 URL。
部署:在线编辑 app.py + requirements.txt → 点部署

环境变量:
  DEEPSEEK_API_KEY  DeepSeek API Key
  GITHUB_REPO       Yaaaaaaa233/a-stock-brief
  PUBLIC_REPO       true
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests as http_client
from flask import Flask, request, jsonify

app = Flask(__name__)

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Yaaaaaaa233/a-stock-brief")
PUBLIC_REPO = os.environ.get("PUBLIC_REPO", "true").lower() == "true"


def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def month_str():
    d = bj_now()
    return f"{d.year}-{d.month:02d}"


def fetch_github(path):
    if PUBLIC_REPO:
        url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{path}"
    else:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"
    headers = {}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"token {token}"
    r = http_client.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def extract_latest_day(logs):
    matches = list(re.finditer(r"\n## (\d{4}-\d{2}-\d{2})", logs))
    if not matches:
        return logs[-3000:]
    return logs[matches[-1].start():].strip()


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
        "2. 简洁:不超过 250 字,先结论后原因\n"
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


def call_deepseek(system_prompt, history, message):
    msgs = [{"role": "system", "content": system_prompt}]
    for m in (history or [])[-10:]:
        msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    msgs.append({"role": "user", "content": message})

    r = http_client.post(
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


# ---- Flask 路由 ----

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def index():
    return "a-stock-scf OK"


@app.route("/api/health")
def health():
    return jsonify(
        ok=True,
        service="a-stock-scf",
        has_deepseek=bool(DEEPSEEK_KEY),
        time=bj_now().isoformat(),
    )


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True) or {}
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify(error="缺少 message"), 400
    if not DEEPSEEK_KEY:
        return jsonify(error="服务未配置 DEEPSEEK_API_KEY"), 500

    try:
        prompt = build_system_prompt()
        reply = call_deepseek(prompt, body.get("history", []), message)
        return jsonify(reply=reply)
    except Exception as e:
        return jsonify(error=str(e)), 502
