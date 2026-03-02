# For Luka — Action Items & Setup Notes

> Things that require manual action or credentials that the autonomous agent cannot provide.

## Code-access:

- **REPUBLIC_REPO_URL** / **REDEFINE_REPO_URL**: Set to the git clone URLs of the Republic and Redefine repos. If empty, code context is skipped entirely.
- **REPOS_DIR**: Directory where repos are cloned (default `/opt/repos`, mapped via `./repos:/opt/repos` in docker-compose).
- **ANTHROPIC_API_KEY**: Required for the `/code` command. Claude CLI picks this up from the environment automatically. Set it in your `.env` file.
- **Git access in Docker**: The Dockerfile now installs `git`. If repos are private, you'll need to configure git credentials inside the container (e.g. via `.netrc` or SSH key mounted as a volume).
- **How it works**: When a support email arrives, an LLM extracts search terms. If the email needs code context (`needs_code: true`), the system greps the cloned repos and includes relevant file snippets in the support draft prompt. If repos aren't configured or no matches are found, the feature is silently skipped.
- Create a `repos/` directory in the project root (it's git-ignored by docker-compose bind mount).

## /code command (Claude Code CLI):

- **Dockerfile updated**: Now installs Node.js 20 and `@anthropic-ai/claude-code` globally. This adds ~200MB to the Docker image.
- **ANTHROPIC_API_KEY** must be set in the environment for the `/code` command to work.
- Claude CLI runs in `REPOS_DIR` (`/opt/repos` by default), so it has access to cloned repos.
- The command has a 5-minute timeout and limits Claude to 5 agent turns.
- Use `/code -v <prompt>` for verbose output (no concise-output instruction prepended).
