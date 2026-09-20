"""Locate unchanged Aldertrace primitives without installing a package."""
import os
from pathlib import Path
import sys

NEXT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(os.environ.get('ALDERTRACE_SOURCE_ROOT', NEXT_ROOT.parent)).resolve()
if not (SOURCE_ROOT / 'study-execution/adapters.py').is_file():
    raise RuntimeError('Aldertrace source root is missing its frozen adapters')
sys.path.insert(0, str(SOURCE_ROOT / 'study-execution'))
# The existing adapters add study/ and the repository root when first imported.
import adapters  # noqa: E402
if Path(adapters.ROOT).resolve() != SOURCE_ROOT:
    raise RuntimeError('Another Aldertrace source root is already imported')
