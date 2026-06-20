#!/usr/bin/env python3
"""Stdlib-only local demo for the manufacturing RAG vertical slice (T072).

Run:
    PYTHONPATH=src python3 poc-ui/server.py

Smoke:
    PYTHONPATH=src python3 poc-ui/server.py --smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from raku_rag.domain.models import Citation, IdentityClaims, ScopeType, SubjectType
from raku_rag.manufacturing.app import ManufacturingSystem
from raku_rag.manufacturing.domain.draft import DraftType
from raku_rag.manufacturing.domain.entities import (
    Countermeasure,
    FailureMode,
    MeasureClass,
    TroubleCase,
)
from raku_rag.manufacturing.domain.metadata import (
    ApprovalSource,
    ApprovalStatus,
    DocumentKind,
    ManufacturingDocumentMetadata,
)

TENANT = "tenant_mfg_demo"
COLLECTION = "c"
OPERATOR = IdentityClaims(tenant_id=TENANT, user_id="operator", groups=("maintenance",), roles=())
ADMIN = IdentityClaims(tenant_id=TENANT, user_id="admin", groups=("maintenance",), roles=("admin",))


def mfg_meta(
    document_id: str,
    *,
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    effective_date: str | None = "2026-01-10",
    approval_source: ApprovalSource = ApprovalSource.IMPORTED,
    document_kind: DocumentKind | None = None,
    safety_category: str | None = None,
    hazard_tags: tuple[str, ...] = (),
    equipment: str | None = None,
    equipment_id: str | None = None,
    alarm_code: str | None = None,
    process: str | None = None,
    process_id: str | None = None,
    defect_type: str | None = None,
    part_no: str | None = None,
    obsolete_at: str | None = None,
) -> ManufacturingDocumentMetadata:
    return ManufacturingDocumentMetadata(
        tenant_id=TENANT,
        document_id=document_id,
        approval_status=approval_status,
        effective_date=effective_date,
        approval_source=approval_source,
        document_kind=document_kind,
        safety_category=safety_category,
        hazard_tags=hazard_tags,
        equipment=equipment,
        equipment_id=equipment_id,
        alarm_code=alarm_code,
        process=process,
        process_id=process_id,
        defect_type=defect_type,
        part_no=part_no,
        obsolete_at=obsolete_at,
    )


def seed_system(sysm: ManufacturingSystem) -> ManufacturingSystem:
        """Seed the local demo documents, ACL grants, and trouble-case graph."""
        sysm.grant(TENANT, ScopeType.COLLECTION, COLLECTION, SubjectType.USER, OPERATOR.user_id)
        sysm.grant(TENANT, ScopeType.COLLECTION, COLLECTION, SubjectType.USER, ADMIN.user_id)

        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="approved_lockout",
            text=(
                "To disassemble the press safely, stop the machine, apply lockout tagout, "
                "release stored hydraulic pressure, and verify zero energy before removing guards."
            ),
            metadata=mfg_meta(
                "approved_lockout",
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="lockout_tagout",
                hazard_tags=("equipment_stop", "disassembly", "hydraulic_pressure"),
                equipment="press",
                equipment_id="press1",
                process="press_maintenance",
                process_id="proc_press",
            ),
        )
        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="approved_torque",
            text="The torque specification for the M8 conveyor cover bolt is twelve newton meters.",
            metadata=mfg_meta(
                "approved_torque",
                process="conveyor_assembly",
                process_id="proc_conveyor",
            ),
        )
        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="ledger_pump17",
            text="Equipment ledger: pump17 alarm E152 remedy is to replace the impeller seal.",
            metadata=mfg_meta(
                "ledger_pump17",
                document_kind=DocumentKind.LEDGER,
                equipment="pump17",
                equipment_id="pump17",
                alarm_code="E152",
            ),
        )
        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="quality_p900",
            text="Quality log: for a P900 housing crack defect, scrap and remold the P900 housing.",
            metadata=mfg_meta(
                "quality_p900",
                document_kind=DocumentKind.QUALITY_REPORT,
                defect_type="crack",
                part_no="P900",
            ),
        )
        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="obsolete_coolant",
            text="The legacy coolant flow rate setpoint for the grinder spindle is eight liters per minute.",
            metadata=mfg_meta(
                "obsolete_coolant",
                approval_status=ApprovalStatus.OBSOLETE,
                effective_date="2020-01-01",
                obsolete_at="2025-12-31",
            ),
        )
        sysm.ingest_manufacturing(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            document_id="draft_panel",
            text="Draft note about working on the 400V electrical panel. This note is not approved.",
            metadata=mfg_meta(
                "draft_panel",
                approval_status=ApprovalStatus.DRAFT,
                effective_date=None,
                document_kind=DocumentKind.WORK_INSTRUCTION,
                safety_category="electrical",
                hazard_tags=("electric_shock", "high_voltage"),
            ),
        )
        sysm.register_trouble_case(
            tenant_id=TENANT,
            collection_id=COLLECTION,
            source_document_id="trouble_gearbox",
            text=(
                "Trouble report: the assembly gearbox showed vibration increase and abnormal noise. "
                "Root cause: bearing wear. Provisional countermeasure: reduce feed rate and monitor. "
                "Permanent countermeasure: replace the worn bearing and install a vibration sensor. "
                "Recurrence prevention: add the bearing to the periodic replacement schedule."
            ),
            metadata=mfg_meta(
                "trouble_gearbox",
                document_kind=DocumentKind.TROUBLE_REPORT,
                equipment="gearbox",
                equipment_id="eq_gearbox",
                process="assembly",
                process_id="proc_assembly",
            ),
            trouble_case=TroubleCase(
                tenant_id=TENANT,
                trouble_case_id="tc_gearbox",
                symptom="vibration increase and abnormal noise",
                equipment_id="eq_gearbox",
                process_id="proc_assembly",
                failure_mode_id="fm_bearing",
                source_document_id="trouble_gearbox",
            ),
            failure_mode=FailureMode(
                tenant_id=TENANT,
                failure_mode_id="fm_bearing",
                name="bearing wear",
                description="Worn bearing causing vibration and noise.",
            ),
            countermeasures=(
                Countermeasure(
                    tenant_id=TENANT,
                    measure_id="cm_feed",
                    trouble_case_id="tc_gearbox",
                    description="reduce feed rate and monitor closely",
                    measure_class=MeasureClass.PROVISIONAL,
                    source_document_id="trouble_gearbox",
                ),
                Countermeasure(
                    tenant_id=TENANT,
                    measure_id="cm_bearing",
                    trouble_case_id="tc_gearbox",
                    description="replace the worn bearing and install a vibration sensor",
                    measure_class=MeasureClass.PERMANENT,
                    source_document_id="trouble_gearbox",
                ),
            ),
            recurrence_prevention="add the bearing to the periodic replacement schedule",
        )
        return sysm


def build_seeded_system() -> ManufacturingSystem:
    """Build a fresh seeded ManufacturingSystem for tests, smoke, and the HTTP demo."""
    return seed_system(ManufacturingSystem())


class DemoApp:
    """Small in-memory demo harness around ManufacturingSystem."""

    def __init__(self) -> None:
        self.system = build_seeded_system()

    def snapshot(self) -> dict[str, Any]:
        return {
            "tenant": TENANT,
            "collection": COLLECTION,
            "documents": [
                self._document_summary(document_id)
                for document_id in (
                    "approved_lockout",
                    "approved_torque",
                    "ledger_pump17",
                    "quality_p900",
                    "obsolete_coolant",
                    "draft_panel",
                    "trouble_gearbox",
                )
            ],
            "kpi": self.system.kpi(ADMIN, format="json"),
            "governance": self.system.governance_status(TENANT),
            "examples": EXAMPLES,
        }

    def _document_summary(self, document_id: str) -> dict[str, Any]:
        meta = self.system.get_mfg_meta(TENANT, document_id)
        return {
            "document_id": document_id,
            "approval_status": _enum_value(meta.approval_status) if meta else None,
            "effective_date": meta.effective_date if meta else None,
            "kind": _enum_value(meta.document_kind) if meta else None,
            "equipment": meta.equipment if meta else None,
            "alarm_code": meta.alarm_code if meta else None,
            "defect_type": meta.defect_type if meta else None,
            "part_no": meta.part_no if meta else None,
        }

    def answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_answer(self.system, payload)

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_search(self.system, payload)

    def trouble(self, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_trouble_cases(self.system, payload)

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_draft(self.system, payload)

    def kpi(self) -> dict[str, Any]:
        return {"kpi": handle_kpi(self.system), "telemetry": handle_safety_telemetry(self.system)}


def _query_from(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = str(payload.get(name) or "").strip()
        if value:
            return value
    raise ValueError("query is required")


def handle_answer(system: ManufacturingSystem, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure demo handler for answer requests; no socket required."""
    query = _query_from(payload, "query")
    ans = system.answer(
        OPERATOR,
        query,
        collection_id=COLLECTION,
        intent_hint=payload.get("intent_hint"),
        manufacturing_filters=payload.get("filters") or None,
    )
    return _jsonable(ans)


