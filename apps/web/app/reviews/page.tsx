"use client";

export default function ReviewsPage() {
  return (
    <section className="workspace" aria-label="Reviews">
      <header className="topbar">
        <div>
          <p className="eyebrow">Human review loop</p>
          <h2>Reviews</h2>
        </div>
      </header>
      <section className="result-panel" aria-live="polite">
        <p className="empty-answer">
          Draft review and document approval (the human safety loop) — landing in the next slice.
        </p>
      </section>
    </section>
  );
}
