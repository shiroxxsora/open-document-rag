# Open Document RAG

Production-quality RAG stack with multi-tenant auth, job queue, usage quotas, health probes, API tokens, and tests.

**Repository:** https://github.com/shiroxxsora/open-document-rag

## Run

1. Copy `.env.example` to `.env` and set `LLM_API_KEY`, `EMBEDDING_DIM`, and auth secrets.
2. Start the stack:

```bash
docker compose up -d --build
```

UI: http://localhost:3000  
Backend: http://localhost:8000  
API: `/api/v1/*`

## Existing database (Liquibase baseline)

If the database was created before Liquibase:

```bash
docker compose run --rm liquibase changelog-sync
docker compose run --rm liquibase update
python backend/scripts/migrate_single_tenant.py
```

## Tests

Backend unit tests (no Postgres):

```bash
cd backend
pytest -m "not integration" -v
```

Backend integration tests (Postgres + migrations):

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d postgres liquibase
TEST_POSTGRES_DSN=postgresql://postgres:postgres@localhost:5433/rag_test LLM_MOCK=1 AUTH_MODE=dev pytest -v
```

Frontend:

```bash
cd frontend
npm ci
npm test
```

E2E (stack running with `AUTH_MODE=dev`):

```bash
cd e2e
npm ci
npx playwright install chromium
npm test
```

Set `LLM_MOCK=1` in CI and local integration runs to avoid real LLM calls.

## Features

- Upload `.pdf`, `.docx`, `.txt` with per-user storage under `/data/docs/{user_id}/`
- Postgres job queue + worker with retries and DLQ
- OAuth (Google/GitHub) or `AUTH_MODE=dev` login with httpOnly JWT cookie
- Per-user LLM settings (BYOK), usage quotas, health live/ready/deep
- API applications/tokens with scopes
- Multi-turn chat, SSE `/api/v1/chat/stream`, webhooks with HMAC
- `DELETE /me`, `GET /me/export`

## Useful API (`/api/v1`)

- `GET /health/live`, `GET /health/ready` (public)
- `GET /health`, `GET /health/deep` (auth)
- `POST /auth/dev/login` (dev mode)
- `GET /me`, `PUT /me/settings`, `POST /me/settings/test-llm`
- `GET /documents`, `POST /documents/upload`, `DELETE /documents/{id}`
- `POST /chat`, `POST /chat/stream`
- `GET /usage`, `GET /usage/history`
- Developer: `/developer/applications`, tokens with Bearer `srbs_live_...`
