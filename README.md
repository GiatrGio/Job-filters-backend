# linkedin-job-filter-backend

FastAPI backend for the LinkedIn Job Filter Chrome extension. Evaluates job
postings against user-defined free-text filters using a pluggable LLM
provider (Anthropic or OpenAI).

See the top-level `CLAUDE.md` for the full product/architecture spec.

## Quick start

```bash
cp .env.example .env           # fill in Supabase + Anthropic keys
uv sync                        # install deps (including dev group)
uv run uvicorn app.main:app --reload
```

The API is then served at `http://localhost:8000`.

## Endpoints

| Method | Path               | Auth | Description                                     |
|--------|--------------------|------|-------------------------------------------------|
| GET    | `/health`          | —    | Liveness check.                                 |
| POST   | `/evaluate`        | JWT  | Evaluate a job against the user's filters.      |
| GET    | `/filters`         | JWT  | List the caller's filters.                      |
| POST   | `/filters`         | JWT  | Create a filter.                                |
| PATCH  | `/filters/{id}`    | JWT  | Update a filter (text / position / enabled).    |
| DELETE | `/filters/{id}`    | JWT  | Delete a filter.                                |
| GET    | `/me`              | JWT  | Current plan + monthly usage.                   |

The JWT is a Supabase user access token, passed as `Authorization: Bearer …`.
It is verified against the JWKS at `SUPABASE_JWKS_URL`.

## Database

Apply the migration in `app/db/migrations/0001_init.sql` once. Two options:

- **Supabase CLI:** `supabase db push` (after linking the project).
- **Dashboard:** open SQL editor, paste `0001_init.sql`, run.

The migration sets up `profiles`, `filters`, `evaluations`, `usage_counters`,
RLS policies, an updated_at trigger on filters, and an auth.users → profiles
trigger so a profile row is auto-created on signup.

## LLM provider

Selected by `LLM_PROVIDER` (`anthropic` or `openai`). Models are configurable
via `ANTHROPIC_MODEL` and `OPENAI_MODEL`. Both providers enforce structured
output via tool use / function calling against the same JSON Schema defined
in `app/llm/prompts.py`.

To add a provider: implement `LLMProvider` in `app/llm/<name>.py` and register
it in `app/llm/registry.py`. Nothing else should change.

## Tests

```bash
uv run pytest
```

Tests use a deterministic `FakeLLMProvider` and an in-memory `FakeDB` — no
network calls, no API keys required beyond the placeholder env in
`tests/conftest.py`.

## Deployment (Fly.io)

```bash
fly launch --no-deploy        # first time only
fly secrets set SUPABASE_URL=… SUPABASE_SECRET_KEY=… SUPABASE_JWKS_URL=… \
                ANTHROPIC_API_KEY=… ALLOWED_ORIGINS=chrome-extension://<id>
fly deploy
```

Fly routes to `$PORT` (8080 by default). The `/health` endpoint is wired to
the Fly health check in `fly.toml`. Change `primary_region` if your Supabase
project is not in `fra`.
