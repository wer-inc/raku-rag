"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type {
  Citation,
  GovernanceStatus,
  KnowledgeOpsDashboard,
  ManufacturingAnswerResponse,
  ManufacturingIngestionRun,
  ManufacturingKpi,
  ManufacturingSourceSyncStatus,
  SafetyTelemetryView,
  SearchResultItem,
  DraftArtifact,
} from "@raku-rag/shared";
import {
  apiDeleteJson,
  apiGetJson,
  apiPostJson,
  apiPutJson,
  ingestDocument,
  manufacturingAnswer,
  searchChunks,
  manufacturingAssignReviewer,
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
  manufacturingRequestSourceSync,
  manufacturingReviewDraft,
  manufacturingSafetyTelemetry,
  manufacturingSourceSyncStatus,
  manufacturingTroubleCaseSearch,
  manufacturingUpdateDocumentMetadata,
  submitFeedback,
} from "../../lib/api-client";
import {
  clearSessionToken,
  DEMO_COLLECTION,
  DEMO_TENANT,
  getSessionToken,
  mintTokenFor,
} from "../../lib/session";
import { missingApis, type ManifestScreen } from "../../lib/full-saas";
import CitationViewer, { type CitationViewTarget } from "./CitationViewer";
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
  return error instanceof Error && /session|token|auth/i.test(error.message);
}

async function runWithToken<T>(loader: (token: string) => Promise<T>): Promise<T> {
  const token = await getSessionToken();
  return loader(token);
}

