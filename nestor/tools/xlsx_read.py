"""Совместимость: читатель .xlsx перенесён в nestor_app/xlsx.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nestor_app.xlsx import read_font_colors, read_sheet, sheet_names  # noqa: E402,F401
