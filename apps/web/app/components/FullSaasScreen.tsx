"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type {
  AdminDataSource,
  Citation,
  DataSourceMappingProfile,
  DataSourceProfileType,
  DataSourcePreviewResponse,
  GovernanceStatus,
  KnowledgeOpsDashboard,
  ManufacturingAnswerResponse,
  ManufacturingDocumentSummary,
  ManufacturingIngestionRun,
  ManufacturingKpi,
  ManufacturingSourceSyncStatus,
  SafetyTelemetryView,
  SearchResultItem,
  DraftArtifact,
} from "@raku-rag/shared";
import {
  adminDataSources,
  adminCitationView,
  adminSourcePreview,
  adminSourceSync,
  type AdminSourceSyncResponse,
  apiDeleteJson,
  apiGetJson,
  apiPostJson,
  apiPutJson,
  authHeaders,
  ingestDocument,
  manufacturingAnswer,
  searchChunks,
  manufacturingAssignReviewer,
  manufacturingAuditEvents,
  manufacturingAuditExport,
  manufacturingCreateDraft,
  manufacturingDataUsePolicy,
  manufacturingDeleteDocument,
  manufacturingDocumentApproval,
  manufacturingDocuments,
  manufacturingGetDraft,
  manufacturingDashboard,
  manufacturingGovernanceStatus,
  manufacturingIngestionRun,
  manufacturingKpi,
  manufacturingListDrafts,
  manufacturingImprovements,
  runManufacturingQualityEval,
  type QualityEvalResult,
  manufacturingRequestSourceSync,
  manufacturingReviewDraft,
  manufacturingSafetyTelemetry,
  manufacturingSourceSyncStatus,
  manufacturingTroubleCaseSearch,
  manufacturingUpdateDocumentMetadata,
  submitFeedback,
} from "../../lib/api-client";
import {
  loadConnectorRuns,
  recordConnectorRun,
  type ConnectorRunRecord,
} from "../../lib/connector-runs";
import {
  clearSessionToken,
  DEMO_COLLECTION,
  DEMO_TENANT,
  getSessionToken,
  loadAnswerCollection,
  mintTokenFor,
  saveAnswerCollection,
} from "../../lib/session";
import { missingApis, type ManifestScreen } from "../../lib/full-saas";
import CitationViewer, { type CitationViewTarget } from "./CitationViewer";
import { useDialog } from "../../lib/use-dialog";
import {
  clearAnswerHistory,
  loadAnswerHistory,
  recordAnswer,
  type AnswerHistoryEntry,
} from "../../lib/answer-history";
import {
  clearIngestedDocs,
  loadIngestedDocs,
  recordIngestedDoc,
  updateIngestedDoc,
  type IngestedDoc,
} from "../../lib/uploads";
import {
  loadDrafts,
  recordDraft,
  updateDraftRecord,
  type DraftRecord,
} from "../../lib/drafts";
import {
  clearImprovementItems,
  FEEDBACK_REASONS,
  loadImprovementItems,
  reasonLabel,
  recordImprovementItem,
  setImprovementStatus,
  type ImprovementItem,
} from "../../lib/improvement-queue";

type ViewState<T> =
  | { state: "loading" }
  | { state: "error"; error: string }
  | { state: "ready"; data: T };

type AdminListRow = { id: string; label: string; meta?: string; status?: string };

const MOCK_USERS: AdminListRow[] = [
  { id: "alice", label: "Alice Tanaka", meta: "tenant_admin · reviewer", status: "active" },
  { id: "bob", label: "Bob Sato", meta: "field_user", status: "active" },
  { id: "carol", label: "Carol Kato", meta: "ops_owner", status: "pending" },
];

const MOCK_SOURCES: AdminListRow[] = [
  { id: "src-press", label: "Press line manuals", meta: "sharepoint · 2,184 docs", status: "synced" },
  { id: "src-sop", label: "SOP library", meta: "s3 · 418 docs", status: "syncing" },
  { id: "src-troubles", label: "Trouble cases", meta: "postgres · 6,204 cases", status: "ready" },
];


const MOCK_BILLING = {
  plan: "Enterprise",
  usage: "68% of monthly quota",
  invoices: ["INV-2026-05 paid", "INV-2026-04 paid", "INV-2026-03 paid"],
};

function isAuthError(error: unknown): boolean {
  return error instanceof Error && /401|unauthorized|session|token|auth|jwt|cognito/i.test(error.message);
}

async function runWithToken<T>(loader: (token: string) => Promise<T>): Promise<T> {
  const token = await getSessionToken();
  return loader(token);
}

