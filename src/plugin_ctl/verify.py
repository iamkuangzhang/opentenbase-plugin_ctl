from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .action_result import ActionResult, finish_action, start_action
from .manifest import ManifestError, PluginManifest
from .runtime.opentenbase import OpenTenBaseRuntime


def run_smoke_verify(runtime: OpenTenBaseRuntime, manifest: PluginManifest, smoke_sql: Path) -> ActionResult:
    timer = start_action()
    table_suffix = uuid4().hex[:8]
    table_name = f"pluginctl_verify_{table_suffix}"
    script = smoke_sql.read_text(encoding="utf-8").replace("__DNX_TABLE__", table_name)
    result = runtime.run_sql(script)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    expected_stdout = manifest.payload.get("verify_expect_stdout")
    ok = result.returncode == 0
    if expected_stdout is not None:
        ok = ok and stdout == str(expected_stdout)
    return finish_action(
        timer,
        action="verify",
        plugin_id=manifest.plugin_id,
        ok=ok,
        detail="smoke verify passed" if ok else stderr or stdout or "smoke verify failed",
        returncode=result.returncode if result.returncode != 0 else (0 if ok else 1),
        stdout=stdout,
        stderr=stderr,
        metadata={"stage": "smoke", "smoke_sql": str(smoke_sql), "verify_table": table_name, "verify_expect_stdout": expected_stdout},
    )


def run_removed_verify(runtime: OpenTenBaseRuntime, manifest: PluginManifest) -> ActionResult:
    timer = start_action()
    removed_probe = manifest.payload.get("removed_probe")
    if not removed_probe:
        raise ManifestError(f"missing removed_probe in manifest {manifest.path}")

    result = runtime.run_sql(str(removed_probe))
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    ok = result.returncode == 0 and stdout == "removed"
    return finish_action(
        timer,
        action="verify",
        plugin_id=manifest.plugin_id,
        ok=ok,
        detail="removed verify passed" if ok else stderr or stdout or "removed verify failed",
        returncode=result.returncode if result.returncode != 0 else (0 if ok else 1),
        stdout=stdout,
        stderr=stderr,
        metadata={"stage": "removed", "removed_probe": str(removed_probe)},
    )
