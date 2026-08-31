from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .config import PROJECT_ROOT


MARKER = PROJECT_ROOT / "results" / ".holdout_opened"


def open_holdout(*, season: int, selection_manifest: dict[str, object], force: bool = False) -> None:
    """Record the irreversible first use of the locked final test season."""
    if MARKER.exists() and not force:
        prior = json.loads(MARKER.read_text())
        raise RuntimeError(
            f"holdout was already opened at {prior['opened_at']}; use --force only for reporting"
        )
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "season": season,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "selection_manifest": selection_manifest,
    }
    MARKER.write_text(json.dumps(payload, indent=2) + "\n")

