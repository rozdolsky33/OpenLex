-- 0006_pg_stat_statements.sql
--
-- Enable the pg_stat_statements extension so postgres_exporter's `--collector.stat_statements`
-- (slow-query / call-rate visibility) works instead of erroring every scrape with
-- `function pg_stat_statements(boolean) does not exist`.
--
-- pg_stat_statements needs its shared library loaded via `shared_preload_libraries` at server
-- START (not reloadable), which is configured per-environment OUTSIDE this migration:
--   * kind:    infra/kubernetes/base/postgres/statefulset.yaml sets it on the postgres args.
--   * RDS:     the default DB parameter group already preloads it
--              (shared_preload_libraries = rdsutils,pg_tle,pg_stat_statements,rds_casts).
--   * compose: docker-compose.yml's pgvector image does NOT preload it.
--
-- This file is REPLAYED against every environment (the EKS migrate-job and compose's
-- docker-entrypoint-initdb.d both run every migrations/postgres/*.sql), so an unconditional
-- `CREATE EXTENSION` would abort compose bring-up with "pg_stat_statements must be loaded via
-- shared_preload_libraries". Guard on the library actually being preloaded: create the extension
-- where it can work (kind, RDS), no-op where it can't (compose). Idempotent.
DO $$
BEGIN
  IF current_setting('shared_preload_libraries') LIKE '%pg_stat_statements%' THEN
    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
  END IF;
END
$$;
