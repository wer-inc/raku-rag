-- Rollback 0017_phone_rag: drop phone tables (policies/indexes drop with the tables).
SET search_path TO public;

DROP TABLE IF EXISTS phone_quality_evaluations;
DROP TABLE IF EXISTS phone_call_scenarios;
DROP TABLE IF EXISTS phone_handoff_packages;
DROP TABLE IF EXISTS phone_call_sessions;
