from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from plugin_ctl.cluster import ClusterNode
from plugin_ctl.runtime.opentenbase import ScpSshRemoteExecutor


class RemoteExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.node = ClusterNode(
            name="cn001",
            role="cn",
            host="10.0.0.11",
            ssh_port=2222,
            db_port=30004,
            ssh_user="opentenbase",
            db_user="opentenbase",
            database="postgres",
            lib_dir="/opt/otb/lib",
            extension_dir="/opt/otb/share/extension",
        )

    def test_run_uses_ssh_argument_list_without_shell(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run:
            result = ScpSshRemoteExecutor().run(self.node, ["echo", "ok"])

        args, kwargs = run.call_args
        self.assertEqual(args[0], ["ssh", "-p", "2222", "opentenbase@10.0.0.11", "echo", "ok"])
        self.assertFalse(kwargs["check"])
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertEqual(result.stdout, "ok")

    def test_copy_file_uses_scp_argument_list_without_shell(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run:
            result = ScpSshRemoteExecutor().copy_file(
                self.node,
                Path("otb_timeseries.so"),
                "/opt/otb/lib/otb_timeseries.so",
            )

        args, kwargs = run.call_args
        self.assertEqual(
            args[0],
            [
                "scp",
                "-P",
                "2222",
                "otb_timeseries.so",
                "opentenbase@10.0.0.11:/opt/otb/lib/otb_timeseries.so",
            ],
        )
        self.assertFalse(kwargs["check"])
        self.assertEqual(result.returncode, 0)

    def test_sha256_file_uses_remote_sha256sum(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc  /opt/otb/lib/otb_timeseries.so\n",
            stderr="",
        )
        with patch("subprocess.run", return_value=completed) as run:
            result = ScpSshRemoteExecutor().sha256_file(self.node, "/opt/otb/lib/otb_timeseries.so")

        args, _ = run.call_args
        self.assertEqual(
            args[0],
            ["ssh", "-p", "2222", "opentenbase@10.0.0.11", "sha256sum", "/opt/otb/lib/otb_timeseries.so"],
        )
        self.assertEqual(result.stdout, "abc  /opt/otb/lib/otb_timeseries.so\n")


if __name__ == "__main__":
    unittest.main()
