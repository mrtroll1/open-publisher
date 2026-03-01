# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Feature 6: Postgres Setup

- **DB_PASSWORD**: Set a secure password in `config/.env` (default `agent_dev_pass` is for dev only)
- **DATABASE_URL**: Update if you change the password or run Postgres on a non-default host/port
- Docker will auto-start Postgres with `docker compose up`. Data persists in the `pgdata` volume.
- Schema creates itself on first bot startup via `DbGateway.init_schema()`
