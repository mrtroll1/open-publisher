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

## Feature 4: Article Proposal Monitoring

- **CHIEF_EDITOR_EMAIL**: Set to the chief editor's email address in `config/.env`. If empty, proposal forwarding is silently skipped.
- Non-support emails (those NOT addressed to `SUPPORT_ADDRESSES`) are automatically triaged by LLM to detect article proposals.
- Legitimate proposals are forwarded to the chief editor via Gmail API and admin is notified via Telegram.
- All non-support emails are marked as read after processing (whether forwarded or not).

## Feature 5: Repo Access for Tech Support

- **REPUBLIC_REPO_URL** / **REDEFINE_REPO_URL**: Set to the git clone URLs of the Republic and Redefine repos. If empty, code context is skipped entirely.
- **REPOS_DIR**: Directory where repos are cloned (default `/opt/repos`, mapped via `./repos:/opt/repos` in docker-compose).
- **ANTHROPIC_API_KEY**: Added to config but not yet used (reserved for future Claude Code subprocess in Step 5.6).
- **Git access in Docker**: The Dockerfile now installs `git`. If repos are private, you'll need to configure git credentials inside the container (e.g. via `.netrc` or SSH key mounted as a volume).
- **How it works**: When a support email arrives, an LLM extracts search terms. If the email needs code context (`needs_code: true`), the system greps the cloned repos and includes relevant file snippets in the support draft prompt. If repos aren't configured or no matches are found, the feature is silently skipped.
- Create a `repos/` directory in the project root (it's git-ignored by docker-compose bind mount).
