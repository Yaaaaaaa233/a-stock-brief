"""同步 logs/、skills/、config.yaml 到 Cloudflare KV。

由 GitHub Actions 在跑完早报后调用。
Worker 之后只从 KV 读,完全不依赖 GitHub raw,父母访问最快。

KV key 命名规则:
  logs:YYYY-MM       月度归档(整月)
  logs:latest        最新一天的早报(便于 Worker 快速访问)
  skills:<id>        单个 skill 文件(如 skills:brief)
  config:yaml        config.yaml 全文

必需环境变量:
  CF_API_TOKEN       Cloudflare API Token(需 Workers KV Edit 权限)
  CF_ACCOUNT_ID      Cloudflare 账户 ID
  KV_NAMESPACE_ID    KV namespace ID
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT / "logs"
WEB_DIR = ROOT / "web"
SKILLS_DIR = WEB_DIR / "skills"
CONFIG_PATH = ROOT / "config.yaml"

CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
KV_NAMESPACE_ID = os.environ.get("KV_NAMESPACE_ID", "").strip()

CF_KV_API = (
    "https://api.cloudflare.com/client/v4/accounts/"
    "{account_id}/storage/kv/namespaces/{ns_id}/values/{key}"
)


def write_kv(key: str, value: str, expiration_ttl: int | None = None) -> tuple[bool, str]:
    """写入 KV 一条记录。返回 (是否成功, 错误信息)。"""
    if not all([CF_API_TOKEN, CF_ACCOUNT_ID, KV_NAMESPACE_ID]):
        return False, "未配置 Cloudflare 凭据"
    url = CF_KV_API.format(
        account_id=CF_ACCOUNT_ID,
        ns_id=KV_NAMESPACE_ID,
        key=key,
    )
    params = {}
    if expiration_ttl:
        params["expirationTtl"] = expiration_ttl
    try:
        r = requests.put(
            url,
            headers={
                "Authorization": f"Bearer {CF_API_TOKEN}",
                "Content-Type": "text/plain",
            },
            data=value.encode("utf-8"),
            params=params,
            timeout=30,
        )
        if r.status_code == 200:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, str(e)


def extract_latest_day(logs_content: str) -> str:
    """从月度归档里提取最新一天的内容。"""
    matches = list(re.finditer(r"\n## (\d{4}-\d{2}-\d{2})", logs_content))
    if not matches:
        return logs_content[-3000:]
    last = matches[-1]
    return logs_content[last.start():].strip()


def sync_logs() -> tuple[int, int]:
    """同步所有月度归档 + 最新一天。"""
    success = failed = 0
    log_files = sorted(LOGS_DIR.glob("*.md"))
    if not log_files:
        print("⚠️  logs/ 目录为空,跳过")
        return 0, 0

    for log_file in log_files:
        key = f"logs:{log_file.stem}"
        content = log_file.read_text(encoding="utf-8")
        ok, msg = write_kv(key, content)
        if ok:
            print(f"  ✓ {key} ({len(content):,} 字符)")
            success += 1
        else:
            print(f"  ✗ {key} 失败: {msg}", file=sys.stderr)
            failed += 1

    latest_file = log_files[-1]
    latest_content = latest_file.read_text(encoding="utf-8")
    latest_day = extract_latest_day(latest_content)
    ok, msg = write_kv("logs:latest", latest_day)
    if ok:
        print(f"  ✓ logs:latest ({len(latest_day):,} 字符,来自 {latest_file.name})")
        success += 1
    else:
        print(f"  ✗ logs:latest 失败: {msg}", file=sys.stderr)
        failed += 1

    return success, failed


def sync_skills() -> tuple[int, int]:
    """同步所有 skill 文件。"""
    success = failed = 0
    if not SKILLS_DIR.exists():
        print("⚠️  web/skills/ 不存在,跳过")
        return 0, 0

    for skill_file in SKILLS_DIR.glob("*.md"):
        key = f"skills:{skill_file.stem}"
        content = skill_file.read_text(encoding="utf-8")
        ok, msg = write_kv(key, content)
        if ok:
            print(f"  ✓ {key} ({len(content):,} 字符)")
            success += 1
        else:
            print(f"  ✗ {key} 失败: {msg}", file=sys.stderr)
            failed += 1

    return success, failed


def sync_config() -> tuple[int, int]:
    """同步 config.yaml。"""
    if not CONFIG_PATH.exists():
        print("⚠️  config.yaml 不存在,跳过")
        return 0, 0
    content = CONFIG_PATH.read_text(encoding="utf-8")
    ok, msg = write_kv("config:yaml", content)
    if ok:
        print(f"  ✓ config:yaml ({len(content):,} 字符)")
        return 1, 0
    print(f"  ✗ config:yaml 失败: {msg}", file=sys.stderr)
    return 0, 1


def main() -> int:
    if not all([CF_API_TOKEN, CF_ACCOUNT_ID, KV_NAMESPACE_ID]):
        print(
            "❌ 未配置 Cloudflare 凭据。需要以下环境变量:\n"
            "  CF_API_TOKEN\n"
            "  CF_ACCOUNT_ID\n"
            "  KV_NAMESPACE_ID",
            file=sys.stderr,
        )
        return 2

    print("=== 同步到 Cloudflare KV ===\n")

    print("[1/3] 同步 logs/...")
    s1, f1 = sync_logs()
    print()

    print("[2/3] 同步 skills/...")
    s2, f2 = sync_skills()
    print()

    print("[3/3] 同步 config.yaml...")
    s3, f3 = sync_config()
    print()

    total_s = s1 + s2 + s3
    total_f = f1 + f2 + f3
    print(f"=== 完成:{total_s} 成功,{total_f} 失败 ===")

    return 0 if total_f == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
