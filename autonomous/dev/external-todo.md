# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Feature 3: Redefine PNL API

- **Redefine PNL endpoint**: Need to confirm the actual API URL, auth credentials, and response format. Current code assumes `GET {PNL_API_URL}/stats?month=YYYY-MM` returns `{"data": {"items": [{"name": "...", "category": "...", "amount": 123456}]}}`. If the real API differs, adjust `RedefineGateway.get_pnl_stats()` and `ComputeBudget._build_pnl_rows()`.
- **Redefine team**: Provide PNL API credentials (HTTP Basic auth) for production use.
