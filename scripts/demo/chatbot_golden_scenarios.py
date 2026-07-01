#!/usr/bin/env python3
"""Run ChatBot golden scenarios against a local or deployed /v1 API.

The runner is deliberately stdlib-only. It checks the behavior that matters for an internal RAG
chatbot: enabled collection scope, answer/handoff outcome, citations, answer completeness terms, and
forbidden leakage terms. It does not print tokens or raw retrieved context.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

DEFAULT_DATASET = Path(__file__).with_name("chatbot_golden_scenarios.json")
SUPPORTED_SCHEMA_VERSIONS = {
    "chatbot-golden-scenarios/v1",
    "chatbot-golden-scenarios/v2",
}


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    parent_scenario_id: str
    turn_type: str
    quick_reply_value: str
    category: str
    expected_behavior: str
    passed: bool
    failures: tuple[str, ...]
    failure_kinds: tuple[str, ...]
    ai_action: str
    answerable: bool
    no_answer_reason: str
    cited_document_ids: tuple[str, ...]
    expected_citation_hit: bool
    required_terms_hit: bool
    required_sections_hit: bool
    answer_chars: int
    latency_ms: int
    correlation_id: str


class ScenarioConfigError(ValueError):
    pass


class HttpJsonError(RuntimeError):
    def __init__(self, method: str, path: str, status: int | None, message: str) -> None:
        self.method = method
        self.path = path
        self.status = status
        super().__init__(f"{method} {path} failed: {status or 'network'} {message}")


def normalize_api_base(value: str) -> str:
    """Normalize a user supplied base URL to an origin + /v1 API base."""
    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ScenarioConfigError("API base URL is empty")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ScenarioConfigError(f"invalid API base URL: {value!r}")
    if parsed.path.endswith("/v1"):
        return raw
    return f"{parsed.scheme}://{parsed.netloc}/v1"


def load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_dataset(data)
    return data


def validate_dataset(data: dict[str, Any]) -> None:
    if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise ScenarioConfigError("unsupported schema_version")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ScenarioConfigError("dataset must contain at least one scenario")
    ids: set[str] = set()
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            raise ScenarioConfigError(f"scenario #{index + 1} must be an object")
        scenario_id = str(scenario.get("id") or "")
        if not scenario_id:
            raise ScenarioConfigError(f"scenario #{index + 1} is missing id")
        if scenario_id in ids:
            raise ScenarioConfigError(f"duplicate scenario id: {scenario_id}")
        ids.add(scenario_id)
        if not str(scenario.get("question") or "").strip():
            raise ScenarioConfigError(f"{scenario_id}: question is required")
        behavior = str(scenario.get("expected_behavior") or "")
        if behavior not in {"answer", "handoff", "clarification"}:
            raise ScenarioConfigError(
                f"{scenario_id}: expected_behavior must be answer, handoff, or clarification"
            )
        citation_expected, citation_acceptable = _citation_expectations(scenario)
        if behavior == "answer" and not (citation_expected or citation_acceptable):
            raise ScenarioConfigError(f"{scenario_id}: answer scenarios require expected citations")
        sections = scenario.get("required_sections")
        if sections is not None and not isinstance(sections, list):
            raise ScenarioConfigError(f"{scenario_id}: required_sections must be a list")
        quick_reply_checks = scenario.get("quick_reply_checks")
        if quick_reply_checks is not None:
            if not isinstance(quick_reply_checks, list):
                raise ScenarioConfigError(f"{scenario_id}: quick_reply_checks must be a list")
            for check_index, check in enumerate(quick_reply_checks):
                if not isinstance(check, dict):
                    raise ScenarioConfigError(
                        f"{scenario_id}: quick_reply_checks[{check_index}] must be an object"
                    )
                value = str(check.get("value") or check.get("message") or "").strip()
                if not value:
                    raise ScenarioConfigError(
                        f"{scenario_id}: quick_reply_checks[{check_index}] requires value"
                    )
                check_behavior = str(check.get("expected_behavior") or "answer")
                if check_behavior not in {"answer", "handoff", "clarification"}:
                    raise ScenarioConfigError(
                        f"{scenario_id}: quick_reply_checks[{check_index}] has invalid "
                        "expected_behavior"
                    )


def policy_payload(collection_id: str, dataset: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    configured = dict(dataset.get("policy") or {})
    dataset_collection = str(configured.get("collection_id") or dataset.get("collection_id") or "")
    configured_policy_id = str(configured.get("policy_id") or "")
    if not configured_policy_id or configured_policy_id == f"chat-internal:{dataset_collection}":
        policy_id = f"chat-internal:{collection_id}"
    else:
        policy_id = configured_policy_id
    payload = {
        "policy_id": policy_id,
        "source_id": "",
        "collection_id": collection_id,
        "exposure_mode": "internal_authenticated",
        "allowed_channels": ["web_chat"],
        "allowed_intents": ["rag_question"],
        "require_approved_effective": True,
        "allow_obsolete_primary_evidence": False,
        "status": "active",
        **configured,
    }
    payload["policy_id"] = policy_id
    payload["collection_id"] = collection_id
    payload["source_id"] = ""
    return policy_id, payload


def scenarios_with_defaults(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    min_answer_chars = int(dataset.get("default_min_answer_chars") or 0)
    min_citations = int(dataset.get("default_min_citations") or 1)
    default_sections = list(dataset.get("default_required_sections") or [])
    scenarios: list[dict[str, Any]] = []
    for raw in dataset["scenarios"]:
        scenario = dict(raw)
        if scenario.get("quick_reply_checks"):
            followups: list[dict[str, Any]] = []
            expected_citations, acceptable_citations = _citation_expectations(scenario)
            for raw_check in scenario["quick_reply_checks"]:
                check = dict(raw_check)
                check.setdefault("expected_behavior", "answer")
                if check.get("expected_behavior") == "answer":
                    check.setdefault("min_answer_chars", min_answer_chars)
                    check.setdefault("min_citations", scenario.get("min_citations", min_citations))
                    if expected_citations and not (
                        check.get("expected_document_ids") or check.get("required_citations")
                    ):
                        check["expected_document_ids"] = list(expected_citations)
                    if acceptable_citations and not (
                        check.get("acceptable_document_ids") or check.get("acceptable_citations")
                    ):
                        check["acceptable_document_ids"] = list(acceptable_citations)
                    if default_sections and "required_sections" not in check:
                        check["required_sections"] = list(default_sections)
                followups.append(check)
            scenario["quick_reply_checks"] = followups
        if scenario.get("expected_behavior") == "answer":
            scenario.setdefault("min_answer_chars", min_answer_chars)
            scenario.setdefault("min_citations", min_citations)
            if default_sections and "required_sections" not in scenario:
                scenario["required_sections"] = list(default_sections)
        scenarios.append(scenario)
    return scenarios


def token_headers(token: str, api_key: str = "local-dev-key") -> dict[str, str]:
    if token.count(".") == 2:
        return {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
        }
    return {
        "authorization": f"Bearer {api_key}",
        "x-user-token": token,
        "content-type": "application/json",
    }


def http_json(
    method: str,
    base_url: str,
    path: str,
    *,
    token: str | None = None,
    api_key: str = "local-dev-key",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if token:
        headers.update(token_headers(token, api_key))
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        message = _http_error_summary(raw)
        raise HttpJsonError(method.upper(), path, exc.code, message) from exc
    except URLError as exc:
        raise HttpJsonError(method.upper(), path, None, str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise HttpJsonError(method.upper(), path, None, "invalid JSON response") from exc


def mint_local_dev_token(web_base: str, *, tenant_id: str, user_id: str, timeout: float) -> str:
    base = web_base.rstrip("/")
    body = json.dumps({"tenant_id": tenant_id, "user_id": user_id}).encode("utf-8")
    req = Request(
        f"{base}/api/dev-token",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except Exception as exc:  # pragma: no cover - exercised by CLI only
        raise RuntimeError(f"could not mint local dev token from {base}/api/dev-token") from exc
    token = str(payload.get("token") or "")
    if not token:
        raise RuntimeError("local dev token response did not contain token")
    return token


def ensure_collection_policy(
    base_url: str,
    token: str,
    api_key: str,
    dataset: dict[str, Any],
    collection_id: str,
    timeout: float,
) -> None:
    policy_id, payload = policy_payload(collection_id, dataset)
    http_json(
        "PUT",
        base_url,
        f"/chat/source-exposure-policies/{policy_id}",
        token=token,
        api_key=api_key,
        body=payload,
        timeout=timeout,
    )


def run_scenario(
    base_url: str,
    token: str,
    api_key: str,
    scenario: dict[str, Any],
    *,
    collection_id: str,
    timeout: float,
) -> ScenarioResult:
    return run_scenario_results(
        base_url,
        token,
        api_key,
        scenario,
        collection_id=collection_id,
        timeout=timeout,
    )[0]


def run_scenario_results(
    base_url: str,
    token: str,
    api_key: str,
    scenario: dict[str, Any],
    *,
    collection_id: str,
    timeout: float,
) -> list[ScenarioResult]:
    start = time.perf_counter()
    response = http_json(
        "POST",
        base_url,
        "/chat/sessions",
        token=token,
        api_key=api_key,
        body={
            "channel": "web_chat",
            "collection_id": collection_id,
            "initial_message": str(scenario["question"]),
            "metadata": {"eval_scenario_id": scenario["id"]},
        },
        timeout=timeout,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    initial = evaluate_response(scenario, response, latency_ms=latency_ms)
    results = [initial]
    for check in _quick_reply_checks(scenario):
        results.append(
            run_quick_reply_check(
                base_url,
                token,
                api_key,
                scenario,
                check,
                response,
                collection_id=collection_id,
                timeout=timeout,
            )
        )
    return results


def run_quick_reply_check(
    base_url: str,
    token: str,
    api_key: str,
    parent_scenario: dict[str, Any],
    check: dict[str, Any],
    initial_response: dict[str, Any],
    *,
    collection_id: str,
    timeout: float,
) -> ScenarioResult:
    session_id = str(initial_response.get("session_id") or "")
    value = str(check.get("value") or check.get("message") or "").strip()
    scenario = _quick_reply_scenario(parent_scenario, check)
    offered_values = _offered_quick_reply_values(initial_response)
    require_offered = check.get("require_offered", True) is not False
    if require_offered and value not in offered_values:
        return _failed_result(
            scenario,
            kind="followup",
            message=f"quick reply value={value!r} was not offered by the initial answer",
            turn_type="quick_reply",
            parent_scenario_id=str(parent_scenario.get("id") or ""),
            quick_reply_value=value,
        )
    if not session_id:
        return _failed_result(
            scenario,
            kind="contract",
            message="initial ChatBot response did not include session_id for quick reply follow-up",
            turn_type="quick_reply",
            parent_scenario_id=str(parent_scenario.get("id") or ""),
            quick_reply_value=value,
        )

    start = time.perf_counter()
    response = http_json(
        "POST",
        base_url,
        f"/chat/sessions/{quote(session_id, safe='')}/messages",
        token=token,
        api_key=api_key,
        body={"message": value, "collection_id": collection_id, "stream": False},
        timeout=timeout,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return evaluate_response(
        scenario,
        response,
        latency_ms=latency_ms,
        turn_type="quick_reply",
        parent_scenario_id=str(parent_scenario.get("id") or ""),
        quick_reply_value=value,
    )


def evaluate_response(
    scenario: dict[str, Any],
    response: dict[str, Any],
    *,
    latency_ms: int = 0,
    turn_type: str = "initial",
    parent_scenario_id: str = "",
    quick_reply_value: str = "",
) -> ScenarioResult:
    assistant = response.get("assistant_message") if isinstance(response, dict) else {}
    rag = response.get("rag") if isinstance(response, dict) else {}
    assistant = assistant if isinstance(assistant, dict) else {}
    rag = rag if isinstance(rag, dict) else {}

    message = str(assistant.get("message") or "")
    ai_action = str(assistant.get("ai_action") or "")
    answerable = bool(rag.get("answerable"))
    no_answer_reason = str(rag.get("no_answer_reason") or "")
    citations = _extract_citations(assistant, rag)
    cited_document_ids = tuple(
        dict.fromkeys(str(c.get("document_id") or "") for c in citations if c.get("document_id"))
    )
    failures: list[str] = []
    failure_kinds: list[str] = []
    expected_behavior = str(scenario.get("expected_behavior") or "")
    expected_citations, acceptable_citations = _citation_expectations(scenario)
    citation_hit = True
    terms_hit = True
    sections_hit = True

    if expected_behavior == "answer":
        if not answerable:
            _add_failure(
                failures,
                failure_kinds,
                "retrieval",
                f"expected answerable RAG turn, got no_answer_reason={no_answer_reason or '-'}",
            )
        if ai_action != "answer_with_citations":
            _add_failure(
                failures,
                failure_kinds,
                "contract",
                f"expected ai_action=answer_with_citations, got {ai_action or '-'}",
            )
        min_citations = int(scenario.get("min_citations") or 1)
        if len(cited_document_ids) < min_citations:
            _add_failure(
                failures,
                failure_kinds,
                "citation",
                f"expected at least {min_citations} citation(s), got {len(cited_document_ids)}",
            )
        allowed_citations = set(expected_citations) | set(acceptable_citations)
        if allowed_citations:
            citation_hit = bool(allowed_citations.intersection(cited_document_ids))
        if not citation_hit:
            expected = ", ".join(expected_citations) or "-"
            acceptable = ", ".join(acceptable_citations) or "-"
            _add_failure(
                failures,
                failure_kinds,
                "retrieval",
                "missing expected citation: "
                + expected
                + f"; acceptable alternates: {acceptable}"
                + f" (got {', '.join(cited_document_ids) or '-'})",
            )
        min_chars = int(scenario.get("min_answer_chars") or 0)
        if len(message) < min_chars:
            _add_failure(
                failures,
                failure_kinds,
                "answer_composition",
                f"answer too thin: {len(message)} chars < {min_chars}",
            )
        missing_terms = _missing_required_terms(message, scenario.get("required_terms") or [])
        terms_hit = not missing_terms
        if missing_terms:
            _add_failure(
                failures,
                failure_kinds,
                "answer_composition",
                "missing expected facts/terms: " + ", ".join(missing_terms),
            )
        missing_sections = _missing_required_sections(message, scenario.get("required_sections") or [])
        sections_hit = not missing_sections
        if missing_sections:
            _add_failure(
                failures,
                failure_kinds,
                "answer_composition",
                "missing expected answer sections: " + ", ".join(missing_sections),
            )
    elif expected_behavior == "handoff":
        if answerable or ai_action != "handoff":
            _add_failure(
                failures,
                failure_kinds,
                "safety_refusal",
                f"expected handoff/refusal, got answerable={answerable} ai_action={ai_action or '-'}"
            )
        allowed_reasons = {str(x) for x in (scenario.get("expected_no_answer_reasons") or [])}
        if allowed_reasons:
            if not no_answer_reason:
                _add_failure(
                    failures,
                    failure_kinds,
                    "safety_refusal",
                    "missing no_answer_reason; expected one of "
                    + ", ".join(sorted(allowed_reasons)),
                )
            elif no_answer_reason not in allowed_reasons:
                _add_failure(
                    failures,
                    failure_kinds,
                    "safety_refusal",
                    f"unexpected no_answer_reason={no_answer_reason}; expected one of "
                    + ", ".join(sorted(allowed_reasons)),
                )
    elif expected_behavior == "clarification":
        if answerable or ai_action != "ask_clarification":
            _add_failure(
                failures,
                failure_kinds,
                "clarification",
                f"expected clarification, got answerable={answerable} ai_action={ai_action or '-'}",
            )
    else:
        _add_failure(
            failures,
            failure_kinds,
            "contract",
            f"unsupported expected_behavior={expected_behavior}",
        )

    forbidden_hits = _present_terms(message, scenario.get("forbidden_terms") or [])
    if forbidden_hits:
        _add_failure(
            failures,
            failure_kinds,
            "security",
            "forbidden terms present: " + ", ".join(forbidden_hits),
        )

    max_latency_ms = int(scenario.get("max_latency_ms") or 0)
    if max_latency_ms and latency_ms > max_latency_ms:
        _add_failure(
            failures,
            failure_kinds,
            "latency",
            f"latency too high: {latency_ms}ms > {max_latency_ms}ms",
        )

    return ScenarioResult(
        scenario_id=str(scenario.get("id") or ""),
        parent_scenario_id=parent_scenario_id,
        turn_type=turn_type,
        quick_reply_value=quick_reply_value,
        category=str(scenario.get("category") or ""),
        expected_behavior=expected_behavior,
        passed=not failures,
        failures=tuple(failures),
        failure_kinds=tuple(dict.fromkeys(failure_kinds)),
        ai_action=ai_action,
        answerable=answerable,
        no_answer_reason=no_answer_reason,
        cited_document_ids=cited_document_ids,
        expected_citation_hit=citation_hit,
        required_terms_hit=terms_hit,
        required_sections_hit=sections_hit,
        answer_chars=len(message),
        latency_ms=latency_ms,
        correlation_id=str(response.get("correlation_id") or ""),
    )


def summarize_results(results: list[ScenarioResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    answer_results = [r for r in results if r.expected_behavior == "answer"]
    quick_reply_results = [r for r in results if r.turn_type == "quick_reply"]
    answerable = sum(1 for r in results if r.answerable)
    citation_hits = sum(1 for r in answer_results if r.cited_document_ids)
    expected_citation_hits = sum(1 for r in answer_results if r.expected_citation_hit)
    completeness_hits = sum(
        1 for r in answer_results if r.required_terms_hit and r.required_sections_hit
    )
    thin_answers = sum(
        1 for r in answer_results if r.answerable and r.answer_chars > 0 and r.answer_chars < 80
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "initial_count": sum(1 for r in results if r.turn_type == "initial"),
        "quick_reply_count": len(quick_reply_results),
        "quick_reply_pass_rate": _pass_rate(quick_reply_results),
        "answerable_rate": (answerable / total) if total else 0.0,
        "citation_hit_rate": (citation_hits / len(answer_results)) if answer_results else 0.0,
        "expected_citation_hit_rate": (
            expected_citation_hits / len(answer_results) if answer_results else 0.0
        ),
        "completeness_hit_rate": (
            completeness_hits / len(answer_results) if answer_results else 0.0
        ),
        "thin_answer_count": thin_answers,
        "handoff_count": sum(1 for r in results if r.ai_action == "handoff"),
        "p95_latency_ms": _p95([r.latency_ms for r in results]),
        "categories": _category_summary(results),
        "failure_kinds": _failure_kind_summary(results),
    }


def print_report(
    results: list[ScenarioResult],
    *,
    dataset: dict[str, Any] | None = None,
    profile: dict[str, str] | None = None,
    show_failures: bool = True,
) -> None:
    summary = summarize_results(results)
    print("=== ChatBot Golden Scenario Scorecard ===")
    if dataset is not None:
        identity = dataset_identity(dataset)
        print(f"  dataset           : {identity['dataset_id']}@{identity['dataset_version']}")
        print(f"  schema            : {identity['schema_version']}")
    if profile is not None:
        print(
            "  profile           : "
            f"{profile['profile_name']} "
            f"(embedding={profile['embedding_provider']}, "
            f"answer={profile['answer_profile']}, reranker={profile['reranker']})"
        )
    print(f"  total             : {summary['total']}")
    print(f"  passed            : {summary['passed']}")
    print(f"  failed            : {summary['failed']}")
    print(
        "  quick_replies     : "
        f"{summary['quick_reply_count']} "
        f"(pass_rate={summary['quick_reply_pass_rate']:.3f})"
    )
    print(f"  answerable_rate   : {summary['answerable_rate']:.3f}")
    print(f"  citation_hit_rate : {summary['citation_hit_rate']:.3f}")
    print(f"  expected_citation : {summary['expected_citation_hit_rate']:.3f}")
    print(f"  completeness_rate : {summary['completeness_hit_rate']:.3f}")
    print(f"  thin_answer_count : {summary['thin_answer_count']}")
    print(f"  p95_latency_ms    : {summary['p95_latency_ms']:.0f}")
    if summary["failure_kinds"]:
        print("  failure_kinds     : " + _format_count_map(summary["failure_kinds"]))
    print("")
    print(
        "status  turn    scenario                         expected  action                 "
        "ans  cites  chars"
    )
    print(
        "------  ------  -------------------------------  --------  ---------------------  "
        "---  -----  -----"
    )
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{status:<6}  {result.turn_type[:6]:<6}  {result.scenario_id[:31]:<31}  "
            f"{result.expected_behavior:<8}  {result.ai_action[:21]:<21}  "
            f"{str(result.answerable):<3}  {len(result.cited_document_ids):>5}  "
            f"{result.answer_chars:>5}"
        )
    if show_failures and any(not result.passed for result in results):
        print("")
        print("Failures:")
        for result in results:
            if result.passed:
                continue
            parent = f" parent={result.parent_scenario_id}" if result.parent_scenario_id else ""
            quick = f" quick_reply={result.quick_reply_value}" if result.quick_reply_value else ""
            print(f"- {result.scenario_id} [{result.turn_type}{parent}{quick}]:")
            for failure in result.failures:
                print(f"  - {failure}")


def dataset_identity(dataset: dict[str, Any]) -> dict[str, str]:
    return {
        "schema_version": str(dataset.get("schema_version") or ""),
        "dataset_id": str(dataset.get("dataset_id") or dataset.get("name") or "chatbot_golden"),
        "dataset_version": str(dataset.get("dataset_version") or "unversioned"),
        "evaluation_stage": str(dataset.get("evaluation_stage") or "smoke"),
    }


def profile_metadata(args: argparse.Namespace, dataset: dict[str, Any]) -> dict[str, str]:
    defaults = dict(dataset.get("default_profile") or {})
    return {
        "profile_name": str(
            args.profile_name
            or os.environ.get("RAKU_CHATBOT_EVAL_PROFILE")
            or defaults.get("profile_name")
            or "stg-smoke"
        ),
        "embedding_provider": str(
            args.embedding_provider
            or os.environ.get("RAKU_EMBEDDING_PROVIDER")
            or defaults.get("embedding_provider")
            or "unknown"
        ),
        "answer_profile": str(
            args.answer_profile
            or os.environ.get("RAKU_ANSWER_PROFILE")
            or os.environ.get("RAKU_ANSWER_LLM")
            or defaults.get("answer_profile")
            or "unknown"
        ),
        "reranker": str(
            args.reranker
            or os.environ.get("RAKU_RERANKER")
            or defaults.get("reranker")
            or "none"
        ),
    }


def build_run_payload(
    *,
    dataset: dict[str, Any],
    profile: dict[str, str],
    collection_id: str,
    results: list[ScenarioResult],
) -> dict[str, Any]:
    summary = summarize_results(results)
    return {
        "dataset": dataset_identity(dataset),
        "profile": profile,
        "collection_id": collection_id,
        "summary": summary,
        "readiness": readiness_summary(results, dataset),
        "results": [result.__dict__ for result in results],
    }


def readiness_summary(results: list[ScenarioResult], dataset: dict[str, Any]) -> dict[str, Any]:
    thresholds = dict(dataset.get("readiness_thresholds") or {})
    summary = summarize_results(results)
    refusal_results = [
        r
        for r in results
        if r.expected_behavior == "handoff" or r.category in {"safety_refusal", "security_refusal"}
    ]
    clarification_results = [
        r
        for r in results
        if r.expected_behavior == "clarification" or r.category == "ambiguous_clarification"
    ]
    refusal_pass_rate = _pass_rate(refusal_results)
    clarification_pass_rate = _pass_rate(clarification_results)
    measured = {
        "refusal_pass_rate": refusal_pass_rate,
        "safety_refusal_pass_rate": refusal_pass_rate,
        "clarification_pass_rate": clarification_pass_rate,
        "quick_reply_pass_rate": summary["quick_reply_pass_rate"],
        "expected_citation_hit_rate": summary["expected_citation_hit_rate"],
        "completeness_hit_rate": summary["completeness_hit_rate"],
        "p95_latency_ms": summary["p95_latency_ms"],
    }
    threshold_results: dict[str, bool] = {}
    for key, expected in thresholds.items():
        if key not in measured:
            continue
        value = measured[key]
        if key.endswith("_ms"):
            threshold_results[key] = float(value) <= float(expected)
        else:
            threshold_results[key] = float(value) >= float(expected)
    return {
        "label": str(dataset.get("readiness_label") or "customer-demo-readiness"),
        "measured": measured,
        "thresholds": thresholds,
        "threshold_results": threshold_results,
        "ready": bool(threshold_results) and all(threshold_results.values()) and summary["failed"] == 0,
    }


def _extract_citations(assistant: dict[str, Any], rag: dict[str, Any]) -> list[dict[str, Any]]:
    raw = assistant.get("citations") or rag.get("citations") or []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _quick_reply_checks(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in (scenario.get("quick_reply_checks") or []) if isinstance(item, dict)]


def _quick_reply_scenario(parent_scenario: dict[str, Any], check: dict[str, Any]) -> dict[str, Any]:
    value = str(check.get("value") or check.get("message") or "").strip()
    scenario = dict(parent_scenario)
    scenario.update(check)
    for parent_only_key in (
        "required_terms",
        "forbidden_terms",
        "expected_no_answer_reasons",
        "required_sections",
    ):
        if parent_only_key not in check:
            scenario.pop(parent_only_key, None)
    scenario["id"] = str(check.get("id") or f"{parent_scenario.get('id')}::quick_reply::{value}")
    scenario["category"] = str(check.get("category") or "quick_reply_followup")
    scenario["question"] = str(check.get("label") or value)
    scenario.setdefault("expected_behavior", "answer")
    return scenario


def _offered_quick_reply_values(response: dict[str, Any]) -> set[str]:
    assistant = response.get("assistant_message") if isinstance(response, dict) else {}
    assistant = assistant if isinstance(assistant, dict) else {}
    replies = assistant.get("quick_replies") or []
    values: set[str] = set()
    for reply in replies:
        if isinstance(reply, dict) and reply.get("value"):
            values.add(str(reply["value"]))
    return values


def _failed_result(
    scenario: dict[str, Any],
    *,
    kind: str,
    message: str,
    turn_type: str,
    parent_scenario_id: str = "",
    quick_reply_value: str = "",
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=str(scenario.get("id") or ""),
        parent_scenario_id=parent_scenario_id,
        turn_type=turn_type,
        quick_reply_value=quick_reply_value,
        category=str(scenario.get("category") or ""),
        expected_behavior=str(scenario.get("expected_behavior") or ""),
        passed=False,
        failures=(message,),
        failure_kinds=(kind,),
        ai_action="",
        answerable=False,
        no_answer_reason="",
        cited_document_ids=(),
        expected_citation_hit=False,
        required_terms_hit=False,
        required_sections_hit=False,
        answer_chars=0,
        latency_ms=0,
        correlation_id="",
    )


def _normalize_text(value: str) -> str:
    normalized = value.casefold()
    for old, new in (("〜", "-"), ("–", "-"), ("—", "-"), ("・", "."), ("·", "."), ("　", " ")):
        normalized = normalized.replace(old, new)
    return " ".join(normalized.split())


def _missing_required_terms(answer: str, terms: list[Any]) -> list[str]:
    answer_text = _normalize_text(answer)
    missing: list[str] = []
    for raw in terms:
        term = str(raw)
        if _normalize_text(term) not in answer_text:
            missing.append(term)
    return missing


def _missing_required_sections(answer: str, sections: list[Any]) -> list[str]:
    answer_text = _normalize_text(answer)
    missing: list[str] = []
    for raw in sections:
        if isinstance(raw, dict):
            label = str(raw.get("label") or raw.get("name") or "section")
            terms = [str(x) for x in (raw.get("terms") or [label])]
        else:
            label = str(raw)
            terms = [label]
        if not any(_normalize_text(term) in answer_text for term in terms):
            missing.append(label)
    return missing


def _present_terms(answer: str, terms: list[Any]) -> list[str]:
    answer_text = _normalize_text(answer)
    hits: list[str] = []
    for raw in terms:
        term = str(raw)
        if _normalize_text(term) in answer_text:
            hits.append(term)
    return hits


def _citation_expectations(scenario: dict[str, Any]) -> tuple[list[str], list[str]]:
    expected: list[str] = []
    acceptable: list[str] = []
    for key in ("required_citations", "expected_document_ids"):
        expected.extend(str(x) for x in (scenario.get(key) or []))
    for key in ("acceptable_citations", "acceptable_document_ids"):
        acceptable.extend(str(x) for x in (scenario.get(key) or []))
    return list(dict.fromkeys(expected)), list(dict.fromkeys(acceptable))


def _add_failure(failures: list[str], failure_kinds: list[str], kind: str, message: str) -> None:
    failures.append(message)
    failure_kinds.append(kind)


def _category_summary(results: list[ScenarioResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = summary.setdefault(result.category or "uncategorized", {"total": 0, "passed": 0})
        bucket["total"] += 1
        if result.passed:
            bucket["passed"] += 1
    return summary


def _failure_kind_summary(results: list[ScenarioResult]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        for kind in result.failure_kinds:
            summary[kind] = summary.get(kind, 0) + 1
    return dict(sorted(summary.items()))


def _format_count_map(values: dict[str, int]) -> str:
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _pass_rate(results: list[ScenarioResult]) -> float:
    if not results:
        return 1.0
    return sum(1 for result in results if result.passed) / len(results)


def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return float(ordered[index])


def _http_error_summary(raw: str) -> str:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw[:160]
    for key in ("error", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value[:160]
    return json.dumps({k: payload.get(k) for k in sorted(payload)[:5]}, ensure_ascii=False)[:160]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="scenario JSON file")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("API_BASE") or os.environ.get("RAKU_PROD_BASE_URL") or "http://localhost:3000/v1",
        help="API base URL; origin URLs are normalized to /v1",
    )
    parser.add_argument(
        "--web-base",
        default=os.environ.get("WEB_BASE") or "http://localhost:3002",
        help="web base used only to mint a local /api/dev-token when no token is supplied",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("RAKU_USER_TOKEN") or os.environ.get("RAKU_PROD_BEARER_TOKEN") or "",
        help="Cognito JWT or local user token. Prefer env vars so tokens do not enter shell history.",
    )
    parser.add_argument("--api-key", default=os.environ.get("RAKU_API_KEY") or "demo-api-key")
    parser.add_argument("--tenant", default=os.environ.get("DEMO_TENANT") or "demo")
    parser.add_argument("--user", default=os.environ.get("DEMO_USER") or "alice")
    parser.add_argument("--collection", default="", help="override dataset collection_id")
    parser.add_argument("--ensure-policy", action="store_true", help="upsert the collection-wide ChatBot policy before running")
    parser.add_argument("--no-dev-token", action="store_true", help="do not try to mint a local dev token")
    parser.add_argument("--validate-only", action="store_true", help="validate the dataset without calling any HTTP API")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json", action="store_true", help="print machine-readable result JSON")
    parser.add_argument("--output", default="", help="write machine-readable result JSON to this path")
    parser.add_argument("--profile-name", default="", help="label for this scorecard profile")
    parser.add_argument("--embedding-provider", default="", help="embedding provider label")
    parser.add_argument("--answer-profile", default="", help="answer/composer profile label")
    parser.add_argument("--reranker", default="", help="reranker profile label")
    parser.add_argument("--hide-failures", action="store_true", help="hide per-scenario failure details")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        dataset = load_dataset(Path(args.dataset))
        base_url = normalize_api_base(args.base_url)
        collection_id = args.collection or str(dataset.get("collection_id") or "")
        if not collection_id:
            raise ScenarioConfigError("collection_id is required")
        scenarios = scenarios_with_defaults(dataset)
        profile = profile_metadata(args, dataset)
        if args.validate_only:
            turn_count = sum(1 + len(_quick_reply_checks(scenario)) for scenario in scenarios)
            payload = {
                "status": "ok",
                "dataset": str(Path(args.dataset)),
                **dataset_identity(dataset),
                "profile": profile,
                "collection_id": collection_id,
                "scenario_count": len(scenarios),
                "turn_count": turn_count,
                "categories": sorted({str(item.get("category") or "") for item in scenarios}),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(
                    "dataset ok: "
                    f"{payload['scenario_count']} scenario(s), "
                    f"{payload['turn_count']} turn(s), "
                    f"collection_id={payload['collection_id']}"
                )
            return 0
        token = str(args.token or "")
        if not token and not args.no_dev_token:
            token = mint_local_dev_token(
                args.web_base,
                tenant_id=args.tenant,
                user_id=args.user,
                timeout=args.timeout,
            )
        if not token:
            raise ScenarioConfigError("set --token/RAKU_USER_TOKEN or allow local dev-token minting")
        if args.ensure_policy:
            ensure_collection_policy(base_url, token, args.api_key, dataset, collection_id, args.timeout)
        results = []
        for scenario in scenarios:
            results.extend(
                run_scenario_results(
                    base_url,
                    token,
                    args.api_key,
                    scenario,
                    collection_id=collection_id,
                    timeout=args.timeout,
                )
            )
    except (ScenarioConfigError, HttpJsonError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = build_run_payload(
        dataset=dataset,
        profile=profile,
        collection_id=collection_id,
        results=results,
    )
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_report(
            results,
            dataset=dataset,
            profile=profile,
            show_failures=not args.hide_failures,
        )
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
