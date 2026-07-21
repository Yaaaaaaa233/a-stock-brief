"""
腾讯云 SCF 事件函数入口。
部署:文件名为 index.py,入口为 index.main_handler
只需要 requests 一个依赖(SCF 内置),不需要 Flask。
"""
import json, os, re, urllib.parse
from datetime import datetime, timedelta, timezone

import requests as http

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
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


def search_bing(query, max_results=5):
    """Bing 搜索,直接 HTTP 请求,零依赖。"""
    try:
        url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count={max_results}"
        r = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        results = []
        for m in re.finditer(r'<li class="b_algo"[^>]*>(.*?)</li>', r.text, re.DOTALL):
            h2 = re.search(r'<h2[^>]*><a[^>]*>(.*?)</a>', m.group(1))
            p = re.search(r'<p[^>]*>(.*?)</p>', m.group(1))
            if h2:
                title = re.sub(r'<[^>]+>', '', h2.group(1))
                body = re.sub(r'<[^>]+>', '', p.group(1))[:200] if p else ""
                results.append(f"- {title}: {body}")
                if len(results) >= max_results:
                    break
        return "\n".join(results) if results else ""
    except Exception:
        return ""



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
        f"你是一名财经分析助手。以下是今日的资讯汇总,仅供参考,不强制引用。\n\n"
        f"## 今日资讯\n{brief}\n\n## 板块信息\n{sectors}\n\n"
        "## 规则\n"
        "1. 先结论后原因,每轮不超过 250 字\n"
        "2. 不给买卖建议\n"
        "3. 用你的知识回答所有问题,今日资讯只是额外参考,不是唯一来源\n"
        "4. 提股票时加'投资有风险,仅供参考'\n"
        "5. 需要实时行情时,说明你无法获取实时数据,给出分析方向\n\n"
        "## 政策判断\n"
        "国务院/央行/部委/地方政府正式发文才算政策。新闻报道、分析师观点不算。\n\n"
        "## 禁止\n"
        "禁止\"建议买入/卖出\"、禁止编造股票、禁止把新闻当政策"
    )


def call_deepseek(prompt, history, message):
    msgs = [{"role": "system", "content": prompt}]
    for m in (history or [])[-10:]:
        role = m.get("role", "user")
        if role == "ai":
            role = "assistant"
        msgs.append({"role": role, "content": m.get("content", "")})
    msgs.append({"role": "user", "content": message})
    r = http.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
        json={"model": "deepseek-chat", "messages": msgs, "max_tokens": 800, "temperature": 0.5},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ---------- 事件函数入口 ----------

def main_handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": cors}

    if path in ("/api/health", "/health"):
        return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"ok": True, "time": bj_now().isoformat()})}

    # 临时调试:直查看能否读到日志
    if path in ("/api/debug", "/debug"):
        try:
            url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/logs/{month_str()}.md"
            r = http.get(url, timeout=20)
            r.raise_for_status()
            content = r.text[:500]
            return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"ok": True, "url": url, "status": r.status_code, "size": len(r.text), "preview": content})}
        except Exception as e:
            return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"ok": False, "url": url, "error": str(e)})}

    if path in ("/api/chat", "/chat") and method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except:
            return {"statusCode": 400, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "请求格式错误"})}

        msg = (body.get("message") or "").strip()
        if not msg:
            return {"statusCode": 400, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "缺少 message"})}

        try:
            prompt = build_prompt()
            search = search_bing(msg)
            if search:
                prompt += f"\n\n## 联网搜索结果\n{search}"
            reply = call_deepseek(prompt, body.get("history", []), msg)
            return {"statusCode": 200, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"reply": reply})}
        except Exception as e:
            return {"statusCode": 502, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": str(e)})}

    return {"statusCode": 404, "headers": {**cors, "Content-Type": "application/json"}, "body": json.dumps({"error": "Not Found"})}
