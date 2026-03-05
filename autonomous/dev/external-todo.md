# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Article ingestion pipeline — DONE

Article ingestion now works via `/support/posts` endpoint with date range params. `cmd_ingest_articles` accepts date range (YYYY-MM-DD). Daily auto-ingest runs at 06:30 CET.

## Phase 9: DB Query Tool — setup required from Luka

The bot will query Republic and Redefine production databases directly via SSH tunnel + read-only postgres user. See `autonomous/plans/plan-9.md` for full plan.

### 1. Create read-only DB users

On **Republic** DB server: (already done)
```sql
CREATE USER agent_readonly WITH PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE <republic_db_name> TO agent_readonly;
GRANT USAGE ON SCHEMA public TO agent_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO agent_readonly;
```

On **Redefine** DB server: same, with its own password. (not done yet)

### 2. SSH access for tunneling

The bot will use `sshtunnel` to port-forward to each DB. Needed:
- [ ] SSH key pair for the bot (or reuse existing). Place private key at a path accessible from docker container
- [ ] Add bot's public key to `~/.ssh/authorized_keys` on Republic DB server
- [ ] Add bot's public key to `~/.ssh/authorized_keys` on Redefine DB server
- [ ] Verify the bot can SSH to both servers (may need firewall rules)

### 3. Env vars to add to `config/.env`

```
# Republic production DB (read-only, via SSH tunnel)
REPUBLIC_SSH_HOST=<republic-server-ip>
REPUBLIC_SSH_USER=<ssh-username>
REPUBLIC_SSH_KEY_PATH=/config/keys/republic_readonly_rsa
REPUBLIC_DB_HOST=127.0.0.1
REPUBLIC_DB_PORT=5432
REPUBLIC_DB_NAME=<republic_db_name>
REPUBLIC_DB_USER=agent_readonly
REPUBLIC_DB_PASS=<password-from-step-1>

# Redefine production DB (read-only, via SSH tunnel)
REDEFINE_SSH_HOST=<redefine-server-ip>
REDEFINE_SSH_USER=<ssh-username>
REDEFINE_SSH_KEY_PATH=/config/keys/redefine_readonly_rsa
REDEFINE_DB_HOST=127.0.0.1
REDEFINE_DB_PORT=5432
REDEFINE_DB_NAME=<redefine_db_name>
REDEFINE_DB_USER=agent_readonly
REDEFINE_DB_PASS=<password-from-step-1>
```

### 4. Provide DB schemas

For each database, share the output of:
```sql
\dt           -- list tables
\d <table>    -- for each relevant table
```

This is needed to write the schema templates that Gemini uses to compose queries.

