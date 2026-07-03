-- ★G4: document freshness — owner / review-cycle / last-verified on manufacturing doc metadata.
--
-- goal.md §1-4: document lifecycle management is a PRODUCT feature, but documents carried no owner,
-- review cycle, or last-verified fields — the only staleness signal was the obsolete approval
-- status. These additive columns (safe defaults, no backfill needed) let the KPI/dashboard views
-- derive `review_overdue` (= last_verified_at + review_cycle_days < today, both set) and surface a
-- 最終確認日 / 要再確認 trust signal on citations. The flag is DERIVED, never stored, and never a
-- safety-gate input (approval/effective/obsolete remain the safety boundary). Canonical /
-- latest-version selection across sibling documents is deferred (goal-gap-audit.md ★G4).
--
-- Table inherits the 0006 tenant RLS policy + raku_app grants unchanged (column-only change).
SET search_path TO public;

ALTER TABLE manufacturing_document_metadata
  ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS review_cycle_days integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_verified_at date;
