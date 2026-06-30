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
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_DATASET = Path(__file__).with_name("chatbot_golden_scenarios.json")


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    category: str
    expected_behavior: str
    passed: bool
    failures: tuple[str, ...]
    ai_action: str
    answerable: bool
    no_answer_reason: str
    cited_document_ids: tuple[str, ...]
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
    if data.get("schema_version") != "chatbot-golden-scenarios/v1":
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
        if behavior not in {"answer", "handoff"}:
            raise ScenarioConfigError(f"{scenario_id}: expected_behavior must be answer or handoff")
        if behavior == "answer" and not scenario.get("required_citations"):
            raise ScenarioConfigError(f"{scenario_id}: answer scenarios require citations")


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
    scenarios: list[dict[str, Any]] = []
    for raw in dataset["scenarios"]:
        scenario = dict(raw)
        if scenario.get("expected_behavior") == "answer":
            scenario.setdefault("min_answer_chars", min_answer_chars)
            scenario.setdefault("min_citations", min_citations)
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
    return evaluate_response(scenario, response, latency_ms=latency_ms)


def evaluate_response(
    scenario: dict[str, Any],
    response: dict[str, Any],
    *,
    latency_ms: int = 0,
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
    expected_behavior = str(scenario.get("expected_behavior") or "")

    if expected_behavior == "answer":
        if not answerable:
            failures.append(f"expected answerable RAG turn, got no_answer_reason={no_answer_reason or '-'}")
        if ai_action != "answer_with_citations":
            failures.append(f"expected ai_action=answer_with_citations, got {ai_action or '-'}")
        min_citations = int(scenario.get("min_citations") or 1)
        if len(cited_document_ids) < min_citations:
            failures.append(f"expected at least {min_citations} citation(s), got {len(cited_document_ids)}")
        required_citations = [str(x) for x in (scenario.get("required_citations") or [])]
        if required_citations and not set(required_citations).intersection(cited_document_ids):
            failures.append(
                "missing required citation: "
                + ", ".join(required_citations)
                + f" (got {', '.join(cited_document_ids) or '-'})"
            )
        min_chars = int(scenario.get("min_answer_chars") or 0)
        if len(message) < min_chars:
            failures.append(f"answer too thin: {len(message)} chars < {min_chars}")
        missing_terms = _missing_required_terms(message, scenario.get("required_terms") or [])
        if missing_terms:
            failures.append("missing expected facts/terms: " + ", ".join(missing_terms))
    elif expected_behavior == "handoff":
        if answerable or ai_action != "handoff":
            failures.append(
                f"expected handoff/refusal, got answerable={answerable} ai_action={ai_action or '-'}"
            )
        allowed_reasons = {str(x) for x in (scenario.get("expected_no_answer_reasons") or [])}
        if allowed_reasons and no_answer_reason and no_answer_reason not in allowed_reasons:
            failures.append(
                f"unexpected no_answer_reason={no_answer_reason}; expected one of "
                + ", ".join(sorted(allowed_reasons))
            )
    else:
        failures.append(f"unsupported expected_behavior={expected_behavior}")

    forbidden_hits = _present_terms(message, scenario.get("forbidden_terms") or [])
    if forbidden_hits:
        failures.append("forbidden terms present: " + ", ".join(forbidden_hits))

    return ScenarioResult(
        scenario_id=str(scenario.get("id") or ""),
        category=str(scenario.get("category") or ""),
        expected_behavior=expected_behavior,
        passed=not failures,
        failures=tuple(failures),
        ai_action=ai_action,
        answerable=answerable,
        no_answer_reason=no_answer_reason,
        cited_document_ids=cited_document_ids,
        answer_chars=len(message),
        latency_ms=latency_ms,
        correlation_id=str(response.get("correlation_id") or ""),
    )


def summarize_results(results: list[ScenarioResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    answer_results = [r for r in results if r.expected_behavior == "answer"]
    answerable = sum(1 for r in results if r.answerable)
    citation_hits = sum(1 for r in answer_results if r.cited_document_ids)
    thin_answers = sum(
        1 for r in answer_results if r.answerable and r.answer_chars > 0 and r.answer_chars < 80
    )
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "answerable_rate": (answerable / total) if total else 0.0,
        "citation_hit_rate": (citation_hits / len(answer_results)) if answer_results else 0.0,
        "thin_answer_count": thin_answers,
        "handoff_count": sum(1 for r in results if r.ai_action == "handoff"),
        "p95_latency_ms": _p95([r.latency_ms for r in results]),
        "categories": _category_summary(results),
    }


def print_report(results: list[ScenarioResult], *, show_failures: bool = True) -> None:
    summary = summarize_results(results)
    print("=== ChatBot Golden Scenario Scorecard ===")
    print(f"  total             : {summary['total']}")
    print(f"  passed            : {summary['passed']}")
    print(f"  failed            : {summary['failed']}")
    print(f"  answerable_rate   : {summary['answerable_rate']:.3f}")
    print(f"  citation_hit_rate : {summary['citation_hit_rate']:.3f}")
    print(f"  thin_answer_count : {summary['thin_answer_count']}")
    print(f"  p95_latency_ms    : {summary['p95_latency_ms']:.0f}")
    print("")
    print("status  scenario                         expected  action                 ans  cites  chars")
    print("------  -------------------------------  --------  ---------------------  ---  -----  -----")
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{status:<6}  {result.scenario_id[:31]:<31}  "
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
            print(f"- {result.scenario_id}:")
            for failure in result.failures:
                print(f"  - {failure}")


def _extract_citations(assistant: dict[str, Any], rag: dict[str, Any]) -> list[dict[str, Any]]:
    raw = assistant.get("citations") or rag.get("citations") or []
    return [dict(item) for item in raw if isinstance(item, dict)]


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


def _present_terms(answer: str, terms: list[Any]) -> list[str]:
    answer_text = _normalize_text(answer)
    hits: list[str] = []
    for raw in terms:
        term = str(raw)
        if _normalize_text(term) in answer_text:
            hits.append(term)
    return hits


def _category_summary(results: list[ScenarioResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = summary.setdefault(result.category or "uncategorized", {"total": 0, "passed": 0})
        bucket["total"] += 1
        if result.passed:
            bucket["passed"] += 1
    return summary


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
        if args.validate_only:
            payload = {
                "status": "ok",
                "dataset": str(Path(args.dataset)),
                "collection_id": collection_id,
                "scenario_count": len(scenarios),
                "categories": sorted({str(item.get("category") or "") for item in scenarios}),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(
                    "dataset ok: "
                    f"{payload['scenario_count']} scenario(s), "
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
        results = [
            run_scenario(
                base_url,
                token,
                args.api_key,
                scenario,
                collection_id=collection_id,
                timeout=args.timeout,
            )
            for scenario in scenarios
        ]
    except (ScenarioConfigError, HttpJsonError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "summary": summarize_results(results),
                    "results": [result.__dict__ for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_report(results, show_failures=not args.hide_failures)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
