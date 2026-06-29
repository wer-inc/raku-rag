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
  answer_excerpt?: string;
  collection_id?: string;
}

const KEY = "raku.answerHistory";
const LIMIT = 100;

export function loadAnswerHistory(): AnswerHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((entry) => normalizeEntry(entry))
      .filter((entry): entry is AnswerHistoryEntry => Boolean(entry));
  } catch {
    return [];
  }
}

export function recordAnswer(
  question: string,
  response: ManufacturingAnswerResponse,
  collectionId?: string,
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
    answer_excerpt: answerExcerpt(response),
    collection_id: collectionId,
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

function normalizeEntry(value: unknown): AnswerHistoryEntry | null {
  if (!value || typeof value !== "object") return null;
  const entry = value as Partial<AnswerHistoryEntry>;
  if (!entry.id || !entry.question || !entry.status || !entry.asked_at) return null;
  return {
    id: String(entry.id),
    question: String(entry.question),
    status: entry.status,
    high_risk: Boolean(entry.high_risk),
    blocked: Boolean(entry.blocked),
    obsolete: Boolean(entry.obsolete),
    citation_count: Number(entry.citation_count ?? 0),
    asked_at: String(entry.asked_at),
    answer_excerpt: entry.answer_excerpt ? String(entry.answer_excerpt) : undefined,
    collection_id: entry.collection_id ? String(entry.collection_id) : undefined,
  };
}

function answerExcerpt(response: ManufacturingAnswerResponse): string {
  const text = response.text?.trim();
  if (text) return truncate(text.replace(/\s+/g, " "), 160);
  if (response.manufacturing?.safety_block_reason) return "安全ルールにより回答を保留しました。";
  if (response.status === "insufficient_evidence") return "承認済み根拠が不足しているため、断定できません。";
  return "回答本文はありません。";
}

function truncate(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit - 1)}…` : value;
}
