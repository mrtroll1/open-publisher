# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Feature 3: Redefine PNL API

- **Redefine PNL endpoint**: Need to confirm the actual API URL, auth credentials, and response format. Current code assumes `GET {PNL_API_URL}/stats?month=YYYY-MM` returns `{"data": {"items": [{"name": "...", "category": "...", "amount": 123456}]}}`. If the real API differs, adjust `RedefineGateway.get_pnl_stats()` and `ComputeBudget._build_pnl_rows()`.
- **Redefine team**: Provide PNL API credentials (HTTP Basic auth) for production use.

## Feature 5: Repo Access for Tech Support

- **Git repo access**: The Docker container needs to be able to clone private repos. Options: mount SSH key, use `.netrc` with HTTPS tokens, or use `git credential.helper`.
- **Repo URLs**: Set `REPUBLIC_REPO_URL` and `REDEFINE_REPO_URL` in `.env` to the actual git clone URLs.
- **Step 5.6 (future)**: Claude Code subprocess integration — spawn `claude -p "..." --max-turns 5` for deeper code analysis. Requires `ANTHROPIC_API_KEY` + Claude CLI installed in Docker. Not implemented yet.
