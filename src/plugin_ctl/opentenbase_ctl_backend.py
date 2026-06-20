from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess

from .cluster import (
    DEFAULT_DATABASE,
    DEFAULT_DB_USER,
    DEFAULT_EXTENSION_DIR,
    DEFAULT_LIB_DIR,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USER,
    ClusterConfig,
    ClusterNode,
)


@dataclass(frozen=True, slots=True)
class OpenTenBaseCtlStatusNode:
    name: str
    role: str
    host: str
    db_port: int
    status: str


@dataclass(frozen=True, slots=True)
class OpenTenBaseCtlStatus:
    instance_name: str
    version: str
    nodes: tuple[OpenTenBaseCtlStatusNode, ...]
    install_prefix: str


class OpenTenBaseCtlError(RuntimeError):
    pass


class OpenTenBaseCtlBackend:
    def __init__(self, *, binary: str | None = None, config_file: str | Path | None = None, timeout_seconds: int = 30) -> None:
        self.binary = binary or shutil.which("opentenbase_ctl") or "opentenbase_ctl"
        self.config_file = Path(config_file) if config_file else None
        self.timeout_seconds = timeout_seconds

    def _base_args(self) -> list[str]:
        args = [self.binary]
        return args

    def _candidate_config_files(self) -> list[Path]:
        if self.config_file is not None:
            return [self.config_file]
        home = Path.home()
        candidates = [
            Path.cwd() / "opentenbase_config.ini",
            Path.cwd() / "config.ini",
            home / "opentenbase_config.ini",
            home / "opentenbase_ctl_current" / "config.ini",
            Path("/data/opentenbase/opentenbase_ctl_current/config.ini"),
            Path("/data/opentenbase/opentenbase_ctl_current/opentenbase_config.ini"),
            Path("/opt/opentenbase/opentenbase_ctl_current/config.ini"),
            Path("/opt/opentenbase/opentenbase_ctl_current/opentenbase_config.ini"),
        ]
        seen: set[Path] = set()
        existing: list[Path] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists():
                existing.append(candidate)
        return existing

    def _runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        binary_path = shutil.which(self.binary) or self.binary
        try:
            prefix = Path(binary_path).resolve().parent.parent
        except OSError:
            return env
        candidate_dirs = [
            prefix / "lib",
            prefix / "lib64",
            Path("/usr/local/lib64"),
            Path("/usr/local/lib"),
        ]
        current = env.get("LD_LIBRARY_PATH", "")
        parts = [part for part in current.split(":") if part]
        for lib_dir in candidate_dirs:
            lib_text = str(lib_dir)
            if lib_dir.exists() and lib_text not in parts:
                parts.insert(0, lib_text)
        if parts:
            env["LD_LIBRARY_PATH"] = ":".join(parts)
        return env

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                env=self._runtime_env(),
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=exc.cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"command timed out after {self.timeout_seconds}s",
            )

    def help(self) -> subprocess.CompletedProcess[str]:
        return self._run([*self._base_args(), "--help"])

    def available(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None and self.binary == "opentenbase_ctl":
            return False, "opentenbase_ctl not found in PATH"
        result = self.help()
        text = f"{result.stdout}\n{result.stderr}"
        required = {"status", "sql", "scp"}
        missing = sorted(command for command in required if command not in text)
        if result.returncode not in {0, 1}:
            status_result = self.status()
            if status_result.returncode == 0:
                try:
                    self.parse_status(status_result.stdout)
                except OpenTenBaseCtlError as exc:
                    return False, str(exc)
                return True, "opentenbase_ctl status available"
            return False, text.strip() or f"opentenbase_ctl --help failed: {result.returncode}"
        if missing:
            status_result = self.status()
            if status_result.returncode == 0:
                try:
                    self.parse_status(status_result.stdout)
                except OpenTenBaseCtlError as exc:
                    return False, str(exc)
                return True, "opentenbase_ctl status available"
            return False, "opentenbase_ctl missing required subcommands: " + ", ".join(missing)
        return True, "opentenbase_ctl available"

    def status(self) -> subprocess.CompletedProcess[str]:
        args = [*self._base_args(), "status"]
        if self.config_file is not None:
            return self._run([*args, "-c", str(self.config_file)])
        result = self._run(args)
        if result.returncode == 0:
            return result
        for config_file in self._candidate_config_files():
            candidate_result = self._run([*args, "-c", str(config_file)])
            if candidate_result.returncode == 0:
                return candidate_result
        return result

    def parse_status(self, text: str) -> OpenTenBaseCtlStatus:
        instance_name = ""
        version = ""
        install_prefix = ""
        nodes: list[OpenTenBaseCtlStatusNode] = []

        node_re = re.compile(r"Node\s+([A-Za-z0-9_]+)\(([^:()]+):(\d+)\)\s+is\s+([A-Za-z]+)")
        prefix_re = re.compile(r"PATH=([^: \t]+?)/bin[:$]")

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("Instance name:"):
                instance_name = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                version = line.split(":", 1)[1].strip().lstrip("v")
            elif "Environment variable:" in line and not install_prefix:
                match = prefix_re.search(line)
                if match:
                    install_prefix = match.group(1)
            else:
                match = node_re.search(line)
                if not match:
                    continue
                name, host, db_port, status = match.groups()
                if name.startswith("cn"):
                    role = "cn"
                elif name.startswith("dn"):
                    role = "dn"
                else:
                    continue
                nodes.append(
                    OpenTenBaseCtlStatusNode(
                        name=name,
                        role=role,
                        host=host,
                        db_port=int(db_port),
                        status=status.lower(),
                    )
                )

        if not instance_name:
            raise OpenTenBaseCtlError("failed to parse instance name from opentenbase_ctl status")
        if not nodes:
            raise OpenTenBaseCtlError("failed to parse CN/DN nodes from opentenbase_ctl status")

        return OpenTenBaseCtlStatus(
            instance_name=instance_name,
            version=version,
            nodes=tuple(nodes),
            install_prefix=install_prefix,
        )

    def discover_cluster_config(
        self,
        *,
        name: str | None = None,
        ssh_user: str = DEFAULT_SSH_USER,
        db_user: str = DEFAULT_DB_USER,
        database: str = DEFAULT_DATABASE,
        ssh_port: int = DEFAULT_SSH_PORT,
        lib_dir: str | None = None,
        extension_dir: str | None = None,
    ) -> ClusterConfig:
        ok, detail = self.available()
        if not ok:
            raise OpenTenBaseCtlError(detail)

        result = self.status()
        if result.returncode != 0:
            raise OpenTenBaseCtlError(result.stderr.strip() or result.stdout.strip() or "opentenbase_ctl status failed")

        status = self.parse_status(result.stdout)
        prefix = status.install_prefix
        resolved_lib_dir = lib_dir or (f"{prefix}/lib/postgresql" if prefix else DEFAULT_LIB_DIR)
        resolved_extension_dir = extension_dir or (f"{prefix}/share/postgresql/extension" if prefix else DEFAULT_EXTENSION_DIR)
        nodes = tuple(
            ClusterNode(
                name=node.name,
                role=node.role,
                host=node.host,
                ssh_port=ssh_port,
                db_port=node.db_port,
                ssh_user=ssh_user,
                db_user=db_user,
                database=database,
                lib_dir=resolved_lib_dir,
                extension_dir=resolved_extension_dir,
            )
            for node in status.nodes
        )
        return ClusterConfig(name=name or status.instance_name, nodes=nodes, backend="opentenbase_ctl")
