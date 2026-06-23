"use client";

import { useEffect, useState } from "react";
import type { Citation } from "@raku-rag/shared";
import { submitFeedback } from "../../lib/api-client";
import { getSessionToken } from "../../lib/session";

export interface CitationViewTarget {
  citation: Citation;
  /** correlation_id of the answer this citation supports (feedback answer_id). */
  answerId: string;
  /** The grounded answer statement this citation backs (for context). */
  groundedText: string | null;
  /** 1-based position within the answer's citation list. */
  index: number;
}

const APPROVAL_LABEL: Record<string, { label: string; cls: string }> = {
  approved: { label: "承認済み", cls: "approval-approved" },
  pending_review: { label: "承認待ち", cls: "approval-draft" },
  draft: { label: "ドラフト", cls: "approval-draft" },
  obsolete: { label: "旧版（参考）", cls: "approval-obsolete" },
};

function approval(status?: string | null): { label: string; cls: string } {
  if (status && APPROVAL_LABEL[status]) return APPROVAL_LABEL[status];
  return { label: status ? status : "承認状態 不明", cls: "approval-draft" };
}

function locatorRow(c: Citation): { label: string; value: string } {
  if (c.kind === "visual") {
    return { label: "位置", value: `ビジュアル引用（アセット ${c.source_id}）` };
  }
  if (c.text_range && c.text_range.length === 2) {
    return { label: "本文範囲", value: `文字 ${c.text_range[0]}–${c.text_range[1]}（code-point offset）` };
  }
  return { label: "位置", value: c.chunk_id ?? "—" };
}

export default function CitationViewer({
  target,
  onClose,
}: {
  target: CitationViewTarget | null;
  onClose: () => void;
}) {
  const [sent, setSent] = useState<null | "correct" | "incorrect">(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset feedback state whenever a different citation is opened.
  useEffect(() => {
    setSent(null);
    setError(null);
    setBusy(false);
  }, [target?.answerId, target?.index]);

  // Close on Escape.
  useEffect(() => {
    if (!target) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  if (!target) return null;
  const { citation, answerId, groundedText, index } = target;
  const ap = approval(citation.approval_status);
  const loc = locatorRow(citation);

  async function sendFeedback(verdict: "correct" | "incorrect") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getSessionToken();
      await submitFeedback(
        {
          subject: "user",
          rating: verdict === "correct" ? 5 : 1,
          answer_id: answerId || undefined,
          comment: `citation:${citation.document_id}${citation.chunk_id ? `/${citation.chunk_id}` : ""} verdict:${verdict}`,
        },
        token,
      );
      setSent(verdict);
    } catch (err) {
      setError(err instanceof Error ? err.message : "送信に失敗しました");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cv-overlay" role="dialog" aria-modal="true" aria-label="引用ビューア" onClick={onClose}>
      <div className="cv-panel" onClick={(e) => e.stopPropagation()}>
        <header className="cv-head">
          <div className="cv-head-titles">
            <span className="cv-eyebrow">引用 {index} / 引用ビューア</span>
            <h3>{citation.document_id}</h3>
          </div>
          <button type="button" className="cv-close" aria-label="閉じる" onClick={onClose}>
            ✕
          </button>
        </header>

        <div className="cv-badges">
          <span className={`citation-chip ${ap.cls}`}>{ap.label}</span>
          <span className="citation-chip">{citation.kind === "visual" ? "ビジュアル" : "テキスト"}</span>
          <span className="citation-chip">スコア {citation.retrieval_score.toFixed(3)}</span>
        </div>

        <dl className="cv-fields">
          <div>
            <dt>ドキュメント</dt>
            <dd>{citation.document_id}</dd>
          </div>
          <div>
            <dt>チャンク</dt>
            <dd>{citation.chunk_id ?? "—"}</dd>
          </div>
          <div>
            <dt>ソース</dt>
            <dd>
              {citation.source_id} · v{citation.version}
            </dd>
          </div>
          <div>
            <dt>{loc.label}</dt>
            <dd>{loc.value}</dd>
          </div>
          <div>
            <dt>有効期限 / 発効</dt>
            <dd>{citation.effective_date ?? "—"}</dd>
          </div>
          <div>
            <dt>承認元</dt>
            <dd>{citation.approval_source ?? "—"}</dd>
          </div>
        </dl>

        {groundedText && (
          <section className="cv-grounded">
            <h4>この引用が根拠とする回答</h4>
            <p>{groundedText}</p>
          </section>
        )}

        <p className="cv-note">
          原本（PDFページ / Excelセル範囲 / 図面）の表示にはドキュメント本文・アセット取得 API が必要です（GAP）。
          現状は引用メタデータと根拠範囲を表示します。
        </p>

        <footer className="cv-foot">
          <span className="cv-foot-label">この引用は正しいですか？</span>
          <div className="cv-foot-actions">
            <button
              type="button"
              className={`cv-fb cv-fb-up ${sent === "correct" ? "is-active" : ""}`}
              disabled={busy || sent !== null}
              onClick={() => void sendFeedback("correct")}
            >
              👍 正しい
            </button>
            <button
              type="button"
              className={`cv-fb cv-fb-down ${sent === "incorrect" ? "is-active" : ""}`}
              disabled={busy || sent !== null}
              onClick={() => void sendFeedback("incorrect")}
            >
              👎 間違い
            </button>
          </div>
          {sent && <span className="cv-foot-done">フィードバックを送信しました</span>}
          {error && <span className="cv-foot-error">{error}</span>}
        </footer>
      </div>
    </div>
  );
}
