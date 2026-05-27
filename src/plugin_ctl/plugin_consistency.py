from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Any

from .manifest import PluginManifest
from .plugin_archive import ArchiveStore, manifest_checksum, manifest_package_state
from .plugin_governance import installed_state, registered_node_probe
from .plugin_package import lint_manifest
from .plugin_roles import manifest_roles


@dataclass(slots=True)
class ConsistencyItem:
    plugin_id: str
    check: str
    status: str
    detail: str


def _deploy_metadata(archive: Any) -> dict[str, Any]:
    deploy = archive.latest_actions.get("deploy", {}) if archive else {}
    metadata = deploy.get("metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _remote_payload_path(manifest: PluginManifest, archive: Any) -> str:
    metadata = _deploy_metadata(archive)
    remote_root = str(metadata.get("remote_root") or "")
    if not remote_root:
        return ""
    return f"{remote_root}/{manifest.source_root.name}"


def _check_remote_path(runtime: Any, path: str) -> tuple[bool, str]:
    result = runtime.exec("bash", "-lc", f"test -e {quote(path)}")
    if result.returncode == 0:
        return True, f"remote path exists: {path}"
    return False, result.stderr.strip() or f"remote path not found: {path}"


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
        package_state = archive.package_state or manifest_package_state(root, manifest)
        package_complete = bool(package_state.get("payload_complete"))
        manifest_kind = str(package_state.get("manifest_kind", "unknown"))
        missing = package_state.get("missing", [])
        detail = f"{manifest_kind}; payload_complete={package_complete}"
        if missing:
            detail += "; missing=" + ", ".join(str(item) for item in missing)
        items.append(ConsistencyItem(plugin_id, "archive:package_state", "pass" if package_complete else "warn", detail))
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
    if archive is not None:
        remote_payload = _remote_payload_path(manifest, archive)
        for role in roles:
            check_name = f"role_remote_payload:{role}"
            if not remote_payload:
                items.append(ConsistencyItem(plugin_id, check_name, "warn", "no archived deploy remote payload path; cannot verify remote file presence"))
                continue
            exists, detail = _check_remote_path(runtime, remote_payload)
            items.append(ConsistencyItem(plugin_id, check_name, "pass" if exists else "warn", detail))
    return items


def consistency_items_json(items: list[ConsistencyItem]) -> list[dict[str, str]]:
    return [{"plugin_id": item.plugin_id, "check": item.check, "status": item.status, "detail": item.detail} for item in items]
