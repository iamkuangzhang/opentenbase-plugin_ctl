from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .manifest import ManifestError, PluginManifest, load_manifest


@dataclass(slots=True)
class Catalog:
    root: Path

    def manifest_paths(self) -> list[Path]:
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
