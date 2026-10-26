from __future__ import annotations

import calendar
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import atimelogger_automation as automation
import atimelogger_calendars as calendar_settings
import toggl_atimelogger_settings as toggl_sync


PROJECT_DIR = Path(__file__).resolve().parent
NPM_COMMAND = "npm.cmd" if os.name == "nt" else "npm"


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return day.replace(year=year, month=month, day=min(day.day, last_day))


def parse_date(value: str) -> date | None:
    value = value.strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


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
    calendars = summary.get("calendars") or []

    title = "同步完成" if failed == 0 and returncode == 0 else "同步有失败项"
    lines = [
        f"日期：{summary.get('date', '')}",
        f"时区：{summary.get('timezone', '')}",
        f"日历：{', '.join(calendars) if calendars else '默认日历'}",
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


def build_range_message(start_date: date, results: list[tuple[int, str, dict | None]]) -> tuple[str, str]:
    end_date = start_date + timedelta(days=len(results) - 1)
    totals = {
        "calendarEvents": 0,
        "created": 0,
        "skipped": 0,
        "failed": 0,
    }
    failed_dates = []

    for offset, (returncode, _output, summary) in enumerate(results):
        current_date = start_date + timedelta(days=offset)
        if not summary:
            failed_dates.append(current_date.isoformat())
            totals["failed"] += 1
            continue

        for key in totals:
            totals[key] += int(summary.get(key, 0) or 0)

        if returncode != 0:
            failed_dates.append(current_date.isoformat())

    title = "一周同步完成" if not failed_dates and totals["failed"] == 0 else "一周同步有失败项"
    lines = [
        f"日期范围：{start_date.isoformat()} 至 {end_date.isoformat()}",
        f"日历事件：{totals['calendarEvents']} 条",
        f"新建：{totals['created']} 条",
        f"已跳过：{totals['skipped']} 条",
        f"失败：{totals['failed']} 条",
    ]

    if failed_dates:
        lines.append(f"执行失败日期：{', '.join(failed_dates)}")

    return title, "\n".join(lines)


def run_sync(target_date: str, calendar_ids: list[str] | None = None) -> tuple[int, str]:
    if not shutil.which(NPM_COMMAND):
        return 1, "没有找到 npm。请先确认 Node.js/npm 可以正常运行。"

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    env = os.environ.copy()
    env["NO_COLOR"] = "1"

    command = [
        NPM_COMMAND,
        "run",
        "sync:atimelogger-calendar",
        "--",
        "--date",
        target_date,
    ]
    if calendar_ids is not None:
        command.extend(["--calendars", ",".join(calendar_ids)])

    completed = subprocess.run(
        command,
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
    root.title("Google Calendar 同步到 aTimeLogger")
    root.geometry("680x760")
    root.resizable(False, False)

    today = date.today()
    selected_date = tk.StringVar(value=today.isoformat())
    sync_days = tk.IntVar(value=1)
    status = tk.StringVar(value="选择单日或连续 7 天，然后点击开始同步。")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=12, pady=12)

    loaded_calendar_config = calendar_settings.load_config()
    managed_calendars = list(loaded_calendar_config["calendars"])
    saved_calendar_ids = list(loaded_calendar_config["selectedCalendarIds"])

    frame = ttk.Frame(notebook, padding=18)
    notebook.add(frame, text="手动同步")

    tk.Label(frame, text="起始日期（YYYY-MM-DD）").grid(row=0, column=0, columnspan=4, sticky="w")
    date_entry = tk.Entry(frame, textvariable=selected_date, width=18)
    date_entry.grid(row=1, column=0, columnspan=4, sticky="we", pady=(6, 10))

    mode_frame = tk.Frame(frame)
    mode_frame.grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 10))
    tk.Label(mode_frame, text="同步范围：").pack(side="left")
    tk.Radiobutton(mode_frame, text="单日", variable=sync_days, value=1).pack(side="left")
    tk.Radiobutton(mode_frame, text="连续 7 天", variable=sync_days, value=7).pack(side="left")

    def set_date(value: date, days: int = 1) -> None:
        selected_date.set(value.isoformat())
        sync_days.set(days)

    this_week = today - timedelta(days=today.weekday())

    tk.Button(frame, text="今天", command=lambda: set_date(today)).grid(row=3, column=0, sticky="we", padx=(0, 6))
    tk.Button(frame, text="昨天", command=lambda: set_date(today - timedelta(days=1))).grid(row=3, column=1, sticky="we", padx=6)
    tk.Button(frame, text="一周前", command=lambda: set_date(today - timedelta(days=7))).grid(row=3, column=2, sticky="we", padx=6)
    tk.Button(frame, text="一个月前", command=lambda: set_date(add_months(today, -1))).grid(row=3, column=3, sticky="we", padx=(6, 0))

    tk.Button(frame, text="本周", command=lambda: set_date(this_week, 7)).grid(row=4, column=0, sticky="we", padx=(0, 6), pady=(8, 0))
    tk.Button(frame, text="上周", command=lambda: set_date(this_week - timedelta(days=7), 7)).grid(row=4, column=1, sticky="we", padx=6, pady=(8, 0))
    tk.Button(frame, text="最近 7 天", command=lambda: set_date(today - timedelta(days=6), 7)).grid(row=4, column=2, columnspan=2, sticky="we", padx=(6, 0), pady=(8, 0))

    status_label = tk.Label(frame, textvariable=status, anchor="w", justify="left", wraplength=380)
    status_label.grid(row=5, column=0, columnspan=4, sticky="we", pady=(14, 8))

    start_button = tk.Button(frame, text="开始同步")
    start_button.grid(row=6, column=0, columnspan=4, sticky="we")

    for index in range(4):
        frame.columnconfigure(index, weight=1)

    def set_controls_enabled(enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        date_entry.config(state=state)
        start_button.config(state=state)
        for child in frame.winfo_children():
            if isinstance(child, tk.Button) and child is not start_button:
                child.config(state=state)
        for child in mode_frame.winfo_children():
            if isinstance(child, tk.Radiobutton):
                child.config(state=state)

    def start() -> None:
        target_date = parse_date(selected_date.get())
        if not target_date:
            messagebox.showerror("日期格式错误", "请输入类似 2026-06-08 的日期。", parent=root)
            return

        calendar_ids = get_selected_calendar_ids()
        if not calendar_ids:
            messagebox.showerror("没有选择日历", "请在“日历”页面至少选择一个日历。", parent=root)
            return

        days = sync_days.get()
        end_date = target_date + timedelta(days=days - 1)
        set_controls_enabled(False)
        if days == 1:
            status.set(f"正在同步 {target_date.isoformat()} 的课程表...")
        else:
            status.set(f"正在同步 {target_date.isoformat()} 至 {end_date.isoformat()}...")

        def worker() -> None:
            results = []
            for offset in range(days):
                current_date = target_date + timedelta(days=offset)
                root.after(
                    0,
                    lambda current=current_date, number=offset + 1: status.set(
                        f"正在同步 {current.isoformat()}（{number}/{days}）..."
                    ),
                )
                returncode, output = run_sync(current_date.isoformat(), calendar_ids)
                results.append((returncode, output, extract_summary(output)))

            if days == 1:
                returncode, output, summary = results[0]
                title, message = build_message(summary, output, returncode)
                has_error = returncode != 0
            else:
                title, message = build_range_message(target_date, results)
                has_error = any(returncode != 0 for returncode, _output, _summary in results)

            def finish() -> None:
                status.set(message)
                set_controls_enabled(True)
                if has_error:
                    messagebox.showerror(title, message, parent=root)
                else:
                    messagebox.showinfo(title, message, parent=root)

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    start_button.config(command=start)

    calendar_frame = ttk.Frame(notebook, padding=18)
    notebook.add(calendar_frame, text="日历")

    ttk.Label(
        calendar_frame,
        text="选择需要同步的一个或多个日历。保存后的选择也会用于后台自动同步。",
        wraplength=500,
        justify="left",
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    calendar_list = tk.Listbox(
        calendar_frame,
        selectmode=tk.MULTIPLE,
        exportselection=False,
        height=10,
    )
    calendar_list.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(0, 10))

    def refresh_calendar_list(selected_ids: list[str] | None = None) -> None:
        if selected_ids is None:
            selected_ids = get_selected_calendar_ids() if calendar_list.size() else saved_calendar_ids

        calendar_list.delete(0, tk.END)
        for index, calendar in enumerate(managed_calendars):
            suffix = "（默认课程表）" if calendar.get("default") else ""
            calendar_list.insert(tk.END, f"{calendar['name']}{suffix}")
            if calendar["id"] in selected_ids:
                calendar_list.selection_set(index)

    def get_selected_calendar_ids() -> list[str]:
        return [
            managed_calendars[index]["id"]
            for index in calendar_list.curselection()
            if index < len(managed_calendars)
        ]

    def select_all_calendars() -> None:
        calendar_list.selection_set(0, tk.END)

    def clear_calendar_selection() -> None:
        calendar_list.selection_clear(0, tk.END)

    def save_calendar_selection(show_message: bool = True) -> bool:
        selected_ids = get_selected_calendar_ids()
        if not selected_ids:
            messagebox.showerror("没有选择日历", "请至少选择一个日历。", parent=root)
            return False

        calendar_settings.save_config(managed_calendars, selected_ids)
        if show_message:
            messagebox.showinfo(
                "已保存",
                f"已选择 {len(selected_ids)} 个日历。手动和自动同步都会使用这些日历。",
                parent=root,
            )
        return True

    name_var = tk.StringVar()
    url_var = tk.StringVar()
    ttk.Label(calendar_frame, text="新日历名称").grid(row=3, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(calendar_frame, textvariable=name_var).grid(row=4, column=0, sticky="we", padx=(0, 6), pady=(4, 8))
    ttk.Label(calendar_frame, text="Google Calendar 私密 iCal 地址").grid(
        row=3, column=1, columnspan=2, sticky="w", pady=(4, 0)
    )
    ttk.Entry(calendar_frame, textvariable=url_var).grid(
        row=4, column=1, columnspan=2, sticky="we", padx=(6, 0), pady=(4, 8)
    )

    def add_calendar() -> None:
        name = name_var.get().strip()
        url = url_var.get().strip()
        if not name:
            messagebox.showerror("缺少名称", "请输入日历名称。", parent=root)
            return
        if not url.startswith(("https://", "http://")):
            messagebox.showerror("地址无效", "请输入完整的 Google Calendar 私密 iCal 地址。", parent=root)
            return
        if any(calendar.get("url") == url for calendar in managed_calendars):
            messagebox.showerror("日历已存在", "这个 iCal 地址已经添加。", parent=root)
            return

        selected_ids = get_selected_calendar_ids()
        calendar = calendar_settings.add_calendar(name, url)
        managed_calendars.append(calendar)
        selected_ids.append(calendar["id"])
        refresh_calendar_list(selected_ids)
        name_var.set("")
        url_var.set("")
        save_calendar_selection(show_message=False)

    def rename_calendar() -> None:
        selected_indexes = list(calendar_list.curselection())
        if len(selected_indexes) != 1:
            messagebox.showinfo("选择一个日历", "请只选择一个需要重命名的附加日历。", parent=root)
            return

        calendar = managed_calendars[selected_indexes[0]]
        if calendar.get("default"):
            messagebox.showinfo("默认日历", "默认课程表名称不能在这里修改。", parent=root)
            return

        new_name = simpledialog.askstring(
            "重命名日历",
            "输入新的日历名称：",
            initialvalue=calendar["name"],
            parent=root,
        )
        if not new_name or not new_name.strip():
            return
        calendar["name"] = new_name.strip()
        refresh_calendar_list([calendar["id"]])
        save_calendar_selection(show_message=False)

    def delete_calendars() -> None:
        selected_ids = set(get_selected_calendar_ids())
        removable = [
            calendar for calendar in managed_calendars
            if calendar["id"] in selected_ids and not calendar.get("default")
        ]
        if not removable:
            messagebox.showinfo("没有可删除日历", "默认课程表不能删除，请选择附加日历。", parent=root)
            return
        if not messagebox.askyesno(
            "删除日历",
            f"确定删除选中的 {len(removable)} 个附加日历吗？",
            parent=root,
        ):
            return

        removable_ids = {calendar["id"] for calendar in removable}
        managed_calendars[:] = [
            calendar for calendar in managed_calendars if calendar["id"] not in removable_ids
        ]
        remaining_ids = [
            calendar["id"] for calendar in managed_calendars
            if calendar["id"] in selected_ids and calendar["id"] not in removable_ids
        ]
        if not remaining_ids and managed_calendars:
            remaining_ids = [managed_calendars[0]["id"]]
        refresh_calendar_list(remaining_ids)
        if remaining_ids:
            save_calendar_selection(show_message=False)
        else:
            calendar_settings.save_config(managed_calendars, [])

    calendar_buttons = ttk.Frame(calendar_frame)
    calendar_buttons.grid(row=2, column=0, columnspan=3, sticky="we", pady=(0, 8))
    ttk.Button(calendar_buttons, text="全选", command=select_all_calendars).grid(row=0, column=0, sticky="we")
    ttk.Button(calendar_buttons, text="取消选择", command=clear_calendar_selection).grid(
        row=0, column=1, sticky="we", padx=6
    )
    ttk.Button(calendar_buttons, text="保存日历选择", command=save_calendar_selection).grid(
        row=0, column=2, sticky="we"
    )

    ttk.Button(calendar_frame, text="添加日历", command=add_calendar).grid(
        row=5, column=0, sticky="we", padx=(0, 6)
    )
    ttk.Button(calendar_frame, text="重命名选中", command=rename_calendar).grid(
        row=5, column=1, sticky="we", padx=6
    )
    ttk.Button(calendar_frame, text="删除选中附加日历", command=delete_calendars).grid(
        row=5, column=2, sticky="we", padx=(6, 0)
    )

    calendar_frame.columnconfigure(0, weight=1)
    calendar_frame.columnconfigure(1, weight=1)
    calendar_frame.columnconfigure(2, weight=1)
    calendar_buttons.columnconfigure(0, weight=1)
    calendar_buttons.columnconfigure(1, weight=1)
    calendar_buttons.columnconfigure(2, weight=1)
    refresh_calendar_list()

    toggl_frame = ttk.Frame(notebook, padding=18)
    notebook.add(toggl_frame, text="Toggl 双向同步")

    toggl_config = toggl_sync.load_config()
    toggl_token = tk.StringVar(value=toggl_config.get("togglApiToken", ""))
    toggl_username = tk.StringVar(value=toggl_config.get("togglUsername", ""))
    toggl_password = tk.StringVar(value=toggl_config.get("togglPassword", ""))
    toggl_workspace = tk.StringVar(value=str(toggl_config.get("togglWorkspaceId", "") or ""))
    toggl_direction_label = tk.StringVar(
        value=toggl_sync.DIRECTION_VALUES.get(toggl_config.get("direction", "both"), "双向同步")
    )
    toggl_activity_type = tk.StringVar(
        value=toggl_config.get("atimeloggerActivityTypeName", "工作")
    )
    toggl_export_types = tk.StringVar(
        value=toggl_config.get("atimeloggerToTogglTypeNames", "")
    )
    toggl_include_calendar = tk.BooleanVar(
        value=bool(toggl_config.get("includeGoogleCalendar", False))
    )
    toggl_source_filter_label = tk.StringVar(
        value=toggl_sync.SOURCE_FILTER_VALUES.get(
            toggl_config.get("togglSourceFilter", "exclude-calendar"),
            "排除日历来源记录",
        )
    )
    toggl_calendar_keywords = tk.StringVar(
        value=toggl_config.get(
            "calendarSourceKeywords",
            "calendar,google calendar,outlook,ical",
        )
    )
    toggl_duplicate_policy_label = tk.StringVar(
        value=toggl_sync.DUPLICATE_POLICY_VALUES.get(
            toggl_config.get("duplicatePolicy", "exact"),
            "同标题且时间完全一致",
        )
    )
    toggl_from_date = tk.StringVar(value=today.isoformat())
    toggl_days = tk.IntVar(value=1)
    toggl_status = tk.StringVar(value="就绪。测试模式不会写入或覆盖数据。")

    ttk.Label(
        toggl_frame,
        text="Toggl API token 为推荐登录方式。也可以不填 token，改用 Toggl 账号和密码。",
        wraplength=580,
        justify="left",
    ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

    ttk.Label(toggl_frame, text="Toggl API token").grid(row=1, column=0, columnspan=2, sticky="w")
    ttk.Entry(toggl_frame, textvariable=toggl_token, show="*").grid(
        row=2, column=0, columnspan=2, sticky="we", padx=(0, 8), pady=(4, 8)
    )
    ttk.Label(toggl_frame, text="工作区 ID（可留空自动获取）").grid(
        row=1, column=2, columnspan=2, sticky="w"
    )
    ttk.Entry(toggl_frame, textvariable=toggl_workspace).grid(
        row=2, column=2, columnspan=2, sticky="we", padx=(8, 0), pady=(4, 8)
    )

    ttk.Label(toggl_frame, text="Toggl 账号（token 留空时使用）").grid(
        row=3, column=0, columnspan=2, sticky="w"
    )
    ttk.Entry(toggl_frame, textvariable=toggl_username).grid(
        row=4, column=0, columnspan=2, sticky="we", padx=(0, 8), pady=(4, 8)
    )
    ttk.Label(toggl_frame, text="Toggl 密码").grid(row=3, column=2, columnspan=2, sticky="w")
    ttk.Entry(toggl_frame, textvariable=toggl_password, show="*").grid(
        row=4, column=2, columnspan=2, sticky="we", padx=(8, 0), pady=(4, 8)
    )

    ttk.Label(toggl_frame, text="同步方向").grid(row=5, column=0, columnspan=2, sticky="w")
    ttk.Combobox(
        toggl_frame,
        textvariable=toggl_direction_label,
        values=list(toggl_sync.DIRECTION_LABELS),
        state="readonly",
    ).grid(row=6, column=0, columnspan=2, sticky="we", padx=(0, 8), pady=(4, 8))
    ttk.Label(toggl_frame, text="Toggl → aTimeLogger 活动类型").grid(
        row=5, column=2, columnspan=2, sticky="w"
    )
    ttk.Entry(toggl_frame, textvariable=toggl_activity_type).grid(
        row=6, column=2, columnspan=2, sticky="we", padx=(8, 0), pady=(4, 8)
    )

    ttk.Label(
        toggl_frame,
        text="aTimeLogger → Toggl 类型筛选（逗号分隔，留空表示全部）",
    ).grid(row=7, column=0, columnspan=4, sticky="w")
    ttk.Entry(toggl_frame, textvariable=toggl_export_types).grid(
        row=8, column=0, columnspan=4, sticky="we", pady=(4, 6)
    )
    ttk.Checkbutton(
        toggl_frame,
        text="允许把 Google Calendar 导入的 aTimeLogger 记录继续同步到 Toggl",
        variable=toggl_include_calendar,
    ).grid(row=9, column=0, columnspan=4, sticky="w", pady=(0, 10))

    ttk.Label(toggl_frame, text="Toggl 来源过滤").grid(row=10, column=0, columnspan=2, sticky="w")
    ttk.Combobox(
        toggl_frame,
        textvariable=toggl_source_filter_label,
        values=list(toggl_sync.SOURCE_FILTER_LABELS),
        state="readonly",
    ).grid(row=11, column=0, columnspan=2, sticky="we", padx=(0, 8), pady=(4, 8))
    ttk.Label(toggl_frame, text="同步前重复检查").grid(row=10, column=2, columnspan=2, sticky="w")
    ttk.Combobox(
        toggl_frame,
        textvariable=toggl_duplicate_policy_label,
        values=list(toggl_sync.DUPLICATE_POLICY_LABELS),
        state="readonly",
    ).grid(row=11, column=2, columnspan=2, sticky="we", padx=(8, 0), pady=(4, 8))

    ttk.Label(
        toggl_frame,
        text="日历来源关键词（用于识别 created_with、origin_feature 和集成来源，英文逗号分隔）",
        wraplength=580,
        justify="left",
    ).grid(row=12, column=0, columnspan=4, sticky="w")
    ttk.Entry(toggl_frame, textvariable=toggl_calendar_keywords).grid(
        row=13, column=0, columnspan=4, sticky="we", pady=(4, 8)
    )

    ttk.Separator(toggl_frame).grid(row=14, column=0, columnspan=4, sticky="we", pady=(0, 10))
    ttk.Label(toggl_frame, text="同步起始日期（YYYY-MM-DD）").grid(
        row=15, column=0, columnspan=2, sticky="w"
    )
    ttk.Entry(toggl_frame, textvariable=toggl_from_date).grid(
        row=16, column=0, columnspan=2, sticky="we", padx=(0, 8), pady=(4, 8)
    )
    toggl_range_frame = ttk.Frame(toggl_frame)
    toggl_range_frame.grid(row=16, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=(4, 8))
    ttk.Radiobutton(toggl_range_frame, text="单日", variable=toggl_days, value=1).pack(side="left")
    ttk.Radiobutton(toggl_range_frame, text="连续 7 天", variable=toggl_days, value=7).pack(side="left")

    def set_toggl_date(value: date, days: int = 1) -> None:
        toggl_from_date.set(value.isoformat())
        toggl_days.set(days)

    ttk.Button(toggl_frame, text="今天", command=lambda: set_toggl_date(today)).grid(
        row=17, column=0, sticky="we", padx=(0, 4)
    )
    ttk.Button(toggl_frame, text="昨天", command=lambda: set_toggl_date(today - timedelta(days=1))).grid(
        row=17, column=1, sticky="we", padx=4
    )
    ttk.Button(toggl_frame, text="本周", command=lambda: set_toggl_date(this_week, 7)).grid(
        row=17, column=2, sticky="we", padx=4
    )
    ttk.Button(
        toggl_frame,
        text="上周",
        command=lambda: set_toggl_date(this_week - timedelta(days=7), 7),
    ).grid(row=17, column=3, sticky="we", padx=(4, 0))

    ttk.Label(toggl_frame, textvariable=toggl_status).grid(
        row=18, column=0, columnspan=4, sticky="w", pady=(10, 8)
    )

    def collect_toggl_config() -> dict:
        return {
            "togglApiToken": toggl_token.get().strip(),
            "togglUsername": toggl_username.get().strip(),
            "togglPassword": toggl_password.get(),
            "togglWorkspaceId": toggl_workspace.get().strip(),
            "direction": toggl_sync.DIRECTION_LABELS[toggl_direction_label.get()],
            "atimeloggerActivityTypeName": toggl_activity_type.get().strip() or "工作",
            "atimeloggerToTogglTypeNames": toggl_export_types.get().strip(),
            "includeGoogleCalendar": toggl_include_calendar.get(),
            "togglSourceFilter": toggl_sync.SOURCE_FILTER_LABELS[
                toggl_source_filter_label.get()
            ],
            "calendarSourceKeywords": toggl_calendar_keywords.get().strip(),
            "duplicatePolicy": toggl_sync.DUPLICATE_POLICY_LABELS[
                toggl_duplicate_policy_label.get()
            ],
            "autoSyncEnabled": toggl_config.get("autoSyncEnabled", False),
            "autoTogglToAtimelogger": toggl_config.get(
                "autoTogglToAtimelogger", False
            ),
            "autoAtimeloggerToToggl": toggl_config.get(
                "autoAtimeloggerToToggl", False
            ),
        }

    def save_toggl_config(show_message: bool = True) -> bool:
        config = collect_toggl_config()
        if not (
            config["togglApiToken"]
            or (config["togglUsername"] and config["togglPassword"])
        ):
            messagebox.showerror(
                "缺少 Toggl 登录信息",
                "请填写 Toggl API token，或同时填写 Toggl 账号和密码。",
                parent=root,
            )
            return False
        toggl_config.clear()
        toggl_config.update(config)
        toggl_sync.save_config(config)
        if show_message:
            direction_name = toggl_sync.DIRECTION_VALUES.get(config["direction"], config["direction"])
            target_note = (
                f"\nToggl 导入目标活动类型：{config['atimeloggerActivityTypeName']}"
                if config["direction"] != "atimelogger-to-toggl"
                else "\n当前方向不包含 Toggl → aTimeLogger，因此导入目标活动类型不会使用。"
            )
            messagebox.showinfo(
                "已保存",
                f"同步方向：{direction_name}{target_note}",
                parent=root,
            )
        return True

    def run_toggl_sync(dry_run: bool) -> None:
        target_date = parse_date(toggl_from_date.get())
        if not target_date:
            messagebox.showerror("日期格式错误", "请输入类似 2026-06-13 的日期。", parent=root)
            return
        if not save_toggl_config(show_message=False):
            return

        end_date = target_date + timedelta(days=toggl_days.get() - 1)
        set_toggl_run_controls(False)
        mode_name = "测试" if dry_run else "同步"
        toggl_status.set(f"正在{mode_name} {target_date.isoformat()} 至 {end_date.isoformat()}...")

        def worker() -> None:
            try:
                returncode, output, summary = toggl_sync.run_sync(
                    target_date.isoformat(),
                    end_date.isoformat(),
                    toggl_sync.DIRECTION_LABELS[toggl_direction_label.get()],
                    dry_run,
                )
                title, message = toggl_sync.build_summary_message(summary, output, returncode)
            except Exception as error:
                returncode = 1
                title = f"{mode_name}失败"
                message = str(error)

            def finish() -> None:
                set_toggl_result(message)
                toggl_status.set(f"{mode_name}完成，可以继续测试或执行同步。")
                set_toggl_run_controls(True)
                if returncode == 0:
                    messagebox.showinfo(title, message, parent=root)
                else:
                    messagebox.showerror(title, message, parent=root)

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    toggl_buttons = ttk.Frame(toggl_frame)
    toggl_buttons.grid(row=19, column=0, columnspan=4, sticky="we")
    toggl_save_button = ttk.Button(toggl_buttons, text="保存配置", command=save_toggl_config)
    toggl_save_button.grid(
        row=0, column=0, sticky="we", padx=(0, 4)
    )
    toggl_test_button = ttk.Button(
        toggl_buttons,
        text="测试模式",
        command=lambda: run_toggl_sync(True),
    )
    toggl_test_button.grid(
        row=0, column=1, sticky="we", padx=4
    )
    toggl_run_button = ttk.Button(
        toggl_buttons,
        text="执行双向同步",
        command=lambda: run_toggl_sync(False),
    )
    toggl_run_button.grid(
        row=0, column=2, sticky="we", padx=(4, 0)
    )

    toggl_result_frame = ttk.Frame(toggl_frame)
    toggl_result_frame.grid(row=20, column=0, columnspan=4, sticky="nsew", pady=(10, 0))
    toggl_result_text = tk.Text(
        toggl_result_frame,
        height=8,
        wrap="word",
        state="disabled",
    )
    toggl_result_scroll = ttk.Scrollbar(
        toggl_result_frame,
        orient="vertical",
        command=toggl_result_text.yview,
    )
    toggl_result_text.config(yscrollcommand=toggl_result_scroll.set)
    toggl_result_text.grid(row=0, column=0, sticky="nsew")
    toggl_result_scroll.grid(row=0, column=1, sticky="ns")
    toggl_result_frame.columnconfigure(0, weight=1)
    toggl_result_frame.rowconfigure(0, weight=1)

    def set_toggl_result(message: str) -> None:
        toggl_result_text.config(state="normal")
        toggl_result_text.delete("1.0", tk.END)
        toggl_result_text.insert("1.0", message)
        toggl_result_text.config(state="disabled")

    def set_toggl_run_controls(enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        toggl_save_button.config(state=state)
        toggl_test_button.config(state=state)
        toggl_run_button.config(state=state)

    set_toggl_result("尚未运行测试。测试模式不会创建、更新或覆盖任何记录。")

    for index in range(4):
        toggl_frame.columnconfigure(index, weight=1)
    toggl_frame.rowconfigure(20, weight=1)
    for index in range(3):
        toggl_buttons.columnconfigure(index, weight=1)

    auto_frame = ttk.Frame(notebook, padding=18)
    notebook.add(auto_frame, text="自动同步")

    saved_settings = automation.load_settings()
    startup_sync = tk.BooleanVar(value=automation.startup_enabled())
    app_open_sync = tk.BooleanVar(value=bool(saved_settings.get("sync_when_app_opens", False)))
    calendar_auto_sync = tk.BooleanVar(value=bool(saved_settings.get("calendar_sync_enabled", True)))
    toggl_to_atime_auto_sync = tk.BooleanVar(
        value=bool(toggl_config.get("autoTogglToAtimelogger", False))
    )
    atime_to_toggl_auto_sync = tk.BooleanVar(
        value=bool(toggl_config.get("autoAtimeloggerToToggl", False))
    )
    fixed_schedule = tk.BooleanVar(value=automation.task_exists())
    frequency = tk.StringVar(value=saved_settings.get("frequency", "每天"))
    sync_time = tk.StringVar(value=saved_settings.get("sync_time", "06:00"))
    weekday = tk.StringVar(value=saved_settings.get("weekday", "星期一"))
    calendar_days = tk.IntVar(value=max(1, int(saved_settings.get("calendar_sync_days", 3) or 3)))
    auto_status = tk.StringVar()

    ttk.Label(
        auto_frame,
        text=f"当前平台：{automation.platform_label()}。以下自动同步直接运行本地脚本，不依赖 Codex。",
        wraplength=500,
        justify="left",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Checkbutton(
        auto_frame,
        text="登录系统后自动同步今天（无需打开本脚本）",
        variable=startup_sync,
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))

    ttk.Checkbutton(
        auto_frame,
        text="打开本脚本时自动同步今天",
        variable=app_open_sync,
    ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(auto_frame, text="自动同步内容").grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )

    ttk.Checkbutton(
        auto_frame,
        text="Google Calendar → aTimeLogger",
        variable=calendar_auto_sync,
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 6))

    ttk.Checkbutton(
        auto_frame,
        text="Toggl → aTimeLogger",
        variable=toggl_to_atime_auto_sync,
    ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))

    ttk.Checkbutton(
        auto_frame,
        text="aTimeLogger → Toggl",
        variable=atime_to_toggl_auto_sync,
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Separator(auto_frame).grid(row=7, column=0, columnspan=2, sticky="we", pady=(0, 12))

    ttk.Checkbutton(
        auto_frame,
        text="启用固定时间自动同步",
        variable=fixed_schedule,
    ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 10))

    ttk.Label(auto_frame, text="运行频率").grid(row=9, column=0, sticky="w")
    frequency_box = ttk.Combobox(
        auto_frame,
        textvariable=frequency,
        values=list(automation.FREQUENCIES),
        state="readonly",
        width=20,
    )
    frequency_box.grid(row=10, column=0, sticky="we", padx=(0, 8), pady=(5, 10))

    ttk.Label(auto_frame, text="运行时间（24 小时制）").grid(row=9, column=1, sticky="w")
    time_entry = ttk.Entry(auto_frame, textvariable=sync_time, width=14)
    time_entry.grid(row=10, column=1, sticky="we", padx=(8, 0), pady=(5, 10))

    weekday_label = ttk.Label(auto_frame, text="每周运行日")
    weekday_label.grid(row=11, column=0, sticky="w")
    weekday_box = ttk.Combobox(
        auto_frame,
        textvariable=weekday,
        values=list(automation.WEEKDAYS),
        state="readonly",
        width=20,
    )
    weekday_box.grid(row=12, column=0, columnspan=2, sticky="we", pady=(5, 12))

    ttk.Label(auto_frame, text="日历回溯天数（每次自动同步检查最近 N 天并更新变更）").grid(
        row=13, column=0, sticky="w"
    )
    ttk.Spinbox(auto_frame, from_=1, to=31, textvariable=calendar_days, width=6).grid(
        row=13, column=1, sticky="w", pady=(0, 10)
    )

    ttk.Label(
        auto_frame,
        text="自动任务每次同步最近 N 天（今天及往前，默认 3 天），用于捕捉已改动的日程。历史补同步请使用“手动同步”页面。",
        wraplength=500,
        justify="left",
    ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(0, 10))

    ttk.Label(auto_frame, textvariable=auto_status, wraplength=500, justify="left").grid(
        row=15, column=0, columnspan=2, sticky="w", pady=(0, 10)
    )

    def selected_auto_toggl_direction() -> str | None:
        to_atime = toggl_to_atime_auto_sync.get()
        to_toggl = atime_to_toggl_auto_sync.get()
        if to_atime and to_toggl:
            return "both"
        if to_atime:
            return "toggl-to-atimelogger"
        if to_toggl:
            return "atimelogger-to-toggl"
        return None

    def refresh_auto_status() -> None:
        startup_text = "已启用" if automation.startup_enabled() else "未启用"
        fixed_text = automation.task_backend_label()
        selected = []
        if calendar_auto_sync.get():
            selected.append("日历")
        if toggl_to_atime_auto_sync.get():
            selected.append("Toggl → aTimeLogger")
        if atime_to_toggl_auto_sync.get():
            selected.append("aTimeLogger → Toggl")
        content_text = "、".join(selected) if selected else "未选择"
        auto_status.set(
            f"自动内容：{content_text}；登录后同步：{startup_text}；固定时间同步：{fixed_text}"
        )

    def update_weekday_state(*_args: object) -> None:
        state = "readonly" if frequency.get() == "每周固定一天" else "disabled"
        weekday_box.config(state=state)
        weekday_label.config(state="normal" if state == "readonly" else "disabled")

    def save_auto_settings() -> None:
        try:
            auto_toggl_direction = selected_auto_toggl_direction()
            automation_enabled = startup_sync.get() or app_open_sync.get() or fixed_schedule.get()
            if automation_enabled and not (calendar_auto_sync.get() or auto_toggl_direction):
                raise RuntimeError("请至少选择一种自动同步内容。")
            if calendar_auto_sync.get() and not save_calendar_selection(show_message=False):
                return
            if auto_toggl_direction and not save_toggl_config(show_message=False):
                return
            toggl_config["autoTogglToAtimelogger"] = toggl_to_atime_auto_sync.get()
            toggl_config["autoAtimeloggerToToggl"] = atime_to_toggl_auto_sync.get()
            toggl_config["autoSyncEnabled"] = bool(auto_toggl_direction)
            toggl_sync.save_config(toggl_config)
            automation.set_startup_enabled(startup_sync.get())

            if fixed_schedule.get():
                result = automation.create_or_update_task(
                    frequency.get(),
                    sync_time.get(),
                    weekday.get(),
                )
                if result.returncode != 0:
                    details = automation.result_details(result)
                    raise RuntimeError(details or "系统无法创建自动同步任务。")
            elif automation.task_exists():
                result = automation.delete_task()
                if result.returncode != 0:
                    details = automation.result_details(result)
                    raise RuntimeError(details or "系统无法删除自动同步任务。")

            settings = automation.load_settings()
            settings.update(
                {
                    "sync_when_app_opens": app_open_sync.get(),
                    "calendar_sync_enabled": calendar_auto_sync.get(),
                    "fixed_schedule_enabled": fixed_schedule.get(),
                    "frequency": frequency.get(),
                    "sync_time": sync_time.get(),
                    "weekday": weekday.get(),
                    "calendar_sync_days": max(1, int(calendar_days.get() or 3)),
                }
            )
            automation.save_settings(settings)
        except Exception as error:
            messagebox.showerror("保存失败", str(error), parent=root)
            return

        refresh_auto_status()
        messagebox.showinfo(
            "设置完成",
            "自动同步设置已保存。登录后同步和固定时间同步均不依赖 Codex。\n"
            f"固定时间方式：{automation.task_backend_label()}",
            parent=root,
        )

    def run_auto_now() -> None:
        try:
            automation.run_silent_now()
        except Exception as error:
            messagebox.showerror("启动失败", str(error), parent=root)
            return
        messagebox.showinfo("已启动", "同步已在后台运行，结果会写入日志。", parent=root)

    def open_auto_log() -> None:
        try:
            automation.open_log()
        except Exception as error:
            messagebox.showerror("无法打开日志", str(error), parent=root)

    auto_buttons = ttk.Frame(auto_frame)
    auto_buttons.grid(row=16, column=0, columnspan=2, sticky="we")
    ttk.Button(auto_buttons, text="保存自动同步设置", command=save_auto_settings).grid(
        row=0, column=0, columnspan=2, sticky="we"
    )
    ttk.Button(auto_buttons, text="立即后台同步", command=run_auto_now).grid(
        row=1, column=0, sticky="we", padx=(0, 4), pady=(8, 0)
    )
    ttk.Button(auto_buttons, text="查看日志", command=open_auto_log).grid(
        row=1, column=1, sticky="we", padx=(4, 0), pady=(8, 0)
    )

    auto_frame.columnconfigure(0, weight=1)
    auto_frame.columnconfigure(1, weight=1)
    auto_buttons.columnconfigure(0, weight=1)
    auto_buttons.columnconfigure(1, weight=1)

    frequency.trace_add("write", update_weekday_state)
    update_weekday_state()
    refresh_auto_status()

    def sync_today_when_opened() -> None:
        auto_toggl_direction = selected_auto_toggl_direction()
        if not (calendar_auto_sync.get() or auto_toggl_direction):
            status.set("打开脚本自动同步已启用，但尚未选择同步内容。")
            return
        set_controls_enabled(False)
        status.set(f"正在自动同步今天（{today.isoformat()}）...")

        def worker() -> None:
            messages = []
            if calendar_auto_sync.get():
                returncode, output = run_sync(today.isoformat())
                summary = extract_summary(output)
                _title, message = build_message(summary, output, returncode)
                messages.append(f"Google Calendar → aTimeLogger：\n{message}")
            if auto_toggl_direction and toggl_sync.configured(toggl_config):
                toggl_returncode, toggl_output, toggl_summary = toggl_sync.run_sync(
                    today.isoformat(),
                    today.isoformat(),
                    auto_toggl_direction,
                    False,
                )
                _toggl_title, toggl_message = toggl_sync.build_summary_message(
                    toggl_summary,
                    toggl_output,
                    toggl_returncode,
                )
                direction_name = toggl_sync.DIRECTION_VALUES.get(
                    auto_toggl_direction, auto_toggl_direction
                )
                messages.append(f"{direction_name}：\n{toggl_message}")
            elif auto_toggl_direction:
                messages.append("Toggl 自动同步：尚未配置 Toggl 登录信息，已跳过。")

            def finish() -> None:
                status.set("\n\n".join(messages))
                set_controls_enabled(True)

            root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    if app_open_sync.get():
        root.after(300, sync_today_when_opened)

    if "--auto-tab" in sys.argv:
        notebook.select(auto_frame)

    date_entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        messagebox.showerror("同步失败", str(error))
        sys.exit(1)
