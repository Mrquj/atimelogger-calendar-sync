from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


PROJECT_DIR = Path(__file__).resolve().parent
NPM_COMMAND = "npm.cmd" if os.name == "nt" else "npm"


def extract_summary(output: str) -> dict | None:
    decoder = json.JSONDecoder()
    last_summary = None

    for index, char in enumerate(output):
        if char != "{":
            continue

        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue

        if isinstance(value, dict) and "calendarEvents" in value and "dryRun" in value:
            last_summary = value

    return last_summary


def build_message(summary: dict | None, raw_output: str, returncode: int) -> tuple[str, str]:
    if not summary:
        title = "同步失败" if returncode else "同步完成"
        body = raw_output.strip() or "没有收到同步结果。"
        return title, body[-1800:]

    created = summary.get("created", 0)
    skipped = summary.get("skipped", 0)
    failed = summary.get("failed", 0)
    dry_run = summary.get("dryRun", False)
    activity_type = summary.get("resolvedActivityType") or summary.get("activityType")

    title = "同步完成" if failed == 0 and returncode == 0 else "同步有失败项"
    lines = [
        f"日期：{summary.get('date', '')}",
        f"时区：{summary.get('timezone', '')}",
        f"日历事件：{summary.get('calendarEvents', 0)} 条",
        f"aTimeLogger 活动：{activity_type}",
        f"新建：{created} 条",
        f"已跳过：{skipped} 条",
        f"失败：{failed} 条",
        f"测试模式：{'是' if dry_run else '否'}",
    ]

    failures = summary.get("failures") or []
    if failures:
        lines.append("")
        lines.append("失败明细：")
        for item in failures[:5]:
            reason = str(item.get("reason", "")).replace("\n", " ")
            lines.append(f"- {item.get('title', '')}：{reason[:220]}")

    return title, "\n".join(lines)


def run_sync() -> tuple[int, str]:
    if not shutil.which(NPM_COMMAND):
        return 1, "没有找到 npm。请先确认 Node.js/npm 可以正常运行。"

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    env = os.environ.copy()
    env["NO_COLOR"] = "1"

    completed = subprocess.run(
        [NPM_COMMAND, "run", "sync:atimelogger-calendar"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        startupinfo=startupinfo,
    )

    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    return completed.returncode, output


def main() -> None:
    root = tk.Tk()
    root.title("课程表同步到 aTimeLogger")
    root.geometry("360x120")
    root.resizable(False, False)

    label = tk.Label(root, text="正在同步课程表到 aTimeLogger...", padx=24, pady=28)
    label.pack(fill="both", expand=True)

    def worker() -> None:
        returncode, output = run_sync()
        summary = extract_summary(output)
        title, message = build_message(summary, output, returncode)

        def finish() -> None:
            label.config(text=message)
            if returncode == 0:
                messagebox.showinfo(title, message, parent=root)
            else:
                messagebox.showerror(title, message, parent=root)
            root.destroy()

        root.after(0, finish)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        messagebox.showerror("同步失败", str(error))
        sys.exit(1)
