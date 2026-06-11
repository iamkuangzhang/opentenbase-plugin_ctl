from __future__ import annotations

from .action_result import ActionResult, finish_action, start_action
from .manifest import PluginManifest
from .runtime.opentenbase import OpenTenBaseRuntime


def rollback_plugin(runtime: OpenTenBaseRuntime, manifest: PluginManifest, *, execute: bool = False) -> ActionResult:
    timer = start_action()
    rollback_sql = manifest.rollback_sql
    if rollback_sql is None:
        return finish_action(
            timer,
            action="rollback",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail="rollback not supported: manifest has no rollback_sql",
            returncode=2,
            metadata={"stage": "validate"},
        )
    if not rollback_sql.exists():
        return finish_action(
            timer,
            action="rollback",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=f"rollback sql not found: {rollback_sql}",
            returncode=1,
            metadata={"stage": "validate", "rollback_sql": str(rollback_sql), "execute": execute},
        )
    if not execute:
        return finish_action(
            timer,
            action="rollback",
            plugin_id=manifest.plugin_id,
            ok=True,
            detail="rollback plan ready; rerun without --dry-run to apply",
            returncode=0,
            stdout=rollback_sql.read_text(encoding="utf-8").strip(),
            metadata={"stage": "plan", "rollback_sql": str(rollback_sql), "execute": False, "dry_run": True},
        )

    probe = runtime.run_sql("SELECT 1;")
    if probe.returncode != 0:
        return finish_action(
            timer,
            action="rollback",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=probe.stderr.strip() or probe.stdout.strip() or "OpenTenBase is not reachable",
            returncode=probe.returncode or 1,
            stdout=probe.stdout.strip(),
            stderr=probe.stderr.strip(),
            metadata={"stage": "probe", "rollback_sql": str(rollback_sql), "execute": True},
        )

    result = runtime.run_sql(rollback_sql.read_text(encoding="utf-8"))
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if result.returncode != 0:
        return finish_action(
            timer,
            action="rollback",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=stderr or stdout or "rollback failed",
            returncode=result.returncode or 1,
            stdout=stdout,
            stderr=stderr,
            metadata={"stage": "execute", "rollback_sql": str(rollback_sql), "execute": True},
        )

    return finish_action(
        timer,
        action="rollback",
        plugin_id=manifest.plugin_id,
        ok=True,
        detail="rollback passed",
        returncode=0,
        stdout=stdout,
        stderr=stderr,
        metadata={"stage": "execute", "rollback_sql": str(rollback_sql), "execute": True},
    )
