# Backend build — progress checklist

> Written so a future session can pick up mid-build without needing the full
> prior conversation. Update this file whenever a checkbox changes.

## Status: **MVP backend complete + tracker (`/applications`) + source-agnostic jobs + tier-2 limits.**

## Done

- [x] **Project scaffold** — `pyproject.toml` (uv), `.env.example`,
      `.gitignore`, package `__init__.py`s under `app/` and `tests/`.
- [x] **Pydantic schemas** — `app/schemas/{evaluate,filter,user}.py`.
      Note: `EvaluationResult` uses `pass_` with `alias="pass"` because `pass`
      is a Python keyword; use `.model_dump(by_alias=True)` when serialising
      for storage/response.
- [x] **Config / auth / deps** — `app/config.py` (pydantic-settings),
      `app/auth.py` (JWKS-based JWT verification, in-mem cache, `PyJWKClient`),
      `app/deps.py` (typed `Annotated[..., Depends(...)]` aliases).
- [x] **LLM provider layer** — `app/llm/base.py`, `anthropic.py` (tool_use),
      `openai.py` (function calling), `prompts.py` (shared SYSTEM prompt +
      `EVALUATION_TOOL_SCHEMA`), `registry.py` (factory).
- [x] **Services + db client** — `app/services/{evaluator,cache,quota}.py`,
      `app/db/client.py`. Cache key = sha256 over ordered `(id, text)` pairs,
      so rename OR reorder invalidates. Quota increments **only** on cache miss
      + actual LLM call; cache hits and empty-filter cases cost zero quota.
- [x] **Routers + main** — `app/routers/{evaluate,filters,me}.py`, `app/main.py`
      (CORS allowlist, `/health`). `POST /evaluate` maps `QuotaExceeded` to
      HTTP 402 with the payload spec'd in CLAUDE.md §6.
- [x] **SQL migration** — `app/db/migrations/0001_init.sql`. Creates the four
      tables, enables RLS, self-only policies, `updated_at` trigger on filters,
      and an `auth.users → profiles` insert trigger so a profile exists the
      moment a user signs up.
- [x] **Tests** — `tests/test_evaluate.py`, `tests/test_quota.py`, a
      `FakeLLMProvider` and an in-memory `FakeDB` that implements the subset
      of the supabase-py builder used by the services. `conftest.py` seeds
      env vars so `get_settings()` can load in tests. Coverage: cache hit,
      cache miss, filter-edit invalidation, no-filters path, quota
      enforcement, counter upsert.
- [x] **Deploy / docs** — `Dockerfile` (python:3.12-slim + uv), `fly.toml`
      (fra, `/health` check, auto-stop), `README.md`.
- [x] **Rate limiting on `/evaluate`** — `app/services/rate_limit.py`
      (per-user in-process token bucket, env-configurable capacity +
      refill/min). Wired as a FastAPI dependency; returns 429 with
      `Retry-After: 1` when the bucket is empty. Tests in
      `tests/test_rate_limit.py`. Note: in-process → each Fly machine has
      its own buckets; the monthly quota is still the hard, shared ceiling.
- [x] **Atomic quota increment** — new migration
      `0002_atomic_quota.sql` defines `increment_usage(uuid, text)` as
      `SECURITY DEFINER` with `INSERT … ON CONFLICT DO UPDATE RETURNING`.
      `QuotaService.increment()` now calls the RPC instead of doing a
      read-then-write; `SupabaseDB.rpc(...)` passthrough added; `FakeDB`
      implements the RPC for tests. Closes the race described in the
      original known-trade-offs note.
- [x] **Langfuse observability** — both `AnthropicProvider.evaluate` and
      `OpenAIProvider.evaluate` decorated with `@observe(as_type="generation")`.
      Each call logs the full system prompt, user message, tool schema,
      raw tool-use response, token usage, and latency. Env vars
      `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` drive
      the SDK; empty keys disable it (warn on startup, no crash). `main.py`
      lifespan flushes the queue on shutdown so short-lived processes don't
      drop traces.
