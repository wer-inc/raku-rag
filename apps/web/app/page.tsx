"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { AnswerResponse, Citation } from "@raku-rag/shared";
import { answer } from "../lib/api-client";

const DEFAULT_TENANT = process.env.NEXT_PUBLIC_DEMO_TENANT_ID ?? "demo";
const DEFAULT_USER = process.env.NEXT_PUBLIC_DEMO_USER_ID ?? "alice";
const DEFAULT_COLLECTION = process.env.NEXT_PUBLIC_DEMO_COLLECTION_ID ?? "manuals";

async function makeToken(tenantId: string, userId: string): Promise<string> {
  const res = await fetch("/api/dev-token", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tenant_id: tenantId, user_id: userId, groups: [], roles: [] }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || typeof body.token !== "string") {
    throw new Error(typeof body.error === "string" ? body.error : "failed to create session");
  }
  return body.token;
}

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

export default function Home() {
  const [query, setQuery] = useState("");
  const [collectionId, setCollectionId] = useState(DEFAULT_COLLECTION);
  const [response, setResponse] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const citations = useMemo(() => response?.citations ?? [], [response]);

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const token = await makeToken(DEFAULT_TENANT, DEFAULT_USER);
      setResponse(
        await answer(
          {
            query: trimmed,
            collection_id: collectionId.trim() || DEFAULT_COLLECTION,
          },
          token,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Workspace">
        <div>
          <p className="eyebrow">Raku RAG</p>
          <h1>Manufacturing Knowledge</h1>
        </div>
        <nav className="nav-list" aria-label="Primary">
          <span className="nav-item active">Answers</span>
          <span className="nav-item">Sources</span>
          <span className="nav-item">Reviews</span>
          <span className="nav-item">Operations</span>
        </nav>
      </aside>

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
            <span className="session-label">{DEFAULT_TENANT}</span>
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

            {response.text ? (
              <p className="answer-text">{response.text}</p>
            ) : (
              <p className="empty-answer">No supported answer was returned.</p>
            )}

            {citations.length > 0 && (
              <div className="citation-list">
                <h3>Citations</h3>
                <div className="citation-grid">
                  {citations.map((citation, index) => (
                    <article className="citation-row" key={`${citation.document_id}-${index}`}>
                      <div>
                        <strong>{citationLabel(citation)}</strong>
                        <span>{citation.source_id}</span>
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
    </main>
  );
}
