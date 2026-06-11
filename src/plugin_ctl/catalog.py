from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .manifest import ManifestError, PluginManifest, load_manifest


def user_catalog_path() -> Path:
    override = os.environ.get("PLUGIN_CTL_CATALOG_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".plugin_ctl" / "catalog.json"


def _read_user_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = path or user_catalog_path()
    if not catalog_path.exists():
        return {"plugins": []}
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid user catalog JSON: {catalog_path}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"user catalog root must be an object: {catalog_path}")
    plugins = raw.get("plugins", [])
    if not isinstance(plugins, list):
        raise ManifestError(f"user catalog plugins must be a list: {catalog_path}")
    return {"plugins": plugins}


def _write_user_catalog(data: dict[str, Any], path: Path | None = None) -> Path:
    catalog_path = path or user_catalog_path()
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return catalog_path


def user_manifest_paths(path: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    for entry in _read_user_catalog(path).get("plugins", []):
        if not isinstance(entry, dict):
            continue
        manifest = entry.get("manifest")
        if not manifest:
            continue
        manifest_path = Path(str(manifest)).expanduser()
        if manifest_path.exists():
            paths.append(manifest_path.resolve())
    return sorted(dict.fromkeys(paths))


def find_manifest_in_plugin_dir(plugin_path: Path) -> Path:
    candidate = plugin_path.expanduser().resolve()
    if candidate.is_file():
        return candidate
    if not candidate.exists():
        raise ManifestError(f"plugin path not found: {plugin_path}")
    if not candidate.is_dir():
        raise ManifestError(f"plugin path is not a directory or manifest file: {plugin_path}")

    for path in [candidate / "manifest.yml", candidate / "plugin.yml"]:
        if path.exists():
            return path

    yml_files = sorted([*candidate.glob("*.yml"), *candidate.glob("*.yaml")])
    if len(yml_files) == 1:
        return yml_files[0]
    if not yml_files:
        raise ManifestError(f"no manifest.yml/plugin.yml/*.yml found in {candidate}")
    raise ManifestError(f"multiple manifest candidates found in {candidate}; use a manifest file path")


@dataclass(slots=True)
class Catalog:
    root: Path

    def builtin_manifest_paths(self) -> list[Path]:
        paths: list[Path] = []
        for manifest_path in [
            self.root / "catalog" / "plugins",
            self.root / "examples" / "plugins",
        ]:
            if not manifest_path.exists():
                continue
            paths.extend(sorted(manifest_path.glob("*.yml")))
            paths.extend(sorted(manifest_path.glob("*/manifest.yml")))
        return sorted(dict.fromkeys(paths))

    def manifest_paths(self) -> list[Path]:
        return sorted(dict.fromkeys([*self.builtin_manifest_paths(), *user_manifest_paths()]))

    def load_all(self) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        for path in self.manifest_paths():
            manifests.append(load_manifest(path))
        return manifests

    def load_one(self, plugin_id: str) -> PluginManifest:
        for manifest in self.load_all():
            if manifest.plugin_id == plugin_id:
                return manifest
        raise ManifestError(f"plugin not found: {plugin_id}")

    def add_user_plugin(self, plugin_path: Path) -> tuple[PluginManifest, Path]:
        manifest_path = find_manifest_in_plugin_dir(plugin_path)
        manifest = load_manifest(manifest_path)
        builtin_ids = {load_manifest(path).plugin_id for path in self.builtin_manifest_paths()}
        if manifest.plugin_id in builtin_ids:
            raise ManifestError(f"plugin_id already exists in built-in catalog: {manifest.plugin_id}")

        data = _read_user_catalog()
        plugins = [entry for entry in data["plugins"] if isinstance(entry, dict) and entry.get("plugin_id") != manifest.plugin_id]
        plugins.append(
            {
                "plugin_id": manifest.plugin_id,
                "manifest": str(manifest_path.resolve()),
                "root": str(manifest.project_root.resolve()),
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        data["plugins"] = sorted(plugins, key=lambda entry: str(entry.get("plugin_id", "")))
        return manifest, _write_user_catalog(data)

    def remove_user_plugin(self, plugin_id: str) -> Path:
        data = _read_user_catalog()
        plugins = [entry for entry in data["plugins"] if isinstance(entry, dict)]
        kept = [entry for entry in plugins if entry.get("plugin_id") != plugin_id]
        if len(kept) == len(plugins):
            raise ManifestError(f"user plugin not registered: {plugin_id}")
        data["plugins"] = kept
        return _write_user_catalog(data)