function redirectToLoginAfterAuthError(): void {
  if (typeof window === "undefined") return;
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?return_to=${encodeURIComponent(returnTo || "/home")}`);
}

const SYNC_POLL_MS = 5000;
const SYNC_ACTIVE_STATUSES = new Set([
  "syncing",
  "queued",
  "observing",
  "partially_succeeded",
]);

function isSyncActive(status: string | undefined | null): boolean {
  return !!status && SYNC_ACTIVE_STATUSES.has(status);
}

function formatLoadError(err: unknown): string {
  const message = err instanceof Error ? err.message : "リクエストに失敗しました";
  if (/failed to fetch|networkerror|load failed/i.test(message)) {
    return "バックエンド API に接続できません。API が起動しているか確認してください。";
  }
  return message;
}

type UseLoadOptions<T> = {
  pollIntervalMs?: number;
  shouldPoll?: (data: T) => boolean;
};

function useLoad<T>(
  loader: () => Promise<T>,
  deps: React.DependencyList,
  options?: UseLoadOptions<T>,
): [ViewState<T>, () => void] {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<ViewState<T>>({ state: "loading" });
  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setState({ state: "loading" });
    loader()
      .then((data) => {
        if (active) setState({ state: "ready", data });
      })
      .catch((err) => {
        if (isAuthError(err)) {
          clearSessionToken();
          redirectToLoginAfterAuthError();
        }
        if (active) setState({ state: "error", error: formatLoadError(err) });
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (state.state !== "ready" || !options?.pollIntervalMs || !options.shouldPoll?.(state.data)) {
      return;
    }
    const id = window.setInterval(reload, options.pollIntervalMs);
    return () => window.clearInterval(id);
  }, [state, options?.pollIntervalMs, options?.shouldPoll, reload]);

  return [state, reload];
}

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="screen-section">
      <div className="screen-section-head">
        <h3>{title}</h3>
        {note && <p className="screen-note">{note}</p>}
      </div>
      {children}
    </section>
  );
}

function FieldGrid({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="field-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="metric-card">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}

function DataTable({
  columns,
  rows,
  empty,
}: {
  columns: string[];
  rows: ReactNode[][];
  empty: string;
}) {
  if (rows.length === 0) return <p className="ops-empty">{empty}</p>;
  return (
    <div className="data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "ok") return "回答済み";
  if (status === "insufficient_evidence") return "根拠不足";
  if (status === "budget_exceeded") return "予算上限";
  return "利用不可";
}

function citationLabel(citation: { document_id: string; chunk_id?: string | null }): string {
  return citation.chunk_id ? `${citation.document_id} / ${citation.chunk_id}` : citation.document_id;
}

function downloadCsv(filename: string, rows: Array<Array<string | number | boolean | null | undefined>>): void {
  if (typeof window === "undefined") return;
  const csv = rows
    .map((row) =>
      row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(","),
    )
    .join("\r\n");
  // BOM so Excel reads UTF-8 (Japanese) correctly.
  const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function safetyLabel(response: { manufacturing: { safety_block_reason?: string | null; high_risk?: boolean; obsolete_warning?: boolean } }): string {
  const safety = response.manufacturing;
  if (safety.safety_block_reason) return "保留";
  if (safety.high_risk) return "高リスク";
  if (safety.obsolete_warning) return "旧版参照";
  return "正常";
}

type AnswerTurn =
  | { kind: "user"; id: string; text: string }
  | { kind: "answer"; id: string; question: string; response: ManufacturingAnswerResponse }
  | { kind: "error"; id: string; question: string; error: string };

const CITE_APPROVAL: Record<string, { label: string; cls: string }> = {
  approved: { label: "承認済み", cls: "approval-approved" },
  pending_review: { label: "承認待ち", cls: "approval-draft" },
  draft: { label: "ドラフト", cls: "approval-draft" },
  obsolete: { label: "旧版", cls: "approval-obsolete" },
};

function citeApproval(status?: string | null): { label: string; cls: string } {
  return status && CITE_APPROVAL[status]
    ? CITE_APPROVAL[status]
    : { label: status ? status : "承認状態不明", cls: "approval-draft" };
}

function AnswerFeedback({ question, answerId }: { question: string; answerId: string }) {
  const [sent, setSent] = useState<null | "up" | "down">(null);
  const [showReasons, setShowReasons] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendUp() {
    if (busy || sent) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getSessionToken();
      await submitFeedback({ subject: "user", rating: 5, answer_id: answerId || undefined, comment: "answer:helpful" }, token);
      setSent("up");
    } catch (err) {
      setError(err instanceof Error ? err.message : "送信に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  async function sendDown(reasonCode: string) {
    if (busy || sent) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getSessionToken();
      await submitFeedback(
        { subject: "user", rating: 2, answer_id: answerId || undefined, comment: `answer:needs_improvement reason:${reasonCode}` },
        token,
      );
      recordImprovementItem({ answer_id: answerId, question, reason: reasonCode });
      setSent("down");
      setShowReasons(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "送信に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  if (sent === "up") return <p className="answer-fb-done">フィードバックを送信しました（有用）。</p>;
  if (sent === "down")
    return <p className="answer-fb-done">改善キューに追加しました。<Link href="/operations/improvements">改善キューを見る</Link></p>;

  return (
    <div className="answer-fb">
      {!showReasons ? (
        <div className="answer-fb-row">
          <span className="answer-fb-label">この回答は役に立ちましたか？</span>
          <button type="button" className="answer-fb-btn" disabled={busy} onClick={() => void sendUp()}>
            👍 有用
          </button>
          <button type="button" className="answer-fb-btn" disabled={busy} onClick={() => setShowReasons(true)}>
            👎 要改善
          </button>
        </div>
      ) : (
        <div className="answer-fb-reasons">
          <span className="answer-fb-label">改善が必要な理由を選んでください</span>
          <div className="answer-fb-reason-list">
            {FEEDBACK_REASONS.map((reason) => (
              <button
                key={reason.code}
                type="button"
                className="answer-fb-reason"
                disabled={busy}
                onClick={() => void sendDown(reason.code)}
              >
                {reason.label}
              </button>
            ))}
            <button type="button" className="answer-fb-cancel" onClick={() => setShowReasons(false)}>
              キャンセル
            </button>
          </div>
        </div>
      )}
      {error && <span className="cv-foot-error" role="alert">{error}</span>}
    </div>
  );
}

function AnswerPanel({
  turn,
  onOpenCitation,
}: {
  turn: Extract<AnswerTurn, { kind: "answer" }>;
  onOpenCitation: (target: CitationViewTarget) => void;
}) {
  const r = turn.response;
  const safety = r.manufacturing;
  const blocked = Boolean(safety?.safety_block_reason);
  const insufficient = r.status === "insufficient_evidence";
  const reasonCodes = safety?.high_risk_reason_codes ?? [];

  return (
    <section className="answer-card" aria-live="polite">
      <div className="answer-card-q">
        <span className="answer-card-q-label">質問</span>
        <p>{turn.question}</p>
      </div>
      <div className="result-head">
        <span className={`status-badge status-${r.status}`}>{statusLabel(r.status)}</span>
        {typeof r.confidence === "number" && (
          <span className="answer-confidence">確信度 {r.confidence.toFixed(2)}</span>
        )}
        <span className="correlation-id">{r.correlation_id || "—"}</span>
      </div>

      {r.text ? (
        <p className="answer-text">{r.text}</p>
      ) : (
        <p className="answer-text answer-text-muted">
          {blocked
            ? "安全ルールにより、確定した回答を保留しました。承認済みの手順が公開されるまでお待ちください。"
            : insufficient
              ? "承認済みの根拠が不足しているため、断定できません。文書の承認または追加が必要です。"
              : "対応する回答は返されませんでした。"}
        </p>
      )}

      <section className={`safety-panel ${blocked ? "safety-blocked" : ""}`}>
        <div className="safety-head">
          <span className="safety-title">{safetyLabel(r)}</span>
          {safety?.high_risk && <span className="safety-pill">高リスク</span>}
          {safety?.obsolete_warning && <span className="safety-pill warning">旧版参照</span>}
          {safety?.requires_onsite_confirmation && <span className="safety-pill warning">現場確認必須</span>}
        </div>
        <dl className="safety-fields">
          {safety?.safety_block_reason && (
            <div>
              <dt>保留理由</dt>
              <dd>{safety.safety_block_reason}</dd>
            </div>
          )}
          {reasonCodes.length > 0 && (
            <div>
              <dt>高リスク要因</dt>
              <dd>{reasonCodes.join(", ")}</dd>
            </div>
          )}
          {safety?.notice && (
            <div>
              <dt>注意</dt>
              <dd>{safety.notice}</dd>
            </div>
          )}
        </dl>
      </section>

      {r.citations.length > 0 ? (
        <div className="citation-list">
          <h3>引用ソース（{r.citations.length}）</h3>
          <div className="citation-grid">
            {r.citations.map((citation: Citation, index: number) => {
              const ap = citeApproval(citation.approval_status);
              return (
                <article className="citation-card" key={`${citation.document_id}-${index}`}>
                  <div className="citation-card-main">
                    <div className="citation-card-titles">
                      <strong>{citationLabel(citation)}</strong>
                      <span>
                        {citation.source_id} · v{citation.version}
                        {citation.effective_date ? ` · ${citation.effective_date}` : ""}
                      </span>
                    </div>
                    <span className={`citation-chip ${ap.cls}`}>{ap.label}</span>
                  </div>
                  <div className="citation-card-foot">
                    <output>スコア {citation.retrieval_score.toFixed(3)}</output>
                    <button
                      type="button"
                      className="citation-open"
                      onClick={() =>
                        onOpenCitation({
                          citation,
                          answerId: r.correlation_id,
                          groundedText: r.text,
                          index: index + 1,
                        })
                      }
                    >
                      引用を開く
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      ) : (
        !blocked && <p className="ops-note">引用ソースはありません。</p>
      )}

      <AnswerFeedback question={turn.question} answerId={r.correlation_id} />
    </section>
  );
}

function AnswersBody() {
  const [query, setQuery] = useState("");
  const [collectionId, setCollectionId] = useState(DEMO_COLLECTION);
  const [collections, setCollections] = useState<string[]>([DEMO_COLLECTION]);
  const [turns, setTurns] = useState<AnswerTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewer, setViewer] = useState<CitationViewTarget | null>(null);

  useEffect(() => {
    setCollectionId(loadAnswerCollection());
    void getSessionToken()
      .then((token) => adminDataSources(token))
      .then((sources) => {
        const ids = [...new Set(sources.map((source) => source.collection_id).filter(Boolean))].sort();
        if (ids.length > 0) setCollections(ids);
      })
      .catch(() => {
        /* keep default collection list */
      });
  }, []);

  function onCollectionChange(value: string) {
    setCollectionId(value);
    saveAnswerCollection(value);
  }

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    const targetCollection = collectionId.trim() || DEMO_COLLECTION;

    const turnId = `${Date.now().toString(36)}-${turns.length}`;
    setTurns((prev) => [...prev, { kind: "user", id: `${turnId}-q`, text: trimmed }]);
    setQuery("");
    setLoading(true);
    try {
      const token = await getSessionToken();
      const response = await manufacturingAnswer(
        { query: trimmed, collection_id: targetCollection },
        token,
      );
      recordAnswer(trimmed, response);
      setTurns((prev) => [...prev, { kind: "answer", id: `${turnId}-a`, question: trimmed, response }]);
    } catch (err) {
      clearSessionToken();
      setTurns((prev) => [
        ...prev,
        {
          kind: "error",
          id: `${turnId}-e`,
          question: trimmed,
          error: formatLoadError(err),
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <p className="src-warning">承認済みソースだけを参照し、危険度や旧版参照を明示して回答します。</p>
      <div className="answers-thread">
        {turns.length === 0 && !loading && (
          <div className="answer-empty-state">
            <div className="answer-empty-mark" aria-hidden="true" />
            <div>
              <strong>質問を入力してください</strong>
              <span>製造手順・規格・トラブル対応を横断検索します。</span>
            </div>
          </div>
        )}

        {turns.map((turn) => {
          if (turn.kind === "user") {
            return (
              <div className="answer-user-bubble" key={turn.id}>
                {turn.text}
              </div>
            );
          }
          if (turn.kind === "error") {
            return (
              <section className="result-panel error-panel" aria-live="polite" key={turn.id}>
                <h3>処理に失敗しました</h3>
                <p>{turn.error}</p>
              </section>
            );
          }
          return <AnswerPanel key={turn.id} turn={turn} onOpenCitation={setViewer} />;
        })}

        {loading && <p className="ops-empty" role="status" aria-live="polite">回答を生成中…</p>}
      </div>

      <form className="answers-composer" onSubmit={onAsk}>
        <div className="answers-composer-meta">
          <label className="answers-collection-field">
            <span>検索コレクション</span>
            <select
              aria-label="Collection"
              value={collectionId}
              onChange={(event) => onCollectionChange(event.target.value)}
            >
              {collections.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="answers-composer-inner">
          <textarea
            aria-label="Question"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void onAsk(event as unknown as FormEvent);
              }
            }}
            placeholder="製造手順・規格・トラブル対応を質問する…"
            rows={1}
          />
          <button type="submit" disabled={loading || query.trim().length === 0}>
            {loading ? "回答中" : "質問"}
          </button>
        </div>
      </form>

      <CitationViewer target={viewer} onClose={() => setViewer(null)} />
    </>
  );
}

function SourceSearchBody() {
  const [symptom, setSymptom] = useState("");
  const [collection, setCollection] = useState("manuals");
  const [tcResult, setTcResult] = useState<any | null>(null);
  const [tcLoading, setTcLoading] = useState(false);
  const [tcError, setTcError] = useState<string | null>(null);

  const [sourceId, setSourceId] = useState("");
  const [sync, setSync] = useState<any | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<any | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  async function onSearch(event: FormEvent) {
    event.preventDefault();
    const q = symptom.trim();
    if (!q || tcLoading) return;
    setTcLoading(true);
    setTcError(null);
    setTcResult(null);
    try {
      const token = await getSessionToken();
      setTcResult(
        await manufacturingTroubleCaseSearch(
          { symptom_query: q, collection_id: collection.trim() || "manuals" },
          token,
        ),
      );
    } catch (err) {
      clearSessionToken();
      setTcError(err instanceof Error ? err.message : "検索に失敗しました");
    } finally {
      setTcLoading(false);
    }
  }

  async function onSync(event: FormEvent) {
    event.preventDefault();
    const id = sourceId.trim();
    if (!id) return;
    setSyncError(null);
    setSync(null);
    try {
      const token = await getSessionToken();
      setSync(await manufacturingSourceSyncStatus(id, token));
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "参照に失敗しました");
    }
  }

  async function onRun(event: FormEvent) {
    event.preventDefault();
    const id = runId.trim();
    if (!id) return;
    setRunError(null);
    setRun(null);
    try {
      const token = await getSessionToken();
      setRun(await manufacturingIngestionRun(id, token));
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "参照に失敗しました");
    }
  }

  return (
    <div className="sources-layout standalone-sources-layout">
      <div className="sources-main">
        <form className="question-panel" onSubmit={onSearch}>
          <label className="src-field-label" htmlFor="symptom">
            承認済みソースを検索
          </label>
          <textarea
            id="symptom"
            aria-label="Symptom"
            value={symptom}
            onChange={(e) => setSymptom(e.target.value)}
            placeholder="製造手順・規格・トラブル対応を質問する…"
            rows={3}
          />
          <div className="composer-row">
            <span className="session-label">候補 / 参考のみ</span>
            <button type="submit" disabled={tcLoading || symptom.trim().length === 0}>
              {tcLoading ? "検索中" : "検索"}
            </button>
          </div>
        </form>

        {tcError && (
          <section className="result-panel error-panel" aria-live="polite">
            <h3>検索に失敗しました</h3>
            <p>{tcError}</p>
          </section>
        )}

        {tcResult?.matches?.length > 0 && (
          <div className="sources-results">
            {tcResult.matches.map((match: any) => (
              <article className="result-panel" key={match.trouble_case_id}>
                <div className="result-head">
                  <span className="status-badge">{match.symptom || match.trouble_case_id}</span>
                  <output>{match.relevance_score.toFixed(3)}</output>
                </div>
                <div className="ops-flags">
                  {match.equipment_id && <span className="citation-chip">equip {match.equipment_id}</span>}
                  {match.process_id && <span className="citation-chip">process {match.process_id}</span>}
                  <span className="citation-chip">case {match.trouble_case_id}</span>
                </div>
                {match.failure_mode && (
                  <div>
                    <h3 className="src-h4">原因候補</h3>
                    <p className="answer-text src-cause">
                      {match.failure_mode.name}
                      {match.failure_mode.description ? ` — ${match.failure_mode.description}` : ""}
                    </p>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}

        {!tcError && !tcLoading && !tcResult && (
          <p className="ops-empty">質問を入れると、候補と参照ソースを表示します。</p>
        )}
      </div>

      <aside className="sources-side">
        <section className="ops-panel">
            <h3>ソース状態</h3>
          <form className="src-inline-form" onSubmit={onSync}>
            <input
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              placeholder="source_id"
              aria-label="ソース ID"
              autoComplete="off"
            />
            <button type="submit">確認</button>
          </form>
          {syncError && <p className="ops-note">{syncError}</p>}
          {sync && <FieldGrid rows={[["状態", sync.status], ["コレクション", sync.collection_id ?? "—"], ["相関 ID", sync.correlation_id ?? "—"]]} />}
        </section>
        <section className="ops-panel">
          <h3>取り込み実行</h3>
          <form className="src-inline-form" onSubmit={onRun}>
            <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="run_id" aria-label="実行 ID" autoComplete="off" />
            <button type="submit">確認</button>
          </form>
          {runError && <p className="ops-note">{runError}</p>}
          {run && <FieldGrid rows={[["実行 ID", run.ingestion_run_id], ["状態", run.status], ["ソース", run.source_id ?? "—"]]} />}
        </section>
      </aside>
    </div>
  );
}

function screenTitle(screen: ManifestScreen): string {
  const titles: Record<string, string> = {
    answers: "質問する",
    "answer-history": "回答履歴",
    "source-search": "ソース",
    "source-list": "ソース一覧",
    "source-detail": "ソース詳細",
    "add-source": "ソースを追加",
    "ingestion-runs": "取り込み実行",
    "document-list": "ドキュメント",
    "document-detail": "ドキュメント詳細",
    "review-queue": "AIドラフトレビュー",
    "review-detail": "AIドラフト詳細",
    "approval-workflow-settings": "同期・承認ポリシー",
    "document-approval-queue": "根拠文書レビュー",
    "operations-dashboard": "運用ダッシュボード",
    "safety-telemetry": "安全テレメトリ",
    "quality-kpi": "品質・KPI",
    "impact-report": "導入効果レポート",
    "knowledge-improvement-queue": "ナレッジ改善キュー",
    "audit-log": "監査ログ",
    "compliance-export": "コンプライアンス出力",
    users: "ユーザー",
    "roles-groups-acl": "ロール・権限",
    "provider-policy": "プロバイダーポリシー",
    "retrieval-settings": "検索設定",
    "retrieval-debug": "検索診断",
    "logging-privacy": "ログ / プライバシー",
    integrations: "連携",
    "api-keys-webhooks": "APIキー / Webhook",
    "usage-billing": "利用状況 / 請求",
    "home-dashboard": "ホームダッシュボード",
    support: "サポート",
  };
  return titles[screen.id] ?? screen.title;
}

function ScreenShell({ screen, children }: { screen: ManifestScreen; children: ReactNode }) {
  return (
    <section className="workspace full-saas-workspace" aria-label={screen.title}>
      <header className="topbar">
        <div>
          <h2>{screenTitle(screen)}</h2>
        </div>
      </header>
      {children}
    </section>
  );
}

function ScreenLoadError({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <section className="result-panel error-panel" aria-live="polite">
      <h3>読み込みに失敗しました</h3>
      <p>{error}</p>
      {onRetry && (
        <div className="screen-actions">
          <button type="button" onClick={onRetry}>
            再試行
          </button>
        </div>
      )}
    </section>
  );
}

function MockBanner({ screen }: { screen: ManifestScreen }) {
  return (
    <p className="src-warning">
      {screen.title} の主要な確認項目を表示しています。連携状況に応じて表示内容は順次更新されます。
    </p>
  );
}

const SOURCE_SYNC_STATUS: Record<string, { label: string; key: string }> = {
  succeeded: { label: "同期済み", key: "ok" },
  idle: { label: "待機", key: "ok" },
  partially_succeeded: { label: "一部成功", key: "wait" },
  syncing: { label: "同期中", key: "wait" },
  queued: { label: "待機中", key: "wait" },
  observing: { label: "確認中", key: "wait" },
  failed: { label: "失敗", key: "bad" },
};

type SourceListRow = {
  source: AdminDataSource;
  sync: ManufacturingSourceSyncStatus | null;
  origin: "registered" | "documents";
  documentCount: number | null;
  approvedCount: number | null;
  pendingCount: number | null;
};

function sourceFreshness(row: SourceListRow): string {
  const at = row.source.last_synced_at;
  if (row.origin === "documents" && !at) return "取込済み";
  if (!at) return "未同期";
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime()) ? at : parsed.toLocaleString("ja-JP");
}

function valueLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(valueLabel).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function loadSourceListRows(): Promise<SourceListRow[]> {
  const token = await getSessionToken();
  const [sources, documents] = await Promise.all([
    adminDataSources(token),
    manufacturingDocuments(token).catch(() => [] as ManufacturingDocumentSummary[]),
  ]);
  const docStats = new Map<
    string,
    { sourceId: string; collectionId: string; documentCount: number; approvedCount: number; pendingCount: number }
  >();
  for (const doc of documents) {
    const sourceId = doc.source_id || "upload";
    const current =
      docStats.get(sourceId) ??
      {
        approvedCount: 0,
        collectionId: doc.collection_id || DEMO_COLLECTION,
        documentCount: 0,
        pendingCount: 0,
        sourceId,
      };
    current.documentCount += 1;
    if (doc.approval_status === "approved") current.approvedCount += 1;
    if (doc.approval_status === "pending_review") current.pendingCount += 1;
    docStats.set(sourceId, current);
  }
  const registered = await Promise.all(
    sources.map(async (source) => {
      let sync: ManufacturingSourceSyncStatus | null = null;
      try {
        sync = await manufacturingSourceSyncStatus(source.source_id, token);
      } catch {
        sync = null;
      }
      const stat = docStats.get(source.source_id);
      docStats.delete(source.source_id);
      return {
        approvedCount: stat?.approvedCount ?? null,
        documentCount: stat?.documentCount ?? null,
        origin: "registered" as const,
        pendingCount: stat?.pendingCount ?? null,
        source,
        sync,
      };
    }),
  );
  const fromDocuments: SourceListRow[] = [...docStats.values()]
    .sort((a, b) => a.sourceId.localeCompare(b.sourceId))
    .map((stat) => ({
      approvedCount: stat.approvedCount,
      documentCount: stat.documentCount,
      origin: "documents",
      pendingCount: stat.pendingCount,
      source: {
        audit_events: [],
        collection_id: stat.collectionId,
        config: {
          display_name: stat.sourceId === "upload" ? "ファイルアップロード" : stat.sourceId,
          source_type: "upload",
        },
        source_id: stat.sourceId,
        status: "active",
        tenant_id: "",
        type: "upload",
      },
      sync: null,
    }));
  return [...registered, ...fromDocuments];
}

function SourceListBody() {
  const [state, reload] = useLoad(loadSourceListRows, [], {
    pollIntervalMs: SYNC_POLL_MS,
    shouldPoll: (rows) => rows.some(({ sync }) => isSyncActive(sync?.status)),
  });
  const polling = state.state === "ready" && state.data.some(({ sync }) => isSyncActive(sync?.status));

  return (
    <div className="standalone-list-shell">
      <header className="standalone-list-head">
        <div className="standalone-list-head-title">
          <h3>ソース</h3>
          {polling && <span className="sync-poll-badge">同期中 — 自動更新</span>}
        </div>
        <div className="standalone-list-tools">
          <button type="button" className="is-secondary" onClick={reload}>
            更新
          </button>
          <Link href="/sources/new">ソースを追加</Link>
        </div>
      </header>
      {state.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">ソースを読み込み中…</p>}
      {state.state === "error" && <ScreenLoadError error={state.error} onRetry={reload} />}
      {state.state === "ready" &&
        (state.data.length === 0 ? (
          <div className="standalone-empty-state">
            <div className="standalone-empty-icon" aria-hidden="true">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h6a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                <path d="M12 11v5M9.5 13.5h5" />
              </svg>
            </div>
            <h4>まだソースが登録されていません</h4>
            <p>
              社内ドキュメントやデータソースを接続すると、根拠付きで横断検索・回答できるようになります。
            </p>
            <Link className="standalone-empty-cta" href="/sources/new">
              ソースを追加
            </Link>
          </div>
        ) : (
          <div className="standalone-table-wrap" role="table">
            <div className="standalone-table-head" role="row">
              <div role="columnheader">ソース</div>
              <div role="columnheader">種別</div>
              <div role="columnheader">ステータス</div>
              <div className="is-right" role="columnheader">文書数</div>
              <div className="is-right" role="columnheader">最終同期</div>
              <div role="columnheader">コレクション</div>
              <div role="columnheader">承認内訳</div>
            </div>
            {state.data.map((row) => {
              const { source, sync } = row;
              const config = (source.config ?? {}) as Record<string, unknown>;
              const name = (config.display_name as string) || source.source_id;
              const kind = (config.source_type as string) || source.type;
              const status =
                row.origin === "documents" && !sync
                  ? { label: "取込済み", key: "ok" }
                  : sync?.status
                    ? SOURCE_SYNC_STATUS[sync.status] ?? { label: sync.status, key: "wait" }
                    : { label: "未同期", key: "wait" };
              const changed = row.documentCount ?? sync?.summary?.changed_count;
              const approval =
                row.documentCount != null
                  ? `承認済み ${row.approvedCount ?? 0} / 承認待ち ${row.pendingCount ?? 0}`
                  : "プレビュー";
              const href = row.origin === "documents" ? "/documents" : `/sources/${source.source_id}`;
              return (
                <Link
                  key={source.source_id}
                  href={href}
                  className="standalone-table-row"
                  role="row"
                >
                  <div className="standalone-source-cell" role="cell">
                    <div className="standalone-source-mark">{kind.slice(0, 2).toUpperCase()}</div>
                    <span>{name}</span>
                  </div>
                  <div role="cell">{kind}</div>
                  <div role="cell">
                    <span className={`standalone-status ${status.key}`}>{status.label}</span>
                  </div>
                  <div className="is-right mono" role="cell">{changed ?? "—"}</div>
                  <div className="is-right muted" role="cell">{sourceFreshness(row)}</div>
                  <div className="muted" role="cell">{source.collection_id}</div>
                  <div role="cell">
                    <span className="standalone-status wait">{approval}</span>
                  </div>
                </Link>
              );
            })}
          </div>
        ))}
    </div>
  );
}

const PREVIEW_PROFILE_OPTIONS: Array<{ value: DataSourceProfileType; label: string }> = [
  { value: "auto", label: "自動判定" },
  { value: "manufacturing", label: "設備・工程データ" },
  { value: "faq", label: "FAQ" },
  { value: "manual", label: "マニュアル・手順書" },
  { value: "generic", label: "汎用文書" },
];
const PREVIEW_REQUIRED_FIELDS_BY_PROFILE: Record<DataSourceProfileType, string[]> = {
  auto: [],
  manufacturing: ["equipment_id"],
  faq: ["question", "answer"],
  manual: [],
  generic: [],
};
const PREVIEW_DISPLAY_FIELDS_BY_PROFILE: Record<string, string[]> = {
  manufacturing: [
    "equipment_id",
    "factory_id",
    "line_id",
    "process_id",
    "alarm_code",
    "defect_type",
    "part_no",
    "effective_date",
  ],
  faq: [
    "question",
    "answer",
    "category",
    "product_id",
    "product_name",
    "equipment_id",
    "published_at",
    "updated_at",
  ],
  manual: [
    "document_title",
    "document_version",
    "section",
    "heading",
    "body",
    "equipment_id",
    "published_at",
    "updated_at",
  ],
  generic: ["document_title", "category", "body", "owner_department", "published_at", "updated_at"],
};
const PREVIEW_DEFAULT_KIND_OPTIONS = [
  ["", "指定なし"],
  ["trouble_report", "トラブル報告"],
  ["work_instruction", "作業標準"],
  ["inspection_record", "検査記録"],
  ["maintenance_log", "保全記録"],
] as const;
const PREVIEW_APPROVAL_OPTIONS = [
  ["", "指定なし"],
  ["pending_review", "承認待ち"],
  ["approved", "承認済み"],
  ["draft", "ドラフト"],
  ["obsolete", "旧版"],
] as const;

function isDataSourceProfileType(value: unknown): value is DataSourceProfileType {
  return (
    value === "auto" ||
    value === "manufacturing" ||
    value === "faq" ||
    value === "manual" ||
    value === "generic"
  );
}

function splitPreviewFields(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function previewValidationClass(status: string): string {
  return status === "valid" ? "ok" : "wait";
}

function previewDisplayFields(preview: DataSourcePreviewResponse): string[] {
  const mapped = Object.values(preview.suggested_mapping);
  const normalized = new Set<string>();
  for (const row of preview.sample_rows) {
    for (const key of Object.keys(row.normalized ?? {})) normalized.add(key);
  }
  const preferred = PREVIEW_DISPLAY_FIELDS_BY_PROFILE[preview.profile_type] ?? [];
  const ordered = [
    ...preferred,
    ...preview.canonical_fields.filter((field) => !preferred.includes(field)),
  ];
  return ordered
    .filter((field, index, all) => all.indexOf(field) === index)
    .filter((field) => mapped.includes(field) || normalized.has(field))
    .slice(0, 8);
}

function SourcePreviewPanel({
  sourceId,
  collectionId,
}: {
  sourceId: string;
  collectionId?: string | null;
}) {
  const [profileType, setProfileType] = useState<DataSourceProfileType>("auto");
  const [sampleDocuments, setSampleDocuments] = useState(2);
  const [sampleRows, setSampleRows] = useState(8);
  const [requiredFields, setRequiredFields] = useState(
    PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "),
  );
  const [documentKind, setDocumentKind] = useState("");
  const [approvalStatus, setApprovalStatus] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [datasource, setDatasource] = useState<AdminDataSource | null>(null);
  const [preview, setPreview] = useState<DataSourcePreviewResponse | null>(null);
  const [mappingEdits, setMappingEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setPreview(null);
    setMappingEdits({});
    setMessage(null);
    setDatasource(null);
    setProfileType("auto");
    setRequiredFields(PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "));
    setDocumentKind("");
    setApprovalStatus("");
    setEffectiveDate("");
    void getSessionToken()
      .then((token) =>
        apiGetJson<AdminDataSource>(
          `/admin/datasources/${encodeURIComponent(sourceId)}`,
          token,
        ),
      )
      .then((data) => {
        if (!active) return;
        setDatasource(data);
        const rawProfile = data.config?.mapping_profile;
        if (!rawProfile || typeof rawProfile !== "object" || Array.isArray(rawProfile)) return;
        const mappingProfile = rawProfile as DataSourceMappingProfile;
        const storedProfile = mappingProfile.profile_type ?? mappingProfile.data_profile;
        if (isDataSourceProfileType(storedProfile)) {
          setProfileType(storedProfile);
          setRequiredFields(
            Array.isArray(mappingProfile.required_fields)
              ? mappingProfile.required_fields.join(", ")
              : PREVIEW_REQUIRED_FIELDS_BY_PROFILE[storedProfile].join(", "),
          );
        }
        if (mappingProfile.defaults && typeof mappingProfile.defaults === "object") {
          setDocumentKind(String(mappingProfile.defaults.document_kind ?? ""));
          setApprovalStatus(String(mappingProfile.defaults.approval_status ?? ""));
          setEffectiveDate(String(mappingProfile.defaults.effective_date ?? ""));
        }
        const storedMapping = {
          ...(mappingProfile.mapping ?? {}),
          ...(mappingProfile.field_mapping ?? {}),
        };
        setMappingEdits(storedMapping);
      })
      .catch(() => {
        if (active) setDatasource(null);
      });
    return () => {
      active = false;
    };
  }, [sourceId]);

  const displayFields = useMemo(() => (preview ? previewDisplayFields(preview) : []), [preview]);

  function onProfileTypeChange(value: DataSourceProfileType) {
    setProfileType(value);
    setRequiredFields(PREVIEW_REQUIRED_FIELDS_BY_PROFILE[value].join(", "));
    setPreview(null);
    setMessage(null);
  }

  async function runPreview(useEditedMapping: boolean) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const defaults: Record<string, unknown> = {};
      if (documentKind) defaults.document_kind = documentKind;
      if (approvalStatus) defaults.approval_status = approvalStatus;
      if (effectiveDate) defaults.effective_date = effectiveDate;

      const fieldMapping = useEditedMapping
        ? Object.fromEntries(
            Object.entries(mappingEdits).filter(([, target]) => target.trim()),
          )
        : undefined;
      const required = splitPreviewFields(requiredFields);

      const token = await getSessionToken();
      const data = await adminSourcePreview(
        sourceId,
        {
          collection_id: collectionId ?? undefined,
          profile_type: profileType,
          sample_documents: sampleDocuments,
          sample_rows: sampleRows,
          ...(fieldMapping && Object.keys(fieldMapping).length ? { field_mapping: fieldMapping } : {}),
          ...(Object.keys(defaults).length ? { defaults } : {}),
          ...(required.length ? { required_fields: required } : {}),
        },
        token,
      );
      setPreview(data);
      setMappingEdits((current) => {
        const next: Record<string, string> = { ...data.suggested_mapping };
        for (const column of data.detected_columns) {
          if (current[column] !== undefined) next[column] = current[column];
        }
        return next;
      });
    } catch (err) {
      setMessage(formatLoadError(err));
    } finally {
      setBusy(false);
    }
  }

  function updateMapping(column: string, target: string) {
    setMappingEdits((current) => ({ ...current, [column]: target }));
  }

  async function saveMappingProfile() {
    if (!preview || savingProfile) return;
    setSavingProfile(true);
    setMessage(null);
    try {
      const defaults: Record<string, unknown> = {};
      if (documentKind) defaults.document_kind = documentKind;
      if (approvalStatus) defaults.approval_status = approvalStatus;
      if (effectiveDate) defaults.effective_date = effectiveDate;
      const fieldMapping = Object.fromEntries(
        Object.entries(mappingEdits).filter(([, target]) => target.trim()),
      );
      const required = splitPreviewFields(requiredFields);
      const token = await getSessionToken();
      const current =
        datasource ??
        (await apiGetJson<AdminDataSource>(
          `/admin/datasources/${encodeURIComponent(sourceId)}`,
          token,
        ));
      const nextConfig: Record<string, unknown> = { ...(current.config ?? {}) };
      delete nextConfig.credential_status;
      nextConfig.mapping_profile = {
        profile_type: profileType === "auto" ? preview.profile_type : profileType,
        field_mapping: fieldMapping,
        defaults,
        required_fields: required,
      };
      await apiPutJson(
        `/admin/datasources/${encodeURIComponent(sourceId)}`,
        {
          collection_id: current.collection_id,
          type: current.type,
          config: nextConfig,
          sync_schedule: current.sync_schedule ?? null,
          status: current.status,
          reason: "mapping_profile_saved_from_preview",
        },
        token,
      );
      setDatasource({ ...current, config: nextConfig });
      setMessage("マッピング設定を保存しました。次回同期からこの設定を使います。");
    } catch (err) {
      setMessage(formatLoadError(err));
    } finally {
      setSavingProfile(false);
    }
  }

  return (
    <Section title="取込プレビュー" note="サンプル文書・行数・必須項目">
      <div className="preview-control-grid">
        <label>
          <span>データ種別</span>
          <select
            value={profileType}
            onChange={(e) => onProfileTypeChange(e.target.value as DataSourceProfileType)}
          >
            {PREVIEW_PROFILE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>文書数</span>
          <input
            type="number"
            min={1}
            max={10}
            value={sampleDocuments}
            onChange={(e) => setSampleDocuments(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
        <label>
          <span>行数</span>
          <input
            type="number"
            min={1}
            max={50}
            value={sampleRows}
            onChange={(e) => setSampleRows(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
        <label>
          <span>文書種別</span>
          <select value={documentKind} onChange={(e) => setDocumentKind(e.target.value)}>
            {PREVIEW_DEFAULT_KIND_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>承認状態</span>
          <select value={approvalStatus} onChange={(e) => setApprovalStatus(e.target.value)}>
            {PREVIEW_APPROVAL_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>発効日</span>
          <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
        </label>
        <label>
          <span>必須項目</span>
          <input value={requiredFields} onChange={(e) => setRequiredFields(e.target.value)} />
        </label>
      </div>

      <div className="screen-actions">
        <button type="button" disabled={busy} onClick={() => void runPreview(false)}>
          {busy ? "確認中…" : "プレビュー実行"}
        </button>
        {preview && (
          <button type="button" disabled={busy} onClick={() => void runPreview(true)}>
            補正して再プレビュー
          </button>
        )}
        {preview && (
          <button type="button" disabled={busy || savingProfile} onClick={() => void saveMappingProfile()}>
            {savingProfile ? "保存中…" : "この設定を保存"}
          </button>
        )}
      </div>
      {message && <p className="src-warning">{message}</p>}

      {preview && (
        <div className="preview-results">
          <div className="preview-summary">
            <span>
              <strong>{preview.profile_label}</strong>
              判定
            </span>
            <span>
              <strong>{preview.document_count}</strong>
              文書
            </span>
            <span>
              <strong>{preview.detected_columns.length}</strong>
              列
            </span>
            <span>
              <strong>{preview.validation.valid_count}</strong>
              正常行
            </span>
            <span>
              <strong>{preview.validation.needs_review_count}</strong>
              要確認行
            </span>
          </div>

          {preview.detected_columns.length > 0 && (
            <div className="preview-map">
              <div className="preview-map-head">
                <span>元カラム</span>
                <span>標準項目</span>
                <span>信頼度</span>
              </div>
              {preview.detected_columns.map((column) => (
                <div key={column} className="preview-map-row">
                  <span className="mono">{column}</span>
                  <select
                    value={mappingEdits[column] ?? preview.suggested_mapping[column] ?? ""}
                    onChange={(e) => updateMapping(column, e.target.value)}
                    aria-label="標準項目マッピング"
                  >
                    <option value="">未使用</option>
                    {preview.canonical_fields.map((field) => (
                      <option key={field} value={field}>
                        {field}
                      </option>
                    ))}
                  </select>
                  <span className="mono">
                    {preview.mapping_confidence[column] != null
                      ? `${Math.round(preview.mapping_confidence[column] * 100)}%`
                      : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}

          <DataTable
            columns={["行", "状態", ...displayFields, "メッセージ"]}
            rows={preview.sample_rows.map((row) => [
              `${row.document_id}:${row.row_number}`,
              <span className={`standalone-status ${previewValidationClass(row.validation.status)}`}>
                {row.validation.status === "valid" ? "正常" : "要確認"}
              </span>,
              ...displayFields.map((field) => valueLabel(row.normalized[field])),
              [...row.validation.errors, ...row.validation.warnings].join(" / ") || "—",
            ])}
            empty="サンプル行はありません。"
          />

          {preview.documents.some((doc) => doc.text_preview) && (
            <div className="preview-docs">
              {preview.documents
                .filter((doc) => doc.text_preview)
                .map((doc) => (
                  <pre key={doc.document_id} className="code-block">
                    {doc.document_id}
                    {"\n"}
                    {doc.text_preview}
                  </pre>
                ))}
            </div>
          )}
        </div>
      )}
    </Section>
  );
}

function AnswerHistoryBody() {
  const [entries, setEntries] = useState<AnswerHistoryEntry[]>([]);

  useEffect(() => {
    setEntries(loadAnswerHistory());
  }, []);

  function onClear() {
    clearAnswerHistory();
    setEntries([]);
  }

  function safetyTag(entry: AnswerHistoryEntry): string {
    if (entry.blocked) return "保留";
    if (entry.high_risk) return "高リスク";
    if (entry.obsolete) return "旧版参照";
    return "正常";
  }

  return (
    <Section
      title="回答履歴"
      note="このブラウザで確認できる質問履歴です。"
    >
      {entries.length === 0 ? (
        <p className="ops-empty">まだ履歴はありません。「質問する」から質問すると、ここに残ります。</p>
      ) : (
        <>
          <DataTable
            columns={["質問", "状態", "安全", "引用", "日時"]}
            rows={entries.map((entry) => [
              entry.question,
              statusLabel(entry.status),
              safetyTag(entry),
              String(entry.citation_count),
              new Date(entry.asked_at).toLocaleString("ja-JP"),
            ])}
            empty="まだ履歴はありません。"
          />
          <div className="screen-actions">
            <button type="button" className="btn-reject" onClick={onClear}>
              履歴を消去
            </button>
          </div>
        </>
      )}
    </Section>
  );
}

function HomeDashboardBody() {
  const [state, reload] = useLoad(
    async () => {
      const token = await getSessionToken();
      const [dashboard, telemetry, kpi, governance] = await Promise.all([
        manufacturingDashboard(token),
        manufacturingSafetyTelemetry(token),
        manufacturingKpi(token),
        manufacturingGovernanceStatus(token),
      ]);
      return { dashboard, telemetry, kpi, governance };
    },
    [],
  );

  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">ホームダッシュボードを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;

  const { dashboard, telemetry, kpi, governance } = state.data;
  return (
    <>
      <Section title="今日のタスク" note="ホームでは今日の作業をひと目で確認できます。">
        <div className="home-task-grid">
          <Link href="/reviews" className="home-task-card">
            <div className="home-task-head">
              <span className="home-task-label">AIドラフト</span>
              <span className="home-task-dot" />
            </div>
            <strong>{dashboard.unanswered_question_count}</strong>
            <span>未回答の質問</span>
            <span className="home-task-cta">レビューへ</span>
          </Link>
          <Link href="/operations/safety" className="home-task-card">
            <div className="home-task-head">
              <span className="home-task-label">安全ブロック</span>
              <span className="home-task-dot home-task-dot-warn" />
            </div>
            <strong>{telemetry.safety_gate_block_count}</strong>
            <span>安全ルールで止まった件数</span>
            <span className="home-task-cta">テレメトリを見る</span>
          </Link>
          <Link href="/operations" className="home-task-card">
            <div className="home-task-head">
              <span className="home-task-label">高リスク</span>
              <span className="home-task-dot home-task-dot-danger" />
            </div>
            <strong>{telemetry.high_risk_query_count}</strong>
            <span>注意が必要な問い合わせ</span>
            <span className="home-task-cta">運用を見る</span>
          </Link>
          <Link href="/operations/quality" className="home-task-card">
            <div className="home-task-head">
              <span className="home-task-label">自己解決率</span>
              <span className="home-task-dot home-task-dot-ok" />
            </div>
            <strong>{(kpi.self_resolution_rate * 100).toFixed(1)}%</strong>
            <span>エスカレーションせず解決した割合</span>
            <span className="home-task-cta">KPI を見る</span>
          </Link>
        </div>
      </Section>
      <div className="home-split">
        <Section title="クイックアクセス" note="主要ワークスペースへすぐ移動できます。">
          <div className="quick-card-grid">
            <Link href="/" className="action-card">
              <strong>質問する</strong>
              <span>根拠付きの質問を投げる</span>
            </Link>
            <Link href="/sources/list" className="action-card">
              <strong>ソース一覧</strong>
              <span>接続済みソースと同期状態を確認する</span>
            </Link>
            <Link href="/reviews" className="action-card">
              <strong>AIドラフトレビュー</strong>
              <span>AI ドラフトを確認する</span>
            </Link>
            <Link href="/operations" className="action-card">
              <strong>運用</strong>
              <span>安全性と KPI を見る</span>
            </Link>
          </div>
        </Section>
        <Section title="ガバナンス" note={governance.ismap_readiness_memo ?? "メモはありません。"}>
          <FieldGrid
            rows={[
              ["ポリシー版本", String(governance.policy_version)],
              ["No-train デフォルト", governance.no_train.no_train_default ? "はい" : "いいえ"],
              ["提供元 no-train 必須", governance.no_train.provider_no_train_required ? "はい" : "いいえ"],
              ["高リスク回答は承認済み根拠が必須", governance.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
              ["引用必須", governance.groundedness.citation_required ? "はい" : "いいえ"],
            ]}
          />
        </Section>
      </div>
    </>
  );
}

function SourceDetailBody({ sourceId }: { sourceId: string }) {
  const [syncState, setSyncState] = useState<ViewState<ManufacturingSourceSyncStatus>>({ state: "loading" });
  const [runState, setRunState] = useState<ViewState<ManufacturingIngestionRun | null>>({ state: "loading" });
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const reload = useCallback(() => setRefreshTick((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setSyncState({ state: "loading" });
    setRunState({ state: "loading" });
    runWithToken((token) => manufacturingSourceSyncStatus(sourceId, token))
      .then((data) => {
        if (!active) return;
        setSyncState({ state: "ready", data });
        const latest = data.correlation_id;
        if (!latest) {
          setRunState({ state: "ready", data: null });
          return;
        }
        return runWithToken((token) => manufacturingIngestionRun(latest, token));
      })
      .then((data) => {
        if (active) setRunState({ state: "ready", data: data ?? null });
      })
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) {
          setSyncState({ state: "error", error: formatLoadError(err) });
          setRunState({ state: "ready", data: null });
        }
      });
    return () => {
      active = false;
    };
  }, [sourceId, refreshTick]);

  useEffect(() => {
    if (syncState.state !== "ready" || !isSyncActive(syncState.data.status)) return;
    const id = window.setInterval(reload, SYNC_POLL_MS);
    return () => window.clearInterval(id);
  }, [syncState, reload]);

  async function onSyncRequest(event: FormEvent) {
    event.preventDefault();
    setSyncMessage(null);
    try {
      await runWithToken((token) => manufacturingRequestSourceSync(sourceId, { reason: "manual_refresh" }, token));
      setSyncMessage("同期を依頼しました");
      reload();
    } catch (err) {
      setSyncMessage(formatLoadError(err));
    }
  }

  const polling = syncState.state === "ready" && isSyncActive(syncState.data.status);

  return (
    <>
      <Section title="ソース操作" note="同期操作は明示的で監査可能です。">
        <form className="src-inline-form" onSubmit={onSyncRequest}>
          <input value={sourceId} readOnly aria-label="ソース ID" />
          <button type="submit">同期を依頼</button>
          <button type="button" onClick={reload}>
            状態を更新
          </button>
        </form>
        {polling && <p className="ops-note">同期中です — {SYNC_POLL_MS / 1000} 秒ごとに自動更新します。</p>}
        {syncMessage && <p className="ops-note">{syncMessage}</p>}
      </Section>

      <SourcePreviewPanel
        sourceId={sourceId}
        collectionId={syncState.state === "ready" ? syncState.data.collection_id : undefined}
      />

      {syncState.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">ソース同期状態を読み込み中…</p>}
      {syncState.state === "error" && <ScreenLoadError error={syncState.error} onRetry={reload} />}
      {syncState.state === "ready" && (
        <>
          <Section title="同期状態">
            <FieldGrid
              rows={[
                ["状態", syncState.data.status],
                ["コレクション", syncState.data.collection_id ?? "—"],
                ["相関 ID", syncState.data.correlation_id ?? "—"],
                ["観測数", syncState.data.summary.observed_count ?? "—"],
                ["変更数", syncState.data.summary.changed_count ?? "—"],
                ["削除数", syncState.data.summary.deleted_count ?? "—"],
              ]}
            />
          </Section>
          <Section title="最新ドキュメント" note="ドキュメント状態は同期ビューから取得しています。">
            <DataTable
              columns={["文書", "状態", "チャンク", "更新"]}
              rows={syncState.data.documents.map((doc) => [
                doc.document_id,
                doc.status,
                doc.chunk_count ?? "—",
                doc.updated_at ?? "—",
              ])}
              empty="文書の投影は返されませんでした。"
            />
          </Section>
        </>
      )}

      {runState.state === "ready" && runState.data && (
        <Section title="最新取り込み実行">
          <FieldGrid
            rows={[
              ["実行 ID", runState.data.ingestion_run_id],
              ["状態", runState.data.status],
              ["ソース", runState.data.source_id ?? "—"],
              ["コレクション", runState.data.collection_id ?? "—"],
              ["開始", runState.data.started_at ?? "—"],
              ["終了", runState.data.finished_at ?? "—"],
            ]}
          />
        </Section>
      )}
    </>
  );
}

const DOC_APPROVAL_STATUS: Record<string, { label: string; cls: string }> = {
  draft: { label: "ドラフト", cls: "approval-draft" },
  pending_review: { label: "承認待ち", cls: "approval-draft" },
  approved: { label: "承認済み", cls: "approval-approved" },
  obsolete: { label: "旧版", cls: "approval-obsolete" },
};

const DOC_LIFECYCLE_RANK: Record<string, number> = {
  draft: 0,
  pending_review: 1,
  approved: 2,
  obsolete: 3,
};

function DocumentApprovalQueueBody() {
  const [docs, setDocs] = useState<IngestedDoc[]>([]);
  const [serverDocs, setServerDocs] = useState<
    Array<{ document_id: string; approval_status: string; collection_id: string; effective_date: string | null }>
  >([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    setDocs(loadIngestedDocs());
    try {
      const token = await getSessionToken();
      // Manufacturing approval queue reads the manufacturing overlay endpoint (same one its
      // approve/obsolete writes use). The old /admin/documents path 404s on this build, leaving the
      // queue silently empty even when 18 docs exist.
      const rows = await manufacturingDocuments(token);
      setServerDocs(rows);
    } catch {
      setServerDocs([]);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  const merged = [
    ...serverDocs.map((d) => ({
      document_id: d.document_id,
      filename: d.document_id,
      collection_id: d.collection_id,
      approval_status: d.approval_status,
      effective_date: d.effective_date,
      chunk_count: 0,
      source: "server" as const,
    })),
    ...docs
      .filter((d) => !serverDocs.some((s) => s.document_id === d.document_id))
      .map((d) => ({ ...d, source: "local" as const })),
  ];

  async function transition(doc: { document_id: string; approval_status: string; effective_date: string | null }, toStatus: string) {
    if (busy) return;
    setBusy(doc.document_id);
    setError(null);
    setMessage(null);
    try {
      const token = await getSessionToken();
      const res = await manufacturingDocumentApproval(doc.document_id, { to_status: toStatus }, token);
      const state = (res.approval_state ?? {}) as { approval_status?: string; effective_date?: string | null };
      const nextStatus = state.approval_status ?? toStatus;
      updateIngestedDoc(doc.document_id, {
        approval_status: nextStatus,
        effective_date: state.effective_date ?? doc.effective_date,
      });
      await reload();
      setMessage(`${doc.document_id} を「${DOC_APPROVAL_STATUS[nextStatus]?.label ?? nextStatus}」に更新しました。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setBusy(null);
    }
  }

  const pending = merged.filter((d) => (DOC_LIFECYCLE_RANK[d.approval_status] ?? 0) < 2);

  return (
    <>
      <p className="src-warning">
        取り込んだ文書は、ここで承認するまで正式な根拠になりません。AIドラフトのレビュー（
        <Link href="/reviews">AIドラフトレビュー</Link>）とは別キューです。
      </p>
      <Section
        title="根拠文書レビュー"
        note={`テナント ${merged.length} 件（承認待ち相当 ${pending.length} 件）。承認すると質問の正式な根拠になります。`}
      >
        {merged.length === 0 ? (
          <p className="ops-empty">
            取り込んだ文書がありません。<Link href="/sources/new">ソースを追加</Link> からアップロードしてください。
          </p>
        ) : (
          <div className="approval-list">
            {merged.map((doc) => {
              const st = DOC_APPROVAL_STATUS[doc.approval_status] ?? {
                label: doc.approval_status,
                cls: "approval-draft",
              };
              const rank = DOC_LIFECYCLE_RANK[doc.approval_status] ?? 0;
              const isBusy = busy === doc.document_id;
              return (
                <article className="approval-row" key={doc.document_id}>
                  <div className="approval-row-main">
                    <div className="approval-row-titles">
                      <strong>{doc.document_id}</strong>
                      <span>
                        {doc.filename} · {doc.collection_id} · 発効 {doc.effective_date ?? "—"} · {doc.chunk_count} チャンク
                      </span>
                    </div>
                    <span className={`citation-chip ${st.cls}`}>{st.label}</span>
                  </div>
                  <div className="approval-row-actions">
                    {rank < 2 && (
                      <button
                        type="button"
                        className="btn-approve"
                        disabled={isBusy}
                        onClick={() => void transition(doc, "approved")}
                      >
                        承認
                      </button>
                    )}
                    {rank < 3 && (
                      <button type="button" disabled={isBusy} onClick={() => void transition(doc, "obsolete")}>
                        旧版化
                      </button>
                    )}
                    {rank >= 3 && <span className="ops-note">終了状態</span>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
        {message && <p className="cv-foot-done">{message}</p>}
        {error && <p className="cv-foot-error" role="alert">{error}</p>}
      </Section>
    </>
  );
}

function ReviewDetailBody({ artifactId }: { artifactId: string }) {
  const [draftState, setDraftState] = useState<ViewState<DraftArtifact>>({ state: "loading" });
  const [reviewerId, setReviewerId] = useState("");
  const [comment, setComment] = useState("");
  const [docId, setDocId] = useState("");
  const [approvalState, setApprovalState] = useState("pending_review");
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // The pending approve/reject awaiting confirmation (null = no dialog open). Approval is irreversible
  // and audited, so it always passes through a confirm step. (issue 0015)
  const [confirmKind, setConfirmKind] = useState<"approved" | "rejected" | null>(null);

  useEffect(() => {
    let active = true;
    setDraftState({ state: "loading" });
    // Reset all per-draft action/form state so a confirm dialog or in-flight flag can't carry over to a
    // DIFFERENT draft (e.g. via browser back/forward) and act on the wrong artifact — approval is
    // irreversible and audited. (issue 0015)
    setConfirmKind(null);
    setSaving(false);
    setActionError(null);
    setComment("");
    setReviewerId("");
    setDocId("");
    runWithToken((token) => manufacturingGetDraft(artifactId, token))
      .then((data) => active && setDraftState({ state: "ready", data }))
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) setDraftState({ state: "error", error: err instanceof Error ? err.message : "リクエストに失敗しました" });
      });
    return () => {
      active = false;
    };
  }, [artifactId]);

  async function onAssign() {
    if (draftState.state !== "ready" || saving) return;
    setActionError(null);
    setSaving(true);
    try {
      await runWithToken((token) => manufacturingAssignReviewer(artifactId, { reviewer_id: reviewerId }, token));
      const refreshed = await runWithToken((token) => manufacturingGetDraft(artifactId, token));
      setDraftState({ state: "ready", data: refreshed });
      updateDraftRecord(artifactId, { status: refreshed.status, reviewer_id: refreshed.reviewer_id });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    } finally {
      setSaving(false);
    }
  }

  async function onReview(decision: "approved" | "rejected") {
    if (draftState.state !== "ready" || saving) return;
    // A rejection must carry a reason for the audit trail (HR5). Defense in depth — the reject button
    // is also disabled while the comment is empty. (issue 0015)
    if (decision === "rejected" && !comment.trim()) {
      setActionError("却下にはレビューコメント(理由)が必要です。");
      setConfirmKind(null);
      return;
    }
    setActionError(null);
    setSaving(true);
    try {
      await runWithToken((token) =>
        manufacturingReviewDraft(artifactId, { decision, comment: comment.trim() || undefined }, token),
      );
      const refreshed = await runWithToken((token) => manufacturingGetDraft(artifactId, token));
      setDraftState({ state: "ready", data: refreshed });
      updateDraftRecord(artifactId, { status: refreshed.status });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    } finally {
      setSaving(false);
      setConfirmKind(null);
    }
  }

  async function onApproveDocument() {
    if (!docId.trim() || saving) return;
    setActionError(null);
    setSaving(true);
    try {
      await runWithToken((token) => manufacturingDocumentApproval(docId.trim(), { to_status: approvalState }, token));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    } finally {
      setSaving(false);
    }
  }

  if (draftState.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">ドラフトを読み込み中…</p>;
  if (draftState.state === "error") return <ScreenLoadError error={draftState.error} />;

  const draft = draftState.data;
  const content = draft.content as {
    kind?: string;
    notice?: string;
    items?: unknown[];
    evidence_citations?: unknown[];
  };
  const items = Array.isArray(content.items) ? content.items : [];
  const st = draftStatusLabel(draft.status);
  const terminal = draft.status === "approved" || draft.status === "rejected" || draft.status === "archived";

  return (
    <>
      <div className="review-detail-head">
        <div className="review-detail-titles">
          <span className="eyebrow">{draftKindLabel(draft.type)} ドラフト</span>
          <h3>{draft.artifact_id}</h3>
        </div>
        <span className={`citation-chip ${st.cls}`}>{st.label}</span>
      </div>

      {!terminal && (
        <p className="src-warning">
          {content.notice ??
            "このドラフトは未承認です。AI 出力はレビューで承認されるまで正式な知識・公開物にはなりません。"}
        </p>
      )}
      {draft.status === "approved" && (
        <p className="ops-note" role="status" aria-live="polite" style={{ color: "#15803d", fontWeight: 600 }}>
          承認済み — このドラフトは正式に公開できます。
        </p>
      )}
      {draft.status === "rejected" && (
        <p className="ops-note" role="status" aria-live="polite" style={{ color: "#be123c", fontWeight: 600 }}>
          却下 — 修正のうえ再生成が必要です。
        </p>
      )}

      <Section title="ドラフト詳細" note="AI 出力は、レビューで状態が変わるまでドラフトのままです。">
        <FieldGrid
          rows={[
            ["ドラフト ID", draft.artifact_id],
            ["種別", draftKindLabel(draft.type)],
            ["状態", st.label],
            [
              "作成者",
              draft.created_by === "ai" ? "AI" : draft.created_by === "user" ? "担当者" : (draft.created_by ?? "—"),
            ],
            ["レビュー担当", draft.reviewer_id ?? "未割当"],
            [
              "決定",
              draft.approval_decision
                ? (APPROVAL_DECISION_LABEL[draft.approval_decision] ?? draft.approval_decision)
                : "—",
            ],
            ["根拠ドキュメント", draft.source_document_ids.length ? draft.source_document_ids.join(", ") : "—"],
            ["監査参照", draft.audit_log_ref ?? "—"],
          ]}
        />
      </Section>

      <Section title="内容">
        {items.length > 0 ? (
          <ol className="draft-items">
            {items.map((item, i) => (
              <li key={i}>{typeof item === "string" ? item : JSON.stringify(item)}</li>
            ))}
          </ol>
        ) : (
          <p className="ops-note">
            根拠ドキュメントから具体項目を抽出できませんでした。
            ステータス遷移とレビュー手順を確認するためのドラフトです。
          </p>
        )}
        {draft.source_citations.length > 0 && (
          <div className="ops-flags">
            {draft.source_citations.map((c) => (
              <span className="citation-chip" key={c}>
                {c}
              </span>
            ))}
          </div>
        )}
        <details className="draft-raw">
          <summary>生データ (JSON)</summary>
          <pre className="code-block">{JSON.stringify(draft.content, null, 2)}</pre>
        </details>
      </Section>

      <Section title="レビュー操作" note={terminal ? "このドラフトは終了状態です。" : undefined}>
        <div className="form-grid">
          <div className="review-assign-row">
            <input
              value={reviewerId}
              onChange={(e) => setReviewerId(e.target.value)}
              placeholder="reviewer_id（担当者ID）"
              aria-label="レビュー担当者ID"
              disabled={terminal || saving}
            />
            <button type="button" onClick={() => void onAssign()} disabled={terminal || saving || !reviewerId.trim()}>
              {saving ? "処理中…" : "担当に割り当て"}
            </button>
          </div>
          {draft.status === "draft" && (
            <p className="ops-note" role="note">
              承認・却下の前に、まず担当者を割り当ててレビューを開始してください。
            </p>
          )}
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            aria-label="レビューコメント"
            placeholder={draft.status === "in_review" ? "レビューコメント（却下時は理由が必須）" : "レビューコメント（任意）"}
            rows={3}
            disabled={terminal || saving}
          />
          <div className="review-decide">
            <button
              type="button"
              className="btn-approve"
              onClick={() => setConfirmKind("approved")}
              disabled={saving || draft.status !== "in_review"}
            >
              承認・公開
            </button>
            <button
              type="button"
              className="btn-reject"
              onClick={() => setConfirmKind("rejected")}
              disabled={saving || draft.status !== "in_review" || !comment.trim()}
            >
              却下
            </button>
          </div>
          {draft.status === "in_review" && !comment.trim() && (
            <p className="ops-note" role="note">
              却下する場合はレビューコメント（理由）が必須です。
            </p>
          )}
        </div>
      </Section>

      <Section title="根拠文書レビュー">
        <div className="form-grid">
          <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="document_id" aria-label="ドキュメントID" />
          <select value={approvalState} onChange={(e) => setApprovalState(e.target.value)} aria-label="承認状態">
            <option value="pending_review">pending_review</option>
            <option value="approved">approved</option>
            <option value="obsolete">obsolete</option>
            <option value="draft">draft</option>
          </select>
          <button type="button" onClick={() => void onApproveDocument()} disabled={!docId.trim() || saving}>
            {saving ? "処理中…" : "変更"}
          </button>
        </div>
      </Section>
      {actionError && (
        <p className="src-warning" role="alert">
          {actionError}
        </p>
      )}
      {confirmKind && (
        <ConfirmDialog
          title={confirmKind === "approved" ? "このドラフトを承認しますか？" : "このドラフトを却下しますか？"}
          body={
            confirmKind === "approved"
              ? "承認すると正式なレビュー結果として監査に記録されます。この操作は取り消せません。"
              : "却下するとこのドラフトは終了状態になります。この操作は取り消せません。"
          }
          confirmLabel={confirmKind === "approved" ? "承認する" : "却下する"}
          danger={confirmKind === "rejected"}
          busy={saving}
          onCancel={() => setConfirmKind(null)}
          onConfirm={() => void onReview(confirmKind)}
        />
      )}
    </>
  );
}

const DRAFT_KINDS: Array<{ value: string; label: string }> = [
  { value: "checklist", label: "点検チェックリスト" },
  { value: "trouble_report", label: "トラブル報告" },
  { value: "quality_report", label: "品質報告" },
  { value: "training", label: "教育資料" },
  { value: "faq", label: "FAQ" },
];

const DRAFT_STATUS_LABEL: Record<string, { label: string; cls: string }> = {
  draft: { label: "ドラフト", cls: "approval-draft" },
  in_review: { label: "レビュー中", cls: "approval-draft" },
  approved: { label: "承認済み", cls: "approval-approved" },
  rejected: { label: "却下", cls: "approval-obsolete" },
  archived: { label: "アーカイブ", cls: "approval-obsolete" },
};

const APPROVAL_DECISION_LABEL: Record<string, string> = {
  approved: "承認",
  rejected: "却下",
  archived: "アーカイブ",
};

// Confirmation dialog for irreversible, audited review actions (approve / reject). Reuses the Citation
// Viewer modal styles and the useDialog hook (focus trap, Escape-to-close, focus restore). (issue 0015)
function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  // Stay focus-trapped while open; ignore Escape/backdrop/cancel while a request is in flight.
  const cancel = () => {
    if (!busy) onCancel();
  };
  useDialog(true, cancel, panelRef);
  return (
    <div className="cv-overlay" onClick={cancel}>
      <div
        className="cv-panel"
        ref={panelRef}
        tabIndex={-1}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-body"
        aria-busy={busy}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cv-head">
          <div className="cv-head-titles">
            <span className="cv-eyebrow">確認</span>
            <h3 id="confirm-dialog-title">{title}</h3>
          </div>
          <button type="button" className="cv-close" onClick={cancel} disabled={busy} aria-label="閉じる">
            ×
          </button>
        </div>
        <p className="ops-note" id="confirm-dialog-body">
          {body}
        </p>
        <div className="review-decide">
          <button
            type="button"
            className={danger ? "btn-reject" : "btn-approve"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "処理中…" : confirmLabel}
          </button>
          <button type="button" onClick={cancel} disabled={busy}>
            キャンセル
          </button>
        </div>
      </div>
    </div>
  );
}

function draftStatusLabel(status: string): { label: string; cls: string } {
  return DRAFT_STATUS_LABEL[status] ?? { label: status, cls: "approval-draft" };
}

function draftKindLabel(kind: string): string {
  return DRAFT_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

function ReviewQueueBody() {
  const router = useRouter();
  const [drafts, setDrafts] = useState<DraftRecord[]>([]);
  const [kind, setKind] = useState("checklist");
  const [docIds, setDocIds] = useState("m1");
  const [collection, setCollection] = useState("manuals");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reloadDrafts() {
    try {
      const token = await getSessionToken();
      const rows = await manufacturingListDrafts(token);
      setDrafts(
        rows.map((d) => ({
          artifact_id: d.artifact_id,
          kind: d.type,
          status: d.status,
          source_document_ids: d.source_document_ids ?? [],
          reviewer_id: d.reviewer_id ?? null,
          created_at: d.created_at ?? new Date().toISOString(),
        })),
      );
    } catch {
      setDrafts(loadDrafts());
    }
  }

  useEffect(() => {
    void reloadDrafts();
  }, []);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const token = await getSessionToken();
      const ids = docIds
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const draft = await manufacturingCreateDraft(
        {
          kind,
          source_document_ids: ids.length ? ids : undefined,
          collection_id: collection.trim() || undefined,
        },
        token,
      );
      recordDraft({
        artifact_id: draft.artifact_id,
        kind: draft.type,
        status: draft.status,
        source_document_ids: draft.source_document_ids ?? ids,
        reviewer_id: draft.reviewer_id ?? null,
        created_at: draft.created_at ?? new Date().toISOString(),
      });
      router.push(`/reviews/${draft.artifact_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ドラフト生成に失敗しました");
      setCreating(false);
    }
  }

  return (
    <>
      <p className="src-warning">
        AI 出力は常にドラフトです。人手レビューで承認されるまで、正式な知識にはなりません（自動承認は禁止）。
      </p>
      <div className="reviews-layout standalone-reviews-layout">
        <section className="review-queue-panel" aria-label="AIドラフトレビュー">
          <div className="review-queue-head">
            <h3>AIドラフトレビュー</h3>
            <span className="review-queue-count">{drafts.length}</span>
          </div>
          {drafts.length === 0 ? (
            <p className="ops-empty">
              まだドラフトはありません。右の「AI ドラフトを作成」から生成してください。
            </p>
          ) : (
            <div className="review-queue-list">
              {drafts.map((draft) => {
                const st = draftStatusLabel(draft.status);
                return (
                  <Link key={draft.artifact_id} href={`/reviews/${draft.artifact_id}`} className="review-queue-row">
                    <span className={`review-queue-status ${st.cls}`}>{st.label}</span>
                    <strong>{draft.artifact_id}</strong>
                    <span>{draftKindLabel(draft.kind)}</span>
                    <span className="review-queue-reviewer">{draft.reviewer_id ?? "未割当"}</span>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <section className="result-panel">
          <h3>AI ドラフトを作成</h3>
          <p className="ops-note">承認済みソースを根拠に、レビュー必須のドラフトを生成します。</p>
          <form className="draft-create-form" onSubmit={onCreate}>
            <label>
              <span>種別</span>
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {DRAFT_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>根拠ドキュメント ID（カンマ区切り）</span>
              <input value={docIds} onChange={(e) => setDocIds(e.target.value)} placeholder="m1, belt-c7" />
            </label>
            <label>
              <span>コレクション</span>
              <input value={collection} onChange={(e) => setCollection(e.target.value)} />
            </label>
            <button type="submit" disabled={creating}>
              {creating ? "生成中…" : "ドラフトを生成"}
            </button>
          </form>
          {error && <p className="cv-foot-error" role="alert">{error}</p>}
        </section>
      </div>
    </>
  );
}

function IngestionRunsBody() {
  const [runId, setRunId] = useState("");
  const [state, setState] = useState<ViewState<ManufacturingIngestionRun>>({ state: "loading" });
  const [uploads, setUploads] = useState<IngestedDoc[]>([]);
  const [connectorRuns, setConnectorRuns] = useState<ConnectorRunRecord[]>([]);
  const [lastLookupId, setLastLookupId] = useState("");

  useEffect(() => {
    setUploads(loadIngestedDocs());
    setConnectorRuns(loadConnectorRuns());
  }, []);

  async function loadRun(id: string) {
    const trimmed = id.trim();
    if (!trimmed) return;
    setLastLookupId(trimmed);
    setState({ state: "loading" });
    try {
      const data = await runWithToken((token) => manufacturingIngestionRun(trimmed, token));
      setState({ state: "ready", data });
    } catch (err) {
      if (isAuthError(err)) clearSessionToken();
      setState({ state: "error", error: formatLoadError(err) });
    }
  }

  async function lookup(event: FormEvent) {
    event.preventDefault();
    await loadRun(runId);
  }

  function retryLookup() {
    if (lastLookupId) void loadRun(lastLookupId);
  }

  function connectorStatusLabel(status: string): string {
    if (status === "succeeded") return "成功";
    if (isSyncActive(status)) return "実行中";
    if (status === "failed") return "失敗";
    return status;
  }

  return (
    <>
      <Section title="実行を確認" note="実行 ID でバックエンドの投影を確認できます。">
        <form className="src-inline-form" onSubmit={lookup}>
          <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="ingestion_run_id" aria-label="実行 ID" />
          <button type="submit" disabled={!runId.trim()}>
            確認
          </button>
        </form>
      </Section>
      {connectorRuns.length > 0 && (
        <Section
          title="最近のコネクタ同期（このブラウザ）"
          note="「ソースを追加」から開始した同期です。実行 ID で詳細を確認できます。"
        >
          <DataTable
            columns={["実行 ID", "ソース", "コレクション", "状態", "変更", "日時"]}
            rows={connectorRuns.map((run) => [
              <button
                type="button"
                key={run.ingestion_run_id}
                className="linklike"
                onClick={() => {
                  setRunId(run.ingestion_run_id);
                  void loadRun(run.ingestion_run_id);
                }}
              >
                {run.ingestion_run_id}
              </button>,
              run.source_id,
              run.collection_id,
              connectorStatusLabel(run.status),
              String(run.changed_count),
              new Date(run.synced_at).toLocaleString("ja-JP"),
            ])}
            empty="コネクタ同期はまだありません。"
          />
        </Section>
      )}
      {uploads.length > 0 && (
        <Section title="最近のアップロード取込（このブラウザ）" note="ファイルアップロードから作成された取込ランです。">
          <DataTable
            columns={["実行 ID", "ドキュメント", "状態", "チャンク", "日時"]}
            rows={uploads.map((doc) => [
              <button
                type="button"
                key={doc.ingestion_run_id}
                className="linklike"
                onClick={() => {
                  setRunId(doc.ingestion_run_id);
                  void loadRun(doc.ingestion_run_id);
                }}
              >
                {doc.ingestion_run_id}
              </button>,
              doc.document_id,
              doc.status === "succeeded" ? "成功" : doc.status,
              String(doc.chunk_count),
              new Date(doc.ingested_at).toLocaleString("ja-JP"),
            ])}
            empty="取込はまだありません。"
          />
        </Section>
      )}
      {connectorRuns.length === 0 && uploads.length === 0 && (
        <p className="ops-empty">
          まだ取込履歴はありません。<Link href="/sources/new">ソースを追加</Link> から同期またはアップロードしてください。
        </p>
      )}
      {state.state === "loading" && lastLookupId && <p className="ops-empty" role="status" aria-live="polite">実行状態を読み込み中…</p>}
      {state.state === "error" && <ScreenLoadError error={state.error} onRetry={retryLookup} />}
      {state.state === "ready" && (
        <Section title="実行詳細">
          <FieldGrid
            rows={[
              ["実行 ID", state.data.ingestion_run_id],
              ["状態", state.data.status],
              ["ソース", state.data.source_id ?? "—"],
              ["コレクション", state.data.collection_id ?? "—"],
              ["開始", state.data.started_at ?? "—"],
              ["終了", state.data.finished_at ?? "—"],
            ]}
          />
        </Section>
      )}
    </>
  );
}

function OperationTelemetryBody() {
  const [state, reload] = useLoad(
    async () => {
      const token = await getSessionToken();
      const [telemetry, governance] = await Promise.all([
        manufacturingSafetyTelemetry(token),
        manufacturingGovernanceStatus(token),
      ]);
      return { telemetry, governance };
    },
    [],
  );

  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">安全テレメトリを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const breakdown = state.data.telemetry.block_breakdown ?? state.data.telemetry.safety_gate_block_breakdown ?? {};
  return (
    <>
      <Section title="安全テレメトリ">
        <div className="metric-grid">
          <Stat label="高リスク問い合わせ" value={state.data.telemetry.high_risk_query_count} />
          <Stat label="安全ゲート遮断" value={state.data.telemetry.safety_gate_block_count} />
          <Stat label="テナント" value={state.data.telemetry.tenant_id} />
          <Stat label="ソース" value={state.data.telemetry.source} />
        </div>
      </Section>
      <Section title="ブロック内訳">
        <DataTable
          columns={["理由", "件数"]}
          rows={Object.entries(breakdown).map(([reason, count]) => [reason, count])}
          empty="安全ブロックはまだありません。"
        />
      </Section>
    </>
  );
}

function QualityBody() {
  const [state, reload] = useLoad(
    async () => {
      const token = await getSessionToken();
      const [kpi, governance] = await Promise.all([manufacturingKpi(token), manufacturingGovernanceStatus(token)]);
      return { kpi, governance };
    },
    [],
  );
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">品質データを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const { kpi } = state.data;
  return (
    <>
      <Section title="品質 KPI">
        <div className="metric-grid">
          <Stat label="自己解決率" value={`${(kpi.self_resolution_rate * 100).toFixed(1)}%`} />
          <Stat label="根拠あり回答" value={`${(kpi.grounded_answer_rate * 100).toFixed(1)}%`} />
          <Stat label="根拠不足" value={`${(kpi.insufficient_evidence_rate * 100).toFixed(1)}%`} />
          <Stat label="低評価" value={`${(kpi.low_rating_rate * 100).toFixed(1)}%`} />
        </div>
      </Section>
      <Section title="監査由来サマリー">
        <FieldGrid
          rows={[
            ["回答 p50", kpi.average_time_to_answer.p50],
            ["回答 p95", kpi.average_time_to_answer.p95],
            ["頻出文書", kpi.frequently_referenced_documents.length],
            ["旧版候補", kpi.obsolete_document_candidates.length],
            ["集計時刻", kpi.materialized_at],
          ]}
        />
      </Section>
      <QualityEvalSection />
    </>
  );
}

// AI quality & safety scorecard: runs a fixed eval set against the live answer path and shows
// retrieval recall / groundedness / high-risk recall / security checks. The same measurement as
// scripts/demo/quality_scorecard.sh, surfaced for decision-makers (continuous safety/quality evidence).
const QUALITY_EVAL_ITEMS = [
  { question: "コンベアの M8 カバーボルト 締付トルク は何 N·m か", expected_evidence: [{ document_id: "eq-motor-m8-torque" }] },
  { question: "圧力容器 V-205 耐圧試験 の 試験圧力 と 保持時間 と 昇圧手順", expected_evidence: [{ document_id: "std-2210-hydrotest" }] },
  { question: "受電盤 MCC-3 の 感電 防止 LOTO ロックアウト 検電 手順", expected_evidence: [{ document_id: "safe-0331-loto" }] },
  { question: "ポンプ P-12 の 潤滑 グリス 給脂 間隔", expected_evidence: [{ document_id: "eq-pump-p12-lubrication" }] },
  { question: "コンベヤ ベルト 点検 標準 摩耗 蛇行", expected_evidence: [{ document_id: "eq-belt-inspection-standard" }] },
  { question: "アラーム E-152 油圧 異常 アキュムレータ 確認", expected_evidence: [{ document_id: "eq-alarm-e152-al21" }] },
  { question: "PWHT 溶接後熱処理 の 保持温度 保持時間", expected_evidence: [{ document_id: "wi-0457-pwht" }] },
  { question: "ベアリング 異音 発熱 軌道 摩耗 の 対策", expected_evidence: [{ document_id: "tc-0258" }] },
  { question: "ヒケ ボイド 寸法不良 成形 保圧 の 対策", expected_evidence: [{ document_id: "tc-0231" }] },
];

function pct(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function QualityEvalSection() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QualityEvalResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      const token = await getSessionToken();
      setResult(await runManufacturingQualityEval(QUALITY_EVAL_ITEMS, token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "評価の実行に失敗しました");
    } finally {
      setRunning(false);
    }
  }

  const securityEntries = result ? Object.entries(result.security_checks) : [];
  const securityFailed = securityEntries.filter(
    ([, v]) => !(typeof v === "object" ? v.passed : v),
  );

  return (
    <Section
      title="AI品質・安全評価（eval）"
      note="固定の評価セットを実回答パスに対して実行し、検索再現率・根拠率・高リスク再現・セキュリティ検査を測定します。リリース前の品質確認や継続的な安全性の証跡に使えます。"
    >
      <div className="screen-actions">
        <button type="button" onClick={() => void run()} disabled={running}>
          {running ? "評価を実行中…" : "品質評価を実行"}
        </button>
      </div>
      {error && <p className="cv-foot-error" role="alert">{error}</p>}
      {result && (
        <>
          <div className="metric-grid">
            <Stat label="検索再現率 (recall@k)" value={pct(result.metrics.recall_at_k)} />
            <Stat label="根拠率 (groundedness)" value={pct(result.metrics.groundedness)} />
            <Stat label="高リスク再現" value={pct(result.metrics.high_risk_recall)} />
          </div>
          <FieldGrid
            rows={[
              ["ゲート判定", result.gate_result === "passed" ? "合格" : result.gate_result],
              [
                "セキュリティ検査",
                securityFailed.length === 0
                  ? `全${securityEntries.length}項目パス`
                  : `失敗: ${securityFailed.map(([k]) => k).join(", ")}`,
              ],
            ]}
          />
        </>
      )}
    </Section>
  );
}

function ImpactReportBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    const [dashboard, telemetry, kpi, drafts] = await Promise.all([
      manufacturingDashboard(token),
      manufacturingSafetyTelemetry(token),
      manufacturingKpi(token),
      manufacturingListDrafts(token).catch(() => []),
    ]);
    const reviewDone = drafts.filter((d) => d.status === "approved" || d.status === "rejected").length;
    return { dashboard, telemetry, kpi, draftCount: drafts.length, reviewDone };
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">導入効果レポートを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const { dashboard, telemetry, kpi, draftCount, reviewDone } = state.data;
  const blocks = telemetry.safety_gate_block_breakdown ?? telemetry.block_breakdown ?? {};
  return (
    <>
      <p className="src-warning">
        活用状況サマリーです。現場の自己解決、危険な断定の阻止、不足文書の可視化を重視しています。
      </p>
      <Section title="現場インパクト">
        <div className="metric-grid">
          <Stat label="自己解決率" value={`${(kpi.self_resolution_rate * 100).toFixed(0)}%`} />
          <Stat label="根拠付き回答率" value={`${(kpi.grounded_answer_rate * 100).toFixed(0)}%`} />
          <Stat label="根拠不足率" value={`${(kpi.insufficient_evidence_rate * 100).toFixed(0)}%`} />
          <Stat label="低評価率" value={`${(kpi.low_rating_rate * 100).toFixed(0)}%`} />
        </div>
      </Section>
      <Section title="安全・品質">
        <FieldGrid
          rows={[
            ["高リスク質問数", telemetry.high_risk_query_count],
            ["安全ゲート block", telemetry.safety_gate_block_count],
            ["未回答質問", dashboard.unanswered_question_count],
            ["ドラフト生成数", draftCount],
            ["レビュー完了数", reviewDone],
            ["よく参照された文書", kpi.frequently_referenced_documents.slice(0, 5).join(", ") || "—"],
            ["旧版候補", kpi.obsolete_document_candidates.slice(0, 5).join(", ") || "—"],
          ]}
        />
      </Section>
      {Object.keys(blocks).length > 0 && (
        <Section title="ゲート block 内訳">
          <FieldGrid rows={Object.entries(blocks).map(([k, v]) => [k, String(v)])} />
        </Section>
      )}
    </>
  );
}

function ImprovementQueueBody() {
  const [items, setItems] = useState<ImprovementItem[]>([]);
  const [serverItems, setServerItems] = useState<
    Array<{ id: string; kind: string; answer_id: string | null; reason: string | null; created_at: string }>
  >([]);

  useEffect(() => {
    setItems(loadImprovementItems());
    void (async () => {
      try {
        const token = await getSessionToken();
        const res = await manufacturingImprovements(token);
        setServerItems(
          res.items.map((i) => ({
            id: i.id,
            kind: i.kind,
            answer_id: i.answer_id,
            reason: i.reason,
            created_at: i.created_at,
          })),
        );
      } catch {
        setServerItems([]);
      }
    })();
  }, []);

  function resolve(id: string) {
    setImprovementStatus(id, "resolved");
    setItems(loadImprovementItems());
  }
  function reopen(id: string) {
    setImprovementStatus(id, "open");
    setItems(loadImprovementItems());
  }
  function clearAll() {
    clearImprovementItems();
    setItems([]);
  }

  const open = items.filter((i) => i.status === "open");

  const kindLabel: Record<string, string> = {
    low_rating: "低評価",
    unanswered: "未回答",
    insufficient_evidence: "根拠不足",
    safety_block: "安全ブロック",
    obsolete_only: "旧版のみヒット",
  };

  return (
    <>
      <p className="src-warning">
        監査ログ由来の改善候補と、ブラウザ内フィードバックを合わせて表示します。
      </p>
      {serverItems.length > 0 && (
        <Section title="監査由来の改善候補" note={`${serverItems.length} 件`}>
          <div className="improve-list">
            {serverItems.map((item) => (
              <article className="improve-row" key={item.id}>
                <div className="improve-row-titles">
                  <span className="citation-chip approval-obsolete">{kindLabel[item.kind] ?? item.kind}</span>
                  <strong>{item.answer_id ?? item.id}</strong>
                  <span>
                    {item.reason ?? "—"} · {new Date(item.created_at).toLocaleString("ja-JP")}
                  </span>
                </div>
                <div className="improve-row-actions">
                  <Link className="button-link secondary" href="/sources/new">
                    文書を追加
                  </Link>
                  <Link className="button-link secondary" href="/admin/retrieval/debug">
                    再評価
                  </Link>
                </div>
              </article>
            ))}
          </div>
        </Section>
      )}
      <Section
        title="改善キュー"
        note={`未対応 ${open.length} 件 / 全 ${items.length} 件（このブラウザのフィードバック）。`}
      >
        {items.length === 0 ? (
          <p className="ops-empty">
            まだ改善項目はありません。<Link href="/">質問する</Link> で回答に「👎 要改善」を付けると、ここに集約されます。
          </p>
        ) : (
          <div className="improve-list">
            {items.map((item) => (
              <article className={`improve-row ${item.status === "resolved" ? "is-resolved" : ""}`} key={item.id}>
                <div className="improve-row-titles">
                  <span
                    className={`citation-chip ${item.status === "resolved" ? "approval-approved" : "approval-obsolete"}`}
                  >
                    {item.status === "resolved" ? "対応済み" : "未対応"}
                  </span>
                  <strong>{item.question}</strong>
                  <span>
                    理由: {reasonLabel(item.reason)} · {new Date(item.created_at).toLocaleString("ja-JP")}
                  </span>
                </div>
                <div className="improve-row-actions">
                  <Link className="button-link secondary" href="/sources/new">
                    文書を追加
                  </Link>
                  <Link className="button-link secondary" href="/operations/quality">
                    品質 KPI
                  </Link>
                  {item.status === "open" ? (
                    <button type="button" className="btn-approve" onClick={() => resolve(item.id)}>
                      対応済みにする
                    </button>
                  ) : (
                    <button type="button" onClick={() => reopen(item.id)}>
                      未対応に戻す
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
        {items.length > 0 && (
          <div className="screen-actions">
            <button type="button" className="btn-reject" onClick={clearAll}>
              この一覧を消去
            </button>
          </div>
        )}
      </Section>
    </>
  );
}

function ComplianceExportBody() {
  const [state, reload] = useLoad(
    async () => {
      const token = await getSessionToken();
      const [exportPayload, governance, policy] = await Promise.all([
        manufacturingAuditExport(token, "dict"),
        manufacturingGovernanceStatus(token),
        manufacturingDataUsePolicy(token),
      ]);
      return { exportPayload, governance, policy };
    },
    [],
  );
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">出力データを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return (
      <Section title="コンプライアンス出力">
        <pre className="code-block">{JSON.stringify(state.data.exportPayload, null, 2)}</pre>
      </Section>
  );
}

function GenericMockBody({ screen }: { screen: ManifestScreen }) {
  return (
    <>
      <MockBanner screen={screen} />
      <Section title="表示項目">
        <FieldGrid rows={screen.data.map((item, index) => [`data[${index}]`, String(item)])} />
      </Section>
      <Section title="連携状況">
        <DataTable
          columns={["メソッド", "パス", "状態"]}
          rows={missingApis(screen).map((api) => [api.method, api.path, api.status])}
          empty="追加の連携情報はありません。"
        />
      </Section>
    </>
  );
}

export default function FullSaasScreen({ pathname, screen }: { pathname: string; screen: ManifestScreen }) {
  return (
    <ScreenShell screen={screen}>
      {screen.id === "answers" && <AnswersBody />}
      {screen.id === "home-dashboard" && <HomeDashboardBody />}
      {screen.id === "answer-history" && <AnswerHistoryBody />}
      {screen.id === "source-search" && <SourceSearchBody />}
      {screen.id === "source-list" && <SourceListBody />}
      {screen.id === "source-detail" && <SourceDetailBody sourceId={pathname.split("/").at(-1) ?? ""} />}
      {screen.id === "ingestion-runs" && <IngestionRunsBody />}
      {screen.id === "document-list" && <DocumentListBody />}
      {screen.id === "document-detail" && (
        <DocumentDetailBody documentId={pathname.split("/").at(-1) ?? ""} />
      )}
      {screen.id === "review-queue" && <ReviewQueueBody />}
      {screen.id === "document-approval-queue" && <DocumentApprovalQueueBody />}
      {screen.id === "review-detail" && <ReviewDetailBody artifactId={pathname.split("/").at(-1) ?? ""} />}
      {screen.id === "approval-workflow-settings" && <ApprovalWorkflowBody />}
      {screen.id === "operations-dashboard" && <GenericOpsOverview />}
      {screen.id === "safety-telemetry" && <OperationTelemetryBody />}
      {screen.id === "quality-kpi" && <QualityBody />}
      {screen.id === "impact-report" && <ImpactReportBody />}
      {screen.id === "knowledge-improvement-queue" && <ImprovementQueueBody />}
      {screen.id === "audit-log" && <AuditLogBody />}
      {screen.id === "compliance-export" && <ComplianceExportBody />}
      {screen.id === "users" && <MockAdminScreen title="ユーザー" rows={MOCK_USERS} />}
      {screen.id === "roles-groups-acl" && <RolesAclBody />}
      {screen.id === "provider-policy" && <ProviderPolicyBody />}
      {screen.id === "retrieval-settings" && <RetrievalBody />}
      {screen.id === "retrieval-debug" && <RetrievalDebugBody />}
      {screen.id === "logging-privacy" && <LoggingPrivacyBody />}
      {screen.id === "integrations" && <MockAdminScreen title="連携" rows={MOCK_SOURCES} />}
      {screen.id === "api-keys-webhooks" && <ApiKeysBody />}
      {screen.id === "usage-billing" && <BillingBody />}
      {screen.id === "support" && <SupportBody />}
      {screen.id === "add-source" && <AddSourceBody />}
    </ScreenShell>
  );
}

const APPROVAL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "approved", label: "承認済み（すぐ正式根拠に使える）" },
  { value: "pending_review", label: "承認待ち" },
  { value: "draft", label: "ドラフト（参照のみ）" },
  { value: "obsolete", label: "旧版（参照のみ・警告）" },
];

const ACCEPT_EXT = ".txt,.md,.markdown,.csv,.html,.htm,.docx,.xlsx,.pdf,.png,.jpg,.jpeg";

type AddSourceTypeId =
  | "file"
  | "url"
  | "googledrive"
  | "sharepoint"
  | "onedrive"
  | "box"
  | "confluence"
  | "notion"
  | "slack"
  | "kintone"
  | "garoon"
  | "s3"
  | "db";

type AddSourceField = {
  id: string;
  label: string;
  placeholder: string;
  type?: "text" | "password";
};

type AddSourceType = {
  id: AddSourceTypeId;
  name: string;
  desc: string;
  mono: string;
  readiness: "ready" | "three_days" | "later";
};

type AddSourceConfig = {
  upload?: boolean;
  oauth?: string;
  fields: AddSourceField[];
  dataSourceType:
    | "upload"
    | "object_storage"
    | "slack"
    | "confluence"
    | "database"
    | "notion"
    | "box"
    | "google_drive";
  note: string;
};

const ADD_SOURCE_TYPES: AddSourceType[] = [
  {
    id: "file",
    name: "ファイルアップロード",
    desc: "PDF・Word・Excel・CAD などを直接アップロード",
    mono: "UP",
    readiness: "ready",
  },
  {
    id: "url",
    name: "URL / Web",
    desc: "公開ページや社内 Wiki をクロール",
    mono: "URL",
    readiness: "ready",
  },
  {
    id: "googledrive",
    name: "Google Drive",
    desc: "共有ドライブ・フォルダの文書を同期",
    mono: "GD",
    readiness: "three_days",
  },
  {
    id: "sharepoint",
    name: "SharePoint",
    desc: "ドキュメントライブラリを接続",
    mono: "SP",
    readiness: "three_days",
  },
  {
    id: "onedrive",
    name: "OneDrive",
    desc: "個人・部門のファイルを同期",
    mono: "OD",
    readiness: "three_days",
  },
  {
    id: "box",
    name: "Box",
    desc: "フォルダ単位で文書を取込",
    mono: "BOX",
    readiness: "ready",
  },
  {
    id: "confluence",
    name: "Confluence",
    desc: "スペース・ページを同期",
    mono: "CF",
    readiness: "ready",
  },
  {
    id: "notion",
    name: "Notion",
    desc: "手順・ナレッジページを同期",
    mono: "NO",
    readiness: "ready",
  },
  {
    id: "slack",
    name: "Slack",
    desc: "チャンネルの Q&A を取込",
    mono: "SL",
    readiness: "later",
  },
  {
    id: "kintone",
    name: "kintone",
    desc: "サイボウズ kintone アプリを連携",
    mono: "KT",
    readiness: "ready",
  },
  {
    id: "garoon",
    name: "Garoon",
    desc: "サイボウズ Garoon の文書・掲示板",
    mono: "GR",
    readiness: "three_days",
  },
  {
    id: "s3",
    name: "Amazon S3",
    desc: "バケットから図面・文書を同期",
    mono: "S3",
    readiness: "ready",
  },
  {
    id: "db",
    name: "データベース",
    desc: "PostgreSQL / MySQL のレコードを取込",
    mono: "DB",
    readiness: "ready",
  },
];

const ADD_SOURCE_CONFIGS: Record<AddSourceTypeId, AddSourceConfig> = {
  file: {
    upload: true,
    fields: [],
    dataSourceType: "upload",
    note: "既存のアップロード API でそのまま取込できます。",
  },
  url: {
    fields: [
      { id: "target_url", label: "クロール対象 URL", placeholder: "https://intranet.example/manuals" },
      { id: "crawl_depth", label: "クロール深度", placeholder: "例: 2" },
      { id: "sync_schedule", label: "更新スケジュール", placeholder: "例: 毎日 03:00" },
    ],
    dataSourceType: "object_storage",
    note: "URL・深度・スケジュールを保存し、同一ホスト内（公開アドレスのみ）をクロールして取込します。",
  },
  googledrive: {
    oauth: "Google",
    fields: [
      { id: "folder_id", label: "対象フォルダ / 共有ドライブ", placeholder: "フォルダ URL または ID（未指定はマイドライブ直下）" },
    ],
    dataSourceType: "google_drive",
    note: "「Google で接続」で OAuth 認可（drive.readonly）を行うと、リフレッシュトークンをサーバ側のシークレットストアに保管し、同期時に短命アクセストークンを自動発行します。ネイティブ Google ドキュメントはエクスポート取込します。",
  },
  sharepoint: {
    oauth: "Microsoft",
    fields: [
      { id: "site_url", label: "サイト URL", placeholder: "https://tenant.sharepoint.com/sites/quality" },
      { id: "document_library", label: "ドキュメントライブラリ", placeholder: "Documents" },
    ],
    dataSourceType: "object_storage",
    note: "サイトとライブラリ単位の設定UIです。Microsoft OAuth 接続はバックエンド連携が必要です。",
  },
  onedrive: {
    oauth: "Microsoft",
    fields: [{ id: "target_folder", label: "対象サイト / フォルダ", placeholder: "OneDrive フォルダ URL または ID" }],
    dataSourceType: "object_storage",
    note: "OneDrive の対象フォルダを保存できます。認証と差分同期はバックエンド側で接続します。",
  },
  box: {
    fields: [
      { id: "folder_id", label: "対象フォルダ ID", placeholder: "0（ルート）または フォルダ ID" },
      { id: "access_token", label: "アクセストークン", placeholder: "Box access token", type: "password" },
    ],
    dataSourceType: "box",
    note: "アクセストークン（Bearer）方式でフォルダ内の文書を取込します。対応形式（txt/md/csv/html/docx/xlsx）のみ同期します。",
  },
  confluence: {
    fields: [
      { id: "site_url", label: "サイト URL", placeholder: "https://example.atlassian.net/wiki" },
      { id: "space_key", label: "対象スペース", placeholder: "MFG" },
      { id: "email", label: "メールアドレス", placeholder: "bot@example.com" },
      { id: "api_token", label: "API トークン", placeholder: "Atlassian API token", type: "password" },
    ],
    dataSourceType: "confluence",
    note: "API トークン方式（メール + トークンの Basic 認証）で対象スペースのページを取込します。",
  },
  notion: {
    fields: [
      { id: "database_id", label: "対象データベース ID", placeholder: "Notion database ID" },
      { id: "integration_token", label: "インテグレーショントークン", placeholder: "secret_xxx", type: "password" },
    ],
    dataSourceType: "notion",
    note: "インテグレーショントークン方式でデータベース内のページをブロック展開し、Markdown 化して取込します。",
  },
  slack: {
    oauth: "Slack",
    fields: [{ id: "target_channel", label: "対象チャンネル", placeholder: "#quality-q-and-a" }],
    dataSourceType: "slack",
    note: "Slack はメッセージ履歴、権限、削除反映の扱いが重く、3日対応候補からは外しています。",
  },
  kintone: {
    fields: [
      { id: "subdomain", label: "サブドメイン", placeholder: "example.cybozu.com" },
      { id: "api_token", label: "API トークン", placeholder: "API token", type: "password" },
      { id: "app_id", label: "対象アプリ", placeholder: "123" },
    ],
    dataSourceType: "object_storage",
    note: "API トークン方式で kintone アプリのレコードを取込します（cybozu.com / kintone.com のみ許可）。",
  },
  garoon: {
    fields: [
      { id: "site_url", label: "サイト URL", placeholder: "https://example.cybozu.com/g/" },
      { id: "login_name", label: "ログイン名", placeholder: "bot@example.com" },
      { id: "password", label: "パスワード", placeholder: "password", type: "password" },
      { id: "target_space", label: "対象スペース", placeholder: "掲示板 / スペース名" },
    ],
    dataSourceType: "object_storage",
    note: "Garoon の接続項目を入力できます。資格情報の保管先と同期処理はバックエンド実装が必要です。",
  },
  s3: {
    fields: [
      { id: "bucket", label: "バケット名", placeholder: "raku-rag-documents" },
      { id: "region", label: "リージョン", placeholder: "ap-northeast-1" },
      { id: "access_key_id", label: "アクセスキー ID", placeholder: "AKIA..." },
      { id: "secret_access_key", label: "シークレットアクセスキー", placeholder: "secret", type: "password" },
      { id: "prefix", label: "プレフィックス（任意）", placeholder: "manuals/" },
      { id: "endpoint_url", label: "エンドポイント（任意・MinIO等）", placeholder: "https://minio.example.com" },
      { id: "allow_private_host", label: "内部エンドポイントを許可（任意）", placeholder: "社内 MinIO は true" },
    ],
    dataSourceType: "object_storage",
    note: "S3 はバケット・リージョン・プレフィックスを保存して同期します。独自エンドポイント利用時はアクセスキーが必須で、社内エンドポイントは内部ホスト許可を true にしてください。",
  },
  db: {
    fields: [
      { id: "db_engine", label: "エンジン", placeholder: "postgres または mysql" },
      { id: "connection_string", label: "接続文字列", placeholder: "postgresql://… または mysql://user:pass@host:3306/db", type: "password" }, // pragma: allowlist secret -- UI placeholder example, not a real credential
      { id: "table_name", label: "対象テーブル", placeholder: "public.maintenance_cases" },
      { id: "updated_column", label: "更新検知列（任意）", placeholder: "updated_at" },
      { id: "allow_private_host", label: "内部ホストを許可（任意）", placeholder: "社内DBに接続する場合は true" },
    ],
    dataSourceType: "database",
    note: "PostgreSQL / MySQL の接続文字列と対象テーブルを保存して同期します。エンジンは接続文字列から自動判定（未指定時）。社内ネットワークの DB に接続する場合は内部ホスト許可を true にしてください。",
  },
};

function sourceReadinessLabel(readiness: AddSourceType["readiness"]): string {
  if (readiness === "ready") return "利用可";
  if (readiness === "three_days") return "3日候補";
  return "要追加設計";
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

interface UploadForIngestResult {
  ref: string;
  filename: string;
  content_type: string;
  size?: number;
  storage?: string;
}

async function fallbackInlineUpload(file: File): Promise<UploadForIngestResult> {
  const form = new FormData();
  form.append("file", file);
  const upRes = await fetch("/api/upload", { method: "POST", body: form });
  const up = await upRes.json().catch(() => ({}));
  if (!upRes.ok) throw new Error(up.error ?? "アップロードに失敗しました");
  return up as UploadForIngestResult;
}

async function uploadForIngest(file: File, token: string): Promise<UploadForIngestResult> {
  const presignRes = await fetch("/api/upload/presign", {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      filename: file.name || "upload.bin",
      size: file.size,
      content_type: file.type || "application/octet-stream",
    }),
  });
  const presign = await presignRes.json().catch(() => ({}));

  if (presignRes.ok && typeof presign.upload_url === "string" && typeof presign.ref === "string") {
    const contentType =
      typeof presign.content_type === "string"
        ? presign.content_type
        : file.type || "application/octet-stream";
    const uploadRes = await fetch(presign.upload_url, {
      method: "PUT",
      headers: { "content-type": contentType },
      body: file,
    });
    if (!uploadRes.ok) throw new Error(`S3 アップロードに失敗しました (HTTP ${uploadRes.status})`);
    return {
      ref: presign.ref,
      filename: typeof presign.filename === "string" ? presign.filename : file.name || "upload.bin",
      content_type: contentType,
      size: typeof presign.size === "number" ? presign.size : file.size,
      storage: "s3",
    };
  }

  if (presignRes.status === 403 || presignRes.status === 501) {
    return fallbackInlineUpload(file);
  }

  throw new Error(
    typeof presign.error === "string" ? presign.error : "アップロード URL の発行に失敗しました",
  );
}

const GDRIVE_OAUTH_STATE_KEY = "raku.gdrive.oauth.state";
const GDRIVE_OAUTH_MESSAGE_SOURCE = "raku-gdrive-oauth";

function makeOAuthNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes); // CSPRNG, not Math.random — this nonce is the CSRF guard
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function AddSourceBody() {
  const [selectedSource, setSelectedSource] = useState<AddSourceTypeId>("file");
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [collectionId, setCollectionId] = useState("manuals");
  const [sourceId, setSourceId] = useState("upload");
  const [approvalStatus, setApprovalStatus] = useState("approved");
  const [effectiveDate, setEffectiveDate] = useState(todayIso());
  // Connector (multi-file) trust policy. Default review_required so synced files land in the review
  // queue (pending_review) — never auto-approved. 'trusted' inherits approval from the source of
  // truth (approval_source=imported) so a governed source approves all its files at sync time.
  const [approvalPolicy, setApprovalPolicy] = useState<"review_required" | "trusted">(
    "review_required",
  );
  const [mappingProfileType, setMappingProfileType] = useState<DataSourceProfileType>("auto");
  const [mappingRequiredFields, setMappingRequiredFields] = useState(
    PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestedDoc | null>(null);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [configSaving, setConfigSaving] = useState(false);
  const [configMessage, setConfigMessage] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<AdminSourceSyncResponse | null>(null);
  // Google Drive OAuth connection (021-gdrive). connectionId is the only credential the form keeps;
  // the refresh token lives server-side. saveDatasource gates on it for google_drive.
  const [oauthStatus, setOauthStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [oauthConnectionId, setOauthConnectionId] = useState<string>("");
  const [oauthError, setOauthError] = useState<string | null>(null);

  const selectedSourceDef = ADD_SOURCE_TYPES.find((source) => source.id === selectedSource) ?? ADD_SOURCE_TYPES[0];
  const selectedConfig = ADD_SOURCE_CONFIGS[selectedSource];
  const needsOAuthConnection = selectedConfig.dataSourceType === "google_drive";

  // Receive the connection result from the OAuth popup (apps/web/app/oauth/google/callback).
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== GDRIVE_OAUTH_MESSAGE_SOURCE) return;
      if (data.ok && typeof data.connection_id === "string") {
        setOauthConnectionId(data.connection_id);
        setOauthStatus("connected");
        setOauthError(null);
      } else {
        setOauthStatus("error");
        setOauthError(typeof data.error === "string" ? data.error : "接続に失敗しました");
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  async function onConnectGoogle() {
    setOauthError(null);
    setOauthStatus("connecting");
    try {
      const nonce = makeOAuthNonce();
      window.sessionStorage.setItem(GDRIVE_OAUTH_STATE_KEY, nonce);
      const redirectUri = `${window.location.origin}/oauth/google/callback`;
      const token = await getSessionToken();
      const { authorization_url } = await apiGetJson<{ authorization_url: string }>(
        `/oauth/google/authorize?state=${encodeURIComponent(nonce)}&redirect_uri=${encodeURIComponent(redirectUri)}`,
        token,
      );
      const popup = window.open(authorization_url, "raku-gdrive-oauth", "width=520,height=640");
      if (!popup) {
        // Popups blocked: fall back to a full-page redirect (callback stashes the id in sessionStorage).
        window.location.href = authorization_url;
      }
    } catch (err) {
      setOauthStatus("error");
      setOauthError(err instanceof Error ? err.message : "OAuth 接続の開始に失敗しました");
    }
  }

  function onSelectSource(sourceIdValue: AddSourceTypeId) {
    setSelectedSource(sourceIdValue);
    setSourceId(sourceIdValue === "file" ? "upload" : sourceIdValue);
    setConfigValues({});
    setConfigMessage(null);
    setError(null);
    setResult(null);
    setSyncResult(null);
    setOauthStatus("idle");
    setOauthConnectionId("");
    setOauthError(null);
    setMappingProfileType("auto");
    setMappingRequiredFields(PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "));
  }

  function onMappingProfileTypeChange(value: DataSourceProfileType) {
    setMappingProfileType(value);
    setMappingRequiredFields(PREVIEW_REQUIRED_FIELDS_BY_PROFILE[value].join(", "));
  }

  function onConfigChange(fieldId: string, value: string) {
    setConfigValues((current) => ({ ...current, [fieldId]: value }));
  }

  function onPickFile(picked: File | null) {
    setFile(picked);
    if (picked && !documentId.trim()) {
      setDocumentId(picked.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 80));
    }
  }

  async function saveDatasource(): Promise<string | null> {
    if (selectedSource === "file" || configSaving || syncing) return null;
    if (needsOAuthConnection && !oauthConnectionId) {
      setError("先に「Google で接続」で OAuth 認可を完了してください。");
      return null;
    }
    setError(null);
    setConfigMessage(null);
    setSyncResult(null);
    setConfigSaving(true);
    try {
      const datasourceId = sourceId.trim() || selectedSource;
      const token = await getSessionToken();
      const credentialFieldIds = new Set(
        selectedConfig.fields.filter((field) => field.type === "password").map((field) => field.id),
      );
      const credentials = Object.fromEntries(
        Object.entries(configValues).filter(([key, value]) => credentialFieldIds.has(key) && value),
      );
      const safeConfigValues = Object.fromEntries(
        Object.entries(configValues).filter(([key]) => !credentialFieldIds.has(key)),
      );
      const mappingDefaults: Record<string, unknown> = {
        approval_status: approvalPolicy === "trusted" ? "approved" : "pending_review",
      };
      if (approvalPolicy === "trusted" && effectiveDate) {
        mappingDefaults.effective_date = effectiveDate;
      }
      await apiPutJson(
        `/admin/datasources/${encodeURIComponent(datasourceId)}`,
        {
          collection_id: collectionId.trim() || "manuals",
          type: selectedConfig.dataSourceType,
          config: {
            // Backend dispatch key. It matches the AddSourceTypeId for every connector EXCEPT
            // google_drive (UI id 'googledrive' -> dispatch/type 'google_drive').
            source_type: selectedSource === "googledrive" ? "google_drive" : selectedSource,
            display_name: selectedSourceDef.name,
            oauth_provider: selectedConfig.oauth ?? null,
            // OAuth connection id (google_drive): sync resolves the refresh token by this id. The
            // refresh token itself is never in the config — it lives in the server SecretStore.
            ...(needsOAuthConnection ? { connection_id: oauthConnectionId } : {}),
            // Trust policy (server derives every synced file's approval state from this, not from the
            // sync request): 'trusted' => approved+imported; 'review_required' => pending_review.
            approval_policy: approvalPolicy,
            approval_effective_date: approvalPolicy === "trusted" ? effectiveDate || todayIso() : null,
            ...safeConfigValues,
            mapping_profile: {
              profile_type: mappingProfileType,
              defaults: mappingDefaults,
              required_fields: splitPreviewFields(mappingRequiredFields),
            },
          },
          credentials,
          sync_schedule: configValues.sync_schedule || null,
          status: "active",
          reason: "configured_from_add_source_screen",
        },
        token,
      );
      setConfigMessage(`${selectedSourceDef.name} の接続設定を保存しました。`);
      return datasourceId;
    } catch (err) {
      setError(err instanceof Error ? err.message : "接続設定の保存に失敗しました");
      return null;
    } finally {
      setConfigSaving(false);
    }
  }

  async function onSaveDatasource(event: FormEvent) {
    event.preventDefault();
    await saveDatasource();
  }

  async function onSaveAndSync() {
    if (syncing || configSaving) return;
    const datasourceId = await saveDatasource();
    if (!datasourceId) return;
    setSyncing(true);
    setError(null);
    try {
      const token = await getSessionToken();
      // No approval block here: the server derives every synced file's approval state from the saved
      // datasource trust policy (config.approval_policy), so the sync request can never self-grant
      // 'approved'. review_required => files land in pending_review for the review queue.
      const sync = await adminSourceSync(
        datasourceId,
        {
          collection_id: collectionId.trim() || "manuals",
          limit: 25,
        },
        token,
      );
      setSyncResult(sync);
      recordConnectorRun({
        ingestion_run_id: sync.ingestion_run_id,
        source_id: sync.source_id,
        collection_id: sync.collection_id,
        status: sync.status,
        observed_count: sync.observed_count,
        changed_count: sync.changed_count,
        failed_count: sync.failed_count,
        synced_at: new Date().toISOString(),
      });
      const policyNote =
        approvalPolicy === "trusted"
          ? `${sync.changed_count ?? 0} 件を「承認済み（信頼ソース）」として取り込みました。`
          : `${sync.changed_count ?? 0} 件を「承認待ち（pending_review）」として取り込みました。根拠文書レビューで承認すると正式な根拠になります。`;
      setConfigMessage(`${selectedSourceDef.name} の同期を開始しました。${policyNote}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "同期開始に失敗しました");
    } finally {
      setSyncing(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setResult(null);
    setConfigMessage(null);

    if (selectedSource !== "file") {
      setError("このソース種別は接続設定フォームから保存してください。");
      return;
    }

    let payload: File | null = file;
    if (mode === "text") {
      const trimmed = text.trim();
      if (!trimmed) {
        setError("テキストを入力してください。");
        return;
      }
      payload = new File([trimmed], `${documentId.trim() || "pasted"}.txt`, { type: "text/plain" });
    }
    if (!payload) {
      setError("ファイルを選択してください。");
      return;
    }

    setSubmitting(true);
    try {
      const token = await getSessionToken();
      const up = await uploadForIngest(payload, token);

      const docId =
        documentId.trim() ||
        up.filename.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 80) ||
        `doc-${Date.now().toString(36)}`;

      const ingest = await ingestDocument(
        {
          collection_id: collectionId.trim() || "manuals",
          source_id: sourceId.trim() || "upload",
          document_id: docId,
          ref: up.ref,
          content_type: up.content_type,
          manufacturing: {
            approval_status: approvalStatus as "approved" | "pending_review" | "draft" | "obsolete",
            effective_date: effectiveDate || null,
            approval_source: "workflow",
          },
        },
        token,
      );

      const record: IngestedDoc = {
        document_id: ingest.document_id ?? docId,
        collection_id: collectionId.trim() || "manuals",
        source_id: sourceId.trim() || "upload",
        filename: up.filename,
        content_type: up.content_type,
        approval_status: approvalStatus,
        effective_date: effectiveDate || null,
        ingestion_run_id: ingest.ingestion_run_id,
        status: ingest.status,
        chunk_count: ingest.chunk_count ?? 0,
        ingested_at: new Date().toISOString(),
      };
      recordIngestedDoc(record);
      setResult(record);
      if (ingest.failure_reason) {
        setError(`取込は完了しましたが警告があります: ${ingest.failure_reason}`);
      }
      // reset content inputs but keep settings for the next upload
      setFile(null);
      setText("");
      setDocumentId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "取込に失敗しました");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <Section title="データソース種別" note="取り込むデータソースの種別を選択してください。">
        <div className="source-type-grid">
          {ADD_SOURCE_TYPES.filter((source) => source.readiness === "ready").map((source) => (
            <button
              key={source.id}
              type="button"
              className={`source-type-card ${selectedSource === source.id ? "active" : ""}`}
              aria-pressed={selectedSource === source.id}
              onClick={() => onSelectSource(source.id)}
            >
              <span className="source-type-mark">{source.mono}</span>
              <span className="source-type-body">
                <strong>{source.name}</strong>
                <span>{source.desc}</span>
              </span>
              <span className={`source-type-status ${source.readiness}`}>
                {sourceReadinessLabel(source.readiness)}
              </span>
            </button>
          ))}
        </div>
        <p className="source-config-note">{selectedConfig.note}</p>
      </Section>

      {selectedSource === "file" ? (
        <form className="upload-form" onSubmit={onSubmit}>
        <Section title="ドキュメントを追加" note="対応形式: テキスト / Markdown / HTML / CSV / Word(.docx) / Excel(.xlsx) / PDF / 画像">
          <div className="upload-mode-tabs">
            <button
              type="button"
              aria-pressed={mode === "file"}
              className={`upload-mode-tab ${mode === "file" ? "active" : ""}`}
              onClick={() => setMode("file")}
            >
              ファイル
            </button>
            <button
              type="button"
              aria-pressed={mode === "text"}
              className={`upload-mode-tab ${mode === "text" ? "active" : ""}`}
              onClick={() => setMode("text")}
            >
              テキストを貼り付け
            </button>
          </div>

          {mode === "file" ? (
            <label className="upload-drop">
              <input
                type="file"
                accept={ACCEPT_EXT}
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null)}
              />
              <span className="upload-drop-main">{file ? file.name : "ファイルを選択（または、ここにドロップ）"}</span>
              <span className="upload-drop-sub">
                {file
                  ? `${(file.size / 1024).toFixed(1)} KB`
                  : ".txt / .md / .csv / .html / .docx / .xlsx / .pdf / .png / .jpg・最大25MB"}
              </span>
            </label>
          ) : (
            <textarea
              className="upload-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="ここに手順・規格・トラブル対応の本文を貼り付け…"
              rows={6}
            />
          )}

          <div className="upload-fields">
            <label>
              <span>ドキュメント ID</span>
              <input
                value={documentId}
                onChange={(e) => setDocumentId(e.target.value)}
                placeholder="例: WI-0457（空ならファイル名から生成）"
              />
            </label>
            <label>
              <span>コレクション</span>
              <input value={collectionId} onChange={(e) => setCollectionId(e.target.value)} />
            </label>
            <label>
              <span>ソース</span>
              <input value={sourceId} onChange={(e) => setSourceId(e.target.value)} />
            </label>
            <label>
              <span>承認状態</span>
              <select value={approvalStatus} onChange={(e) => setApprovalStatus(e.target.value)}>
                {APPROVAL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>発効日</span>
              <input type="date" value={effectiveDate} onChange={(e) => setEffectiveDate(e.target.value)} />
            </label>
          </div>

          <div className="screen-actions">
            <button type="submit" disabled={submitting}>
              {submitting ? "取込中…" : "アップロードして取込"}
            </button>
          </div>
        </Section>
        </form>
      ) : (
        <form className="connector-form" onSubmit={onSaveDatasource}>
          <Section title={`${selectedSourceDef.name} の接続設定`} note={selectedSourceDef.desc}>
            {selectedConfig.oauth && needsOAuthConnection && (
              <div className="connector-oauth">
                <div>
                  <strong>{selectedConfig.oauth} OAuth</strong>
                  <span>
                    {oauthStatus === "connected"
                      ? `接続済み（connection: ${oauthConnectionId.slice(0, 8)}…）。設定を保存して同期できます。`
                      : "「Google で接続」で drive.readonly を認可します。リフレッシュトークンはサーバ側に保管されます。"}
                  </span>
                  {oauthStatus === "error" && oauthError && (
                    <span className="connector-oauth-error" style={{ color: "#c0392b" }} role="alert">
                      接続エラー: {oauthError}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onConnectGoogle}
                  disabled={oauthStatus === "connecting"}
                >
                  {oauthStatus === "connecting"
                    ? "接続中…"
                    : oauthStatus === "connected"
                      ? "再接続"
                      : `${selectedConfig.oauth} で接続`}
                </button>
              </div>
            )}
            {selectedConfig.oauth && !needsOAuthConnection && (
              <div className="connector-oauth">
                <div>
                  <strong>{selectedConfig.oauth} OAuth</strong>
                  <span>認可フローを接続すると、この設定から自動同期を開始できます。</span>
                </div>
                <button type="button" disabled>
                  OAuth 接続待ち
                </button>
              </div>
            )}

            <div className="connector-form-grid">
              <label>
                <span>コレクション</span>
                <input value={collectionId} onChange={(e) => setCollectionId(e.target.value)} />
              </label>
              <label>
                <span>ソース ID</span>
                <input value={sourceId} onChange={(e) => setSourceId(e.target.value)} />
              </label>
              <label>
                <span>信頼ポリシー</span>
                <select
                  value={approvalPolicy}
                  onChange={(e) => setApprovalPolicy(e.target.value as "review_required" | "trusted")}
                >
                  <option value="review_required">レビューが必要（pending_review で取込）</option>
                  <option value="trusted">信頼する（承認済みとして取込）</option>
                </select>
              </label>
              {approvalPolicy === "trusted" && (
                <label>
                  <span>発効日（信頼ソース）</span>
                  <input
                    type="date"
                    value={effectiveDate}
                    onChange={(e) => setEffectiveDate(e.target.value)}
                  />
                </label>
              )}
              {selectedConfig.fields.map((field) => (
                <label key={field.id}>
                  <span>{field.label}</span>
                  <input
                    type={field.type ?? "text"}
                    value={configValues[field.id] ?? ""}
                    onChange={(e) => onConfigChange(field.id, e.target.value)}
                    placeholder={field.placeholder}
                  />
                </label>
              ))}
            </div>

            <div className="connector-mapping-panel">
              <div className="connector-mapping-head">
                <strong>データ解釈</strong>
                <span>FAQ、マニュアル、設備データなどの列名差分を標準項目に寄せる設定です。</span>
              </div>
              <div className="connector-form-grid">
                <label>
                  <span>データ種別</span>
                  <select
                    value={mappingProfileType}
                    onChange={(e) => onMappingProfileTypeChange(e.target.value as DataSourceProfileType)}
                  >
                    {PREVIEW_PROFILE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>必須項目</span>
                  <input
                    value={mappingRequiredFields}
                    onChange={(e) => setMappingRequiredFields(e.target.value)}
                    placeholder="例: question, answer"
                  />
                </label>
              </div>
            </div>

            <p className="ops-note">
              {approvalPolicy === "trusted"
                ? "信頼ソース: 同期した全ファイルを承認済み（source-of-truth）として取り込みます。1件ずつのレビューは行いません。"
                : "既定: 同期した全ファイルは pending_review で取り込まれ、根拠文書レビューで承認するまで高リスク回答の正式な根拠にはなりません。"}
            </p>

            <div className="screen-actions">
              <button type="submit" disabled={configSaving}>
                {configSaving ? "保存中…" : "接続設定を保存"}
              </button>
              <button type="button" onClick={onSaveAndSync} disabled={configSaving || syncing}>
                {syncing ? "同期中…" : "保存して同期開始"}
              </button>
            </div>
          </Section>
        </form>
      )}

      {error && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>取込メッセージ</h3>
          <p>{error}</p>
        </section>
      )}

      {configMessage && (
        <section className="result-panel config-success" aria-live="polite">
          <h3>保存しました</h3>
          <p>{configMessage}</p>
        </section>
      )}

      {syncResult && (
        <section className="result-panel" aria-live="polite">
          <div className="result-head">
            <span className={`status-badge status-${syncResult.status === "succeeded" ? "ok" : "temporarily_unavailable"}`}>
              {syncResult.status === "succeeded" ? "同期開始" : syncResult.status}
            </span>
            <span className="correlation-id">{syncResult.ingestion_run_id}</span>
          </div>
          <FieldGrid
            rows={[
              ["ソース", syncResult.source_id],
              ["コレクション", syncResult.collection_id],
              ["対象ドキュメント", String(syncResult.observed_count)],
              ["開始した取込", String(syncResult.changed_count)],
              ["失敗", String(syncResult.failed_count)],
            ]}
          />
          <div className="screen-actions">
            <Link className="button-link secondary" href="/ingestion-runs">
              取込ランを見る
            </Link>
          </div>
        </section>
      )}

      {result && (
        <section className="result-panel" aria-live="polite">
          <div className="result-head">
            <span className={`status-badge status-${result.status === "succeeded" ? "ok" : "temporarily_unavailable"}`}>
              {result.status === "succeeded" ? "取込成功" : result.status}
            </span>
            <span className="correlation-id">{result.ingestion_run_id}</span>
          </div>
          <FieldGrid
            rows={[
              ["ドキュメント", result.document_id],
              ["ファイル", result.filename],
              ["チャンク数", String(result.chunk_count)],
              ["承認状態", APPROVAL_OPTIONS.find((o) => o.value === result.approval_status)?.label ?? result.approval_status],
              ["発効日", result.effective_date ?? "—"],
              ["コレクション", result.collection_id],
            ]}
          />
          <div className="screen-actions">
            <Link className="button-link" href="/">
              質問するで根拠を確認
            </Link>
            <Link className="button-link secondary" href="/ingestion-runs">
              取込ランを見る
            </Link>
            <Link className="button-link secondary" href="/documents">
              ドキュメント一覧
            </Link>
          </div>
        </section>
      )}
    </>
  );
}

function SupportBody() {
  const incidents = [
    ["回答 API レイテンシ上昇", "解決済み", "2026-06-18"],
    ["CAD 図面ソースの同期遅延", "調査中", "2026-06-22"],
  ];
  return (
    <>
      <Section title="稼働状況" note="サポート受付とインシデント状況を表示します。">
        <div className="metric-grid">
          <Stat label="稼働率（30日）" value="99.95%" />
          <Stat label="オープン中" value="1" />
          <Stat label="解決済み（今月）" value="4" />
        </div>
      </Section>
      <Section title="インシデント">
        <DataTable
          columns={["タイトル", "状態", "日付"]}
          rows={incidents.map((row) => row.map((cell) => cell))}
          empty="インシデントはありません。"
        />
      </Section>
      <Section title="お問い合わせ">
        <FieldGrid
          rows={[
            ["サポート窓口", "support@raku-rag.example"],
            ["緊急連絡", "Slack #manufacturing-qa"],
            ["対応時間", "平日 9:00–18:00 (JST)"],
          ]}
        />
      </Section>
    </>
  );
}

const UPLOAD_APPROVAL_LABEL: Record<string, string> = {
  approved: "承認済み",
  pending_review: "承認待ち",
  draft: "ドラフト",
  obsolete: "旧版",
};

const DOCUMENT_KIND_LABEL: Record<string, string> = {
  work_instruction: "作業手順書",
  standard: "標準",
  inspection: "検査基準",
  safety: "安全",
  trouble_case: "トラブル事例",
  manual: "マニュアル",
  drawing: "図面",
  spec: "仕様書",
};

function DocumentListBody() {
  const [uploaded, setUploaded] = useState<IngestedDoc[]>([]);
  const [docs, reloadDocs] = useLoad(
    async () => manufacturingDocuments(await getSessionToken(), DEMO_COLLECTION),
    [],
  );

  useEffect(() => {
    setUploaded(loadIngestedDocs());
  }, []);

  const emptyDocumentMessage =
    uploaded.length > 0
      ? "テナント一覧への反映を確認中です。直近アップロードは上の控えに表示されています。"
      : "ドキュメントはまだありません。「ソースを追加」から取り込めます。";

  return (
    <>
      {uploaded.length > 0 && (
        <Section
          title="最近アップロードしたドキュメント"
          note="このブラウザから取り込んだドキュメントです（取込直後の控え。テナント全体は下の一覧に表示されます）。"
        >
          <DataTable
            columns={["文書", "承認状態", "チャンク", "コレクション", "取込日時"]}
            rows={uploaded.map((doc) => [
              <Link key={doc.document_id} href={`/documents/${doc.document_id}`}>
                {doc.document_id}
              </Link>,
              UPLOAD_APPROVAL_LABEL[doc.approval_status] ?? doc.approval_status,
              String(doc.chunk_count),
              doc.collection_id,
              new Date(doc.ingested_at).toLocaleString("ja-JP"),
            ])}
            empty="アップロードはありません。"
          />
          <div className="screen-actions">
            <button
              type="button"
              className="btn-reject"
              onClick={() => {
                clearIngestedDocs();
                setUploaded([]);
              }}
            >
              この控えを消去
            </button>
          </div>
        </Section>
      )}
      <Section
        title="ドキュメント"
        note="テナントのナレッジベースに取り込まれ、検索・回答の根拠になっているドキュメントです。"
      >
        {docs.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">ドキュメントを読み込み中…</p>}
        {docs.state === "error" && <ScreenLoadError error={docs.error} onRetry={reloadDocs} />}
        {docs.state === "ready" && (
          <DataTable
            columns={["文書", "種別", "承認状態", "発効日", "ソース", "コレクション"]}
            rows={docs.data.map((doc) => [
              <Link key={doc.document_id} href={`/documents/${doc.document_id}`}>
                {doc.document_id}
              </Link>,
              ((kind) => (kind ? DOCUMENT_KIND_LABEL[kind] ?? kind : "—"))(
                doc.document_kind ?? doc.source_id,
              ),
              <span
                key={`${doc.document_id}-status`}
                className={`review-queue-status approval-${doc.approval_status}`}
              >
                {UPLOAD_APPROVAL_LABEL[doc.approval_status] ?? doc.approval_status}
              </span>,
              doc.effective_date ?? "—",
              doc.source_id,
              doc.collection_id,
            ])}
            empty={emptyDocumentMessage}
          />
        )}
      </Section>
    </>
  );
}

function DocumentDetailBody({ documentId }: { documentId: string }) {
  const [saving, setSaving] = useState(false);
  const [metadata, setMetadata] = useState("{\n  \"owner\": \"ops\"\n}");
  const [state, setState] = useState<ViewState<{ processing: Record<string, unknown> }>>({ state: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const reload = useCallback(() => setRefreshTick((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setState({ state: "loading" });
    runWithToken((token) => apiGetJson(`/admin/documents/${encodeURIComponent(documentId)}/processing-status`, token))
      .then((processing) =>
        active && setState({ state: "ready", data: { processing: processing as Record<string, unknown> } }),
      )
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) setState({ state: "error", error: formatLoadError(err) });
      });
    return () => {
      active = false;
    };
  }, [documentId, refreshTick]);

  async function onSave() {
    setSaving(true);
    setActionError(null);
    try {
      const parsed = JSON.parse(metadata) as Record<string, unknown>;
      await runWithToken((token) => manufacturingUpdateDocumentMetadata(documentId, parsed, token));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    setSaving(true);
    setActionError(null);
    try {
      await runWithToken((token) => manufacturingDeleteDocument(documentId, token));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Section title="ドキュメント詳細" note="文書の処理状態とメタデータを表示します。">
        <FieldGrid
          rows={[
            ["文書 ID", documentId],
            ["承認状態", "pending_review"],
            ["ソース", "取り込みソース"],
            [
              "状態",
              state.state === "ready"
                ? String((state.data.processing as { status?: string }).status ?? "ready")
                : "loading",
            ],
          ]}
        />
      </Section>
      <Section title="メタデータ編集">
        <textarea value={metadata} onChange={(e) => setMetadata(e.target.value)} rows={8} aria-label="メタデータ" />
        <div className="screen-actions">
          <button type="button" onClick={() => void onSave()} disabled={saving}>
            メタデータを保存
          </button>
          <button type="button" className="btn-reject" onClick={() => void onDelete()} disabled={saving}>
            文書を削除
          </button>
        </div>
      </Section>
      {state.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">処理状態を読み込み中…</p>}
      {state.state === "error" && <ScreenLoadError error={state.error} onRetry={reload} />}
      {state.state === "ready" && (
        <Section title="処理状態">
          <pre className="code-block">{JSON.stringify(state.data.processing, null, 2)}</pre>
        </Section>
      )}
      {actionError && <ScreenLoadError error={actionError} />}
    </>
  );
}

function ApprovalWorkflowBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    return manufacturingGovernanceStatus(token);
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">ガバナンス状態を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return (
    <>
      <Section title="ガバナンスベースのポリシー">
        <FieldGrid
          rows={[
            ["AI生成物はドラフト固定", state.data.draft_review.ai_output_always_draft ? "はい" : "いいえ"],
            ["AIドラフト承認に担当者必須", state.data.draft_review.reviewer_required_for_approval ? "はい" : "いいえ"],
            ["高リスク回答は承認済み根拠が必須", state.data.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
          ]}
        />
      </Section>
      <Section title="同期・承認ポリシー">
        <textarea
          value="現在の画面では、ガバナンス設定とデータソースの信頼ポリシーを表示します。同期元を信頼するか、根拠文書レビューに回すかはデータソース追加時に選択します。"
          readOnly
          rows={5}
          aria-label="同期・承認ポリシーの説明"
        />
        <p className="ops-note">この画面のポリシー編集 API は未接続です。</p>
      </Section>
    </>
  );
}

function GenericOpsOverview() {
  const [state, reload] = useLoad(
    async () => {
      const token = await getSessionToken();
      const [dashboard, telemetry, kpi, governance] = await Promise.all([
        manufacturingDashboard(token),
        manufacturingSafetyTelemetry(token),
        manufacturingKpi(token),
        manufacturingGovernanceStatus(token),
      ]);
      return { dashboard, telemetry, kpi, governance };
    },
    [],
  );
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">運用概要を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const telemetryBreakdown =
    state.data.telemetry.block_breakdown ?? state.data.telemetry.safety_gate_block_breakdown ?? {};
  const breakdownEntries = Object.entries(telemetryBreakdown);
  const totalBlocks = breakdownEntries.reduce((sum, [, count]) => sum + Number(count || 0), 0) || 1;
  // 承認カバレッジ = 根拠付き回答率（承認済み引用に裏付けられた回答の割合）。実 KPI 由来。
  const coverage = Math.max(0, Math.min(100, Math.round((state.data.kpi.grounded_answer_rate ?? 0) * 100)));
  // 旧版・要見直し候補（実データ）。以前はハードコードの「有効期限が近い引用」を表示していた。
  const reviewCandidates = state.data.kpi.obsolete_document_candidates ?? [];
  return (
    <>
      <div className="standalone-ops-kpis">
        <div className="standalone-ops-kpi">
          <div className="standalone-ops-kpi-label">未回答 / 保留</div>
          <div className="standalone-ops-kpi-value">{state.data.dashboard.unanswered_question_count}</div>
          <div className="standalone-ops-kpi-sub">質問の滞留状況</div>
        </div>
        <div className="standalone-ops-kpi">
          <div className="standalone-ops-kpi-label">高リスク</div>
          <div className="standalone-ops-kpi-value">{state.data.telemetry.high_risk_query_count}</div>
          <div className="standalone-ops-kpi-sub">安全注意が必要な件数</div>
        </div>
        <div className="standalone-ops-kpi">
          <div className="standalone-ops-kpi-label">安全ブロック</div>
          <div className="standalone-ops-kpi-value">{state.data.telemetry.safety_gate_block_count}</div>
          <div className="standalone-ops-kpi-sub">回答を止めた件数</div>
        </div>
        <div className="standalone-ops-kpi">
          <div className="standalone-ops-kpi-label">自己解決率</div>
          <div className="standalone-ops-kpi-value">{`${(state.data.kpi.self_resolution_rate * 100).toFixed(1)}%`}</div>
          <div className="standalone-ops-kpi-sub">問い合わせ抑制の指標</div>
        </div>
      </div>

      <div className="standalone-ops-main">
        <section className="standalone-ops-card">
          <div className="standalone-ops-card-head">
            <h3>安全テレメトリ</h3>
            <div className="standalone-ops-legends">
              <span><i className="legend-dot legend-warning" />高リスク</span>
              <span><i className="legend-dot legend-danger" />保留</span>
              <span><i className="legend-dot legend-muted" />旧版</span>
            </div>
          </div>
          <div className="standalone-ops-bars">
            {breakdownEntries.length > 0 ? (
              breakdownEntries.map(([reason, count]) => {
                const value = Number(count || 0);
                const height = Math.max(8, Math.round((value / totalBlocks) * 100));
                return (
                  <div className="standalone-ops-bar" key={reason}>
                    <div className="standalone-ops-bar-main" style={{ height: `${height}%` }} />
                    <div className="standalone-ops-bar-label">{reason}</div>
                  </div>
                );
              })
            ) : (
              <div className="ops-empty">安全テレメトリはまだありません。</div>
            )}
          </div>
        </section>

        <section className="standalone-ops-card">
          <div className="standalone-ops-card-head">
            <h3>承認カバレッジ</h3>
          </div>
          <div className="standalone-ops-coverage">
            <div className="standalone-ops-coverage-value">{coverage}%</div>
            <span>根拠付き回答率</span>
          </div>
          <div className="standalone-ops-progress">
            <div style={{ width: `${coverage}%` }} />
          </div>
          <div className="standalone-ops-expiring-title">旧版・要見直し候補</div>
          <div className="standalone-ops-expiring">
            {reviewCandidates.length > 0 ? (
              reviewCandidates.slice(0, 6).map((docId) => (
                <div key={docId} className="standalone-ops-expiring-row">
                  <div>
                    <div className="standalone-ops-expiring-doc">{docId}</div>
                    <div className="standalone-ops-expiring-date">旧版のみヒット / 要見直し</div>
                  </div>
                  <Link href={`/documents/${docId}`}>確認</Link>
                </div>
              ))
            ) : (
              <div className="ops-empty">要見直しの候補はありません。</div>
            )}
          </div>
        </section>
      </div>

      <section className="standalone-ops-panel">
        <div className="standalone-ops-card-head">
          <h3>ガバナンス</h3>
        </div>
        <FieldGrid
          rows={[
            ["ポリシー版本", String(state.data.governance.policy_version)],
            ["No-train デフォルト", state.data.governance.no_train.no_train_default ? "はい" : "いいえ"],
            ["安全ゲート有効", state.data.governance.safety_gate.enabled ? "はい" : "いいえ"],
            ["高リスク回答は承認済み根拠が必須", state.data.governance.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
            ["AI生成物はドラフト固定", state.data.governance.draft_review.ai_output_always_draft ? "はい" : "いいえ"],
          ]}
        />
      </section>
    </>
  );
}

interface AuditRecord {
  timestamp?: string;
  actor_id?: string;
  actor_role?: string | null;
  action?: string;
  resource_type?: string | null;
  resource_id?: string | null;
  decision?: string | null;
  reason?: string | null;
  safety_block_reason?: string | null;
  high_risk_classification_result?: boolean;
  collection_id?: string | null;
  document_ids_used?: string[];
  citation_ids?: string[];
  entry_hash?: string | null;
}

function fmtTime(value?: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP");
  } catch {
    return value;
  }
}

function AuditLogBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    try {
      return manufacturingAuditEvents(token, { limit: 200 });
    } catch {
      const exported = await manufacturingAuditExport(token, "dict");
      const records = (exported as { records?: AuditRecord[] }).records ?? [];
      return { events: records, total: records.length, offset: 0, limit: records.length };
    }
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">監査ログを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;

  const records = (state.data.events ?? []) as AuditRecord[];

  function onExportCsv() {
    const header = [
      "timestamp",
      "actor_id",
      "actor_role",
      "action",
      "resource_type",
      "resource_id",
      "decision",
      "reason",
      "high_risk",
      "safety_block_reason",
      "collection_id",
      "document_ids_used",
      "entry_hash",
    ];
    const rows = records.map((r) => [
      r.timestamp,
      r.actor_id,
      r.actor_role,
      r.action,
      r.resource_type,
      r.resource_id,
      r.decision,
      r.reason,
      r.high_risk_classification_result ? "true" : "",
      r.safety_block_reason,
      r.collection_id,
      (r.document_ids_used ?? []).join("|"),
      r.entry_hash,
    ]);
    downloadCsv("audit-log.csv", [header, ...rows]);
  }

  return (
    <>
      <p className="src-warning">
        監査ログは改ざん不可・追記のみ（ハッシュチェーン）。重要操作の actor / action / resource / decision を記録します。
      </p>
      <Section title="監査イベント" note={`${state.data.total ?? records.length} 件`}>
        <div className="screen-actions">
          <button type="button" onClick={onExportCsv} disabled={records.length === 0}>
            CSV を出力
          </button>
        </div>
        <DataTable
          columns={["時刻", "アクター", "アクション", "リソース", "決定 / 理由", "ハッシュ"]}
          rows={records.map((r) => [
            fmtTime(r.timestamp),
            r.actor_id ?? "—",
            r.action ?? "—",
            r.resource_id ? `${r.resource_type ?? ""} ${r.resource_id}`.trim() : (r.resource_type ?? "—"),
            <span key="d">
              {r.decision ?? "—"}
              {r.reason ? ` · ${r.reason}` : ""}
              {r.high_risk_classification_result ? " · 高リスク" : ""}
            </span>,
            <span className="mono" key="h">
              {(r.entry_hash ?? "").slice(0, 12) || "—"}
            </span>,
          ])}
          empty="監査イベントはまだありません。"
        />
      </Section>
      <Section title="生データ">
        <details className="draft-raw">
          <summary>JSON（{records.length} 件）</summary>
          <pre className="code-block">{JSON.stringify(state.data, null, 2)}</pre>
        </details>
      </Section>
    </>
  );
}

const ROLE_REFERENCE: Array<[string, string, string]> = [
  ["管理者 (tenant_admin)", "全設定・課金・権限・承認", "tenant"],
  ["承認者 (reviewer)", "文書・ドラフトの承認 / 却下", "document"],
  ["運用 (ops_owner)", "ソース・取込・運用ダッシュボード", "tenant"],
  ["編集者 (editor)", "ソース追加・ドラフト編集", "collection"],
  ["閲覧者 / 一般 (field_user)", "質問・閲覧のみ", "collection"],
];

interface SimResult {
  userId: string;
  status: string;
  citationCount: number;
  docs: string[];
}

function PermissionSimulator() {
  const [userId, setUserId] = useState("bob");
  const [query, setQuery] = useState("What is the maintenance interval for pump P-12?");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(asUser: string) {
    if (loading) return;
    setUserId(asUser);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const token = await mintTokenFor(DEMO_TENANT, asUser);
      const res = await manufacturingAnswer({ query: query.trim(), collection_id: "manuals" }, token);
      setResult({
        userId: asUser,
        status: res.status,
        citationCount: res.citations.length,
        docs: Array.from(new Set(res.citations.map((c) => c.document_id))),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "実行に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  const accessible = result ? result.citationCount > 0 : false;

  return (
    <Section
      title="権限シミュレーター"
      note="指定ユーザーとして同じ質問を実行し、その人がアクセスできる根拠だけが返ることを確認します（ACL は deny-by-default でサーバ側強制）。"
    >
      <div className="form-grid">
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} placeholder="質問" aria-label="質問" />
        <div className="review-assign-row">
          <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user_id" aria-label="ユーザーID" />
          <button type="button" onClick={() => void run(userId.trim() || "bob")} disabled={loading || !query.trim()}>
            このユーザーで実行
          </button>
        </div>
        <div className="ops-flags">
          <button type="button" className="citation-open" onClick={() => void run("alice")} disabled={loading}>
            alice（承認者・manuals 付与）で実行
          </button>
          <button type="button" className="citation-open" onClick={() => void run("bob")} disabled={loading}>
            bob（権限なし）で実行
          </button>
        </div>
      </div>

      {loading && <p className="ops-empty" role="status" aria-live="polite">実行中…</p>}
      {error && <p className="cv-foot-error" role="alert">{error}</p>}
      {result && (
        <div className={`sim-result ${accessible ? "sim-ok" : "sim-deny"}`}>
          <div className="result-head">
            <span className={`status-badge status-${result.status}`}>{statusLabel(result.status)}</span>
            <span className="correlation-id">user: {result.userId}</span>
          </div>
          <FieldGrid
            rows={[
              ["アクセス可能な引用", `${result.citationCount} 件`],
              ["参照ドキュメント", result.docs.length ? result.docs.join(", ") : "（権限により非表示）"],
              [
                "判定",
                accessible
                  ? "このユーザーは根拠にアクセスできます。"
                  : "権限外のため、検索結果・引用・回答に文書は一切出ません。",
              ],
            ]}
          />
        </div>
      )}
    </Section>
  );
}

function RolesAclBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    return apiGetJson<{ grants?: Array<Record<string, unknown>> }>("/admin/acl", token);
  }, []);

  return (
    <>
      <p className="src-warning">
        ACL は deny-by-default。権限外の文書は、検索結果・LLM コンテキスト・引用・ダッシュボードのいずれにも出ません（サーバ側で強制）。
      </p>
      <Section title="ロール一覧" note="テナントで利用できるロールと範囲。">
        <DataTable
          columns={["ロール", "権限の範囲", "スコープ"]}
          rows={ROLE_REFERENCE.map((row) => [row[0], row[1], row[2]])}
          empty="ロール定義はありません。"
        />
      </Section>

      <Section title="ACL 付与" note="GET /v1/admin/acl から取得した実データです。">
        {state.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">ACL を読み込み中…</p>}
        {state.state === "error" && <ScreenLoadError error={state.error} onRetry={reload} />}
        {state.state === "ready" && (
          <DataTable
            columns={["サブジェクト", "リソース", "権限"]}
            rows={(state.data.grants ?? []).map((g) => [
              String(g.subject_id ?? g.subject ?? "—"),
              String(g.resource_id ?? g.scope_id ?? g.scope ?? "—"),
              String(g.permission ?? g.role ?? "—"),
            ])}
            empty="明示的な ACL 付与はありません（既定で deny、付与で許可）。"
          />
        )}
      </Section>

      <PermissionSimulator />
    </>
  );
}

interface ProviderPolicy {
  provider_policy_id?: string;
  name?: string;
  status?: string;
  parser_mode?: string;
  allowed_parser_providers?: string[];
  allowed_ocr_providers?: string[];
  allowed_layout_providers?: string[];
  allowed_structured_providers?: string[];
  allowed_llm_providers?: string[];
  allowed_embedding_providers?: string[];
  allowed_visual_embedding_providers?: string[];
  allowed_vlm_providers?: string[];
  allowed_caption_providers?: string[];
  allowed_rerank_providers?: string[];
  allowed_regions?: string[];
  data_residency_requirement?: string;
  cross_cloud_processing_allowed?: boolean;
  zero_retention_required?: boolean;
}

interface DataUsePolicy {
  no_train_default?: boolean;
  training_opt_in?: boolean;
  provider_no_train_required?: boolean;
  no_train_fallback?: string;
  retention_customer?: number;
  retention_audit?: number;
  export_enabled?: boolean;
  policy_version?: string;
}

function NoTrainSummary({ policy }: { policy: DataUsePolicy }) {
  return (
    <FieldGrid
      rows={[
        ["顧客データを学習に使わない", policy.no_train_default ? "はい" : "いいえ"],
        ["提供元の no-train 必須", policy.provider_no_train_required ? "はい" : "いいえ"],
        ["no-train フォールバック", policy.no_train_fallback ?? "—"],
        ["学習オプトイン", policy.training_opt_in ? "あり" : "なし"],
        ["顧客データ保持（日）", String(policy.retention_customer ?? "—")],
        ["監査保持（日）", String(policy.retention_audit ?? "—")],
        ["エクスポート許可", policy.export_enabled ? "はい" : "いいえ"],
        ["ポリシー版", policy.policy_version ?? "—"],
      ]}
    />
  );
}

function ProviderPolicyBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    const [policies, dataUse] = await Promise.all([
      apiGetJson<unknown>("/admin/provider-policies", token),
      manufacturingDataUsePolicy(token),
    ]);
    return { policies, dataUse };
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">プロバイダーポリシーを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const policies = (Array.isArray(state.data.policies) ? state.data.policies : []) as ProviderPolicy[];
  const dataUse = state.data.dataUse as DataUsePolicy;
  return (
    <>
      <p className="src-warning">
        顧客データは既定で学習に使用しません。利用プロバイダ・リージョン・データ所在地を明示します。
      </p>
      <Section title="データ利用 / No-train" note="セキュリティ審査・営業説明にそのまま使える方針です。">
        <NoTrainSummary policy={dataUse} />
      </Section>
      {policies.map((p, i) => (
        <Section
          key={p.provider_policy_id ?? i}
          title={p.name ?? p.provider_policy_id ?? "プロバイダーポリシー"}
          note={`状態: ${p.status ?? "—"}`}
        >
          <FieldGrid
            rows={[
              ["パーサーモード", p.parser_mode ?? "—"],
              ["データ所在地", p.data_residency_requirement ?? "—"],
              ["クロスクラウド処理", p.cross_cloud_processing_allowed ? "許可" : "不許可"],
              ["ゼロ保持要件", p.zero_retention_required ? "必須" : "—"],
              ["許可リージョン", (p.allowed_regions ?? []).join(", ") || "—"],
              ["パーサー", (p.allowed_parser_providers ?? []).join(", ") || "—"],
              ["OCR", (p.allowed_ocr_providers ?? []).join(", ") || "—"],
              ["レイアウト解析", (p.allowed_layout_providers ?? []).join(", ") || "—"],
              ["構造抽出", (p.allowed_structured_providers ?? []).join(", ") || "—"],
              ["LLM プロバイダ", (p.allowed_llm_providers ?? []).join(", ") || "—"],
              ["埋め込みプロバイダ", (p.allowed_embedding_providers ?? []).join(", ") || "—"],
              ["画像埋め込み", (p.allowed_visual_embedding_providers ?? []).join(", ") || "—"],
              ["画像理解", (p.allowed_vlm_providers ?? []).join(", ") || "—"],
              ["キャプション", (p.allowed_caption_providers ?? []).join(", ") || "—"],
              ["リランカー", (p.allowed_rerank_providers ?? []).join(", ") || "—"],
            ]}
          />
        </Section>
      ))}
      <Section title="生データ">
        <details className="draft-raw">
          <summary>JSON</summary>
          <pre className="code-block">{JSON.stringify(state.data.policies, null, 2)}</pre>
        </details>
      </Section>
    </>
  );
}

interface RetrievalDebugResult {
  query: string;
  status: string;
  highRisk: boolean;
  blockReason: string | null;
  candidates: SearchResultItem[];
  usedChunkIds: Set<string>;
  citationApproval: Map<string, string>;
  searchCorrelation: string;
  answerCorrelation: string;
}

function RetrievalDebugBody() {
  const [query, setQuery] = useState("What is the maintenance interval for pump P-12?");
  const [collection, setCollection] = useState("manuals");
  const [topK, setTopK] = useState(8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RetrievalDebugResult | null>(null);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (loading || !query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const token = await getSessionToken();
      const [searchRes, answerRes] = await Promise.all([
        searchChunks({ query: query.trim(), collection_id: collection.trim() || "manuals", top_k: topK }, token),
        manufacturingAnswer({ query: query.trim(), collection_id: collection.trim() || "manuals" }, token),
      ]);
      const usedChunkIds = new Set<string>();
      const citationApproval = new Map<string, string>();
      for (const c of answerRes.citations) {
        if (c.chunk_id) usedChunkIds.add(c.chunk_id);
        if (c.chunk_id && c.approval_status) citationApproval.set(c.chunk_id, c.approval_status);
      }
      for (const u of answerRes.used_chunks ?? []) {
        const id = typeof u === "string" ? u : (u as { chunk_id?: string }).chunk_id;
        if (id) usedChunkIds.add(id);
      }
      setResult({
        query: query.trim(),
        status: answerRes.status,
        highRisk: Boolean(answerRes.manufacturing?.high_risk),
        blockReason: answerRes.manufacturing?.safety_block_reason ?? null,
        candidates: searchRes.results,
        usedChunkIds,
        citationApproval,
        searchCorrelation: searchRes.correlation_id,
        answerCorrelation: answerRes.correlation_id,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "実行に失敗しました");
    } finally {
      setLoading(false);
    }
  }

  function verdict(item: SearchResultItem): { label: string; cls: string; reason: string } {
    if (!result) return { label: "—", cls: "", reason: "" };
    const used = result.usedChunkIds.has(item.chunk_id);
    if (used) return { label: "採用", cls: "approval-approved", reason: "回答の根拠に採用" };
    if (result.blockReason) return { label: "除外", cls: "approval-obsolete", reason: "安全ゲートで回答を保留" };
    if (result.status === "insufficient_evidence")
      return { label: "除外", cls: "approval-obsolete", reason: "根拠ゲート（しきい値/承認）で不採用" };
    return { label: "除外", cls: "approval-draft", reason: "上位候補に採用されず" };
  }

  return (
    <>
      <p className="src-warning">
        質問に対する検索候補（ACL deny-by-default 適用後）と、回答に採用された根拠・除外理由を表示します。「なぜ答えられなかったか」の診断に使えます。
      </p>
      <form className="draft-create-form" onSubmit={run}>
        <Section title="検索診断">
          <label>
            <span>質問</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <div className="upload-fields">
            <label>
              <span>コレクション</span>
              <input value={collection} onChange={(e) => setCollection(e.target.value)} />
            </label>
            <label>
              <span>top_k</span>
              <input
                type="number"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Math.max(1, Math.min(20, Number(e.target.value) || 8)))}
              />
            </label>
          </div>
          <div className="screen-actions">
            <button type="submit" disabled={loading || !query.trim()}>
              {loading ? "診断中…" : "診断を実行"}
            </button>
          </div>
        </Section>
      </form>

      {error && (
        <section className="result-panel error-panel" role="alert">
          <h3>診断に失敗しました</h3>
          <p>{error}</p>
        </section>
      )}

      {result && (
        <>
          <Section title="判定">
            <FieldGrid
              rows={[
                ["回答ステータス", statusLabel(result.status)],
                ["高リスク分類", result.highRisk ? "はい" : "いいえ"],
                ["安全ブロック理由", result.blockReason ?? "—"],
                ["検索候補数", String(result.candidates.length)],
                ["採用された根拠", String(result.usedChunkIds.size)],
              ]}
            />
          </Section>

          <Section
            title="検索候補（ACL 適用後・スコア順）"
            note="この一覧は既に ACL deny-by-default で絞り込まれています。権限外の文書はそもそも出ません。"
          >
            <DataTable
              columns={["チャンク", "スコア", "承認", "採用/除外", "理由"]}
              rows={result.candidates.map((item) => {
                const v = verdict(item);
                const appr = result.citationApproval.get(item.chunk_id);
                return [
                  <span className="mono" key="c">
                    {item.document_id} / {item.chunk_id}
                  </span>,
                  item.retrieval_score.toFixed(3),
                  appr ? UPLOAD_APPROVAL_LABEL[appr] ?? appr : "—",
                  <span className={`citation-chip ${v.cls}`} key="v">
                    {v.label}
                  </span>,
                  v.reason,
                ];
              })}
              empty="検索候補はありません（権限・コレクション・クエリを確認してください）。"
            />
          </Section>

          <Section title="パイプラインと補足情報">
            <FieldGrid
              rows={[
                ["パイプライン", "埋め込み → ベクトル候補（ACL事前フィルタ）→ ハイブリッド統合 → ACL再確認 → リランク → top_k → 安全/根拠ゲート → 生成"],
                ["ACL", "deny-by-default・サーバ側強制（候補は許可済みのみ）"],
                ["相関 ID", `search ${result.searchCorrelation || "—"} / answer ${result.answerCorrelation || "—"}`],
                [
                  "詳細診断",
                  "ACL適用前の候補、リランク前後スコア、メタデータフィルタ内部は管理者向け診断として順次表示します。",
                ],
              ]}
            />
          </Section>
        </>
      )}
    </>
  );
}

function RetrievalBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    const [profiles, queries] = await Promise.all([
      apiGetJson("/admin/retrieval-profiles", token),
      apiGetJson("/admin/query-profiles", token),
    ]);
    return { profiles, queries };
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">検索設定を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return <Section title="検索設定"><pre className="code-block">{JSON.stringify(state.data, null, 2)}</pre></Section>;
}

function LoggingPrivacyBody() {
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    const [logging, policy] = await Promise.all([
      apiGetJson<unknown>("/admin/logging-policies", token),
      manufacturingDataUsePolicy(token),
    ]);
    return { logging, policy };
  }, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">ログポリシーを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const dataUse = state.data.policy as DataUsePolicy;
  return (
    <>
      <p className="src-warning">ログ保存方針とデータ利用（no-train）方針です。顧客データの取り扱いとリテンションを明示します。</p>
      <Section title="データ利用 / 保持">
        <NoTrainSummary policy={dataUse} />
      </Section>
      <Section title="ログポリシー">
        <details className="draft-raw">
          <summary>JSON</summary>
          <pre className="code-block">{JSON.stringify(state.data.logging, null, 2)}</pre>
        </details>
      </Section>
    </>
  );
}

function ApiKeysBody() {
  return (
    <>
      <Section title="APIキー" note="外部連携で利用する API キーを管理します。">
        <DataTable columns={["キー", "範囲", "状態"]} rows={[]} empty="APIキーはまだありません。" />
      </Section>
      <Section title="Webhook">
        <p className="ops-empty">Webhook はまだ登録されていません。</p>
      </Section>
    </>
  );
}

function BillingBody() {
  return (
    <>
      <Section title="利用状況 / 請求" note="利用状況と予算の概要を表示します。">
        <FieldGrid rows={[["プラン", MOCK_BILLING.plan], ["利用状況", MOCK_BILLING.usage]]} />
      </Section>
      <Section title="請求書">
        <ul className="ops-list">
          {MOCK_BILLING.invoices.map((invoice) => (
            <li key={invoice}>{invoice}</li>
          ))}
        </ul>
      </Section>
    </>
  );
}

function MockAdminScreen({ title, rows }: { title: string; rows: AdminListRow[] }) {
  return (
    <Section title={title}>
      <DataTable
        columns={[title, "メタデータ", "状態"]}
        rows={rows.map((row) => [row.label, row.meta ?? "—", row.status ?? "—"])}
        empty={`${title} の設定はまだありません。`}
      />
    </Section>
  );
}
