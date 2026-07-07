"use client";

import { useCallback, useEffect, useState } from "react";
import {
  applyExtractionReviewAction,
  extractionReviewMetrics,
  listExtractionReviews,
  type ExtractionReviewItem,
  type ExtractionReviewMetrics,
} from "../../../lib/api-client";
import { getSessionToken } from "../../../lib/session";

const ACTION_LABELS: Record<string, string> = {
  approve: "承認",
  edit_and_approve: "修正して承認",
  reject: "却下",
  reprocess: "再処理",
  mark_as_non_content: "対象外",
  escalate: "エスカレーション",
};

const REASON_LABELS: Record<string, string> = {
  mojibake_suspected: "文字化けの疑い",
  cid_artifacts: "CID/フォント欠落",
  empty_extraction: "抽出テキストが空",
  minor_mojibake: "軽微な文字化け",
  low_overall_confidence: "全体信頼度が低い",
  low_layout_confidence: "レイアウト信頼度が低い",
  low_table_structure_confidence: "表構造の信頼度が低い",
  drawing_only_page: "図面のみのページ",
  handwriting_or_seal_detected: "手書き/印鑑を検出",
  language_mismatch: "期待言語と不一致",
};

function reasonText(reasons: string[]): string {
  return reasons.map((r) => REASON_LABELS[r] ?? r).join(" / ");
}

function providerText(item: ExtractionReviewItem): string {
  const doc = item.provider_details ?? [];
  const blocks = item.block_provider_details ?? [];
  const values = [
    ...doc.map((p) => {
      const models = p.model_versions ? Object.values(p.model_versions).filter(Boolean) : [];
      const suffix = [p.provider_version, ...models, p.config_hash].filter(Boolean).join(" / ");
      return [p.provider, suffix].filter(Boolean).join("@");
    }),
    ...blocks.map((p) => {
      const suffix = [p.provider_version, p.model_version, p.prompt_version]
        .filter(Boolean)
        .join(" / ");
      return [p.provider, suffix || p.method || p.route].filter(Boolean).join("@");
    }),
  ].filter(Boolean);
  return Array.from(new Set(values)).join(" | ");
}

