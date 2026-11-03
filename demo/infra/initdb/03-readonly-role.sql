-- Least-privilege role used by the AI employee for research.
CREATE ROLE dex_readonly LOGIN PASSWORD 'dex_readonly';
GRANT CONNECT ON DATABASE deleg8 TO dex_readonly;
GRANT USAGE ON SCHEMA public TO dex_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dex_readonly;
ALTER ROLE dex_readonly SET default_transaction_read_only = on;
