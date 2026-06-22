"use client";

import { useCallback, useEffect, useState } from "react";
import type {
  GovernanceStatus,
  KnowledgeOpsDashboard,
  ManufacturingKpi,
  SafetyTelemetryView,
} from "@raku-rag/shared";
import {
  manufacturingDashboard,
  manufacturingGovernanceStatus,
  manufacturingKpi,
  manufacturingSafetyTelemetry,
} from "../../lib/api-client";
import { clearSessionToken, getSessionToken } from "../../lib/session";

const LIST_CAP = 12;

interface OpsData {
  dashboard: KnowledgeOpsDashboard;
  telemetry: SafetyTelemetryView;
  kpi: ManufacturingKpi;
  governance: GovernanceStatus;
}

function pct(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function CappedList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="ops-empty">{empty}</p>;
  const shown = items.slice(0, LIST_CAP);
  return (
    <>
      <ul className="ops-list">
        {shown.map((item, i) => (
          <li key={`${item}-${i}`}>{item}</li>
        ))}
      </ul>
      {items.length > shown.length && (
        <p className="ops-note">
          showing {shown.length} of {items.length}
        </p>
      )}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="ops-stat">
      <span className="ops-stat-value">{value}</span>
      <span className="ops-stat-label">{label}</span>
    </div>
  );
}

function Flag({ label, on }: { label: string; on: boolean }) {
  return (
    <span className={`ops-flag ${on ? "on" : "off"}`}>
      {on ? "✓" : "✕"} {label}
    </span>
  );
}

export default function OperationsPage() {
  const [data, setData] = useState<OpsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = await getSessionToken();
      const [dashboard, telemetry, kpi, governance] = await Promise.all([
        manufacturingDashboard(token),
        manufacturingSafetyTelemetry(token),
        manufacturingKpi(token),
        manufacturingGovernanceStatus(token),
      ]);
      setData({ dashboard, telemetry, kpi, governance });
    } catch (err) {
      clearSessionToken();
      setError(err instanceof Error ? err.message : "failed to load operations data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const telemetryBreakdown =
    data?.telemetry.block_breakdown ?? data?.telemetry.safety_gate_block_breakdown ?? {};

  return (
    <section className="workspace" aria-label="Operations">
      <header className="topbar">
        <div>
          <p className="eyebrow">Knowledge operations</p>
          <h2>Operations</h2>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Loading" : "Refresh"}
        </button>
      </header>

      {error && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>Could not load</h3>
          <p>{error}</p>
        </section>
      )}

      {loading && !data && <p className="ops-empty">Loading operations data…</p>}

      {data && (
        <>
          <section className="ops-panel" aria-label="Knowledge gaps">
            <h3>Knowledge base health</h3>
            <div className="ops-stats">
              <Stat label="Unanswered / blocked" value={data.dashboard.unanswered_question_count} />
            </div>
            <div className="ops-cols">
              <div>
                <h4>Knowledge-gap areas</h4>
                <CappedList items={data.dashboard.knowledge_gap_areas} empty="No gaps recorded." />
              </div>
              <div>
                <h4>Obsolete candidates</h4>
                <CappedList
                  items={data.dashboard.obsolete_document_candidates}
                  empty="No obsolete documents."
                />
              </div>
              <div>
                <h4>Frequently referenced</h4>
                <CappedList
                  items={data.dashboard.frequently_referenced_documents}
                  empty="No citations yet."
                />
              </div>
              <div>
                <h4>Frequent questions</h4>
                <CappedList
                  items={data.dashboard.frequent_questions}
                  empty="No question activity yet."
                />
              </div>
              <div>
                <h4>Low-rating answers</h4>
                <CappedList items={data.dashboard.low_rating_answers} empty="No low ratings." />
              </div>
            </div>
          </section>

          <section className="ops-panel" aria-label="Safety telemetry">
            <h3>Safety telemetry</h3>
            <div className="ops-stats">
              <Stat label="High-risk queries" value={data.telemetry.high_risk_query_count} />
              <Stat label="Safety-gate blocks" value={data.telemetry.safety_gate_block_count} />
            </div>
            <h4>Block breakdown</h4>
            {Object.keys(telemetryBreakdown).length === 0 ? (
              <p className="ops-empty">No safety-gate blocks recorded.</p>
            ) : (
              <ul className="ops-list">
                {Object.entries(telemetryBreakdown).map(([reason, count]) => (
                  <li key={reason}>
                    <span className="ops-kv-key">{reason}</span>
                    <span className="ops-kv-val">{count}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="ops-note">source: {data.telemetry.source}</p>
          </section>

          <section className="ops-panel" aria-label="KPIs">
            <h3>PoC KPIs</h3>
            <div className="ops-stats">
              <Stat label="Self-resolution" value={pct(data.kpi.self_resolution_rate)} />
              <Stat label="Grounded answers" value={pct(data.kpi.grounded_answer_rate)} />
              <Stat label="Insufficient evidence" value={pct(data.kpi.insufficient_evidence_rate)} />
              <Stat label="Low-rating" value={pct(data.kpi.low_rating_rate)} />
              <Stat
                label="Expert interruption ↓"
                value={pct(data.kpi.expert_interruption_reduction)}
              />
              <Stat label="Answer p50 (ms)" value={data.kpi.average_time_to_answer?.p50 ?? "—"} />
              <Stat label="Answer p95 (ms)" value={data.kpi.average_time_to_answer?.p95 ?? "—"} />
            </div>
            {data.kpi.materialized_at && (
              <p className="ops-note">materialized at {data.kpi.materialized_at}</p>
            )}
          </section>

          <section className="ops-panel" aria-label="Governance">
            <h3>Governance</h3>
            <p className="ops-note">policy version {String(data.governance.policy_version)}</p>
            <div className="ops-flags">
              <Flag label="No-train default" on={data.governance.no_train?.no_train_default} />
              <Flag
                label="Provider no-train required"
                on={data.governance.no_train?.provider_no_train_required}
              />
              <Flag label="Safety gate enabled" on={data.governance.safety_gate?.enabled} />
              <Flag
                label="High-risk needs approved citation"
                on={data.governance.safety_gate?.high_risk_requires_approved_citation}
              />
              <Flag
                label="AI output always draft"
                on={data.governance.draft_review?.ai_output_always_draft}
              />
              <Flag
                label="Reviewer required to approve"
                on={data.governance.draft_review?.reviewer_required_for_approval}
              />
              <Flag label="Groundedness enabled" on={data.governance.groundedness?.enabled} />
              <Flag label="Citation required" on={data.governance.groundedness?.citation_required} />
              <Flag label="Audit tamper-evident" on={data.governance.audit_coverage?.tamper_evident} />
              <Flag
                label="Audit reference-ids only"
                on={data.governance.audit_coverage?.reference_ids_only}
              />
            </div>
            <div className="ops-stats">
              <Stat
                label="Customer retention (days)"
                value={data.governance.retention?.retention_customer_days ?? "—"}
              />
              <Stat
                label="Audit retention (days)"
                value={data.governance.retention?.retention_audit_days ?? "—"}
              />
            </div>
          </section>
        </>
      )}
    </section>
  );
}
