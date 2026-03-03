# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Plan 3: Knowledge DB

### Run seed script after deploy
After deploying the updated code (with pgvector tables + embedding gateway):
```bash
python -m backend.domain.use_cases.seed_knowledge
```
This seeds 19 knowledge entries from the existing `.md` files into the `knowledge_entries` table. Requires:
- Running Postgres with pgvector extension
- `GEMINI_API_KEY` configured for embedding generation
- One-time operation, idempotent (skips if entries already exist)

