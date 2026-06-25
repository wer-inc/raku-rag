"""Per-tenant secret storage for connector OAuth refresh tokens (021-gdrive-oauth).

Refresh tokens are long-lived bearer credentials and must NEVER live in the datasource
config blob, logs, or the browser. They are written once (at OAuth callback) to a
``SecretStore`` and read back only at sync time to mint a short-lived access token.

Three implementations, selected by ``RAKU_RUNTIME_PROFILE`` via :func:`secret_store_from_settings`:

* :class:`InMemorySecretStore` — default (``deterministic`` profile). Stdlib-only, keeps the
  Tier-A gate fast and free of ``boto3``. Lost on process restart (acceptable: a tenant
  re-connects, mirroring the existing in-memory admin store).
* :class:`FileSecretStore` — stdlib JSON file, for local dev persistence across restarts.
* :class:`SecretsManagerSecretStore` — ``production`` profile. AWS Secrets Manager with a KMS
  CMK doing envelope encryption (``boto3`` lazy-imported inside ``__init__`` so the module never
  pulls a non-stdlib dependency at import time — mirrors ``S3Connector``). Zero crypto dependency
  in Python: KMS performs the encryption.

Physical secret id is ``{prefix}/{tenant_id}/{secret_name}`` so tenant isolation holds in every
backend and the AWS names sit under one IAM-grantable prefix (``{prefix}/*``).
"""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

DEFAULT_SECRETS_PREFIX = "raku/local"


class SecretNotFoundError(KeyError):
    """Raised when a requested secret does not exist in the store."""


class SecretStore(ABC):
    """Stores per-tenant connector secrets (e.g. OAuth refresh tokens)."""

    @abstractmethod
    def store_secret(self, tenant_id: str, secret_name: str, value: str) -> None:
        """Create or overwrite the secret ``secret_name`` for ``tenant_id``."""

    @abstractmethod
    def retrieve_secret(self, tenant_id: str, secret_name: str) -> str:
        """Return the secret value; raise :class:`SecretNotFoundError` when absent."""

    @abstractmethod
    def delete_secret(self, tenant_id: str, secret_name: str) -> bool:
        """Delete the secret. Return ``True`` if it existed, ``False`` otherwise."""


def _require(tenant_id: str, secret_name: str) -> None:
    if not tenant_id:
        raise ValueError("tenant_id is required")
    if not secret_name:
        raise ValueError("secret_name is required")


class InMemorySecretStore(SecretStore):
    """Process-local secret store. Default for the deterministic/test profile."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def store_secret(self, tenant_id: str, secret_name: str, value: str) -> None:
        _require(tenant_id, secret_name)
        with self._lock:
            self._items[(tenant_id, secret_name)] = value

    def retrieve_secret(self, tenant_id: str, secret_name: str) -> str:
        _require(tenant_id, secret_name)
        with self._lock:
            try:
                return self._items[(tenant_id, secret_name)]
            except KeyError as exc:
                raise SecretNotFoundError(f"{tenant_id}/{secret_name}") from exc

    def delete_secret(self, tenant_id: str, secret_name: str) -> bool:
        _require(tenant_id, secret_name)
        with self._lock:
            return self._items.pop((tenant_id, secret_name), None) is not None


class FileSecretStore(SecretStore):
    """JSON-file-backed secret store for local dev (stdlib only).

    Not encrypted at rest — for local development only; production uses
    :class:`SecretsManagerSecretStore`.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _key(self, tenant_id: str, secret_name: str) -> str:
        return f"{tenant_id}::{secret_name}"

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def store_secret(self, tenant_id: str, secret_name: str, value: str) -> None:
        _require(tenant_id, secret_name)
        with self._lock:
            data = self._load()
            data[self._key(tenant_id, secret_name)] = value
            self._save(data)

    def retrieve_secret(self, tenant_id: str, secret_name: str) -> str:
        _require(tenant_id, secret_name)
        with self._lock:
            data = self._load()
            try:
                return data[self._key(tenant_id, secret_name)]
            except KeyError as exc:
                raise SecretNotFoundError(f"{tenant_id}/{secret_name}") from exc

    def delete_secret(self, tenant_id: str, secret_name: str) -> bool:
        _require(tenant_id, secret_name)
        with self._lock:
            data = self._load()
            existed = data.pop(self._key(tenant_id, secret_name), None) is not None
            if existed:
                self._save(data)
            return existed


