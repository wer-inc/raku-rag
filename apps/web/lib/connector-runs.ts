// Client-side record of connector sync runs started from Add Source.
// Complements upload-only rows in uploads.ts until a tenant-wide ingestion-run list API exists.

export interface ConnectorRunRecord {
  ingestion_run_id: string;
  source_id: string;
  collection_id: string;
  status: string;
  observed_count: number;
  changed_count: number;
  failed_count: number;
  synced_at: string; // ISO
}

const KEY = "raku.connectorRuns";
const LIMIT = 100;

export function loadConnectorRuns(): ConnectorRunRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ConnectorRunRecord[]) : [];
  } catch {
    return [];
  }
}

export function recordConnectorRun(run: ConnectorRunRecord): void {
  if (typeof window === "undefined") return;
  const next = [
    run,
    ...loadConnectorRuns().filter((r) => r.ingestion_run_id !== run.ingestion_run_id),
  ].slice(0, LIMIT);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* best-effort */
  }
}

export function clearConnectorRuns(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
