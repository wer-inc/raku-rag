-- P1-10: durable manufacturing audit hash-chain payload.
--
-- The legacy summary columns stay queryable for dashboards. The canonical payload preserves every
-- redacted AuditLogEntry field so readback and verify_chain() can recompute the same hash after a
-- process restart.

ALTER TABLE manufacturing_audit_events
  ADD COLUMN IF NOT EXISTS entry_payload jsonb NOT NULL DEFAULT '{}'::jsonb;
