import subprocess
import unittest

from datanexus.cluster import run_cluster_status


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


if __name__ == "__main__":
    unittest.main()
