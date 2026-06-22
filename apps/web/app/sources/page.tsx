"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import type {
  Citation,
  DisplayCountermeasure,
  IngestionRunStatusResponse,
  SourceSyncStatusResponse,
  TroubleCaseMatch,
  TroubleCaseSearchResponse,
} from "@raku-rag/shared";
import {
  manufacturingIngestionRun,
  manufacturingSourceSyncStatus,
  manufacturingTroubleCaseSearch,
} from "../../lib/api-client";
import { DEMO_COLLECTION, clearSessionToken, getSessionToken } from "../../lib/session";

function CitationChips({ citation }: { citation: Citation }) {
  return (
    <div className="citation-meta">
      {citation.approval_status && (
        <span className={`citation-chip approval-${citation.approval_status}`}>
          {citation.approval_status}
        </span>
      )}
      {citation.effective_date && (
        <span className="citation-chip">effective {citation.effective_date}</span>
      )}
      {citation.approval_source && <span className="citation-chip">{citation.approval_source}</span>}
    </div>
  );
}

function Measure({ measure }: { measure: DisplayCountermeasure }) {
  return (
    <li className="measure-row">
      <div>
        <p className="measure-desc">{measure.description}</p>
        <div className="citation-meta">
          <span className="citation-chip approval-draft">candidate</span>
          <span className="citation-chip">{measure.measure_class}</span>
          {measure.label && <span className="measure-label">{measure.label}</span>}
        </div>
      </div>
    </li>
  );
}

