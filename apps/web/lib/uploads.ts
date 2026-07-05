// Client-side record of documents ingested via the Add Source upload flow.
// There is no tenant-scoped `GET /v1/admin/documents` yet (see specs/full-saas/gaps.md),
// so recently ingested docs are kept locally to make "取込ラン" / "ドキュメント一覧に出る"
// visible end-to-end. Swap for the real document list once the API exists.

export interface IngestedDoc {
  document_id: string;
  collection_id: string;
  source_id: string;
  source_name?: string;
  source_type?: string;
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

// A local record is an optimistic bridge until the server document list reflects an upload. Keep a
// just-uploaded doc visible for this long even if the server list hasn't surfaced it yet (an async
// PDF/image ingest still landing); after that, absent-from-server means it was deleted/purged.
const RECONCILE_GRACE_MS = 10 * 60 * 1000;

/**
 * Prune stale local upload records against an authoritative server document list.
 *
 * Call ONLY with a real, successful server response — never on a fetch error, where you cannot tell an
 * empty tenant from an unreachable API. A local record that is (a) absent from `serverDocumentIds` and
 * (b) older than the grace window is stale (typically the document was deleted/purged server-side) and
 * is removed, so it can't linger forever as a phantom row (e.g. a permanent "レビュー待ち"). Returns the
 * retained records; also rewrites localStorage when something was pruned.
 */
export function reconcileIngestedDocs(serverDocumentIds: Iterable<string>): IngestedDoc[] {
  const all = loadIngestedDocs();
  const known = new Set(serverDocumentIds);
  const now = Date.now();
  const kept = all.filter((doc) => {
    if (known.has(doc.document_id)) return true;
    const ingestedAt = Date.parse(doc.ingested_at || "");
    if (Number.isNaN(ingestedAt)) return true; // no usable timestamp -> keep (cannot age it out)
    return now - ingestedAt < RECONCILE_GRACE_MS;
  });
  if (typeof window !== "undefined" && kept.length !== all.length) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(kept));
    } catch {
      /* best-effort */
    }
  }
  return kept;
}
