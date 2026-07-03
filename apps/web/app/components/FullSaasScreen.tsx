"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type {
  AdminDataSource,
  AdminDataSourceOverview,
  ChatAssistantMessage,
  ChatbotSourceExposurePolicy,
  Citation,
  DataSourceMappingProfile,
  DataSourceProfileType,
  DataSourcePreviewResponse,
  FeedbackRecord,
  GovernanceStatus,
  KnowledgeOpsDashboard,
  ManufacturingAnswerResponse,
  ManufacturingDocumentSummary,
  ManufacturingIngestionRun,
  ManufacturingKpi,
  ManufacturingSourceSyncStatus,
  PhoneCallDetailResponse,
  PhoneCallSummaryItem,
  PhoneHandoffPackage,
  PhoneMetricsResponse,
  PhoneQualityEvaluation,
  PhoneScenarioSummary,
  PhoneTurnResponse,
  QualityOperationalResponse,
  SafetyTelemetryView,
  SearchResultItem,
  DraftArtifact,
} from "@raku-rag/shared";
import {
  adminDataSources,
  adminDataSourceOverview,
  adminCitationView,
  adminSourceTestConnection,
  adminSourcePreview,
  adminSourceSync,
  type AdminSourceSyncResponse,
  apiDeleteJson,
  apiGetJson,
  apiPostJson,
  apiPutJson,
  authHeaders,
  chatMetrics,
  chatSourceExposurePolicies,
  createChatSession,
  ingestDocument,
  manufacturingAnswer,
  requestChatHandoff,
  searchChunks,
  sendChatMessage,
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
  manufacturingAuditEvidencePack,
  latestManufacturingQualityEval,
  runManufacturingQualityEval,
  type QualityEvalResult,
  manufacturingRequestSourceSync,
  manufacturingReviewDraft,
  manufacturingSafetyTelemetry,
  manufacturingSourceSyncStatus,
  manufacturingTroubleCaseSearch,
  manufacturingUpdateDocumentMetadata,
  phoneAcceptHandoff,
  phoneCallDetail,
  phoneCreateQualityEvaluation,
  phoneCreateScenario,
  phoneListCalls,
  phoneListQualityEvaluations,
  phoneListScenarios,
  phoneMetrics,
  phonePreviewScenario,
  phoneRollbackScenario,
  phoneScenarioAction,
  phoneSimulateCall,
  phoneSubmitTurn,
  phoneUpsertScenarioVersion,
  listFeedback,
  qualityOperational,
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
  loadSessionRoles,
  mintTokenFor,
  saveAnswerCollection,
} from "../../lib/session";
import {
  APPROVAL_WORKFLOW_ENABLED,
  missingApis,
  type ManifestScreen,
} from "../../lib/full-saas";
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
  clearResolvedImprovementItems,
  FEEDBACK_REASONS,
  loadImprovementItems,
  reasonLabel,
  recordImprovementItem,
  setImprovementStatus,
  type ImprovementItem,
} from "../../lib/improvement-queue";
import { useToast } from "../../lib/toast";

type ViewState<T> =
  | { state: "loading" }
  | { state: "error"; error: string }
  | { state: "ready"; data: T };

type AdminListRow = { id: string; label: string; meta?: string; status?: string };

const CHAT_MARKDOWN_ALLOWED_ELEMENTS = [
  "blockquote",
  "br",
  "code",
  "em",
  "li",
  "ol",
  "p",
  "pre",
  "strong",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
];

/** U1: the answer body additionally renders Bedrock-style `#`/`##` headings and `---` rules. */
const ANSWER_MARKDOWN_ALLOWED_ELEMENTS = [
  ...CHAT_MARKDOWN_ALLOWED_ELEMENTS,
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
];

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
]);

function isSyncActive(status: string | undefined | null): boolean {
  return !!status && SYNC_ACTIVE_STATUSES.has(status);
}

type LoadErrorView = { message: string; detail?: string };

function isAbortError(err: unknown): boolean {
  if (typeof err !== "object" || err === null || !("name" in err)) return false;
  const name = (err as { name?: unknown }).name;
  return name === "AbortError" || name === "TimeoutError";
}

function loadErrorStatus(err: unknown, message: string): number | undefined {
  if (typeof err === "object" && err !== null && "status" in err) {
    const status = (err as { status?: unknown }).status;
    if (typeof status === "number") return status;
  }
  const match = /HTTP (\d{3})/.exec(message);
  return match ? Number(match[1]) : undefined;
}

/** U12: humanize load/submit errors; keep the raw technical detail available for ops. */
function describeLoadError(err: unknown): LoadErrorView {
  if (isAbortError(err)) {
    return { message: "応答がありませんでした。回線状況を確認して再試行してください。" };
  }
  const raw = err instanceof Error ? err.message : "リクエストに失敗しました";
  if (/failed to fetch|networkerror|load failed/i.test(raw)) {
    return { message: "バックエンド API に接続できません。API が起動しているか確認してください。" };
  }
  const status = loadErrorStatus(err, raw);
  if (status === 401) {
    return { message: "認証の有効期限が切れています。再ログインしてください。", detail: raw };
  }
  if (status === 403) {
    return { message: "この操作を行う権限がありません。管理者に確認してください。", detail: raw };
  }
  if (status !== undefined && status >= 500) {
    return {
      message: "サーバーで問題が発生しました。少し待ってからもう一度お試しください。",
      detail: raw,
    };
  }
  return { message: raw };
}

