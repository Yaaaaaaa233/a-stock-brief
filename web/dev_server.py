"""本地预览服务器 - 单一对话版,跟 worker.js 行为一致。

用法:
    cd Toolbox/A
    export DEEPSEEK_API_KEY="sk-xxx"
    python -m web.dev_server
    # 浏览器打开 http://localhost:8765
"""
from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
LOGS_DIR = ROOT / "logs"
CONFIG_PATH = ROOT / "config.yaml"
PORT = int(os.environ.get("PORT", "8765"))

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Yaaaaaaa233/a-stock-brief")


def bj_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def month_str() -> str:
    d = bj_now()
    return f"{d.year}-{d.month:02d}"


def day_str() -> str:
    d = bj_now()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def fetch_github(path: str) -> str:
    local_candidates = {
        f"web/{Path(path).name}": WEB_DIR / Path(path).name,
        f"logs/{Path(path).name}": LOGS_DIR / Path(path).name,
        "config.yaml": CONFIG_PATH,
    }
    if path in local_candidates and local_candidates[path].exists():
        return local_candidates[path].read_text(encoding="utf-8")
    url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{path}"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.text


def extract_latest_day(logs: str) -> str:
    day_key = f"## {day_str()}"
    idx = logs.rfind(day_key)
    if idx < 0:
        return logs[-3000:]
    next_section = logs.find("\n## ", idx + 5)
    return logs[idx:next_section].strip() if next_section > 0 else logs[idx:].strip()


def build_system_prompt() -> str:
    try:
        logs = fetch_github(f"logs/{month_str()}.md")
        brief = extract_latest_day(logs)
    except Exception as e:
        brief = f"(今日早报暂未生成: {e})"

    try:
        sectors = fetch_github("config.yaml")
    except Exception:
        sectors = "(板块配置加载失败)"

    return f"""你是财经助手,服务对象是 55-70 岁的中老年 A 股投资者(只用微信,不熟悉专业术语)。

## 今日早报内容(已自动加载)

{brief}

## 板块配置(查询龙头股时严格按此)

{sectors}

## 回答准则

1. **通俗**:遇到专业词用 1 个生活化比喻解释(降准=银行少交保证金)
2. **简洁**:回答不超过 250 字,先结论后原因
3. **客观**:不给具体买卖建议(如"应该买 XX"),但可以解释影响方向
4. **诚实**:早报里没讲到的,直接说"今天早报没提到",再按通用知识回答
5. **风险提示**:提到具体股票时,自动加"投资有风险,仅供参考"
6. **不预测涨跌**:严禁"会涨""必涨""必跌",改为"通常被认为是利好/利空"

## 关于"政策"的严格定义(重要)

✅ **是政策**:
- 国务院 / 央行 / 各部委 / 地方政府正式发文
- 有明确发文单位(如"央行决定""财政部公告")
- 有具体执行措施(降准 0.5% / 补贴延长至 X 年)

❌ **不是政策**:
- 新闻媒体报道"国家可能..."、"据传..."
- 分析师/机构的预测或建议
- 公司公告(这是企业行为)
- 普通时事新闻

**用户问"今天有什么政策"时**,只从今日早报里找符合严格定义的内容,不要把新闻当政策。

## 禁止行为

- ❌ "建议买入/卖出 XX 股票"
- ❌ "会涨/跌 X%"
- ❌ 编造不在配置里的股票
- ❌ 把新闻/传闻说成政策
"""


def call_deepseek(system_prompt: str, history: list, message: str) -> str:
    if not DEEPSEEK_KEY:
        return "⚠️ 未配置 DEEPSEEK_API_KEY 环境变量。\n\n请运行:\n```\nexport DEEPSEEK_API_KEY=sk-xxx\n```"
    messages = [
        {"role": "system", "content": system_prompt},
        *history[-10:],
        {"role": "user", "content": message},
    ]
    r = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": messages,
            "max_tokens": 800,
            "temperature": 0.5,
            "stream": False,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        sys.stderr.write(f"[{ts}] {args[0]}\n")

    def _send(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_OPTIONS(self):
        self._send(b"ok", "text/plain")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/chat.html", "/index.html"):
            self._send((WEB_DIR / "chat.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/health":
            self._json({
                "ok": True,
                "has_deepseek_key": bool(DEEPSEEK_KEY),
                "github_repo": GITHUB_REPO,
                "time": bj_now().isoformat(),
            })
        else:
            self._send(b"Not Found", "text/plain", 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._send(b"Not Found", "text/plain", 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            message = body.get("message", "")
            history = body.get("history", [])
            if not message:
                self._json({"error": "缺少 message"}, 400)
                return
            system_prompt = build_system_prompt()
            reply = call_deepseek(system_prompt, history, message)
            self._json({"reply": reply})
        except Exception as e:
            self._json({"error": str(e)}, 502)


def main():
    if not DEEPSEEK_KEY:
        print("⚠️  未配置 DEEPSEEK_API_KEY,聊天会失败。")
        print("    export DEEPSEEK_API_KEY=sk-xxx")
        print()
    print(f"📁 本地目录: {ROOT}")
    print(f"🌐 访问地址: http://localhost:{PORT}")
    print(f"🔧 DeepSeek Key: {'已配置' if DEEPSEEK_KEY else '未配置'}")
    print()
    print("按 Ctrl+C 停止")
    print()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
