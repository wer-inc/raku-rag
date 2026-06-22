import type {
  AnswerRequest,
  AnswerResponse,
  AssignReviewerRequest,
  CreateDraftRequest,
  DocumentApprovalRequest,
  DocumentApprovalResult,
  DraftArtifact,
  GovernanceStatus,
  IngestionRunStatusResponse,
  KnowledgeOpsDashboard,
  ManufacturingAnswerRequest,
  ManufacturingAnswerResponse,
  ManufacturingKpi,
  ReviewDraftRequest,
  SafetyTelemetryView,
  SourceSyncStatusResponse,
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
  return {
    "content-type": "application/json",
    authorization: "Bearer local-dev-key",
    "x-user-token": userToken,
  };
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

// --- Operations read views (specs/014; all GET, audit-derived, read-only) ----------------------

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
): Promise<SourceSyncStatusResponse> {
  return mfgGet<SourceSyncStatusResponse>(
    `sources/${encodeURIComponent(sourceId)}/sync-status`,
    userToken,
  );
}

export async function manufacturingIngestionRun(
  runId: string,
  userToken: string,
): Promise<IngestionRunStatusResponse> {
  return mfgGet<IngestionRunStatusResponse>(
    `ingestion-runs/${encodeURIComponent(runId)}`,
    userToken,
  );
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
