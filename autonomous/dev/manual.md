# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Code-access (repo cloning):

- **How it works**: On startup, the bot clones all configured repos (shallow, `--depth 1`) into `/opt/repos`. Every restart does a fresh re-clone — no local state is ever kept.
- **REPO_* env vars**: Each `REPO_<NAME>=<url>` var in `.env` becomes a clone target. The directory name is the suffix lowercased (e.g. `REPO_REPUBLIC_API` → `/opt/repos/republic_api`).
- **Git tokens**: Create a **Project Access Token** on GitLab for each repo with `read_repository` scope. This keeps access read-only and per-repo (you can upgrade any single token to `write_repository` later). The clone URL format is `https://oauth2:<token>@gitlab.com/group/repo.git`.
- **REPOS_DIR**: Directory where repos are cloned (default `/opt/repos`, mapped via `./repos:/opt/repos` in docker-compose).
- Create a `repos/` directory in the project root (it's git-ignored by docker-compose bind mount).

Example `.env` entries:
```
REPO_REPUBLIC_CMS=https://oauth2:glpat-xxx@gitlab.com/republic/republic.git
REPO_REPUBLIC_API=https://oauth2:glpat-yyy@gitlab.com/republic/republic-api.git
REPO_REPUBLIC_NUXT=https://oauth2:glpat-zzz@gitlab.com/republic/nuxt.git
REPO_REDEFINE_BACK=https://oauth2:glpat-aaa@gitlab.com/flamecms/redefine-back.git
REPO_REDEFINE_PAYMENT=https://oauth2:glpat-bbb@gitlab.com/flamecms/payment.git
```

## /code command (Claude Code CLI):

- **Dockerfile**: Installs Node.js 20 and `@anthropic-ai/claude-code` globally (~200MB added to image). Node.js is required because Claude Code CLI is an npm package.
- **ANTHROPIC_API_KEY**: Required — Claude Code CLI calls the Anthropic API to answer queries. Get a key from [console.anthropic.com](https://console.anthropic.com). Set it in `.env`.
- Claude CLI runs in `REPOS_DIR` (`/opt/repos` by default), so it has access to all cloned repos.
- A `CLAUDE.md` is mounted read-only at `/opt/repos/CLAUDE.md` from `knowledge/claude-code-context.md` — this gives Claude Code context about the repos.
- The command has a 5-minute timeout and limits Claude to 5 agent turns.
- Use `/code -v <prompt>` for verbose output.
