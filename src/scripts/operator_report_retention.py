"""Shared helpers for one-off operator report retention."""

from __future__ import annotations

from pathlib import Path
from time import time
from typing import Iterable


def list_report_targets(paths: Iterable[Path], *, retention_days: int) -> list[dict[str, object]]:
    """List known report files and whether they are past the retention window."""
    targets: list[dict[str, object]] = []
    now = time()
    for path in paths:
        if not path.exists():
            continue
        age_days = max(0.0, (now - path.stat().st_mtime) / 86400)
        targets.append(
            {
                "path": str(path),
                "age_days": round(age_days, 1),
                "retention_days": retention_days,
                "prune_candidate": age_days >= retention_days,
            }
        )
    return targets