- [x] **Migration 0004 — jobs + tracker.** Renames `evaluations.linkedin_job_id`
      → `job_id`, adds `source` text column with backfill to `'linkedin'`, and
      replaces the unique constraint with `(user_id, source, job_id, filters_hash)`.
      Adds `applications` table (the tracker), `cv_tailorings_used` to
      `usage_counters`, `monthly_cv_tailoring_limit` to `profiles`, and bumps
      free-tier `monthly_eval_limit` default + existing free users to 200.
- [x] **Source-agnostic `JobInput`.** `app/schemas/evaluate.py` uses
      `validation_alias=AliasChoices("job_id", "linkedin_job_id")` so older
      extension builds keep working unchanged. The cache, evaluator, and
      provider metadata all key on `(source, job_id)` now.
- [x] **Tracker endpoints (`/applications`).** `app/routers/applications.py`
      + `app/services/applications.py` + `app/schemas/application.py` provide
      list / create-or-upsert / get-by-id / get-by-job / patch / delete. The
      create call is idempotent on `(user_id, source, external_id)` so the
      extension's "Track this job" button is fire-and-forget. Tests in
      `tests/test_applications.py` cover idempotency, cross-user isolation,
      partial updates, status enum validation.

## Not done (explicit non-goals for this pass)

- [ ] **`uv sync` + dep install.** Per user, scaffold only — deps not installed
      and no venv created yet. First real run: `uv sync && uv run pytest`.
- [ ] **Git init / first commit.** Per user, no `git init` yet.
- [ ] **Local `.env` with real secrets.** Only `.env.example` exists. The real
      Supabase + Anthropic values from `CLAUDE.md` were NOT written to disk.
      **Action for user: rotate the Anthropic key in `CLAUDE.md` — it was
      committed into that doc and should be considered leaked.**
- [ ] **SQL migrations applied** to the Supabase project. Only the files exist.
      Apply `0001_init.sql`, `0002_atomic_quota.sql`, `0003_filter_profiles.sql`,
      `0004_jobs_and_tracker.sql` in order via `supabase db push` or paste into
      the SQL editor.
- [ ] **Stripe / paid plan gating.** Out of scope for MVP per CLAUDE.md §9.
- [ ] **Integration tests** that hit real Anthropic / real Supabase. Unit
      tests only.

## First-run checklist for the user

1. `cd linkedin-job-filter-backend`
2. `cp .env.example .env` and fill in real values (Supabase project URL,
   secret key, JWKS URL, Anthropic key, extension origin).
3. `uv sync` (installs runtime + dev deps).
4. Apply `app/db/migrations/0001_init.sql` to the Supabase project.
5. `uv run pytest` — should pass with 0 network calls.
6. `uv run uvicorn app.main:app --reload` — hit `http://localhost:8000/health`.
7. Try `POST /evaluate` with a real Supabase access token to sanity-check
   end-to-end.

## Known trade-offs worth remembering

- `EvaluationCache.put` stores the full structured results but **not** the
  raw job description, per CLAUDE.md §10 (minimise retained personal data).
- The CORS allowlist falls back to `*` if `ALLOWED_ORIGINS` is empty — this
  is a dev convenience; tighten it in production by always setting the
  extension's `chrome-extension://<id>` origin.
- `_cached_provider` in `app/deps.py` keys by `provider_name`; changing
  `LLM_PROVIDER` at runtime won't re-pick up new API keys without a restart.
  Fine for our deploy model (Fly restart on `fly secrets set`).
- The rate limiter is in-process (per Fly machine). Horizontal scaling out
  would require a shared store (Redis) for consistent limits. The monthly
  quota stays correct regardless — it lives in Postgres.
- `increment_usage` is granted to `service_role` only (revoked from `anon`
  and `authenticated`). If you add a role, remember to revoke explicitly —
  otherwise an authenticated user could bump someone else's counter.
