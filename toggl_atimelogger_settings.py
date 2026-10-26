from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / ".toggl-atimelogger-config.json"
STATE_FILE = PROJECT_DIR / ".toggl-atimelogger-state.json"
NPM_COMMAND = "npm.cmd" if os.name == "nt" else "npm"

DIRECTION_LABELS = {
    "双向同步": "both",
    "Toggl → aTimeLogger": "toggl-to-atimelogger",
    "aTimeLogger → Toggl": "atimelogger-to-toggl",
}
DIRECTION_VALUES = {value: label for label, value in DIRECTION_LABELS.items()}
SOURCE_FILTER_LABELS = {
    "全部已完成记录": "all",
    "排除日历来源记录": "exclude-calendar",
    "仅手动/非集成记录": "manual-only",
}
SOURCE_FILTER_VALUES = {value: label for label, value in SOURCE_FILTER_LABELS.items()}
DUPLICATE_POLICY_LABELS = {
    "不检查重复": "none",
    "同标题且时间完全一致": "exact",
    "同标题且时间有重叠": "title-overlap",
}
DUPLICATE_POLICY_VALUES = {value: label for label, value in DUPLICATE_POLICY_LABELS.items()}


def load_config() -> dict:
    defaults = {
        "togglApiToken": "",
        "togglUsername": "",
        "togglPassword": "",
        "togglWorkspaceId": "",
        "direction": "both",
        "atimeloggerActivityTypeName": "工作",
        "atimeloggerToTogglTypeNames": "",
        "includeGoogleCalendar": False,
        "togglSourceFilter": "exclude-calendar",
        "calendarSourceKeywords": "calendar,google calendar,outlook,ical",
        "duplicatePolicy": "exact",
        "autoSyncEnabled": False,
        "autoTogglToAtimelogger": False,
        "autoAtimeloggerToToggl": False,
    }
    if not CONFIG_FILE.exists():
        return defaults

    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if isinstance(saved, dict):
        defaults.update(saved)
        if saved.get("autoSyncEnabled") and (
            "autoTogglToAtimelogger" not in saved
            and "autoAtimeloggerToToggl" not in saved
        ):
            direction = saved.get("direction", "both")
            defaults["autoTogglToAtimelogger"] = direction in ("both", "toggl-to-atimelogger")
            defaults["autoAtimeloggerToToggl"] = direction in ("both", "atimelogger-to-toggl")
    return defaults


def automatic_direction(config: dict | None = None) -> str | None:
    config = config or load_config()
    to_atime = bool(config.get("autoTogglToAtimelogger", False))
    to_toggl = bool(config.get("autoAtimeloggerToToggl", False))
    if to_atime and to_toggl:
        return "both"
    if to_atime:
        return "toggl-to-atimelogger"
    if to_toggl:
        return "atimelogger-to-toggl"
    return None


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def configured(config: dict | None = None) -> bool:
    config = config or load_config()
    return bool(
        config.get("togglApiToken")
        or (config.get("togglUsername") and config.get("togglPassword"))
    )


def hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def run_sync(
    from_date: str,
    to_date: str,
    direction: str,
    dry_run: bool,
) -> tuple[int, str, dict | None]:
    npm = shutil.which(NPM_COMMAND)
    if not npm:
        return 1, "没有找到 npm。请先安装 Node.js 和 npm。", None

    command = [
        npm,
        "run",
        "sync:toggl-atimelogger",
        "--",
        "--from",
        from_date,
        "--to",
        to_date,
        "--direction",
        direction,
    ]
    if dry_run:
        command.append("--dry-run")
    else:
        command.append("--write")

    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "NO_COLOR": "1"},
        startupinfo=hidden_startupinfo(),
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    summary = extract_summary(output)
    returncode = completed.returncode
    if not dry_run and summary and summary.get("dryRun"):
        returncode = 1
        output = (
            f"{output}\n真实同步请求被配置为测试模式，未写入任何数据。"
            "请关闭 TOGGL_ATIMELOGGER_DRY_RUN 或使用图形界面的真实同步按钮。"
        )
    return returncode, output, summary


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
        if isinstance(value, dict) and "createdInAtimeLogger" in value:
            last_summary = value
    return last_summary


def build_summary_message(summary: dict | None, output: str, returncode: int) -> tuple[str, str]:
    if not summary:
        body = output.strip()[-1800:] or "没有收到同步结果。"
        if "HTTP 402" in body and "hourly limit" in body:
            return (
                "Toggl API 调用额度已用完",
                "Toggl 暂时拒绝同步请求。请等待返回信息中的倒计时结束后重试。\n\n"
                + body,
            )
        title = "双向同步失败" if returncode else "双向同步完成"
        return title, body

    title = "双向同步测试完成（未写入）" if summary.get("dryRun") else "双向同步完成"
    if summary.get("failed", 0) or summary.get("conflicts", 0):
        title = "双向同步需要处理"

    lines = [
        f"日期范围：{summary.get('from')} 至 {summary.get('to')}",
        f"方向：{summary.get('direction')}",
        f"Toggl 记录：{summary.get('togglEntries', 0)} 条",
        f"来源过滤掉：{summary.get('togglFilteredOut', 0)} 条",
        f"aTimeLogger 区间：{summary.get('atimeIntervals', 0)} 条",
        f"可导出到 Toggl：{summary.get('atimeEligibleForToggl', 0)} 条",
        f"已建立映射：{summary.get('atimeAlreadyMapped', 0)} 条",
        f"排除 Google Calendar：{summary.get('atimeExcludedGoogleCalendar', 0)} 条",
        f"被类型筛选排除：{summary.get('atimeExcludedByType', 0)} 条",
        f"在 aTimeLogger 新建：{summary.get('createdInAtimeLogger', 0)} 条",
        f"在 aTimeLogger 更新：{summary.get('updatedInAtimeLogger', 0)} 条",
        f"迁移到目标活动类型：{summary.get('movedToAtimeLoggerType', 0)} 条",
        f"在 Toggl 新建：{summary.get('createdInToggl', 0)} 条",
        f"在 Toggl 更新：{summary.get('updatedInToggl', 0)} 条",
        f"跳过：{summary.get('skipped', 0)} 条",
        f"因重复跳过：{summary.get('duplicateSkipped', 0)} 条",
        f"冲突：{summary.get('conflicts', 0)} 条",
        f"失败：{summary.get('failed', 0)} 条",
        f"测试模式：{'是' if summary.get('dryRun') else '否'}",
    ]
    failure_details = [
        detail for detail in summary.get("details", [])
        if detail.get("reason") or detail.get("action") == "conflict"
    ]
    if failure_details:
        lines.append("")
        lines.append("失败/冲突详情：")
        for detail in failure_details[:10]:
            reason = detail.get("reason", "两边记录均发生变化")
            identity = (
                detail.get("togglId")
                or detail.get("atimeIntervalId")
                or "未知记录"
            )
            lines.append(f"- {detail.get('action', 'failed')} [{identity}]：{reason}")
        if len(failure_details) > 10:
            lines.append(f"- 其余 {len(failure_details) - 10} 条请查看输出或日志。")
    return title, "\n".join(lines)
