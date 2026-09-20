#!/usr/bin/env python3
"""Run from this folder: python run.py test | pick | serve | gate | compact | leakcheck"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logitpick.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
