from __future__ import annotations

import json
import locale
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SILENT_RUNNER = PROJECT_DIR / "run_atimelogger_sync_silent.pyw"
FALLBACK_SCHEDULER = PROJECT_DIR / "run_atimelogger_scheduler.pyw"
LOG_FILE = PROJECT_DIR / "logs" / "atimelogger-auto-sync.log"
SETTINGS_FILE = PROJECT_DIR / ".atimelogger-sync-settings.json"
TASK_NAME = "aTimeLogger Calendar Auto Sync V2"
WINDOWS_STARTUP_FILE_NAME = "aTimeLogger Calendar Auto Sync V2.cmd"
WINDOWS_SCHEDULER_STARTUP_FILE_NAME = "aTimeLogger Fixed Schedule V2.pyw"
WINDOWS_SCHEDULER_LEGACY_STARTUP_FILE_NAMES = (
    "aTimeLogger Fixed Schedule V2.cmd",
    "aTimeLogger Fixed Schedule V2.lnk",
)
WINDOWS_SCHEDULER_RUN_VALUE_NAME = "aTimeLogger Fixed Schedule V2"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LINUX_UNIT_NAME = "atimelogger-calendar-auto-sync-v2"

FREQUENCIES = {
    "每天": ("DAILY", "1"),
    "每隔 2 天": ("DAILY", "2"),
    "每隔 7 天": ("DAILY", "7"),
    "每周固定一天": ("WEEKLY", "1"),
}

WEEKDAYS = {
    "星期一": "MON",
    "星期二": "TUE",
    "星期三": "WED",
    "星期四": "THU",
    "星期五": "FRI",
    "星期六": "SAT",
    "星期日": "SUN",
}


def platform_label() -> str:
    if os.name == "nt":
        return "Windows"
    if sys.platform.startswith("linux"):
        return "Linux"
    return sys.platform


def hidden_startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def run_command(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
            startupinfo=hidden_startupinfo(),
        )
    except FileNotFoundError as error:
        return subprocess.CompletedProcess(arguments, 127, "", str(error))


def result_details(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip()


def systemd_quote(value: str | Path) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def find_python_gui() -> Path | None:
    current = Path(sys.executable)
    if os.name == "nt":
        pythonw = current.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw

    return current if current.exists() else None


def validate_time(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def load_settings() -> dict:
    defaults = {
        "sync_when_app_opens": False,
        "calendar_sync_enabled": True,
        "fixed_schedule_enabled": False,
        "frequency": "每天",
        "sync_time": "06:00",
        "weekday": "星期一",
    }
    if not SETTINGS_FILE.exists():
        return defaults

    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if isinstance(saved, dict):
        defaults.update(saved)
    return defaults


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _windows_startup_file() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("没有找到 Windows APPDATA 目录。")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / WINDOWS_STARTUP_FILE_NAME
    )


def _windows_scheduler_startup_file() -> Path:
    return _windows_startup_file().with_name(WINDOWS_SCHEDULER_STARTUP_FILE_NAME)


def _windows_scheduler_legacy_startup_files() -> list[Path]:
    return [
        _windows_startup_file().with_name(file_name)
        for file_name in WINDOWS_SCHEDULER_LEGACY_STARTUP_FILE_NAMES
    ]


def _windows_scheduler_run_command() -> str | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            value, _value_type = winreg.QueryValueEx(
                key, WINDOWS_SCHEDULER_RUN_VALUE_NAME
            )
    except OSError:
        return None
    return str(value)


def _windows_fallback_scheduler_exists() -> bool:
    return (
        bool(_windows_scheduler_run_command())
        or _windows_scheduler_startup_file().exists()
        or any(file_path.exists() for file_path in _windows_scheduler_legacy_startup_files())
    )


def _remove_windows_fallback_scheduler() -> None:
    _windows_scheduler_startup_file().unlink(missing_ok=True)
    for file_path in _windows_scheduler_legacy_startup_files():
        file_path.unlink(missing_ok=True)
    if os.name != "nt":
        return
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            WINDOWS_RUN_KEY,
            access=winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, WINDOWS_SCHEDULER_RUN_VALUE_NAME)
    except OSError:
        pass


