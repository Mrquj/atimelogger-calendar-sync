from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from atimelogger_automation import load_settings, save_settings
from toggl_atimelogger_settings import automatic_direction, load_config as load_toggl_config


PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "atimelogger-auto-sync.log"
MAX_LOG_SIZE = 2 * 1024 * 1024


def find_npm() -> str | None:
    command = "npm.cmd" if os.name == "nt" else "npm"
    found = shutil.which(command)
    if found:
        return found

    if os.name == "nt":
        standard_path = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd"
        if standard_path.exists():
            return str(standard_path)

    if sys.platform.startswith("linux"):
        for candidate in (Path("/usr/bin/npm"), Path("/usr/local/bin/npm")):
            if candidate.exists():
                return str(candidate)

        shell = os.environ.get("SHELL")
        if shell:
            lookup = subprocess.run(
                [shell, "-lc", "command -v npm"],
                capture_output=True,
                text=True,
                errors="replace",
            )
            found = lookup.stdout.strip()
            if lookup.returncode == 0 and found:
                return found

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


def write_log(message: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        backup = LOG_FILE.with_suffix(".previous.log")
        backup.unlink(missing_ok=True)
        LOG_FILE.replace(backup)

    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(message.rstrip() + "\n")


def scheduled_run_is_due() -> tuple[bool, dict]:
    settings = load_settings()
    frequency = settings.get("frequency", "每天")
    interval_days = {
        "每天": 1,
        "每隔 2 天": 2,
        "每隔 7 天": 7,
        "每周固定一天": 1,
    }.get(frequency, 1)

    last_run_text = settings.get("last_scheduled_run")
    if interval_days <= 1 or not last_run_text:
        return True, settings

    try:
        last_run = date.fromisoformat(last_run_text)
    except ValueError:
        return True, settings

    return (date.today() - last_run).days >= interval_days, settings


def main() -> int:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    is_scheduled = "--scheduled" in sys.argv
    settings = None
    if is_scheduled:
        is_due, settings = scheduled_run_is_due()
        if not is_due:
            write_log(f"[{timestamp}] SKIPPED: scheduled frequency is not due today")
            return 0

    settings = settings or load_settings()
    calendar_enabled = bool(settings.get("calendar_sync_enabled", True))
    toggl_config = load_toggl_config()
    toggl_direction = automatic_direction(toggl_config)
    toggl_enabled = toggl_direction is not None
    if not (calendar_enabled or toggl_enabled):
        write_log(f"[{timestamp}] SKIPPED: no automatic sync content selected")
        return 0

    npm = find_npm()
    if not npm:
        write_log(f"[{timestamp}] FAILED: npm not found")
        return 1

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    final_returncode = 0
    if calendar_enabled:
        _cal_days = max(1, int(os.environ.get("SYNC_CALENDAR_DAYS") or settings.get("calendar_sync_days") or 3))
        _cal_start = (date.today() - timedelta(days=_cal_days - 1)).isoformat()
        completed = subprocess.run(
            [npm, "run", "sync:atimelogger-calendar", "--", "--date", _cal_start, "--days", str(_cal_days)],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "NO_COLOR": "1"},
            startupinfo=startupinfo,
        )

        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        summary = extract_summary(output)
        if summary:
            result = {
                "date": summary.get("date"),
                "calendars": summary.get("calendars", []),
                "calendarEvents": summary.get("calendarEvents", 0),
                "created": summary.get("created", 0),
                "skipped": summary.get("skipped", 0),
                "failed": summary.get("failed", 0),
                "dryRun": summary.get("dryRun", False),
            }
            write_log(
                f"[{timestamp}] calendar-atimelogger exit={completed.returncode} "
                f"{json.dumps(result, ensure_ascii=False)}"
            )
        else:
            compact_output = output.strip().replace("\n", " ")[:1200]
            write_log(
                f"[{timestamp}] calendar-atimelogger exit={completed.returncode} {compact_output}"
            )
        if completed.returncode != 0:
            final_returncode = completed.returncode
    else:
        write_log(f"[{timestamp}] calendar-atimelogger SKIPPED: disabled")

    if toggl_enabled:
        toggl_completed = subprocess.run(
            [
                npm,
                "run",
                "sync:toggl-atimelogger",
                "--",
                "--direction",
                toggl_direction,
                "--write",
            ],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "NO_COLOR": "1"},
            startupinfo=startupinfo,
        )
        toggl_output = "\n".join(
            part for part in [toggl_completed.stdout, toggl_completed.stderr] if part
        )
        toggl_summary = None
        decoder = json.JSONDecoder()
        for index, char in enumerate(toggl_output):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(toggl_output[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and "createdInAtimeLogger" in value:
                toggl_summary = value

        if toggl_summary:
            compact = {
                "from": toggl_summary.get("from"),
                "to": toggl_summary.get("to"),
                "direction": toggl_summary.get("direction"),
                "createdInAtimeLogger": toggl_summary.get("createdInAtimeLogger", 0),
                "updatedInAtimeLogger": toggl_summary.get("updatedInAtimeLogger", 0),
                "movedToAtimeLoggerType": toggl_summary.get("movedToAtimeLoggerType", 0),
                "createdInToggl": toggl_summary.get("createdInToggl", 0),
                "updatedInToggl": toggl_summary.get("updatedInToggl", 0),
                "atimeEligibleForToggl": toggl_summary.get("atimeEligibleForToggl", 0),
                "atimeExcludedByType": toggl_summary.get("atimeExcludedByType", 0),
                "conflicts": toggl_summary.get("conflicts", 0),
                "failed": toggl_summary.get("failed", 0),
                "dryRun": toggl_summary.get("dryRun", False),
                "firstFailure": next(
                    (
                        detail.get("reason")
                        for detail in toggl_summary.get("details", [])
                        if detail.get("reason")
                    ),
                    None,
                ),
            }
            write_log(
                f"[{timestamp}] toggl-atimelogger exit={toggl_completed.returncode} "
                f"{json.dumps(compact, ensure_ascii=False)}"
            )
        else:
            compact_output = toggl_output.strip().replace("\n", " ")[:1200]
            write_log(
                f"[{timestamp}] toggl-atimelogger exit={toggl_completed.returncode} {compact_output}"
            )
        if toggl_completed.returncode != 0:
            final_returncode = toggl_completed.returncode
    else:
        write_log(f"[{timestamp}] toggl-atimelogger SKIPPED: disabled")

    if is_scheduled and settings is not None:
        settings["last_scheduled_run"] = date.today().isoformat()
        save_settings(settings)

    return final_returncode


if __name__ == "__main__":
    raise SystemExit(main())
