---
name: cron
description: Schedule, list, and remove reminders with correct one-time vs recurring behavior.
always: true
---

Use this skill when handling reminders and scheduling requests.

### Rules
- Use cron_job for scheduling.
- One-time reminders (“in/after”, “at <time>”) → every_s=0; do not infer recurrence from duration (e.g., “after 1 minute” = one-time).
- Recurring reminders → every_s>0 only if the user explicitly says “every”, “repeat”, or “recurring”.
- When adding a job, pass next_at as an ISO datetime; keep confirmations concise and do not show cron IDs unless asked.

### Scheduled task behavior
- Treat the incoming text as a message when user requested.
- Do not check/list/manage reminders unless explicitly asked.
- Respond with the reminder content directly and concisely.
