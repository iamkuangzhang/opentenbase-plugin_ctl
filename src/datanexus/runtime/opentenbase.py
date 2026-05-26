from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from datanexus.cluster import ClusterNode


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

    def docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def psql_path(self) -> str:
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
        args = [
                "docker",
                "exec",
                self.container,
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
        return self._run(["docker", "exec", self.container, *args])

    def copy_to_container(self, source: Path, target: str) -> subprocess.CompletedProcess[str]:
        return self._run(["docker", "cp", str(source), f"{self.container}:{target}"])

    def run_sql_file(self, file_path: str) -> subprocess.CompletedProcess[str]:
        psql = self.psql_path()
        return self._run(
            [
                "docker",
                "exec",
                self.container,
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
        )

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        psql = self.psql_path()
        return self._run(
            [
                "docker",
                "exec",
                self.container,
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
        )