def _linux_autostart_file() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / f"{LINUX_UNIT_NAME}.desktop"


def startup_enabled() -> bool:
    if os.name == "nt":
        return _windows_startup_file().exists()
    if sys.platform.startswith("linux"):
        return _linux_autostart_file().exists()
    return False


def set_startup_enabled(enabled: bool) -> None:
    python = find_python_gui()
    if not python:
        raise RuntimeError("没有找到 Python 运行程序。")
    if not SILENT_RUNNER.exists():
        raise RuntimeError(f"没有找到：{SILENT_RUNNER.name}")

    if os.name == "nt":
        file_path = _windows_startup_file()
        if not enabled:
            file_path.unlink(missing_ok=True)
            return

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            f'@echo off\r\n"{python}" "{SILENT_RUNNER}"\r\n',
            encoding="utf-8",
        )
        return

    if sys.platform.startswith("linux"):
        file_path = _linux_autostart_file()
        if not enabled:
            file_path.unlink(missing_ok=True)
            return

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=aTimeLogger Calendar Auto Sync\n"
            f"Exec={systemd_quote(python)} {systemd_quote(SILENT_RUNNER)}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
        return

    raise RuntimeError(f"暂不支持在 {platform_label()} 设置登录后自动同步。")


def _linux_systemd_paths() -> tuple[Path, Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    unit_dir = config_home / "systemd" / "user"
    return (
        unit_dir / f"{LINUX_UNIT_NAME}.service",
        unit_dir / f"{LINUX_UNIT_NAME}.timer",
    )


def _linux_systemctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return run_command(["systemctl", "--user", *arguments])


def task_exists() -> bool:
    if os.name == "nt":
        return (
            run_command(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
            or _windows_fallback_scheduler_exists()
        )
    if sys.platform.startswith("linux"):
        return _linux_systemctl(["is-enabled", "--quiet", f"{LINUX_UNIT_NAME}.timer"]).returncode == 0
    return False


def create_or_update_task(frequency: str, sync_time: str, weekday: str) -> subprocess.CompletedProcess[str]:
    selected_time = validate_time(sync_time)
    if not selected_time:
        raise ValueError("请输入类似 06:00 或 21:30 的时间。")
    if frequency not in FREQUENCIES:
        raise ValueError("请选择有效的运行频率。")
    if weekday not in WEEKDAYS:
        raise ValueError("请选择有效的每周运行日。")

    python = find_python_gui()
    if not python:
        raise RuntimeError("没有找到 Python 运行程序。")
    if not SILENT_RUNNER.exists():
        raise RuntimeError(f"没有找到：{SILENT_RUNNER.name}")

    schedule, modifier = FREQUENCIES[frequency]
    if os.name == "nt":
        action = f'"{python}" "{SILENT_RUNNER}" --scheduled'
        arguments = [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            action,
            "/SC",
            schedule,
            "/MO",
            modifier,
            "/ST",
            selected_time,
            "/F",
        ]
        if schedule == "WEEKLY":
            arguments.extend(["/D", WEEKDAYS[weekday]])
        result = run_command(arguments)
        if result.returncode == 0:
            _remove_windows_fallback_scheduler()
            return result
        details = result_details(result).lower()
        if "access is denied" not in details and "拒绝访问" not in details:
            return result
        return _install_windows_fallback_scheduler(python)

    if sys.platform.startswith("linux"):
        service_file, timer_file = _linux_systemd_paths()
        service_file.parent.mkdir(parents=True, exist_ok=True)

        service_file.write_text(
            "[Unit]\n"
            "Description=Sync Google Calendar to aTimeLogger\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"WorkingDirectory={PROJECT_DIR}\n"
            f"ExecStart={systemd_quote(python)} {systemd_quote(SILENT_RUNNER)} --scheduled\n",
            encoding="utf-8",
        )

        hour, minute = selected_time.split(":")
        if schedule == "WEEKLY":
            calendar_value = f"{WEEKDAYS[weekday].title()} *-*-* {hour}:{minute}:00"
        else:
            calendar_value = f"*-*-* {hour}:{minute}:00"

        timer_file.write_text(
            "[Unit]\n"
            "Description=Schedule Google Calendar to aTimeLogger sync\n\n"
            "[Timer]\n"
            f"OnCalendar={calendar_value}\n"
            "Persistent=true\n"
            f"Unit={LINUX_UNIT_NAME}.service\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n",
            encoding="utf-8",
        )

        reload_result = _linux_systemctl(["daemon-reload"])
        if reload_result.returncode != 0:
            return reload_result
        return _linux_systemctl(["enable", "--now", f"{LINUX_UNIT_NAME}.timer"])

    raise RuntimeError(f"暂不支持在 {platform_label()} 设置固定时间自动同步。")


def delete_task() -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        fallback_existed = _windows_fallback_scheduler_exists()
        _remove_windows_fallback_scheduler()
        result = run_command(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        if result.returncode == 0 or fallback_existed:
            return subprocess.CompletedProcess(
                result.args,
                0,
                "固定时间自动同步已关闭。",
                "",
            )
        return result
    if sys.platform.startswith("linux"):
        result = _linux_systemctl(["disable", "--now", f"{LINUX_UNIT_NAME}.timer"])
        service_file, timer_file = _linux_systemd_paths()
        service_file.unlink(missing_ok=True)
        timer_file.unlink(missing_ok=True)
        _linux_systemctl(["daemon-reload"])
        return result
    raise RuntimeError(f"暂不支持在 {platform_label()} 删除自动同步任务。")


def run_task_now() -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        return run_command(["schtasks", "/Run", "/TN", TASK_NAME])
    if sys.platform.startswith("linux"):
        return _linux_systemctl(["start", "--no-block", f"{LINUX_UNIT_NAME}.service"])
    raise RuntimeError(f"暂不支持在 {platform_label()} 启动自动同步任务。")


def _install_windows_fallback_scheduler(
    python: Path,
) -> subprocess.CompletedProcess[str]:
    if not FALLBACK_SCHEDULER.exists():
        return subprocess.CompletedProcess(
            [],
            1,
            "",
            f"没有找到：{FALLBACK_SCHEDULER.name}",
        )
    try:
        file_path = _windows_scheduler_startup_file()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "import runpy\n"
            "import sys\n"
            f"sys.path.insert(0, {str(PROJECT_DIR)!r})\n"
            f"runpy.run_path({str(FALLBACK_SCHEDULER)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        for legacy_file in _windows_scheduler_legacy_startup_files():
            legacy_file.unlink(missing_ok=True)
        subprocess.Popen(
            [str(python), str(FALLBACK_SCHEDULER)],
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=hidden_startupinfo(),
        )
    except OSError as error:
        return subprocess.CompletedProcess([], 1, "", str(error))
    return subprocess.CompletedProcess(
        [],
        0,
        "Windows 计划任务权限不足，已改用当前用户本地定时器。",
        "",
    )


def task_backend_label() -> str:
    if os.name == "nt":
        if run_command(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0:
            return "Windows 计划任务"
        if _windows_fallback_scheduler_exists():
            return "当前用户本地定时器"
        return "未启用"
    return "systemd 用户定时器" if task_exists() else "未启用"


def run_silent_now() -> None:
    python = find_python_gui()
    if not python:
        raise RuntimeError("没有找到 Python 运行程序。")
    if not SILENT_RUNNER.exists():
        raise RuntimeError(f"没有找到：{SILENT_RUNNER.name}")

    subprocess.Popen(
        [str(python), str(SILENT_RUNNER)],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=hidden_startupinfo(),
        start_new_session=os.name != "nt",
    )


def open_log() -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("尚无自动同步日志。\n", encoding="utf-8")

    if os.name == "nt":
        os.startfile(LOG_FILE)
    elif sys.platform.startswith("linux"):
        run_command(["xdg-open", str(LOG_FILE)])
    else:
        raise RuntimeError(f"暂不支持在 {platform_label()} 打开日志。")
