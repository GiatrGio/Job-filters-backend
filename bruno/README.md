# Bruno collection — LinkedIn Job Filter API

Covers every endpoint of the backend: `/health`, `/me`, `/filters` CRUD, and
`/evaluate`.

## Import

1. Open Bruno.
2. **Collection → Open Collection** → pick this `bruno/` directory.
3. In the environment dropdown (top-right), select **Local**.

## Configure the JWT

Every endpoint except `/health` requires a Supabase user access token.

1. Sign in through the extension (or directly against Supabase).
2. Grab the token — easiest path: open the extension's options page,
   `Right-click → Inspect → Console`, run:
   ```js
   const { data } = await (await fetch(
     `${import.meta.env.VITE_SUPABASE_URL}/auth/v1/token?grant_type=password`,
     { method: "POST", headers: { apikey: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY, "Content-Type": "application/json" },
       body: JSON.stringify({ email: "you@example.com", password: "…" }) }
   )).json();
   copy(data.access_token);
   ```
   Or run `supabase.auth.getSession()` in the same console and copy
   `access_token` from the result.
3. Paste the token into **Environment → Local → `jwt`** in Bruno.

Access tokens expire in an hour by default — refresh as needed.

## Suggested flow

- `Health / Health Check` — no auth, sanity check the server is up.
- `Me / Get Me` — verifies the JWT works and shows current plan + usage.
- `Filters / Create Filter` — creates a filter; a post-response script
  saves the returned `id` into the `filterId` env var automatically.
- `Filters / List Filters`, `Update Filter`, `Delete Filter` — operate on
  the last-created filter.
- `Evaluate / Evaluate Job` — sends a job payload. First call hits the LLM;
  subsequent calls with the same `linkedin_job_id` (and unchanged filters)
  return `cached: true` from the server-side cache.
