"""P2-10 — model/prompt/dataset provenance for evaluation runs.

The eval gate is only useful across releases if a run records the exact version triple it evaluated:
model/provider versions, prompt/template policy, and the dataset fingerprint. The registry is a
deterministic snapshot, not a mutable global service, so it stays cheap enough for Tier A.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping

from raku_rag.eval.models import EvaluationSet

DEFAULT_ANSWER_PROMPT_VERSION = "answer-grounded-contract-v1"
DEFAULT_INJECTION_GUARD_VERSION = "prompt-injection-guard-v1"


@dataclass(frozen=True)
class EvaluationVersionRegistry:
    dataset_version: str
    embedding_provider: str
    embedding_model_version: str
    embedding_dimension: int
    llm_model_version: str
    vlm_model_version: str = ""
    prompt_template_version: str = DEFAULT_ANSWER_PROMPT_VERSION
    injection_guard_version: str = DEFAULT_INJECTION_GUARD_VERSION
    extra: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "dataset_version": self.dataset_version,
            "embedding_provider": self.embedding_provider,
            "embedding_model_version": self.embedding_model_version,
            "embedding_dimension": self.embedding_dimension,
            "llm_model_version": self.llm_model_version,
            "vlm_model_version": self.vlm_model_version,
            "prompt_template_version": self.prompt_template_version,
            "injection_guard_version": self.injection_guard_version,
            "extra": dict(self.extra),
        }
        payload["registry_version"] = _registry_version(payload)
        return payload


def build_version_registry(system, eval_set: EvaluationSet) -> dict:
    embedder = getattr(system, "embedder", None)
    capability = getattr(embedder, "capability", None)
    embedding_provider = str(getattr(capability, "provider", "") or "")
    embedding_model_version = str(
        getattr(capability, "model_version", "") or getattr(embedder, "model_version", "") or ""
    )
    embedding_dimension = int(
        getattr(capability, "dimensions", None)
        or getattr(embedder, "dim", None)
        or getattr(embedder, "dimensions", None)
        or 0
    )
    registry = EvaluationVersionRegistry(
        dataset_version=eval_set.dataset_version or _fallback_dataset_version(eval_set),
        embedding_provider=embedding_provider,
        embedding_model_version=embedding_model_version,
        embedding_dimension=embedding_dimension,
        llm_model_version=str(getattr(getattr(system, "llm", None), "model", "") or ""),
        vlm_model_version=str(getattr(getattr(system, "vlm", None), "model", "") or ""),
    )
    return registry.to_dict()


def _fallback_dataset_version(eval_set: EvaluationSet) -> str:
    payload = [
        eval_set.tenant_id,
        eval_set.eval_set_id,
        [item.item_id for item in eval_set.items],
    ]
    return "dataset_" + _sha(payload)[:16]


def _registry_version(payload: Mapping[str, object]) -> str:
    return "eval_registry_" + _sha(payload)[:16]


def _sha(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    "DEFAULT_ANSWER_PROMPT_VERSION",
    "DEFAULT_INJECTION_GUARD_VERSION",
    "EvaluationVersionRegistry",
    "build_version_registry",
]
