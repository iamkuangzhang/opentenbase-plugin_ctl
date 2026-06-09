from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Protocol

from plugin_ctl.cluster import ClusterNode


@dataclass(frozen=True, slots=True)
class RemoteCommandResult:
    node: str
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class RemoteNodeExecutor(Protocol):
    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        ...

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        ...

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        ...


@dataclass(slots=True)
class ScpSshRemoteExecutor:
    timeout_seconds: int = 30

    def _run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        try:
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            return RemoteCommandResult(
                node=node.name,
                argv=tuple(argv),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        except subprocess.TimeoutExpired as exc:
            return RemoteCommandResult(
                node=node.name,
                argv=tuple(str(part) for part in exc.cmd),
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"command timed out after {self.timeout_seconds}s",
            )

    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        # 后续可以替换为 Paramiko / AsyncSSH；当前阶段只建立标准库 subprocess 骨架。
        return self._run(
            node,
            [
                "ssh",
                "-p",
                str(node.ssh_port),
                f"{node.ssh_user}@{node.host}",
                *argv,
            ],
        )

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        # 物理分发卡点：这里是真正远端复制入口，当前使用系统 scp。
        return self._run(
            node,
            [
                "scp",
                "-P",
                str(node.ssh_port),
                str(local_path),
                f"{node.ssh_user}@{node.host}:{remote_path}",
            ],
        )

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        # 对账卡点：后续可用该结果和本地 SHA256 做强校验。
        return self.run(node, ["sha256sum", remote_path])


@dataclass(slots=True)
class OpenTenBaseRuntime:
    container: str = "opentenbaseDN1"
    host: str = "127.0.0.1"
    port: int = 30004
    user: str = "opentenbase"
    database: str = "postgres"
    timeout_seconds: int = 10
    mode: str | None = None

    def runtime_mode(self) -> str:
        configured = (self.mode or os.getenv("OPENTENBASE_PLUGINCTL_RUNTIME") or "").strip().lower()
        if configured in {"local", "bare", "bare-metal"}:
            return "local"
        if configured == "docker":
            return "docker"
        return "docker" if shutil.which("docker") is not None else "local"

    def docker_available(self) -> bool:
        if self.runtime_mode() == "local":
            return True
        return shutil.which("docker") is not None

    def psql_path(self) -> str:
        if self.runtime_mode() == "local":
            return (
                os.getenv("OPENTENBASE_PLUGINCTL_PSQL")
                or shutil.which("psql")
                or "/data/opentenbase/install/opentenbase_bin_v2.0/bin/psql"
            )
        result = subprocess.run(
            ["docker", "exec", self.container, "bash", "-lc", "command -v psql"],
            check=False,
            capture_output=True,
            text=True,
        )
        candidate = result.stdout.strip()
        if candidate:
            return candidate
        return "/data/opentenbase/install/opentenbase_bin_v2.0/bin/psql"

    def list_containers(self) -> list[str]:
        if self.runtime_mode() == "local":
            return []
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_container_statuses(self) -> dict[str, str]:
        if self.runtime_mode() == "local":
            return {}
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {}
        statuses: dict[str, str] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            name, status = line.split("|", 1)
            statuses[name] = status
        return statuses

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        psql = self.psql_path()
        psql_args = [
                psql,
                "-X",
                "-A",
                "-t",
                "-h",
                self.host,
                "-p",
                str(self.port),
                "-U",
                self.user,
                "-d",
                self.database,
                "-c",
                sql,
            ]
        if self.runtime_mode() == "local":
            return self._run(psql_args)
        args = [
                "docker",
                "exec",
                self.container,
                *psql_args,
            ]
        return self._run(args)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=exc.cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"command timed out after {self.timeout_seconds}s",
            )

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        if self.runtime_mode() == "local":
            return self._run(list(args))
        return self._run(["docker", "exec", self.container, *args])

    def copy_to_container(self, source: Path, target: str) -> subprocess.CompletedProcess[str]:
        if self.runtime_mode() == "local":
            args = ["copy", str(source), target]
            try:
                target_path = Path(target)
                target_path.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    destination = target_path / source.name
                    if destination.exists():
                        shutil.rmtree(destination)
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, target_path / source.name)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
            except OSError as exc:
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(exc))
        return self._run(["docker", "cp", str(source), f"{self.container}:{target}"])

    def run_sql_file(self, file_path: str) -> subprocess.CompletedProcess[str]:
        psql = self.psql_path()
        psql_args = [
                psql,
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-h",
                self.host,
                "-p",
                str(self.port),
                "-U",
                self.user,
                "-d",
                self.database,
                "-f",
                file_path,
            ]
        if self.runtime_mode() == "local":
            return self._run(psql_args)
        return self._run(
            [
                "docker",
                "exec",
                self.container,
                *psql_args,
            ]
        )

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        psql = self.psql_path()
        psql_args = [
                psql,
                "-X",
                "-A",
                "-t",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                self.user,
                "-d",
                self.database,
                "-c",
                sql,
            ]
        if self.runtime_mode() == "local":
            return self._run(psql_args)
        return self._run(
            [
                "docker",
                "exec",
                self.container,
                *psql_args,
            ]
        )
