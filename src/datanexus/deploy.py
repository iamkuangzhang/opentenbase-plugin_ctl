from __future__ import annotations

from uuid import uuid4

from .action_result import ActionResult, finish_action, start_action
from .manifest import PluginManifest
from .runtime.opentenbase import OpenTenBaseRuntime


def deploy_sql_payload(runtime: OpenTenBaseRuntime, manifest: PluginManifest) -> ActionResult:
    timer = start_action()
    source_root = manifest.source_root
    install_sql = manifest.install_sql
    if not source_root.exists():
        return finish_action(timer, action="deploy", plugin_id=manifest.plugin_id, ok=False, detail=f"source root not found: {source_root}", returncode=1, metadata={"stage": "validate"})
    if not install_sql.exists():
        return finish_action(timer, action="deploy", plugin_id=manifest.plugin_id, ok=False, detail=f"install sql not found: {install_sql}", returncode=1, metadata={"stage": "validate"})

    probe = runtime.run_sql("SELECT 1;")
    if probe.returncode != 0:
        detail = probe.stderr.strip() or probe.stdout.strip() or "OpenTenBase is not reachable"
        return finish_action(
            timer,
            action="deploy",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=detail,
            returncode=probe.returncode or 1,
            stdout=probe.stdout.strip(),
            stderr=probe.stderr.strip(),
            metadata={"stage": "probe"},
        )

    installed_probe = manifest.payload.get("installed_probe")
    if installed_probe:
        installed = runtime.run_sql(str(installed_probe))
        if installed.returncode == 0 and installed.stdout.strip():
            version = installed.stdout.strip()
            return finish_action(
                timer,
                action="deploy",
                plugin_id=manifest.plugin_id,
                ok=True,
                detail=f"already deployed: {version}",
                returncode=0,
                stdout=installed.stdout.strip(),
                stderr=installed.stderr.strip(),
                metadata={"stage": "installed", "installed_version": version, "remote_root": ""},
            )

    remote_root = f"/tmp/datanexus/{manifest.plugin_id}_{uuid4().hex[:8]}"
    cleanup = runtime.exec("bash", "-lc", f"rm -rf {remote_root} && mkdir -p {remote_root}")
    if cleanup.returncode != 0:
        return finish_action(
            timer,
            action="deploy",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=cleanup.stderr.strip() or "failed to prepare remote directory",
            returncode=cleanup.returncode,
            stdout=cleanup.stdout.strip(),
            stderr=cleanup.stderr.strip(),
            metadata={"stage": "prepare", "remote_root": remote_root},
        )

    copy = runtime.copy_to_container(source_root, remote_root)
    if copy.returncode != 0:
        return finish_action(
            timer,
            action="deploy",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=copy.stderr.strip() or "failed to copy payload",
            returncode=copy.returncode,
            stdout=copy.stdout.strip(),
            stderr=copy.stderr.strip(),
            metadata={"stage": "copy", "remote_root": remote_root},
        )

    remote_plugin_root = f"{remote_root}/{source_root.name}"
    relative_install = install_sql.relative_to(source_root).as_posix()
    remote_install_sql = f"{remote_plugin_root}/{relative_install}"
    install = runtime.run_sql_file(remote_install_sql)
    stdout = install.stdout.strip()
    stderr = install.stderr.strip()
    if install.returncode != 0:
        detail = stderr or stdout or "deploy failed"
        return finish_action(
            timer,
            action="deploy",
            plugin_id=manifest.plugin_id,
            ok=False,
            detail=detail,
            returncode=install.returncode,
            stdout=stdout,
            stderr=stderr,
            metadata={"stage": "install", "remote_root": remote_root, "remote_install_sql": remote_install_sql},
        )

    return finish_action(
        timer,
        action="deploy",
        plugin_id=manifest.plugin_id,
        ok=True,
        detail="deploy sql payload passed",
        returncode=install.returncode,
        stdout=stdout,
        stderr=stderr,
        metadata={"stage": "install", "remote_root": remote_root, "remote_install_sql": remote_install_sql},
    )
