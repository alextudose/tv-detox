"""Journal of every change, written before the change is made, so restore
can undo it even if the run stops halfway."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATUSES = ("pending", "applied", "failed", "reverted")


class Manifest:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())["entries"]

    def record(self, *, kind: str, target: str, before, after, undo: str) -> str:
        entries = self.entries()
        entry_id = f"{len(entries) + 1:03d}-{kind}"
        entries.append({"id": entry_id, "kind": kind, "target": target,
                        "before": before, "after": after, "undo": undo,
                        "status": "pending", "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        self._write(entries)
        return entry_id

    def mark(self, entry_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        entries = self.entries()
        for entry in entries:
            if entry["id"] == entry_id:
                entry["status"] = status
                self._write(entries)
                return
        raise KeyError(entry_id)

    def to_restore(self) -> list[dict]:
        """Newest first. Pending and failed entries are kept: the change may
        have reached the TV before the run stopped."""
        return [e for e in reversed(self.entries()) if e["status"] != "reverted"]

    def _write(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": entries}, indent=2))
        os.replace(tmp, self.path)
