"""Python answer-service — the internal HTTP boundary over the Postgres-backed ProductionSystem.

This is the one place that exposes the proven RAG core (001 Step 2/3: Postgres + pgvector + RLS, with the
security + ranking parity gates green) over HTTP. The NestJS API is a THIN product facade that forwards
authenticated requests here; the RAG truth (retrieval / ACL / ranking) lives ONLY in ProductionSystem and
is never reimplemented in TypeScript.

    POST /internal/answer  {tenant_id,user_id,groups,roles,query,collection_id?} -> AnswerResponse JSON
    POST /internal/search  {...}                                                 -> {results,correlation_id}
    POST /internal/ingest  {...}                                                 -> IngestResponse JSON
    GET  /internal/assets/{asset_id}                                             -> authorized VisualAsset JSON
    GET  /internal/ingestion-runs/{id}                                           -> IngestionRun JSON
    GET  /internal/documents/{id}/processing-status                              -> DocumentProcessingState JSON
    GET  /internal/sources/{id}/sync-status                                      -> SourceSyncState JSON
    POST /internal/sources/{id}/preview                                          -> datasource mapping preview JSON
    GET  /healthz                                                                -> {status:"ok"}

Run:  POSTGRES_URL=postgresql://raku:raku@127.0.0.1:5432/raku_parity \
      PYTHONPATH=src python3 apps/answer-service/server.py --seed --reset-demo-db --port 8088
stdlib only (http.server) + the project's psycopg-backed ProductionSystem.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import sys
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

# Run as a script: put the project root and src/ on sys.path so `raku_rag` and worker helpers resolve.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from raku_rag.domain.models import ACLGrant, IdentityClaims, ScopeType, SubjectType  # noqa: E402
from raku_rag.eval import EvaluationRunner, EvaluationSet  # noqa: E402
from raku_rag.manufacturing.drafts.review import InvalidTransitionError  # noqa: E402
from raku_rag.persistence.evaluation_runs import (  # noqa: E402
    InMemoryEvaluationRunRepository,
    PostgresEvaluationRunRepository,
)
from raku_rag.persistence.datasources import (  # noqa: E402
    InMemoryDataSourceRepository,
    PostgresDataSourceRepository,
)
from raku_rag.services.source_sync import SourceSyncService  # noqa: E402
from raku_rag.industry import (  # noqa: E402
    IndustryApiService,
    InvestmentApiService,
    RealEstateApiService,
)
from raku_rag.persistence.provider_config_audit import ProviderConfigAuditRepository  # noqa: E402
from raku_rag.persistence.chatbot import (  # noqa: E402
    InMemoryChatFeedbackRepository,
    InMemoryChatHandoffRepository,
    InMemoryChatScenarioRepository,
    InMemoryChatSessionRepository,
    InMemoryChatbotSourcePolicyRepository,
    PostgresChatFeedbackRepository,
    PostgresChatHandoffRepository,
    PostgresChatScenarioRepository,
    PostgresChatSessionRepository,
    PostgresChatbotSourcePolicyRepository,
)
from raku_rag.production import (  # noqa: E402
    DEFAULT_DSN,
    ProductionSystem,
    build_manufacturing_system_for_base,
)
from raku_rag.core.config import settings_from_env  # noqa: E402
from raku_rag.core.coreference import followup_from_history  # noqa: E402
from raku_rag.services.answer_format import answer_format_metadata  # noqa: E402
from raku_rag.services.datasource_sync import build_sync_documents  # noqa: E402
from raku_rag.persistence.oauth_connection import (  # noqa: E402
    InMemoryOAuthConnectionStore,
    build_connection,
)
from raku_rag.persistence.secret_store import secret_store_from_settings  # noqa: E402
from raku_rag.services import oauth_token_resolver  # noqa: E402
from raku_rag.providers.connectors import default_connector_from_env  # noqa: E402
from raku_rag.workers.ingestion import IngestionJobMessage, IngestionRunStore  # noqa: E402
from raku_rag.workers.queue.sqs import SqsTaskQueue  # noqa: E402
from workers.ingest.provider_policy import (  # noqa: E402
    ProviderPolicy,
    ProviderPolicyEnforcer,
    ProviderRequest,
    capability_for,
)
from raku_rag.chatbot import ChatbotService  # noqa: E402
from raku_rag.persistence.phone_models import (  # noqa: E402
    InMemoryPhoneCallRepository,
    InMemoryPhoneQualityRepository,
    InMemoryPhoneScenarioRepository,
    PostgresPhoneCallRepository,
    PostgresPhoneQualityRepository,
    PostgresPhoneScenarioRepository,
)
from raku_rag.persistence.lexicon import (  # noqa: E402
    InMemoryLexiconRepository,
    PostgresLexiconRepository,
)
from raku_rag.persistence.feedback import (  # noqa: E402
    InMemoryFeedbackRepository,
    PostgresFeedbackRepository,
)
from raku_rag.persistence.telemetry import (  # noqa: E402
    InMemoryQueryTraceReader,
    PostgresQueryTraceReader,
)
from raku_rag.services.lexicon import LexiconError, LexiconService  # noqa: E402
from raku_rag.persistence.uploads import (  # noqa: E402
    InMemoryUploadRecordRepository,
    PostgresUploadRecordRepository,
    build_upload_record,
)
from raku_rag.phone import PhoneCallService, PhoneScenarioService  # noqa: E402
from raku_rag.phone.quality import PhoneQualityService  # noqa: E402
from raku_rag.phone.interfaces import CallableAnswerGateway  # noqa: E402
from raku_rag.providers.asr import DeterministicAsrProvider  # noqa: E402
from raku_rag.providers.telephony import DeterministicCallSimulator  # noqa: E402
from raku_rag.providers.tts import DeterministicTtsProvider  # noqa: E402

_LOCAL_DEMO_HOSTS = {"localhost", "127.0.0.1", "::1"}
_LOCAL_DEMO_DBS = {"raku", "raku_demo", "raku_parity"}
_DEFAULT_MAX_UPLOAD_OBJECT_BYTES = 25 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _AdminSettingsStore:
    """Tenant-scoped admin settings boundary used by the product facade.

    Provider/Retrieval/Logging policy migrations are still separate work; this store gives the API a
    stable contract now while reflecting ACL grants and tenant budgets into the existing core services.
    """

    _id_fields = {
        "datasources": "source_id",
        "query-profiles": "profile_id",
        "provider-policies": "provider_policy_id",
        "retrieval-profiles": "retrieval_profile_id",
        "logging-policies": "logging_policy_id",
    }
    _event_types = {
        "datasources": "data_source_changed",
        "query-profiles": "query_profile_changed",
        "provider-policies": "provider_policy_changed",
        "retrieval-profiles": "retrieval_profile_changed",
        "logging-policies": "logging_policy_changed",
    }
    _parser_policy_keys = {
        "parser_mode",
        "allowed_parser_providers",
        "allowed_ocr_providers",
        "allowed_layout_providers",
        "allowed_structured_providers",
        "allowed_vlm_providers",
        "allowed_caption_providers",
        "allowed_llm_providers",
        "allowed_embedding_providers",
        "allowed_visual_embedding_providers",
        "allowed_rerank_providers",
        "fallback_policy",
    }
    _residency_policy_keys = {
        "allowed_regions",
        "provider_regions",
        "data_residency_requirement",
        "cross_cloud_processing_allowed",
    }
    _opt_in_policy_keys = {
        "customer_opt_in_required",
        "customer_opt_in_status",
        "opt_in_status_by_family",
    }
    _model_policy_keys = {"embedding_provider", "llm_provider", "llm_model"}

    def __init__(
        self,
        system: ProductionSystem,
        *,
        datasource_repo: object | None = None,
        provider_policy_repo: object | None = None,
    ) -> None:
        self._system = system
        self._datasource_repo = datasource_repo
        self._provider_policy_repo = provider_policy_repo or getattr(
            system, "provider_policies", None
        )
        self._items: dict[str, dict[str, dict[str, dict]]] = {name: {} for name in self._id_fields}
        self._acl: dict[str, dict[str, dict]] = {}
        self._budgets: dict[str, dict[str, dict]] = {}
        self._provider_config_audit = ProviderConfigAuditRepository()

    def _bucket(self, resource: str, tenant_id: str) -> dict[str, dict]:
        return self._items[resource].setdefault(tenant_id, {})

    def _audit_snapshot(self, item: dict | None) -> dict:
        if not item:
            return {}
        return {
            key: value
            for key, value in item.items()
            if key not in {"audit_events", "provider_config_audit_event_id"}
        }

    def _event_type_for(self, resource: str, body: dict) -> str:
        touched = set(body)
        if resource == "provider-policies":
            if touched & self._parser_policy_keys:
                return "parser_provider_changed"
            if touched & self._residency_policy_keys:
                return "residency_override"
            if touched & self._opt_in_policy_keys:
                return "opt_in_changed"
        if resource == "query-profiles" and touched & self._model_policy_keys:
            return "model_changed"
        return self._event_types.get(resource, "provider_policy_changed")

    def _audit_event(
        self,
        tenant_id: str,
        resource: str,
        item_id: str,
        body: dict,
        actor: str,
        *,
        before: dict,
        after: dict,
    ) -> dict:
        event = self._provider_config_audit.record_change(
            tenant_id=tenant_id,
            event_type=self._event_type_for(resource, body),
            actor=actor,
            before=before,
            after=after,
            reason=str(body.get("reason") or ""),
            approval_ref=str(body.get("approval_ref") or ""),
            collection_id=after.get("collection_id") or before.get("collection_id"),
            correlation_id=item_id,
        )
        return event.to_dict()

    def _lifecycle(self) -> dict:
        return {
            "profile_version": 1,
            "schema_version": 1,
            "effective_from": None,
            "deprecated_at": None,
        }

    def _default_query_profile(self, tenant_id: str, profile_id: str) -> dict:
        return {
            "profile_id": profile_id,
            "tenant_id": tenant_id,
            "collection_id": None,
            "score_threshold": 0.1,
            "top_k": 5,
            "minimum_evidence_count": 1,
            "rerank_enabled": True,
            "rerank_top_n": 20,
            "retrieval_profile_id": "default",
            "max_context_tokens": 8000,
            "max_context_chunks": 8,
            "max_synchronous_llm_calls": 1,
            "query_rewrite_enabled": False,
            "self_eval_enabled": True,
            "self_eval_criteria": [],
            "embedding_provider": "hashing-local",
            "llm_provider": "extractive-local",
            "llm_model": "extractive-mvp",
            "captioning_enabled": False,
            "captioning_budget_limit": None,
            **self._lifecycle(),
        }

    def _default_provider_policy(self, tenant_id: str, policy_id: str) -> dict:
        return {
            "provider_policy_id": policy_id,
            "tenant_id": tenant_id,
            "collection_id": None,
            "name": "Default provider policy",
            "status": "active",
            "parser_mode": "aws_only",
            "allowed_parser_providers": ["aws_textract", "tesseract"],
            "allowed_ocr_providers": ["aws_textract", "tesseract"],
            "allowed_layout_providers": ["aws_textract", "tesseract"],
            "allowed_structured_providers": ["aws_textract", "customer_managed"],
            "allowed_llm_providers": ["bedrock", "customer_managed"],
            "allowed_embedding_providers": ["bedrock", "customer_managed"],
            "allowed_visual_embedding_providers": ["bedrock", "customer_managed"],
            "allowed_vlm_providers": ["bedrock", "customer_managed"],
            "allowed_caption_providers": ["bedrock", "customer_managed"],
            "allowed_rerank_providers": ["bedrock", "customer_managed"],
            "allowed_regions": [],
            "provider_regions": {},
            "data_residency_requirement": "single_region",
            "cross_cloud_processing_allowed": False,
            "zero_retention_required": True,
            "no_train_required": True,
            "customer_opt_in_required": True,
            "customer_opt_in_status": "pending",
            "opt_in_status_by_family": {},
            "provider_contract_refs": [],
            "provider_capability_snapshot": {},
            "fallback_policy": {
                "parse": {"provider": "aws_textract"},
                "ocr": {"provider": "aws_textract"},
                "embed": {"provider": "bedrock"},
                "rerank": {"provider": "bedrock"},
                "llm": {"provider": "bedrock"},
            },
            "audit_events": [],
            **self._lifecycle(),
        }

    def _default_retrieval_profile(self, tenant_id: str, profile_id: str) -> dict:
        return {
            "retrieval_profile_id": profile_id,
            "tenant_id": tenant_id,
            "collection_id": None,
            "name": "Default retrieval profile",
            "version": 1,
            "status": "active",
            "metadata_filter_required": True,
            "identifier_match_enabled": True,
            "identifier_fields": [],
            "keyword_match_enabled": True,
            "keyword_strategy": "postgres_fts",
            "vector_search_enabled": True,
            "vector_top_k": 50,
            "vector_score_threshold": 0.1,
            "rerank_enabled": True,
            "rerank_provider": "score_order",
            "rerank_model": "score-order-mvp",
            "rerank_candidate_limit": 20,
            "final_context_limit": 8,
            "exact_candidate_limit": 20,
            "max_context_tokens": 8000,
            "hybrid_candidate_limit": 50,
            "minimum_evidence_count": 1,
            "fallback_behavior": "insufficient_evidence",
            **self._lifecycle(),
        }

    def _default_logging_policy(self, tenant_id: str, policy_id: str) -> dict:
        return {
            "logging_policy_id": policy_id,
            "tenant_id": tenant_id,
            "collection_id": None,
            "name": "Default logging policy",
            "status": "active",
            "raw_user_query_storage": "disabled",
            "raw_retrieved_context_storage": "disabled",
            "model_input_storage": "disabled",
            "model_output_storage": "disabled",
            "store_citation_ids": True,
            "store_chunk_ids": True,
            "store_prompt_template_version": True,
            "store_model_metadata": True,
            "store_latency": True,
            "store_cost": True,
            "production_sampling_rate": 1.0,
            "high_risk_trace_policy": "metadata_only",
            "pii_redaction_policy_ref": "",
            "secret_redaction_policy_ref": "",
            "retention_policy_ref": "",
            **self._lifecycle(),
        }

    def _default_for(self, tenant_id: str, resource: str, item_id: str) -> dict | None:
        if item_id != "default":
            return None
        if resource == "query-profiles":
            return self._default_query_profile(tenant_id, item_id)
        if resource == "provider-policies":
            return self._default_provider_policy(tenant_id, item_id)
        if resource == "retrieval-profiles":
            return self._default_retrieval_profile(tenant_id, item_id)
        if resource == "logging-policies":
            return self._default_logging_policy(tenant_id, item_id)
        return None

    def _ensure_default(self, tenant_id: str, resource: str) -> None:
        default = self._default_for(tenant_id, resource, "default")
        if default:
            self._bucket(resource, tenant_id).setdefault("default", default)

    def list_resource(
        self, tenant_id: str, resource: str, *, collection_id: str = ""
    ) -> list[dict]:
        if resource == "datasources" and self._datasource_repo is not None:
            return self._datasource_repo.list(tenant_id, collection_id=collection_id)
        if resource == "provider-policies" and hasattr(self._provider_policy_repo, "list_mappings"):
            items = self._provider_policy_repo.list_mappings(tenant_id, collection_id)
            if items:
                return [copy.deepcopy(item) for item in items]
        self._ensure_default(tenant_id, resource)
        items = list(self._bucket(resource, tenant_id).values())
        if collection_id:
            items = [item for item in items if item.get("collection_id") == collection_id]
        return [copy.deepcopy(item) for item in items]

    def get_resource(self, tenant_id: str, resource: str, item_id: str) -> dict | None:
        if resource == "datasources" and self._datasource_repo is not None:
            return self._datasource_repo.get(tenant_id, item_id)
        if resource == "provider-policies" and hasattr(self._provider_policy_repo, "get_mapping"):
            item = self._provider_policy_repo.get_mapping(tenant_id, "", item_id)
            if item is not None:
                return copy.deepcopy(item)
        self._ensure_default(tenant_id, resource)
        item = self._bucket(resource, tenant_id).get(item_id)
        return copy.deepcopy(item) if item else None

    def upsert_resource(
        self, tenant_id: str, resource: str, item_id: str, body: dict, *, actor: str
    ) -> dict:
        id_field = self._id_fields[resource]
        if resource == "datasources" and self._datasource_repo is not None:
            existing = self._datasource_repo.get(tenant_id, item_id)
            before = self._audit_snapshot(existing)
            item = self._datasource_repo.upsert(tenant_id, item_id, body, actor=actor)
            after = self._audit_snapshot(item)
            event = self._audit_event(
                tenant_id, resource, item_id, body, actor, before=before, after=after
            )
            result = copy.deepcopy(item)
            result["audit_events"] = [event]
            result["provider_config_audit_event_id"] = event["provider_config_audit_event_id"]
            return result
        existing = self.get_resource(tenant_id, resource, item_id)
        before = self._audit_snapshot(existing)
        item = (
            existing
            or self._default_for(tenant_id, resource, item_id)
            or {
                id_field: item_id,
                "tenant_id": tenant_id,
                "status": "active",
                **self._lifecycle(),
            }
        )
        clean = {
            k: v
            for k, v in body.items()
            if k not in {"tenant_id", id_field, "reason", "audit_events"}
        }
        item.update(clean)
        item[id_field] = item_id
        item["tenant_id"] = tenant_id
        item["updated_at"] = _now()
        if "status" not in item:
            item["status"] = "active"
        if resource == "datasources":
            item.setdefault("config", {})
            item.setdefault("collection_id", clean.get("collection_id") or "default")
            item.setdefault("type", clean.get("type") or "upload")
        if resource == "logging-policies" and "raw_retrieved_context_storage" not in clean:
            item.setdefault("raw_retrieved_context_storage", "disabled")
        if resource == "retrieval-profiles":
            item["version"] = int(item.get("version") or 1) + (1 if existing else 0)
        if resource == "provider-policies" and hasattr(self._provider_policy_repo, "upsert"):
            persisted = self._provider_policy_repo.upsert(tenant_id, item_id, item)
            item.update(persisted)

        after = self._audit_snapshot(item)
        event = self._audit_event(
            tenant_id, resource, item_id, body, actor, before=before, after=after
        )
        item.setdefault("audit_events", []).append(event)
        self._bucket(resource, tenant_id)[item_id] = item
        result = copy.deepcopy(item)
        result["provider_config_audit_event_id"] = event["provider_config_audit_event_id"]
        return result

    def list_audit_events(
        self,
        tenant_id: str,
        *,
        event_type: str = "",
        correlation_id: str = "",
        collection_id: str = "",
    ) -> list[dict]:
        return [
            event.to_dict()
            for event in self._provider_config_audit.list_events(
                tenant_id,
                event_type=event_type,
                correlation_id=correlation_id,
                collection_id=collection_id,
            )
        ]

    def validate_provider_policy(self, tenant_id: str, policy_id: str, body: dict) -> dict:
        policy = self.get_resource(tenant_id, "provider-policies", policy_id)
        if policy is None:
            return {"allowed": False, "reasons": ["provider policy not found"]}
        operation = str(body.get("operation") or "")
        provider = str(body.get("provider") or self._default_provider_for_operation(operation))
        capability_override = (
            body.get("capability") if isinstance(body.get("capability"), dict) else None
        )
        decision = ProviderPolicyEnforcer().evaluate(
            ProviderPolicy.from_mapping(policy),
            ProviderRequest(
                operation=operation,
                provider=provider,
                capability=capability_for(provider, capability_override),
            ),
        )
        return decision.to_dict()

    def _default_provider_for_operation(self, operation: str) -> str:
        if operation in {"parse", "ocr", "layout", "structured"}:
            return "aws_textract"
        if operation in {
            "embed",
            "embedding",
            "visual_embedding",
            "rerank",
            "llm",
            "vlm",
            "caption",
        }:
            return "bedrock"
        return "customer_managed"

    def benchmark_retrieval_profile(self, tenant_id: str, profile_id: str, body: dict) -> dict:
        digest = hashlib.sha256(
            json.dumps([tenant_id, profile_id, body], sort_keys=True).encode()
        ).hexdigest()[:12]
        evaluation_run_id = f"eval_{digest}"
        return {
            "evaluation_run_id": evaluation_run_id,
            "status_url": f"/v1/evaluations/runs/{evaluation_run_id}",
        }

    def acl(self, tenant_id: str) -> dict:
        return {"grants": list(self._acl.setdefault(tenant_id, {}).values())}

    def update_acl(self, tenant_id: str, body: dict, *, actor: str) -> dict:
        grants = self._acl.setdefault(tenant_id, {})
        before = {"grants": list(grants.values())}
        for grant_id in body.get("revoke_grant_ids") or []:
            grants.pop(str(grant_id), None)
        for raw in body.get("grants") or []:
            scope_type = str(raw["scope_type"])
            scope_id = str(raw["scope_id"])
            subject_type = str(raw["subject_type"])
            subject_id = str(raw["subject_id"])
            grant_id = str(
                raw.get("grant_id")
                or f"{tenant_id}:{scope_type}:{scope_id}:{subject_type}:{subject_id}"
            )
            grant = {
                "grant_id": grant_id,
                "tenant_id": tenant_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "permission": "read",
                "created_at": _now(),
            }
            grants[grant_id] = grant
            self._system.acl.add(
                ACLGrant(
                    tenant_id=tenant_id,
                    scope_type=ScopeType(scope_type),
                    scope_id=scope_id,
                    subject_type=SubjectType(subject_type),
                    subject_id=subject_id,
                )
            )
        event = self._provider_config_audit.record_change(
            tenant_id=tenant_id,
            event_type="acl_changed",
            actor=actor,
            before=before,
            after={"grants": list(grants.values())},
            reason=str(body.get("reason") or ""),
            correlation_id="acl",
        ).to_dict()
        return {
            "grants": list(grants.values()),
            "provider_config_audit_event_id": event["provider_config_audit_event_id"],
        }

    def budgets(self, tenant_id: str, *, scope_type: str = "", scope_id: str = "") -> list[dict]:
        budgets = list(self._budgets.setdefault(tenant_id, {}).values())
        if scope_type:
            budgets = [budget for budget in budgets if budget.get("scope_type") == scope_type]
        if scope_id:
            budgets = [budget for budget in budgets if budget.get("scope_id") == scope_id]
        return budgets

    def update_budgets(self, tenant_id: str, body: dict, *, actor: str) -> dict:
        budgets = self._budgets.setdefault(tenant_id, {})
        before = {"budgets": list(budgets.values())}
        for raw in body.get("budgets") or []:
            scope_type = str(raw["scope_type"])
            scope_id = str(raw.get("scope_id") or tenant_id)
            budget_id = str(raw.get("budget_id") or f"{scope_type}:{scope_id}")
            limit = raw.get("limit")
            budget = {
                "budget_id": budget_id,
                "tenant_id": tenant_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "limit": limit,
                "spent": 0,
                "currency": raw.get("currency") or "USD",
                "period": raw.get("period") or "monthly",
                "status": raw.get("status") or "active",
                "updated_at": _now(),
            }
            budgets[budget_id] = budget
            if scope_type == "tenant" and scope_id == tenant_id:
                self._system.cost.set_budget(tenant_id, float(limit) if limit is not None else None)
        event = self._provider_config_audit.record_change(
            tenant_id=tenant_id,
            event_type="budget_changed",
            actor=actor,
            before=before,
            after={"budgets": list(budgets.values())},
            reason=str(body.get("reason") or ""),
            correlation_id="budgets",
        ).to_dict()
        return {
            "budgets": list(budgets.values()),
            "provider_config_audit_event_id": event["provider_config_audit_event_id"],
        }


class _EvalFeedbackStore:
    def __init__(
        self, system: ProductionSystem, run_repository=None, feedback_repository=None
    ) -> None:
        self._system = system
        self._sets: dict[tuple[str, str], EvaluationSet] = {}
        self._runs: dict[tuple[str, str], dict] = {}
        # P2-9: eval runs are persisted via a repository so results are trendable across releases.
        # Default in-memory; production wires PostgresEvaluationRunRepository(system._conn) once
        # migration 0007 is applied (the durable, RLS-scoped evaluation_runs table).
        self._runs_repo = run_repository or InMemoryEvaluationRunRepository()
        # ★G3a: user 👍/👎 feedback persists via a repository so the admin improvement queue is
        # server-driven and survives restarts. Default in-memory; production wires
        # PostgresFeedbackRepository(system._conn) once migration 0023 is applied (the durable,
        # RLS-scoped answer_feedback table).
        self._feedback_repo = feedback_repository or InMemoryFeedbackRepository()

    def create_set(self, tenant_id: str, body: dict) -> dict:
        eval_set = EvaluationSet.register(tenant_id=tenant_id, items=body.get("items") or ())
        self._sets[(tenant_id, eval_set.eval_set_id)] = eval_set
        return {
            "eval_set_id": eval_set.eval_set_id,
            "dataset_version": eval_set.dataset_version,
            "item_count": len(eval_set.items),
            "status": "created",
        }

    def create_run(self, tenant_id: str, body: dict, principal: IdentityClaims) -> dict:
        eval_set_id = str(body.get("eval_set_id") or "")
        eval_set = self._sets.get((tenant_id, eval_set_id))
        if eval_set is None:
            raise KeyError("eval_set_id")
        run = EvaluationRunner(self._system, run_repository=self._runs_repo).run(
            eval_set,
            principal=principal,
            collection_id=str(body.get("collection_id") or "") or None,
            baseline=bool(body.get("baseline") or False),
        )
        payload = run.to_dict()
        self._runs[(tenant_id, run.run_id)] = payload
        return {"run_id": run.run_id, "status_url": f"/v1/evaluations/runs/{run.run_id}"}

    def get_run(self, tenant_id: str, run_id: str) -> dict | None:
        # Read from the durable repository first (trendable across releases); fall back to the cache.
        stored = self._runs_repo.get(tenant_id, run_id)
        if stored is not None:
            return stored.to_dict()
        return self._runs.get((tenant_id, run_id))

    def list_runs(self, tenant_id: str, eval_set_id: str | None = None) -> list[dict]:
        return [run.to_dict() for run in self._runs_repo.list_runs(tenant_id, eval_set_id)]

    def create_feedback(self, tenant_id: str, body: dict, actor: str) -> dict:
        record = self._feedback_repo.create(
            tenant_id,
            actor_id=actor,
            answer_id=str(body.get("answer_id") or ""),
            evaluation_run_id=str(body.get("evaluation_run_id") or ""),
            subject=str(body.get("subject") or "user"),
            score=int(body.get("rating") or 0),
            comment=str(body.get("comment") or ""),
            reason_code=str(body.get("reason_code") or ""),
            citation_id=str(body.get("citation_id") or "") or None,
        )
        return {"feedback_id": record["feedback_id"], "status": "accepted"}

    def list_feedback(
        self, tenant_id: str, *, limit: int = 100, offset: int = 0, rating: str = ""
    ) -> list[dict]:
        return self._feedback_repo.list(
            tenant_id, limit=limit, offset=offset, rating_filter=rating or None
        )


def seed(system: ProductionSystem) -> None:
    """Seed a small demo tenant so the vertical slice is touchable end-to-end."""
    docs = {
        "m1": "The maintenance interval for pump P-12 is ninety days per the equipment manual.",
        "m2": "Alarm E-152 on the press indicates a hydraulic pressure fault: stop the line and "
        "check the accumulator before restarting.",
        "m3": "The torque specification for the M8 cover bolt on the conveyor is twelve newton metres.",
    }
    for doc_id, text in docs.items():
        system.ingest_text(tenant_id="demo", collection_id="manuals", document_id=doc_id, text=text)
    system.grant("demo", ScopeType.COLLECTION, "manuals", SubjectType.USER, "alice")


def _assert_demo_reset_allowed(dsn: str) -> None:
    """Guard the destructive demo reset; --seed alone is non-destructive."""
    parsed = urlparse(dsn)
    dbname = unquote((parsed.path or "").lstrip("/"))
    host = parsed.hostname or ""
    if host in _LOCAL_DEMO_HOSTS and dbname in _LOCAL_DEMO_DBS:
        return
    if os.environ.get("RAKU_ALLOW_DEMO_DB_RESET") == "1":
        return
    raise SystemExit(
        "Refusing to reset a non-local demo database. Use --seed without --reset-demo-db, "
        "or set RAKU_ALLOW_DEMO_DB_RESET=1 only in a disposable environment."
    )


# P4-4 / AF-9 — shared-secret gate for the internal API boundary. The answer-service used to blindly
# trust the loopback request + its x-raku-* identity headers. When RAKU_INTERNAL_AUTH_SECRET is configured
# (production), every /internal/* request must carry a matching X-Internal-Auth header (constant-time
# compare); /healthz stays public. When the secret is UNSET (local dev / tests) the gate is a no-op so
# nothing regresses. (Full mTLS on the deployed API<->answer-service hop is the deployment-topology half.)
_INTERNAL_AUTH_SECRET = os.environ.get("RAKU_INTERNAL_AUTH_SECRET", "")


def internal_auth_ok(secret: str, path: str, presented: str) -> bool:
    """Pure decision for the internal-boundary shared-secret gate (unit-testable offline)."""
    if not secret:
        return True  # dev/test no-op: backward compatible
    if path == "/healthz":
        return True  # health is public
    return hmac.compare_digest(presented or "", secret)


def _claims(body: dict) -> IdentityClaims:
    return IdentityClaims(
        tenant_id=str(body["tenant_id"]),
        user_id=str(body["user_id"]),
        groups=tuple(body.get("groups") or ()),
        roles=tuple(body.get("roles") or ()),
    )


def _claims_from_headers(headers) -> IdentityClaims:
    return IdentityClaims(
        tenant_id=str(headers["x-raku-tenant-id"]),
        user_id=str(headers.get("x-raku-user-id") or "unknown"),
        groups=tuple(json.loads(headers.get("x-raku-groups") or "[]")),
        roles=tuple(json.loads(headers.get("x-raku-roles") or "[]")),
    )


def _jsonable(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _query_time_range(qs: dict[str, list[str]]) -> tuple[str, str] | None:
    start = (qs.get("from") or [""])[0]
    end = (qs.get("to") or [""])[0]
    return (start, end) if start and end else None


def _qs_int(qs: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return max(0, int((qs.get(key) or [str(default)])[0]))
    except ValueError:
        return default


def _citation_json(c, *, include_approval: bool = False) -> dict:
    item = {
        "kind": c.kind,
        "document_id": c.document_id,
        "chunk_id": c.chunk_id,
        "source_id": c.source_id,
        "version": c.version,
        "text_range": list(c.text_range) if getattr(c, "text_range", None) else None,
        "retrieval_score": c.retrieval_score,
        "asset_id": getattr(c, "asset_id", "") or None,
        "page_number": getattr(c, "page_number", 0) or None,
        "region_id": getattr(c, "region_id", "") or None,
        "bbox": _jsonable(getattr(c, "bbox", None)),
        "sheet_name": getattr(c, "sheet_name", "") or None,
        "cell_range": getattr(c, "cell_range", "") or None,
        "row_id": getattr(c, "row_id", "") or None,
        "table_id": getattr(c, "table_id", "") or None,
        "form_id": getattr(c, "form_id", "") or None,
        "field_name": getattr(c, "field_name", "") or None,
        "chart_id": getattr(c, "chart_id", "") or None,
        "series_name": getattr(c, "series_name", "") or None,
        "point_index": (
            getattr(c, "point_index", -1) if getattr(c, "point_index", -1) >= 0 else None
        ),
        "column_name": getattr(c, "column_name", "") or None,
        "pixel_derived": bool(getattr(c, "pixel_derived", False)),
        "visual_evidence_verified": bool(getattr(c, "visual_evidence_verified", False)),
        "visual_verifier_verdicts": _jsonable(getattr(c, "visual_verifier_verdicts", ())),
    }
    if include_approval:
        item.update(
            {
                "approval_status": getattr(c, "approval_status", None),
                "effective_date": getattr(c, "effective_date", None),
                "approval_source": getattr(c, "approval_source", None),
                # ★G4 freshness trust signal (display-only; derived by the overlay, never a gate).
                "last_verified_at": getattr(c, "last_verified_at", None) or None,
                "review_overdue": bool(getattr(c, "review_overdue", False)),
            }
        )
    return item


def _answer_json(ans) -> dict:
    return {
        "status": ans.status,
        "text": ans.text,
        **answer_format_metadata(ans),
        "citations": [_citation_json(c) for c in ans.citations],
        "used_chunks": [
            {"chunk_id": cid, "document_id": cid.split(":")[0], "retrieval_score": 0.0}
            for cid in ans.used_chunks
        ],
        "confidence": ans.confidence,
        "route": getattr(ans, "route", "rag"),
        "freshness": (
            {
                "indexed_at": ans.freshness[0].indexed_at,
                "document_version": ans.freshness[0].document_version,
                "source_freshness": ans.freshness[0].source_freshness,
            }
            if ans.freshness
            else None
        ),
        "correlation_id": ans.correlation_id,
    }


def _manufacturing_answer_json(ans) -> dict:
    """Serialize a ManufacturingAnswer: base answer fields + the safety extension nested under
    ``manufacturing`` (P1-1 deployment exposure; GAP-M02 nesting). Citations carry approval provenance.
    """
    return {
        "status": ans.status,
        "text": ans.text,
        **answer_format_metadata(ans),
        "confidence": ans.confidence,
        "citations": [_citation_json(c, include_approval=True) for c in ans.citations],
        "used_chunks": list(ans.used_chunks),
        "correlation_id": ans.correlation_id,
        "manufacturing": {
            "high_risk": ans.high_risk,
            "high_risk_reason_codes": list(ans.high_risk_reason_codes),
            "safety_block_reason": ans.safety_block_reason,
            "obsolete_warning": ans.obsolete_warning,
            "requires_onsite_confirmation": ans.requires_onsite_confirmation,
            "notice": ans.notice,
        },
    }


def _data_use_policy_json(policy) -> dict:
    return {
        "tenant_id": policy.tenant_id,
        "no_train_default": policy.no_train_default,
        "training_opt_in": policy.training_opt_in,
        "opt_in_contract_ref": policy.opt_in_contract_ref,
        "provider_no_train_required": policy.provider_no_train_required,
        "no_train_fallback": policy.no_train_fallback.value,
        "retention_customer": policy.retention_customer,
        "retention_audit": policy.retention_audit,
        "export_enabled": policy.export_enabled,
        "policy_version": policy.policy_version,
        "updated_by": policy.updated_by,
        "updated_at": policy.updated_at,
    }


def _search_json(
    system: ProductionSystem, principal: IdentityClaims, query: str, collection_id, top_k
) -> dict:
    digest = hashlib.sha256(f"{principal.tenant_id}:{query}".encode("utf-8")).hexdigest()[:12]
    correlation_id = f"trace_{digest}"
    results = system.search(principal, query, collection_id, correlation_id=correlation_id)
    if isinstance(top_k, int) and top_k > 0:
        results = results[:top_k]
    items = []
    for r in results:
        doc = system.registry.get(principal.tenant_id, r.chunk.document_id)
        items.append(
            {
                "source_id": doc.source_id if doc else "",
                "document_id": r.chunk.document_id,
                "chunk_id": r.chunk.chunk_id,
                "version": doc.version if doc else 0,
                "retrieval_score": r.retrieval_score,
                "heading_path": list(r.chunk.heading_path),
                "text": r.chunk.text,
                "freshness": {
                    "indexed_at": doc.indexed_at if doc else None,
                    "document_version": doc.version if doc else None,
                    "source_freshness": doc.updated_at if doc else None,
                },
            }
        )
    return {"results": items, "correlation_id": correlation_id}


def _dagster_run_url(run_id: str) -> str:
    base_url = os.environ.get("DAGSTER_BASE_URL", "").rstrip("/")
    if not base_url or not run_id:
        return ""
    return f"{base_url}/runs/{quote(run_id, safe='')}"


def _ingestion_run_json(run) -> dict:
    return {
        "ingestion_run_id": run.ingestion_run_id,
        "type": run.type,
        "trigger": run.trigger,
        "status": run.status,
        "tenant_id": run.tenant_id,
        "collection_id": run.collection_id,
        "source_id": run.source_id,
        "document_id": run.document_id,
        "document_ref": run.document_ref,
        "content_type": run.content_type,
        "sqs_message_id": run.sqs_message_id,
        "retry_count": run.retry_count,
        "chunk_count": run.chunk_count,
        "failure_reason": run.failure_reason,
        "dagster_run_id": run.dagster_run_id,
        "dagster_run_url": _dagster_run_url(run.dagster_run_id),
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "summary": {
            "observed_count": 1 if run.document_id else 0,
            "changed_count": 1 if run.status == "succeeded" else 0,
            "deleted_count": 0,
            "skipped_count": 0,
            "failed_count": 1 if run.status in {"failed", "dead_letter"} else 0,
        },
        "documents": (
            [
                {
                    "document_id": run.document_id,
                    "source_document_id": run.document_id,
                    "parse_status": run.status,
                    "chunk_status": run.status,
                    "embedding_status": run.status,
                    "index_status": run.status,
                    "last_indexed_at": run.finished_at,
                    "last_error": run.failure_reason,
                }
            ]
            if run.document_id
            else []
        ),
        "asset_materializations": [],
        "correlation_id": run.ingestion_run_id,
    }


def _processing_state_json(state) -> dict:
    return {
        "tenant_id": state.tenant_id,
        "collection_id": state.collection_id,
        "source_id": state.source_id,
        "document_id": state.document_id,
        "source_document_id": state.document_id,
        "ingestion_run_id": state.ingestion_run_id,
        "content_checksum": state.content_checksum,
        "parser_version": state.parser_version,
        "chunking_config_version": state.chunking_config_version,
        "embedding_model_version": state.embedding_model_version,
        "parse_status": state.status,
        "chunk_status": state.status,
        "embedding_status": state.status,
        "index_status": state.status,
        "chunk_count": state.chunk_count,
        "last_indexed_at": state.updated_at if state.status == "succeeded" else "",
        "last_error": state.failure_reason,
    }


def _source_sync_state_json(state) -> dict:
    return {
        "tenant_id": state.tenant_id,
        "source_id": state.source_id,
        "collection_id": state.collection_id,
        "status": state.status,
        "last_manifest_checksum": state.last_manifest_checksum,
        "last_ingestion_run_id": state.last_ingestion_run_id,
        "observed_count": state.observed_count,
        "changed_count": state.changed_count,
        "deleted_count": state.deleted_count,
        "skipped_count": state.skipped_count,
        "failed_count": state.failed_count,
        "freshness": {"last_successful_sync_at": state.last_synced_at},
        "last_error": "",
        "dagster_run_id": "",
        "dagster_run_url": "",
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _empty_datasource_document_counts() -> dict:
    return {
        "total": 0,
        "approved": 0,
        "pending_review": 0,
        "draft": 0,
        "obsolete": 0,
        "unknown": 0,
    }


def _safe_datasource_display_name(source: dict) -> str:
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    display_name = (
        config.get("display_name") or source.get("display_name") or source.get("source_id")
    )
    return str(display_name or "")


def _safe_datasource_source_type(source: dict) -> str:
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    source_type = config.get("source_type") or source.get("type") or "source"
    return str(source_type or "source")


def _safe_datasource_credential_status(source: dict) -> str:
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    status = source.get("credential_status") or config.get("credential_status")
    if status:
        return str(status)
    if config.get("credential_ref"):
        return "configured"
    return "missing"


def _datasource_sync_overview(
    runs: IngestionRunStore, tenant_id: str, source_id: str
) -> dict | None:
    state = runs.source_sync_state(tenant_id, source_id)
    if state is None:
        return None
    return {
        "status": state.status,
        "summary": {
            "observed_count": state.observed_count,
            "changed_count": state.changed_count,
            "deleted_count": state.deleted_count,
            "skipped_count": state.skipped_count,
            "failed_count": state.failed_count,
        },
        "freshness": {"last_successful_sync_at": state.last_synced_at},
        "last_ingestion_run_id": state.last_ingestion_run_id,
    }


def _datasource_overview_rows(
    sources: list[dict],
    documents: list[dict],
    runs: IngestionRunStore,
    tenant_id: str,
) -> list[dict]:
    counts_by_source: dict[str, dict] = {}
    for doc in documents:
        source_id = str(doc.get("source_id") or "")
        if not source_id:
            continue
        counts = counts_by_source.setdefault(source_id, _empty_datasource_document_counts())
        counts["total"] += 1
        approval_status = str(doc.get("approval_status") or "unknown")
        if approval_status in {"approved", "pending_review", "draft", "obsolete"}:
            counts[approval_status] += 1
        else:
            counts["unknown"] += 1

    rows: list[dict] = []
    for source in sources:
        source_id = str(source.get("source_id") or "")
        config = source.get("config") if isinstance(source.get("config"), dict) else {}
        rows.append(
            {
                "source_id": source_id,
                "tenant_id": str(source.get("tenant_id") or tenant_id),
                "collection_id": str(source.get("collection_id") or ""),
                "type": source.get("type"),
                "status": source.get("status") or "draft",
                "display_name": _safe_datasource_display_name(source),
                "source_type": _safe_datasource_source_type(source),
                "credential_status": _safe_datasource_credential_status(source),
                "approval_policy": config.get("approval_policy"),
                "approval_effective_date": config.get("approval_effective_date"),
                "sync_schedule": source.get("sync_schedule"),
                "last_synced_at": source.get("last_synced_at"),
                "sync": _datasource_sync_overview(runs, tenant_id, source_id),
                "document_counts": dict(
                    counts_by_source.get(source_id, _empty_datasource_document_counts())
                ),
            }
        )
    return rows


def _manufacturing_source_sync_status_json(
    runs: IngestionRunStore, tenant_id: str, source_id: str
) -> dict:
    projection = runs.source_sync_status(tenant_id, source_id)
    if projection is None:
        return {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "status": "not_found",
            "summary": {},
            "documents": [],
            "asset_materializations": [],
        }
    payload = projection.to_dict()
    payload.pop("dagster_run_id", None)
    payload.pop("dagster_run_url", None)
    for document in payload.get("documents", []):
        document.pop("dagster_run_id", None)
        document["status"] = (
            document.get("index_status")
            or document.get("embedding_status")
            or document.get("chunk_status")
            or document.get("parse_status")
            or "unknown"
        )
    payload["manufacturing_metadata"] = {
        "approval_metadata_checksum_observed": True,
        "metadata_only_updates_supported": True,
        "dagster_run_fields_internal_only": True,
    }
    return payload


def _ingest_response_json(job) -> dict:
    return {
        "ingestion_run_id": job.ingestion_run_id,
        "document_id": job.document_id,
        "status": job.status,
        "status_url": f"/v1/admin/ingestion-runs/{job.ingestion_run_id}",
        "sqs_message_id": getattr(job, "sqs_message_id", ""),
        "failure_reason": job.failure_reason,
        "chunk_count": job.chunk_count,
    }


def _sync_datasource_to_ingest(
    system: ProductionSystem,
    tenant_id: str,
    source_id: str,
    datasource: dict,
    body: dict,
) -> dict:
    documents = build_sync_documents(source_id, datasource, body=body)
    if not documents:
        raise ValueError("datasource did not produce any documents")
    collection_id = str(body.get("collection_id") or datasource.get("collection_id") or "manuals")
    applied_approval_status = _approval_from_datasource_policy(datasource)[0]
    runs: list[dict] = []
    for document in documents:
        mfg_meta = _mfg_metadata_for_sync(body, datasource, tenant_id, document.document_id)
        run = system.ingest_document(
            tenant_id=tenant_id,
            collection_id=collection_id,
            source_id=source_id,
            document_id=document.document_id,
            document_ref=document.document_ref,
            raw=document.raw,
            content_type=document.content_type,
            manufacturing_metadata=mfg_meta,
        )
        runs.append(_ingest_response_json(run))

    failed = [run for run in runs if run.get("status") == "failed"]
    if len(failed) == len(runs):
        status = "failed"
    elif failed:
        status = "partially_succeeded"
    else:
        status = "succeeded"
    first = runs[0]
    return {
        "source_id": source_id,
        "collection_id": collection_id,
        "status": status,
        "ingestion_run_id": first["ingestion_run_id"],
        "status_url": first["status_url"],
        "observed_count": len(documents),
        "changed_count": len(runs),
        "failed_count": len(failed),
        # Which trust policy the saved datasource applied to EVERY synced file (Step 0/1): a
        # 'review_required' source lands its files in pending_review for the human review queue; a
        # 'trusted' source stamps them approved (source-of-truth) so they are immediately citable.
        "approval_policy": _datasource_approval_policy(datasource),
        "applied_approval_status": applied_approval_status,
        "runs": runs,
    }


def _oauth_google_callback(
    tenant_id: str,
    body: dict,
    *,
    secret_store,
    oauth_connections,
    env=None,
    fetch_url=None,
) -> dict:
    """Exchange a Google auth code for tokens, persist the refresh token, record a connection.

    tenant_id is the authenticated header identity (never the body). Returns
    {connection_id, refresh_token_stored}. Raises ValueError (missing code),
    OAuthConfigError (no client creds) or OAuthExchangeError (Google rejected / no refresh token).
    """
    code = str(body.get("code") or "")
    redirect_uri = str(body.get("redirect_uri") or "")
    if not code:
        raise ValueError("missing field: code")
    connection = build_connection(tenant_id=tenant_id, source_id="", provider="google_drive")
    kwargs = {}
    if env is not None:
        kwargs["env"] = env
    if fetch_url is not None:
        kwargs["fetch_url"] = fetch_url
    result = oauth_token_resolver.exchange_code(
        code,
        redirect_uri,
        secret_store=secret_store,
        tenant_id=tenant_id,
        secret_ref=connection.refresh_token_secret_ref,
        **kwargs,
    )
    stored = oauth_connections.upsert(replace(connection, scope=str(result.get("scope") or "")))
    return {
        "connection_id": stored.connection_id,
        "refresh_token_stored": bool(result.get("refresh_token_stored")),
    }


def _inject_gdrive_access_token(
    tenant_id: str,
    source_id: str,
    datasource: dict,
    body: dict,
    *,
    secret_store,
    oauth_connections,
    env=None,
    fetch_url=None,
) -> None:
    """For a google_drive datasource, mint a FRESH access token from the stored refresh token and
    inject it into ``body['fresh_access_token']``. No-op for any other source type. A stale token in
    the config is never used. Raises ValueError when no connection exists (reconnect required) or
    RefreshTokenExpiredError/OAuthConfigError on refresh failure."""
    cfg = datasource.get("config") or {}
    src_type = str(cfg.get("source_type") or datasource.get("type") or "").lower()
    if src_type != "google_drive":
        return
    conn_id = str(cfg.get("connection_id") or "")
    connection = (
        oauth_connections.get(tenant_id, conn_id)
        if conn_id
        else oauth_connections.get_by_source(tenant_id, source_id)
    )
    if connection is None:
        raise ValueError("google_drive datasource is not connected (reconnect required)")
    kwargs = {}
    if env is not None:
        kwargs["env"] = env
    if fetch_url is not None:
        kwargs["fetch_url"] = fetch_url
    body["fresh_access_token"] = oauth_token_resolver.resolve_fresh_access_token(
        connection, secret_store, **kwargs
    )


def _mfg_raw_from_body(body: dict) -> dict | None:
    """The raw manufacturing-metadata mapping carried by an ingest request, or None if absent.

    Accepts either a single ``manufacturing`` object (the to_mapping()/from_mapping() shape) or the
    contract's split ``manufacturing_metadata`` + ``approval`` blocks (mfg-openapi.md). Does NOT inject
    tenant_id/document_id — those are the caller's (authenticated) responsibility.
    """
    raw = body.get("manufacturing")
    if raw is None:
        meta_block = body.get("manufacturing_metadata") or {}
        approval_block = body.get("approval") or {}
        if not meta_block and not approval_block:
            return None
        raw = {**meta_block, **approval_block}
        # contract alias: document_type -> document_kind (data-model §B)
        if "document_type" in raw and "document_kind" not in raw:
            raw["document_kind"] = raw.pop("document_type")
    if not isinstance(raw, dict):
        return None
    return raw


def _mfg_metadata_from_body(body: dict, tenant_id: str, document_id: str):
    """P1-1: build ManufacturingDocumentMetadata from the ingest request, or None if absent.

    tenant_id and document_id are taken from the authenticated principal / request, never from the
    metadata block. Used by the single-document ``/internal/ingest`` boundary, where the caller
    explicitly chose the approval state for ONE document (1 reviewer, 1 doc).
    """
    raw = _mfg_raw_from_body(body)
    if raw is None:
        return None
    from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata

    return ManufacturingDocumentMetadata.from_mapping(
        {**raw, "tenant_id": tenant_id, "document_id": document_id}
    )


def _datasource_approval_policy(datasource: dict) -> str:
    """The saved datasource's trust policy: 'trusted' or (default) 'review_required'.

    A datasource is review-required unless an operator EXPLICITLY marked it trusted (an audited
    ``data_source_changed`` event at upsert). Anything unrecognised falls back to review_required
    (fail-safe): an unknown/garbled policy must never grant auto-approval.
    """
    config = datasource.get("config") or {}
    policy = str(config.get("approval_policy") or "review_required").strip().lower()
    return "trusted" if policy == "trusted" else "review_required"


def _approval_from_datasource_policy(datasource: dict) -> tuple[str, str, str | None]:
    """Derive (approval_status, approval_source, effective_date) for EVERY file of a sync from the
    saved datasource trust policy — NEVER from the (forgeable, per-request) sync body (Step 0 safety).

    - 'trusted'        -> ('approved', 'imported', effective_date): the operator asserted the source
                          is the system of record (FR-MFG-004a). effective_date defaults to today so
                          the doc is approved+effective and immediately citable for high-risk answers.
    - 'review_required'-> ('pending_review', 'workflow', None): each file enters the human review
                          queue. pending_review is usable as a non-primary / non-high-risk basis but
                          is NEVER an approved+effective citation, so a high-risk answer stays blocked
                          (APPROVED_CITATION_MISSING) until a human approves it.
    """
    if _datasource_approval_policy(datasource) == "trusted":
        config = datasource.get("config") or {}
        eff = config.get("approval_effective_date") or _now()[:10]
        return ("approved", "imported", str(eff))
    return ("pending_review", "workflow", None)


def _datasource_mapping_profile_extra(datasource: dict) -> dict:
    config = datasource.get("config") or {}
    profile = config.get("mapping_profile")
    if not isinstance(profile, dict):
        return {}
    extra: dict[str, object] = {}
    profile_type = profile.get("profile_type") or profile.get("data_profile")
    if profile_type:
        extra["datasource_profile_type"] = str(profile_type)
    raw_required = profile.get("required_fields")
    if isinstance(raw_required, (list, tuple)):
        extra["datasource_required_fields"] = [str(field) for field in raw_required]
    raw_mapping = {}
    if isinstance(profile.get("mapping"), dict):
        raw_mapping.update(profile.get("mapping") or {})
    if isinstance(profile.get("field_mapping"), dict):
        raw_mapping.update(profile.get("field_mapping") or {})
    if raw_mapping:
        extra["datasource_mapped_fields"] = sorted({str(value) for value in raw_mapping.values()})
    return extra


def _mfg_metadata_for_sync(body: dict, datasource: dict, tenant_id: str, document_id: str):
    """Sync-time manufacturing metadata for ONE synced file.

    NON-approval fields (equipment, safety_category, …) may still come from the sync body, but the
    approval triplet (approval_status / approval_source / effective_date) is ALWAYS overridden by the
    saved datasource trust policy — the body can never self-grant 'approved' for a connector sync.

    Always returns metadata (never None): every synced file carries an EXPLICIT approval_status
    (pending_review at minimum), closing the 'absent metadata == usable primary' gap (gate.py
    ``_usable_primary(None) is True``).
    """
    from raku_rag.manufacturing.domain.metadata import ManufacturingDocumentMetadata

    raw = dict(_mfg_raw_from_body(body) or {})
    status, source, eff = _approval_from_datasource_policy(datasource)
    raw["approval_status"] = status
    raw["approval_source"] = source
    raw["effective_date"] = eff
    extra = dict(raw.get("extra") or {}) if isinstance(raw.get("extra"), dict) else {}
    extra.update(_datasource_mapping_profile_extra(datasource))
    if extra:
        raw["extra"] = extra
    return ManufacturingDocumentMetadata.from_mapping(
        {**raw, "tenant_id": tenant_id, "document_id": document_id}
    )


def _tenant_upload_prefix(tenant_id: str) -> str:
    return f"tenants/{quote(tenant_id, safe='')[:180]}/uploads/"


def _allowed_ingest_buckets() -> set[str]:
    raw: list[str] = []
    for name in (
        "RAKU_ALLOWED_INGEST_BUCKETS",
        "RAKU_UPLOAD_BUCKET",
        "DOCUMENT_BUCKET",
        "S3_BUCKET",
    ):
        value = os.environ.get(name, "")
        raw.extend(part.strip() for part in value.split(",") if part.strip())
    return set(raw)


def _max_upload_object_bytes() -> int:
    raw = os.environ.get("RAKU_MAX_UPLOAD_OBJECT_BYTES") or os.environ.get(
        "RAKU_MAX_DOCUMENT_BYTES"
    )
    try:
        value = int(raw) if raw else _DEFAULT_MAX_UPLOAD_OBJECT_BYTES
    except ValueError:
        value = _DEFAULT_MAX_UPLOAD_OBJECT_BYTES
    return value if value > 0 else _DEFAULT_MAX_UPLOAD_OBJECT_BYTES


def _parse_s3_ref(ref: str) -> tuple[str, str]:
    parsed = urlparse(ref)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if parsed.scheme != "s3" or not bucket or not key:
        raise ValueError("invalid s3 document_ref")
    return bucket, key


def _verify_upload_s3_ref(connector, document_ref: str, tenant_id: str) -> None:
    if not document_ref.startswith("s3://"):
        return
    bucket, key = _parse_s3_ref(document_ref)
    allowed = _allowed_ingest_buckets()
    if not allowed:
        raise ValueError("S3 ingest bucket is not configured")
    if bucket not in allowed:
        raise PermissionError("S3 document_ref bucket is not allowed")
    tenant_prefix = _tenant_upload_prefix(tenant_id)
    if not key.startswith(tenant_prefix):
        raise PermissionError("S3 document_ref is not owned by the authenticated tenant")

    object_info = getattr(connector, "object_info", None)
    if not callable(object_info):
        raise ValueError("S3 connector cannot verify upload object metadata")
    info = object_info(document_ref)
    content_length = int(info.get("content_length") or 0)
    if content_length > _max_upload_object_bytes():
        raise ValueError("S3 upload object exceeds maximum ingest size")
    metadata = {
        str(k).lower(): str(v) for k, v in dict(info.get("metadata") or {}).items() if k is not None
    }
    tenant_marker = metadata.get("raku-tenant-id")
    if tenant_marker != quote(tenant_id, safe="")[:180]:
        raise PermissionError("S3 upload metadata tenant mismatch")
    if not metadata.get("raku-upload-id"):
        raise ValueError("S3 upload metadata is missing upload id")


def _failed_ingest_response(body: dict, reason: str) -> dict:
    return {
        "ingestion_run_id": "",
        "document_id": str(body.get("document_id") or ""),
        "status": "failed",
        "status_url": "",
        "failure_reason": reason,
        "chunk_count": 0,
    }


def _job_summary_json(run) -> dict:
    return {
        "job_id": run.ingestion_run_id,
        "ingestion_run_id": run.ingestion_run_id,
        "type": run.type,
        "trigger": run.trigger,
        "status": run.status,
        "source_id": run.source_id,
        "document_id": run.document_id,
        "failure_reason": run.failure_reason,
        "retry_count": run.retry_count,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "dagster_run_id": run.dagster_run_id,
        "dagster_run_url": _dagster_run_url(run.dagster_run_id),
    }


def _reindex_response_json(plan) -> dict:
    return {
        "reindex_plan_id": plan.reindex_plan_id,
        "collection_id": plan.collection_id,
        "source_id": plan.source_id,
        "status": plan.status,
        "status_url": f"/v1/admin/reindex-plans/{plan.reindex_plan_id}",
        "affected_document_count": plan.affected_document_count,
        "dagster_backfill_id": plan.dagster_backfill_id,
    }


def _datasource_repository_for(system: ProductionSystem, secret_store):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresDataSourceRepository(conn, secret_store)
    return InMemoryDataSourceRepository(secret_store)


def _chatbot_source_policy_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresChatbotSourcePolicyRepository(conn)
    return InMemoryChatbotSourcePolicyRepository()


def _chatbot_state_repositories_for(system: ProductionSystem) -> dict:
    """S1-3: sessions/handoffs/feedback/scenarios persist to Postgres over a real DB
    (0018_chatbot_persistence, RLS-forced) so conversations survive answer-service restarts."""
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return {
            "session_repository": PostgresChatSessionRepository(conn),
            "handoff_repository": PostgresChatHandoffRepository(conn),
            "feedback_repository": PostgresChatFeedbackRepository(conn),
            "scenario_repository": PostgresChatScenarioRepository(conn),
        }
    return {
        "session_repository": InMemoryChatSessionRepository(),
        "handoff_repository": InMemoryChatHandoffRepository(),
        "feedback_repository": InMemoryChatFeedbackRepository(),
        "scenario_repository": InMemoryChatScenarioRepository(),
    }


def _phone_call_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresPhoneCallRepository(conn)
    return InMemoryPhoneCallRepository()


def _phone_scenario_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresPhoneScenarioRepository(conn)
    return InMemoryPhoneScenarioRepository()


def _phone_quality_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresPhoneQualityRepository(conn)
    return InMemoryPhoneQualityRepository()


def _lexicon_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresLexiconRepository(conn)
    return InMemoryLexiconRepository()


def _feedback_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresFeedbackRepository(conn)
    return InMemoryFeedbackRepository()


def _evaluation_run_repository_for(system: ProductionSystem):
    """U10: durable evaluation runs (evaluation_runs, migration 0007) so the 品質・KPI screen can
    show the latest persisted run across restarts. In-memory fallback for the offline profile."""
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresEvaluationRunRepository(conn)
    return InMemoryEvaluationRunRepository()


def _query_trace_reader_for(system: ProductionSystem):
    """★G3b/★G5: 実測運用メトリクス reader — Postgres query_traces, else in-memory metrics."""
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresQueryTraceReader(conn)
    return InMemoryQueryTraceReader(system.metrics)


def _upload_record_repository_for(system: ProductionSystem):
    conn = getattr(system, "_conn", None)
    if isinstance(system, ProductionSystem) and conn is not None:
        return PostgresUploadRecordRepository(conn)
    return InMemoryUploadRecordRepository()


def _upload_record_ttl_seconds() -> int:
    raw = os.environ.get("RAKU_UPLOAD_RECORD_TTL_SECONDS") or ""
    try:
        value = int(raw)
    except ValueError:
        value = 24 * 60 * 60
    return value if value > 0 else 24 * 60 * 60


def _source_sync_queue_from_env():
    queue_url = os.environ.get("INGESTION_QUEUE_URL") or os.environ.get("SQS_QUEUE_URL")
    if not queue_url:
        return None
    return SqsTaskQueue(queue_url, dead_letter_queue_url=os.environ.get("SQS_DLQ_URL", ""))


def _is_pdf_content_type(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip() == "application/pdf"


def _safe_s3_key_part(value: object) -> str:
    text = str(value or "")
    return "".join(ch if ch.isalnum() or ch in "._=-" else "-" for ch in text).strip("-")


def _stage_visual_upload_ref(
    connector,
    *,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    document_ref: str,
    raw: bytes,
    content_type: str,
) -> str:
    if not _is_pdf_content_type(content_type) or document_ref.startswith("s3://"):
        return document_ref
    put_bytes = getattr(connector, "put_bytes", None)
    if not callable(put_bytes):
        return document_ref
    checksum = hashlib.sha256(raw).hexdigest()
    key = "/".join(
        (
            "uploads",
            _safe_s3_key_part(tenant_id),
            _safe_s3_key_part(collection_id),
            _safe_s3_key_part(document_id),
            f"{checksum}.pdf",
        )
    )
    return str(put_bytes(key, raw, content_type=content_type))


def _enqueue_upload_ingest_if_needed(queue, runs, run) -> str:
    if queue is None or run.status != "queued" or run.sqs_message_id:
        return ""
    message = IngestionJobMessage(
        idempotency_key=run.idempotency_key,
        tenant_id=run.tenant_id,
        collection_id=run.collection_id,
        source_id=run.source_id,
        document_id=run.document_id,
        document_ref=run.document_ref,
        content_type=run.content_type,
    )
    message_id = queue.enqueue_message(message.to_dict())
    runs.mark_message_id(run, message_id)
    return message_id


def make_handler(system: ProductionSystem):
    connector = default_connector_from_env()
    runtime_settings = settings_from_env()
    secret_store = secret_store_from_settings(runtime_settings)
    oauth_connections = InMemoryOAuthConnectionStore()
    datasource_repo = _datasource_repository_for(system, secret_store)
    source_sync_queue = _source_sync_queue_from_env()
    runs = getattr(system, "ingestion_runs", IngestionRunStore())
    source_sync_service = SourceSyncService(
        system=system,
        runs=runs,
        datasource_repo=datasource_repo,
        secret_store=secret_store,
        child_queue=source_sync_queue,
        connector=connector,
        oauth_connections=oauth_connections,
        oauth_secret_store=secret_store,
    )
    admin_settings = _AdminSettingsStore(system, datasource_repo=datasource_repo)
    eval_feedback = _EvalFeedbackStore(
        system,
        run_repository=_evaluation_run_repository_for(system),
        feedback_repository=_feedback_repository_for(system),
    )
    # ★G3b/★G5: real operational metrics for the 品質・KPI screen (query_traces-backed).
    quality_reader = _query_trace_reader_for(system)
    manufacturing_system = build_manufacturing_system_for_base(system)
    chatbot = ChatbotService(
        # Accepts the optional keyword-only `intent_query` (the raw, un-enriched user query) that
        # `L0DeterministicAnswerEngine` forwards when L2's coreference rewrite carried prior-turn
        # context — see chatbot/coreference.py's Finding. The manufacturing chain binds its high-risk
        # classification + approved-citation gate to that raw intent while retrieving with the
        # enriched query. Omitted (None) on every non-rewriting turn => unchanged behavior.
        lambda principal, query, collection_id, *, intent_query=None: _manufacturing_answer_json(
            manufacturing_system.answer(principal, query, collection_id, intent_query=intent_query)
        ),
        source_policy_repository=_chatbot_source_policy_repository_for(system),
        # Reuse the same LLMProvider instance the manufacturing/base answer path already built
        # (system.llm) rather than constructing a second one — see providers/llms.py.
        llm_provider=system.llm,
        # Opt-in, default off (P1 of the conversational-agent roadmap): flips the demo tenant's
        # chatbot_authority_level to "L1" (envelope phrasing). Offline-safe even when set, since
        # RAKU_LLM_PROVIDER stays unset by default (system.llm is then the extractive no-op stub).
        enable_demo_tenant_l1=os.environ.get("RAKU_CHATBOT_DEMO_TENANT_L1") == "1",
        # Opt-in, default off (P3): flips the demo tenant to "L2" (coreference resolution, cumulative
        # with L1's envelope) instead of "L1". Independent flag rather than replacing
        # RAKU_CHATBOT_DEMO_TENANT_L1 outright, so an existing L1 pilot is never silently upgraded —
        # a tenant needs its own explicit opt-in per rung, matching the roadmap's per-tenant dial.
        enable_demo_tenant_l2=os.environ.get("RAKU_CHATBOT_DEMO_TENANT_L2") == "1",
        # Opt-in, default off (P4): flips the demo tenant to "L3" (defense-in-depth verification over
        # composed answers, cumulative with L2's coreference and L1's envelope). Whether real
        # generation ever fires stays governed entirely by RAKU_LLM_PROVIDER/system.llm (unset by
        # default here, same as every other rung) — see chatbot/composition.py's module docstring.
        enable_demo_tenant_l3=os.environ.get("RAKU_CHATBOT_DEMO_TENANT_L3") == "1",
        demo_tenant_id=os.environ.get("DEMO_TENANT", "demo"),
        # Per-hop re-classification signal for "L4" (P5, agentic control): every query an agentic
        # decision-maker proposes is re-checked before it runs — see chatbot/agent.py. Reuses the SAME
        # classifier instance the real answer path's safety gate consults (never a second, drifting
        # one). NOTE: L2's coreference rewrite no longer relies on this signal — its safety is now
        # handled at the root cause (intent_query threading; see chatbot/coreference.py's Finding),
        # so L2 enriches every referential follow-up and the manufacturing chain judges the high-risk
        # decision on the raw intent regardless.
        high_risk_query_signal=manufacturing_system.is_high_risk_query_signal,
        # P5: "L4" is registered in ChatbotService._answer_engines (chatbot/agent.py) so the seam is
        # real and testable, but deliberately NOT dialable here yet -- no `agent_decision_maker` is
        # passed (stays None), and there is no `RAKU_CHATBOT_DEMO_TENANT_L4` flag, unlike L1/L2/L3
        # above. No real (Bedrock-backed) AgentDecisionMaker implementation exists; building one needs
        # credentials this environment does not have. Even a tenant explicitly dialed to "L4" via the
        # authority repository gets the inert L0-passthrough behavior (see agent.py) until a real
        # decision-maker is both built and consciously wired here.
        **_chatbot_state_repositories_for(system),
    )
    # 022-ai-phone-rag: the phone layer reuses the SAME audited manufacturing answer path as the
    # chatbot (FR-009) — no separate retrieval/citation path for the phone channel.
    phone = PhoneCallService(
        CallableAnswerGateway(
            lambda principal, query, collection_id: _manufacturing_answer_json(
                manufacturing_system.answer(principal, query, collection_id)
            )
        ),
        repository=_phone_call_repository_for(system),
        scenarios=PhoneScenarioService(_phone_scenario_repository_for(system)),
        telephony=DeterministicCallSimulator(),
        asr=DeterministicAsrProvider(),
        tts=DeterministicTtsProvider(),
        # US4: QA reviews persist via 0017 and flow into the audit-derived improvement queue
        # through the SAME manufacturing audit writer (single source of truth).
        quality=PhoneQualityService(
            _phone_quality_repository_for(system), audit=manufacturing_system.audit
        ),
        audit=manufacturing_system.audit,
        lexicon=None,
    )
    industry_api = IndustryApiService()
    real_estate_api = RealEstateApiService()
    investment_api = InvestmentApiService()
    # 0045: server-issued S3 upload provenance — presign registers, ingest resolves + consumes.
    upload_records = _upload_record_repository_for(system)
    # ★V2 tenant_lexicon: per-tenant vocabulary extensions, shared across the three channels.
    lexicon = LexiconService(_lexicon_repository_for(system), audit=manufacturing_system.audit)
    manufacturing_system.lexicon = lexicon
    chatbot._lexicon = lexicon
    phone._lexicon = lexicon
    # Wave 1c: retrieval-time synonym expansion reads the SAME tenant lexicon
    # (retrieval.synonyms namespace, lexical leg only — services/retrieval.py). Attached
    # post-construction like the chatbot/phone consumers so all channels share one instance.
    system.retrieval._lexicon = lexicon

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_result(self, result: tuple[int, dict]) -> None:
            code, payload = result
            self._send(code, _jsonable(payload))

        def _body(self) -> dict:
            n = int(self.headers.get("content-length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _tenant_header(self) -> str:
            tenant_id = self.headers.get("x-raku-tenant-id") or ""
            if not tenant_id:
                raise KeyError("x-raku-tenant-id")
            return tenant_id

        def _internal_auth_ok(self, path: str) -> bool:
            """P4-4 — enforce the internal-boundary shared secret; 401 + False on mismatch."""
            if internal_auth_ok(
                _INTERNAL_AUTH_SECRET, path, self.headers.get("X-Internal-Auth", "")
            ):
                return True
            self._send(401, {"error": "internal_auth_required"})
            return False

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if not self._internal_auth_ok(path):
                    return
                parts = [unquote(p) for p in path.split("/") if p]
                if path == "/healthz":
                    self._send(200, {"status": "ok", "backend": "production-system"})
                elif parts == ["internal", "chat", "sessions"]:
                    qs = parse_qs(parsed.query)
                    self._send_result(chatbot.list_sessions(_claims_from_headers(self.headers), qs))
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "chat", "sessions"]
                    and parts[3] != "export"
                ):
                    self._send_result(
                        chatbot.get_session(_claims_from_headers(self.headers), parts[3])
                    )
                elif len(parts) == 4 and parts[:3] == ["internal", "chat", "handoffs"]:
                    self._send_result(
                        chatbot.get_handoff(_claims_from_headers(self.headers), parts[3])
                    )
                elif parts == ["internal", "chat", "metrics"]:
                    self._send_result(chatbot.metrics(_claims_from_headers(self.headers)))
                elif parts == ["internal", "chat", "retention-policy"]:
                    self._send_result(chatbot.retention_policy(_claims_from_headers(self.headers)))
                elif parts == ["internal", "chat", "source-exposure-policies"]:
                    self._send_result(
                        chatbot.list_source_policies(_claims_from_headers(self.headers))
                    )
                elif parts == ["internal", "chat", "scenarios"]:
                    self._send_result(chatbot.list_scenarios(_claims_from_headers(self.headers)))
                elif parts == ["internal", "phone", "calls"]:
                    qs = parse_qs(parsed.query)
                    self._send_result(phone.list_calls(_claims_from_headers(self.headers), qs))
                elif len(parts) == 4 and parts[:3] == ["internal", "phone", "calls"]:
                    self._send_result(phone.get_call(_claims_from_headers(self.headers), parts[3]))
                elif len(parts) == 4 and parts[:3] == ["internal", "phone", "handoffs"]:
                    self._send_result(
                        phone.get_handoff(_claims_from_headers(self.headers), parts[3])
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "calls"]
                    and parts[4] == "quality-evaluations"
                ):
                    self._send_result(
                        phone.list_quality_evaluations(_claims_from_headers(self.headers), parts[3])
                    )
                elif parts == ["internal", "phone", "metrics"]:
                    qs = parse_qs(parsed.query)
                    self._send_result(phone.metrics(_claims_from_headers(self.headers), qs))
                elif parts == ["internal", "phone", "retention-policy"]:
                    self._send_result(phone.retention_policy(_claims_from_headers(self.headers)))
                elif parts == ["internal", "phone", "scenarios"]:
                    self._send_result(phone.list_scenarios(_claims_from_headers(self.headers)))
                elif parts == ["internal", "reviews", "extraction"]:
                    # ADR-018 §12.1 — extraction review queue (quarantined chunks) for the tenant.
                    self._send(
                        200,
                        {"items": system.list_extraction_reviews(self._tenant_header())},
                    )
                elif parts == ["internal", "industries"]:
                    self._send(200, industry_api.list_industries(tenant_id=self._tenant_header()))
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "profile"
                ):
                    self._send(200, industry_api.profile(parts[2]))
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "dashboard"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        industry_api.dashboard(self._tenant_header(), parts[2], roles=roles),
                    )
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "kpi"
                ):
                    self._send(200, industry_api.kpi(self._tenant_header(), parts[2]))
                elif (
                    len(parts) == 5
                    and parts[:2] == ["internal", "industries"]
                    and parts[3:] == ["governance", "status"]
                ):
                    self._send(200, industry_api.governance_status(parts[2]))
                elif (
                    len(parts) == 5
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "drafts"
                ):
                    draft = industry_api.get_draft(parts[2], parts[4])
                    self._send(200, draft) if draft else self._send(404, {"error": "not found"})
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "real-estate", "properties"]
                    and parts[4] == "knowledge"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        real_estate_api.property_knowledge(self._tenant_header(), parts[3], roles),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "real-estate", "units"]
                    and parts[4] == "knowledge"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        real_estate_api.unit_knowledge(self._tenant_header(), parts[3], roles),
                    )
                elif len(parts) == 4 and parts[:3] == ["internal", "real-estate", "drafts"]:
                    draft = real_estate_api.draft(parts[3])
                    self._send(200, draft) if draft else self._send(404, {"error": "not found"})
                elif parts == ["internal", "real-estate", "dashboard"]:
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(200, real_estate_api.dashboard(self._tenant_header(), roles))
                elif parts == ["internal", "real-estate", "kpi"]:
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(200, real_estate_api.kpi(self._tenant_header(), roles))
                elif parts == ["internal", "real-estate", "audit"]:
                    self._send(200, real_estate_api.audit())
                elif parts == ["internal", "real-estate", "governance", "status"]:
                    self._send(200, real_estate_api.governance_status())
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "investment", "funds"]
                    and parts[4] == "knowledge"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        investment_api.fund_knowledge(self._tenant_header(), parts[3], roles),
                    )
                elif len(parts) == 4 and parts[:3] == ["internal", "investment", "drafts"]:
                    draft = investment_api.draft(parts[3])
                    self._send(200, draft) if draft else self._send(404, {"error": "not found"})
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "investment"]
                    and parts[2] == "disclosure-evidence"
                ):
                    evidence = investment_api.disclosure_evidence(parts[3])
                    (
                        self._send(200, evidence)
                        if evidence
                        else self._send(404, {"error": "not found"})
                    )
                elif parts == ["internal", "investment", "dashboard"]:
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(200, investment_api.dashboard(self._tenant_header(), roles))
                elif parts == ["internal", "investment", "kpi"]:
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(200, investment_api.kpi(self._tenant_header(), roles))
                elif parts == ["internal", "investment", "audit"]:
                    self._send(200, investment_api.audit())
                elif parts == ["internal", "investment", "governance", "status"]:
                    self._send(200, investment_api.governance_status())
                elif parts == ["internal", "manufacturing", "policy", "data-use"]:
                    self._send(
                        200,
                        _data_use_policy_json(
                            manufacturing_system.get_data_use_policy(self._tenant_header())
                        ),
                    )
                elif parts == ["internal", "manufacturing", "governance", "status"]:
                    self._send(200, manufacturing_system.governance_status(self._tenant_header()))
                elif len(parts) == 4 and parts[:3] == ["internal", "admin", "lexicon"]:
                    principal = _claims_from_headers(self.headers)
                    self._send(
                        200,
                        {
                            "namespace": parts[3],
                            "entries": {
                                k: list(v)
                                for k, v in lexicon.entries(principal.tenant_id, parts[3]).items()
                            },
                        },
                    )
                elif parts == ["internal", "manufacturing", "audit", "evidence-pack"]:
                    # ★1: the audit hash chain rendered as a monthly compliance artifact
                    # (reference IDs only; includes the chain verification verdict).
                    from raku_rag.manufacturing.api.evidence_pack import build_evidence_pack

                    qs = parse_qs(parsed.query)
                    self._send(
                        200,
                        build_evidence_pack(
                            manufacturing_system.audit,
                            _claims_from_headers(self.headers),
                            from_iso=(qs.get("from") or [""])[0],
                            to_iso=(qs.get("to") or [""])[0],
                        ),
                    )
                elif parts == ["internal", "manufacturing", "audit", "export"]:
                    qs = parse_qs(parsed.query)
                    fmt = (qs.get("fmt") or ["dict"])[0]
                    exported = manufacturing_system.export_audit(
                        principal=_claims_from_headers(self.headers), fmt=fmt
                    )
                    payload = (
                        {"format": fmt, "records": exported}
                        if fmt == "dict"
                        else {"format": fmt, "content": exported}
                    )
                    self._send(200, payload)
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "sources"]
                    and parts[4] == "sync-status"
                ):
                    self._send(
                        200,
                        _manufacturing_source_sync_status_json(
                            system.ingestion_runs,
                            self._tenant_header(),
                            parts[3],
                        ),
                    )
                elif len(parts) == 4 and parts[:3] == [
                    "internal",
                    "manufacturing",
                    "ingestion-runs",
                ]:
                    self._send(
                        200,
                        _jsonable(
                            manufacturing_system.ingestion_run_status(
                                _claims_from_headers(self.headers), parts[3]
                            )
                        ),
                    )
                elif parts == ["internal", "manufacturing", "drafts"]:
                    qs = parse_qs(parsed.query)
                    drafts = manufacturing_system.list_drafts(
                        self._tenant_header(),
                        status=(qs.get("status") or [None])[0],
                        reviewer_id=(qs.get("reviewer_id") or [None])[0],
                    )
                    self._send(200, {"drafts": [_jsonable(d) for d in drafts]})
                elif len(parts) == 4 and parts[:3] == ["internal", "manufacturing", "drafts"]:
                    draft = manufacturing_system.get_draft(self._tenant_header(), parts[3])
                    (
                        self._send(200, _jsonable(draft))
                        if draft
                        else self._send(404, {"error": "not found"})
                    )
                elif parts == ["internal", "manufacturing", "documents"]:
                    qs = parse_qs(parsed.query)
                    self._send(
                        200,
                        {
                            "documents": manufacturing_system.list_documents(
                                _claims_from_headers(self.headers),
                                collection_id=(qs.get("collection_id") or [None])[0],
                                approval_status=(qs.get("approval_status") or [None])[0],
                            )
                        },
                    )
                elif len(parts) == 4 and parts[:3] == ["internal", "manufacturing", "documents"]:
                    detail = manufacturing_system.get_document_detail(
                        _claims_from_headers(self.headers), parts[3]
                    )
                    (
                        self._send(200, _jsonable(detail))
                        if detail
                        else self._send(404, {"error": "not found"})
                    )
                elif parts == ["internal", "manufacturing", "audit", "events"]:
                    qs = parse_qs(parsed.query)
                    limit_raw = (qs.get("limit") or ["100"])[0]
                    offset_raw = (qs.get("offset") or ["0"])[0]
                    self._send(
                        200,
                        manufacturing_system.list_audit_events(
                            principal=_claims_from_headers(self.headers),
                            action=(qs.get("action") or [None])[0],
                            limit=int(limit_raw) if str(limit_raw).isdigit() else 100,
                            offset=int(offset_raw) if str(offset_raw).isdigit() else 0,
                        ),
                    )
                elif parts == ["internal", "manufacturing", "improvements"]:
                    qs = parse_qs(parsed.query)
                    limit_raw = (qs.get("limit") or ["100"])[0]
                    self._send(
                        200,
                        manufacturing_system.improvement_queue(
                            _claims_from_headers(self.headers),
                            limit=int(limit_raw) if str(limit_raw).isdigit() else 100,
                        ),
                    )
                elif parts == ["internal", "manufacturing", "dashboard"]:
                    qs = parse_qs(parsed.query)
                    self._send(
                        200,
                        _jsonable(
                            manufacturing_system.knowledge_ops_dashboard(
                                _claims_from_headers(self.headers),
                                collection_id=(qs.get("collection_id") or [None])[0],
                                factory_id=(qs.get("factory_id") or [None])[0],
                                department_id=(qs.get("department_id") or [None])[0],
                                time_range=_query_time_range(qs),
                            )
                        ),
                    )
                elif parts == ["internal", "manufacturing", "safety-telemetry"]:
                    qs = parse_qs(parsed.query)
                    self._send(
                        200,
                        _jsonable(
                            manufacturing_system.safety_telemetry(
                                _claims_from_headers(self.headers),
                                collection_id=(qs.get("collection_id") or [None])[0],
                                factory_id=(qs.get("factory_id") or [None])[0],
                                department_id=(qs.get("department_id") or [None])[0],
                                time_range=_query_time_range(qs),
                                granularity=(qs.get("granularity") or ["daily"])[0],
                            )
                        ),
                    )
                elif parts == ["internal", "manufacturing", "kpi"]:
                    qs = parse_qs(parsed.query)
                    fmt = (qs.get("format") or ["json"])[0]
                    result = manufacturing_system.kpi(
                        _claims_from_headers(self.headers),
                        collection_id=(qs.get("collection_id") or [None])[0],
                        time_range=_query_time_range(qs),
                        format=fmt,
                    )
                    payload = (
                        result if isinstance(result, dict) else {"format": fmt, "content": result}
                    )
                    self._send(200, _jsonable(payload))
                elif parts == ["internal", "jobs"]:
                    qs = parse_qs(parsed.query)
                    runs = system.ingestion_runs.list_runs(
                        self._tenant_header(),
                        status=(qs.get("status") or [""])[0],
                        source_id=(qs.get("source_id") or [""])[0],
                    )
                    self._send(200, {"jobs": [_job_summary_json(run) for run in runs]})
                elif len(parts) == 3 and parts[:2] == ["internal", "ingestion-runs"]:
                    run = system.ingestion_runs.get_for_tenant(self._tenant_header(), parts[2])
                    if run:
                        self._send(200, _ingestion_run_json(run))
                    else:
                        self._send(404, {"error": "not found"})
                elif len(parts) == 3 and parts[:2] == ["internal", "assets"]:
                    asset = system.assets.get_visual_asset(
                        _claims_from_headers(self.headers), parts[2]
                    )
                    if asset:
                        self._send(200, asset)
                    else:
                        self._send(404, {"error": "not found"})
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "documents"]
                    and parts[3] == "file"
                ):
                    # /internal/documents/{id}/file -> docid is parts[2] (4 segments, matching the API
                    # facade and the sibling processing-status route). Was mis-indexed for 5 segments.
                    payload = manufacturing_system.get_document_file(
                        _claims_from_headers(self.headers), parts[2]
                    )
                    (
                        self._send(200, _jsonable(payload))
                        if payload
                        else self._send(404, {"error": "not found"})
                    )
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "documents"]
                    and parts[3] == "citation-view"
                ):
                    # /internal/documents/{id}/citation-view -> docid is parts[2] (4 segments). The
                    # 5-segment guard here previously 404'd every citation-view open.
                    qs = parse_qs(parsed.query)
                    chunk_id = (qs.get("chunk_id") or [None])[0]
                    payload = manufacturing_system.get_citation_source(
                        _claims_from_headers(self.headers),
                        parts[2],
                        chunk_id=chunk_id,
                    )
                    (
                        self._send(200, _jsonable(payload))
                        if payload
                        else self._send(404, {"error": "not found"})
                    )
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "documents"]
                    and parts[3] == "processing-status"
                ):
                    state = system.ingestion_runs.processing_state(self._tenant_header(), parts[2])
                    if state:
                        self._send(200, _processing_state_json(state))
                    else:
                        self._send(404, {"error": "not found"})
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "sources"]
                    and parts[3] == "sync-status"
                ):
                    state = system.ingestion_runs.source_sync_state(self._tenant_header(), parts[2])
                    if state:
                        self._send(200, _source_sync_state_json(state))
                    else:
                        self._send(404, {"error": "not found"})
                elif len(parts) == 4 and parts[:3] == ["internal", "evaluations", "runs"]:
                    run = eval_feedback.get_run(self._tenant_header(), parts[3])
                    if run:
                        self._send(200, run)
                    else:
                        self._send(404, {"error": "not found"})
                elif parts == ["internal", "evaluations", "latest"]:
                    # U10: latest persisted evaluation run for the tenant (list_runs is
                    # chronological). Tenant comes from the principal headers, never a query param.
                    latest_runs = eval_feedback.list_runs(self._tenant_header())
                    if latest_runs:
                        self._send(200, latest_runs[-1])
                    else:
                        self._send(404, {"error": "not found"})
                elif parts == ["internal", "feedback"]:
                    # ★G3a: the persisted feedback list behind the admin improvement queue.
                    # Tenant comes from the authenticated principal headers, NEVER a query param.
                    principal = _claims_from_headers(self.headers)
                    qs = parse_qs(parsed.query)
                    self._send(
                        200,
                        {
                            "items": eval_feedback.list_feedback(
                                principal.tenant_id,
                                limit=_qs_int(qs, "limit", 100),
                                offset=_qs_int(qs, "offset", 0),
                                rating=(qs.get("rating") or [""])[0],
                            )
                        },
                    )
                elif parts == ["internal", "quality", "operational"]:
                    # ★G3b/★G5: 実測運用メトリクス — real p50/p95/status counts from query_traces
                    # plus the persisted low-rating count. Tenant comes from the authenticated
                    # principal headers ONLY, never a query param.
                    principal = _claims_from_headers(self.headers)
                    qs = parse_qs(parsed.query)
                    summary = quality_reader.operational_summary(
                        principal.tenant_id, limit=_qs_int(qs, "limit", 20)
                    )
                    summary["low_rating_count"] = len(
                        eval_feedback.list_feedback(principal.tenant_id, limit=1000, rating="down")
                    )
                    self._send(200, _jsonable(summary))
                elif len(parts) >= 3 and parts[:2] == ["internal", "admin"]:
                    resource = parts[2]
                    qs = parse_qs(parsed.query)
                    if resource == "provider-config-audit-events" and len(parts) == 3:
                        self._send(
                            200,
                            admin_settings.list_audit_events(
                                self._tenant_header(),
                                event_type=(qs.get("event_type") or [""])[0],
                                correlation_id=(qs.get("correlation_id") or [""])[0],
                                collection_id=(qs.get("collection_id") or [""])[0],
                            ),
                        )
                    elif resource == "datasources" and len(parts) == 4 and parts[3] == "overview":
                        collection_id = (qs.get("collection_id") or [""])[0]
                        sources = admin_settings.list_resource(
                            self._tenant_header(),
                            "datasources",
                            collection_id=collection_id,
                        )
                        documents = manufacturing_system.list_documents(
                            _claims_from_headers(self.headers),
                            collection_id=collection_id or None,
                        )
                        self._send(
                            200,
                            {
                                "sources": _datasource_overview_rows(
                                    sources,
                                    documents,
                                    system.ingestion_runs,
                                    self._tenant_header(),
                                )
                            },
                        )
                    elif resource in admin_settings._id_fields and len(parts) == 3:
                        self._send(
                            200,
                            admin_settings.list_resource(
                                self._tenant_header(),
                                resource,
                                collection_id=(qs.get("collection_id") or [""])[0],
                            ),
                        )
                    elif resource in admin_settings._id_fields and len(parts) == 4:
                        item = admin_settings.get_resource(
                            self._tenant_header(), resource, parts[3]
                        )
                        if item:
                            self._send(200, item)
                        else:
                            self._send(404, {"error": "not found"})
                    elif resource == "acl" and len(parts) == 3:
                        self._send(200, admin_settings.acl(self._tenant_header()))
                    elif resource == "budgets" and len(parts) == 3:
                        self._send(
                            200,
                            admin_settings.budgets(
                                self._tenant_header(),
                                scope_type=(qs.get("scope_type") or [""])[0],
                                scope_id=(qs.get("scope_id") or [""])[0],
                            ),
                        )
                    else:
                        self._send(404, {"error": "not found"})
                else:
                    self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": f"missing header: {exc}"})
            except Exception as exc:  # pragma: no cover - surface as 500 to the facade
                self._send(500, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if not self._internal_auth_ok(path):
                    return
                body = self._body()
                parts = [unquote(p) for p in path.split("/") if p]
                if path == "/internal/answer":
                    principal = _claims(body)
                    query = str(body.get("query") or "")
                    collection_id = body.get("collection_id")
                    self._send(200, _answer_json(system.answer(principal, query, collection_id)))
                elif parts == ["internal", "chat", "sessions"]:
                    self._send_result(
                        chatbot.create_session(_claims_from_headers(self.headers), body)
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "chat", "sessions"]
                    and parts[4] == "messages"
                ):
                    self._send_result(
                        chatbot.submit_message(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "chat", "sessions"]
                    and parts[4] == "handoff"
                ):
                    self._send_result(
                        chatbot.request_handoff(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "chat", "sessions"]
                    and parts[4] == "feedback"
                ):
                    self._send_result(
                        chatbot.submit_feedback(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif parts == ["internal", "chat", "sessions", "export"]:
                    self._send_result(chatbot.export_sessions(_claims_from_headers(self.headers)))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "chat", "sessions"]
                    and parts[4] == "delete-request"
                ):
                    self._send_result(
                        chatbot.delete_request(_claims_from_headers(self.headers), parts[3])
                    )
                elif parts == ["internal", "chat", "source-exposure-policies", "validate"]:
                    self._send_result(
                        chatbot.validate_source_policy(_claims_from_headers(self.headers), body)
                    )
                elif parts == ["internal", "chat", "scenarios"]:
                    self._send_result(
                        chatbot.create_scenario(_claims_from_headers(self.headers), body)
                    )
                elif (
                    len(parts) == 7
                    and parts[:3] == ["internal", "chat", "scenarios"]
                    and parts[4] == "versions"
                ):
                    self._send_result(
                        chatbot.scenario_action(
                            _claims_from_headers(self.headers),
                            parts[3],
                            parts[5],
                            parts[6],
                            body,
                        )
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "chat", "scenarios"]
                    and parts[4] == "rollback"
                ):
                    self._send_result(
                        chatbot.rollback_scenario(_claims_from_headers(self.headers), parts[3])
                    )
                elif parts == ["internal", "phone", "calls", "simulate"]:
                    self._send_result(phone.simulate_call(_claims_from_headers(self.headers), body))
                elif parts == ["internal", "phone", "calls", "export"]:
                    self._send_result(phone.export_calls(_claims_from_headers(self.headers), body))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "calls"]
                    and parts[4] == "quality-evaluations"
                ):
                    self._send_result(
                        phone.create_quality_evaluation(
                            _claims_from_headers(self.headers), parts[3], body
                        )
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "calls"]
                    and parts[4] == "delete-request"
                ):
                    self._send_result(
                        phone.delete_call_request(
                            _claims_from_headers(self.headers), parts[3], body
                        )
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "calls"]
                    and parts[4] == "turns"
                ):
                    self._send_result(
                        phone.submit_turn(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "handoffs"]
                    and parts[4] == "accept"
                ):
                    self._send_result(
                        phone.accept_handoff(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif parts == ["internal", "phone", "scenarios"]:
                    self._send_result(
                        phone.create_scenario(_claims_from_headers(self.headers), body)
                    )
                elif (
                    len(parts) == 7
                    and parts[:3] == ["internal", "phone", "scenarios"]
                    and parts[4] == "versions"
                ):
                    self._send_result(
                        phone.scenario_action(
                            _claims_from_headers(self.headers),
                            parts[3],
                            parts[5],
                            parts[6],
                            body,
                        )
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "phone", "scenarios"]
                    and parts[4] == "rollback"
                ):
                    self._send_result(
                        phone.rollback_scenario(_claims_from_headers(self.headers), parts[3], body)
                    )
                elif path == "/internal/manufacturing/answer":
                    # P2-1: the manufacturing safety overlay (high-risk gate, approved+effective
                    # evidence requirement, draft/obsolete never primary) on the deployed answer path.
                    # Route through ``manufacturing_system.answer`` (NOT the audit-less
                    # ``build_manufacturing_answer_service`` overlay): identical safety behaviour over the
                    # same Postgres base, but it ALSO records the high-risk classification + safety
                    # decision + citation access to the tamper-evident hash-chain audit (parity with the
                    # drafts/approval routes). Previously this handler discarded the decision (`*_`) and
                    # wrote no audit row for a deployed safety-gate answer (AF-6 / FR-MFG-021).
                    principal = _claims(body)
                    query = str(body.get("query") or "")
                    collection_id = body.get("collection_id")
                    # U19 (追い質問の文脈維持): optional `history` = prior thread turns
                    # [{question, cited_document_ids?}] (most recent last, server-capped). A short
                    # referential follow-up ("その締付トルクは?") is rewritten into a standalone
                    # RETRIEVAL query carrying the prior turn's identifiers/terms — the exact shared
                    # logic the chatbot L2 rung uses (core/coreference.py) — while the RAW query is
                    # threaded as `intent_query` so the high-risk classification and the
                    # approved-citation requirement bind to what the user actually asked, never the
                    # enriched text (the intent-query safety invariant; chatbot/coreference.py's
                    # Finding). No history / non-referential => (query, None): byte-identical call.
                    retrieval_query, intent_query = followup_from_history(
                        query, body.get("history")
                    )
                    mfg_ans = manufacturing_system.answer(
                        principal,
                        retrieval_query,
                        collection_id,
                        intent_hint=body.get("intent_hint"),
                        manufacturing_filters=body.get("manufacturing_filters"),
                        factory_id=body.get("factory_id"),
                        intent_query=intent_query,
                    )
                    payload = _manufacturing_answer_json(mfg_ans)
                    if intent_query is not None:
                        # Transparency for the UI chip (文脈を引き継ぎました): report that the
                        # query was rewritten and what retrieval actually searched for.
                        payload["context_carried"] = True
                        payload["retrieval_query"] = retrieval_query
                    self._send(200, payload)
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "sources"]
                    and parts[4] == "sync"
                ):
                    tenant_id = self._tenant_header()
                    source_id = parts[3]
                    try:
                        response, message, created = source_sync_service.request_source_sync(
                            tenant_id=tenant_id,
                            source_id=source_id,
                            body=body,
                            requested_by=self.headers.get("x-raku-user-id") or "",
                        )
                    except KeyError:
                        self._send(404, {"error": "datasource not found"})
                        return
                    if source_sync_queue is not None:
                        if created:
                            message_id = source_sync_queue.enqueue_message(message.to_dict())
                            run = runs.get_for_tenant(tenant_id, response["sync_run_id"])
                            if run is not None:
                                runs.mark_message_id(run, message_id)
                            response["sqs_message_id"] = message_id
                        response["queued"] = True
                        response["status_url"] = (
                            f"/v1/manufacturing/ingestion-runs/{response['sync_run_id']}"
                        )
                        self._send(202, response)
                    else:
                        executed = source_sync_service.execute_source_sync(message)
                        executed["queued"] = False
                        executed["status_url"] = (
                            f"/v1/manufacturing/ingestion-runs/{executed['sync_run_id']}"
                        )
                        self._send(202, executed)
                elif parts == ["internal", "manufacturing", "documents", "approval-batch"]:
                    principal = _claims_from_headers(self.headers)
                    result = manufacturing_system.batch_transition_approval(
                        tenant_id=principal.tenant_id,
                        document_ids=body.get("document_ids") or (),
                        to_status=str(body.get("to_status") or ""),
                        actor=principal,
                    )
                    self._send(200, _jsonable(result))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "documents"]
                    and parts[4] == "approval"
                ):
                    principal = _claims_from_headers(self.headers)
                    if "import_external" in body:
                        result = manufacturing_system.import_external_approval(
                            tenant_id=principal.tenant_id,
                            document_id=parts[3],
                            external=dict(body.get("import_external") or {}),
                            actor=principal,
                        )
                    else:
                        result = manufacturing_system.transition_approval(
                            tenant_id=principal.tenant_id,
                            document_id=parts[3],
                            to_status=str(body.get("to_status") or ""),
                            actor=principal,
                        )
                    self._send(200, _jsonable({"document_id": parts[3], "approval_state": result}))
                elif parts == ["internal", "manufacturing", "trouble-cases", "search"]:
                    principal = _claims_from_headers(self.headers)
                    response = manufacturing_system.search_trouble_cases(
                        principal,
                        str(body.get("symptom_query") or body.get("query") or ""),
                        collection_id=body.get("collection_id"),
                        manufacturing_filters=body.get("manufacturing_filters"),
                        top_k=body.get("top_k"),
                    )
                    self._send(200, _jsonable(response))
                elif parts == ["internal", "manufacturing", "trouble-cases", "register"]:
                    # Seed a past TroubleCase as a knowledge graph (symptom -> cause/FailureMode ->
                    # split provisional/permanent Countermeasures), so trouble-cases/search can resolve
                    # an ACL-visible source document back to its structured countermeasures. Without
                    # this the curated demo ingested trouble reports as plain text and the symptom
                    # search returned 0 (the graph store was empty).
                    from raku_rag.manufacturing.domain.entities import (
                        Countermeasure,
                        FailureMode,
                        MeasureClass,
                        TroubleCase,
                    )

                    # Identity in the body (same convention as /internal/ingest), so the curated demo
                    # seed can register graphs without forging x-raku-* headers.
                    principal = _claims(body)
                    doc_id = str(body.get("source_document_id") or body.get("document_id") or "")
                    tc_id = f"tc:{doc_id}"
                    fm_id = f"fm:{doc_id}"
                    fm_body = body.get("failure_mode") or {}
                    measures = []
                    for i, desc in enumerate(body.get("provisional") or ()):
                        measures.append(
                            Countermeasure(
                                tenant_id=principal.tenant_id,
                                measure_id=f"{tc_id}:prov:{i}",
                                trouble_case_id=tc_id,
                                description=str(desc),
                                measure_class=MeasureClass.PROVISIONAL,
                                source_document_id=doc_id,
                            )
                        )
                    for i, desc in enumerate(body.get("permanent") or ()):
                        measures.append(
                            Countermeasure(
                                tenant_id=principal.tenant_id,
                                measure_id=f"{tc_id}:perm:{i}",
                                trouble_case_id=tc_id,
                                description=str(desc),
                                measure_class=MeasureClass.PERMANENT,
                                source_document_id=doc_id,
                            )
                        )
                    manufacturing_system.register_trouble_case(
                        tenant_id=principal.tenant_id,
                        collection_id=str(body.get("collection_id") or "manuals"),
                        source_document_id=doc_id,
                        text=str(body.get("text") or ""),
                        metadata=_mfg_metadata_from_body(body, principal.tenant_id, doc_id),
                        trouble_case=TroubleCase(
                            tenant_id=principal.tenant_id,
                            trouble_case_id=tc_id,
                            symptom=str(body.get("symptom") or ""),
                            equipment_id=body.get("equipment_id"),
                            failure_mode_id=fm_id,
                            source_document_id=doc_id,
                        ),
                        failure_mode=FailureMode(
                            tenant_id=principal.tenant_id,
                            failure_mode_id=fm_id,
                            name=str(fm_body.get("name") or ""),
                            description=str(fm_body.get("description") or ""),
                        ),
                        countermeasures=tuple(measures),
                        recurrence_prevention=body.get("recurrence"),
                        source_id=str(body.get("source_id") or "case"),
                    )
                    self._send(
                        202,
                        {"trouble_case_id": tc_id, "document_id": doc_id, "status": "registered"},
                    )
                elif parts == ["internal", "manufacturing", "drafts"]:
                    principal = _claims_from_headers(self.headers)
                    draft = manufacturing_system.generate_draft(
                        principal=principal,
                        kind=str(body.get("kind") or body.get("type") or ""),
                        source_document_ids=tuple(body.get("source_document_ids") or ()),
                        template_id=body.get("template_id"),
                        collection_id=body.get("collection_id"),
                        manufacturing_filters=body.get("manufacturing_filters"),
                    )
                    self._send(200, _jsonable(draft))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "drafts"]
                    and parts[4] == "assign"
                ):
                    draft = manufacturing_system.assign_reviewer(
                        tenant_id=self._tenant_header(),
                        artifact_id=parts[3],
                        reviewer_id=body.get("reviewer_id"),
                        reviewer_group=body.get("reviewer_group"),
                        reviewer_role=body.get("reviewer_role"),
                    )
                    self._send(200, _jsonable(draft))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "drafts"]
                    and parts[4] == "review"
                ):
                    draft = manufacturing_system.review_draft(
                        tenant_id=self._tenant_header(),
                        artifact_id=parts[3],
                        reviewer=_claims_from_headers(self.headers),
                        decision=str(body.get("decision") or ""),
                        comment=body.get("comment"),
                    )
                    self._send(200, _jsonable(draft))
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "drafts"]
                    and parts[4] == "publish"
                ):
                    # issue 0019 — publish the APPROVED draft as approved knowledge. The actor comes
                    # from the SIGNED principal headers only (same identity source as .../review);
                    # non-approved / already-published drafts surface as 409 (InvalidTransitionError).
                    draft = manufacturing_system.publish_draft(
                        principal=_claims_from_headers(self.headers),
                        artifact_id=parts[3],
                    )
                    self._send(200, _jsonable(draft))
                elif path == "/internal/search":
                    principal = _claims(body)
                    query = str(body.get("query") or "")
                    collection_id = body.get("collection_id")
                    top_k = body.get("top_k")
                    self._send(200, _search_json(system, principal, query, collection_id, top_k))
                elif path == "/internal/uploads":
                    # 0045: register upload provenance BEFORE the browser gets a presigned PUT URL.
                    # Identity comes from the signed headers; the record is the only thing ingest
                    # will later trust for upload_id -> (bucket, key) resolution.
                    principal = _claims_from_headers(self.headers)
                    for field in ("upload_id", "bucket", "object_key"):
                        if not body.get(field):
                            raise KeyError(field)
                    upload_id = str(body["upload_id"])
                    if upload_records.get(principal.tenant_id, upload_id) is not None:
                        self._send(409, {"error": "upload_id already registered"})
                        return
                    try:
                        declared_length = (
                            int(body["content_length"])
                            if body.get("content_length") is not None
                            else None
                        )
                    except (TypeError, ValueError):
                        declared_length = None
                    record = build_upload_record(
                        tenant_id=principal.tenant_id,
                        upload_id=upload_id,
                        user_id=principal.user_id,
                        bucket=str(body["bucket"]),
                        object_key=str(body["object_key"]),
                        content_type=str(body.get("content_type") or ""),
                        content_length=declared_length,
                        filename=str(body.get("filename") or ""),
                        ttl_seconds=_upload_record_ttl_seconds(),
                    )
                    upload_records.save(record)
                    self._send(201, {"tenant_id": principal.tenant_id, **record.public()})
                elif path == "/internal/ingest":
                    principal = _claims(body)
                    for field in ("collection_id", "source_id", "document_id"):
                        if not body.get(field):
                            raise KeyError(field)
                    # 0045: an upload_id resolves bucket/key from the server-issued provenance
                    # record (one-time-use, expiring) instead of trusting the caller's raw ref.
                    upload_record = None
                    upload_id = str(body.get("upload_id") or "")
                    if upload_id:
                        upload_record = upload_records.get(principal.tenant_id, upload_id)
                        if upload_record is None:
                            self._send(
                                200,
                                _failed_ingest_response(body, "unknown upload_id for this tenant"),
                            )
                            return
                        if upload_record.consumed_at:
                            self._send(
                                200,
                                _failed_ingest_response(body, "upload already consumed"),
                            )
                            return
                        if upload_record.is_expired():
                            self._send(200, _failed_ingest_response(body, "upload record expired"))
                            return
                        record_ref = f"s3://{upload_record.bucket}/{upload_record.object_key}"
                        if body.get("document_ref") and str(body["document_ref"]) != record_ref:
                            self._send(
                                200,
                                _failed_ingest_response(
                                    body, "document_ref does not match the upload record"
                                ),
                            )
                            return
                        body["document_ref"] = record_ref
                    elif not body.get("document_ref"):
                        raise KeyError("document_ref")
                    elif os.environ.get("RAKU_REQUIRE_UPLOAD_RECORD") == "1" and str(
                        body["document_ref"]
                    ).startswith("s3://"):
                        # Strict provenance mode: raw s3 refs without a registered record are
                        # refused (flip after all upload clients send upload_id).
                        self._send(
                            200,
                            _failed_ingest_response(
                                body, "s3 ingest requires a registered upload_id"
                            ),
                        )
                        return
                    original_ref = str(body["document_ref"])
                    content_type = str(body.get("content_type") or "text/plain")
                    try:
                        _verify_upload_s3_ref(connector, original_ref, principal.tenant_id)
                    except Exception as verify_exc:
                        self._send(
                            200,
                            _failed_ingest_response(body, f"invalid s3 document_ref: {verify_exc}"),
                        )
                        return
                    try:
                        raw = connector.fetch(original_ref)
                    except Exception as fetch_exc:
                        # A document_ref the connector can't resolve (e.g. a file:// path from another
                        # container, or a bad data:/s3: ref) is a per-document INGEST failure, not a
                        # server fault — return a graceful failed IngestResponse (status=failed +
                        # failure_reason, chunk_count=0). The NestJS facade maps any non-2xx upstream to
                        # 502, so this MUST stay 2xx for the client to see the real reason.
                        self._send(
                            200,
                            _failed_ingest_response(
                                body, f"could not fetch document_ref: {fetch_exc}"
                            ),
                        )
                        return
                    mfg_meta = _mfg_metadata_from_body(
                        body, principal.tenant_id, str(body["document_id"])
                    )
                    # Original display filename (incl. Japanese): the registered upload record is the
                    # server-authoritative source; fall back to a caller-supplied filename. Persisted to
                    # Document.metadata so the /files list shows the real name, not the id (safeName_).
                    doc_filename = ""
                    if upload_record is not None:
                        doc_filename = getattr(upload_record, "filename", "") or ""
                    if not doc_filename:
                        doc_filename = str(body.get("filename") or "")
                    staged_ref = _stage_visual_upload_ref(
                        connector,
                        tenant_id=principal.tenant_id,
                        collection_id=str(body["collection_id"]),
                        document_id=str(body["document_id"]),
                        document_ref=original_ref,
                        raw=raw,
                        content_type=content_type,
                    )
                    job = system.ingest_document(
                        tenant_id=principal.tenant_id,
                        collection_id=str(body["collection_id"]),
                        source_id=str(body["source_id"]),
                        document_id=str(body["document_id"]),
                        document_ref=staged_ref,
                        raw=raw,
                        content_type=content_type,
                        manufacturing_metadata=mfg_meta,
                        filename=doc_filename,
                    )
                    # 0045: one-time consumption — a leaked ref/upload_id cannot be replayed.
                    # Failed jobs keep the record open so the same upload can be retried.
                    if upload_record is not None and job.status in {
                        "queued",
                        "running",
                        "succeeded",
                    }:
                        upload_records.mark_consumed(
                            principal.tenant_id, upload_id, job.ingestion_run_id
                        )
                    _enqueue_upload_ingest_if_needed(source_sync_queue, runs, job)
                    self._send(
                        202 if job.status in {"queued", "running", "succeeded"} else 200,
                        _ingest_response_json(job),
                    )
                elif path == "/internal/evaluations/sets":
                    self._send(201, eval_feedback.create_set(self._tenant_header(), body))
                elif path == "/internal/evaluations/runs":
                    principal = IdentityClaims(
                        tenant_id=self._tenant_header(),
                        user_id=self.headers.get("x-raku-user-id") or "eval",
                        groups=tuple(json.loads(self.headers.get("x-raku-groups") or "[]")),
                        roles=tuple(json.loads(self.headers.get("x-raku-roles") or "[]")),
                    )
                    self._send(
                        202, eval_feedback.create_run(self._tenant_header(), body, principal)
                    )
                elif path == "/internal/feedback":
                    result = eval_feedback.create_feedback(
                        self._tenant_header(),
                        body,
                        self.headers.get("x-raku-user-id") or "unknown",
                    )
                    # Also record a user rating of an answer into the manufacturing audit chain — the
                    # single source of truth the knowledge-improvement queue + low_rating KPI derive
                    # from. Without this the eval store held the rating in isolation and low-rating
                    # feedback never surfaced in the improvement queue (FR-MFG-012/021/028). Eval-job
                    # feedback stays in the eval store only. Best-effort: never fail the user's POST.
                    if str(body.get("subject") or "user") == "user" and body.get("answer_id"):
                        try:
                            manufacturing_system.record_answer_feedback(
                                principal=_claims_from_headers(self.headers),
                                rating=int(body.get("rating") or 0),
                                answer_correlation_id=str(body.get("answer_id") or ""),
                                comment=body.get("comment"),
                            )
                        except Exception:
                            pass
                    self._send(202, result)
                elif parts == ["internal", "real-estate", "metadata", "import"]:
                    self._send(202, real_estate_api.metadata_import(self._tenant_header(), body))
                elif parts == ["internal", "real-estate", "documents", "enrich"]:
                    self._send(200, real_estate_api.enrich_document(self._tenant_header(), body))
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "contract-question"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        real_estate_api.contract_question(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "repair-investigation"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        real_estate_api.repair_investigation(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "occupant-reply-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        real_estate_api.occupant_reply_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "owner-report-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        real_estate_api.owner_report_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "move-out-checklist-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        real_estate_api.move_out_checklist_draft(
                            self._tenant_header(), roles, body
                        ),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "real-estate", "workflows"]
                    and parts[3] == "restoration-explanation-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        real_estate_api.restoration_explanation_draft(
                            self._tenant_header(), roles, body
                        ),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "real-estate", "drafts"]
                    and parts[4] == "review"
                ):
                    reviewed = real_estate_api.review_draft(parts[3], body)
                    (
                        self._send(200, reviewed)
                        if reviewed
                        else self._send(404, {"error": "not found"})
                    )
                elif parts == ["internal", "investment", "metadata", "import"]:
                    self._send(202, investment_api.metadata_import(self._tenant_header(), body))
                elif parts == ["internal", "investment", "documents", "enrich"]:
                    self._send(200, investment_api.enrich_document(self._tenant_header(), body))
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "fund-question"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        investment_api.fund_question(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "rfp-response-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        investment_api.rfp_response_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "ddq-response-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        investment_api.ddq_response_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "inquiry-reply-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        investment_api.inquiry_reply_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "marketing-material-check"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        investment_api.marketing_material_check(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "monthly-commentary-draft"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        201,
                        investment_api.monthly_commentary_draft(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 4
                    and parts[:3] == ["internal", "investment", "workflows"]
                    and parts[3] == "compliance-rule-question"
                ):
                    roles = tuple(json.loads(self.headers.get("x-raku-roles") or "[]"))
                    self._send(
                        200,
                        investment_api.compliance_rule_question(self._tenant_header(), roles, body),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "investment", "drafts"]
                    and parts[4] == "review"
                ):
                    reviewed = investment_api.review_draft(parts[3], body)
                    (
                        self._send(200, reviewed)
                        if reviewed
                        else self._send(404, {"error": "not found"})
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "investment", "drafts"]
                    and parts[4] == "compliance-review"
                ):
                    reviewed = investment_api.compliance_review(parts[3], body)
                    (
                        self._send(200, reviewed)
                        if reviewed
                        else self._send(404, {"error": "not found"})
                    )
                elif (
                    len(parts) == 5
                    and parts[:2] == ["internal", "industries"]
                    and parts[3:] == ["metadata", "validate"]
                ):
                    self._send(200, industry_api.validate_metadata(parts[2], body))
                elif (
                    len(parts) == 5
                    and parts[:2] == ["internal", "industries"]
                    and parts[3:] == ["documents", "enrich"]
                ):
                    self._send(
                        200, industry_api.enrich_document(self._tenant_header(), parts[2], body)
                    )
                elif (
                    len(parts) == 6
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "workflows"
                    and parts[5] == "run"
                ):
                    self._send(
                        200,
                        industry_api.run_workflow(
                            self._tenant_header(),
                            self.headers.get("x-raku-user-id") or "",
                            parts[2],
                            parts[4],
                            body,
                        ),
                    )
                elif (
                    len(parts) == 6
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "drafts"
                    and parts[5] == "review"
                ):
                    reviewed = industry_api.review_draft(
                        self._tenant_header(),
                        self.headers.get("x-raku-user-id") or "",
                        parts[2],
                        parts[4],
                        body,
                    )
                    (
                        self._send(200, reviewed)
                        if reviewed
                        else self._send(404, {"error": "not found"})
                    )
                elif (
                    len(parts) == 5
                    and parts[:2] == ["internal", "industries"]
                    and parts[3] == "drafts"
                ):
                    self._send(
                        201,
                        industry_api.create_draft(
                            self._tenant_header(),
                            self.headers.get("x-raku-user-id") or "",
                            parts[2],
                            parts[4],
                            body,
                        ),
                    )
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "ingestion-runs"]
                    and parts[3] == "retry"
                ):
                    tenant_id = self._tenant_header()
                    run = system.ingestion_runs.get_for_tenant(tenant_id, parts[2])
                    if run is None:
                        self._send(404, {"error": "not found"})
                        return
                    if not run.document_ref:
                        self._send(400, {"error": "ingestion run has no document_ref"})
                        return
                    raw = connector.fetch(run.document_ref)
                    retried = system.retry_ingestion_run(
                        tenant_id=tenant_id,
                        ingestion_run_id=run.ingestion_run_id,
                        raw=raw,
                    )
                    if retried is None:
                        self._send(404, {"error": "not found"})
                    else:
                        _enqueue_upload_ingest_if_needed(source_sync_queue, runs, retried)
                        self._send(
                            202 if retried.status in {"queued", "running", "succeeded"} else 200,
                            _ingest_response_json(retried),
                        )
                elif parts == ["internal", "oauth", "google", "callback"]:
                    # 021-gdrive: exchange the auth code, persist the refresh token, record a
                    # connection. tenant is the header identity (NEVER the body).
                    tenant_id = self._tenant_header()
                    try:
                        result = _oauth_google_callback(
                            tenant_id,
                            body,
                            secret_store=secret_store,
                            oauth_connections=oauth_connections,
                        )
                    except oauth_token_resolver.OAuthConfigError as exc:
                        self._send(502, {"error": str(exc)})
                        return
                    except (ValueError, oauth_token_resolver.OAuthExchangeError) as exc:
                        self._send(400, {"error": str(exc)})
                        return
                    self._send(200, result)
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "sources"]
                    and parts[3] in {"test", "test-connection"}
                ):
                    tenant_id = self._tenant_header()
                    try:
                        self._send(
                            200,
                            source_sync_service.test_connection(
                                tenant_id=tenant_id,
                                source_id=parts[2],
                                body=body,
                            ),
                        )
                    except KeyError:
                        self._send(404, {"error": "datasource not found"})
                    except Exception as exc:
                        self._send(400, {"ok": False, "error": str(exc)})
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "sources"]
                    and parts[3] == "preview"
                ):
                    tenant_id = self._tenant_header()
                    try:
                        self._send(
                            200,
                            source_sync_service.preview_source(
                                tenant_id=tenant_id,
                                source_id=parts[2],
                                body=body,
                            ),
                        )
                    except KeyError:
                        self._send(404, {"error": "datasource not found"})
                    except Exception as exc:
                        self._send(400, {"error": str(exc)})
                elif (
                    len(parts) == 4 and parts[:2] == ["internal", "sources"] and parts[3] == "sync"
                ):
                    tenant_id = self._tenant_header()
                    source_id = parts[2]
                    try:
                        response, message, created = source_sync_service.request_source_sync(
                            tenant_id=tenant_id,
                            source_id=source_id,
                            body=body,
                            requested_by=self.headers.get("x-raku-user-id") or "",
                        )
                    except KeyError:
                        self._send(404, {"error": "datasource not found"})
                        return
                    if source_sync_queue is not None:
                        if created:
                            message_id = source_sync_queue.enqueue_message(message.to_dict())
                            run = runs.get_for_tenant(tenant_id, response["sync_run_id"])
                            if run is not None:
                                runs.mark_message_id(run, message_id)
                            response["sqs_message_id"] = message_id
                        response["queued"] = True
                        self._send(202, response)
                    else:
                        executed = source_sync_service.execute_source_sync(message)
                        executed["queued"] = False
                        self._send(202, executed)
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "admin", "provider-policies"]
                    and parts[4] == "validate"
                ):
                    self._send(
                        200,
                        admin_settings.validate_provider_policy(
                            self._tenant_header(), parts[3], body
                        ),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "admin", "retrieval-profiles"]
                    and parts[4] == "benchmark"
                ):
                    self._send(
                        202,
                        admin_settings.benchmark_retrieval_profile(
                            self._tenant_header(), parts[3], body
                        ),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "admin", "collections"]
                    and parts[4] == "reindex"
                ):
                    document_ids = [str(v) for v in (body.get("document_ids") or [])]
                    plan = system.reindex.create_plan(
                        tenant_id=self._tenant_header(),
                        collection_id=parts[3],
                        source_id=str(body.get("source_id") or ""),
                        document_ids=document_ids,
                        reason=str(body.get("reason") or "manual"),
                        created_by=self.headers.get("x-raku-user-id") or "",
                        target_parser_version=str(body.get("target_parser_version") or ""),
                        target_chunking_config_version=str(
                            body.get("target_chunking_config_version") or ""
                        ),
                        target_embedding_model_version=str(
                            body.get("target_embedding_model_version") or ""
                        ),
                    )
                    self._send(202, _reindex_response_json(plan))
                else:
                    self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": f"missing field: {exc}"})
            except InvalidTransitionError as exc:
                # Out-of-order lifecycle transition (e.g. approve before assign) — a client/state
                # conflict, not a server fault. Surface 409 so the facade returns a real 4xx, not 502.
                self._send(409, {"error": str(exc)})
            except PermissionError as exc:
                self._send(403, {"error": str(exc)})
            except ValueError as exc:
                # Invalid input (e.g. an unknown DraftType, missing reviewer, bad decision).
                self._send(422, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - surface as 500 to the facade
                self._send(500, {"error": str(exc)})

        def do_PUT(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if not self._internal_auth_ok(path):
                    return
                body = self._body()
                parts = [unquote(p) for p in path.split("/") if p]
                if len(parts) == 4 and parts[:3] == [
                    "internal",
                    "chat",
                    "source-exposure-policies",
                ]:
                    self._send_result(
                        chatbot.upsert_source_policy(
                            _claims_from_headers(self.headers), parts[3], body
                        )
                    )
                elif (
                    len(parts) == 6
                    and parts[:3] == ["internal", "chat", "scenarios"]
                    and parts[4] == "versions"
                ):
                    self._send_result(
                        chatbot.upsert_scenario_version(
                            _claims_from_headers(self.headers), parts[3], parts[5], body
                        )
                    )
                elif (
                    len(parts) == 6
                    and parts[:3] == ["internal", "phone", "scenarios"]
                    and parts[4] == "versions"
                ):
                    self._send_result(
                        phone.upsert_scenario_version(
                            _claims_from_headers(self.headers), parts[3], parts[5], body
                        )
                    )
                elif (
                    len(parts) == 4
                    and parts[:2] == ["internal", "admin"]
                    and parts[2] in admin_settings._id_fields
                ):
                    self._send(
                        200,
                        admin_settings.upsert_resource(
                            self._tenant_header(),
                            parts[2],
                            parts[3],
                            body,
                            actor=self.headers.get("x-raku-user-id") or "unknown",
                        ),
                    )
                elif len(parts) == 5 and parts[:3] == ["internal", "admin", "lexicon"]:
                    principal = _claims_from_headers(self.headers)
                    try:
                        values = lexicon.update(
                            principal.tenant_id,
                            parts[3],
                            parts[4],
                            list(body.get("values") or []),
                            actor_id=principal.user_id,
                        )
                    except LexiconError as exc:
                        self._send(422, {"error": exc.code})
                        return
                    self._send(
                        200,
                        {"namespace": parts[3], "key": parts[4], "values": list(values)},
                    )
                elif len(parts) == 3 and parts[:2] == ["internal", "admin"] and parts[2] == "acl":
                    self._send(
                        200,
                        admin_settings.update_acl(
                            self._tenant_header(),
                            body,
                            actor=self.headers.get("x-raku-user-id") or "unknown",
                        ),
                    )
                elif (
                    len(parts) == 3 and parts[:2] == ["internal", "admin"] and parts[2] == "budgets"
                ):
                    self._send(
                        200,
                        admin_settings.update_budgets(
                            self._tenant_header(),
                            body,
                            actor=self.headers.get("x-raku-user-id") or "unknown",
                        ),
                    )
                elif parts == ["internal", "manufacturing", "policy", "data-use"]:
                    principal = _claims_from_headers(self.headers)
                    self._send(
                        200,
                        _data_use_policy_json(
                            manufacturing_system.update_data_use_policy(
                                tenant_id=principal.tenant_id,
                                patch=body,
                                actor=principal,
                            )
                        ),
                    )
                elif (
                    len(parts) == 5
                    and parts[:3] == ["internal", "manufacturing", "documents"]
                    and parts[4] == "metadata"
                ):
                    principal = _claims_from_headers(self.headers)
                    metadata = _mfg_metadata_from_body(body, principal.tenant_id, parts[3])
                    if metadata is None:
                        raise KeyError("manufacturing")
                    updated = manufacturing_system.update_metadata(
                        tenant_id=principal.tenant_id,
                        document_id=parts[3],
                        metadata=metadata,
                    )
                    self._send(
                        200,
                        _jsonable(
                            {
                                "document_id": parts[3],
                                "manufacturing_metadata": updated,
                                "approval": {
                                    "approval_status": updated.approval_status,
                                    "effective_date": updated.effective_date,
                                    "approval_source": updated.approval_source,
                                },
                            }
                        ),
                    )
                else:
                    self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": f"missing field: {exc}"})
            except Exception as exc:  # pragma: no cover - surface as 500 to the facade
                self._send(500, {"error": str(exc)})

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                path = urlparse(self.path).path
                if not self._internal_auth_ok(path):
                    return
                parts = [unquote(p) for p in path.split("/") if p]
                if len(parts) == 3 and parts[:2] == ["internal", "documents"]:
                    tenant_id = self._tenant_header()
                    document_id = parts[2]
                    result = system.deletion.delete(tenant_id, document_id)
                    self._send(
                        202,
                        {
                            "job_id": f"delete_{document_id}",
                            "document_id": document_id,
                            "status": "succeeded",
                            "tombstoned_chunks": result.tombstoned_chunks,
                            "invalidated_cache_entries": result.invalidated_cache_entries,
                            "purged_chunks": result.purged_chunks,
                            "tombstoned_crops": result.tombstoned_crops,
                            "invalidated_visual_cache_entries": result.invalidated_visual_cache_entries,
                            "tombstoned_visual_assets": result.tombstoned_visual_assets,
                            "tombstoned_visual_regions": result.tombstoned_visual_regions,
                            "tombstoned_visual_embeddings": result.tombstoned_visual_embeddings,
                        },
                    )
                else:
                    self._send(404, {"error": "not found"})
            except KeyError as exc:
                self._send(400, {"error": f"missing header: {exc}"})
            except Exception as exc:  # pragma: no cover - surface as 500 to the facade
                self._send(500, {"error": str(exc)})

        def log_message(self, *_args) -> None:  # quiet
            return

    return Handler


def _start_auto_sync_scheduler(dsn: str, port: int) -> None:
    """S2-1 (#0034): background thread that executes stored `sync_schedule` values.

    - Discovery reads the 0019 registry via a PRIVATE psycopg connection (per-source re-resolution
      stays RLS-checked through the normal repository `get`).
    - Firing POSTs the EXISTING internal manual-sync route on 127.0.0.1 with a slot-scoped
      idempotency key, so scheduled syncs reuse the exact run/queue/dedup machinery manual syncs
      have — and never touch the request thread's connection or stores.
    """
    import threading
    import urllib.request

    from raku_rag.services.sync_scheduler import AutoSyncScheduler

    interval = max(15, int(os.environ.get("RAKU_AUTO_SYNC_INTERVAL_SECONDS", "60")))

    def _log(event: str, **fields: object) -> None:
        print(json.dumps({"event": event, **{k: str(v) for k, v in fields.items()}}), flush=True)

    def _trigger(tenant_id: str, source_id: str, idempotency_key: str) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/internal/manufacturing/sources/{quote(source_id)}/sync",
            data=json.dumps(
                {"idempotency_key": idempotency_key, "requested_by": "auto-sync-scheduler"}
            ).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-raku-tenant-id": tenant_id,
                "x-raku-user-id": "auto-sync-scheduler",
                "x-raku-groups": "[]",
                "x-raku-roles": "[]",
                "X-Internal-Auth": _INTERNAL_AUTH_SECRET,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def _run() -> None:
        try:
            import psycopg

            from raku_rag.persistence.postgres import _set_app_role

            conn = psycopg.connect(dsn, autocommit=True)
            # Same posture as every other connection: drop to the non-owner raku_app role so RLS
            # governs the scheduler too (its registry read escape is the explicit GUC policy).
            with conn.cursor() as cur:
                _set_app_role(conn, cur)
            runtime_settings = settings_from_env()
            repo = PostgresDataSourceRepository(conn, secret_store_from_settings(runtime_settings))
        except Exception as exc:  # noqa: BLE001 — scheduler must never take the server down
            _log("auto_sync.disabled", reason=f"scheduler_connection_failed: {exc}")
            return
        scheduler = AutoSyncScheduler(
            list_scheduled=repo.list_scheduled,
            get_source=repo.get,
            trigger=_trigger,
            prune=repo.remove_schedule,
            log=_log,
        )
        _log("auto_sync.started", interval_seconds=interval)
        import time as _time

        while True:
            try:
                scheduler.tick()
            except Exception as exc:  # noqa: BLE001
                _log("auto_sync.tick_error", error=str(exc))
            _time.sleep(interval)

    threading.Thread(target=_run, name="auto-sync-scheduler", daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description="raku-rag answer-service (ProductionSystem over HTTP)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("ANSWER_SERVICE_PORT", "8088")))
    ap.add_argument("--seed", action="store_true", help="seed a demo tenant on startup")
    ap.add_argument(
        "--reset-demo-db",
        action="store_true",
        help="truncate a local disposable demo DB before seeding; refuses non-local DSNs",
    )
    args = ap.parse_args()

    dsn = os.environ.get("POSTGRES_URL", DEFAULT_DSN)
    if args.reset_demo_db:
        _assert_demo_reset_allowed(dsn)
    # Read RAKU_* runtime knobs (embedding provider, llm provider, thresholds, …) from the environment.
    # Without this ProductionSystem falls back to Settings() defaults and SILENTLY ignores every env
    # override — e.g. RAKU_EMBEDDING_PROVIDER / RAKU_LLM_PROVIDER set by the deploy would do nothing.
    system = ProductionSystem(dsn, settings=settings_from_env(), reset=args.reset_demo_db)
    if args.seed:
        seed(system)
        print(f"seeded demo tenant; ProductionSystem on {dsn}", flush=True)

    # Bind host: default loopback for local/dev safety; in the container set ANSWER_SERVICE_HOST=0.0.0.0
    # so the (SG/subnet-isolated) internal ALB health check can reach the task over its ENI — a
    # 127.0.0.1 bind is unreachable from the load balancer and ECS kills the task on failed health checks.
    host = os.environ.get("ANSWER_SERVICE_HOST", "127.0.0.1")
    httpd = HTTPServer((host, args.port), make_handler(system))
    print(f"answer-service listening on http://{host}:{args.port} (/internal/answer)", flush=True)
    # S2-1 (#0034): the auto-sync scheduler runs ONLY in the real server process (never in tests
    # importing make_handler). It owns a private DB connection and fires syncs through this
    # server's own internal HTTP route, so it shares no state with request handling.
    if os.environ.get("RAKU_AUTO_SYNC_ENABLED", "1") == "1":
        _start_auto_sync_scheduler(dsn, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


if __name__ == "__main__":
    main()