def handle_search(system: ManufacturingSystem, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure demo handler for manufacturing search."""
    query = _query_from(payload, "query")
    hits = system.search(
        OPERATOR,
        query,
        collection_id=COLLECTION,
        manufacturing_filters=payload.get("filters") or None,
    )
    return {"results": _jsonable(hits)}


def handle_trouble_cases(system: ManufacturingSystem, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure demo handler for similar trouble-case search."""
    query = _query_from(payload, "symptom", "query")
    resp = system.search_trouble_cases(OPERATOR, query, collection_id=COLLECTION)
    return _jsonable(resp)


def handle_draft(system: ManufacturingSystem, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure demo handler for AI draft generation."""
    kind = payload.get("kind") or DraftType.CHECKLIST.value
    source_document_id = payload.get("source_document_id") or "approved_lockout"
    draft = system.generate_draft(
        principal=OPERATOR,
        kind=kind,
        context_citations=(
            Citation(
                kind="text",
                document_id=source_document_id,
                source_id="demo",
                version=1,
                retrieval_score=0.99,
                chunk_id=f"{source_document_id}:0",
            ),
        ),
        source_document_ids=(source_document_id,),
        template_id="demo-template",
        collection_id=COLLECTION,
    )
    return _jsonable(draft)


def handle_draft_review(system: ManufacturingSystem, payload: dict[str, Any]) -> dict[str, Any]:
    """Pure demo handler for draft review; proves AI self-approval is rejected."""
    artifact_id = str(payload.get("artifact_id") or "").strip()
    if not artifact_id:
        return {"error": "artifact_id is required"}
    decision = str(payload.get("decision") or "approved")
    reviewer_id = payload.get("reviewer_id")
    if reviewer_id:
        current = system.get_draft(TENANT, artifact_id)
        if current is not None and getattr(current.status, "value", current.status) == "draft":
            system.assign_reviewer(tenant_id=TENANT, artifact_id=artifact_id, reviewer_id=str(reviewer_id))
        reviewed = system.review_draft(
            tenant_id=TENANT,
            artifact_id=artifact_id,
            reviewer=IdentityClaims(tenant_id=TENANT, user_id=str(reviewer_id), roles=("reviewer",)),
            decision=decision,
            comment="demo review",
        )
        result = _jsonable(reviewed)
        result["rejected_self_approve"] = False
        return result
    try:
        reviewed = system.review_draft(
            tenant_id=TENANT,
            artifact_id=artifact_id,
            reviewer=None,
            decision=decision,
        )
        result = _jsonable(reviewed)
        result["rejected_self_approve"] = False
        return result
    except Exception:
        current = system.get_draft(TENANT, artifact_id)
        result = _jsonable(current) if current is not None else {"artifact_id": artifact_id}
        result["rejected_self_approve"] = True
        return result


def handle_dashboard(system: ManufacturingSystem) -> dict[str, Any]:
    return _jsonable(system.knowledge_ops_dashboard(ADMIN))


def handle_kpi(system: ManufacturingSystem) -> dict[str, Any]:
    return _jsonable(system.kpi(ADMIN, format="json"))


def handle_safety_telemetry(system: ManufacturingSystem) -> dict[str, Any]:
    return _jsonable(system.safety_telemetry(ADMIN))


def render_index() -> str:
    return INDEX_HTML


EXAMPLES = {
    "safe_answer": "what is the torque specification for the M8 conveyor cover bolt?",
    "high_risk_ok": "How do I disassemble the press safely?",
    "high_risk_block": "How do I work on the 400V panel without getting electrocuted?",
    "obsolete_warning": "what is the legacy coolant flow rate setpoint for the grinder spindle?",
    "search_alarm": "alarm E152 pump17 remedy",
    "trouble": "vibration increase abnormal noise gearbox bearing",
}


_APP: DemoApp | None = None


def app() -> DemoApp:
    global _APP
    if _APP is None:
        _APP = DemoApp()
    return _APP


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(_jsonable(k)): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    data = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _html_response(handler: BaseHTTPRequestHandler) -> None:
    data = render_index().encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "raku-rag-demo/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("POC_UI_QUIET") != "1":
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path in ("/", "/index.html"):
                _html_response(self)
            elif self.path == "/api/state":
                _json_response(self, 200, app().snapshot())
            elif self.path == "/api/kpi":
                _json_response(self, 200, app().kpi())
            elif self.path == "/api/dashboard":
                _json_response(self, 200, handle_dashboard(app().system))
            else:
                _json_response(self, 404, {"error": "not_found"})
        except Exception as exc:  # pragma: no cover - defensive HTTP envelope
            _json_response(self, 500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if self.path == "/api/answer":
                _json_response(self, 200, app().answer(payload))
            elif self.path == "/api/search":
                _json_response(self, 200, app().search(payload))
            elif self.path in ("/api/trouble", "/api/trouble-cases"):
                _json_response(self, 200, app().trouble(payload))
            elif self.path == "/api/draft":
                _json_response(self, 200, app().draft(payload))
            elif self.path == "/api/draft/review":
                _json_response(self, 200, handle_draft_review(app().system, payload))
            else:
                _json_response(self, 404, {"error": "not_found"})
        except Exception as exc:
            _json_response(self, 400, {"error": str(exc)})


INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>raku-rag Manufacturing PoC</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #18202a;
      --muted: #5a6472;
      --line: #d8dde5;
      --accent: #0d6b63;
      --danger: #b42318;
      --warn: #a15c00;
      --ok: #14723a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      padding: 18px 24px;
      background: #102a32;
      color: white;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 16px; letter-spacing: 0; }
    main {
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px;
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    textarea, input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font: inherit;
      color: var(--ink);
      background: white;
    }
    textarea { min-height: 92px; resize: vertical; }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 12px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    button.secondary { background: #31424f; }
    button.light { background: #e8eef2; color: var(--ink); }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .grid { display: grid; gap: 16px; }
    .examples { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      background: #fbfcfd;
      font-size: 12px;
    }
    .status-ok { color: var(--ok); font-weight: 700; }
    .status-warn { color: var(--warn); font-weight: 700; }
    .status-danger { color: var(--danger); font-weight: 700; }
    pre {
      margin: 0;
      padding: 12px;
      border-radius: 6px;
      overflow: auto;
      max-height: 420px;
      background: #0d1720;
      color: #dce7ef;
      font-size: 13px;
      line-height: 1.45;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfd;
    }
    .metric strong { display: block; font-size: 18px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 7px 6px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 700; }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; padding: 12px; }
      .examples { grid-template-columns: 1fr; }
      .summary { grid-template-columns: 1fr; }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>raku-rag Manufacturing PoC</h1>
    <div class="row">
      <span class="pill">stdlib demo</span>
      <span class="pill">local only</span>
      <span class="pill">in-memory</span>
    </div>
  </header>
  <main>
    <div class="grid">
      <section>
        <h2>Question</h2>
        <div class="grid">
          <textarea id="query"></textarea>
          <div class="row">
            <button onclick="ask()">Ask</button>
            <button class="secondary" onclick="runSearch()">Search</button>
            <button class="secondary" onclick="runTrouble()">Trouble Case</button>
            <button class="light" onclick="makeDraft()">Draft</button>
            <button class="light" onclick="loadDashboard()">Dashboard</button>
            <button class="light" onclick="loadKpi()">KPI</button>
          </div>
          <div class="examples" id="examples"></div>
        </div>
      </section>
      <section>
        <h2>Result</h2>
        <div id="quick"></div>
        <pre id="result">{}</pre>
      </section>
    </div>
    <div class="grid">
      <section>
        <h2>Demo State</h2>
        <div class="summary" id="metrics"></div>
      </section>
      <section>
        <h2>Seeded Documents</h2>
        <div id="docs"></div>
      </section>
    </div>
  </main>
  <script>
    const query = document.getElementById("query");
    const result = document.getElementById("result");
    const quick = document.getElementById("quick");
    const examples = document.getElementById("examples");
    const metrics = document.getElementById("metrics");
    const docs = document.getElementById("docs");

    async function api(path, payload) {
      const options = payload === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      };
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || res.statusText);
      return data;
    }
    function show(data) {
      result.textContent = JSON.stringify(data, null, 2);
      const status = data.status || (data.kpi ? "kpi" : "");
      const cls = data.safety_block_reason ? "status-danger" : data.obsolete_warning ? "status-warn" : "status-ok";
      quick.innerHTML = status ? `<p><span class="${cls}">${status}</span> ${data.safety_block_reason || ""}</p>` : "";
    }
    async function ask() { show(await api("/api/answer", { query: query.value })); await refresh(); }
    async function runSearch() { show(await api("/api/search", { query: query.value })); }
    async function runTrouble() { show(await api("/api/trouble-cases", { symptom: query.value })); await refresh(); }
    async function makeDraft() { show(await api("/api/draft", { kind: "checklist" })); await refresh(); }
    async function loadDashboard() { show(await api("/api/dashboard")); await refresh(); }
    async function loadKpi() { show(await api("/api/kpi")); await refresh(); }
    function setExample(text) { query.value = text; }
    async function refresh() {
      const state = await api("/api/state");
      query.value ||= state.examples.safe_answer;
      examples.innerHTML = Object.entries(state.examples).map(([name, text]) =>
        `<button class="light" onclick='setExample(${JSON.stringify(text)})'>${name}</button>`
      ).join("");
      metrics.innerHTML = [
        ["high risk", state.kpi.high_risk_query_count],
        ["safety blocks", state.kpi.safety_gate_block_count],
        ["grounded rate", state.kpi.grounded_answer_rate]
      ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");
      docs.innerHTML = `<table><thead><tr><th>document</th><th>status</th><th>tags</th></tr></thead><tbody>${
        state.documents.map(d => `<tr><td>${d.document_id}</td><td>${d.approval_status || ""}</td><td>${[d.kind,d.equipment,d.alarm_code,d.defect_type,d.part_no].filter(Boolean).join(", ")}</td></tr>`).join("")
      }</tbody></table>`;
    }
    refresh().catch(err => show({ error: err.message }));
  </script>
</body>
</html>
"""


def smoke() -> dict[str, Any]:
    system = build_seeded_system()
    safe = handle_answer(system, {"query": EXAMPLES["safe_answer"]})
    high_risk = handle_answer(system, {"query": EXAMPLES["high_risk_ok"]})
    blocked = handle_answer(system, {"query": EXAMPLES["high_risk_block"]})
    trouble = handle_trouble_cases(system, {"symptom": EXAMPLES["trouble"]})
    draft = handle_draft(system, {"kind": "checklist"})
    kpi = {"kpi": handle_kpi(system), "telemetry": handle_safety_telemetry(system)}
    assert safe["status"] == "ok", safe
    assert high_risk["status"] == "ok" and high_risk["high_risk"] is True, high_risk
    assert blocked["status"] == "insufficient_evidence", blocked
    assert blocked["safety_block_reason"] == "approved_citation_missing", blocked
    assert trouble["status"] == "ok" and trouble["results"], trouble
    assert draft["status"] == "draft", draft
    assert kpi["kpi"]["high_risk_query_count"] >= 2, kpi
    return {"status": "ok", "checks": ["answer", "high_risk", "safety_block", "trouble", "draft", "kpi"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local manufacturing PoC UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)

    if args.smoke:
        print(json.dumps(smoke(), ensure_ascii=False, indent=2))
        return 0

    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    print(f"manufacturing PoC UI: http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