function MatchCard({ match }: { match: TroubleCaseMatch }) {
  const { provisional, permanent } = match.countermeasures;
  return (
    <article className="result-panel">
      <div className="result-head">
        <span className="status-badge">{match.symptom || match.trouble_case_id}</span>
        <output>{match.relevance_score.toFixed(3)}</output>
      </div>
      <div className="ops-flags">
        {match.equipment_id && <span className="citation-chip">equip {match.equipment_id}</span>}
        {match.process_id && <span className="citation-chip">process {match.process_id}</span>}
        <span className="citation-chip">case {match.trouble_case_id}</span>
      </div>

      {match.failure_mode && (
        <div>
          <h4 className="src-h4">Likely cause</h4>
          <p className="answer-text src-cause">
            {match.failure_mode.name}
            {match.failure_mode.description ? ` — ${match.failure_mode.description}` : ""}
          </p>
        </div>
      )}

      <div>
        <h4 className="src-h4">Countermeasures (past-case candidates / reference)</h4>
        <p className="src-warning">
          Shown as candidates / past examples — not a definitive or official work order. Confirm
          on-site and follow the approved procedure.
        </p>
        {provisional.length > 0 && (
          <>
            <p className="src-bucket">Provisional</p>
            <ul className="measure-list">
              {provisional.map((m) => (
                <Measure key={m.measure_id} measure={m} />
              ))}
            </ul>
          </>
        )}
        {permanent.length > 0 && (
          <>
            <p className="src-bucket">Permanent</p>
            <ul className="measure-list">
              {permanent.map((m) => (
                <Measure key={m.measure_id} measure={m} />
              ))}
            </ul>
          </>
        )}
        {provisional.length === 0 && permanent.length === 0 && (
          <p className="ops-empty">No countermeasures recorded for this case.</p>
        )}
      </div>

      {match.recurrence_prevention && (
        <div>
          <h4 className="src-h4">Recurrence prevention</h4>
          <p className="answer-text src-cause">{match.recurrence_prevention}</p>
        </div>
      )}

      {match.citations.length > 0 && (
        <div className="citation-list">
          <h4 className="src-h4">Citations</h4>
          <div className="citation-grid">
            {match.citations.map((c, i) => (
              <article className="citation-row" key={`${c.document_id}-${i}`}>
                <div>
                  <strong>
                    {c.document_id}
                    {c.chunk_id ? ` / ${c.chunk_id}` : ""}
                  </strong>
                  <span>
                    {c.source_id} · v{c.version}
                  </span>
                  <CitationChips citation={c} />
                </div>
                <output>{c.retrieval_score.toFixed(3)}</output>
              </article>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

function KvGrid({ rows }: { rows: Array<[string, string | number | null | undefined]> }) {
  return (
    <dl className="safety-fields">
      {rows
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{String(v)}</dd>
          </div>
        ))}
    </dl>
  );
}

export default function SourcesPage() {
  const [symptom, setSymptom] = useState("");
  const [collection, setCollection] = useState(DEMO_COLLECTION);
  const [tcResult, setTcResult] = useState<TroubleCaseSearchResponse | null>(null);
  const [tcLoading, setTcLoading] = useState(false);
  const [tcError, setTcError] = useState<string | null>(null);

  const [sourceId, setSourceId] = useState("");
  const [sync, setSync] = useState<SourceSyncStatusResponse | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<IngestionRunStatusResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  async function onSearch(event: FormEvent) {
    event.preventDefault();
    const q = symptom.trim();
    if (!q || tcLoading) return;
    setTcLoading(true);
    setTcError(null);
    setTcResult(null);
    try {
      const token = await getSessionToken();
      setTcResult(
        await manufacturingTroubleCaseSearch(
          { symptom_query: q, collection_id: collection.trim() || DEMO_COLLECTION },
          token,
        ),
      );
    } catch (err) {
      clearSessionToken();
      setTcError(err instanceof Error ? err.message : "search failed");
    } finally {
      setTcLoading(false);
    }
  }

  async function onSync(event: FormEvent) {
    event.preventDefault();
    const id = sourceId.trim();
    if (!id) return;
    setSyncError(null);
    setSync(null);
    try {
      const token = await getSessionToken();
      setSync(await manufacturingSourceSyncStatus(id, token));
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "lookup failed");
    }
  }

  async function onRun(event: FormEvent) {
    event.preventDefault();
    const id = runId.trim();
    if (!id) return;
    setRunError(null);
    setRun(null);
    try {
      const token = await getSessionToken();
      setRun(await manufacturingIngestionRun(id, token));
    } catch (err) {
      setRunError(err instanceof Error ? err.message : "lookup failed");
    }
  }

  return (
    <section className="workspace" aria-label="Sources">
      <header className="topbar">
        <div>
          <p className="eyebrow">Knowledge sources</p>
          <h2>Sources</h2>
        </div>
        <label className="collection-field">
          <span>Collection</span>
          <input
            value={collection}
            onChange={(e) => setCollection(e.target.value)}
            placeholder="manuals"
            autoComplete="off"
          />
        </label>
      </header>

      <form className="question-panel" onSubmit={onSearch}>
        <label className="src-field-label" htmlFor="symptom">
          Search past trouble-cases by symptom
        </label>
        <textarea
          id="symptom"
          aria-label="Symptom"
          value={symptom}
          onChange={(e) => setSymptom(e.target.value)}
          placeholder="e.g. pump P-12 abnormal vibration and overheating"
          rows={3}
        />
        <div className="composer-row">
          <span className="session-label">candidates / reference only</span>
          <button type="submit" disabled={tcLoading || symptom.trim().length === 0}>
            {tcLoading ? "Searching" : "Search"}
          </button>
        </div>
      </form>

      {tcError && (
        <section className="result-panel error-panel" aria-live="polite">
          <h3>Search failed</h3>
          <p>{tcError}</p>
        </section>
      )}

      {tcResult && tcResult.status !== "ok" && (
        <section className="result-panel" aria-live="polite">
          <p className="empty-answer">No matching past cases with sufficient evidence.</p>
        </section>
      )}

      {tcResult?.results.map((m) => (
        <MatchCard key={m.trouble_case_id} match={m} />
      ))}

      <section className="ops-panel" aria-label="Source sync status">
        <h3>Source sync status</h3>
        <form className="src-inline-form" onSubmit={onSync}>
          <input
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            placeholder="source_id"
            autoComplete="off"
            aria-label="Source id"
          />
          <button type="submit" disabled={sourceId.trim().length === 0}>
            Look up
          </button>
        </form>
        {syncError && <p className="ops-empty">{syncError}</p>}
        {sync && (
          <KvGrid
            rows={[
              ["status", sync.status],
              ["last successful sync", sync.freshness?.last_successful_sync_at ?? null],
              ["last ingestion run", sync.last_ingestion_run_id],
              ["observed", sync.observed_count],
              ["changed", sync.changed_count],
              ["deleted", sync.deleted_count],
              ["failed", sync.failed_count],
              ["last error", sync.last_error],
            ]}
          />
        )}
      </section>

      <section className="ops-panel" aria-label="Ingestion run status">
        <h3>Ingestion run status</h3>
        <form className="src-inline-form" onSubmit={onRun}>
          <input
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            placeholder="ingestion_run_id"
            autoComplete="off"
            aria-label="Ingestion run id"
          />
          <button type="submit" disabled={runId.trim().length === 0}>
            Look up
          </button>
        </form>
        {runError && <p className="ops-empty">{runError}</p>}
        {run && (
          <>
            <KvGrid
              rows={[
                ["status", run.status],
                ["type", run.type],
                ["trigger", run.trigger],
                ["observed", run.summary?.observed_count],
                ["changed", run.summary?.changed_count],
                ["failed", run.summary?.failed_count],
                ["started", run.started_at],
                ["finished", run.finished_at],
                ["failure", run.failure_reason],
              ]}
            />
            {run.documents.length > 0 && (
              <>
                <h4 className="src-h4">Documents</h4>
                <ul className="ops-list">
                  {run.documents.map((d) => (
                    <li key={d.document_id}>
                      <span className="ops-kv-key">{d.document_id}</span>
                      <span className="ops-kv-val">{d.index_status}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </section>
    </section>
  );
}
