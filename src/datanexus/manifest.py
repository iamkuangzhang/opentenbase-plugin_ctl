from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(RuntimeError):
    pass


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    database: str
    targets: dict[str, bool]
    payload: dict[str, Any]
    distributed: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def source_root(self) -> Path:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        return self.project_root / self.payload["source_root"]

    @property
    def install_sql(self) -> Path:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        return self.project_root / self.payload["install_sql"]

    @property
    def verify_sql(self) -> Path:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        return self.project_root / self.payload["verify_sql"]

    @property
    def smoke_sql(self) -> Path:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        smoke_sql = self.payload.get("smoke_sql")
        if not smoke_sql:
            raise ManifestError(f"missing smoke_sql in manifest {self.path}")
        return self.project_root / smoke_sql

    @property
    def rollback_sql(self) -> Path | None:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        rollback_sql = self.payload.get("rollback_sql")
        if not rollback_sql:
            return None
        return self.project_root / rollback_sql

    @property
    def project_root(self) -> Path:
        if self.path is None:
            raise ManifestError("manifest path is not attached")
        for parent in [self.path.parent, *self.path.parents]:
            if (parent / "pyproject.toml").exists() and (parent / "src" / "datanexus").exists():
                return parent
        if self.path.parent.name == "plugins" and self.path.parent.parent.name == "catalog":
            return self.path.parent.parent.parent
        if self.path.name == "manifest.yml" and self.path.parent.parent.name == "plugins" and self.path.parent.parent.parent.name == "examples":
            return self.path.parent.parent.parent.parent
        raise ManifestError(f"cannot locate platform root for manifest {self.path}")


def load_manifest(path: Path) -> PluginManifest:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid YAML in {path}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be a mapping in {path}")

    required = ["plugin_id", "name", "version", "description", "database", "targets", "payload"]
    missing = [key for key in required if key not in raw]
    if missing:
        raise ManifestError(f"missing manifest fields in {path}: {', '.join(missing)}")

    manifest = PluginManifest(
        plugin_id=str(raw["plugin_id"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        description=str(raw["description"]),
        database=str(raw["database"]),
        targets=dict(raw["targets"]),
        payload=dict(raw["payload"]),
        distributed=dict(raw.get("distributed", {})),
        hooks=dict(raw.get("hooks", {})),
        notes=list(raw.get("notes", [])),
        path=path,
    )
    return manifest