class SecretsManagerSecretStore(SecretStore):
    """AWS Secrets Manager backend with KMS envelope encryption (production profile).

    ``boto3`` is imported lazily inside ``__init__`` (never at module load) so importing this
    module stays stdlib-only and the Tier-A gate is unaffected. The KMS CMK does all encryption;
    no Python crypto dependency is introduced.
    """

    def __init__(
        self,
        *,
        region_name: str | None = None,
        kms_key_id: str | None = None,
        prefix: str = DEFAULT_SECRETS_PREFIX,
        client: object | None = None,
    ) -> None:
        self._prefix = prefix.rstrip("/")
        self._kms_key_id = kms_key_id or None
        if client is not None:
            self._client = client
        else:
            try:
                import boto3  # type: ignore
            except Exception as exc:  # pragma: no cover - optional prod dependency
                raise RuntimeError(
                    "boto3 is required for SecretsManagerSecretStore without an injected client"
                ) from exc
            region = region_name or os.environ.get("AWS_REGION") or os.environ.get(
                "AWS_DEFAULT_REGION", "us-east-1"
            )
            self._client = boto3.client("secretsmanager", region_name=region)

    def _physical_id(self, tenant_id: str, secret_name: str) -> str:
        return f"{self._prefix}/{tenant_id}/{secret_name}"

    def store_secret(self, tenant_id: str, secret_name: str, value: str) -> None:
        _require(tenant_id, secret_name)
        name = self._physical_id(tenant_id, secret_name)
        # Try update first; create on absence. Avoids importing botocore exception classes.
        try:
            kwargs = {"SecretId": name, "SecretString": value}
            if self._kms_key_id:
                kwargs["KmsKeyId"] = self._kms_key_id
            self._client.put_secret_value(**kwargs)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - secret may not exist yet
            create_kwargs = {
                "Name": name,
                "SecretString": value,
                "Tags": [
                    {"Key": "raku:tenant", "Value": tenant_id},
                    {"Key": "raku:purpose", "Value": "connector-oauth"},
                ],
            }
            if self._kms_key_id:
                create_kwargs["KmsKeyId"] = self._kms_key_id
            self._client.create_secret(**create_kwargs)  # type: ignore[attr-defined]

    def retrieve_secret(self, tenant_id: str, secret_name: str) -> str:
        _require(tenant_id, secret_name)
        name = self._physical_id(tenant_id, secret_name)
        try:
            resp = self._client.get_secret_value(SecretId=name)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - absent / access denied
            raise SecretNotFoundError(name) from exc
        value = resp.get("SecretString")
        if value is None:
            raise SecretNotFoundError(name)
        return value

    def delete_secret(self, tenant_id: str, secret_name: str) -> bool:
        _require(tenant_id, secret_name)
        name = self._physical_id(tenant_id, secret_name)
        try:
            self._client.delete_secret(  # type: ignore[attr-defined]
                SecretId=name, ForceDeleteWithoutRecovery=True
            )
            return True
        except Exception:  # noqa: BLE001 - already gone
            return False


def secret_store_from_settings(settings, *, env: dict | None = None) -> SecretStore:
    """Select a :class:`SecretStore` for the active runtime profile.

    ``production`` -> AWS Secrets Manager + KMS. Any other profile -> in-memory (stdlib-only,
    keeps the Tier-A gate boto3-free). Set ``RAKU_SECRET_STORE=file`` with ``RAKU_SECRET_STORE_PATH``
    to opt into the local file backend regardless of profile.
    """
    src = os.environ if env is None else env
    override = str(src.get("RAKU_SECRET_STORE", "")).strip().lower()
    if override == "file":
        return FileSecretStore(src.get("RAKU_SECRET_STORE_PATH", ".raku-secrets.json"))
    if override == "memory":
        return InMemorySecretStore()

    # RAKU_SECRET_STORE=aws forces Secrets Manager independently of the runtime profile, so a
    # deterministic-profile deploy (real embeddings/LLM off) still persists OAuth refresh tokens
    # durably. Otherwise the production profile selects it; everything else stays in-memory.
    use_secrets_manager = override in {"aws", "secretsmanager"} or (
        getattr(settings, "runtime_profile", "deterministic") == "production"
    )
    if use_secrets_manager:
        return SecretsManagerSecretStore(
            region_name=getattr(settings, "aws_region", None),
            kms_key_id=getattr(settings, "secrets_manager_kms_key_id", "") or None,
            prefix=str(src.get("RAKU_SECRETS_PREFIX", DEFAULT_SECRETS_PREFIX)),
        )
    return InMemorySecretStore()
