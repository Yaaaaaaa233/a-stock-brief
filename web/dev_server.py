"""本地预览服务器 - 不需要部署就能看网页效果。

用法:
    cd Toolbox/A
    export DEEPSEEK_API_KEY="sk-xxx"
    python -m web.dev_server
    # 然后浏览器打开 http://localhost:8765

按 Ctrl+C 退出。
"""
from __future__ import annotations

import json
import os
import re
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
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

SKILLS_META = {
    "brief": {
        "name": "早报解读", "icon": "💬",
        "description": "基于今日早报回答,父母友好",
        "default": True,
        "greeting": "👋 你好!我已经读取了今天的早报,有什么想了解的吗?比如某条新闻的意思、对哪些板块有影响。",
        "quickReplies": ["今天的早报讲了什么?", "今天最值得关注的是什么?", "有啥风险要注意?"],
    },
    "sector": {
        "name": "板块查询", "icon": "🏭",
        "description": "查询板块龙头股",
        "greeting": "👋 想了解哪个板块?我可以告诉你对应的龙头股和关键词。",
        "quickReplies": ["新能源板块有哪些龙头股?", "半导体板块关注什么?", "低空经济是什么?"],
    },
    "policy": {
        "name": "政策解读", "icon": "📜",
        "description": "通俗解释财经政策",
        "greeting": "👋 把政策原文或者关键词发给我,我用大白话解释 + 打比方 + 影响分析。",
        "quickReplies": ["降准是什么意思?", "LPR 调整影响房贷吗?", "集采对医药股是利好还是利空?"],
    },
    "concept": {
        "name": "概念科普", "icon": "📚",
        "description": "解释财经名词",
        "greeting": "👋 遇到不懂的财经名词?发给我,我用最简单的话+生活化比喻解释。",
        "quickReplies": ["什么是 PE?", "北向资金是什么?", "融资融券是啥意思?"],
    },
    "history": {
        "name": "历史回顾", "icon": "🗓",
        "description": "查看过去几天早报",
        "greeting": "👋 我可以帮你回顾过去 7 天的早报内容。",
        "quickReplies": ["本周讲了哪些大事?", "上周和这周比较?", "最近有啥政策?"],
    },
}


def bj_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def month_str() -> str:
    d = bj_now()
    return f"{d.year}-{d.month:02d}"


def day_str() -> str:
    d = bj_now()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def fetch_github(path: str) -> str:
    """优先读本地,失败再读 jsDelivr CDN(国内可达性较好)。"""
    local_candidates = {
        f"web/skills/{Path(path).name}": WEB_DIR / "skills" / Path(path).name,
        f"web/{Path(path).name}": WEB_DIR / Path(path).name,
        f"logs/{Path(path).name}": LOGS_DIR / Path(path).name,
        "config.yaml": CONFIG_PATH,
    }
    if path in local_candidates and local_candidates[path].exists():
        return local_candidates[path].read_text(encoding="utf-8")

    # jsDelivr CDN(国内可达性较好,但只对公开仓库有效)
    if GITHUB_TOKEN:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{path}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    else:
        url = f"https://cdn.jsdelivr.net/gh/{GITHUB_REPO}@main/{path}"
        headers = {}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text


def extract_system_prompt(md: str) -> str:
    if md.startswith("---"):
        fm_end = md.find("\n---", 3)
        if fm_end > 0:
            return md[fm_end + 4:].strip()
    return md.strip()


def extract_latest_day_brief(logs: str) -> str:
    day_key = f"## {day_str()}"
    idx = logs.rfind(day_key)
    if idx < 0:
        return logs[-3000:]
    next_section = logs.find("\n## ", idx + 5)
    return logs[idx:next_section].strip() if next_section > 0 else logs[idx:].strip()


def extract_recent_logs(logs: str) -> str:
    sections = re.split(r"\n## (?=\d{4}-\d{2}-\d{2})", logs)
    return "\n## ".join(sections[-7:]).strip()


def build_system_prompt(skill_id: str) -> str:
    md = fetch_github(f"web/skills/{skill_id}.md")
    prompt = extract_system_prompt(md)

    if "{{today_brief}}" in prompt:
        try:
            logs = fetch_github(f"logs/{month_str()}.md")
            prompt = prompt.replace("{{today_brief}}", extract_latest_day_brief(logs))
        except Exception as e:
            prompt = prompt.replace("{{today_brief}}", f"(今日早报暂未生成: {e})")

    if "{{recent_logs}}" in prompt:
        try:
            logs = fetch_github(f"logs/{month_str()}.md")
            prompt = prompt.replace("{{recent_logs}}", extract_recent_logs(logs))
        except Exception:
            prompt = prompt.replace("{{recent_logs}}", "(历史日志暂无)")

    if "{{sectors_config}}" in prompt:
        try:
            cfg = fetch_github("config.yaml")
            prompt = prompt.replace("{{sectors_config}}", cfg)
        except Exception:
            prompt = prompt.replace("{{sectors_config}}", "(配置加载失败)")

    return prompt


def call_deepseek(system_prompt: str, history: list, message: str) -> str:
    if not DEEPSEEK_KEY:
        return "⚠️ 未配置 DEEPSEEK_API_KEY 环境变量,无法调用 AI。\n\n请运行:\n```\nexport DEEPSEEK_API_KEY=sk-xxx\n```"
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
    data = r.json()
    return data["choices"][0]["message"]["content"]


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

    def _serve_static(self, path: Path, content_type: str):
        if not path.exists():
            self._send(b"Not Found", "text/plain", 404)
            return
        self._send(path.read_bytes(), content_type)

    def do_OPTIONS(self):
        self._send(b"ok", "text/plain")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/chat.html"):
            self._serve_static(WEB_DIR / "chat.html", "text/html; charset=utf-8")
        elif path == "/api/skills":
            skills = [
                {"id": k, "name": v["name"], "icon": v["icon"],
                 "description": v["description"], "default": v.get("default", False),
                 "greeting": v.get("greeting", ""), "quickReplies": v.get("quickReplies", [])}
                for k, v in SKILLS_META.items()
            ]
            self._json({"skills": skills})
        elif path == "/health":
            self._json({
                "ok": True,
                "service": "a-stock-chat-dev",
                "has_deepseek_key": bool(DEEPSEEK_KEY),
                "github_repo": GITHUB_REPO,
                "time": bj_now().isoformat(),
            })
        elif path.startswith("/skills/"):
            self._serve_static(WEB_DIR / path[1:], "text/markdown; charset=utf-8")
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
            skill_id = body.get("skill")
            message = body.get("message", "")
            history = body.get("history", [])
            if skill_id not in SKILLS_META:
                self._json({"error": f"未知 skill: {skill_id}"}, 400)
                return
            system_prompt = build_system_prompt(skill_id)
            reply = call_deepseek(system_prompt, history, message)
            self._json({"reply": reply})
        except Exception as e:
            self._json({"error": str(e)}, 502)


def open_browser():
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    if not DEEPSEEK_KEY:
        print("⚠️  未配置 DEEPSEEK_API_KEY,聊天会失败。")
        print("    export DEEPSEEK_API_KEY=sk-xxx")
        print()
    print(f"📁 本地目录: {ROOT}")
    print(f"🌐 访问地址: http://localhost:{PORT}")
    print(f"🔧 DeepSeek Key: {'已配置' if DEEPSEEK_KEY else '未配置'}")
    print(f"📦 GitHub Repo: {GITHUB_REPO}")
    print()
    print("按 Ctrl+C 停止")
    print()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Timer(1.0, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
