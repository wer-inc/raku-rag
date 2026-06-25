from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

from raku_rag.core.config import Settings
from raku_rag.persistence.secret_store import (
    FileSecretStore,
    InMemorySecretStore,
    SecretNotFoundError,
    SecretsManagerSecretStore,
    secret_store_from_settings,
)


class _StdlibStoreContract:
    """Shared round-trip contract for the stdlib (in-memory/file) backends."""

    def _make(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def test_store_then_retrieve(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "refresh-xyz")
        self.assertEqual(store.retrieve_secret("tenant_a", "gdrive/conn1"), "refresh-xyz")

    def test_overwrite(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "old")
        store.store_secret("tenant_a", "gdrive/conn1", "new")
        self.assertEqual(store.retrieve_secret("tenant_a", "gdrive/conn1"), "new")

    def test_missing_raises(self) -> None:
        store = self._make()
        with self.assertRaises(SecretNotFoundError):
            store.retrieve_secret("tenant_a", "nope")

    def test_tenant_isolation(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "a-secret")
        with self.assertRaises(SecretNotFoundError):
            store.retrieve_secret("tenant_b", "gdrive/conn1")

    def test_delete(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "v")
        self.assertTrue(store.delete_secret("tenant_a", "gdrive/conn1"))
        self.assertFalse(store.delete_secret("tenant_a", "gdrive/conn1"))
        with self.assertRaises(SecretNotFoundError):
            store.retrieve_secret("tenant_a", "gdrive/conn1")

    def test_requires_tenant_and_name(self) -> None:
        store = self._make()
        with self.assertRaises(ValueError):
            store.store_secret("", "n", "v")
        with self.assertRaises(ValueError):
            store.store_secret("t", "", "v")


class InMemorySecretStoreTest(_StdlibStoreContract, unittest.TestCase):
    def _make(self):
        return InMemorySecretStore()


class FileSecretStoreTest(_StdlibStoreContract, unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _make(self):
        return FileSecretStore(Path(self._dir.name) / "secrets.json")

    def test_persists_across_instances(self) -> None:
        path = Path(self._dir.name) / "persist.json"
        FileSecretStore(path).store_secret("t", "gdrive/c", "v")
        self.assertEqual(FileSecretStore(path).retrieve_secret("t", "gdrive/c"), "v")


class _FakeSecretsManagerClient:
    """Minimal boto3 secretsmanager stand-in for the AWS backend."""

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self.created: list[dict] = []

    def put_secret_value(self, **kwargs):
        sid = kwargs["SecretId"]
        if sid not in self.secrets:
            raise RuntimeError("ResourceNotFoundException")
        self.secrets[sid] = kwargs["SecretString"]
        return {"ARN": sid}

    def create_secret(self, **kwargs):
        self.created.append(kwargs)
        self.secrets[kwargs["Name"]] = kwargs["SecretString"]
        return {"ARN": kwargs["Name"]}

    def get_secret_value(self, **kwargs):
        sid = kwargs["SecretId"]
        if sid not in self.secrets:
            raise RuntimeError("ResourceNotFoundException")
        return {"SecretString": self.secrets[sid]}

    def delete_secret(self, **kwargs):
        if kwargs["SecretId"] not in self.secrets:
            raise RuntimeError("ResourceNotFoundException")
        del self.secrets[kwargs["SecretId"]]
        return {}


class SecretsManagerSecretStoreTest(unittest.TestCase):
    def _make(self):
        self.client = _FakeSecretsManagerClient()
        return SecretsManagerSecretStore(
            client=self.client, kms_key_id="alias/raku-cmk", prefix="raku/test"
        )

    def test_create_then_update_round_trip(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "refresh-1")  # create path
        self.assertEqual(store.retrieve_secret("tenant_a", "gdrive/conn1"), "refresh-1")
        store.store_secret("tenant_a", "gdrive/conn1", "refresh-2")  # update path
        self.assertEqual(store.retrieve_secret("tenant_a", "gdrive/conn1"), "refresh-2")

    def test_physical_id_under_prefix_and_kms_tag(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "v")
        self.assertIn("raku/test/tenant_a/gdrive/conn1", self.client.secrets)
        created = self.client.created[0]
        self.assertEqual(created["KmsKeyId"], "alias/raku-cmk")
        self.assertIn({"Key": "raku:tenant", "Value": "tenant_a"}, created["Tags"])

    def test_missing_raises(self) -> None:
        store = self._make()
        with self.assertRaises(SecretNotFoundError):
            store.retrieve_secret("tenant_a", "absent")

    def test_delete(self) -> None:
        store = self._make()
        store.store_secret("tenant_a", "gdrive/conn1", "v")
        self.assertTrue(store.delete_secret("tenant_a", "gdrive/conn1"))
        self.assertFalse(store.delete_secret("tenant_a", "gdrive/conn1"))


class FactoryTest(unittest.TestCase):
    def test_deterministic_profile_is_in_memory(self) -> None:
        store = secret_store_from_settings(Settings(runtime_profile="deterministic"), env={})
        self.assertIsInstance(store, InMemorySecretStore)

    def test_file_override(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = secret_store_from_settings(
                Settings(),
                env={"RAKU_SECRET_STORE": "file", "RAKU_SECRET_STORE_PATH": f"{d}/s.json"},
            )
            self.assertIsInstance(store, FileSecretStore)

    def test_production_profile_selects_secrets_manager(self) -> None:
        # Inject a fake client via the override path is not available through the factory, so we
        # only assert it ATTEMPTS the AWS backend; with boto3 absent it raises RuntimeError.
        try:
            store = secret_store_from_settings(Settings(runtime_profile="production"), env={})
            self.assertIsInstance(store, SecretsManagerSecretStore)
        except RuntimeError as exc:
            self.assertIn("boto3", str(exc))


class ModuleImportIsStdlibOnlyTest(unittest.TestCase):
    def test_import_without_boto3(self) -> None:
        """The module must import (and the stdlib backend must work) with boto3 absent.

        Run in a subprocess so blocking boto3 cannot contaminate this process's import state.
        """
        code = (
            "import sys\n"
            "sys.modules['boto3'] = None\n"  # make `import boto3` raise ImportError
            "import raku_rag.persistence.secret_store as m\n"
            "s = m.InMemorySecretStore()\n"
            "s.store_secret('t', 'n', 'v')\n"
            "assert s.retrieve_secret('t', 'n') == 'v'\n"
            "print('STDLIB_OK')\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = "src" + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STDLIB_OK", result.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
