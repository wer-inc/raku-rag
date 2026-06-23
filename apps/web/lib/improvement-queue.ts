// Client-side knowledge-improvement queue (goal.md Priority #7). Low answer
// ratings (👎 要改善) are POSTed to /v1/feedback for the backend AND recorded
// here so an admin can triage them (there is no list-feedback endpoint yet —
// see specs/full-saas/gaps.md). Each item carries the reason the user selected.

export const FEEDBACK_REASONS: Array<{ code: string; label: string }> = [
  { code: "wrong_evidence", label: "根拠が違う" },
  { code: "outdated_doc", label: "古い文書を見ている" },
  { code: "vague", label: "回答が曖昧" },
  { code: "missing_doc", label: "必要な文書がない" },
  { code: "acl_hidden", label: "権限で見えない" },
  { code: "not_real", label: "現場の実態と違う" },
];

export function reasonLabel(code: string): string {
  return FEEDBACK_REASONS.find((r) => r.code === code)?.label ?? code;
}

export interface ImprovementItem {
  id: string;
  answer_id: string;
  question: string;
  reason: string; // reason code
  status: "open" | "resolved";
  created_at: string; // ISO
}

const KEY = "raku.improvementQueue";
const LIMIT = 200;

export function loadImprovementItems(): ImprovementItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ImprovementItem[]) : [];
  } catch {
    return [];
  }
}

function save(rows: ImprovementItem[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rows.slice(0, LIMIT)));
  } catch {
    /* best-effort */
  }
}

export function recordImprovementItem(item: Omit<ImprovementItem, "id" | "status" | "created_at">): void {
  const full: ImprovementItem = {
    ...item,
    id: `imp_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`,
    status: "open",
    created_at: new Date().toISOString(),
  };
  save([full, ...loadImprovementItems()]);
}

export function setImprovementStatus(id: string, status: ImprovementItem["status"]): void {
  save(loadImprovementItems().map((i) => (i.id === id ? { ...i, status } : i)));
}

export function clearImprovementItems(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY);
}
