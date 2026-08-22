"""Path shim so `backend.render.*` resolves no matter where pytest is
invoked from (mirrors backend/agent/tests/conftest.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
