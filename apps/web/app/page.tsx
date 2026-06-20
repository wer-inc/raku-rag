"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { answer } from "../lib/api-client";
import type { AnswerResponse } from "@raku-rag/shared";

// Step 4b — minimal manufacturing-knowledge chat UI. Posts to the NestJS facade (/v1/answer), which
// forwards to the Python answer-service over the Postgres + pgvector + RLS ProductionSystem. The identity
// is taken from the signed token; switch tenant/user to see ACL + tenant isolation in the response.
function makeToken(tenantId: string, userId: string): string {
  const json = JSON.stringify({ tenant_id: tenantId, user_id: userId, groups: [], roles: [] });
  // base64url (NestJS parseUserToken decodes base64url, padding optional)
  return btoa(json).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export default function Home() {
  const [tenant, setTenant] = useState("demo");
  const [user, setUser] = useState("alice");
  const [query, setQuery] = useState("What is the maintenance interval for pump P-12?");
  const [res, setRes] = useState<AnswerResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setRes(null);
    try {
      setRes(await answer({ query }, makeToken(tenant, user)));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ fontFamily: "system-ui", padding: 32, maxWidth: 760, margin: "0 auto" }}>
      <h1>raku-rag — manufacturing field knowledge</h1>
      <p style={{ color: "#666" }}>
        web → NestJS <code>/v1/answer</code> → answer-service → ProductionSystem (Postgres + pgvector +
        RLS). Identity comes from the signed token — switch <em>tenant</em>/<em>user</em> to see ACL and
        tenant isolation. Try <code>demo / alice</code> (granted) vs <code>other / bob</code> (no access).
      </p>

      <form onSubmit={onAsk} style={{ display: "grid", gap: 8, marginTop: 16 }}>
        <div style={{ display: "flex", gap: 12 }}>
          <label>
            tenant{" "}
            <input value={tenant} onChange={(e) => setTenant(e.target.value)} style={{ width: 120 }} />
          </label>
          <label>
            user{" "}
            <input value={user} onChange={(e) => setUser(e.target.value)} style={{ width: 120 }} />
          </label>
        </div>
        <textarea value={query} onChange={(e) => setQuery(e.target.value)} rows={2} />
        <button type="submit" disabled={loading} style={{ padding: "6px 14px", width: "fit-content" }}>
          {loading ? "asking…" : "Ask"}
        </button>
      </form>

      {error && <p style={{ color: "crimson" }}>error: {error}</p>}

      {res && (
        <section style={{ marginTop: 24 }}>
          <p>
            <strong>status:</strong> <code>{res.status}</code>
          </p>
          {res.text ? (
            <blockquote style={{ borderLeft: "3px solid #0a0", paddingLeft: 12, margin: 0 }}>
              {res.text}
            </blockquote>
          ) : (
            <p style={{ color: "#a60" }}>
              No grounded answer — insufficient evidence, or not visible to this identity (ACL / tenant).
            </p>
          )}
          {res.citations.length > 0 && (
            <>
              <h3>citations</h3>
              <ul>
                {res.citations.map((c, i) => (
                  <li key={i}>
                    <code>{c.document_id}</code> · chunk <code>{c.chunk_id}</code> · score{" "}
                    {c.retrieval_score.toFixed(3)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </main>
  );
}
