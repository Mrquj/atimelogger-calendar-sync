from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import atimelogger_automation as automation


PROJECT_DIR = Path(__file__).resolve().parent
MUTEX_NAME = "Local\\aTimeLoggerFixedScheduleV2"


def acquire_windows_mutex() -> object | None:
    if os.name != "nt":
        return object()
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or kernel32.GetLastError() == 183:
        return None
    return handle


def weekday_matches(settings: dict, today: date) -> bool:
    if settings.get("frequency") != "每周固定一天":
        return True
    weekdays = list(automation.WEEKDAYS)
    expected = settings.get("weekday", "星期一")
    return expected in weekdays and weekdays.index(expected) == today.weekday()


def launch_scheduled_sync() -> None:
    python = automation.find_python_gui()
    if not python:
        return
    subprocess.Popen(
        [str(python), str(automation.SILENT_RUNNER), "--scheduled"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=automation.hidden_startupinfo(),
    )


def main() -> int:
    mutex = acquire_windows_mutex()
    if mutex is None:
        return 0

    last_attempt: str | None = None
    while True:
        if os.name == "nt" and not automation._windows_fallback_scheduler_exists():
            return 0

        settings = automation.load_settings()
        if settings.get("fixed_schedule_enabled", False):
            now = datetime.now()
            today_text = now.date().isoformat()
            sync_time = automation.validate_time(str(settings.get("sync_time", "06:00")))
            if (
                sync_time
                and weekday_matches(settings, now.date())
                and now.strftime("%H:%M") >= sync_time
                and last_attempt != today_text
            ):
                launch_scheduled_sync()
                last_attempt = today_text
        time.sleep(20)


if __name__ == "__main__":
    raise SystemExit(main())
