from __future__ import annotations

import json
import uuid
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / ".atimelogger-calendars.json"
ENV_FILE = PROJECT_DIR / ".dev.vars"
FALLBACK_ENV_FILE = PROJECT_DIR / ".env"
DEFAULT_CALENDAR_ID = "default"


def default_calendar_available() -> bool:
    for env_file in (ENV_FILE, FALLBACK_ENV_FILE):
        if not env_file.exists():
            continue
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("GOOGLE_CALENDAR_ICS_URL=") and line.split("=", 1)[1].strip():
                return True
            if line.startswith("GOOGLE_CALENDAR_ICS_FILE=") and line.split("=", 1)[1].strip():
                return True
    return False


def load_config() -> dict:
    config = {"calendars": [], "selectedCalendarIds": None}
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}

        if isinstance(saved, dict):
            calendars = saved.get("calendars")
            selected = saved.get("selectedCalendarIds")
            if isinstance(calendars, list):
                config["calendars"] = [
                    calendar
                    for calendar in calendars
                    if isinstance(calendar, dict)
                    and calendar.get("id")
                    and calendar.get("name")
                    and calendar.get("url")
                    and calendar.get("id") != DEFAULT_CALENDAR_ID
                ]
            if isinstance(selected, list):
                config["selectedCalendarIds"] = [str(value) for value in selected]

    calendars = []
    if default_calendar_available():
        calendars.append(
            {
                "id": DEFAULT_CALENDAR_ID,
                "name": "课程表",
                "url": None,
                "default": True,
            }
        )
    calendars.extend(config["calendars"])

    selected = config["selectedCalendarIds"]
    if selected is None:
        selected = [calendar["id"] for calendar in calendars]

    return {
        "calendars": calendars,
        "selectedCalendarIds": selected,
    }


def save_config(calendars: list[dict], selected_calendar_ids: list[str]) -> None:
    additional = [
        {
            "id": str(calendar["id"]),
            "name": str(calendar["name"]).strip(),
            "url": str(calendar["url"]).strip(),
        }
        for calendar in calendars
        if calendar.get("id") != DEFAULT_CALENDAR_ID
        and calendar.get("name")
        and calendar.get("url")
    ]
    CONFIG_FILE.write_text(
        json.dumps(
            {
                "calendars": additional,
                "selectedCalendarIds": selected_calendar_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def add_calendar(name: str, url: str) -> dict:
    return {
        "id": uuid.uuid4().hex,
        "name": name.strip(),
        "url": url.strip(),
        "default": False,
    }
