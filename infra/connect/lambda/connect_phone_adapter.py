"""024 L010-L012 — Amazon Connect → raku-rag phone-layer adapter (stdlib-only handler).

Invoked by the Contact Flow ("Invoke AWS Lambda function" block). This is a TRANSLATION layer
only (FR-L01): every conversational decision stays in the 022 orchestrator behind
`/internal/phone/*`; the adapter maps Connect events to `call_start` / `turn` / `hangup`
requests and flattens the response for flow branching.

Contract with the contact flow (all response values are strings — Connect requires a flat map):
    ok            "true" | "false"
    action        "continue" | "handoff" | "end_call" | "reject" | "error"
    speech_text   what the flow should say next (Polly)
    call_id       raku-rag call id (flow stores it as a contact attribute `raku_call_id`)
    ai_action     raw orchestrator action (logging/analytics)
    handoff_reason / handoff_destination / handoff_url   set when action == "handoff"

Config (env; *_SSM_PARAM / *_SECRET_ARN variants are fetched at cold start via boto3, which is
only imported then — unit tests run without boto3 by setting the direct env values):
    RAKU_INTERNAL_API_BASE        e.g. http://internal-...ap-northeast-1.elb.amazonaws.com
    RAKU_INTERNAL_AUTH_SECRET     shared secret for the internal boundary (X-Internal-Auth)
    RAKU_INTERNAL_AUTH_SECRET_ARN Secrets Manager ARN alternative
    RAKU_PHONE_DID_MAP            JSON: {"+815012345678": {"tenant_id": ..., "user_id": ...,
                                  "groups": [...], "collection_id": ..., "scenario_id": ...}}
    RAKU_PHONE_DID_MAP_SSM_PARAM  SSM parameter name alternative
    RAKU_PHONE_HANDOFF_URL_BASE   e.g. https://<web>/phone (operator screen-pop link)
    RAKU_PHONE_HTTP_TIMEOUT_SECONDS  default 6 (Connect Lambda invocations cap at 8s)

Security invariants (FR-L04, tested in tests/security/test_phone_gateway_role.py):
- The caller's raw E.164 number is masked HERE and never leaves the adapter (not in the API
  body, not in logs, not in returned attributes).
- The synthesized principal carries ONLY the `phone_gateway` service role.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

_FALLBACK_UNAVAILABLE = "申し訳ありません。この番号は現在ご利用いただけません。"
_FALLBACK_ERROR = "申し訳ありません。システムの確認が必要なため、担当者におつなぎするか、後ほどおかけ直しください。"
_TERMINAL_STATES = {"transferred", "completed", "abandoned", "failed"}

_cached_secret: str | None = None
_cached_did_map: dict | None = None


def mask_phone_number(value: str) -> str:
    """Same display contract as raku_rag.phone.redaction.mask_phone_number (kept dependency-free)."""
    digits = re.sub(r"[^\d+]", "", value or "")
    if not digits:
        return ""
    if len(digits) <= 6:
        return "*" * len(digits)
    head = digits[:3] if digits.startswith("+") else digits[:2]
    return f"{head}{'*' * 6}{digits[-4:]}"


def _internal_auth_secret() -> str:
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    direct = os.environ.get("RAKU_INTERNAL_AUTH_SECRET", "")
    if direct:
        _cached_secret = direct
        return direct
    arn = os.environ.get("RAKU_INTERNAL_AUTH_SECRET_ARN", "")
    if arn:
        import boto3  # lambda runtime provides it; unit tests never reach this branch

        client = boto3.client("secretsmanager")
        raw = client.get_secret_value(SecretId=arn)["SecretString"]
        # The stack stores this as JSON {"secret": "..."} (ECS injects the "secret" field);
        # accept both the JSON form and a plain string.
        try:
            parsed = json.loads(raw)
            _cached_secret = str(parsed.get("secret") or raw) if isinstance(parsed, dict) else raw
        except json.JSONDecodeError:
            _cached_secret = raw
        return _cached_secret
    _cached_secret = ""
    return ""


def _did_map() -> dict:
    global _cached_did_map
    if _cached_did_map is not None:
        return _cached_did_map
    raw = os.environ.get("RAKU_PHONE_DID_MAP", "")
    if not raw:
        param = os.environ.get("RAKU_PHONE_DID_MAP_SSM_PARAM", "")
        if param:
            import boto3  # lazy for the same reason as above

            ssm = boto3.client("ssm")
            raw = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    try:
        _cached_did_map = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        _cached_did_map = {}
    return _cached_did_map


def _normalize_number(value: str) -> str:
    return re.sub(r"[^\d+]", "", value or "")


def resolve_did(system_number: str) -> dict | None:
    """DID → tenant/service-identity mapping; None = unknown DID (fail closed, FR-L02)."""
    mapping = _did_map()
    normalized = _normalize_number(system_number)
    entry = mapping.get(normalized)
    if entry is None and normalized.startswith("+81"):
        # Accept domestic-format keys (0AB-J) for the same number.
        entry = mapping.get("0" + normalized[3:])
    return dict(entry) if isinstance(entry, dict) else None


def _principal_headers(entry: dict) -> dict:
    return {
        "content-type": "application/json",
        "x-raku-tenant-id": str(entry.get("tenant_id") or ""),
        "x-raku-user-id": str(entry.get("user_id") or "phone-gateway"),
        "x-raku-groups": json.dumps(list(entry.get("groups") or [])),
        "x-raku-roles": json.dumps(["phone_gateway"]),
        "X-Internal-Auth": _internal_auth_secret(),
    }


def _post(path: str, headers: dict, body: dict) -> tuple[int, dict]:
    base = os.environ.get("RAKU_INTERNAL_API_BASE", "http://127.0.0.1:8088").rstrip("/")
    timeout = float(os.environ.get("RAKU_PHONE_HTTP_TIMEOUT_SECONDS", "6"))
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — internal ALB only
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except Exception:
            payload = {}
        return exc.code, payload
    # URLError / timeout / connection refused propagate to the caller's error branch.


def _flatten_turn(turn: dict, call_id: str) -> dict:
    ai_action = str(turn.get("ai_action") or "")
    call_state = str(turn.get("call_state") or "")
    if ai_action == "handoff":
        action = "handoff"
    elif ai_action == "end_call" or call_state in _TERMINAL_STATES:
        action = "end_call"
    else:
        action = "continue"
    handoff = turn.get("handoff") or {}
    url_base = os.environ.get("RAKU_PHONE_HANDOFF_URL_BASE", "").rstrip("/")
    handoff_id = str(handoff.get("handoff_package_id") or "")
    return {
        "ok": "true",
        "action": action,
        "ai_action": ai_action,
        "call_id": call_id,
        "call_state": call_state,
        "speech_text": str(turn.get("speech_text") or turn.get("ai_response_text") or ""),
        "handoff_reason": str(handoff.get("reason") or ""),
        "handoff_destination": str(handoff.get("destination_id") or ""),
        "handoff_url": f"{url_base}?handoff={handoff_id}" if url_base and handoff_id else "",
    }


def _error(action: str, speech: str, **extra: str) -> dict:
    out = {"ok": "false", "action": action, "speech_text": speech, "ai_action": "", "call_id": ""}
    out.update({k: str(v) for k, v in extra.items()})
    return out


def lambda_handler(event: dict, context: object = None) -> dict:
    details = (event or {}).get("Details") or {}
    contact = details.get("ContactData") or {}
    parameters = details.get("Parameters") or {}
    attributes = contact.get("Attributes") or {}

    contact_id = str(contact.get("ContactId") or "")
    raw_caller = str((contact.get("CustomerEndpoint") or {}).get("Address") or "")
    system_number = str((contact.get("SystemEndpoint") or {}).get("Address") or "")
    action = str(parameters.get("action") or "turn")

    entry = resolve_did(system_number)
    if entry is None:
        return _error("reject", _FALLBACK_UNAVAILABLE)

    headers = _principal_headers(entry)
    try:
        if action == "call_start":
            status, payload = _post(
                "/internal/phone/calls/simulate",
                headers,
                {
                    "caller": {
                        # FR-L04: raw E.164 never leaves the adapter.
                        "phone_number": mask_phone_number(raw_caller),
                    },
                    "channel": "connect",
                    "provider": "amazon-connect",
                    "provider_call_id": contact_id,
                    "scenario_id": entry.get("scenario_id"),
                    "collection_id": entry.get("collection_id"),
                    "utterances": [],
                    "options": {"recording_enabled": False},
                },
            )
            if status != 202:
                return _error("error", _FALLBACK_ERROR, http_status=str(status))
            return {
                "ok": "true",
                "action": "continue",
                "ai_action": "",
                "call_id": str(payload.get("call_id") or ""),
                "call_state": str(payload.get("status") or "active"),
                "speech_text": "",
                "handoff_reason": "",
                "handoff_destination": "",
                "handoff_url": "",
            }

        call_id = str(parameters.get("call_id") or attributes.get("raku_call_id") or "")
        if not call_id:
            return _error("error", _FALLBACK_ERROR, detail="missing_call_id")

        if action == "hangup":
            status, payload = _post(
                f"/internal/phone/calls/{call_id}/turns", headers, {"event_type": "hangup"}
            )
            if status != 200:
                return _error("error", "", http_status=str(status))
            return _flatten_turn(payload, call_id)

        # Default: a caller speech turn (Lex transcript).
        utterance = str(parameters.get("utterance") or "")
        body: dict = {
            "event_type": "speech",
            "text": utterance,
            "collection_id": entry.get("collection_id"),
        }
        confidence = parameters.get("asr_confidence")
        if confidence not in (None, ""):
            try:
                body["asr_confidence"] = float(confidence)
            except (TypeError, ValueError):
                pass
        status, payload = _post(f"/internal/phone/calls/{call_id}/turns", headers, body)
        if status == 409:
            return _error("end_call", "", http_status="409")
        if status != 200:
            return _error("error", _FALLBACK_ERROR, http_status=str(status))
        return _flatten_turn(payload, call_id)
    except Exception:
        # Timeouts / network failures: never leave the caller in silence (FR-L06 / SC-L3).
        return _error("error", _FALLBACK_ERROR)
