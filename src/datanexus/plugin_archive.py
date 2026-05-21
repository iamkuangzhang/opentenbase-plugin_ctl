from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .manifest import PluginManifest
from .plugin_diagnose import PluginDiagnosis
from .plugin_roles import manifest_roles
from .state_store import StateRecord, StateStore


@dataclass(slots=True)
class ArchiveRecord:
    plugin_id: str
    version: str
    manifest_path: str
    installed_at: str
    status: str
    checksum: str
    target_roles: list[str]
    latest_actions: dict[str, dict[str, Any]]
    runtime_metadata: dict[str, Any]
    updated_at: str


class ArchiveStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / ".datanexus" / "archive.json"

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def all(self) -> list[ArchiveRecord]:
        return [ArchiveRecord(**record) for record in self._read()]

    def get(self, plugin_id: str) -> ArchiveRecord | None:
        for record in reversed(self.all()):
            if record.plugin_id == plugin_id:
                return record
        return None

    def upsert(self, record: ArchiveRecord) -> ArchiveRecord:
        records = [raw for raw in self._read() if raw.get("plugin_id") != record.plugin_id]
        records.append(asdict(record))
        self._write(records)
        return record


def manifest_checksum(manifest: PluginManifest) -> str:
    digest = hashlib.sha256()
    paths = [manifest.path, manifest.install_sql, manifest.verify_sql, manifest.smoke_sql]
    if manifest.rollback_sql:
        paths.append(manifest.rollback_sql)
    for path in sorted([item for item in paths if item is not None], key=lambda item: str(item)):
        digest.update(str(path.relative_to(manifest.project_root)).encode("utf-8"))
        digest.update(b"\0")
        if path.exists():
            digest.update(path.read_bytes())
        else:
            digest.update(f"missing:{path}".encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _record_json(record: StateRecord) -> dict[str, Any]:
    return {
        "timestamp": record.timestamp,
        "ok": record.ok,
        "detail": record.detail,
        "version": record.metadata.get("version", ""),
        "stage": record.metadata.get("stage", ""),
        "returncode": record.metadata.get("returncode", ""),
        "duration_ms": record.metadata.get("duration_ms", ""),
    }


def latest_actions(root: Path, plugin_id: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, StateRecord] = {}
    for record in StateStore(root).all():
        if record.plugin_id == plugin_id:
            latest[record.action] = record
    return {action: _record_json(record) for action, record in sorted(latest.items())}


def runtime_metadata_from_actions(actions: dict[str, dict[str, Any]], records: list[StateRecord]) -> dict[str, Any]:
    for record in reversed(records):
        metadata = record.metadata
        if metadata.get("cluster") or metadata.get("container"):
            return {
                "cluster": metadata.get("cluster", ""),
                "container": metadata.get("container", ""),
                "host": metadata.get("host", ""),
                "port": metadata.get("port", ""),
                "database": metadata.get("database", ""),
                "user": metadata.get("user", ""),
            }
    return {}


def build_archive_record(root: Path, manifest: PluginManifest, diagnosis: PluginDiagnosis | None = None) -> ArchiveRecord:
    now = datetime.now(timezone.utc).isoformat()
    actions = latest_actions(root, manifest.plugin_id)
    records = [record for record in StateStore(root).all() if record.plugin_id == manifest.plugin_id]
    installed_at = ""
    deploy = actions.get("deploy")
    if deploy and deploy.get("ok"):
        installed_at = str(deploy.get("timestamp", ""))

    status = diagnosis.installed_state if diagnosis else "unknown"
    if status == "not_installed" and actions.get("rollback", {}).get("ok"):
        status = "removed"

    return ArchiveRecord(
        plugin_id=manifest.plugin_id,
        version=manifest.version,
        manifest_path=str(manifest.path or ""),
        installed_at=installed_at,
        status=status,
        checksum=manifest_checksum(manifest),
        target_roles=manifest_roles(manifest),
        latest_actions=actions,
        runtime_metadata=runtime_metadata_from_actions(actions, records),
        updated_at=now,
    )


def archive_record_json(record: ArchiveRecord) -> dict[str, Any]:
    return asdict(record)


def archive_list_json(records: list[ArchiveRecord]) -> list[dict[str, Any]]:
    return [archive_record_json(record) for record in records]