function useLoad<T>(loader: () => Promise<T>, deps: React.DependencyList): ViewState<T> {
  const [state, setState] = useState<ViewState<T>>({ state: "loading" });

  useEffect(() => {
    let active = true;
    setState({ state: "loading" });
    loader()
      .then((data) => {
        if (active) setState({ state: "ready", data });
      })
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) setState({ state: "error", error: err instanceof Error ? err.message : "リクエストに失敗しました" });
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
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

function QuickLinks() {
  return (
    <div className="quick-links">
      <Link href="/">質問する</Link>
      <Link href="/sources">ソース</Link>
      <Link href="/reviews">レビュー</Link>
      <Link href="/operations">運用</Link>
      <Link href="/admin/users">管理</Link>
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
      {error && <span className="cv-foot-error">{error}</span>}
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
  const [turns, setTurns] = useState<AnswerTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewer, setViewer] = useState<CitationViewTarget | null>(null);

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    const turnId = `${Date.now().toString(36)}-${turns.length}`;
    setTurns((prev) => [...prev, { kind: "user", id: `${turnId}-q`, text: trimmed }]);
    setQuery("");
    setLoading(true);
    try {
      const token = await getSessionToken();
      const response = await manufacturingAnswer({ query: trimmed, collection_id: "manuals" }, token);
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
          error: err instanceof Error ? err.message : "リクエストに失敗しました",
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

        {loading && <p className="ops-empty">回答を生成中…</p>}
      </div>

      <form className="answers-composer" onSubmit={onAsk}>
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
                    <h4 className="src-h4">原因候補</h4>
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
            <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="run_id" autoComplete="off" />
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
    "review-queue": "レビューキュー",
    "review-detail": "レビュー詳細",
    "approval-workflow-settings": "承認ルール",
    "document-approval-queue": "文書承認キュー",
    "operations-dashboard": "運用ダッシュボード",
    "safety-telemetry": "安全テレメトリ",
    "quality-kpi": "品質・KPI",
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
          <p className="eyebrow">フル SaaS ワークスペース</p>
          <h2>{screenTitle(screen)}</h2>
        </div>
      </header>
      {children}
    </section>
  );
}

function ScreenLoadError({ error }: { error: string }) {
  return (
    <section className="result-panel error-panel" aria-live="polite">
      <h3>読み込みに失敗しました</h3>
      <p>{error}</p>
    </section>
  );
}

function MockBanner({ screen }: { screen: ManifestScreen }) {
  return (
    <p className="src-warning">
      {screen.title} は固定された契約で表示しています。バックエンドに一覧や書き込みの API がない部分は、
      型付きモックで表示し、GAP を見えるままにしています。
    </p>
  );
}

function SourceListBody() {
  const sources = [
    { name: "Press line manuals", type: "SharePoint", status: "正常", docs: "2,184", fresh: "2日前", owner: "北島" },
    { name: "SOP library", type: "S3", status: "同期中", docs: "418", fresh: "12時間前", owner: "山本" },
    { name: "Trouble cases", type: "Postgres", status: "準備完了", docs: "6,204", fresh: "5時間前", owner: "佐藤" },
    { name: "CAD 図面ソース", type: "SharePoint", status: "認証エラー", docs: "126", fresh: "1日前", owner: "設計" },
  ];

  return (
    <div className="standalone-list-shell">
      <header className="standalone-list-head">
        <div className="standalone-list-head-title">
          <h3>ソース</h3>
        </div>
        <div className="standalone-list-tools">
          <label className="standalone-search">
            <span aria-hidden="true">⌕</span>
            <input placeholder="ソースを検索" />
          </label>
          <button type="button">ソースを追加</button>
        </div>
      </header>
      <div className="standalone-table-wrap">
        <div className="standalone-table-head">
          <div>ソース</div>
          <div>種別</div>
          <div>ステータス</div>
          <div className="is-right">文書数</div>
          <div className="is-right">鮮度</div>
          <div>オーナー</div>
        </div>
        {sources.map((source) => (
          <Link key={source.name} href="/sources/list" className="standalone-table-row">
            <div className="standalone-source-cell">
              <div className="standalone-source-mark">{source.name.slice(0, 1)}</div>
              <span>{source.name}</span>
            </div>
            <div>{source.type}</div>
            <div>
              <span
                className={`standalone-status ${source.status === "正常" ? "ok" : source.status === "認証エラー" ? "bad" : "wait"}`}
              >
                {source.status}
              </span>
            </div>
            <div className="is-right mono">{source.docs}</div>
            <div className="is-right muted">{source.fresh}</div>
            <div className="muted">{source.owner}</div>
          </Link>
        ))}
      </div>
    </div>
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
      note="このブラウザでの質問履歴です（テナント共有の履歴 API 提供まではローカル保存）。"
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
  const state = useLoad(
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

  if (state.state === "loading") return <p className="ops-empty">ホームダッシュボードを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;

  const { dashboard, telemetry, kpi, governance } = state.data;
  return (
    <>
      <Section title="今日のタスク" note="ホームでは今日の作業をひと目で確認できます。">
        <div className="home-task-grid">
          <Link href="/reviews" className="home-task-card">
            <div className="home-task-head">
              <span className="home-task-label">レビュー待ち</span>
              <span className="home-task-dot" />
            </div>
            <strong>{dashboard.unanswered_question_count}</strong>
            <span>未回答の質問</span>
            <span className="home-task-cta">ドラフト確認</span>
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
            <Link href="/sources" className="action-card">
              <strong>ソース</strong>
              <span>トラブルケースとソース状態を確認する</span>
            </Link>
            <Link href="/reviews" className="action-card">
              <strong>レビュー</strong>
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
              ["高リスクは承認済み引用必須", governance.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
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
  const [runState, setRunState] = useState<ViewState<ManufacturingIngestionRun>>({ state: "loading" });
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setSyncState({ state: "loading" });
    setRunState({ state: "loading" });
    runWithToken((token) => manufacturingSourceSyncStatus(sourceId, token))
      .then((data) => {
        if (active) setSyncState({ state: "ready", data });
        const latest = data.correlation_id;
        if (latest) {
          return runWithToken((token) => manufacturingIngestionRun(latest, token));
        }
        return null;
      })
      .then((data) => {
        if (active && data) setRunState({ state: "ready", data });
      })
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) setSyncState({ state: "error", error: err instanceof Error ? err.message : "リクエストに失敗しました" });
      });
    return () => {
      active = false;
    };
  }, [sourceId]);

  async function onSyncRequest(event: FormEvent) {
    event.preventDefault();
    setSyncMessage(null);
    try {
      await runWithToken((token) => manufacturingRequestSourceSync(sourceId, { reason: "manual_refresh" }, token));
      setSyncMessage("同期を依頼しました");
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : "同期依頼に失敗しました");
    }
  }

  return (
    <>
      <Section title="ソース操作" note="同期操作は明示的で監査可能です。">
        <form className="src-inline-form" onSubmit={onSyncRequest}>
          <input value={sourceId} readOnly aria-label="ソース ID" />
          <button type="submit">同期を依頼</button>
        </form>
        {syncMessage && <p className="ops-note">{syncMessage}</p>}
      </Section>

      {syncState.state === "loading" && <p className="ops-empty">ソース同期状態を読み込み中…</p>}
      {syncState.state === "error" && <ScreenLoadError error={syncState.error} />}
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

      {runState.state === "ready" && (
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
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDocs(loadIngestedDocs());
  }, []);

  async function transition(doc: IngestedDoc, toStatus: string) {
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
      setDocs(loadIngestedDocs());
      setMessage(`${doc.document_id} を「${DOC_APPROVAL_STATUS[nextStatus]?.label ?? nextStatus}」に更新しました。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新に失敗しました");
    } finally {
      setBusy(null);
    }
  }

  const pending = docs.filter((d) => (DOC_LIFECYCLE_RANK[d.approval_status] ?? 0) < 2);

  return (
    <>
      <p className="src-warning">
        取り込んだ文書は、ここで承認するまで正式な根拠になりません。承認ワークフローは前進のみで、obsolete
        化が可能です（差し戻しは未対応・source-of-truth 上書きは import_external が必要）。
      </p>
      <Section
        title="文書承認キュー"
        note={`このブラウザで取り込んだ ${docs.length} 件（承認待ち相当 ${pending.length} 件）。承認すると質問の正式な根拠になり、旧版化すると警告表示になります。`}
      >
        {docs.length === 0 ? (
          <p className="ops-empty">
            取り込んだ文書がありません。<Link href="/sources/new">ソースを追加</Link> からアップロードしてください。
          </p>
        ) : (
          <div className="approval-list">
            {docs.map((doc) => {
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
        {error && <p className="cv-foot-error">{error}</p>}
      </Section>
    </>
  );
}

function ReviewDetailBody({ artifactId }: { artifactId: string }) {
  const [draftState, setDraftState] = useState<ViewState<DraftArtifact>>({ state: "loading" });
  const [reviewerId, setReviewerId] = useState("alice");
  const [comment, setComment] = useState("");
  const [docId, setDocId] = useState("");
  const [approvalState, setApprovalState] = useState("pending_review");
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setDraftState({ state: "loading" });
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
    if (draftState.state !== "ready") return;
    setActionError(null);
    try {
      await runWithToken((token) => manufacturingAssignReviewer(artifactId, { reviewer_id: reviewerId }, token));
      const refreshed = await runWithToken((token) => manufacturingGetDraft(artifactId, token));
      setDraftState({ state: "ready", data: refreshed });
      updateDraftRecord(artifactId, { status: refreshed.status, reviewer_id: refreshed.reviewer_id });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    }
  }

  async function onReview(decision: "approved" | "rejected") {
    if (draftState.state !== "ready") return;
    setActionError(null);
    try {
      await runWithToken((token) =>
        manufacturingReviewDraft(artifactId, { decision, comment: comment.trim() || undefined }, token),
      );
      const refreshed = await runWithToken((token) => manufacturingGetDraft(artifactId, token));
      setDraftState({ state: "ready", data: refreshed });
      updateDraftRecord(artifactId, { status: refreshed.status });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    }
  }

  async function onApproveDocument() {
    if (!docId.trim()) return;
    setActionError(null);
    try {
      await runWithToken((token) => manufacturingDocumentApproval(docId.trim(), { to_status: approvalState }, token));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "リクエストに失敗しました");
    }
  }

  if (draftState.state === "loading") return <p className="ops-empty">ドラフトを読み込み中…</p>;
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
        <p className="ops-note" style={{ color: "#15803d", fontWeight: 600 }}>
          承認済み — このドラフトは正式に公開できます。
        </p>
      )}
      {draft.status === "rejected" && (
        <p className="ops-note" style={{ color: "#be123c", fontWeight: 600 }}>
          却下 — 修正のうえ再生成が必要です。
        </p>
      )}

      <Section title="ドラフト詳細" note="AI 出力は、レビューで状態が変わるまでドラフトのままです。">
        <FieldGrid
          rows={[
            ["ドラフト ID", draft.artifact_id],
            ["種別", draftKindLabel(draft.type)],
            ["状態", st.label],
            ["作成者", draft.created_by === "ai" ? "AI" : (draft.created_by ?? "—")],
            ["レビュー担当", draft.reviewer_id ?? "未割当"],
            ["決定", draft.approval_decision ?? "—"],
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
            生成された項目はありません（デモの根拠ドキュメントからは具体項目を抽出できませんでした）。
            ステータス遷移とレビュー手順の検証用ドラフトです。
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
            <input value={reviewerId} onChange={(e) => setReviewerId(e.target.value)} placeholder="reviewer_id" />
            <button type="button" onClick={() => void onAssign()} disabled={terminal || !reviewerId.trim()}>
              担当に割り当て
            </button>
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="レビューコメント（任意）"
            rows={3}
            disabled={terminal}
          />
          <div className="review-decide">
            <button type="button" className="btn-approve" onClick={() => void onReview("approved")} disabled={terminal}>
              承認・公開
            </button>
            <button type="button" className="btn-reject" onClick={() => void onReview("rejected")} disabled={terminal}>
              却下
            </button>
          </div>
        </div>
      </Section>

      <Section title="文書承認">
        <div className="form-grid">
          <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="document_id" />
          <select value={approvalState} onChange={(e) => setApprovalState(e.target.value)}>
            <option value="pending_review">pending_review</option>
            <option value="approved">approved</option>
            <option value="obsolete">obsolete</option>
            <option value="draft">draft</option>
          </select>
          <button type="button" onClick={() => void onApproveDocument()} disabled={!docId.trim()}>
            変更
          </button>
        </div>
      </Section>
      {actionError && <ScreenLoadError error={actionError} />}
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

  useEffect(() => {
    setDrafts(loadDrafts());
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
        <section className="review-queue-panel" aria-label="Drafts">
          <div className="review-queue-head">
            <h3>レビューキュー</h3>
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
          {error && <p className="cv-foot-error">{error}</p>}
        </section>
      </div>
    </>
  );
}

function IngestionRunsBody() {
  const [runId, setRunId] = useState("");
  const [state, setState] = useState<ViewState<ManufacturingIngestionRun>>({ state: "loading" });
  const [uploads, setUploads] = useState<IngestedDoc[]>([]);

  useEffect(() => {
    setUploads(loadIngestedDocs());
  }, []);

  async function lookup(event: FormEvent) {
    event.preventDefault();
    const id = runId.trim();
    if (!id) return;
    setState({ state: "loading" });
    try {
      const data = await runWithToken((token) => manufacturingIngestionRun(id, token));
      setState({ state: "ready", data });
    } catch (err) {
      if (isAuthError(err)) clearSessionToken();
        setState({ state: "error", error: err instanceof Error ? err.message : "リクエストに失敗しました" });
    }
  }

  return (
    <>
      <Section title="実行を確認" note="実行 ID でバックエンドの投影を確認できます。">
        <form className="src-inline-form" onSubmit={lookup}>
          <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="ingestion_run_id" />
          <button type="submit" disabled={!runId.trim()}>
            確認
          </button>
        </form>
      </Section>
      {uploads.length > 0 && (
        <Section title="最近の取込（このブラウザ）" note="アップロードから作成された取込ランです。実行 ID で詳細を確認できます。">
          <DataTable
            columns={["実行 ID", "ドキュメント", "状態", "チャンク", "日時"]}
            rows={uploads.map((doc) => [
              <button
                type="button"
                key={doc.ingestion_run_id}
                className="linklike"
                onClick={() => {
                  setRunId(doc.ingestion_run_id);
                  void runWithToken((token) => manufacturingIngestionRun(doc.ingestion_run_id, token))
                    .then((data) => setState({ state: "ready", data }))
                    .catch((err) =>
                      setState({ state: "error", error: err instanceof Error ? err.message : "参照に失敗しました" }),
                    );
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
      <Section title="サンプル実行" note="テナント全体の一覧 API が来るまでは型付きモックです。">
        <DataTable
          columns={["実行", "ソース", "状態"]}
          rows={[
            ["run-1024", "src-sop", "成功"],
            ["run-2048", "src-press", "実行中"],
            ["run-4096", "src-troubles", "失敗"],
          ]}
          empty="実行はまだありません。"
        />
      </Section>
      {state.state === "loading" && <p className="ops-empty">実行状態を読み込み中…</p>}
      {state.state === "error" && <ScreenLoadError error={state.error} />}
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
  const state = useLoad(
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

  if (state.state === "loading") return <p className="ops-empty">安全テレメトリを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
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
  const state = useLoad(
    async () => {
      const token = await getSessionToken();
      const [kpi, governance] = await Promise.all([manufacturingKpi(token), manufacturingGovernanceStatus(token)]);
      return { kpi, governance };
    },
    [],
  );
  if (state.state === "loading") return <p className="ops-empty">品質データを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
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
    </>
  );
}

function ImprovementQueueBody() {
  const [items, setItems] = useState<ImprovementItem[]>([]);

  useEffect(() => {
    setItems(loadImprovementItems());
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

  return (
    <>
      <p className="src-warning">
        回答への「要改善」フィードバックを集約します。理由ごとに、文書追加・FAQ化・メタデータ修正・再評価につなげてください。
      </p>
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
  const state = useLoad(
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
  if (state.state === "loading") return <p className="ops-empty">出力データを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
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
      <Section title="固定契約">
        <FieldGrid rows={screen.data.map((item, index) => [`data[${index}]`, String(item)])} />
      </Section>
      <Section title="GAP 状態">
        <DataTable
          columns={["メソッド", "パス", "状態"]}
          rows={missingApis(screen).map((api) => [api.method, api.path, api.status])}
          empty="バックエンドの GAP はありません。"
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

const ACCEPT_EXT = ".txt,.md,.markdown,.csv,.html,.htm,.docx,.xlsx";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function AddSourceBody() {
  const [mode, setMode] = useState<"file" | "text">("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [collectionId, setCollectionId] = useState("manuals");
  const [sourceId, setSourceId] = useState("upload");
  const [approvalStatus, setApprovalStatus] = useState("approved");
  const [effectiveDate, setEffectiveDate] = useState(todayIso());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestedDoc | null>(null);

  function onPickFile(picked: File | null) {
    setFile(picked);
    if (picked && !documentId.trim()) {
      setDocumentId(picked.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 80));
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    setResult(null);

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
      // 1) upload to the local sink -> file:// ref the answer-service can read
      const form = new FormData();
      form.append("file", payload);
      const upRes = await fetch("/api/upload", { method: "POST", body: form });
      const up = await upRes.json().catch(() => ({}));
      if (!upRes.ok) throw new Error(up.error ?? "アップロードに失敗しました");

      const docId =
        documentId.trim() ||
        up.filename.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]/g, "-").slice(0, 80) ||
        `doc-${Date.now().toString(36)}`;

      // 2) ingest -> parse / chunk / embed / store
      const token = await getSessionToken();
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
      <p className="src-warning">
        ファイルをアップロードすると、取込ランが作成され、パース・分割・埋め込み・保存まで実行されます。
        承認済みに設定したドキュメントは、その場で「質問する」の正式な根拠になります（PDF は次フェーズ）。
      </p>

      <form className="upload-form" onSubmit={onSubmit}>
        <Section title="ドキュメントを追加" note="対応形式: テキスト / Markdown / HTML / CSV / Word(.docx) / Excel(.xlsx)">
          <div className="upload-mode-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "file"}
              className={`upload-mode-tab ${mode === "file" ? "active" : ""}`}
              onClick={() => setMode("file")}
            >
              ファイル
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "text"}
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
                {file ? `${(file.size / 1024).toFixed(1)} KB` : ".txt / .md / .csv / .html / .docx / .xlsx・最大10MB"}
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

      {error && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>取込メッセージ</h3>
          <p>{error}</p>
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
      <Section title="稼働状況" note="サポート / インシデント API が来るまでは型付きモックです。">
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
  const docs = useLoad(
    async () => manufacturingDocuments(await getSessionToken(), DEMO_COLLECTION),
    [],
  );

  useEffect(() => {
    setUploaded(loadIngestedDocs());
  }, []);

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
        {docs.state === "loading" && <p className="ops-empty">ドキュメントを読み込み中…</p>}
        {docs.state === "error" && <ScreenLoadError error={docs.error} />}
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
            empty="ドキュメントはまだありません。「ソースを追加」から取り込めます。"
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

  useEffect(() => {
    let active = true;
    setState({ state: "loading" });
    runWithToken((token) => apiGetJson(`/admin/documents/${encodeURIComponent(documentId)}/processing-status`, token))
      .then((processing) =>
        active && setState({ state: "ready", data: { processing: processing as Record<string, unknown> } }),
      )
      .catch((err) => {
        if (isAuthError(err)) clearSessionToken();
        if (active) setState({ state: "error", error: err instanceof Error ? err.message : "リクエストに失敗しました" });
      });
    return () => {
      active = false;
    };
  }, [documentId]);

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
      <Section title="ドキュメント詳細" note="詳細 API がないため、実際の処理状態と型付きモックを組み合わせています。">
        <FieldGrid
          rows={[
            ["文書 ID", documentId],
            ["承認状態", "pending_review"],
            ["ソース", "mock-source"],
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
        <textarea value={metadata} onChange={(e) => setMetadata(e.target.value)} rows={8} />
        <div className="screen-actions">
          <button type="button" onClick={() => void onSave()} disabled={saving}>
            メタデータを保存
          </button>
          <button type="button" className="btn-reject" onClick={() => void onDelete()} disabled={saving}>
            文書を削除
          </button>
        </div>
      </Section>
      {state.state === "loading" && <p className="ops-empty">処理状態を読み込み中…</p>}
      {state.state === "error" && <ScreenLoadError error={state.error} />}
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
  const [memo, setMemo] = useState("Review flow is controlled by governance status.");
  const state = useLoad(async () => {
    const token = await getSessionToken();
    return manufacturingGovernanceStatus(token);
  }, []);
  if (state.state === "loading") return <p className="ops-empty">ガバナンス状態を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
  return (
    <>
      <Section title="ガバナンスベースの承認ルール">
        <FieldGrid
          rows={[
            ["AI 出力は常にドラフト", state.data.draft_review.ai_output_always_draft ? "はい" : "いいえ"],
            ["レビュー担当必須", state.data.draft_review.reviewer_required_for_approval ? "はい" : "いいえ"],
            ["高リスクは承認済み引用必須", state.data.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
          ]}
        />
      </Section>
      <Section title="設計メモ">
        <textarea value={memo} onChange={(e) => setMemo(e.target.value)} rows={5} />
        <p className="ops-note">専用の承認ワークフロー API が来るまではモック表示です。</p>
      </Section>
    </>
  );
}

function GenericOpsOverview() {
  const state = useLoad(
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
  if (state.state === "loading") return <p className="ops-empty">運用概要を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
  const telemetryBreakdown =
    state.data.telemetry.block_breakdown ?? state.data.telemetry.safety_gate_block_breakdown ?? {};
  const breakdownEntries = Object.entries(telemetryBreakdown);
  const totalBlocks = breakdownEntries.reduce((sum, [, count]) => sum + Number(count || 0), 0) || 1;
  const coverage = Math.max(0, Math.min(100, Math.round(Number(state.data.governance.policy_version) * 3.1)));
  const expiring = [
    { doc: "WI-0457", expiry: "2026-07-01", days: 9 },
    { doc: "QC-08", expiry: "2026-07-03", days: 11 },
    { doc: "SOP-220", expiry: "2026-07-08", days: 16 },
  ];
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
            <span>{state.data.dashboard.frequently_referenced_documents.length} / {Math.max(1, state.data.dashboard.frequently_referenced_documents.length + 2)} 文書</span>
          </div>
          <div className="standalone-ops-progress">
            <div style={{ width: `${coverage}%` }} />
          </div>
          <div className="standalone-ops-expiring-title">有効期限が近い引用</div>
          <div className="standalone-ops-expiring">
            {expiring.map((item) => (
              <div key={item.doc} className="standalone-ops-expiring-row">
                <div>
                  <div className="standalone-ops-expiring-doc">{item.doc}</div>
                  <div className="standalone-ops-expiring-date">{item.expiry}</div>
                </div>
                <span>{item.days}</span>
              </div>
            ))}
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
            ["高リスクは承認済み引用必須", state.data.governance.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
            ["AI 出力は常にドラフト", state.data.governance.draft_review.ai_output_always_draft ? "はい" : "いいえ"],
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
  const state = useLoad(async () => {
    const token = await getSessionToken();
    return manufacturingAuditExport(token, "dict");
  }, []);
  if (state.state === "loading") return <p className="ops-empty">監査ログを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;

  const records = ((state.data as { records?: AuditRecord[] }).records ?? []) as AuditRecord[];

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
      <Section title="監査イベント" note={`${records.length} 件`}>
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
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} placeholder="質問" />
        <div className="review-assign-row">
          <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user_id" />
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

      {loading && <p className="ops-empty">実行中…</p>}
      {error && <p className="cv-foot-error">{error}</p>}
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
  const state = useLoad(async () => {
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
        {state.state === "loading" && <p className="ops-empty">ACL を読み込み中…</p>}
        {state.state === "error" && <ScreenLoadError error={state.error} />}
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
  allowed_llm_providers?: string[];
  allowed_embedding_providers?: string[];
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
  const state = useLoad(async () => {
    const token = await getSessionToken();
    const [policies, dataUse] = await Promise.all([
      apiGetJson<unknown>("/admin/provider-policies", token),
      manufacturingDataUsePolicy(token),
    ]);
    return { policies, dataUse };
  }, []);
  if (state.state === "loading") return <p className="ops-empty">プロバイダーポリシーを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
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
              ["LLM プロバイダ", (p.allowed_llm_providers ?? []).join(", ") || "—"],
              ["埋め込みプロバイダ", (p.allowed_embedding_providers ?? []).join(", ") || "—"],
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
        <section className="result-panel error-panel">
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

          <Section title="パイプラインと GAP">
            <FieldGrid
              rows={[
                ["パイプライン", "埋め込み → ベクトル候補（ACL事前フィルタ）→ ハイブリッド統合 → ACL再確認 → リランク → top_k → 安全/根拠ゲート → 生成"],
                ["ACL", "deny-by-default・サーバ側強制（候補は許可済みのみ）"],
                ["相関 ID", `search ${result.searchCorrelation || "—"} / answer ${result.answerCorrelation || "—"}`],
                [
                  "未公開（要 explain API）",
                  "ACL適用前の候補・rerank前後スコア・metadataフィルタ内部は、answer-service に explain フラグを追加すると表示できます。",
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
  const state = useLoad(async () => {
    const token = await getSessionToken();
    const [profiles, queries] = await Promise.all([
      apiGetJson("/admin/retrieval-profiles", token),
      apiGetJson("/admin/query-profiles", token),
    ]);
    return { profiles, queries };
  }, []);
  if (state.state === "loading") return <p className="ops-empty">検索設定を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
  return <Section title="検索設定"><pre className="code-block">{JSON.stringify(state.data, null, 2)}</pre></Section>;
}

function LoggingPrivacyBody() {
  const state = useLoad(async () => {
    const token = await getSessionToken();
    const [logging, policy] = await Promise.all([
      apiGetJson<unknown>("/admin/logging-policies", token),
      manufacturingDataUsePolicy(token),
    ]);
    return { logging, policy };
  }, []);
  if (state.state === "loading") return <p className="ops-empty">ログポリシーを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} />;
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
      <Section title="APIキー" note="UI は固定し、バックエンドの面はまだ未実装です。">
        <DataTable columns={["キー", "範囲", "状態"]} rows={[]} empty="APIキーはまだありません。" />
      </Section>
      <Section title="Webhook">
        <p className="ops-empty">Webhook 管理は API が揃うまで型付きモックです。</p>
      </Section>
    </>
  );
}

function BillingBody() {
  return (
    <>
      <Section title="利用状況 / 請求" note="予算 API はありますが、利用状況や請求はまだモックです。">
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
