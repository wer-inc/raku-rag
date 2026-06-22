"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import type { DraftArtifact, DraftType } from "@raku-rag/shared";
import {
  manufacturingAssignReviewer,
  manufacturingCreateDraft,
  manufacturingDocumentApproval,
  manufacturingGetDraft,
  manufacturingReviewDraft,
} from "../../lib/api-client";
import { DEMO_COLLECTION, clearSessionToken, getSessionToken } from "../../lib/session";

const DRAFT_TYPES: DraftType[] = ["checklist", "trouble_report", "quality_report", "training", "faq"];
const APPROVAL_STATES = ["pending_review", "approved", "obsolete", "draft"];

function statusClass(status: string): string {
  if (status === "approved") return "approval-approved";
  if (status === "rejected" || status === "obsolete") return "approval-obsolete";
  return "approval-draft";
}

function Kv({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div>
      <dt>{label}</dt>
      <dd>{String(value)}</dd>
    </div>
  );
}

export default function ReviewsPage() {
  const [draft, setDraft] = useState<DraftArtifact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // load / create inputs
  const [loadId, setLoadId] = useState("");
  const [newKind, setNewKind] = useState<DraftType>("checklist");
  const [newSources, setNewSources] = useState("");
  // action inputs
  const [reviewerId, setReviewerId] = useState("");
  const [comment, setComment] = useState("");
  // document approval inputs
  const [docId, setDocId] = useState("");
  const [toStatus, setToStatus] = useState(APPROVAL_STATES[0]);
  const [approvalMsg, setApprovalMsg] = useState<string | null>(null);

  async function run<T>(fn: (token: string) => Promise<T>, onOk: (r: T) => void) {
    setBusy(true);
    setError(null);
    try {
      const token = await getSessionToken();
      onOk(await fn(token));
    } catch (err) {
      if (err instanceof Error && /session|token|auth/i.test(err.message)) clearSessionToken();
      setError(err instanceof Error ? err.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  function onLoad(event: FormEvent) {
    event.preventDefault();
    const id = loadId.trim();
    if (!id || busy) return;
    void run((t) => manufacturingGetDraft(id, t), setDraft);
  }

  function onCreate(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const source_document_ids = newSources
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    void run(
      (t) =>
        manufacturingCreateDraft(
          { kind: newKind, source_document_ids, collection_id: DEMO_COLLECTION },
          t,
        ),
      (d) => {
        setDraft(d);
        setLoadId(d.artifact_id);
      },
    );
  }

  function onAssign() {
    if (!draft || busy) return;
    const reviewer_id = reviewerId.trim();
    if (!reviewer_id) return;
    void run((t) => manufacturingAssignReviewer(draft.artifact_id, { reviewer_id }, t), setDraft);
  }

  function onReview(decision: "approved" | "rejected") {
    if (!draft || busy) return;
    void run(
      (t) =>
        manufacturingReviewDraft(
          draft.artifact_id,
          { decision, comment: comment.trim() || undefined },
          t,
        ),
      setDraft,
    );
  }

  function onApproval(event: FormEvent) {
    event.preventDefault();
    const id = docId.trim();
    if (!id || busy) return;
    setApprovalMsg(null);
    void run(
      (t) => manufacturingDocumentApproval(id, { to_status: toStatus }, t),
      (r) => setApprovalMsg(`${r.document_id}: approval transitioned`),
    );
  }

  const isAi = draft?.created_by === "ai";
  const notApproved = draft && draft.status !== "approved";

  return (
    <section className="workspace" aria-label="Reviews">
      <header className="topbar">
        <div>
          <p className="eyebrow">Human review loop</p>
          <h2>Reviews</h2>
        </div>
      </header>

      <p className="src-warning">
        AI output is always a <strong>draft</strong>. It is not approved knowledge until a human
        reviewer approves it — approval and document state transitions are recorded in the audit log.
      </p>

      <section className="ops-panel" aria-label="Load or create draft">
        <h3>Open a draft</h3>
        <form className="src-inline-form" onSubmit={onLoad}>
          <input
            value={loadId}
            onChange={(e) => setLoadId(e.target.value)}
            placeholder="artifact_id"
            aria-label="Artifact id"
            autoComplete="off"
          />
          <button type="submit" disabled={busy || loadId.trim().length === 0}>
            Load
          </button>
        </form>
        <form className="src-inline-form" onSubmit={onCreate}>
          <select
            value={newKind}
            onChange={(e) => setNewKind(e.target.value)}
            aria-label="Draft type"
          >
            {DRAFT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            value={newSources}
            onChange={(e) => setNewSources(e.target.value)}
            placeholder="source_document_ids (comma-separated)"
            aria-label="Source document ids"
            autoComplete="off"
          />
          <button type="submit" disabled={busy}>
            Generate
          </button>
        </form>
      </section>

      {error && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>Action failed</h3>
          <p>{error}</p>
        </section>
      )}

      {draft && (
        <section className="result-panel" aria-live="polite" aria-label="Draft">
          <div className="result-head">
            <span className={`citation-chip ${statusClass(draft.status)}`}>{draft.status}</span>
            <span className="correlation-id">{draft.artifact_id}</span>
          </div>
          <div className="ops-flags">
            <span className="citation-chip">{draft.type}</span>
            {isAi && <span className="citation-chip approval-draft">AI-authored</span>}
            {draft.created_by === "user" && <span className="citation-chip">user-authored</span>}
          </div>

          {notApproved && (
            <p className="src-warning">
              This draft is <strong>{draft.status}</strong> — not approved knowledge. Do not treat its
              content as an approved instruction.
            </p>
          )}

          <dl className="safety-fields">
            <Kv label="Created by" value={draft.created_by} />
            <Kv label="Created at" value={draft.created_at} />
            <Kv label="Template" value={draft.template_id} />
            <Kv label="Source documents" value={draft.source_document_ids.join(", ")} />
            <Kv label="Source citations" value={draft.source_citations.join(", ")} />
            <Kv label="Reviewer" value={draft.reviewer_id} />
            <Kv label="Assigned at" value={draft.assigned_at} />
            <Kv label="Reviewed at" value={draft.reviewed_at} />
            <Kv label="Decision" value={draft.approval_decision} />
            <Kv label="Review comment" value={draft.review_comment} />
            <Kv label="Audit ref" value={draft.audit_log_ref} />
          </dl>

          <div className="review-actions">
            <h4 className="src-h4">Reviewer actions</h4>
            <div className="src-inline-form">
              <input
                value={reviewerId}
                onChange={(e) => setReviewerId(e.target.value)}
                placeholder="reviewer_id"
                aria-label="Reviewer id"
                autoComplete="off"
              />
              <button type="button" onClick={onAssign} disabled={busy || !reviewerId.trim()}>
                Assign
              </button>
            </div>
            <textarea
              aria-label="Review comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="review comment (optional)"
              rows={2}
            />
            <div className="review-decide">
              <button
                type="button"
                className="btn-approve"
                onClick={() => onReview("approved")}
                disabled={busy}
              >
                Approve
              </button>
              <button
                type="button"
                className="btn-reject"
                onClick={() => onReview("rejected")}
                disabled={busy}
              >
                Reject
              </button>
            </div>
            <p className="ops-note">
              Approval requires a reviewer and is enforced server-side; an unauthorized action is
              rejected and leaves the draft unchanged.
            </p>
          </div>
        </section>
      )}

      <section className="ops-panel" aria-label="Document approval">
        <h3>Document approval</h3>
        <form className="src-inline-form" onSubmit={onApproval}>
          <input
            value={docId}
            onChange={(e) => setDocId(e.target.value)}
            placeholder="document_id"
            aria-label="Document id"
            autoComplete="off"
          />
          <select value={toStatus} onChange={(e) => setToStatus(e.target.value)} aria-label="To status">
            {APPROVAL_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <button type="submit" disabled={busy || docId.trim().length === 0}>
            Transition
          </button>
        </form>
        {approvalMsg && <p className="ops-note">{approvalMsg}</p>}
      </section>
    </section>
  );
}
