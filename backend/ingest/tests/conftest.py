"""Make `backend.*` importable no matter where pytest is invoked from —
the repo uses namespace packages (no backend/__init__.py), so the repo root
just needs to be on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
