"""腾讯云 SCF 事件函数 - 对话用智谱(自带联网搜索),早报仍用 DeepSeek。

环境变量:
  ZHIPU_API_KEY    智谱 API Key(必需)
  GITHUB_REPO      Yaaaaaaa233/a-stock-brief
  PUBLIC_REPO      true
"""
import json, os, re
from datetime import datetime, timedelta, timezone

import requests as http

ZHIPU_KEY = os.environ.get("ZHIPU_API_KEY", "")
DASHSCOPE_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Yaaaaaaa233/a-stock-brief")
PUBLIC_REPO = os.environ.get("PUBLIC_REPO", "true").lower() == "true"


def bj_now():
    return datetime.now(timezone(timedelta(hours=8)))


def month_str():
    return f"{bj_now().year}-{bj_now().month:02d}"


def fetch_github(path):
    url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{path}"
    r = http.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def latest_brief(logs):
    ms = list(re.finditer(r"\n## (\d{4}-\d{2}-\d{2})", logs))
    return logs[ms[-1].start():].strip() if ms else logs[-3000:]


def build_prompt():
    try:
        brief = latest_brief(fetch_github(f"logs/{month_str()}.md"))
    except Exception as e:
        brief = f"(早报加载失败:{e})"
    try:
        sectors = fetch_github("config.yaml")
    except Exception as e:
        sectors = f"(配置加载失败:{e})"

    return (
        f"你是一名具有联网搜索能力的财经分析助手。以下是今日资讯汇总,仅供参考。\n\n"
        f"## 今日资讯\n{brief}\n\n## 板块信息\n{sectors}\n\n"
        "## 规则\n"
        "1. 先结论后原因,每轮不超过 250 字\n"
        "2. 不给买卖建议\n"
        "3. 用你的知识回答所有问题,今日资讯只是额外参考,不是唯一来源\n"
        "4. 提股票时加'投资有风险,仅供参考'\n\n"
        "## 政策判断\n"
        "国务院/央行/部委/地方政府正式发文才算政策。新闻报道、分析师观点不算。\n\n"
        "## 禁止\n"
        "禁止\"建议买入/卖出\"、禁止编造股票、禁止把新闻当政策"
    )


def call_dashscope(prompt, history, message):
    """调阿里通义千问,自带联网搜索。"""
    msgs = [{"role": "system", "content": prompt}]
    for m in (history or [])[-10:]:
        role = m.get("role", "user")
        if role == "ai":
            role = "assistant"
        msgs.append({"role": role, "content": m.get("content", "")})
    msgs.append({"role": "user", "content": message})

    r = http.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers={"Authorization": f"Bearer {DASHSCOPE_KEY}", "Content-Type": "application/json"},
        json={
            "model": "qwen-plus",
            "messages": msgs,
            "max_tokens": 800,
            "temperature": 0.5,
            "enable_search": True,
            "search_options": {"forced_search": True, "search_strategy": "turbo"},
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# ---------- 入口 ----------

def main_handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors}

    if path in ("/api/health", "/health"):
        return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"ok": True, "time": bj_now().isoformat()})}

    if path in ("/api/debug", "/debug"):
        result = {"time": bj_now().isoformat(), "has_dashscope": bool(DASHSCOPE_KEY)}
        try:
            url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/logs/{month_str()}.md"
            r = http.get(url, timeout=30)
            result["brief"] = {"ok": True, "size": len(r.text)}
        except Exception as e:
            result["brief"] = {"ok": False, "error": str(e)}
        return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps(result, ensure_ascii=False)}

    if path in ("/api/chat", "/chat") and method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except:
            return {"statusCode": 400, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "请求格式错误"})}

        msg = (body.get("message") or "").strip()
        if not msg:
            return {"statusCode": 400, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "缺少 message"})}
        if not DASHSCOPE_KEY:
            return {"statusCode": 500, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "服务未配置 DASHSCOPE_API_KEY"})}

        try:
            reply = call_dashscope(build_prompt(), body.get("history", []), msg)
            return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"reply": reply})}
        except Exception as e:
            return {"statusCode": 502, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": str(e)})}

    return {"statusCode": 404, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "Not Found"})}
