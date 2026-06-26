import type {
  AdminDataSource,
  AdminDocumentDetail,
  AnswerRequest,
  AnswerResponse,
  AssignReviewerRequest,
  AuditEventListResponse,
  CitationSourceView,
  CreateDraftRequest,
  DocumentFileResponse,
  ImprovementQueueResponse,
  DocumentApprovalRequest,
  DocumentApprovalResult,
  DraftArtifact,
  FeedbackRequest,
  FeedbackResponse,
  GovernanceStatus,
  IngestRequest,
  IngestResponse,
  KnowledgeOpsDashboard,
  ManufacturingDocumentSummary,
  ManufacturingAnswerRequest,
  ManufacturingAnswerResponse,
  ManufacturingIngestionRun,
  ManufacturingKpi,
  ManufacturingSourceSyncStatus,
  ReviewDraftRequest,
  SafetyTelemetryView,
  SearchRequest,
  SearchResponse,
  TroubleCaseSearchRequest,
  TroubleCaseSearchResponse,
} from "@raku-rag/shared";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:3000/v1";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = typeof body?.message === "string" ? body.message : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

function authHeaders(userToken: string): Record<string, string> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    authorization: `Bearer ${userToken.split(".").length === 3 ? userToken : "local-dev-key"}`,
  };
  if (userToken.split(".").length !== 3) {
    headers["x-user-token"] = userToken;
  }
  return headers;
}

function authedRequestInit(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  userToken: string,
  body?: unknown,
): RequestInit {
  return {
    method,
    headers: authHeaders(userToken),
    cache: method === "GET" ? "no-store" : undefined,
    body: body === undefined ? undefined : JSON.stringify(body ?? {}),
  };
}

export async function apiGetJson<T>(path: string, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, authedRequestInit("GET", userToken));
  return jsonOrThrow<T>(res);
}

export async function apiPostJson<T>(path: string, body: unknown, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, authedRequestInit("POST", userToken, body));
  return jsonOrThrow<T>(res);
}

export async function apiPutJson<T>(path: string, body: unknown, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, authedRequestInit("PUT", userToken, body));
  return jsonOrThrow<T>(res);
}

export async function apiPatchJson<T>(path: string, body: unknown, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, authedRequestInit("PATCH", userToken, body));
  return jsonOrThrow<T>(res);
}

export async function apiDeleteJson<T>(path: string, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, authedRequestInit("DELETE", userToken));
  return jsonOrThrow<T>(res);
}

/** Authenticated GET against a `/v1/manufacturing/*` read view. */
async function mfgGet<T>(path: string, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}/manufacturing/${path}`, {
    method: "GET",
    headers: authHeaders(userToken),
    cache: "no-store",
  });
  return jsonOrThrow<T>(res);
}

/** Authenticated POST against a `/v1/manufacturing/*` endpoint. */
async function mfgPost<T>(path: string, body: unknown, userToken: string): Promise<T> {
  const res = await fetch(`${API_BASE}/manufacturing/${path}`, {
    method: "POST",
    headers: authHeaders(userToken),
    body: JSON.stringify(body ?? {}),
  });
  return jsonOrThrow<T>(res);
}

export async function apiHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
  return jsonOrThrow<{ status: string }>(res);
}

export async function answer(req: AnswerRequest, userToken: string): Promise<AnswerResponse> {
  const res = await fetch(`${API_BASE}/answer`, {
    method: "POST",
    headers: authHeaders(userToken),
    body: JSON.stringify(req),
  });
  return jsonOrThrow<AnswerResponse>(res);
}

export async function manufacturingAnswer(
  req: ManufacturingAnswerRequest,
  userToken: string,
): Promise<ManufacturingAnswerResponse> {
  const res = await fetch(`${API_BASE}/manufacturing/answer`, {
    method: "POST",
    headers: authHeaders(userToken),
    body: JSON.stringify(req),
  });
  return jsonOrThrow<ManufacturingAnswerResponse>(res);
}

/** Ingest a document (POST /v1/ingest). The `ref` is a connector ref (file:// for local uploads). */
export async function ingestDocument(req: IngestRequest, userToken: string): Promise<IngestResponse> {
  return apiPostJson<IngestResponse>("/ingest", req, userToken);
}

/** Retrieve ranked candidate chunks (POST /v1/search) — already ACL deny-by-default filtered. */
export async function searchChunks(req: SearchRequest, userToken: string): Promise<SearchResponse> {
  const res = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: authHeaders(userToken),
    body: JSON.stringify(req),
  });
  return jsonOrThrow<SearchResponse>(res);
}

/** Record answer/citation feedback (👍/👎, "この引用は正しい/間違い"). */
export async function submitFeedback(
  req: FeedbackRequest,
  userToken: string,
): Promise<FeedbackResponse> {
  return apiPostJson<FeedbackResponse>("/feedback", req, userToken);
}

// --- Operations read views (specs/014; all GET, audit-derived, read-only) ----------------------

