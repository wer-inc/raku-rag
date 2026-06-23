// Client-side record of AI drafts created via the Review screen. There is no
// `GET /v1/manufacturing/drafts` list endpoint yet (see specs/full-saas/gaps.md),
// so created drafts are tracked locally to populate the review queue. Each draft's
// authoritative state still comes from `GET /v1/manufacturing/drafts/:id`; this record
// just keeps the queue list + last-known status.

export interface DraftRecord {
  artifact_id: string;
  kind: string;
  status: string;
  source_document_ids: string[];
  reviewer_id: string | null;
  created_at: string;
}

const KEY = "raku.drafts";
const LIMIT = 100;

export function loadDrafts(): DraftRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DraftRecord[]) : [];
  } catch {
    return [];
  }
}

function save(rows: DraftRecord[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rows.slice(0, LIMIT)));
  } catch {
    /* best-effort */
  }
}

export function recordDraft(draft: DraftRecord): void {
  const next = [draft, ...loadDrafts().filter((d) => d.artifact_id !== draft.artifact_id)];
  save(next);
}

export function updateDraftRecord(artifactId: string, patch: Partial<DraftRecord>): void {
  const next = loadDrafts().map((d) => (d.artifact_id === artifactId ? { ...d, ...patch } : d));
  save(next);
}

export function clearDrafts(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
