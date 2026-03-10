# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Goals & Tasks System (Plan 12)

- [ ] Add `GOAL_MONITOR_INTERVAL` to `config/backend.env` (seconds, default 3600)
- [ ] Add `GOAL_NOTIFICATION_INTERVAL` to `config/bot.env` (seconds, default 300)
- [ ] Deploy and verify migration 007 applied (check DB for goals/tasks/notifications tables)
- [ ] Create initial goals via Telegram to verify end-to-end flow
- [ ] Teach identity intents (publisher vision, editorial direction) via /teach
- [ ] Monitor goal_monitor logs for first 48h — check trigger evaluation quality
- [ ] Tune GOAL_MONITOR_INTERVAL based on actual usage (more frequent if many trigger-based tasks)