export async function manufacturingImprovements(
  userToken: string,
  limit = 100,
): Promise<ImprovementQueueResponse> {
  return mfgGet<ImprovementQueueResponse>(
    `improvements?limit=${encodeURIComponent(String(limit))}`,
    userToken,
  );
}

export async function adminDocumentFile(
  documentId: string,
  userToken: string,
): Promise<DocumentFileResponse> {
  return apiGetJson<DocumentFileResponse>(
    `/admin/documents/${encodeURIComponent(documentId)}/file`,
    userToken,
  );
}

export async function manufacturingDocuments(
  userToken: string,
  collectionId?: string,
  approvalStatus?: string,
): Promise<ManufacturingDocumentSummary[]> {
  const params = new URLSearchParams();
  if (collectionId) params.set("collection_id", collectionId);
  if (approvalStatus) params.set("approval_status", approvalStatus);
  const qs = params.toString();
  const path = qs ? `documents?${qs}` : "documents";
  const res = await mfgGet<{ documents: ManufacturingDocumentSummary[] }>(path, userToken);
  return res.documents ?? [];
}

export async function adminDocumentDetail(
  documentId: string,
  userToken: string,
): Promise<AdminDocumentDetail> {
  return apiGetJson<AdminDocumentDetail>(
    `/admin/documents/${encodeURIComponent(documentId)}`,
    userToken,
  );
}

export async function adminCitationView(
  documentId: string,
  userToken: string,
  chunkId?: string,
): Promise<CitationSourceView> {
  const qs = chunkId ? `?chunk_id=${encodeURIComponent(chunkId)}` : "";
  return apiGetJson<CitationSourceView>(
    `/admin/documents/${encodeURIComponent(documentId)}/citation-view${qs}`,
    userToken,
  );
}

export async function manufacturingListDrafts(
  userToken: string,
  opts?: { status?: string; reviewerId?: string },
): Promise<DraftArtifact[]> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.reviewerId) params.set("reviewer_id", opts.reviewerId);
  const qs = params.toString();
  const res = await mfgGet<{ drafts: DraftArtifact[] }>(
    qs ? `drafts?${qs}` : "drafts",
    userToken,
  );
  return res.drafts ?? [];
}

export async function manufacturingAuditEvents(
  userToken: string,
  opts?: { action?: string; limit?: number; offset?: number },
): Promise<AuditEventListResponse> {
  const params = new URLSearchParams();
  if (opts?.action) params.set("action", opts.action);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return apiGetJson<AuditEventListResponse>(
    `/manufacturing/audit/events${qs ? `?${qs}` : ""}`,
    userToken,
  );
}

export async function manufacturingDashboard(userToken: string): Promise<KnowledgeOpsDashboard> {
  return mfgGet<KnowledgeOpsDashboard>("dashboard", userToken);
}

export async function manufacturingSafetyTelemetry(
  userToken: string,
): Promise<SafetyTelemetryView> {
  return mfgGet<SafetyTelemetryView>("safety-telemetry", userToken);
}

export async function manufacturingKpi(userToken: string): Promise<ManufacturingKpi> {
  return mfgGet<ManufacturingKpi>("kpi", userToken);
}

export interface QualityEvalItem {
  question: string;
  expected_evidence: Array<{ document_id: string }>;
}

export interface QualityEvalResult {
  run_id: string;
  gate_result: string;
  status: string;
  metrics: { recall_at_k?: number; groundedness?: number; high_risk_recall?: number };
  security_checks: Record<string, { passed?: boolean } | boolean>;
}

/** Register a quality eval set and run it against the live answer path, returning the scorecard
 *  (recall@k / groundedness / high-risk recall / security checks). Mirrors scripts/demo/quality_scorecard.sh. */
export async function runManufacturingQualityEval(
  items: QualityEvalItem[],
  userToken: string,
): Promise<QualityEvalResult> {
  const set = await apiPostJson<{ eval_set_id: string }>("/evaluations/sets", { items }, userToken);
  const run = await apiPostJson<{ run_id: string }>(
    "/evaluations/runs",
    { eval_set_id: set.eval_set_id, collection_id: "manuals" },
    userToken,
  );
  return apiGetJson<QualityEvalResult>(
    `/evaluations/runs/${encodeURIComponent(run.run_id)}`,
    userToken,
  );
}

export async function manufacturingGovernanceStatus(
  userToken: string,
): Promise<GovernanceStatus> {
  return mfgGet<GovernanceStatus>("governance/status", userToken);
}

// --- Sources view (specs/014 slice 2) ----------------------------------------------------------

export async function manufacturingTroubleCaseSearch(
  req: TroubleCaseSearchRequest,
  userToken: string,
): Promise<TroubleCaseSearchResponse> {
  return mfgPost<TroubleCaseSearchResponse>("trouble-cases/search", req, userToken);
}

