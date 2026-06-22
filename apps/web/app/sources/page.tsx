"use client";

export default function SourcesPage() {
  return (
    <section className="workspace" aria-label="Sources">
      <header className="topbar">
        <div>
          <p className="eyebrow">Knowledge sources</p>
          <h2>Sources</h2>
        </div>
      </header>
      <section className="result-panel" aria-live="polite">
        <p className="empty-answer">
          Browse sources, approval/freshness state, and past trouble-cases — landing in the next slice.
        </p>
      </section>
    </section>
  );
}
