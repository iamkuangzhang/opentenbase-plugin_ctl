from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from .cluster import find_cluster_config, load_cluster_config
from .manifest import PluginManifest


@dataclass(frozen=True, slots=True)
class BuildResult:
    plugin_id: str
    ok: bool
    skipped: bool
    detail: str
    pg_config: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def is_sql_only(manifest: PluginManifest) -> bool:
    return manifest.plugin_type.lower() in {"", "sql", "sql-only", "sql_only"}


def build_plugin(manifest: PluginManifest) -> BuildResult:
    if is_sql_only(manifest):
        return BuildResult(
            plugin_id=manifest.plugin_id,
            ok=True,
            skipped=True,
            detail=f"Plugin {manifest.plugin_id} is SQL-only and does not require compilation.",
        )

    if manifest.plugin_type.lower() != "c":
        return BuildResult(manifest.plugin_id, False, False, f"unsupported plugin type: {manifest.plugin_type}", returncode=2)

    missing = _missing_sources(manifest)
    if missing:
        return BuildResult(manifest.plugin_id, False, False, "missing build input: " + ", ".join(missing), returncode=2)

    make = shutil.which("make")
    if not make:
        return BuildResult(manifest.plugin_id, False, False, "make not found", returncode=127)

    pg_config = resolve_pg_config(manifest)
    if not pg_config:
        return BuildResult(manifest.plugin_id, False, False, "pg_config not found", returncode=127)

    pgxs = subprocess.run([pg_config, "--pgxs"], text=True, capture_output=True)
    if pgxs.returncode != 0 or not pgxs.stdout.strip():
        return BuildResult(
            manifest.plugin_id,
            False,
            False,
            "PGXS not available from pg_config",
            pg_config=pg_config,
            stdout=pgxs.stdout,
            stderr=pgxs.stderr,
            returncode=pgxs.returncode or 1,
        )

    workdir = manifest.project_root / str(manifest.build.get("workdir", "."))
    clean = subprocess.run([make, f"PG_CONFIG={pg_config}", "clean"], cwd=workdir, text=True, capture_output=True)
    build = subprocess.run([make, f"PG_CONFIG={pg_config}"], cwd=workdir, text=True, capture_output=True)
    stdout = clean.stdout + build.stdout
    stderr = clean.stderr + build.stderr
    if build.returncode != 0:
        return BuildResult(
            manifest.plugin_id,
            False,
            False,
            "build failed",
            pg_config=pg_config,
            stdout=stdout,
            stderr=stderr,
            returncode=build.returncode,
        )

    missing_artifacts = [path.name for path in library_artifact_paths(manifest) if not path.exists()]
    if missing_artifacts:
        return BuildResult(
            manifest.plugin_id,
            False,
            False,
            "build artifact missing: " + ", ".join(missing_artifacts),
            pg_config=pg_config,
            stdout=stdout,
            stderr=stderr,
            returncode=1,
        )

    return BuildResult(
        manifest.plugin_id,
        True,
        False,
        f"Build completed for {manifest.plugin_id}.",
        pg_config=pg_config,
        stdout=stdout,
        stderr=stderr,
        returncode=0,
    )


def library_artifact_paths(manifest: PluginManifest) -> tuple[Path, ...]:
    values = [*_as_list(manifest.library_files), *_as_list(manifest.payload.get("library_files", []))]
    paths: list[Path] = []
    for value in values:
        path = Path(str(value))
        paths.append(path if path.is_absolute() else manifest.project_root / path)
    return tuple(dict.fromkeys(paths))


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def resolve_pg_config(manifest: PluginManifest) -> str:
    configured = str(manifest.build.get("pg_config", "auto") or "auto")
    if configured != "auto":
        return configured if Path(configured).exists() or shutil.which(configured) else ""

    cluster_path = find_cluster_config()
    if cluster_path:
        try:
            cluster = load_cluster_config(cluster_path)
            for node in cluster.nodes:
                for candidate in _pg_config_candidates_from_dirs(node.lib_dir, node.extension_dir):
                    if candidate.exists():
                        return str(candidate)
        except Exception:
            pass

    found = shutil.which("pg_config")
    if found:
        return found

    for candidate in [
        Path("/data/opentenbase/install/opentenbase_bin_v2.0/bin/pg_config"),
        Path("/data/opentenbase/install/opentenbase/5.21.8.11/bin/pg_config"),
    ]:
        if candidate.exists():
            return str(candidate)
    return ""


def _pg_config_candidates_from_dirs(lib_dir: str, extension_dir: str) -> list[Path]:
    candidates: list[Path] = []
    lib_path = Path(lib_dir)
    if lib_path.name == "postgresql" and lib_path.parent.name == "lib":
        candidates.append(lib_path.parent.parent / "bin" / "pg_config")
    if lib_path.name == "lib":
        candidates.append(lib_path.parent / "bin" / "pg_config")
    ext_path = Path(extension_dir)
    if ext_path.name == "extension" and ext_path.parent.name == "postgresql" and ext_path.parent.parent.name == "share":
        candidates.append(ext_path.parent.parent.parent / "bin" / "pg_config")
    return candidates


def _missing_sources(manifest: PluginManifest) -> list[str]:
    missing: list[str] = []
    for value in [*manifest.source_files, "Makefile"]:
        path = Path(str(value))
        resolved = path if path.is_absolute() else manifest.project_root / path
        if not resolved.exists():
            missing.append(str(value))
    return list(dict.fromkeys(missing))