export async function manufacturingSourceSyncStatus(
  sourceId: string,
  userToken: string,
): Promise<ManufacturingSourceSyncStatus> {
  return mfgGet<ManufacturingSourceSyncStatus>(
    `sources/${encodeURIComponent(sourceId)}/sync-status`,
    userToken,
  );
}

export interface AdminSourceSyncResponse {
  source_id: string;
  collection_id: string;
  status: string;
  ingestion_run_id: string;
  sync_run_id?: string;
  queued?: boolean;
  sqs_message_id?: string;
  status_url: string;
  observed_count: number;
  changed_count: number;
  failed_count: number;
  runs: IngestResponse[];
}

/** List the tenant's configured datasources (GET /admin/datasources). */
export async function adminDataSources(
  userToken: string,
  collectionId?: string,
): Promise<AdminDataSource[]> {
  const path = collectionId
    ? `/admin/datasources?collection_id=${encodeURIComponent(collectionId)}`
    : "/admin/datasources";
  return apiGetJson<AdminDataSource[]>(path, userToken);
}

export async function adminSourceTestConnection(
  sourceId: string,
  body: Record<string, unknown>,
  userToken: string,
): Promise<Record<string, unknown>> {
  return apiPostJson<Record<string, unknown>>(
    "/admin/sources/" + encodeURIComponent(sourceId) + "/test-connection",
    body,
    userToken,
  );
}


export async function adminSourceSync(
  sourceId: string,
  body: Record<string, unknown>,
  userToken: string,
): Promise<AdminSourceSyncResponse> {
  return apiPostJson<AdminSourceSyncResponse>(
    `/admin/sources/${encodeURIComponent(sourceId)}/sync`,
    body,
    userToken,
  );
}

export async function manufacturingIngestionRun(
  runId: string,
  userToken: string,
): Promise<ManufacturingIngestionRun> {
  return mfgGet<ManufacturingIngestionRun>(
    `ingestion-runs/${encodeURIComponent(runId)}`,
    userToken,
  );
}

export async function manufacturingRequestSourceSync(
  sourceId: string,
  body: Record<string, unknown>,
  userToken: string,
): Promise<Record<string, unknown>> {
  return mfgPost<Record<string, unknown>>(`sources/${encodeURIComponent(sourceId)}/sync`, body, userToken);
}

export async function manufacturingUpdateDocumentMetadata(
  documentId: string,
  body: Record<string, unknown>,
  userToken: string,
): Promise<Record<string, unknown>> {
  return apiPutJson<Record<string, unknown>>(
    `/manufacturing/documents/${encodeURIComponent(documentId)}/metadata`,
    body,
    userToken,
  );
}

export async function manufacturingDeleteDocument(
  documentId: string,
  userToken: string,
): Promise<Record<string, unknown>> {
  return apiDeleteJson<Record<string, unknown>>(
    `/admin/documents/${encodeURIComponent(documentId)}`,
    userToken,
  );
}

export async function manufacturingAuditExport(
  userToken: string,
  fmt?: string,
): Promise<Record<string, unknown>> {
  const suffix = fmt ? `?fmt=${encodeURIComponent(fmt)}` : "";
  return apiGetJson<Record<string, unknown>>(`/manufacturing/audit/export${suffix}`, userToken);
}

export async function manufacturingDataUsePolicy(
  userToken: string,
): Promise<Record<string, unknown>> {
  return apiGetJson<Record<string, unknown>>("/manufacturing/policy/data-use", userToken);
}

// --- Reviews view (specs/014 slice 3) — human review loop; mutations are explicit human actions --

export async function manufacturingGetDraft(
  artifactId: string,
  userToken: string,
): Promise<DraftArtifact> {
  return mfgGet<DraftArtifact>(`drafts/${encodeURIComponent(artifactId)}`, userToken);
}

export async function manufacturingCreateDraft(
  req: CreateDraftRequest,
  userToken: string,
): Promise<DraftArtifact> {
  return mfgPost<DraftArtifact>("drafts", req, userToken);
}

export async function manufacturingAssignReviewer(
  artifactId: string,
  req: AssignReviewerRequest,
  userToken: string,
): Promise<DraftArtifact> {
  return mfgPost<DraftArtifact>(
    `drafts/${encodeURIComponent(artifactId)}/assign`,
    req,
    userToken,
  );
}

export async function manufacturingReviewDraft(
  artifactId: string,
  req: ReviewDraftRequest,
  userToken: string,
): Promise<DraftArtifact> {
  return mfgPost<DraftArtifact>(
    `drafts/${encodeURIComponent(artifactId)}/review`,
    req,
    userToken,
  );
}

export async function manufacturingDocumentApproval(
  documentId: string,
  req: DocumentApprovalRequest,
  userToken: string,
): Promise<DocumentApprovalResult> {
  return mfgPost<DocumentApprovalResult>(
    `documents/${encodeURIComponent(documentId)}/approval`,
    req,
    userToken,
  );
}
