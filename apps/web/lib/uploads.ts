// Client-side record of documents ingested via the Add Source upload flow.
// There is no tenant-scoped `GET /v1/admin/documents` yet (see specs/full-saas/gaps.md),
// so recently ingested docs are kept locally to make "取込ラン" / "ドキュメント一覧に出る"
// visible end-to-end. Swap for the real document list once the API exists.

export interface IngestedDoc {
  document_id: string;
  collection_id: string;
  source_id: string;
  filename: string;
  content_type: string;
  approval_status: string;
  effective_date: string | null;
  ingestion_run_id: string;
  status: string;
  chunk_count: number;
  ingested_at: string; // ISO
}

const KEY = "raku.ingestedDocs";
const LIMIT = 100;

export function loadIngestedDocs(): IngestedDoc[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as IngestedDoc[]) : [];
  } catch {
    return [];
  }
}

export function recordIngestedDoc(doc: IngestedDoc): void {
  if (typeof window === "undefined") return;
  // Newest first; de-dupe by document_id so re-ingesting updates the row.
  const next = [doc, ...loadIngestedDocs().filter((d) => d.document_id !== doc.document_id)].slice(
    0,
    LIMIT,
  );
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* best-effort */
  }
}

export function updateIngestedDoc(documentId: string, patch: Partial<IngestedDoc>): void {
  if (typeof window === "undefined") return;
  const next = loadIngestedDocs().map((d) =>
    d.document_id === documentId ? { ...d, ...patch } : d,
  );
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* best-effort */
  }
}

export function clearIngestedDocs(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
