# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Feature 6: Postgres Setup

- **DB_PASSWORD**: Set a secure password in `config/.env` (default `agent_dev_pass` is for dev only)
- **DATABASE_URL**: Update if you change the password or run Postgres on a non-default host/port
- Docker will auto-start Postgres with `docker compose up`. Data persists in the `pgdata` volume.
- Schema creates itself on first bot startup via `DbGateway.init_schema()`

## Feature 3: Redefine PNL + Exchange Rate

- **PNL_API_URL**: Set to the Redefine PNL API base URL (e.g. `https://redefine.example.com/api/pnl`)
- **PNL_API_USER** / **PNL_API_PASSWORD**: HTTP Basic auth credentials for the PNL API
- **EUR_RUB_CELL**: Cell where EUR/RUB rate is written in the budget sheet (default `G2`)
- **PNL API response format**: The code expects `{"data": {"items": [{"name": "...", "category": "...", "amount": 123456}]}}`. Verify this matches the actual Redefine PNL API response and adjust `_build_pnl_rows()` in `compute_budget.py` if needed.
- Exchange rate is fetched from `open.er-api.com` (free, no API key). If this service goes down, the rate will be `0.0` and PNL rows will be skipped.
