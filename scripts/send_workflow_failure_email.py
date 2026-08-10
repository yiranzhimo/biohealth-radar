#!/usr/bin/env python3
"""Send a compact GitHub Actions failure email using repository-configured SMTP."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path


def source_health() -> str:
    path = Path("data/raw/company_sources_latest.json")
    if not path.exists():
        return "公司来源快照：不存在"
    payload = json.loads(path.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])
    failed = [item for item in sources if item.get("lastCheckStatus") == "failed"]
    return f"公司来源：{len(sources)}；失败：{len(failed)}；失败率：{len(failed) / len(sources):.1%}" if sources else "公司来源：0"


def main() -> int:
    required = {
        "SMTP_HOST": os.environ.get("SMTP_HOST", ""),
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME", ""),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "ALERT_EMAIL": os.environ.get("ALERT_EMAIL", ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        print(f"::warning::Failure email skipped; missing configuration: {', '.join(missing)}")
        return 0

    workflow = os.environ.get("GITHUB_WORKFLOW", "BioHealth Radar scheduled task")
    repository = os.environ.get("GITHUB_REPOSITORY", "unknown repository")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repository}/actions/runs/{run_id}" if run_id else server
    message = EmailMessage()
    message["Subject"] = f"[BioHealth Radar] 定时任务失败：{workflow}"
    message["From"] = required["SMTP_USERNAME"]
    message["To"] = required["ALERT_EMAIL"]
    message.set_content(
        "\n".join([
            f"仓库：{repository}",
            f"工作流：{workflow}",
            f"运行记录：{run_url}",
            source_health(),
            "发布状态：本次失败数据未提交；网页继续保留上一次成功版本。",
        ])
    )
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(required["SMTP_HOST"], port, context=ssl.create_default_context(), timeout=20) as smtp:
        smtp.login(required["SMTP_USERNAME"], required["SMTP_PASSWORD"])
        smtp.send_message(message)
    print(f"Failure notification sent for {workflow}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::warning::Could not send failure email: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(0)
