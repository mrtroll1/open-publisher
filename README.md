# open-publisher

An AI agent with a Telegram interface that runs the back office of
republicmag.io. Live since February 2026; automates my own job.

## What it does
- Monthly accounting
- Document generation and signing, for and with contractors
- Tech support
- Lookups across several databases
- Interactive knowledge base

## How it works
- **Orchestration** — a router classifies each message: clear intent goes straight
  to a tool, everything else enters a ReAct loop (function calling → execute →
  feed results back, up to 10 steps). Tools are resolved per request from a
  permission table keyed by role and chat, so two people asking the same thing
  get different capabilities. Relevant knowledge is retrieved into the system
  prompt; every step is logged to Postgres.
- **Models** — Gemini in two tiers (fast for classification and extraction,
  smart for the loop); the Claude Code CLI runs as a subprocess for code tasks.
- **Approval gates** — nothing leaves the system unseen. Support replies and
  editorial forwards are drafted and held as `PENDING` decisions until I approve,
  edit, or skip them in Telegram; the verdict is written back with who decided.
  Invoices and contracts are generated as drafts and only dispatched on an
  explicit send command. Autonomous goal plans halt at checkpoint tasks and wait.
- Python · Docker · GitLab CI · tests

## Where it goes
Creative initiative, and ownership of its own implementation and use.

## Vision
Backoffice of a small media requires little to none human presense
