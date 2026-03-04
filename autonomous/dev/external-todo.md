# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Article ingestion pipeline

The pipeline code exists (`IngestArticles`, `cmd_ingest_articles`) but only ingests author metadata (names + post counts), not actual article content. LLM summarization is implemented but never triggered because the Republic API endpoint (`/posts/authors`) doesn't return article bodies.

To make it actually useful:

- [ ] **Republic API**: Add an endpoint that returns article content (title + body text), not just author stats. Current endpoint `REPUBLIC_API_URL/posts/authors?month=YYYY-MM` only returns `{"author": "...", "post_count": N}`. Need something like `/posts?month=YYYY-MM` → `[{"title": "...", "content": "...", "url": "..."}]`
- [ ] **Env var `REPUBLIC_API_URL`**: Must be set and pointing to a running Republic content API instance
- [ ] **Env var `GEMINI_API_KEY`**: Must be set (needed for LLM summarization via Gemini)
- [ ] Once the API returns content, update `cmd_ingest_articles` to pass article bodies (not just author titles) to `IngestArticles.execute()`

