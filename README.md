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
| DELETE | `/me`              | JWT  | Delete the caller's own account and all its data. |
| POST   | `/generate-cover-letter` | JWT | Generate editable cover-letter prose.      |
| POST   | `/cover-letter/pdf` | JWT | Render edited text to an in-memory PDF.         |
| POST   | `/billing/checkout-session` | JWT | Create a Stripe Checkout session for Pro. |
| POST   | `/billing/portal-session` | JWT | Create a Stripe Customer Portal session. |
| POST   | `/billing/webhook` | Stripe signature | Receive Stripe subscription webhooks. |
| POST   | `/auth/web-handoffs` | JWT | Create a 60-second extension → website login URL. |
| POST   | `/auth/web-handoffs/exchange` | One-time ticket; optional JWT | Consume the ticket and establish/reuse the website user. |

The JWT is a Supabase user access token, passed as `Authorization: Bearer …`.
It is verified against the JWKS at `SUPABASE_JWKS_URL`.

## Database

Apply every numbered migration in `app/db/migrations/` in order. Two options:

- **Supabase CLI:** `supabase db push` (after linking the project).
- **Dashboard:** open SQL editor and run each unapplied numbered migration in order.

The migrations are cumulative and are the source of truth for profiles,
filters, evaluations, tracker data, quotas, billing, CV/cover-letter data, and
the ephemeral `auth_handoffs` table.

### Account deletion depends on the schema

Every user-owned table declares `references auth.users on delete cascade`, so
`DELETE /me` erases a user's data by deleting one row — the auth user. **A new
user-owned table must declare that cascade**, or its rows will outlive the
account that owns them.

`llm_calls` is the deliberate exception: migration 0018 makes it
`on delete set null` so LLM cost history survives a departing user, anonymised.

`WEBSITE_URL` must be the website origin used in handoff URLs (`http://localhost:3000`
locally, `https://www.canvasjob.com` in production). `AUTH_HANDOFF_TTL_SECONDS`
defaults to 60 and is intentionally capped at five minutes.

## LLM provider

Selected by `LLM_PROVIDER` (`anthropic` or `openai`). Models are configurable
via `ANTHROPIC_MODEL` and `OPENAI_MODEL`. Both providers enforce structured
output via tool use / function calling against the same JSON Schema defined
in `app/llm/prompts.py`.

LLM call costs in the local admin panel are estimates. The backend exposes
`GET /admin/llm-pricing`, backed by env overrides or the small built-in
catalog for the default models, so the website can cache rates client-side and
estimate old rows that were logged without a persisted cost.

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
