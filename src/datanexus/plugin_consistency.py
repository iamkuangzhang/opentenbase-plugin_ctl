from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import PluginManifest
from .plugin_archive import ArchiveRecord, ArchiveStore, manifest_checksum
from .plugin_governance import installed_state, registered_node_probe
from .plugin_package import lint_manifest
from .plugin_roles import manifest_roles


@dataclass(slots=True)
class ConsistencyItem:
    plugin_id: str
    check: str
    status: str
    detail: str


def consistency_check(root: Path, runtime: Any, manifest: PluginManifest) -> list[ConsistencyItem]:
    plugin_id = manifest.plugin_id
    items: list[ConsistencyItem] = []
    archive = ArchiveStore(root).get(plugin_id)

    for lint in lint_manifest(manifest):
        if lint.status != "pass":
            items.append(ConsistencyItem(plugin_id, f"package:{lint.check}", lint.status, lint.detail))

    if archive is None:
        items.append(ConsistencyItem(plugin_id, "archive:record", "warn", "no archive record found"))
    else:
        items.append(ConsistencyItem(plugin_id, "archive:record", "pass", f"status={archive.status}, version={archive.version}"))
        current_checksum = manifest_checksum(manifest)
        items.append(
            ConsistencyItem(
                plugin_id,
                "archive:checksum",
                "pass" if archive.checksum == current_checksum else "warn",
                "manifest and package hash match" if archive.checksum == current_checksum else "manifest or package files changed since archive record",
            )
        )
        items.append(
            ConsistencyItem(
                plugin_id,
                "archive:version",
                "pass" if archive.version == manifest.version else "warn",
                f"archive={archive.version}, manifest={manifest.version}",
            )
        )

    state, detail = installed_state(runtime, manifest)
    items.append(ConsistencyItem(plugin_id, "runtime:installed_state", "pass" if state == "installed" else "warn", f"{state}: {detail}"))
    if archive is not None:
        archive_installed = archive.status == "installed"
        runtime_installed = state == "installed"
        items.append(
            ConsistencyItem(
                plugin_id,
                "archive_vs_runtime",
                "pass" if archive_installed == runtime_installed else "warn",
                f"archive={archive.status}, runtime={state}",
            )
        )

    roles = manifest_roles(manifest)
    if not roles:
        items.append(ConsistencyItem(plugin_id, "roles:declared", "warn", "no role mapping declared"))
        return items

    ok, node_detail = registered_node_probe(runtime, roles)
    items.append(ConsistencyItem(plugin_id, "roles:registered_nodes", "pass" if ok else "warn", node_detail))
    items.append(ConsistencyItem(plugin_id, "roles:target_roles", "pass", ", ".join(roles)))
    return items


def consistency_items_json(items: list[ConsistencyItem]) -> list[dict[str, str]]:
    return [{"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail} for item in items]