function formatLoadError(err: unknown): string {
  const described = describeLoadError(err);
  return described.detail && described.detail !== described.message
    ? `${described.message}(${described.detail})`
    : described.message;
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

function WorkStat({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "ok" | "wait" | "bad";
}) {
  return (
    <div className={`work-stat ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
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

function compactCitationLabel(citation: { document_id: string; chunk_id?: string | null }): string {
  if (!citation.chunk_id || citation.chunk_id.startsWith(`${citation.document_id}:`)) {
    return citation.document_id;
  }
  return citationLabel(citation);
}

function citationKindLabel(kind?: string | null): string {
  switch (kind) {
    case "visual":
      return "画像";
    case "spreadsheet":
      return "表計算";
    case "table_row":
      return "表";
    case "form_field":
      return "帳票";
    case "chart_series":
      return "グラフ";
    case "figure_caption":
      return "図表";
    default:
      return "文書";
  }
}

function citationLocationLabel(citation: Citation): string | null {
  if (citation.page_number) return `${citation.page_number}ページ`;
  if (citation.sheet_name && citation.cell_range) return `${citation.sheet_name} ${citation.cell_range}`;
  if (citation.sheet_name) return citation.sheet_name;
  if (citation.cell_range) return citation.cell_range;
  if (citation.row_id) return `行 ${citation.row_id}`;
  return null;
}

function citationEffectiveDateLabel(date: string | null | undefined): string | null {
  if (!date) return null;
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return null;
  return `有効日 ${parsed.toLocaleDateString("ja-JP")}`;
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
  | { kind: "error"; id: string; question: string; error: string; detail?: string };

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

/** U12: hard cutoff for one answer generation round-trip (Bedrock can take 2-9s; 60s = stuck). */
const ANSWER_REQUEST_TIMEOUT_MS = 60_000;

const ANSWER_STARTERS = [
  "プレス機の異音が出たときの初動手順を教えて",
  "旧版の手順書を参照してよい条件はありますか",
  "出荷前検査で不一致が出た場合の初動を確認したい",
];

const CHAT_STARTERS = [
  "交換部品の確認手順を案内して",
  "担当者に引き継ぐ前に必要な情報を整理して",
  "承認済みの規格だけで回答して",
];

type ChatReferenceScope = {
  collection_id: string;
  source_count: number;
  last_synced_at?: string;
};

type HistoryStatusFilter = "all" | ManufacturingAnswerResponse["status"];
type HistorySafetyFilter = "all" | "normal" | "blocked" | "high_risk" | "obsolete";

function collectionDisplayName(id?: string | null): string {
  if (!id || id === DEMO_COLLECTION) return "デモナレッジ";
  return id;
}

// U15/U11: the collections the workspace already knows about (same derivation as the Answers screen
// selector: distinct collection_id over the registered datasources). Falls back to the demo
// collection when the list is empty or the API is unreachable, so selects always render an option.
function useKnownCollections(): string[] {
  const [collections, setCollections] = useState<string[]>([DEMO_COLLECTION]);
  useEffect(() => {
    void getSessionToken()
      .then((token) => adminDataSources(token))
      .then((sources) => {
        const ids = [...new Set(sources.map((source) => source.collection_id).filter(Boolean))].sort();
        if (ids.length > 0) {
          setCollections(ids.includes(DEMO_COLLECTION) ? ids : [DEMO_COLLECTION, ...ids]);
        }
      })
      .catch(() => {
        /* keep default collection list */
      });
  }, []);
  return collections;
}

function syncedReferenceScopes(
  sources: AdminDataSource[],
  documents: ManufacturingDocumentSummary[] = [],
  syncStatuses: ManufacturingSourceSyncStatus[] = [],
): ChatReferenceScope[] {
  const scopes = new Map<string, ChatReferenceScope>();
  const sourceKeysByCollection = new Map<string, Set<string>>();
  const sourcesById = new Map(sources.map((source) => [source.source_id, source]));

  function upsertScope(collectionId: string, sourceKey: string, lastSyncedAt?: string | null) {
    if (!collectionId) return;
    const current = scopes.get(collectionId) ?? {
      collection_id: collectionId,
      source_count: 0,
      last_synced_at: lastSyncedAt || undefined,
    };
    const sourceKeys = sourceKeysByCollection.get(collectionId) ?? new Set<string>();
    if (!sourceKeys.has(sourceKey)) {
      sourceKeys.add(sourceKey);
      current.source_count = sourceKeys.size;
    }
    if (lastSyncedAt && (!current.last_synced_at || lastSyncedAt > current.last_synced_at)) {
      current.last_synced_at = lastSyncedAt;
    }
    sourceKeysByCollection.set(collectionId, sourceKeys);
    scopes.set(collectionId, current);
  }

  const documentSources = new Set<string>();
  for (const doc of documents) {
    if (!doc.collection_id) continue;
    const sourceKey = doc.source_id || doc.document_id;
    documentSources.add(`${doc.collection_id}\u0000${doc.source_id}`);
    upsertScope(doc.collection_id, sourceKey);
  }

  const syncedSourceIds = new Set<string>();
  for (const sync of syncStatuses) {
    const source = sourcesById.get(sync.source_id);
    const collectionId = sync.collection_id || source?.collection_id || "";
    if (!collectionId || !sourceSyncHasUsableDocuments(sync)) continue;
    syncedSourceIds.add(sync.source_id);
    upsertScope(collectionId, sync.source_id, sourceSyncLastIndexedAt(sync));
  }

  for (const source of sources) {
    if (!source.collection_id || source.status !== "active") continue;
    if (
      !source.last_synced_at &&
      !documentSources.has(`${source.collection_id}\u0000${source.source_id}`) &&
      !syncedSourceIds.has(source.source_id)
    ) {
      continue;
    }
    upsertScope(source.collection_id, source.source_id, source.last_synced_at);
  }
  return [...scopes.values()].sort((a, b) => a.collection_id.localeCompare(b.collection_id));
}

function sourceSyncHasUsableDocuments(sync: ManufacturingSourceSyncStatus): boolean {
  if (sync.status === "succeeded" || sync.status === "partially_succeeded") return true;
  if ((sync.summary?.observed_count ?? 0) > 0) return true;
  return sync.documents.some((doc) => {
    const indexStatus = typeof doc.index_status === "string" ? doc.index_status : "";
    return doc.status === "succeeded" || indexStatus === "succeeded";
  });
}

function sourceSyncLastIndexedAt(sync: ManufacturingSourceSyncStatus): string | undefined {
  const values = sync.documents
    .map((doc) => {
      const indexed = typeof doc.last_indexed_at === "string" ? doc.last_indexed_at : "";
      return indexed || doc.updated_at || "";
    })
    .filter(Boolean);
  return values.sort().at(-1);
}

function isInternalChatPolicyForCollection(
  policy: ChatbotSourceExposurePolicy,
  collectionId: string,
): boolean {
  const channels = new Set(policy.allowed_channels ?? []);
  const intents = new Set(policy.allowed_intents ?? []);
  return (
    policy.collection_id === collectionId &&
    !policy.source_id &&
    policy.status === "active" &&
    policy.exposure_mode === "internal_authenticated" &&
    (channels.size === 0 || channels.has("web_chat")) &&
    (intents.size === 0 || intents.has("rag_question"))
  );
}

function confidenceLabel(confidence: number | null | undefined): string {
  if (typeof confidence !== "number") return "未算出";
  const value = confidence <= 1 ? Math.round(confidence * 100) : Math.round(confidence);
  return `${value}%`;
}

function chatStateLabel(state: string, hasSession: boolean): string {
  if (!hasSession) return "未開始";
  switch (state) {
    case "idle":
      return "待機中";
    case "handoff_pending":
      return "確認依頼済み";
    case "completed":
      return "完了";
    case "waiting_for_user":
      return "ユーザー確認待ち";
    case "active":
    case "open":
      return "会話中";
    default:
      return "会話中";
  }
}

function chatUsageLabel(
  referenceScopeReady: boolean,
  policyAccess: "loading" | "ready" | "forbidden",
  progress: "thinking" | "checking_rag" | "delayed" | null,
): string {
  if (progress) return chatProgressLabel(progress);
  if (referenceScopeReady) return "質問できます";
  if (policyAccess === "loading") return "参照範囲を確認中";
  if (policyAccess === "forbidden") return "設定確認が必要です";
  return "現在利用できません";
}

function canViewChatbotOps(roles: readonly string[]): boolean {
  const allowed = new Set(["admin", "tenant_admin", "platform_admin", "ops_owner"]);
  return roles.some((role) => allowed.has(role));
}

function chatQuickReplyTone(label: string, value: string): { label: string; cls: string } {
  const text = `${label} ${value}`;
  if (text.includes("手順")) return { label: "手順", cls: "chat-action-procedure" };
  if (text.includes("表") || text.includes("判断基準")) return { label: "表", cls: "chat-action-table" };
  if (text.includes("根拠")) return { label: "根拠", cls: "chat-action-evidence" };
  if (text.includes("注意")) return { label: "注意", cls: "chat-action-warning" };
  return { label: "詳細", cls: "chat-action-detail" };
}

function handoffReasonLabel(reason: string): string {
  if (reason === "customer_requested_human") return "ユーザー依頼";
  return "確認待ち";
}

function AnswerFeedback({ question, answerId }: { question: string; answerId: string }) {
  const [sent, setSent] = useState<null | "up" | "down">(null);
  const [showReasons, setShowReasons] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function sendUp() {
    if (busy || sent) return;
    setBusy(true);
    try {
      const token = await getSessionToken();
      await submitFeedback({ subject: "user", rating: 5, answer_id: answerId || undefined, comment: "answer:helpful" }, token);
      setSent("up");
    } catch (err) {
      toast(err instanceof Error ? err.message : "送信に失敗しました", "error");
    } finally {
      setBusy(false);
    }
  }

  async function sendDown(reasonCode: string) {
    if (busy || sent) return;
    setBusy(true);
    try {
      const token = await getSessionToken();
      await submitFeedback(
        {
          subject: "user",
          rating: 2,
          answer_id: answerId || undefined,
          comment: `answer:needs_improvement reason:${reasonCode}`,
          reason_code: reasonCode,
        },
        token,
      );
      recordImprovementItem({ answer_id: answerId, question, reason: reasonCode });
      setSent("down");
      setShowReasons(false);
    } catch (err) {
      toast(err instanceof Error ? err.message : "送信に失敗しました", "error");
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
      <div className="answer-summary-strip" aria-label="回答の状態">
        <span className={`status-badge status-${r.status}`}>{statusLabel(r.status)}</span>
        <span className="answer-summary-item">安全: {safetyLabel(r)}</span>
        <span className="answer-summary-item">引用 {r.citations.length}件</span>
        <span className="answer-summary-item">確信度 {confidenceLabel(r.confidence)}</span>
      </div>

      {r.text ? (
        <ChatMessageMarkdown
          content={r.text}
          className="answer-text answer-markdown"
          tableWrapClassName="answer-markdown-table-wrap"
          allowedElements={ANSWER_MARKDOWN_ALLOWED_ELEMENTS}
        />
      ) : (
        <p className="answer-text answer-text-muted">
          {blocked
            ? "安全ルールにより、確定した回答を保留しました。承認済みの手順が公開されるまでお待ちください。"
            : insufficient
              ? "承認済みの根拠が不足しているため、断定できません。文書の承認または追加が必要です。"
              : "対応する回答は返されませんでした。"}
        </p>
      )}

      {(blocked || insufficient) && (
        <div className="answer-next-actions" aria-label="次の操作">
          <strong>{blocked ? "確定回答を保留しました" : "承認済み根拠が不足しています"}</strong>
          <span>
            {APPROVAL_WORKFLOW_ENABLED
              ? "必要な文書を承認するか、参照できる根拠を追加してから再質問してください。"
              : "参照できる根拠を追加または再同期してから再質問してください。"}
          </span>
          <div>
            {APPROVAL_WORKFLOW_ENABLED && (
              <Link className="citation-open" href="/reviews/documents">根拠文書レビュー</Link>
            )}
            <Link className="citation-open" href="/sources/list">外部接続を確認</Link>
            <Link className="citation-open" href="/documents">ドキュメントを確認</Link>
          </div>
        </div>
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
                    <details className="citation-diagnostics">
                      <summary>診断情報</summary>
                      <span>
                        {citation.source_id} · v{citation.version} · スコア {citation.retrieval_score.toFixed(3)}
                      </span>
                    </details>
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

      {r.correlation_id && (
        <details className="answer-diagnostics">
          <summary>回答IDを表示</summary>
          <span>{r.correlation_id}</span>
        </details>
      )}

      <AnswerFeedback question={turn.question} answerId={r.correlation_id} />
    </section>
  );
}

/** U2: staged generating-answer card (mirrors the chatbot's ChatThinkingBubble treatment). */
const ANSWER_THINKING_STAGES = {
  thinking: { title: "回答を生成中", detail: "質問の意図を整理しています。" },
  checking_rag: {
    title: "承認済みナレッジを照合しています",
    detail: "根拠となる引用候補を確認しています。",
  },
  delayed: {
    title: "回答の生成に時間がかかっています",
    detail: "混み合っている可能性があります。このままお待ちください(最大60秒)。",
  },
} as const;

function AnswerThinkingCard() {
  const [stage, setStage] = useState<keyof typeof ANSWER_THINKING_STAGES>("thinking");

  useEffect(() => {
    const checking = setTimeout(() => setStage("checking_rag"), 450);
    const delayed = setTimeout(() => setStage("delayed"), 5000);
    return () => {
      clearTimeout(checking);
      clearTimeout(delayed);
    };
  }, []);

  const copy = ANSWER_THINKING_STAGES[stage];
  return (
    <section className="answer-card answer-thinking-card" role="status" aria-live="polite">
      <div className="answer-thinking-copy">
        <strong>{copy.title}</strong>
        <span>{copy.detail}</span>
      </div>
      <div className="answer-thinking-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
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
  // 再質問 auto-submit guard (survives StrictMode double-effect; one auto-submit per mount).
  const autoSubmittedRef = useRef(false);

  useEffect(() => {
    const savedCollection = loadAnswerCollection();
    setCollectionId(savedCollection);
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const initialQuestion = params.get("q");
      if (initialQuestion) {
        if (params.get("submit") === "1" && !autoSubmittedRef.current) {
          // History 再質問: submit immediately instead of only pre-filling the composer.
          autoSubmittedRef.current = true;
          // Drop the params so a reload does not re-submit the same question.
          window.history.replaceState(null, "", window.location.pathname);
          void submitQuestion(initialQuestion, savedCollection);
        } else {
          setQuery(initialQuestion);
        }
      }
    }
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

  async function submitQuestion(question: string, collectionOverride?: string) {
    const trimmed = question.trim();
    if (!trimmed || loading) return;
    const targetCollection = (collectionOverride ?? collectionId).trim() || DEMO_COLLECTION;

    const turnId = `${Date.now().toString(36)}-${turns.length}`;
    setTurns((prev) => [...prev, { kind: "user", id: `${turnId}-q`, text: trimmed }]);
    setLoading(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), ANSWER_REQUEST_TIMEOUT_MS);
    try {
      const token = await getSessionToken();
      const response = await manufacturingAnswer(
        { query: trimmed, collection_id: targetCollection },
        token,
        controller.signal,
      );
      recordAnswer(trimmed, response, targetCollection);
      setTurns((prev) => [...prev, { kind: "answer", id: `${turnId}-a`, question: trimmed, response }]);
    } catch (err) {
      if (isAuthError(err)) clearSessionToken();
      const described = describeLoadError(err);
      setTurns((prev) => [
        ...prev,
        {
          kind: "error",
          id: `${turnId}-e`,
          question: trimmed,
          error: described.message,
          detail: described.detail,
        },
      ]);
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setQuery("");
    await submitQuestion(trimmed);
  }

  return (
    <>
      <p className="src-warning">承認済みソースだけを参照し、危険度や旧版参照を明示して回答します。</p>
      <div className="answers-thread">
        {turns.length === 0 && !loading && (
          <div className="answer-empty-state answer-empty-state-rich">
            <div className="answer-empty-mark" aria-hidden="true" />
            <div className="answer-empty-copy">
              <strong>承認済みナレッジに質問する</strong>
              <span>
                現場手順、規格、トラブル対応を横断し、根拠不足や安全保留も回答内で明示します。
              </span>
              <div className="answer-starter-list" aria-label="質問例">
                {ANSWER_STARTERS.map((starter) => (
                  <button key={starter} type="button" onClick={() => setQuery(starter)}>
                    {starter}
                  </button>
                ))}
              </div>
            </div>
            <div className="answer-empty-meta" aria-label="現在の参照範囲">
              <span>参照範囲</span>
              <strong>{collectionDisplayName(collectionId)}</strong>
              <small>回答後はこのブラウザの履歴に保存されます。</small>
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
                {turn.detail && <p className="error-detail">詳細: {turn.detail}</p>}
                <div>
                  <button
                    type="button"
                    className="citation-open"
                    disabled={loading}
                    onClick={() => void submitQuestion(turn.question)}
                  >
                    再試行
                  </button>
                </div>
              </section>
            );
          }
          return <AnswerPanel key={turn.id} turn={turn} onOpenCitation={setViewer} />;
        })}

        {loading && <AnswerThinkingCard />}
      </div>

      <form className="answers-composer" onSubmit={onAsk}>
        <div className="answers-composer-meta">
          <label className="answers-collection-field">
            <span>参照範囲</span>
            <select
              aria-label="回答の参照範囲"
              value={collectionId}
              onChange={(event) => onCollectionChange(event.target.value)}
            >
              {collections.map((id) => (
                <option key={id} value={id}>
                  {collectionDisplayName(id)}
                </option>
              ))}
            </select>
          </label>
          <Link className="composer-meta-link" href="/answers/history">回答履歴</Link>
        </div>
        <div className="answers-composer-inner">
          <textarea
            aria-label="質問内容"
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

type ChatTurn =
  | { kind: "user"; id: string; text: string }
  | {
      kind: "assistant";
      id: string;
      message: ChatAssistantMessage;
      ragStatus?: string | null;
      handoffReason?: string | null;
      handoffPackageId?: string | null;
      ticketId?: string | null;
    }
  | { kind: "error"; id: string; text: string };

function chatProgressLabel(state: "thinking" | "checking_rag" | "delayed"): string {
  if (state === "checking_rag") return "根拠を確認しています";
  if (state === "delayed") return "少し時間がかかっています";
  return "返答を準備しています";
}

function chatActionLabel(action?: string | null): string {
  switch (action) {
    case "collect_slot":
      return "確認中";
    case "answer_with_citations":
      return "回答";
    case "confirm_action":
      return "最終確認";
    case "ticket_created":
      return "受付作成";
    case "handoff":
      return "確認依頼";
    default:
      return action || "応答";
  }
}

function chatPrimaryBadge(action?: string | null, ragStatus?: string | null): { label: string; cls: string } {
  if (action === "handoff") return { label: "担当者確認", cls: "chat-badge-handoff" };
  if (action === "ticket_created") return { label: "受付作成", cls: "chat-badge-handoff" };
  if (ragStatus === "ok") return { label: "根拠確認済み", cls: "chat-badge-evidence-ok" };
  if (ragStatus === "insufficient_evidence") return { label: "根拠不足", cls: "chat-badge-evidence-warn" };
  if (ragStatus === "budget_exceeded") return { label: "予算上限", cls: "chat-badge-evidence-warn" };
  if (action === "collect_slot") return { label: "確認中", cls: "chat-badge-neutral" };
  if (action === "confirm_action") return { label: "最終確認", cls: "chat-badge-neutral" };
  return { label: chatActionLabel(action), cls: "chat-badge-neutral" };
}

function chatProgressDetail(state: "thinking" | "checking_rag" | "delayed"): string {
  if (state === "checking_rag") return "承認済みナレッジと引用候補を照合しています。";
  if (state === "delayed") return "確認に時間がかかっています。必要なら担当者に確認依頼できます。";
  return "質問の意図を整理しています。";
}

function ChatThinkingBubble({
  state,
  onHandoff,
  handoffQueued,
  handoffRequested,
}: {
  state: "thinking" | "checking_rag" | "delayed";
  onHandoff: () => void;
  handoffQueued: boolean;
  handoffRequested: boolean;
}) {
  const handoffButtonLabel = handoffRequested
    ? "確認依頼済み"
    : handoffQueued
      ? "回答後に確認依頼します"
      : "担当者に確認依頼";
  return (
    <article className="chat-bot-bubble chat-thinking-bubble">
      <div role="status" aria-live="polite">
        <div className="chat-thinking-head">
          <span className="chat-bot-avatar" aria-hidden="true">AI</span>
          <div className="chat-thinking-copy">
            <strong>{chatProgressLabel(state)}</strong>
            <span>{chatProgressDetail(state)}</span>
          </div>
        </div>
        <div className="chat-thinking-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
      {state === "delayed" && (
        <button
          type="button"
          className="citation-open"
          onClick={onHandoff}
          disabled={handoffQueued || handoffRequested}
        >
          {handoffButtonLabel}
        </button>
      )}
    </article>
  );
}

function ChatMessageMarkdown({
  content,
  className = "chat-markdown",
  tableWrapClassName = "chat-markdown-table-wrap",
  allowedElements = CHAT_MARKDOWN_ALLOWED_ELEMENTS,
}: {
  content: string;
  className?: string;
  tableWrapClassName?: string;
  allowedElements?: string[];
}) {
  return (
    <div className={className}>
      <ReactMarkdown
        allowedElements={allowedElements}
        remarkPlugins={[remarkGfm]}
        skipHtml
        unwrapDisallowed
        components={{
          table: ({ node: _node, ...props }) => (
            <div className={tableWrapClassName}>
              <table {...props} />
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ChatEvidencePanel({
  message,
  onOpenCitation,
}: {
  message: ChatAssistantMessage;
  onOpenCitation: (target: CitationViewTarget) => void;
}) {
  if (message.citations.length === 0) return null;
  return (
    <section className="chat-evidence-panel" aria-label="参照した根拠">
      <div className="chat-evidence-head">
        <div>
          <span>参照した根拠</span>
          <strong>{message.citations.length}件</strong>
        </div>
        <small>回答に使った承認済みナレッジ</small>
      </div>
      <div className="chat-evidence-list">
        {message.citations.map((citation, index) => {
          const approval = citeApproval(citation.approval_status);
          const location = citationLocationLabel(citation);
          const effectiveDate = citationEffectiveDateLabel(citation.effective_date);
          return (
            <button
              key={`${citation.document_id}-${citation.chunk_id ?? index}`}
              type="button"
              className="chat-evidence-card"
              onClick={() =>
                onOpenCitation({
                  citation,
                  answerId: message.message_id,
                  groundedText: message.message,
                  index: index + 1,
                })
              }
              aria-label={`根拠${index + 1}を開く: ${compactCitationLabel(citation)}`}
            >
              <span className="chat-evidence-index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="chat-evidence-main">
                <span className="chat-evidence-title">{compactCitationLabel(citation)}</span>
                <span className="chat-evidence-meta">
                  {[citationKindLabel(citation.kind), location, effectiveDate]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <span className={`chat-evidence-state ${approval.cls}`}>{approval.label}</span>
              <span className="chat-evidence-open">該当箇所</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ChatQuickReplyActions({
  message,
  onQuickReply,
}: {
  message: ChatAssistantMessage;
  onQuickReply: (label: string, value: string) => void;
}) {
  if (message.quick_replies.length === 0) return null;
  return (
    <div className="chat-actions-panel" aria-label="次の見方">
      <span className="chat-actions-label">次の見方</span>
      <div className="chat-quick-replies">
        {message.quick_replies.map((reply) => {
          const tone = chatQuickReplyTone(reply.label, reply.value);
          return (
            <button
              key={`${message.message_id}-${reply.value}`}
              type="button"
              className={`chat-action-chip ${tone.cls}`}
              onClick={() => onQuickReply(reply.label, reply.value)}
              aria-label={`${reply.label}で回答を見直す`}
            >
              <span>{tone.label}</span>
              {reply.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ChatAssistantBubble({
  turn,
  onQuickReply,
  onOpenCitation,
}: {
  turn: Extract<ChatTurn, { kind: "assistant" }>;
  onQuickReply: (label: string, value: string) => void;
  onOpenCitation: (target: CitationViewTarget) => void;
}) {
  const message = turn.message;
  const primaryBadge = chatPrimaryBadge(message.ai_action, turn.ragStatus);
  return (
    <article className="chat-bot-bubble">
      <div className="chat-bubble-head">
        <span className={`chat-answer-badge ${primaryBadge.cls}`}>{primaryBadge.label}</span>
        {turn.ticketId && <span className="chat-answer-badge chat-badge-neutral">受付 {turn.ticketId}</span>}
        {turn.handoffPackageId && <span className="chat-answer-badge chat-badge-handoff">確認依頼 {turn.handoffPackageId}</span>}
        {turn.handoffReason && <span className="chat-answer-badge chat-badge-evidence-warn">{handoffReasonLabel(turn.handoffReason)}</span>}
      </div>
      <ChatMessageMarkdown content={message.message} />

      <ChatEvidencePanel message={message} onOpenCitation={onOpenCitation} />
      <ChatQuickReplyActions message={message} onQuickReply={onQuickReply} />
    </article>
  );
}

function ChatBotBody() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [collectionId, setCollectionId] = useState(DEMO_COLLECTION);
  const [referenceScopes, setReferenceScopes] = useState<ChatReferenceScope[]>([]);
  const [sourcePolicies, setSourcePolicies] = useState<ChatbotSourceExposurePolicy[]>([]);
  const [policyAccess, setPolicyAccess] = useState<"loading" | "ready" | "forbidden">("loading");
  const [setupError, setSetupError] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [stateSummary, setStateSummary] = useState("idle");
  const [progress, setProgress] = useState<"thinking" | "checking_rag" | "delayed" | null>(null);
  const [handoffQueued, setHandoffQueued] = useState(false);
  const [loading, setLoading] = useState(false);
  const [viewer, setViewer] = useState<CitationViewTarget | null>(null);
  const [metrics, setMetrics] = useState<{ conversation_count: number; handoff_rate: number } | null>(null);
  const thinkingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const delayTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingHandoffAfterResponse = useRef(false);
  const sessionRoles = useMemo(() => loadSessionRoles(), []);
  const showOpsInfo = canViewChatbotOps(sessionRoles);
  const selectedScope = referenceScopes.find((scope) => scope.collection_id === collectionId) ?? null;
  const selectedPolicy = sourcePolicies.find((policy) =>
    isInternalChatPolicyForCollection(policy, collectionId),
  ) ?? null;
  const referenceScopeReady = policyAccess === "ready" && Boolean(selectedScope && selectedPolicy);
  const usageLabel = chatUsageLabel(referenceScopeReady, policyAccess, progress);
  const handoffRequested = stateSummary === "handoff_pending";
  const handoffLabel = handoffRequested
    ? "確認依頼済み"
    : handoffQueued
      ? "回答後に確認依頼します"
      : "必要時に確認依頼できます";
  const syncedDataLabel = selectedScope
    ? `同期済みデータ ${selectedScope.source_count}件`
    : "利用できるナレッジを確認できません";
  const referenceFallbackLabel =
    policyAccess === "loading" ? "参照範囲を確認中" : "現在利用できません";
  const referenceStatusText =
    setupError ??
    (referenceScopeReady
      ? `${collectionDisplayName(collectionId)} を参照して回答します。`
      : policyAccess === "loading"
        ? "参照範囲を確認しています。"
        : "現在このチャットは利用できません。管理者に確認してください。");

  useEffect(() => {
    setCollectionId(loadAnswerCollection());
    void getSessionToken()
      .then(async (token) => {
        const [sources, documents, policyResponse, metricResponse] = await Promise.all([
          adminDataSources(token).catch(() => [] as AdminDataSource[]),
          manufacturingDocuments(token).catch(() => [] as ManufacturingDocumentSummary[]),
          chatSourceExposurePolicies(token).catch(() => null),
          showOpsInfo ? chatMetrics(token).catch(() => null) : Promise.resolve(null),
        ]);
        const syncStatuses = await Promise.all(
          sources.map((source) =>
            manufacturingSourceSyncStatus(source.source_id, token).catch(
              () => null as ManufacturingSourceSyncStatus | null,
            ),
          ),
        );
        const scopes = syncedReferenceScopes(
          sources,
          documents,
          syncStatuses.filter((sync): sync is ManufacturingSourceSyncStatus => Boolean(sync)),
        );
        setReferenceScopes(scopes);
        setCollectionId((current) => {
          const saved = current || DEMO_COLLECTION;
          if (scopes.some((scope) => scope.collection_id === saved)) return saved;
          if (!scopes[0]) return saved;
          saveAnswerCollection(scopes[0].collection_id);
          return scopes[0].collection_id;
        });
        if (policyResponse) {
          setSourcePolicies(policyResponse.items ?? []);
          setPolicyAccess("ready");
        } else {
          setPolicyAccess("forbidden");
        }
        if (metricResponse) {
          setMetrics({
            conversation_count: metricResponse.summary.conversation_count,
            handoff_rate: metricResponse.summary.handoff_rate,
          });
        }
      })
      .catch(() => {
        /* keep default */
      });
    return () => {
      if (thinkingTimer.current) clearTimeout(thinkingTimer.current);
      if (delayTimer.current) clearTimeout(delayTimer.current);
    };
  }, [showOpsInfo]);

  function onCollectionChange(value: string) {
    setCollectionId(value);
    setSetupError(null);
    saveAnswerCollection(value);
  }

  function onNewConversation() {
    if (loading) return;
    setSessionId(null);
    setInput("");
    setTurns([]);
    setStateSummary("idle");
    setProgress(null);
    setHandoffQueued(false);
    pendingHandoffAfterResponse.current = false;
    if (thinkingTimer.current) clearTimeout(thinkingTimer.current);
    if (delayTimer.current) clearTimeout(delayTimer.current);
  }

  function beginRequest() {
    setLoading(true);
    setProgress("thinking");
    if (thinkingTimer.current) clearTimeout(thinkingTimer.current);
    if (delayTimer.current) clearTimeout(delayTimer.current);
    thinkingTimer.current = setTimeout(() => setProgress("checking_rag"), 450);
    delayTimer.current = setTimeout(() => setProgress("delayed"), 2200);
  }

  function endRequest() {
    setLoading(false);
    setProgress(null);
    if (thinkingTimer.current) clearTimeout(thinkingTimer.current);
    if (delayTimer.current) clearTimeout(delayTimer.current);
  }

  function appendAssistant(
    message: ChatAssistantMessage | undefined,
    extra: {
      ragStatus?: string | null;
      handoffReason?: string | null;
      handoffPackageId?: string | null;
      ticketId?: string | null;
    } = {},
  ) {
    if (!message) return;
    setTurns((prev) => [
      ...prev,
      {
        kind: "assistant",
        id: message.message_id,
        message,
        ragStatus: extra.ragStatus,
        handoffReason: extra.handoffReason,
        handoffPackageId: extra.handoffPackageId,
        ticketId: extra.ticketId,
      },
    ]);
  }

  async function requestHandoffForSession(targetSessionId: string, token: string) {
    const response = await requestChatHandoff(
      targetSessionId,
      { reason: "customer_requested_human", comment: "UI confirmation request" },
      token,
    );
    pendingHandoffAfterResponse.current = false;
    setHandoffQueued(false);
    setStateSummary("handoff_pending");
    appendAssistant({
      message_id: `handoff-${response.handoff_package_id}`,
      message: `確認依頼を受け付けました。受付ID: ${response.handoff_package_id}。担当者が会話内容と根拠を確認します。`,
      message_type: "text",
      ai_action: "handoff",
      quick_replies: [],
      citations: [],
    }, {
      handoffReason: response.reason,
      handoffPackageId: response.handoff_package_id,
    });
  }

  async function submitText(
    text: string,
    displayText = text,
    options: { allowWithoutReferenceScope?: boolean } = {},
  ) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    if (!referenceScopeReady && !options.allowWithoutReferenceScope) {
      setSetupError("現在このチャットは利用できません。管理者に確認してください。");
      return;
    }
    const turnId = `${Date.now().toString(36)}-${turns.length}`;
    setTurns((prev) => [...prev, { kind: "user", id: `${turnId}-u`, text: displayText }]);
    setInput("");
    beginRequest();
    try {
      const token = await getSessionToken();
      let activeSessionId = sessionId;
      let handoffAlreadyCreated = false;
      if (!sessionId) {
        const response = await createChatSession(
          { channel: "web_chat", initial_message: trimmed, collection_id: collectionId },
          token,
        );
        activeSessionId = response.session_id;
        setSessionId(response.session_id);
        setStateSummary(response.state?.status ?? response.status);
        handoffAlreadyCreated = Boolean(response.handoff?.handoff_package_id)
          || (response.state?.status ?? response.status) === "handoff_pending";
        if (handoffAlreadyCreated) {
          pendingHandoffAfterResponse.current = false;
          setHandoffQueued(false);
        }
        appendAssistant(response.assistant_message, {
          ragStatus: response.rag?.status,
          handoffReason: response.handoff?.reason,
          handoffPackageId: response.handoff?.handoff_package_id,
          ticketId: response.ticket?.ticket_id,
        });
      } else {
        const response = await sendChatMessage(
          sessionId,
          { message: trimmed, collection_id: collectionId, stream: false },
          token,
        );
        setStateSummary(response.state.status);
        handoffAlreadyCreated = Boolean(response.handoff?.handoff_package_id)
          || response.state.status === "handoff_pending";
        if (handoffAlreadyCreated) {
          pendingHandoffAfterResponse.current = false;
          setHandoffQueued(false);
        }
        appendAssistant(response.assistant_message, {
          ragStatus: response.rag?.status,
          handoffReason: response.handoff?.reason,
          handoffPackageId: response.handoff?.handoff_package_id,
          ticketId: response.ticket?.ticket_id,
        });
      }
      void chatMetrics(token).then((metricResponse) => {
        setMetrics({
          conversation_count: metricResponse.summary.conversation_count,
          handoff_rate: metricResponse.summary.handoff_rate,
        });
      }).catch(() => undefined);
      if (pendingHandoffAfterResponse.current && activeSessionId && !handoffAlreadyCreated) {
        await requestHandoffForSession(activeSessionId, token);
      }
    } catch (err) {
      if (isAuthError(err)) {
        clearSessionToken();
        redirectToLoginAfterAuthError();
      }
      setTurns((prev) => [
        ...prev,
        { kind: "error", id: `${turnId}-e`, text: formatLoadError(err) },
      ]);
      pendingHandoffAfterResponse.current = false;
      setHandoffQueued(false);
    } finally {
      endRequest();
    }
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    await submitText(input);
  }

  async function onHandoff() {
    if (handoffRequested || handoffQueued) return;
    if (loading) {
      pendingHandoffAfterResponse.current = true;
      setHandoffQueued(true);
      return;
    }
    if (!sessionId) {
      await submitText("担当者に確認依頼したい", "担当者に確認依頼したい", {
        allowWithoutReferenceScope: true,
      });
      return;
    }
    beginRequest();
    try {
      const token = await getSessionToken();
      await requestHandoffForSession(sessionId, token);
    } catch (err) {
      pendingHandoffAfterResponse.current = false;
      setHandoffQueued(false);
      setTurns((prev) => [...prev, { kind: "error", id: `handoff-${Date.now()}`, text: formatLoadError(err) }]);
    } finally {
      endRequest();
    }
  }

  function onQuickReply(label: string, value: string) {
    if (value === "handoff") {
      void onHandoff();
      return;
    }
    void submitText(value, label);
  }

  return (
    <>
      <div className="chatbot-layout">
        <section className="chatbot-main" aria-label="ChatBot 会話">
          <div className="chatbot-thread" aria-busy={loading}>
            {turns.length === 0 && !loading && (
              <div className="answer-empty-state answer-empty-state-rich">
                <div className="answer-empty-mark" aria-hidden="true" />
                <div className="answer-empty-copy">
                  <strong>根拠付きチャットを開始する</strong>
                  <span>
                    参照範囲内の承認済みナレッジを使い、回答できない内容は担当者への確認依頼につなげます。
                  </span>
                  <div className="answer-starter-list" aria-label="会話の開始例">
                    {CHAT_STARTERS.map((starter) => (
                      <button
                        key={starter}
                        type="button"
                        onClick={() => void submitText(starter)}
                        disabled={!referenceScopeReady || loading}
                      >
                        {starter}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="answer-empty-meta" aria-label="チャットボットの参照範囲">
                  <span>利用状態</span>
                  <strong>{collectionDisplayName(collectionId)}</strong>
                  <small>{referenceScopeReady ? "質問できます" : "現在利用できません"}</small>
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
                    <h3>送信に失敗しました</h3>
                    <p>{turn.text}</p>
                  </section>
                );
              }
              return (
                <ChatAssistantBubble
                  key={turn.id}
                  turn={turn}
                  onQuickReply={onQuickReply}
                  onOpenCitation={setViewer}
                />
              );
            })}

            {progress && (
              <ChatThinkingBubble
                state={progress}
                onHandoff={() => void onHandoff()}
                handoffQueued={handoffQueued}
                handoffRequested={handoffRequested}
              />
            )}
          </div>

          <form className="answers-composer" onSubmit={onSend}>
            <div className="answers-composer-meta">
              <label className="answers-collection-field">
                <span>参照範囲</span>
                <select
                  aria-label="チャットボットの参照範囲"
                  value={collectionId}
                  onChange={(event) => onCollectionChange(event.target.value)}
                  disabled={referenceScopes.length === 0 || loading}
                >
                  {referenceScopes.length === 0 && <option value={collectionId}>{referenceFallbackLabel}</option>}
                  {referenceScopes.map((scope) => (
                    <option key={scope.collection_id} value={scope.collection_id}>
                      {scope.collection_id}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="citation-open" onClick={onNewConversation} disabled={loading}>
                新しい会話
              </button>
            </div>
            <p
              id="chatbot-reference-help"
              className={referenceScopeReady ? "chatbot-reference-status ready" : "chatbot-reference-status"}
              role={setupError ? "alert" : "status"}
              aria-live="polite"
            >
              {referenceStatusText}
            </p>
            <div className="answers-composer-inner">
              <textarea
                aria-label="チャットメッセージ"
                aria-describedby="chatbot-reference-help"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitText(input);
                  }
                }}
                placeholder={referenceScopeReady ? "相談内容を入力する…" : "現在このチャットは利用できません"}
                rows={1}
                disabled={!referenceScopeReady || loading}
              />
              <button type="submit" disabled={loading || !referenceScopeReady || input.trim().length === 0}>
                {loading ? "送信中" : "送信"}
              </button>
            </div>
          </form>
        </section>

        <aside className="chatbot-side" aria-label="チャットボットの状態">
          <section
            className="chatbot-conversation-status chatbot-side-section"
            aria-labelledby="chatbot-current-state-title"
          >
            <div className="chatbot-side-head">
              <strong id="chatbot-current-state-title">この会話</strong>
              <span>利用状態と回答の前提</span>
            </div>
            <div className="chatbot-state-row chatbot-state-row-primary">
              <span>利用状態</span>
              <strong
                className={referenceScopeReady ? "chatbot-status-ready" : "chatbot-status-waiting"}
              >
                {usageLabel}
              </strong>
            </div>
            <div className="chatbot-state-row">
              <span>参照範囲</span>
              <strong>{collectionDisplayName(collectionId)}</strong>
            </div>
            <div className="chatbot-state-row">
              <span>ナレッジ</span>
              <strong>{syncedDataLabel}</strong>
            </div>
            <div className="chatbot-state-row">
              <span>根拠</span>
              <strong>承認済みデータのみ使用</strong>
            </div>
            <div className="chatbot-state-row">
              <span>確認依頼</span>
              <strong>{handoffLabel}</strong>
            </div>
          </section>

          {showOpsInfo && (metrics || sessionId || stateSummary !== "idle") && (
            <details className="chatbot-ops-details">
              <summary>運用情報</summary>
              <div className="chatbot-ops-grid">
                {metrics && (
                  <>
                    <div className="chatbot-state-row">
                      <span>会話数</span>
                      <strong>{metrics.conversation_count}</strong>
                    </div>
                    <div className="chatbot-state-row">
                      <span>確認依頼率</span>
                      <strong>{Math.round(metrics.handoff_rate * 100)}%</strong>
                    </div>
                  </>
                )}
                <div className="chatbot-state-row">
                  <span>セッション</span>
                  <strong>{sessionId ? "開始済み" : "未開始"}</strong>
                </div>
                <div className="chatbot-state-row">
                  <span>内部状態</span>
                  <strong>{chatStateLabel(stateSummary, Boolean(sessionId))}</strong>
                </div>
                {(sessionId || stateSummary !== "idle") && (
                  <div className="chatbot-diagnostics">
                    <span>session: {sessionId ?? "none"}</span>
                    <span>state: {stateSummary}</span>
                  </div>
                )}
              </div>
            </details>
          )}
        </aside>
      </div>
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
            placeholder="症状・キーワードで検索する（例: 主軸の異音、圧力低下）…"
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
                  {typeof match.relevance_score === "number" && (
                    <output title="関連度スコア（運用診断用）">{match.relevance_score.toFixed(3)}</output>
                  )}
                </div>
                <div className="ops-flags">
                  {match.equipment_id && <span className="citation-chip">設備 {match.equipment_id}</span>}
                  {match.process_id && <span className="citation-chip">工程 {match.process_id}</span>}
                  <span className="citation-chip">事例 {match.trouble_case_id}</span>
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
        <details className="source-ops-details">
          <summary>運用診断（上級者向け）</summary>
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
            <h3>取込履歴</h3>
            <form className="src-inline-form" onSubmit={onRun}>
              <input value={runId} onChange={(e) => setRunId(e.target.value)} placeholder="run_id" aria-label="実行 ID" autoComplete="off" />
              <button type="submit">確認</button>
            </form>
            {runError && <p className="ops-note">{runError}</p>}
            {run && <FieldGrid rows={[["実行 ID", run.ingestion_run_id], ["状態", run.status], ["ソース", run.source_id ?? "—"]]} />}
          </section>
        </details>
      </aside>
    </div>
  );
}

// --- 022-ai-phone-rag: 電話AI対応 (T038 simulator / T049 handoff queue / T061 scenarios) --------

type PhoneChatLine = { caller: string | null; turn: PhoneTurnResponse; at: string };

// 024 L030 — browser voice mode (Web Speech API): zero-cost voice UX on the existing
// simulate/turn API. Recognition/synthesis stay entirely in the browser (FR-L09).
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  continuous: boolean;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

function speechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function speechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

function phoneActionLabel(action: string | null | undefined): string {
  const labels: Record<string, string> = {
    answer_with_citations: "根拠付き回答",
    ask_clarification: "聞き返し",
    handoff: "人間へ転送",
    fallback: "フォールバック",
    end_call: "終話",
  };
  return action ? labels[action] ?? action : "-";
}

// U5: single label registry for every enum the phone flow exposes. Value sets mirror the
// backend contracts (packages/shared/src/dto/phone.ts + src/raku_rag/phone/domain.py
// HANDOFF_REASONS / handoff.py destination_for). Unknown values fall through raw so new
// backend codes stay visible instead of silently mislabeled.
const PHONE_LABELS: Record<string, Record<string, string>> = {
  callState: {
    ringing: "着信中",
    active: "対応中",
    on_hold: "保留中",
    handoff_pending: "転送待ち",
    transferred: "転送済み",
    completed: "完了",
    abandoned: "放棄",
    failed: "失敗",
  },
  handoffReason: {
    customer_requested_human: "お客様が人間対応を希望",
    insufficient_evidence: "根拠不足",
    low_asr_confidence: "音声認識の信頼度不足",
    repeated_misunderstanding: "聞き取り不成立の繰り返し",
    negative_sentiment: "ネガティブな感情",
    high_risk_intent: "高リスクな問い合わせ",
    identity_required: "本人確認が必要",
    provider_failure: "外部サービス障害",
    ai_capability_boundary: "AI対応範囲外",
  },
  handoffStatus: {
    created: "作成済み",
    queued: "キュー投入済み",
    accepted: "受理済み",
    failed: "失敗",
    unavailable: "対応者不在",
    abandoned: "放棄",
    callback_requested: "折り返し希望",
  },
  resolutionStatus: {
    resolved: "解決",
    transferred: "転送済み",
    abandoned: "放棄",
    failed: "失敗",
    unresolved: "未解決",
  },
  scenarioStatus: {
    draft: "下書き",
    in_review: "レビュー中",
    approved: "承認済み",
    scheduled: "公開予約",
    published: "公開中",
    archived: "アーカイブ",
  },
  destinationType: {
    queue: "キュー",
  },
  destinationQueue: {
    "general-support": "総合サポート",
    "billing-support": "請求サポート",
    escalation: "エスカレーション",
    "order-support": "注文サポート",
  },
  priority: {
    low: "低",
    normal: "通常",
    high: "高",
    urgent: "緊急",
  },
};

function phoneLabel(kind: keyof typeof PHONE_LABELS, value: string | null | undefined): string {
  if (!value) return "-";
  return PHONE_LABELS[kind][value] ?? value;
}

/** HH:MM stamp captured client-side when a simulator turn is exchanged (the live turn
 *  payload carries no created_at — only the stored transcript does). */
function phoneTurnTime(): string {
  return new Date().toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function PhoneBody() {
  const [tab, setTab] = useState<"simulator" | "handoffs" | "calls" | "kpi" | "scenarios">(
    "simulator",
  );
  return (
    <>
      <div className="screen-tabs" role="tablist" aria-label="電話AIの機能">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "simulator"}
          onClick={() => setTab("simulator")}
        >
          通話シミュレータ
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "handoffs"}
          onClick={() => setTab("handoffs")}
        >
          転送キュー
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "calls"}
          onClick={() => setTab("calls")}
        >
          通話履歴
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "kpi"}
          onClick={() => setTab("kpi")}
        >
          KPI
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "scenarios"}
          onClick={() => setTab("scenarios")}
        >
          シナリオ管理
        </button>
      </div>
      {tab === "simulator" && <PhoneSimulatorSection />}
      {tab === "handoffs" && <PhoneHandoffSection />}
      {tab === "calls" && <PhoneCallHistorySection />}
      {tab === "kpi" && <PhoneKpiSection />}
      {tab === "scenarios" && <PhoneScenarioSection />}
    </>
  );
}

function PhoneSimulatorSection() {
  const toast = useToast();
  const [callId, setCallId] = useState<string | null>(null);
  const [callState, setCallState] = useState<string>("idle");
  const [lines, setLines] = useState<PhoneChatLine[]>([]);
  const [input, setInput] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [scenarios, setScenarios] = useState<PhoneScenarioSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [voiceMode, setVoiceMode] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const voiceModeRef = useRef(false);
  // Browsers only allow microphone capture in a secure context (HTTPS or localhost); on plain
  // HTTP the Web Speech APIs exist but recognition.start() is rejected — surface WHY instead of
  // rendering a button that silently fails.
  const voiceSecureContext = useMemo(
    () => typeof window === "undefined" || window.isSecureContext !== false,
    [],
  );
  const voiceSupported = useMemo(
    () => speechRecognitionCtor() !== null && speechSynthesisSupported() && voiceSecureContext,
    [voiceSecureContext],
  );

  useEffect(() => {
    void getSessionToken()
      .then((token) => phoneListScenarios(token))
      .then((response) => setScenarios(response.items.filter((s) => s.status === "published")))
      .catch(() => {
        /* scenario list is optional for the simulator */
      });
    return () => {
      recognitionRef.current?.abort();
      if (speechSynthesisSupported()) window.speechSynthesis.cancel();
    };
  }, []);

  const terminal = ["transferred", "completed", "abandoned", "failed"].includes(callState);

  function speakTurn(turn: PhoneTurnResponse | null | undefined) {
    if (!turn || !voiceModeRef.current || !speechSynthesisSupported()) return;
    const text = turn.speech_text || turn.ai_response_text || "";
    if (!text) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ja-JP";
    utterance.onend = () => {
      // Conversational loop: after the AI finishes speaking, listen again — unless the
      // call ended or was handed off to a human.
      const state = turn.call_state;
      const done = ["transferred", "completed", "abandoned", "failed", "handoff_pending"].includes(
        String(state),
      );
      if (voiceModeRef.current && !done) startListening();
    };
    window.speechSynthesis.speak(utterance);
  }

  function startListening() {
    const Ctor = speechRecognitionCtor();
    if (!Ctor || recognitionRef.current) return;
    // Barge-in equivalent: the mic opening cancels any ongoing synthesis.
    if (speechSynthesisSupported()) window.speechSynthesis.cancel();
    const recognition = new Ctor();
    recognition.lang = "ja-JP";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim() ?? "";
      if (transcript) void send(transcript);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setListening(false);
    };
    recognition.onerror = (event) => {
      recognitionRef.current = null;
      setListening(false);
      if (event.error && event.error !== "no-speech" && event.error !== "aborted") {
        toast(`音声認識エラー: ${event.error}`, "error");
      }
    };
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  function stopVoice() {
    recognitionRef.current?.abort();
    recognitionRef.current = null;
    setListening(false);
    if (speechSynthesisSupported()) window.speechSynthesis.cancel();
  }

  function toggleVoiceMode() {
    const next = !voiceMode;
    setVoiceMode(next);
    voiceModeRef.current = next;
    if (!next) stopVoice();
  }

  async function send(text: string, eventType: "speech" | "hangup" = "speech") {
    if (loading) return;
    if (eventType === "speech" && !text.trim()) return;
    setLoading(true);
    try {
      const token = await getSessionToken();
      const collectionId = loadAnswerCollection() || DEMO_COLLECTION;
      if (!callId) {
        const response = await phoneSimulateCall(
          {
            caller: { phone_number: "+81300000000", customer_id: "cust_demo" },
            scenario_id: scenarioId || undefined,
            collection_id: collectionId,
            utterances: [{ type: eventType, text }],
          },
          token,
        );
        setCallId(response.call_id);
        setCallState(response.status);
        const at = phoneTurnTime();
        // The caller utterance opened the call once — attach it to the first AI turn only.
        setLines(response.turns.map((turn, index) => ({ caller: index === 0 ? text : null, turn, at })));
        speakTurn(response.turns[response.turns.length - 1]);
      } else {
        const turn = await phoneSubmitTurn(
          callId,
          { event_type: eventType, text, collection_id: collectionId },
          token,
        );
        setCallState(turn.call_state);
        setLines((current) => [
          ...current,
          { caller: eventType === "speech" ? text : null, turn, at: phoneTurnTime() },
        ]);
        speakTurn(turn);
      }
      setInput("");
    } catch (err) {
      toast(err instanceof Error ? err.message : "通話処理に失敗しました", "error");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setCallId(null);
    setCallState("idle");
    setLines([]);
    setInput("");
  }

  return (
    <>
      <Section
        title="通話シミュレータ"
        note="決定論的なテレフォニーシミュレータで着信を再現し、承認済みナレッジに基づく応答・聞き返し・人間転送を確認できます。実回線には接続しません。"
      >
        <div className="screen-actions">
          <label>
            シナリオ:{" "}
            <select value={scenarioId} onChange={(event) => setScenarioId(event.target.value)} disabled={Boolean(callId)}>
              <option value="">（シナリオなし）</option>
              {scenarios.map((scenario) => (
                <option key={scenario.scenario_id} value={scenario.scenario_id}>
                  {scenario.name}
                </option>
              ))}
            </select>
          </label>
          <span title={callId ? `${callState}（${callId}）` : "idle"}>
            通話状態: <strong>{callId ? phoneLabel("callState", callState) : "未開始"}</strong>
            {callId && <small className="phone-call-id">{callId}</small>}
          </span>
          {callId && (
            <button type="button" onClick={reset}>
              新しい通話
            </button>
          )}
        </div>
        <div className="screen-actions">
          <input
            type="text"
            value={input}
            placeholder="顧客の発話（例: 営業時間を教えてください）"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void send(input);
            }}
            disabled={loading || terminal}
            style={{ minWidth: "24rem" }}
          />
          <button type="button" onClick={() => void send(input)} disabled={loading || terminal}>
            {callId ? "発話を送信" : "通話を開始"}
          </button>
          <button
            type="button"
            onClick={() => void send("人につないでください")}
            disabled={loading || terminal}
          >
            人につないで
          </button>
          <button type="button" onClick={() => void send("", "hangup")} disabled={loading || !callId || terminal}>
            終話
          </button>
        </div>
        <div className="screen-actions">
          <button
            type="button"
            onClick={toggleVoiceMode}
            disabled={!voiceSupported}
            title={
              voiceSupported
                ? "マイクで話し、音声で回答を聞きます(ブラウザ内で完結)"
                : !voiceSecureContext
                  ? "マイクはHTTPS接続でのみ利用できます(現在はHTTP接続のためブラウザがマイクをブロックします)"
                  : "このブラウザは音声認識に対応していません(Chrome推奨)"
            }
            aria-pressed={voiceMode}
          >
            {voiceMode ? "音声モード: ON" : "音声モード: OFF"}
          </button>
          {!voiceSupported && (
            <span role="status">
              {!voiceSecureContext
                ? "音声モードはHTTPS接続でのみ利用できます(HTTP接続ではブラウザがマイクをブロックします)"
                : "このブラウザは音声認識に対応していません(Chrome推奨)"}
            </span>
          )}
          {voiceMode && (
            <button
              type="button"
              onClick={() => (listening ? stopVoice() : startListening())}
              disabled={loading || terminal}
            >
              {listening ? (
                "聞き取り中…(停止)"
              ) : (
                <>
                  {/* No mic glyph exists in the app's ad-hoc inline-SVG set; the emoji stays as the
                      visual, hidden from screen readers (the label text carries the meaning). */}
                  <span aria-hidden="true">🎤</span> マイクで話す
                </>
              )}
            </button>
          )}
          {voiceMode && (
            <span role="status" aria-live="polite">
              {listening ? "どうぞお話しください" : "回答は音声でも読み上げられます"}
            </span>
          )}
        </div>
      </Section>
      <Section title="会話ログ">
        {lines.length === 0 && <p className="ops-empty">まだ通話がありません。発話を送信してください。</p>}
        {lines.length > 0 && (
          <div className="phone-transcript" role="log" aria-label="通話トランスクリプト">
            {lines.map(({ caller, turn, at }) => (
              <Fragment key={turn.turn_id}>
                {caller && (
                  <div className="phone-transcript-row phone-transcript-row-caller">
                    <div className="phone-transcript-bubble phone-transcript-caller">
                      <div className="phone-transcript-meta">
                        <span className="phone-transcript-chip">顧客</span>
                        <span className="phone-transcript-time">{at}</span>
                      </div>
                      <p>{caller}</p>
                    </div>
                  </div>
                )}
                <div className="phone-transcript-row phone-transcript-row-ai">
                  <div className="phone-transcript-bubble phone-transcript-ai">
                    <div className="phone-transcript-meta">
                      <span className="phone-transcript-chip">AI</span>
                      <span className="chat-answer-badge chat-badge-neutral">
                        {phoneActionLabel(turn.ai_action)}
                      </span>
                      <span className="phone-transcript-time">{at}</span>
                    </div>
                    <p>{turn.ai_response_text}</p>
                    {turn.citations.length > 0 && (
                      <div className="phone-transcript-citations" aria-label="回答の根拠">
                        <span className="phone-transcript-citations-label">根拠</span>
                        {turn.citations.map((citation) => {
                          const approval = citeApproval(citation.approval_status);
                          return (
                            <span
                              key={`${citation.document_id}-${citation.chunk_id}`}
                              className="phone-transcript-citation"
                              title={`チャンク: ${citation.chunk_id} / 検索スコア: ${citation.retrieval_score.toFixed(2)}`}
                            >
                              {citation.document_id}
                              <span className={`chat-evidence-state ${approval.cls}`}>{approval.label}</span>
                            </span>
                          );
                        })}
                      </div>
                    )}
                    {turn.handoff && (
                      <p
                        className="phone-transcript-note"
                        role="status"
                        title={`${turn.handoff.destination_id} / ${turn.handoff.reason} / ${turn.handoff.status}`}
                      >
                        「{phoneLabel("handoffReason", turn.handoff.reason)}」のため
                        {phoneLabel("destinationQueue", turn.handoff.destination_id)}
                        {phoneLabel("destinationType", turn.handoff.destination_type)}へ転送
                        （{phoneLabel("handoffStatus", turn.handoff.status)}）
                      </p>
                    )}
                    {!turn.safety.answered_with_evidence && turn.safety.blocked_reason && (
                      <p className="phone-transcript-note">根拠判定: {turn.safety.blocked_reason}</p>
                    )}
                  </div>
                </div>
              </Fragment>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}

function PhoneHandoffSection() {
  const toast = useToast();
  const [selected, setSelected] = useState<PhoneHandoffPackage | null>(null);
  const [confirmAccept, setConfirmAccept] = useState<PhoneHandoffPackage | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    const calls = await phoneListCalls(token);
    return calls.items.filter((item) => item.handoff_required);
  }, []);

  async function open(item: PhoneCallSummaryItem) {
    try {
      const token = await getSessionToken();
      const detail = await phoneCallDetail(item.call_id, token);
      setSelected(detail.handoff);
    } catch (err) {
      toast(err instanceof Error ? err.message : "転送内容の取得に失敗しました", "error");
    }
  }

  async function accept(handoff: PhoneHandoffPackage) {
    setAccepting(true);
    try {
      const token = await getSessionToken();
      const result = await phoneAcceptHandoff(
        handoff.handoff_package_id,
        { operator_id: "workspace-operator" },
        token,
      );
      setSelected({ ...handoff, status: result.status, accepted_at: result.accepted_at });
      toast("転送を受理しました", "success");
      reload();
    } catch (err) {
      toast(err instanceof Error ? err.message : "転送の受理に失敗しました", "error");
    } finally {
      setAccepting(false);
      setConfirmAccept(null);
    }
  }

  if (state.state === "loading") return <p className="ops-empty" role="status">転送キューを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return (
    <>
      <Section title="転送キュー" note="AIが人間対応へ切り替えた通話の一覧です。行を選択すると引き継ぎ内容を確認できます。">
        <DataTable
          columns={["通話ID", "意図", "転送理由", "通話状態", ""]}
          rows={state.data.map((item) => [
            item.call_id,
            item.intent ?? "-",
            <span key={`reason-${item.call_id}`} title={item.handoff_reason ?? undefined}>
              {phoneLabel("handoffReason", item.handoff_reason)}
            </span>,
            <span key={`state-${item.call_id}`} title={item.state}>
              {phoneLabel("callState", item.state)}
            </span>,
            <button key={item.call_id} type="button" onClick={() => void open(item)}>
              引き継ぎを見る
            </button>,
          ])}
          empty="転送された通話はまだありません。"
        />
      </Section>
      {selected && (
        <Section title={`引き継ぎパッケージ ${selected.handoff_package_id}`}>
          <FieldGrid
            rows={[
              ["状態", <span key="status" title={selected.status}>{phoneLabel("handoffStatus", selected.status)}</span>],
              ["理由", <span key="reason" title={selected.reason}>{phoneLabel("handoffReason", selected.reason)}</span>],
              ["優先度", <span key="priority" title={selected.priority}>{phoneLabel("priority", selected.priority)}</span>],
              [
                "転送先",
                <span key="destination" title={`${selected.destination_type}: ${selected.destination_id}`}>
                  {phoneLabel("destinationQueue", selected.destination_id)}
                  {phoneLabel("destinationType", selected.destination_type)}
                </span>,
              ],
              ["顧客", `${selected.customer.customer_id ?? "-"} / ${selected.customer.phone_number_masked ?? "-"}`],
              ["感情", selected.sentiment ?? "-"],
              ["要約", selected.summary],
              ["推奨アクション", selected.recommended_next_action ?? "-"],
            ]}
          />
          <Section title="会話抜粋（マスク済み）">
            <pre style={{ whiteSpace: "pre-wrap" }}>{selected.transcript_excerpt_redacted}</pre>
          </Section>
          {selected.citations.length > 0 && (
            <DataTable
              columns={["根拠文書", "チャンク", "承認状態"]}
              rows={selected.citations.map((citation) => [
                citation.document_id,
                citation.chunk_id,
                <span key={`${citation.document_id}-${citation.chunk_id}`} title={citation.approval_status ?? undefined}>
                  {citeApproval(citation.approval_status).label}
                </span>,
              ])}
              empty="引用はありません。"
            />
          )}
          <div className="screen-actions">
            <button
              type="button"
              onClick={() => setConfirmAccept(selected)}
              disabled={selected.status === "accepted" || accepting}
            >
              {selected.status === "accepted" ? "受理済み" : "この転送を受理する"}
            </button>
          </div>
        </Section>
      )}
      {confirmAccept && (
        <ConfirmDialog
          title="この転送を受理しますか？"
          body="受理すると担当（workspace-operator）が割り当てられ、以降の対応はその担当が引き継ぎます。"
          confirmLabel="受理する"
          busy={accepting}
          onCancel={() => setConfirmAccept(null)}
          onConfirm={() => void accept(confirmAccept)}
        />
      )}
    </>
  );
}

// --- 022 US4: 通話履歴の検索・詳細・QAレビュー ---------------------------------------------------

const PHONE_STATE_OPTIONS = [
  ["", "すべて"],
  ["completed", "完了"],
  ["transferred", "転送済み"],
  ["abandoned", "放棄"],
  ["handoff_pending", "転送待ち"],
  ["active", "対応中"],
  ["failed", "失敗"],
] as const;

function PhoneCallHistorySection() {
  const toast = useToast();
  const [filters, setFilters] = useState({ from: "", to: "", phone_number: "", intent: "", state: "" });
  const [applied, setApplied] = useState<Record<string, string>>({});
  const [detail, setDetail] = useState<PhoneCallDetailResponse | null>(null);
  const [evaluations, setEvaluations] = useState<PhoneQualityEvaluation[]>([]);
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    return phoneListCalls(token, applied);
  }, [applied]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(filters)) {
      if (value.trim()) next[key] = value.trim();
    }
    setDetail(null);
    setApplied(next);
  }

  async function open(item: PhoneCallSummaryItem) {
    try {
      const token = await getSessionToken();
      const [callDetail, evals] = await Promise.all([
        phoneCallDetail(item.call_id, token),
        phoneListQualityEvaluations(item.call_id, token).catch(() => null),
      ]);
      setDetail(callDetail);
      setEvaluations(evals?.items ?? []);
    } catch (err) {
      toast(err instanceof Error ? err.message : "通話詳細の取得に失敗しました", "error");
    }
  }

  if (state.state === "loading") return <p className="ops-empty" role="status">通話履歴を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return (
    <>
      <Section
        title="通話履歴"
        note="期間・電話番号(下4桁)・意図・状態で絞り込めます。行を選択すると全文文字起こしとQAレビューを確認できます。"
      >
        <form className="src-inline-form" onSubmit={applyFilters} aria-label="通話履歴の絞り込み">
          <input
            type="date"
            value={filters.from}
            onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))}
            aria-label="開始日"
          />
          <input
            type="date"
            value={filters.to}
            onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))}
            aria-label="終了日"
          />
          <input
            value={filters.phone_number}
            onChange={(e) => setFilters((f) => ({ ...f, phone_number: e.target.value }))}
            placeholder="電話番号(下4桁)"
            aria-label="電話番号"
            autoComplete="off"
          />
          <input
            value={filters.intent}
            onChange={(e) => setFilters((f) => ({ ...f, intent: e.target.value }))}
            placeholder="意図"
            aria-label="意図"
            autoComplete="off"
          />
          <select
            value={filters.state}
            onChange={(e) => setFilters((f) => ({ ...f, state: e.target.value }))}
            aria-label="通話状態"
          >
            {PHONE_STATE_OPTIONS.map(([value, label]) => (
              <option key={value || "all"} value={value}>
                {label}
              </option>
            ))}
          </select>
          <button type="submit">検索</button>
        </form>
        <DataTable
          columns={["開始", "通話ID", "発信者", "意図", "状態", "解決", ""]}
          rows={state.data.items.map((item) => [
            item.started_at.replace("T", " ").slice(0, 16),
            item.call_id,
            item.caller_phone_number_masked ?? "-",
            item.intent ?? "-",
            <span key={`state-${item.call_id}`} title={item.state}>
              {phoneLabel("callState", item.state)}
            </span>,
            <span key={`resolution-${item.call_id}`} title={item.resolution_status ?? undefined}>
              {phoneLabel("resolutionStatus", item.resolution_status)}
            </span>,
            <button key={item.call_id} type="button" onClick={() => void open(item)}>
              詳細
            </button>,
          ])}
          empty="条件に一致する通話はありません。"
        />
      </Section>
      {detail && (
        <>
          <Section title={`通話 ${detail.call_id}`}>
            <FieldGrid
              rows={[
                ["状態", <span key="state" title={detail.state}>{phoneLabel("callState", detail.state)}</span>],
                ["開始", detail.started_at],
                ["終了", detail.ended_at ?? "-"],
                ["発信者", detail.caller_phone_number_masked ?? "-"],
                ["意図", detail.intent ?? "-"],
                ["要約", detail.summary || "-"],
                [
                  "解決状態",
                  <span key="resolution" title={detail.resolution_status ?? undefined}>
                    {phoneLabel("resolutionStatus", detail.resolution_status)}
                  </span>,
                ],
                ["録音", detail.recording_enabled ? "有効" : "無効"],
                ["マスキング", detail.transcript_redaction_status],
              ]}
            />
            <DataTable
              columns={["#", "話者", "発話（マスク済み）", "AI判断"]}
              rows={detail.transcript.map((turn) => [
                String(turn.sequence_no),
                turn.speaker,
                turn.redacted_text ?? "-",
                phoneActionLabel(turn.ai_action),
              ])}
              empty="発話はありません。"
            />
          </Section>
          <PhoneQualityReviewSection
            callId={detail.call_id}
            evaluations={evaluations}
            onCreated={(created) => setEvaluations((prev) => [...prev, created])}
          />
        </>
      )}
    </>
  );
}

function PhoneQualityReviewSection({
  callId,
  evaluations,
  onCreated,
}: {
  callId: string;
  evaluations: PhoneQualityEvaluation[];
  onCreated: (created: PhoneQualityEvaluation) => void;
}) {
  const toast = useToast();
  const [scores, setScores] = useState({ answer_correctness: "", tone_score: "", handoff_appropriateness: "" });
  const [flags, setFlags] = useState({ hallucination_detected: false, compliance_issue: false, privacy_issue: false });
  const [suggestedFix, setSuggestedFix] = useState("");
  const [gapTopics, setGapTopics] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const token = await getSessionToken();
      const created = await phoneCreateQualityEvaluation(
        callId,
        {
          answer_correctness: scores.answer_correctness ? Number(scores.answer_correctness) : null,
          tone_score: scores.tone_score ? Number(scores.tone_score) : null,
          handoff_appropriateness: scores.handoff_appropriateness
            ? Number(scores.handoff_appropriateness)
            : null,
          ...flags,
          suggested_fix: suggestedFix.trim() || undefined,
          knowledge_gap_topics: gapTopics
            .split(/[、,]/)
            .map((topic) => topic.trim())
            .filter(Boolean),
        },
        token,
      );
      onCreated(created);
      setScores({ answer_correctness: "", tone_score: "", handoff_appropriateness: "" });
      setFlags({ hallucination_detected: false, compliance_issue: false, privacy_issue: false });
      setSuggestedFix("");
      setGapTopics("");
      toast(
        created.improvement_item_id
          ? `QAレビューを記録し、改善キューに追加しました（${created.improvement_item_id}）`
          : "QAレビューを記録しました",
        "success",
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "QAレビューの記録に失敗しました", "error");
    } finally {
      setSubmitting(false);
    }
  }

  const scoreSelect = (
    label: string,
    key: keyof typeof scores,
  ) => (
    <label className="history-filter-field">
      <span>{label}</span>
      <select
        value={scores[key]}
        onChange={(e) => setScores((s) => ({ ...s, [key]: e.target.value }))}
        aria-label={label}
      >
        <option value="">未評価</option>
        {[1, 2, 3, 4, 5].map((n) => (
          <option key={n} value={String(n)}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <Section
      title="QAレビュー"
      note="1〜5で評価します。ハルシネーション/ナレッジ不足を記録すると改善キューに自動連携されます。"
    >
      {evaluations.length > 0 && (
        <DataTable
          columns={["レビュー日時", "担当", "正確性", "トーン", "転送妥当性", "フラグ", "改善キュー"]}
          rows={evaluations.map((ev) => [
            ev.reviewed_at.replace("T", " ").slice(0, 16),
            ev.reviewer_id,
            ev.answer_correctness != null ? String(ev.answer_correctness) : "-",
            ev.tone_score != null ? String(ev.tone_score) : "-",
            ev.handoff_appropriateness != null ? String(ev.handoff_appropriateness) : "-",
            [
              ev.hallucination_detected ? "ハルシネーション" : null,
              ev.compliance_issue ? "コンプライアンス" : null,
              ev.privacy_issue ? "プライバシー" : null,
            ]
              .filter(Boolean)
              .join(" / ") || "-",
            ev.improvement_item_id ?? "-",
          ])}
          empty=""
        />
      )}
      <form onSubmit={submit} aria-label="QAレビューを記録">
        <div className="screen-actions">
          {scoreSelect("回答の正確性", "answer_correctness")}
          {scoreSelect("トーン", "tone_score")}
          {scoreSelect("転送の妥当性", "handoff_appropriateness")}
        </div>
        <div className="screen-actions">
          <label>
            <input
              type="checkbox"
              checked={flags.hallucination_detected}
              onChange={(e) => setFlags((f) => ({ ...f, hallucination_detected: e.target.checked }))}
            />
            ハルシネーションあり
          </label>
          <label>
            <input
              type="checkbox"
              checked={flags.compliance_issue}
              onChange={(e) => setFlags((f) => ({ ...f, compliance_issue: e.target.checked }))}
            />
            コンプライアンス問題
          </label>
          <label>
            <input
              type="checkbox"
              checked={flags.privacy_issue}
              onChange={(e) => setFlags((f) => ({ ...f, privacy_issue: e.target.checked }))}
            />
            プライバシー問題
          </label>
        </div>
        <div className="src-inline-form">
          <input
            value={suggestedFix}
            onChange={(e) => setSuggestedFix(e.target.value)}
            placeholder="改善提案（例: 返金条件FAQを追加）"
            aria-label="改善提案"
            autoComplete="off"
          />
          <input
            value={gapTopics}
            onChange={(e) => setGapTopics(e.target.value)}
            placeholder="不足トピック（カンマ区切り）"
            aria-label="不足トピック"
            autoComplete="off"
          />
          <button type="submit" disabled={submitting}>
            {submitting ? "記録中…" : "レビューを記録"}
          </button>
        </div>
      </form>
    </Section>
  );
}

// --- 022 US5: 電話KPI（応答率・AI完結率・転送率・レイテンシ・ナレッジギャップ） -------------------

function PhoneKpiSection() {
  const [range, setRange] = useState({ from: "", to: "" });
  const [applied, setApplied] = useState<Record<string, string>>({});
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    return phoneMetrics(token, applied);
  }, [applied]);

  function applyRange(event: FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (range.from) next.from = range.from;
    if (range.to) next.to = range.to;
    setApplied(next);
  }

  if (state.state === "loading") return <p className="ops-empty" role="status">KPIを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const metrics = state.data;
  const seconds = metrics.summary.average_handle_time_seconds;
  return (
    <>
      <Section title="電話KPI" note="通話履歴とQAレビューから集計した運用指標です。">
        <form className="src-inline-form" onSubmit={applyRange} aria-label="KPI集計期間">
          <input
            type="date"
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            aria-label="集計開始日"
          />
          <input
            type="date"
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            aria-label="集計終了日"
          />
          <button type="submit">集計</button>
        </form>
        <div className="metric-grid">
          <Stat label="通話数" value={String(metrics.summary.call_count)} />
          <Stat label="応答率" value={pct(metrics.summary.answer_rate)} />
          <Stat label="AI完結率" value={pct(metrics.summary.ai_containment_rate)} />
          <Stat label="転送率" value={pct(metrics.summary.handoff_rate)} />
        </div>
        <FieldGrid
          rows={[
            ["未解決率", pct(metrics.summary.unresolved_rate)],
            ["平均処理時間", seconds ? `${seconds.toFixed(1)} 秒` : "-"],
            [
              "ターン応答 p95",
              metrics.summary.p95_total_turn_latency_ms != null
                ? `${Math.round(metrics.summary.p95_total_turn_latency_ms)} ms`
                : "-",
            ],
            [
              "RAG検索 p95",
              metrics.summary.p95_rag_latency_ms != null
                ? `${Math.round(metrics.summary.p95_rag_latency_ms)} ms`
                : "-",
            ],
          ]}
        />
      </Section>
      <Section title="転送理由 上位">
        <DataTable
          columns={["理由", "件数"]}
          rows={metrics.top_handoff_reasons.map((pair) => [pair.key, String(pair.count)])}
          empty="転送はまだありません。"
        />
      </Section>
      <Section title="問い合わせ意図 上位">
        <DataTable
          columns={["意図", "件数"]}
          rows={metrics.top_intents.map((pair) => [pair.key, String(pair.count)])}
          empty="意図の記録はまだありません。"
        />
      </Section>
      <Section
        title="ナレッジギャップ"
        note="QAレビューで「不足トピック」として記録された内容です。ナレッジ整備の優先度判断に使えます。"
      >
        <DataTable
          columns={["トピック", "件数"]}
          rows={metrics.knowledge_gap_topics.map((pair) => [pair.key, String(pair.count)])}
          empty="記録されたナレッジギャップはありません。"
        />
      </Section>
    </>
  );
}

const PHONE_SCENARIO_ACTION_LABEL: Record<string, string> = {
  "submit-review": "レビュー依頼",
  approve: "承認",
  publish: "公開",
  archive: "アーカイブ",
};

function PhoneScenarioSection() {
  const toast = useToast();
  const [name, setName] = useState("");
  const [intent, setIntent] = useState("faq");
  const [versionId, setVersionId] = useState("scv_1");
  const [previewText, setPreviewText] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  // U16: publish/rollback change what live callers hear — both go through ConfirmDialog.
  const [confirmAction, setConfirmAction] = useState<{
    kind: "publish" | "rollback";
    scenario: PhoneScenarioSummary;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [state, reload] = useLoad(async () => {
    const token = await getSessionToken();
    return (await phoneListScenarios(token)).items;
  }, []);

  async function run(action: () => Promise<unknown>, success: string) {
    try {
      await action();
      toast(success, "success");
      reload();
    } catch (err) {
      toast(err instanceof Error ? err.message : "操作に失敗しました", "error");
    }
  }

  async function create() {
    if (!name.trim()) return;
    await run(async () => {
      const token = await getSessionToken();
      await phoneCreateScenario({ name, intent }, token);
      setName("");
    }, "シナリオを作成しました（下書き版 scv_1 が用意されます）");
  }

  async function lifecycle(
    scenarioId: string,
    action: "submit-review" | "approve" | "publish" | "archive",
  ) {
    await run(async () => {
      const token = await getSessionToken();
      await phoneScenarioAction(scenarioId, versionId, action, {}, token);
    }, `${PHONE_SCENARIO_ACTION_LABEL[action] ?? action}を実行しました`);
  }

  async function rollback(scenarioId: string) {
    await run(async () => {
      const token = await getSessionToken();
      await phoneRollbackScenario(scenarioId, versionId, token);
    }, "ロールバックを実行しました");
  }

  async function runConfirmedAction() {
    if (!confirmAction) return;
    setConfirmBusy(true);
    try {
      if (confirmAction.kind === "publish") {
        await lifecycle(confirmAction.scenario.scenario_id, "publish");
      } else {
        await rollback(confirmAction.scenario.scenario_id);
      }
    } finally {
      setConfirmBusy(false);
      setConfirmAction(null);
    }
  }

  async function ensureDefaults(scenarioId: string) {
    await run(async () => {
      const token = await getSessionToken();
      await phoneUpsertScenarioVersion(
        scenarioId,
        versionId,
        {
          handoff_conditions: [
            { reason: "customer_requested_human", enabled: true },
            { reason: "insufficient_evidence", enabled: true },
          ],
          fallback_message: "確認して担当者におつなぎします。",
        },
        token,
      );
    }, "下書き版を更新しました");
  }

  async function runPreview(scenarioId: string) {
    if (!previewText.trim()) return;
    try {
      const token = await getSessionToken();
      const result = await phonePreviewScenario(
        scenarioId,
        versionId,
        { utterances: [previewText] },
        token,
      );
      const first = result.turns[0];
      setPreview(
        `${phoneActionLabel(first?.ai_action)}: ${first?.ai_response_text ?? "-"}${
          result.would_handoff ? "（転送が発生します）" : ""
        }`,
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "プレビューに失敗しました", "error");
    }
  }

  if (state.state === "loading") return <p className="ops-empty" role="status">シナリオを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  return (
    <>
      <Section
        title="シナリオ管理"
        note="公開には承認者による明示的な承認が必要です（下書き→レビュー→承認→公開）。公開済みの版は変更できず、ロールバックは対象版を参照する新しい版を公開します。ナレッジ自体の承認は既存の文書承認フローを共用します。"
      >
        <div className="screen-actions">
          <input
            type="text"
            value={name}
            placeholder="シナリオ名（例: FAQ基本対応）"
            onChange={(event) => setName(event.target.value)}
          />
          <select value={intent} onChange={(event) => setIntent(event.target.value)}>
            <option value="faq">FAQ</option>
            <option value="business_hours">営業時間</option>
            <option value="pricing_plan">料金・プラン</option>
            <option value="reservation_order_status">予約・注文状況</option>
            <option value="document_request">資料請求</option>
            <option value="department_routing">部署取次</option>
          </select>
          <button type="button" onClick={() => void create()}>
            シナリオを作成
          </button>
          <label>
            対象版:{" "}
            <input
              type="text"
              value={versionId}
              onChange={(event) => setVersionId(event.target.value)}
              style={{ width: "6rem" }}
            />
          </label>
        </div>
        <DataTable
          columns={["シナリオ", "意図", "状態", "公開中の版", "操作"]}
          rows={state.data.map((scenario) => [
            scenario.name,
            scenario.intent,
            <span key={`status-${scenario.scenario_id}`} title={scenario.status}>
              {phoneLabel("scenarioStatus", scenario.status)}
            </span>,
            scenario.active_version_id ?? "-",
            <span key={scenario.scenario_id} className="screen-actions">
              <button type="button" onClick={() => void ensureDefaults(scenario.scenario_id)}>
                下書き更新
              </button>
              <button type="button" onClick={() => void lifecycle(scenario.scenario_id, "submit-review")}>
                レビュー依頼
              </button>
              <button type="button" onClick={() => void lifecycle(scenario.scenario_id, "approve")}>
                承認
              </button>
              <button type="button" onClick={() => setConfirmAction({ kind: "publish", scenario })}>
                公開
              </button>
              <button type="button" onClick={() => setConfirmAction({ kind: "rollback", scenario })}>
                ロールバック
              </button>
              <button type="button" onClick={() => void runPreview(scenario.scenario_id)}>
                プレビュー
              </button>
            </span>,
          ])}
          empty="シナリオはまだありません。"
        />
        <div className="screen-actions">
          <input
            type="text"
            value={previewText}
            placeholder="プレビュー発話（例: 営業時間を教えてください）"
            onChange={(event) => setPreviewText(event.target.value)}
            style={{ minWidth: "20rem" }}
          />
        </div>
        {preview && <p role="status">プレビュー結果 — {preview}</p>}
      </Section>
      {confirmAction && (
        <ConfirmDialog
          title={
            confirmAction.kind === "publish"
              ? `シナリオ「${confirmAction.scenario.name}」を公開しますか？`
              : `シナリオ「${confirmAction.scenario.name}」をロールバックしますか？`
          }
          body={
            confirmAction.kind === "publish"
              ? `公開すると対象版（${versionId}）が実際の着信応答に反映されます。`
              : `対象版（${versionId}）を参照する新しい版を作成して公開し、現在公開中の版を差し替えます。`
          }
          confirmLabel={confirmAction.kind === "publish" ? "公開する" : "ロールバックする"}
          danger={confirmAction.kind === "rollback"}
          busy={confirmBusy}
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => void runConfirmedAction()}
        />
      )}
    </>
  );
}

function screenTitle(screen: ManifestScreen): string {
  const titles: Record<string, string> = {
    "file-browser": "ファイル",
    answers: "質問する",
    chatbot: "チャットボット",
    "answer-history": "回答履歴",
    // U17: 用語統一 — connectors/sources are 「外部接続」 (matches the nav label), file uploads stay
    // 「ファイル」, and the ingestion-runs screen is 「取込履歴」 (was 取り込み実行/取込ラン).
    "source-search": "検索",
    "source-list": "外部接続",
    "source-detail": "外部接続の詳細",
    "add-source": "外部接続を追加",
    "ingestion-runs": "取込履歴",
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

function AddSourceCta({ className }: { className?: string }) {
  const classes = ["button-link", "btn-approve", "add-source-cta", className].filter(Boolean).join(" ");
  return (
    <Link className={classes} href="/sources/new">
      <span className="add-source-plus" aria-hidden="true">
        +
      </span>
      <span>外部接続を追加</span>
    </Link>
  );
}

/** Detail-ish screens get a lightweight back affordance (list ↔ detail navigation). */
const BACK_AFFORDANCE_SCREEN_IDS = new Set(["source-detail", "document-detail", "review-detail"]);

function ScreenShell({ screen, children }: { screen: ManifestScreen; children: ReactNode }) {
  const router = useRouter();
  const title = screenTitle(screen);
  const showBack = BACK_AFFORDANCE_SCREEN_IDS.has(screen.id);
  return (
    <section className="workspace full-saas-workspace" aria-label={title}>
      <header className="topbar">
        <div>
          {showBack && (
            <button type="button" className="topbar-back" onClick={() => router.back()}>
              ← 戻る
            </button>
          )}
          <h2>{title}</h2>
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

const SOURCE_LIST_PAGE_SIZE = 10;
type SourceListFilter = "all" | "needs_action" | "pending_review" | "failed" | "unsynced";
const SOURCE_LIST_FILTERS: Array<{ value: SourceListFilter; label: string }> = [
  { value: "all", label: "すべて" },
  { value: "needs_action", label: "要対応" },
  ...(APPROVAL_WORKFLOW_ENABLED
    ? [{ value: "pending_review" as const, label: "承認待ちあり" }]
    : []),
  { value: "failed", label: "同期失敗" },
  { value: "unsynced", label: "未同期" },
];

type SourceListRow = {
  source: AdminDataSourceOverview;
  sync: AdminDataSourceOverview["sync"];
  origin: "registered";
  documentCount: number | null;
  approvedCount: number | null;
  pendingCount: number | null;
};

function syncFreshness(sync: ManufacturingSourceSyncStatus | AdminDataSourceOverview["sync"] | null): string {
  const freshness = sync?.freshness;
  if (freshness && typeof freshness === "object") {
    const value = (freshness as { last_successful_sync_at?: unknown }).last_successful_sync_at;
    if (typeof value === "string" && value) return value;
  }
  return "";
}

function sourceLastSyncedAt(row: SourceListRow): string {
  return syncFreshness(row.sync) || row.source.last_synced_at || "";
}

function sourceFreshness(row: SourceListRow): string {
  const at = sourceLastSyncedAt(row);
  if (!at) return "未同期";
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime()) ? at : parsed.toLocaleString("ja-JP");
}

function sourceName(row: SourceListRow): string {
  return String(row.source.display_name || row.source.source_id);
}

function sourceKind(row: SourceListRow): string {
  return String(row.source.source_type || row.source.type || "source");
}

function sourceKindLabel(kind: string): string {
  const normalized = kind.toLowerCase().replace(/-/g, "_");
  if (normalized.startsWith("file_") || normalized.startsWith("upload_")) return "ファイル";
  const labels: Record<string, string> = {
    box: "Box",
    confluence: "Confluence",
    database: "データベース",
    file: "ファイル",
    google_drive: "Google Drive",
    googledrive: "Google Drive",
    kintone: "kintone",
    mysql: "MySQL",
    notion: "Notion",
    object_storage: "S3 / オブジェクトストレージ",
    postgres: "PostgreSQL",
    postgresql: "PostgreSQL",
    s3: "S3",
    text: "テキスト",
    upload: "ファイル",
    url: "URL",
  };
  return labels[normalized] ?? kind;
}

function sourceDocumentCount(row: SourceListRow): number | null {
  return row.documentCount ?? row.sync?.summary?.observed_count ?? null;
}

function sourceOperationalStatus(row: SourceListRow): { label: string; key: string; reason: string } {
  const syncStatus = row.sync?.status ?? "";
  if (row.source.status !== "active") {
    return { label: "停止中", key: "bad", reason: "このソースは現在利用対象外です。" };
  }
  if (row.source.credential_status === "missing") {
    return { label: "認証未設定", key: "bad", reason: "認証情報を設定してから同期してください。" };
  }
  if (isSyncActive(syncStatus)) {
    return { label: "同期中", key: "wait", reason: "更新内容を確認しています。" };
  }
  if (syncStatus === "failed") {
    return { label: "同期失敗", key: "bad", reason: "詳細を確認して再同期してください。" };
  }
  if (syncStatus === "partially_succeeded") {
    return { label: "確認が必要", key: "wait", reason: "一部の文書を取り込めませんでした。" };
  }
  if (APPROVAL_WORKFLOW_ENABLED && (row.pendingCount ?? 0) > 0) {
    return { label: "確認が必要", key: "wait", reason: "承認待ちの文書があります。" };
  }
  if (row.origin === "registered" && !sourceLastSyncedAt(row) && !sourceDocumentCount(row)) {
    return { label: "未同期", key: "wait", reason: "初回同期を実行してください。" };
  }
  if (syncStatus === "not_found") {
    return { label: "未同期", key: "wait", reason: "同期履歴がまだありません。" };
  }
  return { label: "利用可", key: "ok", reason: "回答の根拠として利用できます。" };
}

function sourceSyncStatusView(sync: ManufacturingSourceSyncStatus | null): { label: string; key: "ok" | "wait" | "bad"; reason: string } {
  const status = sync?.status ?? "";
  if (!sync) return { label: "確認中", key: "wait", reason: "同期状態を取得しています。" };
  if (isSyncActive(status)) return { label: "同期中", key: "wait", reason: "最新のナレッジへ更新しています。" };
  if (status === "failed") return { label: "同期失敗", key: "bad", reason: "接続設定を確認して再同期してください。" };
  if (status === "partially_succeeded") return { label: "一部要確認", key: "wait", reason: "一部の文書を取り込めませんでした。" };
  if (status === "not_found") return { label: "未同期", key: "wait", reason: "初回同期を実行してください。" };
  return { label: "利用可", key: "ok", reason: "回答の根拠として利用できます。" };
}

function sourceSyncDisplayDate(sync: ManufacturingSourceSyncStatus | null): string {
  const at = sync ? syncFreshness(sync) || sourceSyncLastIndexedAt(sync) : "";
  if (!at) return "まだありません";
  const parsed = new Date(at);
  return Number.isNaN(parsed.getTime()) ? at : parsed.toLocaleString("ja-JP");
}

function sourceApprovalSummary(row: SourceListRow): string {
  const total = sourceDocumentCount(row);
  if (total === null) return APPROVAL_WORKFLOW_ENABLED ? "承認状況未取得" : "文書数未取得";
  if (!APPROVAL_WORKFLOW_ENABLED) return `同期済み ${total} 件`;
  const pending = row.pendingCount ?? 0;
  if (pending > 0) return `${pending} 件の承認待ち`;
  return `承認済み ${row.approvedCount ?? 0} / ${total}`;
}

function sourceCredentialSummary(row: SourceListRow): string {
  const status = String(row.source.credential_status || "");
  if (status === "configured") return "認証: 設定済み";
  if (status === "missing") return "認証: 未設定";
  return status ? `認証: ${status}` : "認証: 種別設定";
}

function sourceTrustSummary(row: SourceListRow): string {
  const policy = String(row.source.approval_policy || "");
  if (policy === "trusted") return "承認: 取込時に正式根拠";
  if (policy === "review_required") return "承認: レビュー後に正式根拠";
  return APPROVAL_WORKFLOW_ENABLED ? "承認: レビュー設定未確認" : "承認: 自動利用";
}

function sourceNeedsAction(row: SourceListRow): boolean {
  const status = sourceOperationalStatus(row);
  return (
    status.label === "確認が必要" ||
    status.label === "同期失敗" ||
    status.label === "未同期" ||
    status.label === "停止中" ||
    row.source.credential_status === "missing"
  );
}

function sourceRecoveryActionLabel(row: SourceListRow): string {
  if (row.sync?.status === "failed") return "設定を修正";
  if (row.source.credential_status === "missing") return "認証を設定";
  return "詳細";
}

function sourceMatchesFilter(row: SourceListRow, filter: SourceListFilter): boolean {
  const status = sourceOperationalStatus(row);
  switch (filter) {
    case "needs_action":
      return sourceNeedsAction(row);
    case "pending_review":
      return (row.pendingCount ?? 0) > 0;
    case "failed":
      return row.sync?.status === "failed" || status.label === "同期失敗";
    case "unsynced":
      return status.label === "未同期";
    default:
      return true;
  }
}

function sourceSearchText(row: SourceListRow): string {
  const kind = sourceKind(row);
  const status = sourceOperationalStatus(row);
  return [
    sourceName(row),
    sourceKindLabel(kind),
    kind,
    row.source.source_id,
    row.source.collection_id,
    status.label,
    status.reason,
  ]
    .join(" ")
    .toLowerCase();
}

function dataSourceKind(source: AdminDataSource | AdminDataSourceOverview): string {
  if ("source_type" in source) {
    return String(source.source_type || source.type || "");
  }
  const config = (source.config ?? {}) as Record<string, unknown>;
  return String(config.source_type || source.type || "");
}

function isExternalConnectionSource(source: AdminDataSource | AdminDataSourceOverview): boolean {
  const kind = dataSourceKind(source).toLowerCase().replace(/-/g, "_");
  if (kind === "text") return false;
  return !isFileUploadSource(source.source_id, kind);
}

function valueLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(valueLabel).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function loadSourceListRows(): Promise<SourceListRow[]> {
  const token = await getSessionToken();
  const overview = await adminDataSourceOverview(token);
  return overview.sources.filter(isExternalConnectionSource).map((source) => ({
    approvedCount: source.document_counts.approved,
    documentCount: source.document_counts.total,
    origin: "registered" as const,
    pendingCount: source.document_counts.pending_review,
    source,
    sync: source.sync,
  }));
}

function SourceListBody() {
  const [state, reload] = useLoad(loadSourceListRows, [], {
    pollIntervalMs: SYNC_POLL_MS,
    shouldPoll: (rows) => rows.some(({ sync }) => isSyncActive(sync?.status)),
  });
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<SourceListFilter>("all");
  const [page, setPage] = useState(1);
  const [syncingSourceId, setSyncingSourceId] = useState<string | null>(null);
  const toast = useToast();
  const polling = state.state === "ready" && state.data.some(({ sync }) => isSyncActive(sync?.status));
  const rows = state.state === "ready" ? state.data : [];
  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (!sourceMatchesFilter(row, filter)) return false;
      if (!needle) return true;
      return sourceSearchText(row).includes(needle);
    });
  }, [filter, query, rows]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / SOURCE_LIST_PAGE_SIZE));
  const pageRows = filteredRows.slice((page - 1) * SOURCE_LIST_PAGE_SIZE, page * SOURCE_LIST_PAGE_SIZE);
  const needsActionCount = rows.filter(sourceNeedsAction).length;
  const pendingReviewCount = rows.reduce((sum, row) => sum + (row.pendingCount ?? 0), 0);
  const usableCount = rows.filter((row) => sourceOperationalStatus(row).label === "利用可").length;
  const syncingCount = rows.filter((row) => isSyncActive(row.sync?.status)).length;

  useEffect(() => {
    setPage(1);
  }, [filter, query]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  async function onResync(row: SourceListRow) {
    if (row.origin !== "registered" || syncingSourceId) return;
    setSyncingSourceId(row.source.source_id);
    try {
      const token = await getSessionToken();
      const syncSource = await ensureTrustedDatasourceForE2E(row.source.source_id, token);
      const sync = await adminSourceSync(
        row.source.source_id,
        { collection_id: syncSource?.collection_id || row.source.collection_id || DEMO_COLLECTION, reason: "manual_refresh" },
        token,
      );
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
      toast(`${sourceName(row)} の再同期を依頼しました。`, "success");
      reload();
    } catch (err) {
      if (isAuthError(err)) clearSessionToken();
      toast(formatLoadError(err), "error");
    } finally {
      setSyncingSourceId(null);
    }
  }

  return (
    <div className="standalone-list-shell">
      <header className="standalone-list-head">
        <div className="standalone-list-head-title">
          <h3>外部接続</h3>
          <p>回答に使う外部ナレッジの状態、承認待ち、再同期の必要性を確認できます。</p>
          {polling && <span className="sync-poll-badge">同期中 — 自動更新</span>}
        </div>
        <div className="standalone-list-tools">
          <button type="button" className="is-secondary" onClick={reload}>
            更新
          </button>
          <AddSourceCta />
        </div>
      </header>
      {state.state === "ready" && state.data.length > 0 && (
        <>
          <section className="work-stat-strip source-list-overview" aria-label="外部接続の概況">
            <WorkStat label="利用できる接続" value={`${usableCount} / ${rows.length}`} detail="回答の根拠に利用可" tone="ok" />
            <WorkStat label="要対応" value={`${needsActionCount} 件`} detail="同期失敗・未同期・承認待ち" tone={needsActionCount > 0 ? "wait" : "neutral"} />
            <WorkStat label="同期中" value={`${syncingCount} 件`} detail="一覧は自動更新されます" tone={syncingCount > 0 ? "wait" : "neutral"} />
            {APPROVAL_WORKFLOW_ENABLED && (
              <WorkStat label="承認待ち文書" value={`${pendingReviewCount} 件`} detail="正式根拠にする前に確認" tone={pendingReviewCount > 0 ? "wait" : "neutral"} />
            )}
          </section>
          <section className="source-list-controls" aria-label="ソースの検索と絞り込み">
            <label className="standalone-search source-list-search">
              <span aria-hidden="true">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="接続名・種類・状態で検索"
                aria-label="接続名・種類・状態で検索"
              />
            </label>
            <div className="source-list-filter" role="group" aria-label="ソース状態で絞り込み">
              {SOURCE_LIST_FILTERS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={filter === option.value ? "source-filter-button active" : "source-filter-button"}
                  aria-pressed={filter === option.value}
                  onClick={() => setFilter(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="source-list-summary" aria-live="polite">
              <span>{filteredRows.length} 件表示</span>
              <span>全体 {rows.length} 件</span>
            </div>
          </section>
        </>
      )}
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
            <h4>まだ外部接続が登録されていません</h4>
            <p>
              Box、Confluence、Notion、S3 などを接続すると、同期状態をここで確認できます。ファイルはファイルメニューで管理します。
            </p>
            <AddSourceCta className="standalone-empty-cta" />
          </div>
        ) : filteredRows.length === 0 ? (
          <div className="standalone-empty-state">
            <h4>条件に合うソースはありません</h4>
            <p>検索語や絞り込みを変えると、別のソースを確認できます。</p>
            <button
              type="button"
              className="standalone-empty-cta"
              onClick={() => {
                setQuery("");
                setFilter("all");
              }}
            >
              条件をクリア
            </button>
          </div>
        ) : (
          <>
            <div className="source-list-items" role="list">
              {pageRows.map((row) => {
                const kind = sourceKind(row);
                const name = sourceName(row);
                const status = sourceOperationalStatus(row);
                const documents = sourceDocumentCount(row);
                const href = `/sources/${row.source.source_id}`;
                const isSyncing = syncingSourceId === row.source.source_id;
                const rowSyncActive = isSyncActive(row.sync?.status);
                return (
                  <article className="source-list-row" key={row.source.source_id} role="listitem">
                    <div className="source-list-main">
                      <div className="standalone-source-mark" aria-hidden="true">
                        {kind.slice(0, 2).toUpperCase()}
                      </div>
                      <div className="source-list-title-block">
                        <h4>
                          <Link href={href} className="source-title-link" aria-label={`${name} の詳細を見る`}>
                            {name}
                          </Link>
                        </h4>
                        <p>{sourceKindLabel(kind)}</p>
                      </div>
                    </div>
                    <div className="source-list-status-cell">
                      <span className={`standalone-status ${status.key}`}>{status.label}</span>
                      <span>{status.reason}</span>
                    </div>
                    <div className="source-list-metrics" aria-label={`${name} の文書と同期状態`}>
                      <span>
                        <strong>{documents ?? "—"}</strong> 文書
                      </span>
                      <span>{sourceApprovalSummary(row)}</span>
                      <span>{sourceCredentialSummary(row)}</span>
                      <span>{sourceTrustSummary(row)}</span>
                      <span>最終同期: {sourceFreshness(row)}</span>
                    </div>
                    <div className="source-list-actions">
                      {APPROVAL_WORKFLOW_ENABLED && (row.pendingCount ?? 0) > 0 && (
                        <Link href="/reviews/documents" className="button-link secondary">
                          レビューへ
                        </Link>
                      )}
                      <Link href={href} className="button-link secondary">
                        {sourceRecoveryActionLabel(row)}
                      </Link>
                      {row.origin === "registered" && (
                        <button
                          type="button"
                          onClick={() => onResync(row)}
                          disabled={Boolean(syncingSourceId) || rowSyncActive}
                        >
                          {isSyncing || rowSyncActive ? "同期中" : "再同期"}
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
            {totalPages > 1 && (
              <nav className="source-list-pagination" aria-label="ソースのページ">
                <button
                  type="button"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={page <= 1}
                >
                  前へ
                </button>
                <span>
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  disabled={page >= totalPages}
                >
                  次へ
                </button>
              </nav>
            )}
          </>
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
  onPreviewReadyChange,
}: {
  sourceId: string;
  collectionId?: string | null;
  onPreviewReadyChange?: (ready: boolean) => void;
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
    onPreviewReadyChange?.(false);
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
    onPreviewReadyChange?.(false);
    setMessage(null);
  }

  async function runPreview(useEditedMapping: boolean) {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    onPreviewReadyChange?.(false);
    try {
      const defaults: Record<string, unknown> = {};
      if (documentKind) defaults.document_kind = documentKind;
      if (APPROVAL_WORKFLOW_ENABLED) {
        if (approvalStatus) defaults.approval_status = approvalStatus;
        if (effectiveDate) defaults.effective_date = effectiveDate;
      } else {
        Object.assign(defaults, datasourceMappingApprovalDefaults("trusted", todayIso()));
      }

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
      onPreviewReadyChange?.(true);
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
    onPreviewReadyChange?.(false);
  }

  async function saveMappingProfile() {
    if (!preview || savingProfile) return;
    setSavingProfile(true);
    setMessage(null);
    try {
      const defaults: Record<string, unknown> = {};
      if (documentKind) defaults.document_kind = documentKind;
      if (APPROVAL_WORKFLOW_ENABLED) {
        if (approvalStatus) defaults.approval_status = approvalStatus;
        if (effectiveDate) defaults.effective_date = effectiveDate;
      } else {
        Object.assign(defaults, datasourceMappingApprovalDefaults("trusted", todayIso()));
      }
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
      const configForSave = applyApprovalWorkflowModeToConfig(nextConfig);
      await apiPutJson(
        `/admin/datasources/${encodeURIComponent(sourceId)}`,
        {
          collection_id: current.collection_id,
          type: current.type,
          config: configForSave,
          sync_schedule: current.sync_schedule ?? null,
          status: current.status,
          reason: "mapping_profile_saved_from_preview",
        },
        token,
      );
      setDatasource({ ...current, config: configForSave });
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
            onChange={(e) => {
              setSampleDocuments(Math.max(1, Number(e.target.value) || 1));
              onPreviewReadyChange?.(false);
            }}
          />
        </label>
        <label>
          <span>行数</span>
          <input
            type="number"
            min={1}
            max={50}
            value={sampleRows}
            onChange={(e) => {
              setSampleRows(Math.max(1, Number(e.target.value) || 1));
              onPreviewReadyChange?.(false);
            }}
          />
        </label>
        <label>
          <span>文書種別</span>
          <select
            value={documentKind}
            onChange={(e) => {
              setDocumentKind(e.target.value);
              onPreviewReadyChange?.(false);
            }}
          >
            {PREVIEW_DEFAULT_KIND_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {APPROVAL_WORKFLOW_ENABLED && (
          <>
            <label>
                <span>承認状態</span>
                <select
                  value={approvalStatus}
                  onChange={(e) => {
                    setApprovalStatus(e.target.value);
                    onPreviewReadyChange?.(false);
                  }}
                >
                {PREVIEW_APPROVAL_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>発効日</span>
              <input
                type="date"
                value={effectiveDate}
                onChange={(e) => {
                  setEffectiveDate(e.target.value);
                  onPreviewReadyChange?.(false);
                }}
              />
            </label>
          </>
        )}
        <label>
          <span>必須項目</span>
          <input
            value={requiredFields}
            onChange={(e) => {
              setRequiredFields(e.target.value);
              onPreviewReadyChange?.(false);
            }}
          />
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
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<HistoryStatusFilter>("all");
  const [safetyFilter, setSafetyFilter] = useState<HistorySafetyFilter>("all");
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    setEntries(loadAnswerHistory());
  }, []);

  function onClear() {
    clearAnswerHistory();
    setEntries([]);
    setConfirmClear(false);
  }

  function safetyTag(entry: AnswerHistoryEntry): string {
    if (entry.blocked) return "保留";
    if (entry.high_risk) return "高リスク";
    if (entry.obsolete) return "旧版参照";
    return "正常";
  }

  function safetyKey(entry: AnswerHistoryEntry): HistorySafetyFilter {
    if (entry.blocked) return "blocked";
    if (entry.high_risk) return "high_risk";
    if (entry.obsolete) return "obsolete";
    return "normal";
  }

  const filteredEntries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (statusFilter !== "all" && entry.status !== statusFilter) return false;
      if (safetyFilter !== "all" && safetyKey(entry) !== safetyFilter) return false;
      if (!needle) return true;
      return [entry.question, entry.answer_excerpt, entry.collection_id]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [entries, query, statusFilter, safetyFilter]);

  const stats = useMemo(() => ({
    total: entries.length,
    blocked: entries.filter((entry) => entry.blocked).length,
    highRisk: entries.filter((entry) => entry.high_risk).length,
    cited: entries.filter((entry) => entry.citation_count > 0).length,
  }), [entries]);

  return (
    <Section
      title="回答履歴"
      note="このブラウザに保存された最近の回答です。監査ログや全社履歴ではありません。"
    >
      {entries.length === 0 ? (
        <div className="history-empty">
          <p className="ops-empty">まだ履歴はありません。「質問する」から質問すると、ここに残ります。</p>
          <Link className="citation-open" href="/">質問する</Link>
        </div>
      ) : (
        <>
          <div className="history-summary-grid" aria-label="履歴サマリ">
            <Stat label="保存された回答" value={stats.total} />
            <Stat label="保留" value={stats.blocked} />
            <Stat label="高リスク" value={stats.highRisk} />
            <Stat label="引用あり" value={stats.cited} />
          </div>

          <div className="history-toolbar">
            <label className="history-search-field">
              <span>検索</span>
              <input
                aria-label="回答履歴を検索"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="質問、回答抜粋、参照範囲"
              />
            </label>
            <label className="history-filter-field">
              <span>状態</span>
              <select
                aria-label="回答状態で絞り込み"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as HistoryStatusFilter)}
              >
                <option value="all">すべて</option>
                <option value="ok">回答済み</option>
                <option value="insufficient_evidence">根拠不足</option>
                <option value="budget_exceeded">予算上限</option>
                <option value="unavailable">利用不可</option>
              </select>
            </label>
            <label className="history-filter-field">
              <span>安全</span>
              <select
                aria-label="安全状態で絞り込み"
                value={safetyFilter}
                onChange={(event) => setSafetyFilter(event.target.value as HistorySafetyFilter)}
              >
                <option value="all">すべて</option>
                <option value="normal">正常</option>
                <option value="blocked">保留</option>
                <option value="high_risk">高リスク</option>
                <option value="obsolete">旧版参照</option>
              </select>
            </label>
          </div>

          {filteredEntries.length === 0 ? (
            <p className="ops-empty">条件に一致する履歴はありません。</p>
          ) : (
            <div className="history-list" aria-label="回答履歴一覧">
              {filteredEntries.map((entry) => (
                <article className="history-card" key={entry.id}>
                  <header>
                    <div className="history-card-title">
                      <strong>{entry.question}</strong>
                      <span>{new Date(entry.asked_at).toLocaleString("ja-JP")}</span>
                    </div>
                    <div className="history-card-badges" aria-label="回答状態">
                      <span className={`status-badge status-${entry.status}`}>{statusLabel(entry.status)}</span>
                      <span className={`citation-chip ${entry.blocked ? "approval-obsolete" : entry.high_risk || entry.obsolete ? "approval-draft" : "approval-approved"}`}>
                        {safetyTag(entry)}
                      </span>
                    </div>
                  </header>
                  {entry.answer_excerpt && <p>{entry.answer_excerpt}</p>}
                  <footer>
                    <span>引用 {entry.citation_count}件</span>
                    {entry.collection_id && <span>参照範囲 {collectionDisplayName(entry.collection_id)}</span>}
                    <Link
                      className="citation-open"
                      href={`/?q=${encodeURIComponent(entry.question)}&submit=1`}
                    >
                      再質問
                    </Link>
                  </footer>
                </article>
              ))}
            </div>
          )}

          <div className="screen-actions history-actions">
            <button type="button" className="citation-open" onClick={() => setConfirmClear(true)}>
              このブラウザの履歴を消去
            </button>
            {confirmClear && (
              <div className="history-clear-confirm" role="group" aria-label="履歴消去の確認">
                <span>保存済みのローカル履歴を削除します。監査ログやサーバーデータは削除されません。</span>
                <button type="button" className="btn-reject" onClick={onClear}>消去する</button>
                <button type="button" className="citation-open" onClick={() => setConfirmClear(false)}>キャンセル</button>
              </div>
            )}
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
          {APPROVAL_WORKFLOW_ENABLED ? (
            <Link href="/reviews" className="home-task-card">
              <div className="home-task-head">
                <span className="home-task-label">AIドラフト</span>
                <span className="home-task-dot" />
              </div>
              <strong>{dashboard.unanswered_question_count}</strong>
              <span>未回答の質問</span>
              <span className="home-task-cta">レビューへ</span>
            </Link>
          ) : (
            <Link href="/sources/list" className="home-task-card">
              <div className="home-task-head">
                <span className="home-task-label">外部接続</span>
                <span className="home-task-dot home-task-dot-ok" />
              </div>
              <strong>同期</strong>
              <span>外部接続とファイルを整える</span>
              <span className="home-task-cta">外部接続を見る</span>
            </Link>
          )}
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
            <Link href="/chatbot" className="action-card">
              <strong>チャットボット</strong>
              <span>取り込んだナレッジで応答を確認する</span>
            </Link>
            <Link href="/sources/list" className="action-card">
              <strong>外部接続</strong>
              <span>接続と同期状態を確認する</span>
            </Link>
            {APPROVAL_WORKFLOW_ENABLED ? (
              <Link href="/reviews" className="action-card">
                <strong>AIドラフトレビュー</strong>
                <span>AI ドラフトを確認する</span>
              </Link>
            ) : (
              <Link href="/files" className="action-card">
                <strong>ファイル</strong>
                <span>ナレッジを追加する</span>
              </Link>
            )}
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
  const [refreshTick, setRefreshTick] = useState(0);
  const toast = useToast();

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
    try {
      const token = await getSessionToken();
      await ensureTrustedDatasourceForE2E(sourceId, token);
      await manufacturingRequestSourceSync(sourceId, { reason: "manual_refresh" }, token);
      toast("同期を依頼しました", "success");
      reload();
    } catch (err) {
      toast(formatLoadError(err), "error");
    }
  }

  const polling = syncState.state === "ready" && isSyncActive(syncState.data.status);
  const syncView = syncState.state === "ready" ? sourceSyncStatusView(syncState.data) : null;
  const syncSummary = syncState.state === "ready" ? syncState.data : null;
  const latestRun = runState.state === "ready" ? runState.data : null;

  return (
    <>
      <Section title="同期と利用状態" note="この接続が回答の根拠として使える状態かを確認できます。">
        <div className="source-detail-summary">
          <div className="source-detail-status">
            <span className={`standalone-status ${syncView?.key ?? "wait"}`}>
              {syncView?.label ?? "確認中"}
            </span>
            <strong>{syncView?.reason ?? "同期状態を読み込んでいます。"}</strong>
            <span>最終同期: {syncSummary ? sourceSyncDisplayDate(syncSummary) : "確認中"}</span>
          </div>
          <form className="source-detail-actions" onSubmit={onSyncRequest}>
            <button type="submit" disabled={polling}>
              {polling ? "同期中" : "同期を開始"}
            </button>
            <button type="button" className="button-link secondary" onClick={reload}>
              状態を更新
            </button>
          </form>
        </div>
        {syncSummary && (
          <section className="work-stat-strip source-detail-stats" aria-label="同期結果の概要">
            <WorkStat label="同期対象" value={`${syncSummary.summary.observed_count ?? 0} 件`} detail="見つかった文書" />
            <WorkStat label="変更" value={`${syncSummary.summary.changed_count ?? 0} 件`} detail="更新された文書" tone={(syncSummary.summary.changed_count ?? 0) > 0 ? "ok" : "neutral"} />
            <WorkStat label="削除" value={`${syncSummary.summary.deleted_count ?? 0} 件`} detail="同期で除外" tone={(syncSummary.summary.deleted_count ?? 0) > 0 ? "wait" : "neutral"} />
            <WorkStat label="回答範囲" value={syncSummary.collection_id ?? "未設定"} detail="この範囲で検索" />
          </section>
        )}
        {polling && <p className="ops-note">同期中です。完了までこの画面は自動更新されます。</p>}
      </Section>

      <SourceConnectionEditPanel sourceId={sourceId} onSaved={reload} />

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
                ["状態", sourceSyncStatusView(syncState.data).label],
                ["回答範囲", syncState.data.collection_id ?? "—"],
                ["観測数", syncState.data.summary.observed_count ?? "—"],
                ["変更数", syncState.data.summary.changed_count ?? "—"],
                ["削除数", syncState.data.summary.deleted_count ?? "—"],
              ]}
            />
            {syncState.data.correlation_id && (
              <details className="ops-details">
                <summary>運用ID</summary>
                <FieldGrid rows={[["相関 ID", syncState.data.correlation_id]]} />
              </details>
            )}
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

      {latestRun && (
        <Section title="最新の取込">
          <FieldGrid
            rows={[
              ["状態", latestRun.status],
              ["回答範囲", latestRun.collection_id ?? "—"],
              ["開始", latestRun.started_at ?? "—"],
              ["終了", latestRun.finished_at ?? "—"],
            ]}
          />
          <details className="ops-details">
            <summary>運用ID</summary>
            <FieldGrid
              rows={[
                ["実行 ID", latestRun.ingestion_run_id],
                ["ソース ID", latestRun.source_id ?? "—"],
              ]}
            />
          </details>
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

function ApprovalWorkflowPausedBody() {
  return (
    <>
      <p className="src-warning" role="status">
        文書承認フローは一時停止中です。新しく追加・同期した文書は、ソースを信頼する前提で質問に使える状態として取り込みます。
      </p>
      <Section title="次に進む" note="まずは外部接続の追加、同期、質問・チャットの end to end を優先します。">
        <div className="quick-card-grid">
          <Link href="/sources/new" className="action-card">
            <strong>外部接続を追加</strong>
            <span>外部接続を設定する</span>
          </Link>
          <Link href="/files" className="action-card">
            <strong>ファイル</strong>
            <span>ファイルを直接アップロードする</span>
          </Link>
          <Link href="/chatbot" className="action-card">
            <strong>チャットボット</strong>
            <span>取り込んだナレッジで応答を確認する</span>
          </Link>
        </div>
      </Section>
    </>
  );
}

function DocumentApprovalQueueBody() {
  if (!APPROVAL_WORKFLOW_ENABLED) return <ApprovalWorkflowPausedBody />;
  return <DocumentApprovalQueueEnabledBody />;
}

function DocumentApprovalQueueEnabledBody() {
  const [docs, setDocs] = useState<IngestedDoc[]>([]);
  const [serverDocs, setServerDocs] = useState<
    Array<{ document_id: string; approval_status: string; collection_id: string; effective_date: string | null }>
  >([]);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();

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
      toast(`${doc.document_id} を「${DOC_APPROVAL_STATUS[nextStatus]?.label ?? nextStatus}」に更新しました。`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "更新に失敗しました", "error");
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
            取り込んだ文書がありません。<Link href="/sources/new">外部接続を追加</Link> から取り込んでください。
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

      {APPROVAL_WORKFLOW_ENABLED && (
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
      )}
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
  // U11: source documents are picked from the real document list; the raw comma-separated ID input
  // survives as an opt-in 詳細指定 fallback for power users (IDs not in the list, e.g. just-ingested).
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [advancedDocInput, setAdvancedDocInput] = useState(false);
  const [docIds, setDocIds] = useState("");
  const [collection, setCollection] = useState(DEMO_COLLECTION);
  const collections = useKnownCollections();
  const [creating, setCreating] = useState(false);
  const [uploadedDocs, setUploadedDocs] = useState<IngestedDoc[]>([]);
  const [docOptionsState, setDocOptionsState] = useState<ViewState<ManufacturingDocumentSummary[]>>({
    state: "loading",
  });
  const toast = useToast();

  useEffect(() => {
    setUploadedDocs(loadIngestedDocs());
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDocOptionsState({ state: "loading" });
    void getSessionToken()
      .then((token) => manufacturingDocuments(token, collection))
      .then((docs) => {
        if (!cancelled) setDocOptionsState({ state: "ready", data: docs });
      })
      .catch((err) => {
        if (!cancelled) setDocOptionsState({ state: "error", error: formatLoadError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [collection]);

  const docOptions = useMemo(() => {
    if (docOptionsState.state !== "ready") return [];
    const titleById = new Map(
      uploadedDocs.filter((doc) => doc.filename).map((doc) => [doc.document_id, doc.filename as string]),
    );
    return docOptionsState.data.map((doc) => ({
      id: doc.document_id,
      label: titleById.get(doc.document_id) ?? doc.document_id,
      kind: documentKindLabel(doc.document_kind),
      approval: doc.approval_status,
    }));
  }, [docOptionsState, uploadedDocs]);

  function toggleDocSelection(id: string) {
    setSelectedDocIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

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
    try {
      const token = await getSessionToken();
      const ids = advancedDocInput
        ? docIds
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : selectedDocIds;
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
      toast(err instanceof Error ? err.message : "ドラフト生成に失敗しました", "error");
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
            {/* U18: pending (下書き+レビュー中) instead of the status-blind total. */}
            <span
              className="review-queue-count"
              title="未対応（下書き + レビュー中）"
              aria-label={`未対応 ${
                drafts.filter((d) => d.status === "draft" || d.status === "in_review").length
              } 件`}
            >
              {drafts.filter((d) => d.status === "draft" || d.status === "in_review").length}
            </span>
          </div>
          {drafts.length > 0 && (
            <p className="review-queue-breakdown" aria-label="ステータス別件数">
              {(
                [
                  ["draft", "下書き"],
                  ["in_review", "レビュー中"],
                  ["approved", "承認済み"],
                  ["rejected", "却下"],
                ] as const
              ).map(([status, label]) => (
                <span key={status}>
                  {label} {drafts.filter((d) => d.status === status).length}
                </span>
              ))}
            </p>
          )}
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
              <span>コレクション</span>
              <select
                value={collection}
                onChange={(e) => {
                  setCollection(e.target.value);
                  // Selected documents belong to the previous collection — reset the picker.
                  setSelectedDocIds([]);
                }}
              >
                {(collections.includes(collection) ? collections : [collection, ...collections]).map((id) => (
                  <option key={id} value={id}>
                    {collectionDisplayName(id)}
                  </option>
                ))}
              </select>
            </label>
            {!advancedDocInput && (
              <div className="draft-doc-picker">
                <span>根拠ドキュメント（未選択の場合はコレクション全体）</span>
                {docOptionsState.state === "loading" && (
                  <p className="ops-empty" role="status" aria-live="polite">
                    ドキュメントを読み込み中…
                  </p>
                )}
                {docOptionsState.state === "error" && (
                  <p className="ops-note" role="alert">
                    ドキュメント一覧を取得できませんでした。「詳細指定」で ID を直接入力できます。
                  </p>
                )}
                {docOptionsState.state === "ready" &&
                  (docOptions.length === 0 ? (
                    <p className="ops-empty">
                      このコレクションにドキュメントはまだありません。
                      <Link href="/sources/new">外部接続を追加</Link> から取り込めます。
                    </p>
                  ) : (
                    <div className="draft-doc-options" role="group" aria-label="根拠ドキュメントの選択">
                      {docOptions.map((doc) => (
                        <label key={doc.id} className="draft-doc-option">
                          <input
                            type="checkbox"
                            checked={selectedDocIds.includes(doc.id)}
                            onChange={() => toggleDocSelection(doc.id)}
                          />
                          <span className="draft-doc-option-label">{doc.label}</span>
                          <span className="draft-doc-option-meta">{doc.kind}</span>
                        </label>
                      ))}
                    </div>
                  ))}
                {selectedDocIds.length > 0 && (
                  <p className="ops-note" aria-live="polite">
                    {selectedDocIds.length} 件選択中
                  </p>
                )}
              </div>
            )}
            {advancedDocInput && (
              <label>
                <span>根拠ドキュメント ID（カンマ区切り）</span>
                <input
                  value={docIds}
                  onChange={(e) => setDocIds(e.target.value)}
                  placeholder="document_id をカンマ区切りで入力"
                />
              </label>
            )}
            <button
              type="button"
              className="linklike draft-doc-mode-toggle"
              aria-pressed={advancedDocInput}
              onClick={() => setAdvancedDocInput((v) => !v)}
            >
              {advancedDocInput ? "一覧から選ぶに戻す" : "詳細指定（ID を直接入力）"}
            </button>
            <button type="submit" disabled={creating}>
              {creating ? "生成中…" : "ドラフトを生成"}
            </button>
          </form>
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
          note="「外部接続を追加」から開始した同期です。実行 ID で詳細を確認できます。"
        >
          <DataTable
            columns={["実行 ID", "ソース", "種別", "状態", "変更", "日時"]}
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
              run.source_name || run.source_id,
              sourceKindLabel(run.source_type || run.source_id),
              connectorStatusLabel(run.status),
              String(run.changed_count),
              new Date(run.synced_at).toLocaleString("ja-JP"),
            ])}
            empty="コネクタ同期はまだありません。"
          />
        </Section>
      )}
      {uploads.length > 0 && (
        <Section title="最近のアップロード取込（このブラウザ）" note="ファイルアップロードから作成された取込です。">
          <DataTable
            columns={["実行 ID", "ソース", "状態", "チャンク", "日時"]}
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
              doc.source_name || doc.filename || doc.document_id,
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
          まだ取込履歴はありません。<Link href="/sources/new">外部接続を追加</Link> から同期またはアップロードしてください。
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
      const [kpi, governance, operational] = await Promise.all([
        manufacturingKpi(token),
        manufacturingGovernanceStatus(token),
        // ★G3b/★G5: 実測メトリクス is reviewer/admin-only — degrade to the proxy-only view
        // (card hidden) instead of failing the whole screen for other roles.
        qualityOperational(token).catch(() => null as QualityOperationalResponse | null),
      ]);
      return { kpi, governance, operational };
    },
    [],
  );
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">品質データを読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;
  const { kpi, operational } = state.data;
  const hasRealLatency = Boolean(operational && operational.query_count > 0);
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
      {operational && (
        <Section
          title="実測運用メトリクス"
          note="query_traces(実測の遅延・回答状態)と永続化フィードバックに基づく運用指標です。質問文は保存前にPIIマスク済みです。"
        >
          <div className="metric-grid">
            <Stat label="質問数" value={operational.query_count} />
            <Stat label="実測 p50" value={`${operational.p50_ms.toFixed(0)} ms`} />
            <Stat label="実測 p95" value={`${operational.p95_ms.toFixed(0)} ms`} />
            <Stat label="未回答率" value={`${(operational.insufficient_rate * 100).toFixed(1)}%`} />
            <Stat label="低評価件数" value={operational.low_rating_count} />
          </div>
          <h3 className="src-h4">最近の未回答クエリ</h3>
          <DataTable
            columns={["質問(マスク済み)", "状態", "日時"]}
            rows={operational.recent_refusals.map((r) => [
              r.query_redacted || r.request_id,
              r.status,
              r.created_at ? new Date(r.created_at).toLocaleString("ja-JP") : "—",
            ])}
            empty="未回答のクエリはまだありません。"
          />
        </Section>
      )}
      <Section title="監査由来サマリー">
        <FieldGrid
          rows={[
            [
              "回答 p50",
              hasRealLatency && operational
                ? `${operational.p50_ms.toFixed(0)} ms(実測)`
                : `${kpi.average_time_to_answer.p50}(代理値: 根拠数)`,
            ],
            [
              "回答 p95",
              hasRealLatency && operational
                ? `${operational.p95_ms.toFixed(0)} ms(実測)`
                : `${kpi.average_time_to_answer.p95}(代理値: 根拠数)`,
            ],
            ["頻出文書", kpi.frequently_referenced_documents.length],
            ["旧版候補", kpi.obsolete_document_candidates.length],
            ["要再確認（確認期限超過）", kpi.review_overdue_document_count ?? 0],
            ["集計時刻", kpi.materialized_at],
          ]}
        />
        {(kpi.review_overdue_documents?.length ?? 0) > 0 && (
          <ul className="ops-list">
            {(kpi.review_overdue_documents ?? []).slice(0, 5).map((d) => (
              <li key={d.document_id}>
                {d.document_id} — 最終確認 {d.last_verified_at || "—"} / 期限 {d.review_due_date}
                {d.owner ? `（担当: ${d.owner}）` : ""}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <QualityEvalSection />
      <Section
        title="監査エビデンスパック"
        note="監査ハッシュチェーンから期間集計(質問数・根拠付き回答率・ブロック内訳・転送・QA・チェーン検証)を生成し、内部監査・安全衛生委員会にそのまま提出できる形で出力します。"
      >
        <EvidencePackSection />
      </Section>
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

function EvidencePackSection() {
  const toast = useToast();
  const [range, setRange] = useState({ from: "", to: "" });
  const [pack, setPack] = useState<Record<string, unknown> | null>(null);
  const [running, setRunning] = useState(false);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (running) return;
    setRunning(true);
    try {
      const token = await getSessionToken();
      setPack(await manufacturingAuditEvidencePack(token, range));
    } catch (err) {
      toast(err instanceof Error ? err.message : "エビデンスパックの生成に失敗しました", "error");
    } finally {
      setRunning(false);
    }
  }

  function download() {
    if (!pack) return;
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-evidence-pack-${range.from || "all"}_${range.to || "now"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const summary = (pack?.summary ?? null) as Record<string, number> | null;
  const chain = (pack?.hash_chain ?? null) as Record<string, unknown> | null;
  return (
    <>
      <form className="src-inline-form" onSubmit={run} aria-label="エビデンスパック期間">
        <input type="date" value={range.from} onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))} aria-label="開始日" />
        <input type="date" value={range.to} onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))} aria-label="終了日" />
        <button type="submit" disabled={running}>{running ? "集計中…" : "生成"}</button>
        {pack && (
          <button type="button" onClick={download}>
            JSONダウンロード
          </button>
        )}
      </form>
      {summary && chain && (
        <FieldGrid
          rows={[
            ["質問件数", String(summary.question_count)],
            [
              "根拠付き回答率",
              summary.grounded_answer_rate != null
                ? `${Math.round((summary.grounded_answer_rate as number) * 100)}%`
                : "-",
            ],
            ["ブロック件数", String(summary.blocked_count)],
            ["人間への転送", String(summary.handoff_count)],
            ["QAレビュー", String(summary.qa_review_count)],
            [
              "監査チェーン検証",
              chain.verified ? `✓ 改ざんなし(${chain.total_entries}件)` : "✗ 検証失敗 — 要調査",
            ],
          ]}
        />
      )}
    </>
  );
}

function QualityEvalSection() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<QualityEvalResult | null>(null);
  // U10: "latest" = the persisted previous run shown by default; "run" = a run started here.
  const [resultSource, setResultSource] = useState<"latest" | "run" | null>(null);
  const [latestChecked, setLatestChecked] = useState(false);
  const toast = useToast();

  // U10: show the last persisted evaluation run (evaluation_runs) on mount instead of a blank
  // section. A run started from the button always wins over the late-arriving latest fetch.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const token = await getSessionToken();
        const latest = await latestManufacturingQualityEval(token);
        if (active && latest) {
          setResult((current) => current ?? latest);
          setResultSource((current) => current ?? "latest");
        }
      } catch {
        // No persisted run / endpoint unavailable — keep the run-it-yourself empty state.
      } finally {
        if (active) setLatestChecked(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function run() {
    if (running) return;
    setRunning(true);
    try {
      const token = await getSessionToken();
      setResult(await runManufacturingQualityEval(QUALITY_EVAL_ITEMS, token));
      setResultSource("run");
    } catch (err) {
      toast(err instanceof Error ? err.message : "評価の実行に失敗しました", "error");
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
          {running ? "評価を実行中…" : result ? "再実行" : "品質評価を実行"}
        </button>
      </div>
      {!result && latestChecked && !running && (
        <p className="ops-empty">まだ評価結果がありません。「品質評価を実行」で最初のスコアカードを作成します。</p>
      )}
      {result && (
        <>
          {resultSource === "latest" && (
            <p className="ops-note" role="status">
              前回の評価結果を表示しています（実行日時: {fmtTime(result.created_at)}）。最新の状態を測るには「再実行」してください。
            </p>
          )}
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
              ["実行日時", fmtTime(result.created_at)],
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

type ImprovementOrigin = "feedback" | "audit" | "local";
type ImprovementStatusFilter = "all" | "open" | "resolved";

const IMPROVEMENT_ORIGIN_LABEL: Record<ImprovementOrigin, string> = {
  feedback: "フィードバック",
  audit: "監査",
  local: "この端末",
};

// U14: one row of the merged improvement queue. `localId` links a server row to the browser-local
// record that duplicates it (matched on answer_id — the only key both sides share; local rows keep
// no feedback_id/correlation_id), which supplies the 対応済み state. Server-side resolve is a
// known follow-up: フィードバック/監査 rows have no persisted status yet.
type UnifiedImprovementRow = {
  key: string;
  origin: ImprovementOrigin;
  chip: { label: string; cls: string };
  title: string;
  detail: string;
  created_at: string;
  localId?: string;
  resolved: boolean;
};

const IMPROVEMENT_KIND_LABEL: Record<string, string> = {
  low_rating: "低評価",
  unanswered: "未回答",
  insufficient_evidence: "根拠不足",
  safety_block: "安全ブロック",
  obsolete_only: "旧版のみヒット",
};

function ImprovementQueueBody() {
  const [items, setItems] = useState<ImprovementItem[]>([]);
  const [serverItems, setServerItems] = useState<
    Array<{ id: string; kind: string; answer_id: string | null; reason: string | null; created_at: string }>
  >([]);
  // ★G3a: persisted feedback rows (answer_feedback via GET /v1/feedback). null = endpoint
  // unavailable (offline / non-reviewer) → fall back to the browser-local queue only.
  const [feedbackRows, setFeedbackRows] = useState<FeedbackRecord[] | null>(null);
  const [originFilter, setOriginFilter] = useState<"all" | ImprovementOrigin>("all");
  const [statusFilter, setStatusFilter] = useState<ImprovementStatusFilter>("all");
  const [confirmClearResolved, setConfirmClearResolved] = useState(false);

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
    void (async () => {
      try {
        const token = await getSessionToken();
        const res = await listFeedback(token, 100);
        setFeedbackRows(res.items);
      } catch {
        setFeedbackRows(null);
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
  function clearResolved() {
    clearResolvedImprovementItems();
    setItems(loadImprovementItems());
    setConfirmClearResolved(false);
  }

  const { rows, mergedCount } = useMemo(() => {
    const localByAnswer = new Map<string, ImprovementItem>();
    for (const item of items) {
      if (item.answer_id && !localByAnswer.has(item.answer_id)) localByAnswer.set(item.answer_id, item);
    }
    // Local rows that duplicate a server row (same answer_id) are folded into it instead of listed twice.
    const consumed = new Set<string>();
    const merged: UnifiedImprovementRow[] = [];
    for (const row of feedbackRows ?? []) {
      const local = row.answer_id ? localByAnswer.get(row.answer_id) : undefined;
      if (local) consumed.add(local.id);
      merged.push({
        key: `fb-${row.feedback_id}`,
        origin: "feedback",
        chip:
          row.rating === "up"
            ? { label: "👍 有用", cls: "approval-approved" }
            : row.rating === "down"
              ? { label: "👎 要改善", cls: "approval-obsolete" }
              : { label: "中立", cls: "approval-draft" },
        title: local?.question || row.answer_id || row.citation_id || row.feedback_id,
        detail: `${row.reason_code ? `理由: ${reasonLabel(row.reason_code)} · ` : ""}${row.actor_id} · ${new Date(row.created_at).toLocaleString("ja-JP")}`,
        created_at: row.created_at,
        localId: local?.id,
        resolved: local?.status === "resolved",
      });
    }
    for (const item of serverItems) {
      const local = item.answer_id ? localByAnswer.get(item.answer_id) : undefined;
      if (local) consumed.add(local.id);
      merged.push({
        key: `audit-${item.id}`,
        origin: "audit",
        chip: { label: IMPROVEMENT_KIND_LABEL[item.kind] ?? item.kind, cls: "approval-obsolete" },
        title: local?.question || item.answer_id || item.id,
        detail: `${item.reason ?? "—"} · ${new Date(item.created_at).toLocaleString("ja-JP")}`,
        created_at: item.created_at,
        localId: local?.id,
        resolved: local?.status === "resolved",
      });
    }
    for (const item of items) {
      if (consumed.has(item.id)) continue;
      merged.push({
        key: `local-${item.id}`,
        origin: "local",
        chip: { label: "👎 要改善", cls: "approval-obsolete" },
        title: item.question,
        detail: `理由: ${reasonLabel(item.reason)} · ${new Date(item.created_at).toLocaleString("ja-JP")}`,
        created_at: item.created_at,
        localId: item.id,
        resolved: item.status === "resolved",
      });
    }
    merged.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    return { rows: merged, mergedCount: consumed.size };
  }, [items, serverItems, feedbackRows]);

  const filteredRows = rows.filter((row) => {
    if (originFilter !== "all" && row.origin !== originFilter) return false;
    if (statusFilter === "resolved" && !row.resolved) return false;
    if (statusFilter === "open" && row.resolved) return false;
    return true;
  });
  const openCount = rows.filter((row) => !row.resolved).length;
  const resolvedLocalCount = items.filter((item) => item.status === "resolved").length;
  const originCounts = (origin: ImprovementOrigin) => rows.filter((row) => row.origin === origin).length;

  return (
    <>
      <p className="src-warning">
        保存済みフィードバック・監査ログ由来の改善候補・このブラウザの記録を 1 つのキューに統合して表示します
        （同じ回答への重複はまとめます）。
      </p>
      {feedbackRows === null && (
        <p className="ops-note" role="status">
          保存済みフィードバックを取得できませんでした（権限またはオフライン）。監査由来とこのブラウザの記録のみ表示しています。
        </p>
      )}
      <Section
        title="改善キュー"
        note={`未対応 ${openCount} 件 / 全 ${rows.length} 件（フィードバック ${originCounts("feedback")} · 監査 ${originCounts("audit")} · この端末 ${originCounts("local")}${mergedCount > 0 ? ` · 重複 ${mergedCount} 件を統合` : ""}）。対応済み状態はこの端末にのみ保存されます。`}
      >
        <div className="source-list-controls improve-queue-controls" aria-label="改善キューの絞り込み">
          <div className="source-list-filter" role="group" aria-label="由来で絞り込み">
            {(
              [
                ["all", "すべて"],
                ["feedback", "フィードバック"],
                ["audit", "監査"],
                ["local", "この端末"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={originFilter === value ? "source-filter-button active" : "source-filter-button"}
                aria-pressed={originFilter === value}
                onClick={() => setOriginFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="source-list-filter" role="group" aria-label="対応状況で絞り込み">
            {(
              [
                ["all", "すべて"],
                ["open", "未対応"],
                ["resolved", "対応済み"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={statusFilter === value ? "source-filter-button active" : "source-filter-button"}
                aria-pressed={statusFilter === value}
                onClick={() => setStatusFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {rows.length === 0 ? (
          <p className="ops-empty">
            まだ改善項目はありません。<Link href="/">質問する</Link> で回答に「👎 要改善」を付けると、ここに集約されます。
          </p>
        ) : filteredRows.length === 0 ? (
          <p className="ops-empty">条件に合う改善項目はありません。絞り込みを変更してください。</p>
        ) : (
          <div className="improve-list">
            {filteredRows.map((row) => (
              <article className={`improve-row ${row.resolved ? "is-resolved" : ""}`} key={row.key}>
                <div className="improve-row-titles">
                  <span className="improve-row-chips">
                    <span className={`citation-chip improve-origin improve-origin-${row.origin}`}>
                      {IMPROVEMENT_ORIGIN_LABEL[row.origin]}
                    </span>
                    <span className={`citation-chip ${row.chip.cls}`}>{row.chip.label}</span>
                    {row.localId && (
                      <span className={`citation-chip ${row.resolved ? "approval-approved" : "approval-obsolete"}`}>
                        {row.resolved ? "対応済み" : "未対応"}
                      </span>
                    )}
                  </span>
                  <strong>{row.title}</strong>
                  <span>{row.detail}</span>
                </div>
                <div className="improve-row-actions">
                  <Link className="button-link secondary" href="/sources/new">
                    文書を追加
                  </Link>
                  {row.origin === "local" ? (
                    <Link className="button-link secondary" href="/operations/quality">
                      品質 KPI
                    </Link>
                  ) : (
                    <Link className="button-link secondary" href="/admin/retrieval/debug">
                      再評価
                    </Link>
                  )}
                  {row.localId &&
                    (row.resolved ? (
                      <button type="button" onClick={() => reopen(row.localId as string)}>
                        未対応に戻す
                      </button>
                    ) : (
                      <button type="button" className="btn-approve" onClick={() => resolve(row.localId as string)}>
                        対応済みにする
                      </button>
                    ))}
                </div>
              </article>
            ))}
          </div>
        )}
        {resolvedLocalCount > 0 && (
          <div className="screen-actions">
            <button type="button" className="btn-reject" onClick={() => setConfirmClearResolved(true)}>
              対応済みをまとめて消去（{resolvedLocalCount} 件）
            </button>
          </div>
        )}
      </Section>
      {confirmClearResolved && (
        <ConfirmDialog
          title="対応済みをまとめて消去"
          body={`このブラウザで「対応済み」にした ${resolvedLocalCount} 件を消去します。未対応の項目とサーバ保存のフィードバック・監査記録は残ります。`}
          confirmLabel="消去する"
          danger
          onCancel={() => setConfirmClearResolved(false)}
          onConfirm={clearResolved}
        />
      )}
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
      {screen.id === "chatbot" && <ChatBotBody />}
      {screen.id === "phone" && <PhoneBody />}
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
      {screen.id === "users" && (
        <MockAdminScreen
          title="ユーザー"
          rows={MOCK_USERS}
          sampleNote="表示中のユーザー一覧はサンプルです。ユーザー管理（IdP 連携・招待）は準備中です。"
        />
      )}
      {screen.id === "roles-groups-acl" && <RolesAclBody />}
      {screen.id === "provider-policy" && <ProviderPolicyBody />}
      {screen.id === "retrieval-settings" && <RetrievalBody />}
      {screen.id === "retrieval-debug" && <RetrievalDebugBody />}
      {screen.id === "logging-privacy" && <LoggingPrivacyBody />}
      {screen.id === "integrations" && (
        <MockAdminScreen
          title="連携"
          rows={MOCK_SOURCES}
          sampleNote="表示中の連携一覧はサンプルです。実際の接続状況は「外部接続」で確認できます。"
        />
      )}
      {screen.id === "api-keys-webhooks" && <ApiKeysBody />}
      {screen.id === "usage-billing" && <BillingBody />}
      {screen.id === "support" && <SupportBody />}
      {screen.id === "add-source" && <AddSourceBody />}
      {screen.id === "file-browser" && <FileBrowserBody />}
    </ScreenShell>
  );
}

const ACCEPT_EXT = ".txt,.md,.markdown,.csv,.html,.htm,.docx,.xlsx,.pdf,.png,.jpg,.jpeg";

type AddSourceTypeId =
  | "text"
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
  /** U15: blocked client-side when empty (mirrors the answer-service connector requirements in
   *  src/raku_rag/services/datasource_sync.py); backend errors stay as the final net. */
  required?: boolean;
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
    id: "text",
    name: "テキストを貼り付け",
    desc: "手順・規格・トラブル対応の本文を貼り付けて取込",
    mono: "TXT",
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
    // U9: the Google OAuth connector (authorize → callback → server-side refresh token → sync) is
    // fully implemented — surface it as selectable. Live use needs GOOGLE_OAUTH_CLIENT_ID (+ the
    // GoogleOAuthConfigSecretName secret on the deploy); when absent, 接続 shows the not-configured error.
    id: "googledrive",
    name: "Google Drive",
    desc: "共有ドライブ・フォルダの文書を同期",
    mono: "GD",
    readiness: "ready",
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
  text: {
    fields: [],
    dataSourceType: "upload",
    note: APPROVAL_WORKFLOW_ENABLED
      ? "本文を貼り付けて、レビュー待ちのナレッジとして取込します。"
      : "本文を貼り付けて、すぐ質問に使えるナレッジとして取込します。",
  },
  url: {
    fields: [
      { id: "target_url", label: "クロール対象 URL", placeholder: "https://intranet.example/manuals", required: true },
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
      { id: "access_token", label: "アクセストークン", placeholder: "Box access token", type: "password", required: true },
    ],
    dataSourceType: "box",
    note: "アクセストークン（Bearer）方式でフォルダ内の文書を取込します。対応形式（txt/md/csv/html/docx/xlsx）のみ同期します。",
  },
  confluence: {
    fields: [
      { id: "site_url", label: "サイト URL", placeholder: "https://example.atlassian.net/wiki", required: true },
      { id: "space_key", label: "対象スペース", placeholder: "MFG", required: true },
      { id: "email", label: "メールアドレス", placeholder: "bot@example.com", required: true },
      { id: "api_token", label: "API トークン", placeholder: "Atlassian API token", type: "password", required: true },
    ],
    dataSourceType: "confluence",
    note: "API トークン方式（メール + トークンの Basic 認証）で対象スペースのページを取込します。",
  },
  notion: {
    fields: [
      { id: "database_id", label: "対象データベース ID", placeholder: "Notion database ID", required: true },
      { id: "integration_token", label: "インテグレーショントークン", placeholder: "secret_xxx", type: "password", required: true },
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
      { id: "subdomain", label: "サブドメイン", placeholder: "example.cybozu.com", required: true },
      { id: "api_token", label: "API トークン", placeholder: "API token", type: "password", required: true },
      { id: "app_id", label: "対象アプリ", placeholder: "123", required: true },
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
      { id: "bucket", label: "バケット名", placeholder: "raku-rag-documents", required: true },
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
      { id: "connection_string", label: "接続文字列", placeholder: "postgresql://… または mysql://user:pass@host:3306/db", type: "password", required: true }, // pragma: allowlist secret -- illustrative placeholder, not a credential
      { id: "table_name", label: "対象テーブル", placeholder: "public.maintenance_cases", required: true },
      { id: "updated_column", label: "更新検知列（任意）", placeholder: "updated_at" },
      { id: "allow_private_host", label: "内部ホストを許可（任意）", placeholder: "社内DBに接続する場合は true" },
    ],
    dataSourceType: "database",
    note: "PostgreSQL / MySQL の接続文字列と対象テーブルを保存して同期します。エンジンは接続文字列から自動判定（未指定時）。社内ネットワークの DB に接続する場合は内部ホスト許可を true にしてください。",
  },
};

/** U9: readiness badge copy — non-ready connectors surface as 対応予定 (near-term / roadmap). */
function sourceReadinessLabel(readiness: AddSourceType["readiness"]): string {
  if (readiness === "ready") return "利用可";
  if (readiness === "three_days") return "近日対応";
  return "ロードマップ";
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

type IngestApprovalStatus = "approved" | "pending_review" | "draft" | "obsolete";
type IngestApprovalSource = "imported" | "workflow";
type DatasourceApprovalPolicy = "review_required" | "trusted";

function defaultIngestApprovalStatus(): IngestApprovalStatus {
  return APPROVAL_WORKFLOW_ENABLED ? "pending_review" : "approved";
}

function defaultIngestApprovalSource(): IngestApprovalSource {
  return APPROVAL_WORKFLOW_ENABLED ? "workflow" : "imported";
}

function defaultDatasourceApprovalPolicy(): DatasourceApprovalPolicy {
  return APPROVAL_WORKFLOW_ENABLED ? "review_required" : "trusted";
}

function defaultApprovalEffectiveDate(): string | null {
  return defaultIngestApprovalStatus() === "approved" ? todayIso() : null;
}

function datasourceMappingApprovalDefaults(
  policy: DatasourceApprovalPolicy,
  effectiveDate?: string | null,
): Record<string, unknown> {
  const approved = policy === "trusted";
  const defaults: Record<string, unknown> = {
    approval_status: approved ? "approved" : "pending_review",
  };
  if (approved) {
    defaults.effective_date = effectiveDate || todayIso();
  }
  return defaults;
}

function applyApprovalWorkflowModeToConfig(config: Record<string, unknown>): Record<string, unknown> {
  if (APPROVAL_WORKFLOW_ENABLED) return config;
  const next: Record<string, unknown> = {
    ...config,
    approval_policy: "trusted",
    approval_effective_date: todayIso(),
  };
  if (next.mapping_profile && typeof next.mapping_profile === "object" && !Array.isArray(next.mapping_profile)) {
    const profile = next.mapping_profile as Record<string, unknown>;
    const defaults =
      profile.defaults && typeof profile.defaults === "object" && !Array.isArray(profile.defaults)
        ? (profile.defaults as Record<string, unknown>)
        : {};
    next.mapping_profile = {
      ...profile,
      defaults: {
        ...defaults,
        approval_status: "approved",
        effective_date: todayIso(),
      },
    };
  }
  return next;
}

function defaultSourceIdFor(sourceType: AddSourceTypeId): string {
  if (sourceType === "text") return `text-${Date.now().toString(36)}`;
  return `${sourceType}-${Date.now().toString(36)}`;
}

function sourceTypeForConfig(sourceType: AddSourceTypeId): string {
  if (sourceType === "text") return "text";
  return sourceType === "googledrive" ? "google_drive" : sourceType;
}

function addSourceTypeForDataSource(source: AdminDataSource): AddSourceTypeId | null {
  const config = (source.config ?? {}) as Record<string, unknown>;
  const rawKind = String(config.source_type || source.type || "").toLowerCase().replace(/-/g, "_");
  switch (rawKind) {
    case "box":
    case "confluence":
    case "notion":
    case "slack":
    case "kintone":
    case "sharepoint":
    case "onedrive":
    case "garoon":
    case "s3":
    case "url":
      return rawKind;
    case "google_drive":
    case "googledrive":
      return "googledrive";
    case "database":
    case "db":
    case "mysql":
    case "postgres":
    case "postgresql":
      return "db";
    case "object_storage":
      if (config.target_url) return "url";
      if (config.subdomain || config.app_id) return "kintone";
      if (config.document_library) return "sharepoint";
      if (config.target_folder) return "onedrive";
      if (config.target_space || config.login_name) return "garoon";
      return "s3";
    default:
      return null;
  }
}

function editableConfigValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

// S2-1 (#0034): live判定 — mirrors raku_rag.services.sync_scheduler.parse_sync_schedule so the
// admin sees WHETHER the entered schedule will actually auto-run (previously it silently did not).
function describeSyncSchedule(value: string): { label: string; active: boolean } {
  const text = value.trim();
  if (!text) return { label: "自動同期: 無効(未設定 — 手動同期のみ)", active: false };
  const lower = text.toLowerCase();
  if (["hourly", "毎時", "毎時間", "1時間ごと"].includes(lower)) {
    return { label: "自動同期: 有効(毎時)", active: true };
  }
  if (["weekly", "毎週"].includes(lower)) {
    return { label: "自動同期: 有効(7日ごと)", active: true };
  }
  const daily = text.match(/^(?:毎日|daily)\s*(?:([01]?\d|2[0-3])[:時]([0-5]\d)?\s*(?:分)?)?$/i);
  if (daily) {
    const hour = (daily[1] ?? "3").padStart(2, "0");
    const minute = daily[2] ?? "00";
    return { label: `自動同期: 有効(毎日 ${hour}:${minute})`, active: true };
  }
  const interval = text.match(/^(\d+)\s*(m|min|分|h|hour|時間|d|day|日)(?:ごと|毎|おき)?$/i);
  if (interval) {
    const unit = interval[2].toLowerCase();
    const unitLabel = ["m", "min", "分"].includes(unit) ? "分" : ["d", "day", "日"].includes(unit) ? "日" : "時間";
    return { label: `自動同期: 有効(${interval[1]}${unitLabel}ごと)`, active: true };
  }
  return { label: "自動同期: この形式は認識されません(自動同期されません)", active: false };
}

function editableConnectionValues(source: AdminDataSource, selectedConfig: AddSourceConfig): Record<string, string> {
  const config = (source.config ?? {}) as Record<string, unknown>;
  return Object.fromEntries(
    selectedConfig.fields.map((field) => {
      if (field.type === "password") return [field.id, ""];
      const value = field.id === "sync_schedule" ? source.sync_schedule ?? config[field.id] : config[field.id];
      return [field.id, editableConfigValue(value)];
    }),
  );
}

function hasStoredCredential(source: AdminDataSource): boolean {
  const config = (source.config ?? {}) as Record<string, unknown>;
  return Boolean(config.credential_status || config.credential_ref);
}

async function loadDataSourceDetail(sourceId: string): Promise<AdminDataSource> {
  const token = await getSessionToken();
  return apiGetJson<AdminDataSource>(`/admin/datasources/${encodeURIComponent(sourceId)}`, token);
}

async function ensureTrustedDatasourceForE2E(
  sourceId: string,
  token: string,
  source?: AdminDataSource,
): Promise<AdminDataSource | null> {
  if (APPROVAL_WORKFLOW_ENABLED) return source ?? null;
  const current =
    source ??
    (await apiGetJson<AdminDataSource>(
      `/admin/datasources/${encodeURIComponent(sourceId)}`,
      token,
    ));
  const currentConfig = (current.config ?? {}) as Record<string, unknown>;
  if (currentConfig.approval_policy === "trusted" && currentConfig.approval_effective_date) {
    return current;
  }
  const nextConfig = applyApprovalWorkflowModeToConfig(currentConfig);
  await apiPutJson(
    `/admin/datasources/${encodeURIComponent(current.source_id)}`,
    {
      collection_id: current.collection_id || DEMO_COLLECTION,
      type: current.type,
      config: nextConfig,
      sync_schedule: current.sync_schedule ?? null,
      status: current.status,
      reason: "approval_workflow_disabled_trusted_sync",
    },
    token,
  );
  return { ...current, config: nextConfig };
}

function SourceConnectionEditPanel({ sourceId, onSaved }: { sourceId: string; onSaved?: () => void }) {
  const [state, reload] = useLoad(() => loadDataSourceDetail(sourceId), [sourceId]);
  const [sourceName, setSourceName] = useState("");
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const toast = useToast();

  const datasource = state.state === "ready" ? state.data : null;
  const selectedSource = datasource ? addSourceTypeForDataSource(datasource) : null;
  const selectedConfig = selectedSource ? ADD_SOURCE_CONFIGS[selectedSource] : null;
  const selectedSourceDef = selectedSource
    ? ADD_SOURCE_TYPES.find((source) => source.id === selectedSource) ?? null
    : null;
  const credentialConfigured = datasource ? hasStoredCredential(datasource) : false;

  useEffect(() => {
    if (state.state !== "ready") return;
    const nextSelectedSource = addSourceTypeForDataSource(state.data);
    const nextConfig = nextSelectedSource ? ADD_SOURCE_CONFIGS[nextSelectedSource] : null;
    const config = (state.data.config ?? {}) as Record<string, unknown>;
    setSourceName(String(config.display_name || ""));
    setConfigValues(nextConfig ? editableConnectionValues(state.data, nextConfig) : {});
    setMessage(null);
  }, [state]);

  function onConfigChange(fieldId: string, value: string) {
    setConfigValues((current) => ({ ...current, [fieldId]: value }));
  }

  async function saveConnection(event: FormEvent) {
    event.preventDefault();
    if (!datasource || !selectedConfig || !selectedSource || saving) return;
    if (!sourceName.trim()) {
      setMessage({ tone: "error", text: "ソース名を入力してください。" });
      return;
    }

    setSaving(true);
    setMessage(null);
    try {
      const credentialFieldIds = new Set(
        selectedConfig.fields.filter((field) => field.type === "password").map((field) => field.id),
      );
      const credentials = Object.fromEntries(
        Object.entries(configValues)
          .filter(([key, value]) => credentialFieldIds.has(key) && value.trim())
          .map(([key, value]) => [key, value.trim()]),
      );
      const safeConfigValues = Object.fromEntries(
        Object.entries(configValues).filter(([key]) => !credentialFieldIds.has(key)),
      );
      const displayName = sourceDisplayName({
        rawName: sourceName,
        fallback: selectedSourceDef?.name ?? datasource.source_id,
      });
      const nextConfig = applyApprovalWorkflowModeToConfig({
        ...(datasource.config ?? {}),
        source_type: sourceTypeForConfig(selectedSource),
        display_name: displayName,
        oauth_provider: selectedConfig.oauth ?? null,
        ...safeConfigValues,
      });
      const hasSyncScheduleField = selectedConfig.fields.some((field) => field.id === "sync_schedule");
      const token = await getSessionToken();
      await apiPutJson(
        `/admin/datasources/${encodeURIComponent(datasource.source_id)}`,
        {
          collection_id: datasource.collection_id || DEMO_COLLECTION,
          type: datasource.type,
          config: nextConfig,
          credentials,
          sync_schedule: hasSyncScheduleField
            ? configValues.sync_schedule || null
            : datasource.sync_schedule ?? null,
          status: datasource.status,
          reason: "connection_settings_updated_from_source_detail",
        },
        token,
      );
      setMessage({ tone: "success", text: "接続設定を保存しました。変更を反映するには再同期してください。" });
      toast(`${displayName} の接続設定を保存しました。`, "success");
      onSaved?.();
    } catch (err) {
      const text = err instanceof Error ? err.message : "接続設定の保存に失敗しました";
      setMessage({ tone: "error", text });
      toast(text, "error");
    } finally {
      setSaving(false);
    }
  }

  if (state.state === "loading") {
    return <p className="ops-empty" role="status" aria-live="polite">接続設定を読み込み中…</p>;
  }
  if (state.state === "error") {
    return <ScreenLoadError error={state.error} onRetry={reload} />;
  }
  if (!datasource || !selectedConfig || !selectedSource) {
    return (
      <Section title="接続設定">
        <p className="source-config-note" role="alert">
          この接続種別は編集フォームに対応していません。設定を変更する場合は新しい外部接続を追加してください。
        </p>
      </Section>
    );
  }

  return (
    <form className="connector-form" onSubmit={saveConnection}>
      <Section
        title="接続設定"
        note="保存済みの外部接続名と同期対象を編集できます。認証情報は表示せず、入力した場合だけ差し替えます。"
      >
        <label className="source-name-field">
          <span>ソース名</span>
          <input
            value={sourceName}
            onChange={(e) => setSourceName(e.target.value)}
            placeholder={`例: ${selectedSourceDef?.name ?? "外部接続"} ナレッジ`}
            required
            aria-describedby="edit-source-name-help"
          />
          <small id="edit-source-name-help">
            {sourceKindLabel(sourceTypeForConfig(selectedSource))} として登録されています。
          </small>
        </label>

        {selectedConfig.oauth && (
          <div className="connector-oauth">
            <div>
              <strong>{selectedConfig.oauth} OAuth</strong>
              <span>
                {datasource.config?.connection_id
                  ? "OAuth 接続済みです。対象フォルダなどの設定を変更できます。"
                  : "OAuth 接続情報がまだありません。再接続が必要です。"}
              </span>
            </div>
            <Link className="button-link secondary" href="/sources/new">
              再接続
            </Link>
          </div>
        )}

        <div className="connector-form-grid">
          {selectedConfig.fields.map((field) => (
            <label key={field.id}>
              <span>{field.label}</span>
              <input
                type={field.type ?? "text"}
                value={configValues[field.id] ?? ""}
                onChange={(e) => onConfigChange(field.id, e.target.value)}
                placeholder={
                  field.type === "password" && credentialConfigured
                    ? "変更する場合だけ入力"
                    : field.placeholder
                }
                aria-describedby={field.type === "password" ? `edit-${field.id}-help` : undefined}
              />
              {field.type === "password" && (
                <small id={`edit-${field.id}-help`} className="connector-field-help">
                  {credentialConfigured
                    ? "保存済みの認証情報は表示しません。空欄のまま保存すると既存値を維持します。"
                    : "同期に必要な認証情報を入力してください。"}
                </small>
              )}
              {field.id === "sync_schedule" && (
                <small className="connector-field-help" role="status">
                  {describeSyncSchedule(configValues[field.id] ?? "").label}
                </small>
              )}
            </label>
          ))}
        </div>

        {message && (
          <p
            className={`source-list-message ${
              message.tone === "success" ? "success" : "error"
            } connection-edit-message`}
            role={message.tone === "error" ? "alert" : "status"}
            aria-live="polite"
          >
            {message.text}
          </p>
        )}

        <div className="screen-actions add-source-actions">
          <button type="submit" disabled={saving}>
            {saving ? "保存中…" : "接続設定を保存"}
          </button>
        </div>
      </Section>
    </form>
  );
}

interface UploadForIngestResult {
  ref: string;
  filename: string;
  content_type: string;
  size?: number;
  storage?: string;
  /** 0045: server-issued provenance id — sent to /v1/ingest so the ref resolves from the record */
  upload_id?: string;
}

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function cleanDocumentIdPart(value: string): string {
  return value
    .replace(/\.[^.]+$/, "")
    .replace(/[^A-Za-z0-9._-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80);
}

function fileNameStemForDisplay(fileName: string): string {
  return (fileName || "").replace(/\.[^.]+$/, "").trim();
}

function sourceDisplayName(params: {
  rawName: string;
  fallback: string;
  files?: File[];
}): string {
  const rawName = params.rawName.trim();
  if (rawName) return rawName;
  const files = params.files ?? [];
  if (files.length === 1) {
    return fileNameStemForDisplay(files[0]?.name ?? "") || params.fallback;
  }
  if (files.length > 1) return `${params.fallback} ${files.length}件`;
  return params.fallback;
}

function documentIdForUpload(params: {
  fileName: string;
  index: number;
  total: number;
}): string {
  const stem = cleanDocumentIdPart(params.fileName || "upload");
  if (params.total <= 1) {
    return stem || `doc-${Date.now().toString(36)}`;
  }
  const base = stem || `doc-${Date.now().toString(36)}`;
  const suffix = `-${params.index + 1}`;
  return `${base.slice(0, Math.max(1, 96 - suffix.length))}${suffix}`;
}

function selectedFilesTitle(files: File[]): string {
  if (files.length === 0) return "ファイルを選択（複数可・または、ここにドロップ）";
  if (files.length === 1) return files[0]?.name || "1 ファイルを選択";
  return `${files.length} 件のファイルを選択`;
}

function selectedFilesDetail(files: File[]): string {
  if (files.length === 0) {
    return ".txt / .md / .csv / .html / .docx / .xlsx / .pdf / .png / .jpg・各ファイル最大25MB";
  }
  const totalBytes = files.reduce((sum, item) => sum + item.size, 0);
  if (files.length === 1) return formatFileSize(files[0]?.size ?? 0);
  const sampleNames = files.slice(0, 3).map((item) => item.name || "upload.bin");
  const suffix = files.length > sampleNames.length ? ` ほか${files.length - sampleNames.length}件` : "";
  return `${sampleNames.join(" / ")}${suffix}・合計 ${formatFileSize(totalBytes)}`;
}

function uploadResultOk(status: string): boolean {
  return status === "succeeded" || status === "queued" || status === "running";
}

function uploadResultStatusLabel(status: string): string {
  if (status === "succeeded") return "成功";
  if (status === "queued") return "処理待ち";
  if (status === "running") return "処理中";
  if (status === "failed") return "失敗";
  return status;
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
    const uploadHeaders =
      presign.headers && typeof presign.headers === "object"
        ? Object.fromEntries(
            Object.entries(presign.headers).filter(
              (entry): entry is [string, string] => typeof entry[1] === "string",
            ),
          )
        : { "content-type": contentType };
    const uploadRes = await fetch(presign.upload_url, {
      method: "PUT",
      headers: uploadHeaders,
      body: file,
    });
    if (!uploadRes.ok) throw new Error(`S3 アップロードに失敗しました (HTTP ${uploadRes.status})`);
    return {
      ref: presign.ref,
      filename: typeof presign.filename === "string" ? presign.filename : file.name || "upload.bin",
      content_type: contentType,
      size: typeof presign.size === "number" ? presign.size : file.size,
      storage: "s3",
      upload_id: typeof presign.upload_id === "string" ? presign.upload_id : undefined,
    };
  }

  if (
    presignRes.status === 403 &&
    typeof presign.error === "string" &&
    presign.error.toLowerCase().includes("upload sink disabled")
  ) {
    throw new Error("この環境ではファイルアップロードが無効です。管理者にアップロード設定を確認してください。");
  }

  if (presignRes.status === 501) {
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

const FILE_BROWSER_FOLDER_KEY = "raku.fileFolders";
const FILE_BROWSER_PAGE_SIZE = 24;
const FILE_BROWSER_ROOT_FOLDER: FileBrowserFolder = {
  created_at: "",
  id: DEMO_COLLECTION,
  name: "フォルダなし",
};

type FileBrowserFolder = {
  created_at: string;
  id: string;
  name: string;
};

type FileBrowserFileRow = {
  approval_status: string;
  content_type?: string;
  document_id: string;
  effective_date: string | null;
  filename: string;
  folder_id: string;
  ingested_at?: string;
  source: "local" | "server";
};

type FileBrowserFilter = "all" | "needs_review" | "approved" | "obsolete";
const FILE_BROWSER_FILTERS: Array<{ label: string; value: FileBrowserFilter }> = [
  { label: "すべて", value: "all" },
  ...(APPROVAL_WORKFLOW_ENABLED ? [{ label: "レビュー待ち", value: "needs_review" as const }] : []),
  { label: "正式根拠", value: "approved" },
  { label: "旧版", value: "obsolete" },
];

function loadFileBrowserFolders(): FileBrowserFolder[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(FILE_BROWSER_FOLDER_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item): FileBrowserFolder | null => {
        if (!item || typeof item !== "object") return null;
        const id = (item as { id?: unknown }).id;
        const name = (item as { name?: unknown }).name;
        const createdAt = (item as { created_at?: unknown }).created_at;
        if (typeof id !== "string" || typeof name !== "string") return null;
        return {
          created_at: typeof createdAt === "string" ? createdAt : new Date().toISOString(),
          id,
          name,
        };
      })
      .filter((item): item is FileBrowserFolder => Boolean(item));
  } catch {
    return [];
  }
}

function saveFileBrowserFolders(folders: FileBrowserFolder[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(FILE_BROWSER_FOLDER_KEY, JSON.stringify(folders));
  } catch {
    /* best-effort */
  }
}

function normalizeFolderName(value: string): string {
  return value.trim().replace(/\s+/g, " ").slice(0, 64);
}

function fileBrowserFolderName(collectionId: string): string {
  if (!collectionId || collectionId === DEMO_COLLECTION) return FILE_BROWSER_ROOT_FOLDER.name;
  if (collectionId.startsWith("files-")) return collectionId.slice("files-".length) || "ファイル";
  return collectionId;
}

function uniqueFolderId(name: string, folders: FileBrowserFolder[]): string {
  const stem = cleanDocumentIdPart(name).toLowerCase() || Date.now().toString(36);
  const used = new Set(folders.map((folder) => folder.id));
  let candidate = `files-${stem}`;
  let index = 2;
  while (used.has(candidate)) {
    candidate = `files-${stem}-${index}`;
    index += 1;
  }
  return candidate;
}

function fileSourceId(folderId: string): string {
  return `file-${cleanDocumentIdPart(folderId) || "folder"}`.slice(0, 120);
}

function isRootFileFolder(folderId: string | null | undefined): boolean {
  return !folderId || folderId === DEMO_COLLECTION;
}

function isFileUploadSource(sourceId: string | null | undefined, sourceType?: string): boolean {
  const normalizedSourceId = String(sourceId || "").toLowerCase();
  const normalizedType = String(sourceType || "").toLowerCase();
  return (
    normalizedType === "upload" ||
    normalizedType === "file" ||
    normalizedSourceId === "upload" ||
    normalizedSourceId.startsWith("file-")
  );
}

function fileRowsFromDocs(
  localDocs: IngestedDoc[],
  apiDocs: ManufacturingDocumentSummary[],
): FileBrowserFileRow[] {
  const fileLocalDocs = localDocs.filter((doc) => isFileUploadSource(doc.source_id, doc.source_type));
  const localIds = new Set(fileLocalDocs.map((doc) => doc.document_id));
  const localRows = fileLocalDocs.map((doc) => ({
    approval_status: doc.approval_status,
    content_type: doc.content_type,
    document_id: doc.document_id,
    effective_date: doc.effective_date,
    filename: doc.filename || doc.document_id,
    folder_id: doc.collection_id || DEMO_COLLECTION,
    ingested_at: doc.ingested_at,
    source: "local" as const,
  }));
  const serverRows = apiDocs
    .filter((doc) => isFileUploadSource(doc.source_id) && !localIds.has(doc.document_id))
    .map((doc) => ({
      approval_status: doc.approval_status,
      document_id: doc.document_id,
      effective_date: doc.effective_date,
      filename: doc.document_id,
      folder_id: doc.collection_id || DEMO_COLLECTION,
      source: "server" as const,
    }));
  return [...localRows, ...serverRows];
}

function fileBrowserSearchText(row: FileBrowserFileRow): string {
  const approval = documentApprovalView(row.approval_status);
  return [
    row.filename,
    row.document_id,
    row.content_type,
    row.folder_id,
    approval.label,
    row.effective_date,
  ]
    .join(" ")
    .toLowerCase();
}

function fileBrowserMatchesFilter(row: FileBrowserFileRow, filter: FileBrowserFilter): boolean {
  if (filter === "needs_review") {
    return row.approval_status === "pending_review" || row.approval_status === "draft";
  }
  if (filter === "approved") return row.approval_status === "approved";
  if (filter === "obsolete") return row.approval_status === "obsolete";
  return true;
}

function FileFolderDialog({
  error,
  name,
  onCancel,
  onChange,
  onSubmit,
}: {
  error: string;
  name: string;
  onCancel: () => void;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  useDialog(true, onCancel, panelRef);

  return (
    <div className="cv-overlay" onMouseDown={onCancel}>
      <div
        className="fb-folder-dialog"
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="file-folder-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <form
          className="fb-folder-dialog-form"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <div className="fb-folder-dialog-head">
            <span className="cv-eyebrow">ファイル</span>
            <h3 id="file-folder-dialog-title">フォルダを作成</h3>
          </div>
          <label className="fb-new-folder-field">
            <span>フォルダ名</span>
            <input
              type="text"
              className="fb-new-folder-input"
              value={name}
              onChange={(event) => onChange(event.target.value)}
              aria-describedby={error ? "file-folder-error" : undefined}
              aria-invalid={error ? "true" : undefined}
              autoComplete="off"
              autoFocus
              maxLength={64}
            />
          </label>
          {error && (
            <p id="file-folder-error" className="fb-form-error" role="alert">
              {error}
            </p>
          )}
          <div className="fb-folder-dialog-actions">
            <button type="button" className="button-link secondary" onClick={onCancel}>
              キャンセル
            </button>
            <button type="submit" className="button-link btn-approve" disabled={!name.trim()}>
              作成
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function FileBrowserBody() {
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [folders, setFolders] = useState<FileBrowserFolder[]>([]);
  const [localDocs, setLocalDocs] = useState<IngestedDoc[]>([]);
  const [apiDocs, setApiDocs] = useState<ManufacturingDocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rootQuery, setRootQuery] = useState("");
  const [fileQuery, setFileQuery] = useState("");
  const [filter, setFilter] = useState<FileBrowserFilter>("all");
  const [page, setPage] = useState(1);
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [uploadFailures, setUploadFailures] = useState<string[]>([]);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [folderError, setFolderError] = useState("");
  const [syncingFiles, setSyncingFiles] = useState(false);
  const toast = useToast();

  async function reloadFiles({ showLoading = true }: { showLoading?: boolean } = {}): Promise<boolean> {
    if (showLoading) setLoading(true);
    setLoadError(null);
    setLocalDocs(loadIngestedDocs());
    try {
      const token = await getSessionToken();
      setApiDocs(await manufacturingDocuments(token));
      return true;
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "ファイル一覧を読み込めませんでした");
      return false;
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  useEffect(() => {
    setFolders(loadFileBrowserFolders());
    void reloadFiles();
  }, []);

  const fileRows = useMemo(() => fileRowsFromDocs(localDocs, apiDocs), [apiDocs, localDocs]);
  const allFolders = useMemo(() => {
    const byId = new Map<string, FileBrowserFolder>();
    for (const folder of folders) {
      byId.set(folder.id, folder);
    }
    for (const row of fileRows) {
      if (isRootFileFolder(row.folder_id)) continue;
      if (!byId.has(row.folder_id)) {
        byId.set(row.folder_id, {
          created_at: row.ingested_at || "",
          id: row.folder_id,
          name: fileBrowserFolderName(row.folder_id),
        });
      }
    }
    return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, "ja"));
  }, [fileRows, folders]);

  const currentFolder = currentFolderId
    ? allFolders.find((folder) => folder.id === currentFolderId) ?? {
        created_at: "",
        id: currentFolderId,
        name: fileBrowserFolderName(currentFolderId),
      }
    : null;
  const uploadTarget = currentFolder ?? FILE_BROWSER_ROOT_FOLDER;

  const visibleFolders = useMemo(() => {
    const needle = rootQuery.trim().toLowerCase();
    if (!needle) return allFolders;
    return allFolders.filter((folder) => folder.name.toLowerCase().includes(needle));
  }, [allFolders, rootQuery]);

  const folderRows = currentFolder
    ? fileRows.filter((row) => row.folder_id === currentFolder.id)
    : [];
  const rootRows = fileRows.filter((row) => isRootFileFolder(row.folder_id));
  const filteredRows = useMemo(() => {
    const needle = fileQuery.trim().toLowerCase();
    return folderRows.filter((row) => {
      if (!fileBrowserMatchesFilter(row, filter)) return false;
      if (!needle) return true;
      return fileBrowserSearchText(row).includes(needle);
    });
  }, [fileQuery, filter, folderRows]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / FILE_BROWSER_PAGE_SIZE));
  const pageRows = filteredRows.slice(
    (page - 1) * FILE_BROWSER_PAGE_SIZE,
    page * FILE_BROWSER_PAGE_SIZE,
  );
  const folderFileCount = (folderId: string) =>
    fileRows.filter((row) => row.folder_id === folderId).length;
  const reviewCount = folderRows.filter((row) =>
    row.approval_status === "pending_review" || row.approval_status === "draft"
  ).length;
  const approvedCount = folderRows.filter((row) => row.approval_status === "approved").length;
  const totalReviewCount = fileRows.filter((row) =>
    row.approval_status === "pending_review" || row.approval_status === "draft"
  ).length;
  const totalApprovedCount = fileRows.filter((row) => row.approval_status === "approved").length;

  useEffect(() => {
    setPage(1);
  }, [currentFolderId, fileQuery, filter]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  function closeNewFolderDialog() {
    setShowNewFolder(false);
    setNewFolderName("");
    setFolderError("");
  }

  function createFolder() {
    const name = normalizeFolderName(newFolderName);
    if (!name) {
      setFolderError("フォルダ名を入力してください");
      return;
    }
    if (allFolders.some((folder) => folder.name.toLowerCase() === name.toLowerCase())) {
      setFolderError("同じ名前のフォルダがあります");
      return;
    }
    const nextFolder = {
      created_at: new Date().toISOString(),
      id: uniqueFolderId(name, allFolders),
      name,
    };
    const nextFolders = [nextFolder, ...folders];
    setFolders(nextFolders);
    saveFileBrowserFolders(nextFolders);
    setFolderError("");
    setNewFolderName("");
    setShowNewFolder(false);
    setCurrentFolderId(null);
    setShowUploadForm(false);
    setRootQuery("");
    toast(`${name} を作成しました。`, "success");
  }

  async function syncFiles() {
    if (syncingFiles || loading || uploading) return;
    setSyncingFiles(true);
    const ok = await reloadFiles({ showLoading: false });
    setSyncingFiles(false);
    if (ok) {
      toast("ファイル一覧を同期しました。", "success");
    }
  }

  async function onUpload() {
    if (!files.length || uploading) return;
    setUploading(true);
    setUploadFailures([]);
    const failures: string[] = [];
    try {
      const token = await getSessionToken();
      const approvalStatus = defaultIngestApprovalStatus();
      const approvalEffectiveDate = defaultApprovalEffectiveDate();
      const approvalSource = defaultIngestApprovalSource();
      for (const [i, file] of files.entries()) {
        setUploadProgress(`${files.length} 件中 ${i + 1} 件目: ${file.name}`);
        try {
          const up = await uploadForIngest(file, token);
          const docId = documentIdForUpload({ fileName: up.filename, index: i, total: files.length });
          const ingest = await ingestDocument(
            {
              collection_id: uploadTarget.id,
              source_id: fileSourceId(uploadTarget.id),
              document_id: docId,
              ref: up.ref,
              upload_id: up.upload_id,
              content_type: up.content_type,
              manufacturing: {
                approval_status: approvalStatus,
                effective_date: approvalEffectiveDate,
                approval_source: approvalSource,
              },
            },
            token,
          );
          if (!uploadResultOk(ingest.status)) {
            throw new Error(ingest.failure_reason || "取込に失敗しました");
          }
          recordIngestedDoc({
            document_id: ingest.document_id ?? docId,
            collection_id: uploadTarget.id,
            source_id: fileSourceId(uploadTarget.id),
            source_name: uploadTarget.name,
            source_type: "upload",
            filename: up.filename,
            content_type: up.content_type,
            approval_status: approvalStatus,
            effective_date: approvalEffectiveDate,
            ingestion_run_id: ingest.ingestion_run_id,
            status: ingest.status,
            chunk_count: ingest.chunk_count ?? 0,
            ingested_at: new Date().toISOString(),
          });
        } catch (err) {
          failures.push(`${file.name}: ${err instanceof Error ? err.message : "取込に失敗しました"}`);
        }
      }
      setLocalDocs(loadIngestedDocs());
      void reloadFiles();
      if (failures.length === 0) {
        toast(`${files.length} 件を取込しました。`, "success");
        setFiles([]);
        setFileInputKey((key) => key + 1);
        setShowUploadForm(false);
      } else {
        setUploadFailures(failures);
        toast(`一部の取込に失敗しました: ${failures[0]}`, "warning");
      }
    } finally {
      setUploadProgress("");
      setUploading(false);
    }
  }

  function renderUploadPanel(panelId: string) {
    return (
      <div id={panelId} className="fb-upload-panel">
        <div className="fb-upload-head">
          <strong>{uploadTarget.name} にアップロード</strong>
          <span>PDF、Word、Excel、CSV、画像などを取り込んで、回答の根拠として管理します。</span>
        </div>
        <label className="upload-drop">
          <input
            key={fileInputKey}
            type="file"
            multiple
            accept={ACCEPT_EXT}
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
              setUploadFailures([]);
            }}
          />
          <span className="upload-drop-main">{selectedFilesTitle(files)}</span>
          <span className="upload-drop-sub">{selectedFilesDetail(files)}</span>
        </label>
        {uploadProgress && (
          <p className="source-config-note" role="status" aria-live="polite">
            {uploadProgress}
          </p>
        )}
        {uploadFailures.length > 0 && (
          <div className="fb-upload-errors" role="alert">
            {uploadFailures.slice(0, 3).map((failure) => (
              <p key={failure}>{failure}</p>
            ))}
          </div>
        )}
        <div className="screen-actions">
          <button type="button" onClick={() => void onUpload()} disabled={files.length === 0 || uploading}>
            {uploading ? "取込中..." : "アップロード取込"}
          </button>
          <button
            type="button"
            className="button-link secondary"
            onClick={() => {
              setShowUploadForm(false);
              setFiles([]);
              setFileInputKey((key) => key + 1);
              setUploadFailures([]);
            }}
          >
            キャンセル
          </button>
        </div>
      </div>
    );
  }

  function renderSyncButton() {
    return (
      <button
        type="button"
        className="button-link secondary"
        onClick={() => void syncFiles()}
        disabled={syncingFiles || loading || uploading}
        aria-label="ファイル一覧を同期"
      >
        {syncingFiles ? "同期中..." : "同期"}
      </button>
    );
  }

  function renderFileList(rows: FileBrowserFileRow[]) {
    return (
      <div className="fb-list" role="list">
        {rows.map((file) => {
          const approval = documentApprovalView(file.approval_status);
          return (
            <article key={`${file.source}-${file.document_id}`} className="fb-list-row" role="listitem">
              <div className="fb-list-main">
                <span className="fb-file-icon" aria-hidden="true" />
                <div className="fb-list-title">
                  <h4 title={file.filename}>{file.filename}</h4>
                  <p>{file.content_type || (file.source === "local" ? "アップロード済み文書" : "登録済み文書")}</p>
                </div>
              </div>
              <div className="fb-list-cell">
                <span className={`review-queue-status ${approval.cls}`}>{approval.label}</span>
                <span>{file.source === "local" ? "アップロード済み" : "文書一覧"}</span>
              </div>
              <div className="fb-list-cell">
                <span>{isRootFileFolder(file.folder_id) ? FILE_BROWSER_ROOT_FOLDER.name : fileBrowserFolderName(file.folder_id)}</span>
                <span>{file.effective_date ? `発効日 ${file.effective_date}` : "発効日なし"}</span>
              </div>
              <div className="fb-list-actions">
                <Link href={`/documents/${file.document_id}`} className="button-link secondary">
                  詳細
                </Link>
              </div>
            </article>
          );
        })}
      </div>
    );
  }

  if (!currentFolder) {
    return (
      <section className="fb-root">
        <div className="fb-toolbar">
          <div>
            <h2 className="fb-heading">ファイル</h2>
            <p className="fb-subtitle">アップロードした文書を、回答に使える根拠として整理します。</p>
          </div>
          <div className="fb-toolbar-actions">
            {renderSyncButton()}
            <button
              type="button"
              className="button-link btn-approve"
              aria-controls="root-file-upload-panel"
              aria-expanded={showUploadForm}
              onClick={() => {
                setShowUploadForm((shown) => !shown);
                setUploadFailures([]);
                setShowNewFolder(false);
                setNewFolderName("");
                setFolderError("");
              }}
            >
              アップロード
            </button>
            <button
              type="button"
              className="button-link secondary"
              aria-haspopup="dialog"
              onClick={() => {
                setShowNewFolder(true);
                setNewFolderName("");
                setFolderError("");
                setShowUploadForm(false);
              }}
            >
              フォルダを作成
            </button>
          </div>
        </div>
        <section className="work-stat-strip fb-overview" aria-label="ファイル管理の概況">
          <WorkStat label="フォルダ" value={`${allFolders.length} 件`} detail="整理済みのまとまり" />
          <WorkStat label="ファイル" value={`${fileRows.length} 件`} detail={`フォルダなし ${rootRows.length} 件`} />
          <WorkStat label="レビュー待ち" value={`${totalReviewCount} 件`} detail="正式根拠にする前に確認" tone={totalReviewCount > 0 ? "wait" : "neutral"} />
          <WorkStat label="正式根拠" value={`${totalApprovedCount} 件`} detail="回答で優先利用" tone="ok" />
        </section>
        {showUploadForm && renderUploadPanel("root-file-upload-panel")}
        {showNewFolder && (
          <FileFolderDialog
            error={folderError}
            name={newFolderName}
            onCancel={closeNewFolderDialog}
            onChange={(value) => {
              setNewFolderName(value);
              if (folderError) setFolderError("");
            }}
            onSubmit={createFolder}
          />
        )}
        {loadError && <ScreenLoadError error={loadError} onRetry={() => void reloadFiles()} />}
        {!loadError && (
          <>
            <section className="source-list-controls fb-controls" aria-label="フォルダの検索">
              <label className="standalone-search source-list-search">
                <span aria-hidden="true">⌕</span>
                <input
                  value={rootQuery}
                  onChange={(event) => setRootQuery(event.target.value)}
                  placeholder="フォルダ名で検索"
                  aria-label="フォルダ名で検索"
                />
              </label>
              <div className="source-list-summary" aria-live="polite">
                <span>{visibleFolders.length} フォルダ</span>
                <span>{fileRows.length} ファイル</span>
              </div>
            </section>
            {loading ? (
              <p className="fb-empty" role="status" aria-live="polite">読み込み中...</p>
            ) : allFolders.length === 0 && rootRows.length === 0 ? (
              <div className="standalone-empty-state">
                <h4>ファイルはまだありません</h4>
                <p>まずは業務手順書やFAQをアップロードすると、質問とチャットボットの根拠として使えます。</p>
                <button type="button" className="standalone-empty-cta" onClick={() => setShowUploadForm(true)}>
                  アップロード
                </button>
              </div>
            ) : allFolders.length > 0 && visibleFolders.length === 0 ? (
              <div className="standalone-empty-state">
                <h4>条件に合うフォルダはありません</h4>
                <button type="button" className="standalone-empty-cta" onClick={() => setRootQuery("")}>
                  検索をクリア
                </button>
              </div>
            ) : visibleFolders.length > 0 ? (
              <div className="fb-list" role="list">
                {visibleFolders.map((folder) => (
                  <article
                    key={folder.id}
                    className="fb-list-row fb-folder-row"
                    role="listitem"
                  >
                    <div className="fb-list-main">
                      <span className="fb-folder-icon" aria-hidden="true" />
                      <div className="fb-list-title">
                        <h4>{folder.name}</h4>
                        <p>フォルダ</p>
                      </div>
                    </div>
                    <div className="fb-list-cell">
                      <span>{folderFileCount(folder.id)} 件</span>
                      <span>{folder.created_at ? `作成 ${folder.created_at.slice(0, 10)}` : "作成日なし"}</span>
                    </div>
                    <div className="fb-list-cell">
                      <span>フォルダ内で検索・アップロードできます</span>
                      <span>根拠文書をまとめて管理</span>
                    </div>
                    <div className="fb-list-actions">
                      <button
                        type="button"
                        className="button-link secondary fb-list-open"
                        onClick={() => {
                          setCurrentFolderId(folder.id);
                          setShowUploadForm(false);
                        }}
                      >
                        開く
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
            {!loading && rootRows.length > 0 && (
              <section className="fb-root-files" aria-label="フォルダなしのファイル">
                <div className="fb-section-heading">
                  <h3>フォルダなし</h3>
                  <span>{rootRows.length} 件</span>
                </div>
                {renderFileList(rootRows)}
              </section>
            )}
          </>
        )}
      </section>
    );
  }

  return (
    <section className="fb-root">
      <nav className="fb-breadcrumb" aria-label="パス">
        <button
          type="button"
          className="fb-bc-link"
          onClick={() => {
            setCurrentFolderId(null);
            setShowUploadForm(false);
            setFiles([]);
            setUploadFailures([]);
          }}
        >
          ファイル
        </button>
        <span className="fb-bc-sep" aria-hidden="true">›</span>
        <span className="fb-bc-current">{currentFolder.name}</span>
      </nav>
      <div className="fb-toolbar">
        <div>
          <h2 className="fb-heading">{currentFolder.name}</h2>
          <p className="fb-subtitle">このフォルダ内の文書と承認状態を確認します。</p>
        </div>
        <div className="fb-toolbar-actions">
          {renderSyncButton()}
          <button
            type="button"
            className="button-link btn-approve"
            aria-controls="file-upload-panel"
            aria-expanded={showUploadForm}
            onClick={() => setShowUploadForm((shown) => !shown)}
          >
            アップロード
          </button>
        </div>
      </div>
      <section className="work-stat-strip fb-overview" aria-label={`${currentFolder.name} の概況`}>
        <WorkStat label="ファイル" value={`${folderRows.length} 件`} detail="このフォルダ内" />
        <WorkStat label="表示中" value={`${filteredRows.length} 件`} detail="検索・絞り込み後" />
        <WorkStat label="レビュー待ち" value={`${reviewCount} 件`} detail="正式根拠にする前に確認" tone={reviewCount > 0 ? "wait" : "neutral"} />
        <WorkStat label="正式根拠" value={`${approvedCount} 件`} detail="回答で優先利用" tone="ok" />
      </section>
      {showUploadForm && (
        renderUploadPanel("file-upload-panel")
      )}
      <section className="source-list-controls fb-controls" aria-label="ファイルの検索と絞り込み">
        <label className="standalone-search source-list-search">
          <span aria-hidden="true">⌕</span>
          <input
            value={fileQuery}
            onChange={(event) => setFileQuery(event.target.value)}
            placeholder="ファイル名・状態で検索"
            aria-label="ファイル名・状態で検索"
          />
        </label>
        <div className="source-list-filter" role="group" aria-label="ファイル状態で絞り込み">
          {FILE_BROWSER_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              className={filter === option.value ? "source-filter-button active" : "source-filter-button"}
              aria-pressed={filter === option.value}
              onClick={() => setFilter(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="source-list-summary" aria-live="polite">
          <span>{filteredRows.length} 件表示</span>
          {APPROVAL_WORKFLOW_ENABLED && <span>レビュー待ち {reviewCount} 件</span>}
          <span>正式根拠 {approvedCount} 件</span>
        </div>
      </section>
      {loading ? (
        <p className="fb-empty" role="status" aria-live="polite">読み込み中...</p>
      ) : folderRows.length === 0 ? (
        <div className="standalone-empty-state">
          <h4>ファイルはまだありません</h4>
          <button type="button" className="standalone-empty-cta" onClick={() => setShowUploadForm(true)}>
            アップロード
          </button>
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="standalone-empty-state">
          <h4>条件に合うファイルはありません</h4>
          <button
            type="button"
            className="standalone-empty-cta"
            onClick={() => {
              setFileQuery("");
              setFilter("all");
            }}
          >
            条件をクリア
          </button>
        </div>
      ) : (
        <>
          {renderFileList(pageRows)}
          {totalPages > 1 && (
            <nav className="source-list-pagination" aria-label="ファイルのページ">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
              >
                前へ
              </button>
              <span>
                {page} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                disabled={page >= totalPages}
              >
                次へ
              </button>
            </nav>
          )}
        </>
      )}
    </section>
  );
}

function AddSourceBody() {
  const [step, setStep] = useState<"select" | "configure">("select");
  const [selectedSource, setSelectedSource] = useState<AddSourceTypeId>("text");
  const [text, setText] = useState("");
  const [sourceName, setSourceName] = useState("");
  // U15: 回答範囲 — rendered as a select (options = the collections the workspace already knows).
  const [collectionId, setCollectionId] = useState(DEMO_COLLECTION);
  const collections = useKnownCollections();
  const [sourceId, setSourceId] = useState(() => defaultSourceIdFor("text"));
  const [approvalStatus] = useState<IngestApprovalStatus>(() => defaultIngestApprovalStatus());
  const [effectiveDate] = useState(() => defaultApprovalEffectiveDate() ?? todayIso());
  const [approvalPolicy] = useState<DatasourceApprovalPolicy>(() => defaultDatasourceApprovalPolicy());
  const [mappingProfileType, setMappingProfileType] = useState<DataSourceProfileType>("auto");
  const [mappingRequiredFields, setMappingRequiredFields] = useState(
    PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "),
  );
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const [uploadFailures, setUploadFailures] = useState<string[]>([]);
  const [result, setResult] = useState<IngestedDoc[]>([]);
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  // U15: per-field inline validation errors (key = field id, or "source_name" for the name field).
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [configSaving, setConfigSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const toast = useToast();
  const [syncResult, setSyncResult] = useState<AdminSourceSyncResponse | null>(null);
  const [connectionTest, setConnectionTest] = useState<{
    status: "idle" | "testing" | "ok" | "error";
    message: string;
    sampleCount?: number;
    sourceId?: string;
  }>({ status: "idle", message: "" });
  const [previewReady, setPreviewReady] = useState(false);
  // Google Drive OAuth connection (021-gdrive). connectionId is the only credential the form keeps;
  // the refresh token lives server-side. saveDatasource gates on it for google_drive.
  const [oauthStatus, setOauthStatus] = useState<"idle" | "connecting" | "connected" | "error">("idle");
  const [oauthConnectionId, setOauthConnectionId] = useState<string>("");
  const [oauthError, setOauthError] = useState<string | null>(null);

  const selectedSourceDef = ADD_SOURCE_TYPES.find((source) => source.id === selectedSource) ?? ADD_SOURCE_TYPES[0];
  const selectedConfig = ADD_SOURCE_CONFIGS[selectedSource];
  const needsOAuthConnection = selectedConfig.dataSourceType === "google_drive";

  function resetConnectionValidation() {
    setConnectionTest({ status: "idle", message: "" });
    setPreviewReady(false);
  }

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
        resetConnectionValidation();
      } else {
        setOauthStatus("error");
        setOauthError(typeof data.error === "string" ? data.error : "接続に失敗しました");
        resetConnectionValidation();
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  async function onConnectGoogle() {
    setOauthError(null);
    setOauthStatus("connecting");
    resetConnectionValidation();
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
    setStep("select");
    setSourceId(defaultSourceIdFor(sourceIdValue));
    setSourceName("");
    setConfigValues({});
    setFieldErrors({});
    setText("");
    setResult([]);
    setUploadProgress("");
    setUploadFailures([]);
    setSyncResult(null);
    resetConnectionValidation();
    setOauthStatus("idle");
    setOauthConnectionId("");
    setOauthError(null);
    setMappingProfileType("auto");
    setMappingRequiredFields(PREVIEW_REQUIRED_FIELDS_BY_PROFILE.auto.join(", "));
  }

  function onConfigChange(fieldId: string, value: string) {
    setConfigValues((current) => ({ ...current, [fieldId]: value }));
    setFieldErrors((current) => {
      if (!(fieldId in current)) return current;
      const next = { ...current };
      delete next[fieldId];
      return next;
    });
    resetConnectionValidation();
  }

  // U15: client-side required-field validation for the connector form. Sets inline errors, focuses
  // the first invalid input, and blocks save/test/sync until valid (backend errors stay the final net).
  function validateConnectorForm(): boolean {
    const errors: Record<string, string> = {};
    if (!sourceName.trim()) {
      errors.source_name = "ソース名を入力してください。";
    }
    for (const field of selectedConfig.fields) {
      if (field.required && !(configValues[field.id] ?? "").trim()) {
        errors[field.id] = `${field.label}は必須です。`;
      }
    }
    setFieldErrors(errors);
    const firstInvalid = errors.source_name
      ? "add-source-name"
      : Object.keys(errors).length > 0
        ? `add-source-field-${Object.keys(errors)[0]}`
        : null;
    if (firstInvalid) {
      document.getElementById(firstInvalid)?.focus();
      toast("入力内容を確認してください。必須項目が未入力です。", "error");
      return false;
    }
    return true;
  }

  async function saveDatasource(): Promise<string | null> {
    if (selectedSource === "text" || configSaving || syncing) return null;
    if (!validateConnectorForm()) return null;
    if (needsOAuthConnection && !oauthConnectionId) {
      toast("先に「Google で接続」で OAuth 認可を完了してください。", "error");
      return null;
    }
    setSyncResult(null);
    setConfigSaving(true);
    try {
      const datasourceId = sourceId.trim() || selectedSource;
      const displayName = sourceDisplayName({
        rawName: sourceName,
        fallback: selectedSourceDef.name,
      });
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
      const mappingDefaults = datasourceMappingApprovalDefaults(approvalPolicy, effectiveDate);
      await apiPutJson(
        `/admin/datasources/${encodeURIComponent(datasourceId)}`,
        {
          collection_id: collectionId.trim() || "manuals",
          type: selectedConfig.dataSourceType,
          config: {
            // Backend dispatch key. It matches the AddSourceTypeId for every connector EXCEPT
            // google_drive (UI id 'googledrive' -> dispatch/type 'google_drive').
            source_type: selectedSource === "googledrive" ? "google_drive" : selectedSource,
            display_name: displayName,
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
      toast(`${displayName} の接続設定を保存しました。`, "success");
      return datasourceId;
    } catch (err) {
      toast(err instanceof Error ? err.message : "接続設定の保存に失敗しました", "error");
      return null;
    } finally {
      setConfigSaving(false);
    }
  }

  async function onTestConnection() {
    if (selectedSource === "text" || configSaving || syncing || connectionTest.status === "testing") return;
    setPreviewReady(false);
    setConnectionTest({ status: "testing", message: "接続設定を保存して疎通確認しています。" });
    const datasourceId = await saveDatasource();
    if (!datasourceId) {
      setConnectionTest({ status: "error", message: "接続テストの前に保存が完了しませんでした。" });
      return;
    }
    try {
      const token = await getSessionToken();
      const result = await adminSourceTestConnection(
        datasourceId,
        { collection_id: collectionId.trim() || "manuals", limit: 1 },
        token,
      );
      const sampleCount = typeof result.sample_count === "number" ? result.sample_count : undefined;
      setConnectionTest({
        status: "ok",
        message:
          sampleCount !== undefined
            ? `接続できました。同期候補を ${sampleCount} 件確認しました。`
            : "接続できました。同期を開始できます。",
        sampleCount,
        sourceId: datasourceId,
      });
      toast("接続テストに成功しました。", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "接続テストに失敗しました";
      setConnectionTest({ status: "error", message });
      toast(message, "error");
    }
  }

  async function onSaveDatasource(event: FormEvent) {
    event.preventDefault();
    await saveDatasource();
  }

  async function onSaveAndSync() {
    if (syncing || configSaving) return;
    if (connectionTest.status !== "ok") {
      toast("同期開始の前に接続テストを実行してください。", "warning");
      return;
    }
    if (!previewReady) {
      toast("同期開始の前に取込プレビューを実行してください。", "warning");
      return;
    }
    const datasourceId = await saveDatasource();
    if (!datasourceId) return;
    setSyncing(true);
    try {
      const token = await getSessionToken();
      // No approval block here: the server derives every synced file's approval state from the saved
      // datasource trust policy (config.approval_policy), so the sync request can never self-grant
      // 'approved'. In the current E2E mode the UI saves trusted sources so synced docs are usable.
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
        source_name: sourceDisplayName({
          rawName: sourceName,
          fallback: selectedSourceDef.name,
        }),
        source_type: sourceTypeForConfig(selectedSource),
        collection_id: sync.collection_id,
        status: sync.status,
        observed_count: sync.observed_count,
        changed_count: sync.changed_count,
        failed_count: sync.failed_count,
        synced_at: new Date().toISOString(),
      });
      toast(`${sourceDisplayName({ rawName: sourceName, fallback: selectedSourceDef.name })} の同期を開始しました。`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "同期開始に失敗しました", "error");
    } finally {
      setSyncing(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setResult([]);
    setUploadFailures([]);
    setUploadProgress("");

    if (selectedSource !== "text") {
      toast("この外部接続は接続設定フォームから保存してください。", "error");
      return;
    }
    if (!sourceName.trim()) {
      toast("ソース名を入力してください。", "error");
      return;
    }

    const trimmed = text.trim();
    if (!trimmed) {
      toast("テキストを入力してください。", "error");
      return;
    }
    const textFileBase = cleanDocumentIdPart(sourceName.trim()) || `pasted-${Date.now().toString(36)}`;
    const payloads = [
      new File([trimmed], `${textFileBase}.txt`, {
        type: "text/plain",
      }),
    ];

    setSubmitting(true);
    const records: IngestedDoc[] = [];
    const failures: string[] = [];
    const displayName = sourceDisplayName({
      rawName: sourceName,
      fallback: selectedSourceDef.name,
    });
    const displayType = sourceTypeForConfig(selectedSource);
    const requestSourceId = sourceId.trim() || defaultSourceIdFor("text");
    try {
      const token = await getSessionToken();
      for (const [index, payload] of payloads.entries()) {
        setUploadProgress("テキストを取込中...");
        try {
          const up = await uploadForIngest(payload, token);
          const docId = documentIdForUpload({
            fileName: up.filename,
            index,
            total: payloads.length,
          });

          const ingest = await ingestDocument(
            {
              collection_id: collectionId.trim() || "manuals",
              source_id: requestSourceId,
              document_id: docId,
              ref: up.ref,
              upload_id: up.upload_id,
              content_type: up.content_type,
              manufacturing: {
                approval_status: approvalStatus,
                effective_date: effectiveDate || null,
                approval_source: defaultIngestApprovalSource(),
              },
            },
            token,
          );

          const record: IngestedDoc = {
            document_id: ingest.document_id ?? docId,
            collection_id: collectionId.trim() || "manuals",
            source_id: requestSourceId,
            source_name: displayName,
            source_type: displayType,
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
          records.push(record);
          if (ingest.failure_reason || ingest.status === "failed") {
            failures.push(`${up.filename}: ${ingest.failure_reason || "取込に失敗しました"}`);
          }
        } catch (err) {
          failures.push(`${payload.name || "upload.bin"}: ${err instanceof Error ? err.message : "取込に失敗しました"}`);
        }
      }
      setResult(records);
      setUploadFailures(failures);
      const acceptedCount = records.filter((item) => uploadResultOk(item.status)).length;
      if (failures.length === 0) {
        setText("");
        setSourceId(defaultSourceIdFor("text"));
        setSourceName("");
      }
      if (failures.length === 0) {
        toast(`${acceptedCount} 件の取込を受け付けました。`, "success");
      } else if (acceptedCount > 0) {
        toast(`${acceptedCount} 件受付、${failures.length} 件は要確認です。${failures[0]}`, "warning");
      } else {
        toast(`${failures.length} 件の取込に失敗しました。${failures[0]}`, "error");
      }
    } finally {
      setUploadProgress("");
      setSubmitting(false);
    }
  }

  const resultAcceptedCount = result.filter((item) => uploadResultOk(item.status)).length;
  const resultAttentionCount = result.length - resultAcceptedCount + uploadFailures.length;
  const resultAttemptCount = result.length + uploadFailures.length;
  const resultSourceName =
    result.find((item) => item.source_name)?.source_name ||
    sourceDisplayName({ rawName: sourceName, fallback: selectedSourceDef.name });
  const resultSourceType = result.find((item) => item.source_type)?.source_type || sourceTypeForConfig(selectedSource);

  return (
    <>
      {step === "select" && (
        <Section title="外部接続の種別" note="接続するサービス（またはテキスト貼り付け）を選択してください。">
          {/* U9: show the full connector lineup — ready ones selectable, the rest disabled with a
              対応予定 badge — so coverage is visible without creating dead configuration paths. */}
          <div className="source-type-grid">
            {ADD_SOURCE_TYPES.map((source) => {
              const selectable = source.readiness === "ready";
              return (
                <button
                  key={source.id}
                  type="button"
                  className={`source-type-card ${selectedSource === source.id ? "active" : ""}`}
                  aria-pressed={selectable ? selectedSource === source.id : undefined}
                  disabled={!selectable}
                  title={selectable ? undefined : `${source.name} は対応予定です`}
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
              );
            })}
          </div>
          <p className="source-config-note">{selectedConfig.note}</p>
          <div className="screen-actions add-source-actions">
            <button type="button" onClick={() => setStep("configure")}>
              次へ →
            </button>
          </div>
        </Section>
      )}

      {step === "configure" && (
        <button
          type="button"
          className="add-source-back"
          onClick={() => setStep("select")}
        >
          ← 外部接続の種別選択に戻る
        </button>
      )}

      {step === "configure" && selectedSource === "text" && (
        <form className="upload-form" onSubmit={onSubmit}>
          <Section
            title="テキストを貼り付け"
            note={
              APPROVAL_WORKFLOW_ENABLED
                ? "手順・規格・トラブル対応などの本文を貼り付けて、レビュー待ちのナレッジとして取込します。"
                : "手順・規格・トラブル対応などの本文を貼り付けて、すぐ質問に使えるナレッジとして取込します。"
            }
          >
            <label className="source-name-field">
              <span>ソース名</span>
              <input
                value={sourceName}
                onChange={(e) => setSourceName(e.target.value)}
                placeholder="例: 品質保証マニュアルの抜粋"
                required
                aria-describedby="text-source-name-help"
              />
              <small id="text-source-name-help">
                {sourceKindLabel(sourceTypeForConfig(selectedSource))} として登録されます。
              </small>
            </label>

            <label className="source-name-field">
              <span>回答範囲（コレクション）</span>
              <select
                value={collectionId}
                onChange={(e) => setCollectionId(e.target.value)}
                aria-label="回答範囲（コレクション）"
              >
                {(collections.includes(collectionId) ? collections : [collectionId, ...collections]).map((id) => (
                  <option key={id} value={id}>
                    {collectionDisplayName(id)}
                  </option>
                ))}
              </select>
              <small>取込した文書は、このコレクションを参照する質問・チャットで利用できます。</small>
            </label>

            <textarea
              className="upload-textarea"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="ここに手順・規格・トラブル対応の本文を貼り付け…"
              rows={8}
              aria-label="取込するテキスト本文"
              required
            />

            <div className="screen-actions add-source-actions">
              <button type="submit" disabled={submitting}>
                {submitting ? "取込中…" : "テキストを取込"}
              </button>
            </div>
            {uploadProgress && (
              <p className="source-config-note" role="status" aria-live="polite">
                {uploadProgress}
              </p>
            )}
          </Section>
        </form>
      )}

      {step === "configure" && selectedSource !== "text" && (
        <form className="connector-form" onSubmit={onSaveDatasource}>
          <Section title={`${selectedSourceDef.name} の接続設定`} note={selectedSourceDef.desc}>
            <label className="source-name-field">
              <span>
                ソース名 <span className="req-mark" aria-hidden="true">*</span>
              </span>
              <input
                id="add-source-name"
                value={sourceName}
                onChange={(e) => {
                  setSourceName(e.target.value);
                  setFieldErrors((current) => {
                    if (!("source_name" in current)) return current;
                    const next = { ...current };
                    delete next.source_name;
                    return next;
                  });
                  resetConnectionValidation();
                }}
                placeholder={`例: ${selectedSourceDef.name} ナレッジ`}
                required
                aria-invalid={fieldErrors.source_name ? true : undefined}
                aria-describedby={
                  fieldErrors.source_name ? "connector-source-name-error" : "connector-source-name-help"
                }
              />
              {fieldErrors.source_name && (
                <span className="field-error" id="connector-source-name-error" role="alert">
                  {fieldErrors.source_name}
                </span>
              )}
              <small id="connector-source-name-help">
                {sourceKindLabel(sourceTypeForConfig(selectedSource))} として登録されます。
              </small>
            </label>

            <label className="source-name-field">
              <span>回答範囲（コレクション）</span>
              <select
                value={collectionId}
                onChange={(e) => {
                  setCollectionId(e.target.value);
                  resetConnectionValidation();
                }}
                aria-label="回答範囲（コレクション）"
              >
                {(collections.includes(collectionId) ? collections : [collectionId, ...collections]).map((id) => (
                  <option key={id} value={id}>
                    {collectionDisplayName(id)}
                  </option>
                ))}
              </select>
              <small>同期した文書は、このコレクションを参照する質問・チャットで利用できます。</small>
            </label>

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
              {selectedConfig.fields.map((field) => (
                <label key={field.id}>
                  <span>
                    {field.label}
                    {field.required && (
                      <>
                        {" "}
                        <span className="req-mark" aria-hidden="true">*</span>
                      </>
                    )}
                  </span>
                  <input
                    id={`add-source-field-${field.id}`}
                    type={field.type ?? "text"}
                    value={configValues[field.id] ?? ""}
                    onChange={(e) => onConfigChange(field.id, e.target.value)}
                    placeholder={field.placeholder}
                    aria-required={field.required || undefined}
                    aria-invalid={fieldErrors[field.id] ? true : undefined}
                    aria-describedby={fieldErrors[field.id] ? `add-source-field-${field.id}-error` : undefined}
                  />
                  {fieldErrors[field.id] && (
                    <span className="field-error" id={`add-source-field-${field.id}-error`} role="alert">
                      {fieldErrors[field.id]}
                    </span>
                  )}
                </label>
              ))}
            </div>

            {connectionTest.status !== "idle" && (
              <p
                className={`source-list-message ${
                  connectionTest.status === "ok" ? "success" : connectionTest.status === "error" ? "error" : ""
                } connection-edit-message`}
                role={connectionTest.status === "error" ? "alert" : "status"}
                aria-live="polite"
              >
                {connectionTest.message}
              </p>
            )}
            {connectionTest.status === "ok" && !previewReady && (
              <p
                id="add-source-preview-required"
                className="source-config-note"
                role="status"
                aria-live="polite"
              >
                同期開始の前に、下の取込プレビューを実行してください。
              </p>
            )}

            <div className="screen-actions add-source-actions">
              <button type="submit" disabled={configSaving}>
                {configSaving ? "保存中…" : "接続設定を保存"}
              </button>
              <button
                type="button"
                onClick={onTestConnection}
                disabled={configSaving || syncing || connectionTest.status === "testing"}
              >
                {connectionTest.status === "testing" ? "接続確認中…" : "接続テスト"}
              </button>
              <button
                type="button"
                onClick={onSaveAndSync}
                disabled={configSaving || syncing || connectionTest.status !== "ok" || !previewReady}
                aria-describedby={
                  connectionTest.status === "ok" && !previewReady ? "add-source-preview-required" : undefined
                }
              >
                {syncing ? "同期中…" : "保存して同期開始"}
              </button>
            </div>
          </Section>
        </form>
      )}

      {step === "configure" &&
        selectedSource !== "text" &&
        connectionTest.status === "ok" &&
        connectionTest.sourceId && (
          <SourcePreviewPanel
            key={connectionTest.sourceId}
            sourceId={connectionTest.sourceId}
            collectionId={collectionId.trim() || "manuals"}
            onPreviewReadyChange={setPreviewReady}
          />
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
              ["ソース名", sourceDisplayName({ rawName: sourceName, fallback: selectedSourceDef.name })],
              ["種別", sourceKindLabel(sourceTypeForConfig(selectedSource))],
              ["対象ドキュメント", String(syncResult.observed_count)],
              ["開始した取込", String(syncResult.changed_count)],
              ["失敗", String(syncResult.failed_count)],
            ]}
          />
          <div className="screen-actions">
            <Link className="button-link secondary" href="/ingestion-runs">
              取込履歴を見る
            </Link>
          </div>
        </section>
      )}

      {(result.length > 0 || uploadFailures.length > 0) && (
        <section className="result-panel" aria-live="polite">
          <div className="result-head">
            <span className={`status-badge status-${resultAttentionCount === 0 ? "ok" : "temporarily_unavailable"}`}>
              {resultAttentionCount === 0 ? "取込受付" : "一部要確認"}
            </span>
            <span className="correlation-id">{resultAttemptCount} 件</span>
          </div>
          <FieldGrid
            rows={[
              ["ソース名", resultSourceName],
              ["種別", sourceKindLabel(resultSourceType)],
              ["取込件数", `${resultAttemptCount} 件`],
              ["受付/成功", `${resultAcceptedCount} 件`],
              ["要確認", `${resultAttentionCount} 件`],
            ]}
          />
          {result.length > 0 && (
            <DataTable
              columns={["入力", "状態", "チャンク", "実行 ID"]}
              rows={result.map((item) => [
                <Link key={item.document_id} href={`/documents/${item.document_id}`}>
                  {item.filename || item.document_id}
                </Link>,
                uploadResultStatusLabel(item.status),
                String(item.chunk_count),
                item.ingestion_run_id,
              ])}
              empty="取込結果はまだありません。"
            />
          )}
          {uploadFailures.length > 0 && (
            <p className="source-config-note" role="alert">
              要確認: {uploadFailures.slice(0, 3).join(" / ")}
              {uploadFailures.length > 3 ? ` ほか${uploadFailures.length - 3}件` : ""}
            </p>
          )}
          <div className="screen-actions">
            {resultAcceptedCount > 0 && (
              <Link className="button-link" href="/">
                質問するで根拠を確認
              </Link>
            )}
            <Link className="button-link secondary" href="/ingestion-runs">
              取込履歴を見る
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

const DOCUMENT_LIST_PAGE_SIZE = 12;
type DocumentListFilter = "all" | "needs_review" | "approved" | "obsolete" | "local";
const DOCUMENT_LIST_FILTERS: Array<{ value: DocumentListFilter; label: string }> = [
  { value: "all", label: "すべて" },
  ...(APPROVAL_WORKFLOW_ENABLED ? [{ value: "needs_review" as const, label: "レビュー待ち" }] : []),
  { value: "approved", label: "正式根拠" },
  { value: "obsolete", label: "旧版" },
  { value: "local", label: "直近アップロード" },
];

type DocumentListRow = {
  document_id: string;
  collection_id: string;
  source_id: string;
  source_name?: string;
  source_type?: string;
  document_kind: string | null;
  approval_status: string;
  effective_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  superseded_by: string | null;
  equipment: string | null;
  safety_category: string | null;
  source: "server" | "local";
  filename?: string;
  chunk_count?: number;
  ingested_at?: string;
};

function documentKindLabel(kind: string | null | undefined, fallback?: string): string {
  if (!kind) return fallback ? sourceKindLabel(fallback) : "種別未設定";
  return DOCUMENT_KIND_LABEL[kind] ?? kind;
}

function documentTitle(row: DocumentListRow): string {
  return row.filename || row.document_id;
}

function documentApprovalView(status: string): { label: string; cls: string; description: string } {
  if (status === "approved") {
    return {
      cls: "approval-approved",
      description: "回答の正式な根拠として利用できます。",
      label: "正式根拠",
    };
  }
  if (status === "obsolete") {
    return {
      cls: "approval-obsolete",
      description: "高リスク回答の正式根拠には使われません。",
      label: "旧版",
    };
  }
  if (status === "draft") {
    return {
      cls: "approval-draft",
      description: APPROVAL_WORKFLOW_ENABLED
        ? "参考のみ。正式根拠化にはレビューが必要です。"
        : "参考のみ。新規取り込みは利用可能として扱います。",
      label: "ドラフト",
    };
  }
  if (status === "pending_review") {
    return {
      cls: "approval-pending_review",
      description: APPROVAL_WORKFLOW_ENABLED
        ? "承認すると正式な根拠になります。"
        : "既存の承認待ちデータです。再同期すると利用可能になります。",
      label: APPROVAL_WORKFLOW_ENABLED ? "レビュー待ち" : "再同期推奨",
    };
  }
  return {
    cls: "approval-draft",
    description: "状態を確認してください。",
    label: status || "状態不明",
  };
}

function documentNeedsReview(row: DocumentListRow): boolean {
  return row.approval_status === "pending_review" || row.approval_status === "draft";
}

function documentMatchesFilter(row: DocumentListRow, filter: DocumentListFilter): boolean {
  switch (filter) {
    case "needs_review":
      return documentNeedsReview(row);
    case "approved":
      return row.approval_status === "approved";
    case "obsolete":
      return row.approval_status === "obsolete";
    case "local":
      return row.source === "local";
    default:
      return true;
  }
}

function documentSearchText(row: DocumentListRow): string {
  const approval = documentApprovalView(row.approval_status);
  return [
    row.document_id,
    row.filename,
    row.collection_id,
    row.source_id,
    row.source_name,
    row.source_type,
    documentKindLabel(row.document_kind, row.source_type || row.source_id),
    approval.label,
    approval.description,
    row.equipment,
    row.safety_category,
  ]
    .join(" ")
    .toLowerCase();
}

function documentFreshness(row: DocumentListRow): string {
  if (row.effective_date) return `発効 ${row.effective_date}`;
  if (row.approved_at) return `承認 ${new Date(row.approved_at).toLocaleDateString("ja-JP")}`;
  if (row.ingested_at) return `取込 ${new Date(row.ingested_at).toLocaleString("ja-JP")}`;
  return "発効日未設定";
}

function localUploadRows(uploaded: IngestedDoc[], serverDocs: ManufacturingDocumentSummary[]): DocumentListRow[] {
  const serverIds = new Set(serverDocs.map((doc) => doc.document_id));
  return uploaded
    .filter((doc) => !serverIds.has(doc.document_id))
    .map((doc) => ({
      approved_at: null,
      approved_by: null,
      approval_status: doc.approval_status,
      chunk_count: doc.chunk_count,
      collection_id: doc.collection_id,
      document_id: doc.document_id,
      document_kind: null,
      effective_date: doc.effective_date,
      equipment: null,
      filename: doc.filename,
      ingested_at: doc.ingested_at,
      safety_category: null,
      source: "local" as const,
      source_id: doc.source_id,
      source_name: doc.source_name,
      source_type: doc.source_type,
      superseded_by: null,
    }));
}

function documentSourceDisplay(row: DocumentListRow): string {
  const typeLabel = sourceKindLabel(row.source_type || row.source_id);
  return row.source_name ? `${row.source_name}（${typeLabel}）` : typeLabel;
}

function DocumentListBody() {
  const [uploaded, setUploaded] = useState<IngestedDoc[]>([]);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<DocumentListFilter>("all");
  const [page, setPage] = useState(1);
  const [docs, reloadDocs] = useLoad(
    async () => manufacturingDocuments(await getSessionToken(), DEMO_COLLECTION),
    [],
  );

  useEffect(() => {
    setUploaded(loadIngestedDocs());
  }, []);

  const emptyDocumentMessage = "ドキュメントはまだありません。「外部接続を追加」から取り込めます。";
  const serverDocs = docs.state === "ready" ? docs.data : [];
  const rows: DocumentListRow[] =
    docs.state === "ready"
      ? [
          ...serverDocs.map((doc) => ({ ...doc, source: "server" as const })),
          ...localUploadRows(uploaded, serverDocs),
        ]
      : [];
  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (!documentMatchesFilter(row, filter)) return false;
      if (!needle) return true;
      return documentSearchText(row).includes(needle);
    });
  }, [filter, query, rows]);
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / DOCUMENT_LIST_PAGE_SIZE));
  const pageRows = filteredRows.slice((page - 1) * DOCUMENT_LIST_PAGE_SIZE, page * DOCUMENT_LIST_PAGE_SIZE);
  const reviewCount = rows.filter(documentNeedsReview).length;
  const approvedCount = rows.filter((row) => row.approval_status === "approved").length;
  const obsoleteCount = rows.filter((row) => row.approval_status === "obsolete").length;

  useEffect(() => {
    setPage(1);
  }, [filter, query]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  return (
    <>
      <Section
        title="ドキュメント"
        note={
          APPROVAL_WORKFLOW_ENABLED
            ? "正式根拠、レビュー待ち、旧版を分けて確認できます。直近アップロードは一覧反映までこの画面に残ります。"
            : "質問に使えるドキュメントと旧版を確認できます。直近アップロードは一覧反映までこの画面に残ります。"
        }
      >
        {docs.state === "loading" && <p className="ops-empty" role="status" aria-live="polite">ドキュメントを読み込み中…</p>}
        {docs.state === "error" && <ScreenLoadError error={docs.error} onRetry={reloadDocs} />}
        {docs.state === "ready" &&
          (rows.length === 0 ? (
            <div className="standalone-empty-state">
              <h4>ドキュメントはまだありません</h4>
              <p>{emptyDocumentMessage}</p>
              <AddSourceCta className="standalone-empty-cta" />
            </div>
          ) : (
            <div className="document-library-shell">
              <section className="source-list-controls document-list-controls" aria-label="ドキュメントの検索と絞り込み">
                <label className="standalone-search source-list-search">
                  <span aria-hidden="true">⌕</span>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="文書名・ソース・状態で検索"
                    aria-label="文書名・ソース・状態で検索"
                  />
                </label>
                <div className="source-list-filter" role="group" aria-label="ドキュメント状態で絞り込み">
                  {DOCUMENT_LIST_FILTERS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={filter === option.value ? "source-filter-button active" : "source-filter-button"}
                      aria-pressed={filter === option.value}
                      onClick={() => setFilter(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div className="source-list-summary" aria-live="polite">
                  <span>{filteredRows.length} 件表示</span>
                  {APPROVAL_WORKFLOW_ENABLED && <span>レビュー待ち {reviewCount} 件</span>}
                  <span>正式根拠 {approvedCount} 件</span>
                  <span>旧版 {obsoleteCount} 件</span>
                  {uploaded.length > 0 && <span>直近アップロード {uploaded.length} 件</span>}
                </div>
                {uploaded.length > 0 && (
                  <button
                    type="button"
                    className="source-filter-button"
                    onClick={() => {
                      clearIngestedDocs();
                      setUploaded([]);
                    }}
                  >
                    この端末の履歴だけ消去
                  </button>
                )}
              </section>
              {filteredRows.length === 0 ? (
                <div className="standalone-empty-state">
                  <h4>条件に合うドキュメントはありません</h4>
                  <p>検索語や絞り込みを変えると、別の文書を確認できます。</p>
                  <button
                    type="button"
                    className="standalone-empty-cta"
                    onClick={() => {
                      setQuery("");
                      setFilter("all");
                    }}
                  >
                    条件をクリア
                  </button>
                </div>
              ) : (
                <>
                  <div className="document-list-items" role="list">
                    {pageRows.map((doc) => {
                      const approval = documentApprovalView(doc.approval_status);
                      const needsReview = documentNeedsReview(doc);
                      return (
                        <article className="document-list-row" key={`${doc.source}-${doc.document_id}`} role="listitem">
                          <div className="document-list-main">
                            <div className="standalone-source-mark" aria-hidden="true">
                              {documentKindLabel(doc.document_kind, doc.source_type || doc.source_id).slice(0, 2)}
                            </div>
                            <div className="source-list-title-block">
                              <h4>
                                <Link href={`/documents/${doc.document_id}`} className="source-title-link" aria-label={`${documentTitle(doc)} の詳細を見る`}>
                                  {documentTitle(doc)}
                                </Link>
                              </h4>
                              <p>
                                {documentKindLabel(doc.document_kind, doc.source_type || doc.source_id)}
                                {doc.source === "local" ? " · 直近アップロード（一覧反映待ち）" : ""}
                              </p>
                            </div>
                          </div>
                          <div className="document-list-status-cell">
                            <span className={`review-queue-status ${approval.cls}`}>{approval.label}</span>
                            <span>{approval.description}</span>
                          </div>
                          <div className="document-list-metrics">
                            <span>{documentFreshness(doc)}</span>
                            <span>ソース: {documentSourceDisplay(doc)}</span>
                            <span>設備/分類: {doc.equipment || doc.safety_category || "—"}</span>
                          </div>
                          <div className="document-list-actions">
                            {APPROVAL_WORKFLOW_ENABLED && needsReview && (
                              <Link href="/reviews/documents" className="button-link">
                                レビューへ
                              </Link>
                            )}
                            {doc.approval_status === "approved" && (
                              <Link href="/" className="button-link secondary">
                                質問で確認
                              </Link>
                            )}
                            <Link href={`/documents/${doc.document_id}`} className="button-link secondary">
                              詳細
                            </Link>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                  {totalPages > 1 && (
                    <nav className="source-list-pagination" aria-label="ドキュメント一覧のページ">
                      <button
                        type="button"
                        onClick={() => setPage((current) => Math.max(1, current - 1))}
                        disabled={page <= 1}
                      >
                        前へ
                      </button>
                      <span>
                        {page} / {totalPages}
                      </span>
                      <button
                        type="button"
                        onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                        disabled={page >= totalPages}
                      >
                        次へ
                      </button>
                    </nav>
                  )}
                </>
              )}
            </div>
          ))}
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
            ["利用状態", APPROVAL_WORKFLOW_ENABLED ? "pending_review" : "利用可"],
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


type KnowledgePreparationData = {
  governance: GovernanceStatus;
  sources: SourceListRow[];
  documents: ManufacturingDocumentSummary[];
  drafts: DraftArtifact[];
};

async function loadKnowledgePreparationData(): Promise<KnowledgePreparationData> {
  const token = await getSessionToken();
  const [governance, sources, documents, drafts] = await Promise.all([
    manufacturingGovernanceStatus(token),
    loadSourceListRows(),
    manufacturingDocuments(token).catch(() => [] as ManufacturingDocumentSummary[]),
    manufacturingListDrafts(token).catch(() => [] as DraftArtifact[]),
  ]);
  return { documents, drafts, governance, sources };
}

function draftNeedsHumanReview(draft: DraftArtifact): boolean {
  return draft.status === "draft" || draft.status === "in_review";
}

function KnowledgePrepStep({
  action,
  description,
  href,
  index,
  label,
  metric,
  tone,
}: {
  action: string;
  description: string;
  href: string;
  index: string;
  label: string;
  metric: string;
  tone: "ok" | "wait" | "bad";
}) {
  return (
    <Link href={href} className="knowledge-step-card" role="listitem">
      <span className="knowledge-step-index" aria-hidden="true">{index}</span>
      <span className="knowledge-step-label">{label}</span>
      <strong>{metric}</strong>
      <span className={`knowledge-step-state ${tone}`}>{description}</span>
      <span className="knowledge-step-action">{action}</span>
    </Link>
  );
}

function ApprovalWorkflowBody() {
  if (!APPROVAL_WORKFLOW_ENABLED) return <ApprovalWorkflowPausedBody />;
  return <ApprovalWorkflowEnabledBody />;
}

function ApprovalWorkflowEnabledBody() {
  const [state, reload] = useLoad(loadKnowledgePreparationData, []);
  if (state.state === "loading") return <p className="ops-empty" role="status" aria-live="polite">ガバナンス状態を読み込み中…</p>;
  if (state.state === "error") return <ScreenLoadError error={state.error} onRetry={reload} />;

  const { documents, drafts, governance, sources } = state.data;
  const sourceActionCount = sources.filter(sourceNeedsAction).length;
  const activeSyncCount = sources.filter((row) => isSyncActive(row.sync?.status)).length;
  const pendingDocumentCount = documents.filter((doc) => doc.approval_status === "pending_review" || doc.approval_status === "draft").length;
  const approvedDocumentCount = documents.filter((doc) => doc.approval_status === "approved").length;
  const openDraftCount = drafts.filter(draftNeedsHumanReview).length;

  return (
    <>
      <Section title="ナレッジ準備" note="外部接続から正式根拠化、AI生成物レビューまでの作業順です。件数が残っている段階から処理してください。">
        <div className="knowledge-flow-grid" role="list" aria-label="ナレッジ準備の作業順">
          <KnowledgePrepStep
            index="1"
            label="外部接続"
            metric={`${sources.length} 件`}
            description={sourceActionCount > 0 ? `${sourceActionCount} 件に対応が必要` : "利用状態を確認済み"}
            tone={sourceActionCount > 0 ? "wait" : "ok"}
            href="/sources/list"
            action="外部接続を確認"
          />
          <KnowledgePrepStep
            index="2"
            label="同期・取り込み"
            metric={activeSyncCount > 0 ? `${activeSyncCount} 件実行中` : "取込履歴"}
            description={activeSyncCount > 0 ? "完了まで自動更新を確認" : "失敗や部分成功を確認"}
            tone={activeSyncCount > 0 ? "wait" : "ok"}
            href="/ingestion-runs"
            action="取込履歴を見る"
          />
          <KnowledgePrepStep
            index="3"
            label="根拠文書レビュー"
            metric={`${pendingDocumentCount} 件`}
            description={pendingDocumentCount > 0 ? "正式根拠化が必要" : `${approvedDocumentCount} 件が正式根拠`}
            tone={pendingDocumentCount > 0 ? "wait" : "ok"}
            href="/reviews/documents"
            action="文書をレビュー"
          />
          <KnowledgePrepStep
            index="4"
            label="AIドラフトレビュー"
            metric={`${openDraftCount} 件`}
            description={openDraftCount > 0 ? "人手レビュー待ち" : "未処理のドラフトなし"}
            tone={openDraftCount > 0 ? "wait" : "ok"}
            href="/reviews"
            action="ドラフトを確認"
          />
        </div>
      </Section>

      <Section title="ガバナンスベースのポリシー">
        <FieldGrid
          rows={[
            ["AI生成物はドラフト固定", governance.draft_review.ai_output_always_draft ? "はい" : "いいえ"],
            ["AIドラフト承認に担当者必須", governance.draft_review.reviewer_required_for_approval ? "はい" : "いいえ"],
            ["高リスク回答は承認済み根拠が必須", governance.safety_gate.high_risk_requires_approved_citation ? "はい" : "いいえ"],
          ]}
        />
      </Section>

      <Section title="同期・承認ポリシー概要" note="同期元を信頼するか、根拠文書レビューに回すかはソース追加時に選択します。">
        <div className="policy-summary-grid">
          <article className="policy-summary-card">
            <span className="policy-summary-label">レビューが必要</span>
            <strong>pending_review で取り込み</strong>
            <p>同期した文書は根拠文書レビューに入り、承認されるまで高リスク回答の正式根拠にはなりません。</p>
            <Link href="/reviews/documents">根拠文書レビューへ</Link>
          </article>
          <article className="policy-summary-card">
            <span className="policy-summary-label">信頼するソース</span>
            <strong>承認済みとして取り込み</strong>
            <p>source-of-truth として扱う同期元です。個別レビューを省略する代わりに、接続設定時の判断が監査上重要になります。</p>
            <AddSourceCta />
          </article>
        </div>
        <p className="ops-note">この画面では現在のポリシーと作業導線を表示します。承認ルール編集 API は未接続です。</p>
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
  const toast = useToast();

  async function run(asUser: string) {
    if (loading) return;
    setUserId(asUser);
    setLoading(true);
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
      toast(err instanceof Error ? err.message : "実行に失敗しました", "error");
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
  const [result, setResult] = useState<RetrievalDebugResult | null>(null);
  const toast = useToast();

  async function run(event: FormEvent) {
    event.preventDefault();
    if (loading || !query.trim()) return;
    setLoading(true);
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
      toast(err instanceof Error ? err.message : "実行に失敗しました", "error");
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

/** U6: honest-mock banner — marks screens whose rows are sample data, without alarming styling. */
function SampleDataNotice({ note }: { note: string }) {
  return (
    <p className="sample-data-notice" role="note">
      <span className="sample-data-badge">サンプルデータ</span>
      {note}
    </p>
  );
}

function BillingBody() {
  return (
    <>
      <SampleDataNotice note="表示中のプラン・請求書はサンプルです。課金連携（実際の利用量・請求データの取得）は準備中です。" />
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

function MockAdminScreen({ title, rows, sampleNote }: { title: string; rows: AdminListRow[]; sampleNote: string }) {
  return (
    <>
      <SampleDataNotice note={sampleNote} />
      <Section title={title}>
        <DataTable
          columns={[title, "メタデータ", "状態"]}
          rows={rows.map((row) => [row.label, row.meta ?? "—", row.status ?? "—"])}
          empty={`${title} の設定はまだありません。`}
        />
      </Section>
    </>
  );
}
