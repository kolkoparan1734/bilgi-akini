# Running Bilgi Akını on Replit

This project keeps its original Flask / Flask-SocketIO backend and plain
HTML, CSS, and JavaScript frontend. Flask serves both on port 5000.

## Run

Click **Run** to start the **Start application** workflow:

```sh
cd backend && env -u DATABASE_URL python -m gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
```

Dependencies are pinned in `backend/requirements.txt` and installed in the
Replit Python environment. No frontend build step is required.

Use a single worker: multiplayer rooms live in process memory. Restarting
the server clears active multiplayer rooms.

## Data and configuration

- No additional secrets or external services are required for local preview.
- The existing default SQLite database is `backend/bilgi_akini.db`. Tables
  and sample questions are initialized automatically when the server starts.
- The database file is ignored by Git. Do not delete it if player progress
  needs to be preserved.
- Keep `frontend/config.js`'s server address empty so API and Socket.IO
  connections use the same origin as the preview.
- The preview workflow unsets the automatically supplied `DATABASE_URL`
  for its process only, preserving the imported project's default SQLite
  storage. It does not delete or change workspace environment variables.
  To intentionally use an external database, remove `env -u DATABASE_URL`
  and install the appropriate database driver.
- For publishing, choose durable database storage first; do not assume the
  local SQLite file persists on a published instance.

## Quick checks

- `/` serves the game.
- `/api/health` returns `{"status":"ok"}`.
- `/api/eras` and `/api/countries/all` return the seeded game content.
