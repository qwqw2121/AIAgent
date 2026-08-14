# AI News Agent - FastAPI + Next.js integration

This bundle connects the frontend to the existing `storage/news.db` through FastAPI.

## Backend

Copy `backend/` into the project root, next to `storage/`.

```bash
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Test:

- http://localhost:8000/api/health
- http://localhost:8000/api/dashboard/stats
- http://localhost:8000/api/news?limit=10
- http://localhost:8000/docs

## Frontend

Copy `frontend/lib/api.ts` into your existing Next.js project's `lib/api.ts`.

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Then:

```bash
npm install
npm run dev
```

## What is connected now

- Dashboard counts and category/source statistics
- News list and news detail
- Source statistics
- Events endpoint (automatically uses an events table if one exists; otherwise returns an explicit pending message)
- Daily/monthly report placeholder APIs
- RAG placeholder API

No fake news data is returned by the backend.