export default function ExtractionReviewPage() {
  const [items, setItems] = useState<ExtractionReviewItem[]>([]);
  const [metrics, setMetrics] = useState<ExtractionReviewMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState<string>("");
  const [editing, setEditing] = useState<{ chunkId: string; text: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = await getSessionToken();
      const [queue, m] = await Promise.all([
        listExtractionReviews(token),
        extractionReviewMetrics(token).catch(() => null),
      ]);
      setItems(queue.items);
      setMetrics(m);
    } catch (err) {
      setError(err instanceof Error ? err.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const act = useCallback(
    async (chunkId: string, action: string, extra?: { corrected_text?: string }) => {
      setBusy(chunkId);
      setError("");
      try {
        const token = await getSessionToken();
        await applyExtractionReviewAction({ chunk_id: chunkId, action, ...extra }, token);
        setEditing(null);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "操作に失敗しました");
      } finally {
        setBusy("");
      }
    },
    [refresh],
  );

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>抽出レビュー キュー</h1>
        <p style={{ color: "#556", marginTop: 6, fontSize: 14 }}>
          品質ゲートで隔離された抽出（文字化け・図面・手書きなど）を確認し、承認・却下します。承認された内容のみ検索・引用に使われます。
        </p>
      </header>

      {metrics && (
        <section
          style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}
          aria-label="品質メトリクス"
        >
          <Kpi label="総チャンク" value={String(metrics.total)} />
          <Kpi label="要レビュー" value={String(metrics.quarantined)} />
          <Kpi label="隔離率" value={`${Math.round((metrics.quarantine_rate ?? 0) * 100)}%`} />
        </section>
      )}

      {error && (
        <div role="alert" style={{ background: "#fdecec", color: "#a12", padding: "10px 12px", borderRadius: 8, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {loading ? (
        <p style={{ color: "#667" }}>読み込み中…</p>
      ) : items.length === 0 ? (
        <p style={{ color: "#667" }}>レビュー待ちの項目はありません。</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 12 }}>
          {items.map((item) => (
            <li
              key={item.chunk_id}
              style={{ border: "1px solid #e3e6ec", borderRadius: 10, padding: 14, background: "#fff" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {item.document_id}
                    {typeof item.page_no === "number" && (
                      <span style={{ fontWeight: 400, color: "#667", fontSize: 13 }}> ・ P.{item.page_no}</span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: "#667", marginTop: 2 }}>
                    <code style={{ fontSize: 12 }}>{item.chunk_id}</code>
                  </div>
                  <div style={{ fontSize: 13, color: "#a12", marginTop: 4 }}>{reasonText(item.reasons)}</div>
                  {item.text_snippet && (
                    <div
                      style={{ fontSize: 12, color: "#556", marginTop: 6, background: "#f6f7f9", padding: "6px 8px", borderRadius: 6, whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 76, overflow: "hidden" }}
                    >
                      {item.text_snippet}
                    </div>
                  )}
                  {item.suggested_action && ACTION_LABELS[item.suggested_action] && (
                    <div style={{ fontSize: 12, color: "#334", marginTop: 6 }}>
                      推奨: <strong>{ACTION_LABELS[item.suggested_action]}</strong>
                    </div>
                  )}
                  {item.route_trace && item.route_trace.length > 0 && (
                    <div style={{ fontSize: 11, color: "#889", marginTop: 6, fontFamily: "monospace" }}>
                      経路:{" "}
                      {item.route_trace
                        .map((s) => [s.stage, s.provider, s.result].filter(Boolean).join(":"))
                        .join(" → ")}
                    </div>
                  )}
                  {providerText(item) && (
                    <div style={{ fontSize: 11, color: "#667", marginTop: 4, fontFamily: "monospace" }}>
                      Provider: {providerText(item)}
                    </div>
                  )}
                </div>
                <span
                  style={{ alignSelf: "start", fontSize: 12, background: "#eef1f6", color: "#334", padding: "3px 8px", borderRadius: 999 }}
                >
                  {item.status}
                </span>
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                <ActionButton disabled={busy === item.chunk_id} onClick={() => act(item.chunk_id, "approve")} primary>
                  {ACTION_LABELS.approve}
                </ActionButton>
                <ActionButton
                  disabled={busy === item.chunk_id}
                  onClick={() => setEditing({ chunkId: item.chunk_id, text: "" })}
                >
                  {ACTION_LABELS.edit_and_approve}
                </ActionButton>
                <ActionButton disabled={busy === item.chunk_id} onClick={() => act(item.chunk_id, "reject")}>
                  {ACTION_LABELS.reject}
                </ActionButton>
                <ActionButton disabled={busy === item.chunk_id} onClick={() => act(item.chunk_id, "escalate")}>
                  {ACTION_LABELS.escalate}
                </ActionButton>
                <ActionButton
                  disabled={busy === item.chunk_id}
                  onClick={() => act(item.chunk_id, "mark_as_non_content")}
                >
                  {ACTION_LABELS.mark_as_non_content}
                </ActionButton>
              </div>

              {editing?.chunkId === item.chunk_id && (
                <div style={{ marginTop: 12 }}>
                  <textarea
                    value={editing.text}
                    onChange={(e) => setEditing({ chunkId: item.chunk_id, text: e.target.value })}
                    placeholder="修正後の正しいテキストを入力"
                    rows={3}
                    style={{ width: "100%", padding: 8, borderRadius: 8, border: "1px solid #ccd", fontSize: 14 }}
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <ActionButton
                      primary
                      disabled={busy === item.chunk_id || !editing.text.trim()}
                      onClick={() => act(item.chunk_id, "edit_and_approve", { corrected_text: editing.text })}
                    >
                      保存して承認
                    </ActionButton>
                    <ActionButton disabled={busy === item.chunk_id} onClick={() => setEditing(null)}>
                      キャンセル
                    </ActionButton>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ border: "1px solid #e3e6ec", borderRadius: 10, padding: "10px 16px", minWidth: 110, background: "#fff" }}>
      <div style={{ fontSize: 12, color: "#667" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  primary,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: "6px 14px",
        borderRadius: 8,
        border: primary ? "none" : "1px solid #ccd",
        background: primary ? "#2563eb" : "#fff",
        color: primary ? "#fff" : "#223",
        fontSize: 14,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
      }}
    >
      {children}
    </button>
  );
}
