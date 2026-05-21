from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StateRecord:
    # timestamp is the local persistence time, not the action execution start
    # time. Action started_at/finished_at are stored in metadata.
    timestamp: str
    plugin_id: str
    action: str
    ok: bool
    detail: str
    metadata: dict[str, Any]


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / ".datanexus" / "state.json"

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def append(self, plugin_id: str, action: str, ok: bool, detail: str, metadata: dict[str, Any] | None = None) -> StateRecord:
        record = StateRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            plugin_id=plugin_id,
            action=action,
            ok=ok,
            detail=detail,
            metadata=metadata or {},
        )
        records = self._read()
        records.append(asdict(record))
        self._write(records)
        return record

    def latest(self, plugin_id: str | None = None) -> StateRecord | None:
        records = self._read()
        if plugin_id is not None:
            records = [record for record in records if record["plugin_id"] == plugin_id]
        if not records:
            return None
        raw = records[-1]
        return StateRecord(**raw)

    def all(self) -> list[StateRecord]:
        return [StateRecord(**record) for record in self._read()]
