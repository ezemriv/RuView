---
name: update-status
description: >
  Update PROJECT_STATUS.md after any major task — new features, fixes, Docker changes, ESP32 work, Telegram bot changes, or anything that moves the project forward.
  ALWAYS invoke this at the end of any significant work session.
  START by reading PROJECT_STATUS.md so you have full context before writing anything.
---

## FIRST ACTION (mandatory)
Read `PROJECT_STATUS.md` now before doing anything else. This gives you context on what was previously completed and what the current state is. Never update the file without reading it first.

You are a project journal updater for the RuView home security alarm project.

After any major task completion, read the current `PROJECT_STATUS.md` at the repo root and update it to reflect:
1. What was just completed (add to the "Completed" section with today's date)
2. The current state of the system (update "Current State")
3. What comes next (update "Next Steps")

## Rules
- ALWAYS read `PROJECT_STATUS.md` before editing it
- Keep entries concise — 1-3 lines per item max
- Dates in `YYYY-MM-DD` format
- Never remove old completed entries — append new ones
- The "Current State" section should be a single paragraph snapshot: what is running, where, and how
- "Next Steps" should be ordered by priority (most important first)
- If `PROJECT_STATUS.md` does not exist yet, create it using the template below

## Template (use only if file does not exist)

```markdown
# RuView Home Security — Project Status

## Current State
<!-- One paragraph: what is built, what is running, what hardware is connected -->

## Completed
<!-- Chronological log, newest first -->

## Next Steps
<!-- Ordered by priority -->

## Key Files & Commands
<!-- Quick reference so you don't have to re-explore -->
| What | Where / Command |
|------|----------------|
| Telegram alerter | `scripts/telegram_alert.py` |
| Docker entrypoint (sim) | `scripts/start.sh` |
| Docker entrypoint (esp32) | `scripts/start_esp32.sh` |
| Dockerfile | `Dockerfile` |
| Credentials | `.env` (gitignored) |
| Run container | `docker run -d --name ruview-alarm --restart unless-stopped --env-file .env -p 3000:3000 -p 3001:3001 -p 5005:5005/udp ruview-telegram` |
| Stop container | `docker stop ruview-alarm && docker rm ruview-alarm` |
| View logs | `docker logs ruview-alarm` |
| Rebuild image | `docker build -t ruview-telegram -f Dockerfile .` |

## Notes & Decisions
<!-- Architectural choices, gotchas, things to remember -->
```

After updating, print a brief summary of what you changed.
