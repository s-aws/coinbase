"""Runtime bootstrap for standalone diagnostic scripts."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_root() -> Path:
    """Add the repository root to ``sys.path`` and return it."""
    root = Path(__file__).resolve().parents[2]
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root
