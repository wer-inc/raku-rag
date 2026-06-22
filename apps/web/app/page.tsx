"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { AnswerResponse, Citation, ManufacturingAnswerResponse } from "@raku-rag/shared";
import { manufacturingAnswer } from "../lib/api-client";
import { DEMO_COLLECTION, DEMO_TENANT, clearSessionToken, getSessionToken } from "../lib/session";

function statusLabel(status: AnswerResponse["status"]): string {
  if (status === "ok") return "Answered";
  if (status === "insufficient_evidence") return "Needs evidence";
  if (status === "budget_exceeded") return "Budget limit";
  return "Unavailable";
}

function citationLabel(citation: Citation): string {
  const chunk = citation.chunk_id ? ` / ${citation.chunk_id}` : "";
  return `${citation.document_id}${chunk}`;
}

function safetyLabel(response: ManufacturingAnswerResponse): string {
  const safety = response.manufacturing;
  if (safety.safety_block_reason) return "Blocked";
  if (safety.high_risk) return "High risk";
  if (safety.obsolete_warning) return "Obsolete source";
  return "Cleared";
}

function formatField(value: string | number | boolean | null | undefined): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [collectionId, setCollectionId] = useState(DEMO_COLLECTION);
  const [response, setResponse] = useState<ManufacturingAnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const citations = useMemo(() => response?.citations ?? [], [response]);
  const safety = response?.manufacturing;

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const token = await getSessionToken();
      setResponse(
        await manufacturingAnswer(
          {
            query: trimmed,
            collection_id: collectionId.trim() || DEMO_COLLECTION,
          },
          token,
        ),
      );
    } catch (err) {
      clearSessionToken();
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="workspace" aria-label="Answer workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Knowledge assistant</p>
          <h2>Ask a grounded question</h2>
        </div>
        <label className="collection-field">
          <span>Collection</span>
          <input
            value={collectionId}
            onChange={(event) => setCollectionId(event.target.value)}
            placeholder="manuals"
            autoComplete="off"
          />
        </label>
      </header>

      <form className="question-panel" onSubmit={onAsk}>
        <textarea
          aria-label="Question"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="What is the maintenance interval for pump P-12?"
          rows={4}
        />
        <div className="composer-row">
          <span className="session-label">{DEMO_TENANT}</span>
          <button type="submit" disabled={loading || query.trim().length === 0}>
            {loading ? "Working" : "Ask"}
          </button>
        </div>
      </form>

      {error && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>Request failed</h3>
          <p>{error}</p>
        </section>
      )}

      {response && (
        <section className="result-panel" aria-live="polite">
          <div className="result-head">
            <span className={`status-badge status-${response.status}`}>
              {statusLabel(response.status)}
            </span>
            <span className="correlation-id">{response.correlation_id}</span>
          </div>

          {safety?.obsolete_warning && (
            <p className="src-warning">
              This answer relies on an obsolete or superseded source. Treat it as reference only —
              confirm against the current approved document before acting.
            </p>
          )}

          {response.text ? (
            <p className={`answer-text${safety?.obsolete_warning ? " answer-text-muted" : ""}`}>
              {response.text}
            </p>
          ) : (
            <p className="empty-answer">No supported answer was returned.</p>
          )}

          {safety && (
            <section
              className={`safety-panel ${safety.safety_block_reason ? "safety-blocked" : ""}`}
              aria-label="Safety state"
            >
              <div className="safety-head">
                <span className="safety-title">{safetyLabel(response)}</span>
                {safety.high_risk && <span className="safety-pill">high risk</span>}
                {safety.obsolete_warning && <span className="safety-pill warning">obsolete</span>}
                {safety.requires_onsite_confirmation && (
                  <span className="safety-pill warning">on-site confirmation</span>
                )}
              </div>
              <dl className="safety-fields">
                {formatField(safety.safety_block_reason) && (
                  <div>
                    <dt>Block reason</dt>
                    <dd>{safety.safety_block_reason}</dd>
                  </div>
                )}
                {safety.high_risk_reason_codes.length > 0 && (
                  <div>
                    <dt>Risk codes</dt>
                    <dd>{safety.high_risk_reason_codes.join(", ")}</dd>
                  </div>
                )}
                {formatField(safety.notice) && (
                  <div>
                    <dt>Notice</dt>
                    <dd>{safety.notice}</dd>
                  </div>
                )}
              </dl>
            </section>
          )}

          {citations.length > 0 && (
            <div className="citation-list">
              <h3>Citations</h3>
              <div className="citation-grid">
                {citations.map((citation, index) => (
                  <article className="citation-row" key={`${citation.document_id}-${index}`}>
                    <div>
                      <strong>{citationLabel(citation)}</strong>
                      <span>
                        {citation.source_id} · v{citation.version}
                      </span>
                      <div className="citation-meta">
                        {citation.approval_status && (
                          <span className={`citation-chip approval-${citation.approval_status}`}>
                            {citation.approval_status}
                          </span>
                        )}
                        {citation.effective_date && (
                          <span className="citation-chip">effective {citation.effective_date}</span>
                        )}
                        {citation.approval_source && (
                          <span className="citation-chip">{citation.approval_source}</span>
                        )}
                      </div>
                    </div>
                    <output>{citation.retrieval_score.toFixed(3)}</output>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      )}
    </section>
  );
}
