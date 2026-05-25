# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project overview

智档 (ZhiDang) is a Customer Success automation platform. CSM meeting transcripts/images → LLM extracts structured facts → compares against existing Jiandaoyun (简道云) records → generates operation cards (create/update/skip) → human review → writes back to Jiandaoyun.

## Commands

### Docker (full stack)
```bash
docker compose up --build          # postgres + backend + nginx frontend
```

### Local development
```bash
# Backend
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev    # Vite dev server on :5173, proxies /api to :8000

# Frontend production build
cd frontend && npm run build                 # outputs to frontend/dist/
```

### Database migrations
```bash
alembic revision --autogenerate -m "description"   # generate migration from model changes
alembic upgrade head                                # apply all pending migrations
```

### Local dev shortcuts
- Use `DATABASE_URL=sqlite:///./zhidang.db` to skip PostgreSQL for quick local dev (some features like GIN indexes only work on PostgreSQL).
- Frontend Vite proxy forwards `/api` to `http://127.0.0.1:8000` in dev mode.

## Architecture

### Core data flow
```
Upload → Agent-A extraction (facts[]) → Agent-B comparison (operation_cards) → Review → Execute → Jiandaoyun
```
Side paths: Chat (NL query/modify), Followup records (meeting → structured record → Jiandaoyun).

### Key files (read first when debugging)

| File | Role |
|------|------|
| `backend/app/main.py` | All 51 API routes, auth, business logic — **2400+ line monolith**, be careful |
| `backend/app/services/tool_registry.py` | Agent tool definitions, FIELD_ALIASES, field matching/safety rules |
| `backend/app/services/agent_runner.py` | Agent tool-calling loop (multi-turn LLM + tool interaction) |
| `backend/app/services/prompts.py` | All LLM system prompts (extraction, comparison, followup) |
| `backend/app/services/jiandaoyun_client.py` | Jiandaoyun HTTP client with v5→v2 API fallback |
| `backend/app/services/operation_executor.py` | Executes approved operation cards → writes to Jiandaoyun |
| `backend/app/services/field_safety.py` | Field-level security policies (blocked fields, value constraints) |
| `backend/app/config/jiandaoyun_field_mapping.json` | Form→field→widget mapping + safety config |
| `backend/app/models.py` | 7 SQLAlchemy models |
| `frontend/src/pages/TranscriptsPage.vue` | Upload + extraction trigger UI |
| `frontend/src/pages/ReviewPage.vue` | Operation card review UI |

### Critical invariants

1. **Jiandaoyun writes must go through `operation_executor` + `JiandaoyunWriter`** — never bypass `field_safety`.
2. **Field mapping changes require 3-file sync**: `jiandaoyun_field_mapping.json`, `tool_registry.py` (FIELD_ALIASES), and potentially `prompts.py`.
3. **API keys/secrets must use `crypto_utils` AES-256-GCM encryption** — never store plaintext in DB.
4. **New Agent tools must be registered in `tool_registry.get_tools()`** — don't define orphan tools.
5. **New business logic goes in `services/`**, not in `main.py` — the monolith is already too large.
6. **Jiandaoyun client has v5→v2 fallback** — both paths must work when modifying `jiandaoyun_client.py`.

### Auth patterns
- JWT for normal auth, SSO via HMAC-SHA256 tokens
- Nonce replay prevention uses DB table `sso_nonce_used`
- API keys encrypted with AES-256-GCM, key derived from `ZHIDANG_SECRET_KEY` or `JWT_SECRET` env var — changing JWT_SECRET invalidates all stored encrypted config

### Known pitfalls
- **Two `main.py` files exist**: root `main.py` is a standalone demo (in-memory state, no DB); `backend/app/main.py` is the real app. Don't confuse them.
- **Operation cards live in memory** (`OPERATION_CARD_STORE` dict) — restart loses them. By design for short review cycles.
- **DeepSeek R1 reasoning models break multi-turn tool calling** — use `deepseek-chat` or `v4-flash` instead.
- **`anthropic` import in main.py has silent fallback** — if SDK fails to import, Agent pipeline degrades gracefully.
- **Customer index cache** (`CUSTOMER_INDEX_CACHE`) has TTL — newly added Jiandaoyun customers may not appear for 5-10 minutes.
- **SSO nonce table grows unbounded** — needs periodic cleanup in production.
- **Frontend timeout config** is stored in localStorage (default 30s) — Agent tasks exceeding this will show as timeout errors on the frontend.
- **Chinese punctuation in prompts must use full-width** (全角) — half-width marks can confuse model parsing.
- **DB operations must use SQLAlchemy sessions** — no raw SQL outside of migration/init scripts.

### Frontend deploy (Docker bind-mount)
The `frontend/dist/` is bind-mounted into the nginx container. When deploying:
- **Never** `rm -rf` + `mkdir` the `dist/` directory — this breaks the bind mount, container sees stale inode, nginx returns 500.
- Only overwrite files, or use `docker cp` + `nginx -s reload`, or restart the frontend container after directory rebuild.
