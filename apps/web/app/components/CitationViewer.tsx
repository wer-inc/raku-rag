"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Citation, CitationPreview } from "@raku-rag/shared";
import { adminCitationView, adminDocumentFile, submitFeedback } from "../../lib/api-client";
import { getSessionToken } from "../../lib/session";
import { useDialog } from "../../lib/use-dialog";

export interface CitationViewTarget {
  citation: Citation;
  answerId: string;
  groundedText: string | null;
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

function locatorFromPreview(preview?: CitationPreview | null): { label: string; value: string } {
  if (!preview) return { label: "位置", value: "—" };
  if (preview.kind === "spreadsheet" && preview.cell_range) {
    return { label: "Excel", value: `${preview.sheet_name ?? "—"} · ${preview.cell_range}` };
  }
  if (preview.heading_path?.length) {
    return { label: "見出し", value: preview.heading_path.join(" › ") };
  }
  if (preview.page_number) {
    return { label: "PDF ページ", value: String(preview.page_number) };
  }
  return { label: "形式", value: preview.content_type };
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
  const [sourceText, setSourceText] = useState<string | null>(null);
  const [preview, setPreview] = useState<CitationPreview | null>(null);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSent(null);
    setError(null);
    setBusy(false);
    setSourceText(null);
    setPreview(null);
    setLoadError(null);
    if (fileUrl) URL.revokeObjectURL(fileUrl);
    setFileUrl(null);
  }, [target?.answerId, target?.index]);

  useEffect(() => {
    if (!target) return;
    let active = true;
    void (async () => {
      try {
        const token = await getSessionToken();
        const view = await adminCitationView(
          target.citation.document_id,
          token,
          target.citation.chunk_id ?? undefined,
        );
        if (!active) return;
        const chunk = view.chunks?.[0];
        setSourceText(chunk?.text ?? null);
        setPreview(view.preview ?? null);
        if (view.preview?.has_source_file) {
          try {
            const file = await adminDocumentFile(target.citation.document_id, token);
            if (!active || file.too_large || !file.content_base64) return;
            const binary = atob(file.content_base64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
            const blob = new Blob([bytes], { type: file.content_type || "application/octet-stream" });
            setFileUrl(URL.createObjectURL(blob));
          } catch {
            /* file preview optional */
          }
        }
      } catch (err) {
        if (active) {
          setLoadError(err instanceof Error ? err.message : "引用元の読み込みに失敗しました");
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [target]);

  // Escape-to-close + focus trap + initial focus + restore-on-close (shared modal a11y).
  useDialog(target != null, onClose, panelRef);

  useEffect(() => {
    return () => {
      if (fileUrl) URL.revokeObjectURL(fileUrl);
    };
  }, [fileUrl]);

  const loc = useMemo(() => locatorFromPreview(preview), [preview]);

  if (!target) return null;
  const { citation, answerId, groundedText, index } = target;
  const ap = approval(citation.approval_status);
  const isObsolete = citation.approval_status === "obsolete";
  const isPdf = preview?.kind === "pdf" || (preview?.content_type ?? "").includes("pdf");

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
    <div className="cv-overlay" onClick={onClose}>
      <div
        ref={panelRef}
        className="cv-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cv-dialog-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="cv-head">
          <div className="cv-head-titles">
            <span className="cv-eyebrow">引用 {index} / 引用ビューア</span>
            <h3 id="cv-dialog-title">{citation.document_id}</h3>
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

        {isObsolete && (
          <p className="src-warning">この引用元は旧版です。正式な根拠として使わないでください。</p>
        )}

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
            <dt>{loc.label}</dt>
            <dd>{loc.value}</dd>
          </div>
          <div>
            <dt>有効期限 / 発効</dt>
            <dd>{citation.effective_date ?? "—"}</dd>
          </div>
        </dl>

        {preview?.kind === "spreadsheet" && (
          <section className="cv-grounded">
            <h4>Excel セル参照</h4>
            <FieldGrid
              rows={[
                ["シート", preview.sheet_name ?? "—"],
                ["行", preview.row ?? "—"],
                ["列", preview.col ?? "—"],
                ["範囲", preview.cell_range ?? "—"],
              ]}
            />
          </section>
        )}

        {preview?.crop_url && (
          <section className="cv-grounded">
            <h4>引用箇所</h4>
            <img
              className="cv-crop-image"
              src={preview.crop_url}
              alt={`${citation.document_id} の引用箇所`}
            />
          </section>
        )}

        {fileUrl && isPdf && (
          <section className="cv-grounded">
            <h4>PDF プレビュー</h4>
            <iframe className="cv-pdf-frame" src={fileUrl} title={`${citation.document_id} preview`} />
          </section>
        )}

        <section className="cv-grounded">
          <h4>引用元テキスト</h4>
          {sourceText ? (
            <pre className="cv-source-text">{sourceText}</pre>
          ) : loadError ? (
            <p className="cv-foot-error">{loadError}</p>
          ) : (
            <p className="ops-empty">引用元を読み込み中…</p>
          )}
        </section>

        {groundedText && (
          <section className="cv-grounded">
            <h4>この引用が根拠とする回答</h4>
            <p>{groundedText}</p>
          </section>
        )}

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

function FieldGrid({ rows }: { rows: Array<[string, string | number]> }) {
  return (
    <dl className="cv-fields">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
