// Client-side answer history (localStorage). There is no tenant-scoped
// `GET /v1/manufacturing/answers/history` endpoint yet (see specs/full-saas/gaps.md),
// so completed Q&As are persisted locally so the 質問→回答→履歴 loop is closed and
// demoable. Swap the loader for the real API once it exists.

import type { ManufacturingAnswerResponse } from "@raku-rag/shared";

export interface AnswerHistoryEntry {
  id: string; // correlation_id (falls back to a synthetic id)
  question: string;
  status: ManufacturingAnswerResponse["status"];
  high_risk: boolean;
  blocked: boolean;
  obsolete: boolean;
  citation_count: number;
  asked_at: string; // ISO timestamp
}

const KEY = "raku.answerHistory";
const LIMIT = 100;

export function loadAnswerHistory(): AnswerHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as AnswerHistoryEntry[]) : [];
  } catch {
    return [];
  }
}

export function recordAnswer(
  question: string,
  response: ManufacturingAnswerResponse,
): AnswerHistoryEntry {
  const safety = response.manufacturing;
  const entry: AnswerHistoryEntry = {
    id: response.correlation_id || `local_${Date.now().toString(36)}`,
    question,
    status: response.status,
    high_risk: Boolean(safety?.high_risk),
    blocked: Boolean(safety?.safety_block_reason),
    obsolete: Boolean(safety?.obsolete_warning),
    citation_count: response.citations?.length ?? 0,
    asked_at: new Date().toISOString(),
  };
  if (typeof window !== "undefined") {
    const next = [entry, ...loadAnswerHistory()].slice(0, LIMIT);
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* storage full / unavailable — history is best-effort */
    }
  }
  return entry;
}

export function clearAnswerHistory(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
