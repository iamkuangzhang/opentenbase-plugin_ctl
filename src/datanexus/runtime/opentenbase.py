from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


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
