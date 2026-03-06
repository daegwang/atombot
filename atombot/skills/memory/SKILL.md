---
name: memory
description: Persistent memory policy (durable, user-approved facts only).
always: true
---

Use this skill when the user asks to remember, forget, or update saved memory.

### Rules
- Save only durable facts with clear future value (preferences, profile, recurring constraints).
- Do not save secrets, tokens, passwords, private keys, or one-time/ephemeral chat details.
- Prefer explicit user consent before adding new memory when intent is ambiguous.
- Keep entries short, factual, and conflict-free; replace outdated facts instead of duplicating.

### Update flow
1. Read current memory (`read_file` on `memory/MEMORY.md`) when you need context.
2. Produce a clean merged version.
3. Persist with `update_memory` (full-file replace).
