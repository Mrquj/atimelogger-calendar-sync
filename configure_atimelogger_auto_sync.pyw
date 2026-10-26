from __future__ import annotations

import runpy
import sys
from pathlib import Path


TARGET = Path(__file__).resolve().parent / "run_atimelogger_sync_choose_date.pyw"

if "--auto-tab" not in sys.argv:
    sys.argv.append("--auto-tab")

runpy.run_path(str(TARGET), run_name="__main__")
