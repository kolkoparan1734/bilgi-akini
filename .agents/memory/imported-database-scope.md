---
name: Imported database scope
description: Why the imported game's preview should retain SQLite
---

Keep the imported game's SQLite storage for preview setup; do not adopt a
different database merely because the environment supplies DATABASE_URL.

**Why:** The user requested running the import, not a database migration.
The automatically supplied URL selected a driver the import did not include.

**How to apply:** Preserve the SQLite preview workflow unless the user asks
to change storage. Treat durable published storage as a separate decision.
