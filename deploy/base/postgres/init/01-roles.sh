# Login roles for the AI layer and the LLM gateway. Passwords are injected from a Kubernetes Secret.
# Grants are defined in 02-schema.sql, after the objects exist.
# The postgres entrypoint sources this file (it is not executable in the ConfigMap),
# so it must not change shell options.

psql -v ON_ERROR_STOP=1 --username postgres --dbname erp \
  -v reader_pw="$AI_READER_PASSWORD" -v writer_pw="$AI_WRITER_PASSWORD" \
  -v litellm_pw="$LITELLM_DB_PASSWORD" -v integration_pw="$ERP_INTEGRATION_PASSWORD" \
  -v audit_reader_pw="$AUDIT_READER_PASSWORD" <<'SQL'
CREATE ROLE ai_reader LOGIN PASSWORD :'reader_pw';
CREATE ROLE ai_writer LOGIN PASSWORD :'writer_pw';

-- Used only by the human-approval path, never by tools the model can call.
CREATE ROLE erp_integration LOGIN PASSWORD :'integration_pw';

-- Reads the audit log for the UI. Cannot write anything.
CREATE ROLE audit_reader LOGIN PASSWORD :'audit_reader_pw';

-- The LLM gateway keeps keys, budgets and spend logs in its own database.
CREATE ROLE litellm LOGIN PASSWORD :'litellm_pw';
CREATE DATABASE litellm OWNER litellm;
SQL
