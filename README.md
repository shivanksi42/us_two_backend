# us-two backend

Standalone FastAPI backend. Its password hashing and JWT approach are adapted from Project1, but it has its own models/database and does not depend on Project1.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Local development defaults to SQLite (`us_two.db`). For deployment, set `DATABASE_URL` to your Supabase Postgres connection string and deploy this backend to Render/Railway/Fly.io. Set `FRONTEND_ORIGIN` to the Vercel site URL.
