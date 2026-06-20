-- Rollback for 0001_core_rls.sql.
-- Intended for throwaway/local Tier B verification before persistent data exists.

DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS acl_grants CASCADE;
DROP TABLE IF EXISTS chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS data_sources CASCADE;
DROP TABLE IF EXISTS collections CASCADE;
DROP TABLE IF EXISTS query_profiles CASCADE;
DROP TABLE IF EXISTS tenants CASCADE;
DROP FUNCTION IF EXISTS raku.current_tenant_id();
DROP SCHEMA IF EXISTS raku;
