import subprocess
import tempfile
import unittest
from pathlib import Path

from plugin_ctl.cluster import load_cluster_config, run_cluster_status


class MockRuntime:
    def __init__(self, container: str) -> None:
        self.container = container

    def docker_available(self) -> bool:
        return True

    def list_container_statuses(self) -> dict[str, str]:
        return {
            "opentenbaseCN": "Up 1 minute",
            "opentenbaseDN1": "Up 1 minute",
            "opentenbaseDN2": "Up 1 minute",
        }

    def exec(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = args[-1]
        process_output = {
            "gtm -D /data/opentenbase/data/gtm": "gtm -D /data/opentenbase/data/gtm",
            "postgres --datanode -D /data/opentenbase/data/dn001": "postgres --datanode -D /data/opentenbase/data/dn001",
            "postgres --coordinator -D /data/opentenbase/data/coord": "postgres --coordinator -D /data/opentenbase/data/coord",
            "postgres --datanode -D /data/opentenbase/data/dn002": "postgres --datanode -D /data/opentenbase/data/dn002",
        }
        for pattern, output in process_output.items():
            if pattern in command:
                return subprocess.CompletedProcess(args=list(args), returncode=0, stdout=output, stderr="")
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="")

    def run_sql(self, sql: str) -> subprocess.CompletedProcess[str]:
        if sql == "SELECT 1;":
            return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")
        if "FROM pgxc_node" in sql:
            return subprocess.CompletedProcess(
                args=["psql"],
                returncode=0,
                stdout=(
                    "cn001|C|172.16.200.10|30004\n"
                    "cn002|C|172.16.200.15|30004\n"
                    "dn001|D|172.16.200.10|40004\n"
                    "dn002|D|172.16.200.15|40004\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(args=["psql"], returncode=1, stdout="", stderr="unexpected sql")

    def run_sql_at(self, host: str, port: int, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="1\n", stderr="")


class MissingContainerRuntime(MockRuntime):
    def list_container_statuses(self) -> dict[str, str]:
        return {
            "opentenbaseDN1": "Up 1 minute",
            "opentenbaseDN2": "Up 1 minute",
        }


class ClusterStatusTest(unittest.TestCase):
    def test_cluster_status_reports_all_expected_checks(self) -> None:
        checks = run_cluster_status(MockRuntime)
        names = [check.name for check in checks]

        self.assertTrue(all(check.ok for check in checks))
        self.assertIn("container:opentenbaseCN", names)
        self.assertIn("process:gtm", names)
        self.assertIn("process:cn001", names)
        self.assertIn("process:dn002", names)
        self.assertIn("psql:30004", names)
        self.assertIn("registered_nodes", names)

    def test_cluster_status_reports_missing_container(self) -> None:
        checks = run_cluster_status(MissingContainerRuntime)
        cn_check = next(check for check in checks if check.name == "container:opentenbaseCN")

        self.assertFalse(cn_check.ok)
        self.assertEqual(cn_check.detail, "missing")


class ClusterConfigTest(unittest.TestCase):
    def write_config(self, text: str) -> Path:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        path = Path(tempdir.name) / "cluster.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_cluster_config_splits_coordinators_and_datanodes(self) -> None:
        path = self.write_config(
            """
[[nodes]]
name = "cn001"
role = "cn"
host = "10.0.0.11"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"

[[nodes]]
name = "dn001"
role = "dn"
host = "10.0.0.21"
ssh_port = 22
db_port = 40004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"
"""
        )

        config = load_cluster_config(path)

        self.assertEqual([node.name for node in config.coordinators], ["cn001"])
        self.assertEqual([node.name for node in config.datanodes], ["dn001"])

    def test_load_cluster_config_rejects_duplicate_node_names(self) -> None:
        path = self.write_config(
            """
[[nodes]]
name = "same"
role = "cn"
host = "10.0.0.11"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"

[[nodes]]
name = "same"
role = "dn"
host = "10.0.0.21"
ssh_port = 22
db_port = 40004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"
"""
        )

        with self.assertRaisesRegex(ValueError, "duplicate node name"):
            load_cluster_config(path)

    def test_load_cluster_config_rejects_invalid_role_and_missing_dirs(self) -> None:
        invalid_role = self.write_config(
            """
[[nodes]]
name = "bad"
role = "worker"
host = "10.0.0.11"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
extension_dir = "/opt/otb/share/extension"
"""
        )
        with self.assertRaisesRegex(ValueError, "invalid role"):
            load_cluster_config(invalid_role)

        missing_dir = self.write_config(
            """
[[nodes]]
name = "cn001"
role = "cn"
host = "10.0.0.11"
ssh_port = 22
db_port = 30004
ssh_user = "opentenbase"
db_user = "opentenbase"
database = "postgres"
lib_dir = "/opt/otb/lib"
"""
        )
        with self.assertRaisesRegex(ValueError, "extension_dir"):
            load_cluster_config(missing_dir)


if __name__ == "__main__":
    unittest.main()
