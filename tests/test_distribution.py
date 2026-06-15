import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from plugin_ctl.cluster import ClusterConfig, ClusterNode
from plugin_ctl.distribution import distribute_payload_to_nodes, sync_plugin_metadata_to_nodes
from plugin_ctl.manifest import load_manifest
from plugin_ctl.runtime.opentenbase import RemoteCommandResult


class MockRemoteExecutor:
    def __init__(self, *, fail_copy_for: str = "", fail_directory_for: str = "", mismatch_checksum_for: str = "") -> None:
        self.fail_copy_for = fail_copy_for
        self.fail_directory_for = fail_directory_for
        self.mismatch_checksum_for = mismatch_checksum_for
        self.copies: list[tuple[str, str, str]] = []
        self.remote_hashes: dict[tuple[str, str], str] = {}
        self.directory_checks: list[tuple[str, tuple[str, ...]]] = []

    def run(self, node: ClusterNode, argv: list[str]) -> RemoteCommandResult:
        self.directory_checks.append((node.name, tuple(argv)))
        if node.name == self.fail_directory_for and argv[:2] == ["test", "-w"]:
            return RemoteCommandResult(node=node.name, argv=tuple(argv), returncode=1, stdout="", stderr="not writable")
        return RemoteCommandResult(node=node.name, argv=tuple(argv), returncode=0, stdout="", stderr="")

    def copy_file(self, node: ClusterNode, local_path: Path, remote_path: str) -> RemoteCommandResult:
        self.copies.append((node.name, str(local_path), remote_path))
        if node.name == self.fail_copy_for:
            return RemoteCommandResult(node=node.name, argv=("scp",), returncode=1, stdout="", stderr="copy failed")
        digest = sha256(local_path.read_bytes()).hexdigest()
        self.remote_hashes[(node.name, remote_path)] = digest
        return RemoteCommandResult(node=node.name, argv=("scp",), returncode=0, stdout="", stderr="")

    def sha256_file(self, node: ClusterNode, remote_path: str) -> RemoteCommandResult:
        digest = self.remote_hashes.get((node.name, remote_path), "")
        if node.name == self.mismatch_checksum_for and digest:
            digest = "0" * 64
        return RemoteCommandResult(
            node=node.name,
            argv=("sha256sum", remote_path),
            returncode=0 if digest else 1,
            stdout=f"{digest}  {remote_path}\n" if digest else "",
            stderr="" if digest else "missing",
        )


class DistributionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.cluster = ClusterConfig(
            name="test-cluster",
            nodes=(
                ClusterNode(
                    name="cn001",
                    role="cn",
                    host="10.0.0.11",
                    ssh_port=22,
                    db_port=30004,
                    ssh_user="opentenbase",
                    db_user="opentenbase",
                    database="postgres",
                    lib_dir="/opt/otb/lib",
                    extension_dir="/opt/otb/share/extension",
                ),
                ClusterNode(
                    name="dn001",
                    role="dn",
                    host="10.0.0.21",
                    ssh_port=22,
                    db_port=40004,
                    ssh_user="opentenbase",
                    db_user="opentenbase",
                    database="postgres",
                    lib_dir="/opt/otb/lib",
                    extension_dir="/opt/otb/share/extension",
                ),
            )
        )

    def write_payload(self, name: str, content: bytes = b"payload") -> Path:
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_distribute_payload_maps_files_to_role_directories_and_checksums(self) -> None:
        so_file = self.write_payload("demo.so")
        sql_file = self.write_payload("demo--1.0.sql")
        control_file = self.write_payload("demo.control")
        executor = MockRemoteExecutor()

        results = distribute_payload_to_nodes(self.cluster, [so_file, sql_file, control_file], executor, max_workers=2)

        self.assertEqual(len(results), 6)
        self.assertTrue(all(result.ok for result in results))
        self.assertTrue(all(result.status == "distributed" for result in results))
        remote_paths = {copy[2] for copy in executor.copies}
        self.assertIn("/opt/otb/lib/demo.so", remote_paths)
        self.assertIn("/opt/otb/share/extension/demo--1.0.sql", remote_paths)
        self.assertIn("/opt/otb/share/extension/demo.control", remote_paths)
        self.assertIn(("cn001", ("test", "-d", "/opt/otb/lib")), executor.directory_checks)
        self.assertIn(("cn001", ("test", "-w", "/opt/otb/lib")), executor.directory_checks)

    def test_distribute_payload_returns_structured_copy_failures(self) -> None:
        so_file = self.write_payload("demo.so")
        executor = MockRemoteExecutor(fail_copy_for="dn001")

        results = distribute_payload_to_nodes(self.cluster, [so_file], executor)

        failed = next(result for result in results if result.node == "dn001")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.status, "copy_failed")
        self.assertEqual(failed.stage, "copy")
        self.assertEqual(failed.detail, "copy failed")

    def test_distribute_payload_rejects_unsupported_file_types(self) -> None:
        txt_file = self.write_payload("README.txt")

        results = distribute_payload_to_nodes(self.cluster, [txt_file], MockRemoteExecutor())

        self.assertEqual({result.stage for result in results}, {"classify"})
        self.assertEqual({result.status for result in results}, {"unsupported"})
        self.assertTrue(all(not result.ok for result in results))

    def test_distribute_payload_reports_checksum_mismatch(self) -> None:
        so_file = self.write_payload("demo.so")
        executor = MockRemoteExecutor(mismatch_checksum_for="cn001")

        results = distribute_payload_to_nodes(self.cluster, [so_file], executor)

        failed = next(result for result in results if result.node == "cn001")
        passed = next(result for result in results if result.node == "dn001")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.status, "checksum_failed")
        self.assertFalse(failed.checksum_ok)
        self.assertTrue(passed.ok)

    def test_distribute_payload_reports_unwritable_remote_directory(self) -> None:
        control_file = self.write_payload("demo.control")
        executor = MockRemoteExecutor(fail_directory_for="dn001")

        results = distribute_payload_to_nodes(self.cluster, [control_file], executor)

        failed = next(result for result in results if result.node == "dn001")
        passed = next(result for result in results if result.node == "cn001")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.status, "directory_failed")
        self.assertEqual(failed.stage, "precheck")
        self.assertEqual(failed.detail, "not writable")
        self.assertTrue(passed.ok)

    def test_sync_plugin_metadata_copies_manifest_and_payload_to_hidden_package_dir(self) -> None:
        plugin_dir = self.root / "demo_plugin"
        payload_dir = plugin_dir / "payload"
        payload_dir.mkdir(parents=True)
        manifest_path = plugin_dir / "manifest.yml"
        manifest_path.write_text(
            "\n".join(
                [
                    "plugin_id: demo_plugin",
                    "name: Demo Plugin",
                    "version: 0.1.0",
                    "description: Demo plugin.",
                    "database: opentenbase",
                    "targets:",
                    "  cn: true",
                    "  dn: true",
                    "payload:",
                    "  source_root: payload",
                    "install_sql: payload/demo_plugin--0.1.0.sql",
                    "verify_sql: SELECT 1;",
                    "rollback_sql: payload/rollback.sql",
                    "installed_probe: SELECT 1;",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (payload_dir / "demo_plugin.control").write_text("default_version = '0.1.0'\n", encoding="utf-8")
        (payload_dir / "demo_plugin--0.1.0.sql").write_text("SELECT 1;\n", encoding="utf-8")
        manifest = load_manifest(manifest_path)
        executor = MockRemoteExecutor()

        results = sync_plugin_metadata_to_nodes(self.cluster, manifest, executor, max_workers=2)

        self.assertTrue(all(result.ok for result in results))
        remote_paths = {copy[2] for copy in executor.copies}
        self.assertIn(".plugin_ctl/packages/demo_plugin/manifest.yml", remote_paths)
        self.assertIn(".plugin_ctl/packages/demo_plugin/payload/demo_plugin.control", remote_paths)
        self.assertIn(".plugin_ctl/packages/demo_plugin/payload/demo_plugin--0.1.0.sql", remote_paths)


if __name__ == "__main__":
    unittest.main()
