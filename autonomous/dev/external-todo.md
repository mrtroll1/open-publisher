# External TODOs

> Work that depends on external systems, APIs, or teams. Things the autonomous agent can stub but not complete.

## Goals & Tasks System (Plan 12)

- [x] Add `GOAL_MONITOR_INTERVAL` to `config/backend.env` (seconds, default 3600)
- [x] Add `GOAL_NOTIFICATION_INTERVAL` to `config/bot.env` (seconds, default 300)
- [x] Deploy and verify migration 007 applied (check DB for goals/tasks/notifications tables)
- [ ] Create initial goals via Telegram to verify end-to-end flow
- [ ] Teach identity intents (publisher vision, editorial direction) via /teach
- [ ] Monitor goal_monitor logs for first 48h — check trigger evaluation quality
- [ ] Tune GOAL_MONITOR_INTERVAL based on actual usage (more frequent if many trigger-based tasks)

## Contractor Operations Overhaul (Plan 13)

- [x] Create "stub" tab in the contractors Google Sheet with header: `id | name | aliases | role_code | telegram | secret_code`
- [x] Deploy migration 008 (editor_dm environment + contractors tool permissions)
- [ ] Bind editor DM chats to `editor_dm` environment via API
- [ ] Create editor users with role `editor` so Authorizer grants correct tools
- [ ] Test self-registration with improved matching threshold (0.6)
- [ ] Test type change flow end-to-end: samozanyaty → global
- [ ] Test stub claim flow: admin creates stub → author starts bot → matches → verifies → fills data
- [ ] Test NL contractor operations in admin DM

