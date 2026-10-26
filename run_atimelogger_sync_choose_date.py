from __future__ import annotations

import runpy
from pathlib import Path


TARGET = Path(__file__).resolve().parent / "run_atimelogger_sync_choose_date.pyw"
runpy.run_path(str(TARGET), run_name="__main__")
