# Collabio M1 — Foundation + Supply Side Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A brand can sign in, find creators by voice, and compare their packages side by side; a creator can sign in, dictate a package by voice, adjust it with clicks, and publish it so it becomes searchable.

**Architecture:** `backend/` is a FastAPI service (uv, Python 3.12) with a pure-logic `core/`, Pydantic `schemas/`, thin `adapters/` (asyncpg, Gemini, ElevenLabs), and feature `modules/`. It owns all writes and all secrets. Local Supabase (CLI + Docker) provides Postgres + pgvector + Auth with ES256 signing keys. `frontend/` is a Next.js 16 app copied from the root scaffold; it authenticates with `@supabase/ssr`, calls the backend through an OpenAPI-generated typed client, and hosts the Voice Dock (ElevenLabs Scribe realtime → backend intent router).

**Tech Stack:** Python 3.12 · uv · FastAPI · Pydantic v2 · pydantic-settings · asyncpg + pgvector · google-genai · elevenlabs · PyJWT[crypto] · tenacity · pytest/pytest-asyncio · Supabase CLI 2.109 · Next.js 16.3.6 · React 19.3 · Tailwind v4 · shadcn (base-nova) · @supabase/ssr · TanStack Query · openapi-fetch/openapi-typescript · @elevenlabs/react · GSAP + @gsap/react · Vitest · Playwright

**Spec:** `docs/superpowers/specs/2026-10-09-collabio-design.md` (M1 rows of §2; §4, §5.1, §6, §10 "Discover" and "Packages", §13, §14)

## Global Constraints

- Branch `collabio-v1`. Every commit message ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (pass as a second `-m`).
- Python is always run through `uv` (`requires-python = ">=3.12,<3.14"`). The system `python` is 3.6.8 — never use it.
- Next.js 16: before writing any Next.js code, read the relevant guide in `node_modules/next/dist/docs/` (per `AGENTS.md`). Use `proxy.ts` (not `middleware.ts`); `params`/`searchParams`/`cookies()` are async.
- The root-level Next.js scaffold is copied into `frontend/`, never moved or edited.
- Money is integer cents, USD only. Display rule: `$1,000` (no decimals when cents are zero), `$999.50` otherwise.
- Gemini: embeddings `gemini-embedding-2`, `output_dimensionality=768`, **each text wrapped in its own `types.Content`** (a bare list of strings returns ONE aggregated embedding). Document format `title: {title} | text: {text}`; query format `task: search result | query: {query}`. Text model `gemini-3.5-flash-lite` (switched from 3.8-flash: free-tier quota) with `thinking_level="low"`, structured output via `response_schema=<Pydantic model>`.
- ElevenLabs STT: model `scribe_v2_realtime`, browser connects with a backend-minted single-use token (`client.tokens.single_use.create(token_type="realtime_scribe")`).
- Supabase keys: frontend uses `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_API_URL`; backend uses `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_DB_URL`, `SUPABASE_JWKS_URL`, `GEMINI_API_KEY`, `GEMINI_TEXT_MODEL`, `GEMINI_EMBED_MODEL`, `ELEVENLABS_API_KEY`, `DEMO_BRAND_EMAIL`, `DEMO_PASSWORD`, `DEMO_HELPER_PHONE`, `DEMO_HELPER_EMAIL`. Secret keys never get a `NEXT_PUBLIC_` prefix.
- A creator's floor price, email, and phone never appear in any response a brand can receive. Tests assert their absence.
- Voice never executes an irreversible action directly (M1 has none, but intents are designed so `publish` is a click).
- Motion only signals a state change; every GSAP animation checks `prefers-reduced-motion`.
- Ports: backend `8000`, frontend `3000`, Supabase API `54321`, Supabase DB `54322`.
- Niche vocabulary (exact keys): `consumer_tech`, `beauty`, `fitness`, `food`, `gaming`, `b2b_saas`. Content types: `short_video`, `long_video`, `story`, `live`. Volume basis: `per_week`, `per_contract`. Preferred channel: `email_first`, `phone_ok`, `email_only`.

## Review Focus

1. **Spoken money phrases** ("two grand", "1.5k", "twelve hundred", "under two thousand dollars") must land as correct integer cents in filters and package drafts → Task 9 adds a `live` eval test with these phrases plus a schema guard that rejects non-integer or negative cents.
2. **Search that matches nothing** (filters too narrow) must show an empty state naming the active chips with one-tap removal, never a blank grid → Task 15 test `shows empty state with removable chips`.
3. **Microphone denied or Scribe token failure** must switch the Dock to a text input with a short reason, and typed commands must still work → Task 14 reducer test `error falls back to typing`.
4. **Holding Space while typing in an input** must type a space and never start listening → Task 14 test `space inside input does not start capture`.
5. **Expired session mid-use** (API returns 401) must refresh the Supabase session once and retry, then redirect to `/sign-in?next=<path>` → Task 11 test `401 refreshes once then redirects`.

---

## File Structure

```
.claude/skills/gsap-*              reinstalled GSAP skills (Task 1)
backend/
  pyproject.toml, uv.lock, .gitignore, .env.example, README.md
  app/main.py                      create_app(), lifespan opens/closes DB pool
  app/config.py                    Settings (pydantic-settings)
  app/api/deps.py                  current_user, require_role, get_db, get_gemini, get_elevenlabs
  app/api/routers/{health,me,discovery,creators,packages,voice}.py
  app/core/money.py                format_cents
  app/core/pricing.py              per_video_cents, extra_video_addon
  app/core/package_text.py         package_one_liner, creator_embedding_document, text_hash
  app/core/package_rules.py        validate_package, missing_fields, merge_package_draft
  app/core/refs.py                 resolve_creator_refs
  app/schemas/{common,me,packages,discovery,voice}.py
  app/adapters/db.py               Database (asyncpg pool + pgvector codec)
  app/adapters/gemini.py           GeminiPort, GeminiClient, format_document, format_query
  app/adapters/elevenlabs.py       ElevenLabsPort, ElevenLabsClient.mint_scribe_token
  app/modules/me/service.py        get_me, onboard
  app/modules/discovery/{repo,service}.py
  app/modules/packages/{repo,service}.py
  app/modules/voice/{prompts,service}.py
  scripts/{export_openapi,build_embedding_cache,seed}.py
  supabase/config.toml, supabase/signing_keys.json (gitignored)
  supabase/migrations/<ts>_m1_core.sql
  supabase/seed/{creators.json,embeddings.json}
  tests/conftest.py, tests/fakes.py, tests/core/*, tests/api/*, tests/db/*, tests/live/*
frontend/                          copy of root scaffold + the following
  .gitignore, .env.example, components.json (+ @elevenlabs registry)
  proxy.ts
  app/(auth)/{sign-in,sign-up,onboarding}/page.tsx
  app/brand/{layout.tsx,discover/page.tsx,discover/review/page.tsx}
  app/creator/{layout.tsx,packages/page.tsx}
  components/shell/app-shell.tsx
  components/voice/{voice-dock.tsx,heard-chip.tsx,voice-screen.tsx}
  components/deal/{package-strip.tsx,creator-card.tsx,filter-chips.tsx,selection-tray.tsx,compare-table.tsx,package-draft-card.tsx}
  lib/api/{openapi.json,schema.d.ts,client.ts}
  lib/supabase/{browser.ts,server.ts,proxy.ts}
  lib/auth/routing.ts
  lib/money.ts
  lib/voice/{dock-machine.ts,use-command-capture.ts}
  lib/discover/state.ts
  tests/unit/*.test.ts(x), tests/e2e/m1.spec.ts
  vitest.config.ts, playwright.config.ts
```

---

### Task 1: Reinstall the GSAP skills

**Files:**
- Restore: `.claude/skills/gsap-*` (8 entries) and their canonical copies under `.agents/skills/`

**Interfaces:**
- Produces: readable skills `gsap-core`, `gsap-react`, `gsap-timeline`, `gsap-plugins`, `gsap-scrolltrigger`, `gsap-performance`, `gsap-utils`, `gsap-frameworks` for later frontend tasks.

- [ ] **Step 1: Confirm the breakage**

Run: `ls .claude/skills/gsap-react/SKILL.md`
Expected: `No such file or directory` (the junction points at the missing `.agents/skills/gsap-react`).

- [ ] **Step 2: Read the installer's options**

Run: `npx skills add --help`
Expected: usage text listing the agent/target flags. Pick the flag that installs for Claude Code at project scope.

- [ ] **Step 3: Remove the dangling junctions and reinstall**

Remove the eight `.claude/skills/gsap-*` junctions with cmd `rmdir` (it deletes the link only), then run `npx skills add greensock/gsap-skills` with the Claude Code project-scope flag from Step 2.

- [ ] **Step 4: Verify every skill is readable**

Run: `for s in core frameworks performance plugins react scrolltrigger timeline utils; do head -3 .claude/skills/gsap-$s/SKILL.md; done`
Expected: 8 YAML front-matter headers, no errors. `skills-lock.json` still lists the same 8 skills.

No commit: these are tooling files outside the product (`.claude/`, `.agents/`, `skills-lock.json` stay untracked unless the user asks).

---

### Task 2: Backend skeleton

**Files:**
- Create: `backend/pyproject.toml`, `backend/.gitignore`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/app/api/routers/health.py`, `backend/tests/conftest.py`, `backend/tests/api/test_health.py`

**Interfaces:**
- Produces: `create_app() -> FastAPI`; `Settings` with fields `supabase_url`, `supabase_secret_key`, `supabase_db_url`, `supabase_jwks_url`, `gemini_api_key`, `gemini_text_model="gemini-3.5-flash-lite"` (switched from 3.8-flash: free-tier quota), `gemini_embed_model="gemini-embedding-2"`, `elevenlabs_api_key`, `frontend_origin="http://localhost:3000"`, `demo_brand_email`, `demo_password`, `demo_helper_phone`, `demo_helper_email`; `get_settings() -> Settings` (lru_cached). Test fixture `client` (httpx `AsyncClient` over `ASGITransport`).

- [ ] **Step 1: Initialise the project**

Run (in `backend/`): `uv init --app --python 3.12 --name collabio-backend` then `uv add fastapi "uvicorn[standard]" pydantic pydantic-settings asyncpg pgvector google-genai elevenlabs "pyjwt[crypto]" httpx tenacity` and `uv add --dev pytest pytest-asyncio respx ruff`.
Expected: `uv.lock` created; `uv run python --version` prints 3.12.x.

Configure in `pyproject.toml`: `[tool.pytest.ini_options] asyncio_mode = "auto"`, `markers = ["db: needs local Supabase", "live: calls real Gemini/ElevenLabs"]`, `addopts = "-m 'not live'"`; ruff line length 100. `.gitignore`: `.venv/`, `__pycache__/`, `.env`, `supabase/signing_keys.json`, `supabase/.temp/`, `.pytest_cache/`, `.ruff_cache/`.

- [ ] **Step 2: Write the failing test**

```python
# tests/api/test_health.py
async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 3: Run it to see it fail**

Run: `uv run pytest tests/api/test_health.py -v`
Expected: FAIL (import error: `app.main` has no `create_app`).

- [ ] **Step 4: Implement `create_app()` and `Settings`**

All routers mount under `/api/v1`. CORS allows `settings.frontend_origin` with credentials and the `Authorization` header. `.env.example` lists every variable in Global Constraints with local defaults (`SUPABASE_URL=http://127.0.0.1:54321`, `SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`, `SUPABASE_JWKS_URL=http://127.0.0.1:54321/auth/v1/.well-known/jwks.json`).

- [ ] **Step 5: Run the test and lint**

Run: `uv run pytest -v && uv run ruff check .`
Expected: 1 passed; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add backend
git commit -m "feat(backend): FastAPI skeleton with settings and health check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Local Supabase, M1 schema, and RLS

**REQUIRED SKILLS:** `supabase:supabase`, `supabase:supabase-postgres-best-practices`.

**Files:**
- Create: `backend/supabase/config.toml` (via `supabase init`), `backend/supabase/signing_keys.json` (gitignored), `backend/supabase/migrations/<timestamp>_m1_core.sql` (via `supabase migration new m1_core`), `backend/app/adapters/db.py`, `backend/tests/db/conftest.py`, `backend/tests/db/test_rls.py`, `backend/tests/db/test_match_creators.py`

**Interfaces:**
- Produces tables (spec §6.1, M1 subset): `profiles`, `brands`, `products`, `creators`, `packages`, `package_floors`; enum types `user_role('brand','creator')`, `content_type`, `volume_basis`, `preferred_channel`, `package_status('draft','published')`; SQL function `match_creators(query_embedding vector(768) default null, max_price_cents int default null, content_types text[] default null, niches text[] default null, region text default null, min_followers int default null, match_limit int default 24) returns table(creator_id uuid, distance double precision)`.
- Produces `Database` with `async connect(dsn)`, `async close()`, `acquire()` and `transaction()` async context managers yielding an `asyncpg.Connection` with the pgvector codec registered.
- Produces test fixtures `db` (a connected `Database` on the local DSN), `db_conn` (a connection inside a transaction rolled back after each test; both skip with reason "local Supabase not running" when the DSN is unreachable) and `as_user(conn, user_id)` (runs `set local role authenticated` + `set local request.jwt.claims = '{"sub": "<id>", "role": "authenticated"}'`).

- [ ] **Step 1: Start Docker and the local stack with ES256 signing keys**

Prerequisite: Docker Desktop running (`docker info` prints a server version; the current install panics on `docker info`, so start/upgrade Docker Desktop first).
Run (in `backend/`): `supabase init`, then `supabase gen signing-key --algorithm ES256 > supabase/signing_keys.json`, set `signing_keys_path = "./signing_keys.json"` in the `[auth]` section of `supabase/config.toml` (the generated file contains it as a commented line), then `supabase start`.
Expected: `curl -s http://127.0.0.1:54321/auth/v1/.well-known/jwks.json` returns a key with `"kty":"EC"`. `supabase status -o env` prints the publishable and secret keys — copy them into `backend/.env`.

- [ ] **Step 2: Write the failing RLS and search tests**

```python
# tests/db/test_rls.py   (all marked @pytest.mark.db; seed rows inserted inside the test transaction)
async def test_brand_reads_published_packages_only(db_conn, as_user, factory): ...
    # brand sees creator X's published package, not X's draft
async def test_brand_cannot_read_floors(db_conn, as_user, factory): ...
    # select from package_floors as brand -> 0 rows
async def test_creator_reads_only_own_floor(db_conn, as_user, factory): ...
async def test_creators_table_is_owner_only(db_conn, as_user, factory): ...
    # brand selecting creators -> 0 rows (contact fields stay private); creator sees own row
async def test_profiles_self_only(db_conn, as_user, factory): ...
async def test_anon_has_no_access(db_conn): ...
    # set local role anon; select from packages -> permission denied or 0 rows

# tests/db/test_match_creators.py
async def test_filters_by_max_price_and_content_type(db_conn, factory): ...
    # creator A: short_video $1,000; creator B: long_video $3,000
    # match_creators(null, 200000, '{short_video}') -> [A]
async def test_orders_by_distance_when_embedding_given(db_conn, factory): ...
    # query = A's embedding -> A first, distance < 1e-6
async def test_ignores_draft_packages(db_conn, factory): ...
async def test_null_embedding_orders_by_followers_desc(db_conn, factory): ...
```

`factory` (in `tests/db/conftest.py`) inserts `auth.users` rows plus profiles/creators/packages and returns their ids; embeddings are deterministic unit vectors.

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/db -v`
Expected: FAIL (`relation "packages" does not exist`).

- [ ] **Step 4: Write the migration**

Column lists follow spec §6.1 exactly for the six M1 tables. Additionally:
- `create extension if not exists vector with schema extensions;` and reference the type as `extensions.vector(768)`.
- `creators.embedding extensions.vector(768)`, `creators.embedding_text_hash text`, HNSW index `using hnsw (embedding extensions.vector_cosine_ops)`.
- `packages.addons jsonb not null default '[]'` (items `{name, price_cents, unit}` where `unit ∈ {'video','item'}`), `packages.extras jsonb not null default '[]'`; check constraints `base_price_cents > 0`, `volume_count >= 1`, `lead_time_days >= 0`.
- Enable RLS on all six tables. Policies (all `to authenticated`, ownership via `(select auth.uid())`): `profiles` select self; `brands`/`products` select own; `creators` select own row only; `packages` select where `status = 'published'` or owned; `package_floors` select owned. No insert/update/delete policies (writes go through the backend's privileged connection).
- `revoke all on <each table> from anon;` `grant select on <each table> to authenticated;`
- `match_creators` is `language sql stable security invoker`: hard filters use `exists (published package where (max_price_cents is null or base_price_cents <= max_price_cents) and (content_types is null or content_type::text = any(content_types)))`, `niches is null or creators.niches && niches`, region and followers filters; order by `embedding <=> query_embedding` when given, else `followers desc`; `limit match_limit`.

Apply with `supabase db reset`. Then run `supabase db advisors` and fix every security finding.

- [ ] **Step 5: Implement `Database` in `app/adapters/db.py`**

Register the codec with `pgvector.asyncpg.register_vector` in the pool's `init` callback; set `search_path` to include `extensions` there too.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/db -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add backend/supabase/config.toml backend/supabase/migrations backend/app/adapters/db.py backend/tests/db
git commit -m "feat(db): M1 schema, RLS policies, and match_creators search" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Pure core — money, pricing, package text, package rules

**Files:**
- Create: `backend/app/schemas/packages.py`, `backend/app/core/money.py`, `backend/app/core/pricing.py`, `backend/app/core/package_text.py`, `backend/app/core/package_rules.py`
- Test: `backend/tests/core/test_money.py`, `test_pricing.py`, `test_package_text.py`, `test_package_rules.py`

**Interfaces:**
- Produces schemas: `Addon(name: str, price_cents: int, unit: Literal["video","item"])`; `PackageTerms` (all package columns from spec §6.1 except ids/status/timestamps); `PackageDraft` (same fields, all optional, default `None`/empty lists); `RuleViolation(field: str, message: str)`; type aliases `Niche`, `ContentType`, `VolumeBasis`, `PreferredChannel` as `Literal`s with the exact vocabularies from Global Constraints.
- Produces functions:
  - `format_cents(cents: int) -> str`
  - `extra_video_addon(pkg: PackageTerms) -> Addon | None` (first addon with `unit == "video"`)
  - `per_video_cents(pkg: PackageTerms) -> int` (`round(base_price_cents / volume_count)`)
  - `package_one_liner(pkg: PackageTerms) -> str`
  - `creator_embedding_document(name: str, bio: str, niches: list[str], packages: list[PackageTerms]) -> tuple[str, str]` → `(title, text)`
  - `text_hash(title: str, text: str) -> str` (sha256 hex of `f"{title}\n{text}"`)
  - `validate_package(pkg: PackageTerms, creator_niches: list[str]) -> list[RuleViolation]`
  - `missing_fields(draft: PackageDraft) -> list[str]`
  - `merge_package_draft(current: PackageDraft, extracted: PackageDraft) -> PackageDraft` (non-null extracted scalars overwrite; addons/extras merged by case-insensitive name, extracted wins)

- [ ] **Step 1: Write the failing tests**

```python
def test_format_cents():
    assert format_cents(100000) == "$1,000"
    assert format_cents(99950) == "$999.50"
    assert format_cents(40000) == "$400"

def test_one_liner_contract_with_extra_video():
    pkg = make_pkg(volume_count=2, volume_basis="per_contract", base_price_cents=100000,
                   addons=[Addon(name="Extra video", price_cents=40000, unit="video")])
    assert package_one_liner(pkg) == "2 videos/contract · $1,000 · +1 video $400"

def test_one_liner_weekly_no_addons():
    pkg = make_pkg(volume_count=1, volume_basis="per_week", base_price_cents=150000, addons=[])
    assert package_one_liner(pkg) == "1 video/week · $1,500"

def test_per_video_cents():
    assert per_video_cents(make_pkg(volume_count=3, base_price_cents=100000)) == 33333

def test_embedding_document_mentions_niche_labels_and_one_liners():
    title, text = creator_embedding_document("Maya Chen", "Honest gadget reviews",
                                             ["consumer_tech"], [make_pkg()])
    assert title == "Maya Chen"
    assert "consumer tech" in text and "2 videos/contract" in text

def test_validate_rejects_niche_outside_creator_domains():
    v = validate_package(make_pkg(niche="beauty"), creator_niches=["consumer_tech"])
    assert [x.field for x in v] == ["niche"]

def test_validate_rejects_duplicate_addon_names():
    pkg = make_pkg(addons=[Addon(name="Rush", price_cents=1, unit="item"),
                           Addon(name="rush", price_cents=2, unit="item")])
    assert "addons" in [x.field for x in validate_package(pkg, ["consumer_tech"])]

def test_missing_fields_lists_required_in_order():
    assert missing_fields(PackageDraft(name="Duo")) == [
        "content_type", "niche", "volume_count", "volume_basis",
        "base_price_cents", "preferred_channel"]

def test_merge_keeps_current_when_extracted_null_and_merges_addons():
    cur = PackageDraft(base_price_cents=100000, addons=[Addon(name="Extra video", price_cents=40000, unit="video")])
    ext = PackageDraft(volume_count=2, addons=[Addon(name="extra video", price_cents=45000, unit="video")])
    out = merge_package_draft(cur, ext)
    assert out.base_price_cents == 100000 and out.volume_count == 2
    assert [(a.name, a.price_cents) for a in out.addons] == [("extra video", 45000)]
```

`make_pkg(**overrides)` is a test helper returning a valid `PackageTerms` (2 short videos/contract, `consumer_tech`, $1,000, `phone_ok`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core -v`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the schemas and the four core modules**

Niche display labels are the key with `_` → space (`b2b_saas` → `b2b saas`). Pluralise "video/videos" by count. The one-liner joins parts with ` · `; the addon part appears only when `extra_video_addon` exists.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/core -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/packages.py backend/app/core backend/tests/core
git commit -m "feat(core): money, pricing, package text, and package rules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Auth — JWT verification, `GET /me`, `POST /onboarding`

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/schemas/me.py`, `backend/app/modules/me/service.py`, `backend/app/api/routers/me.py`
- Test: `backend/tests/api/test_auth.py`, `backend/tests/api/test_me.py`; add helpers to `backend/tests/conftest.py`

**Interfaces:**
- Consumes: `Database` (Task 3), `Settings` (Task 2).
- Produces:
  - `CurrentUser(id: UUID, email: str | None, role: Literal["brand","creator"] | None)`
  - dependencies `current_user(...) -> CurrentUser` and `require_role(role) -> Callable[..., CurrentUser]` (403 when role differs, 409 `onboarding_required` when role is `None`)
  - `MeResponse(user_id, email, role, display_name, brand: BrandSummary | None, creator: CreatorSummary | None)`
  - `OnboardingRequest` = discriminated union on `role`: brand → `display_name, company_name, category, product_name, product_summary`; creator → `display_name, handle, niches: list[Niche] (min 1), region`
  - `GET /api/v1/me`, `POST /api/v1/onboarding` (returns `MeResponse`)
- Test helpers: `make_token(sub, *, exp_delta=3600, aud="authenticated", key=TEST_KEY) -> str` signed ES256 with a test key; `fake_jwks` fixture overriding the JWKS lookup so tokens from `TEST_KEY` verify.

- [ ] **Step 1: Write the failing tests**

```python
async def test_missing_token_401(client): assert (await client.get("/api/v1/me")).status_code == 401
async def test_expired_token_401(client, fake_jwks): ...  # make_token(exp_delta=-10)
async def test_wrong_audience_401(client, fake_jwks): ...  # aud="anon"
async def test_foreign_key_401(client, fake_jwks): ...     # signed by a different EC key
@pytest.mark.db
async def test_me_before_onboarding_has_null_role(client, fake_jwks, auth_user): ...
@pytest.mark.db
async def test_brand_onboarding_creates_profile_brand_product(client, fake_jwks, auth_user): ...
    # role == "brand", brand.company_name == "Lumen Audio", one product row exists
@pytest.mark.db
async def test_creator_onboarding_rejects_unknown_niche_422(client, fake_jwks, auth_user): ...
@pytest.mark.db
async def test_second_onboarding_with_other_role_409(client, fake_jwks, auth_user): ...
```

`auth_user` inserts an `auth.users` row and yields its id; API DB tests run against the real local DB with cleanup.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/api/test_auth.py tests/api/test_me.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement verification and the endpoints**

Use `jwt.PyJWKClient(settings.supabase_jwks_url, cache_keys=True)`, `algorithms=["ES256","RS256"]`, `audience="authenticated"`, require `exp` and `sub`. The role comes from `profiles` (never from JWT `user_metadata`). Onboarding runs in one transaction; a repeat onboarding with the same role updates names, with a different role → 409 `role_locked`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/app/schemas/me.py backend/app/modules/me backend/tests
git commit -m "feat(auth): Supabase JWT verification, /me, and role onboarding" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Gemini adapter

**REQUIRED SKILL:** `gemini-api-dev`.

**Files:**
- Create: `backend/app/adapters/gemini.py`, `backend/tests/fakes.py`
- Test: `backend/tests/core/test_gemini_format.py`, `backend/tests/live/test_gemini_live.py`

**Interfaces:**
- Produces:
  - `format_document(title: str, text: str) -> str` → `"title: {title} | text: {text}"` (`title: none` when empty)
  - `format_query(query: str) -> str` → `"task: search result | query: {query}"`
  - `class GeminiPort(Protocol)`: `async embed_documents(docs: list[tuple[str, str]]) -> list[list[float]]`; `async embed_query(query: str) -> list[float]`; `async generate_structured(*, system: str, prompt: str, schema: type[T]) -> T`
  - `GeminiClient(settings)` implementing the port with `client.aio.models.*`; tenacity retry (3 attempts, exponential backoff) on transient errors; raises `GeminiUnavailable` after retries.
  - `FakeGemini` in `tests/fakes.py`: deterministic embeddings (sha256 of the input expanded to 768 floats, L2-normalised); `generate_structured` returns the next queued object from `fake.queue_structured(obj)` and records `(system, prompt, schema)` in `fake.calls`.

- [ ] **Step 1: Write the failing tests**

```python
def test_format_document(): assert format_document("Maya", "tech") == "title: Maya | text: tech"
def test_format_document_no_title(): assert format_document("", "x") == "title: none | text: x"
def test_format_query(): assert format_query("tech creators") == "task: search result | query: tech creators"

@pytest.mark.live
async def test_embed_documents_returns_one_768_vector_per_doc(settings):
    vecs = await GeminiClient(settings).embed_documents([("A", "tech"), ("B", "beauty")])
    assert len(vecs) == 2 and all(len(v) == 768 for v in vecs)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_gemini_format.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`embed_documents` passes `contents=[types.Content(parts=[types.Part(text=format_document(t, x))]) for t, x in docs]` with `config=types.EmbedContentConfig(output_dimensionality=768)` (batches of 50). `generate_structured` uses `config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json", response_schema=schema, thinking_config=types.ThinkingConfig(thinking_level="low"))` and returns `response.parsed`.

- [ ] **Step 4: Run unit and live tests**

Run: `uv run pytest tests/core/test_gemini_format.py -v` then `uv run pytest -m live tests/live/test_gemini_live.py -v` (needs `GEMINI_API_KEY`).
Expected: 3 passed; live test passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/adapters/gemini.py backend/tests/fakes.py backend/tests/core/test_gemini_format.py backend/tests/live
git commit -m "feat(adapters): Gemini embeddings and structured output port" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Seed marketplace, embedding cache, demo accounts

**Files:**
- Create: `backend/supabase/seed/creators.json`, `backend/supabase/seed/embeddings.json`, `backend/scripts/build_embedding_cache.py`, `backend/scripts/seed.py`
- Test: `backend/tests/core/test_seed_dataset.py`, `backend/tests/db/test_seed.py`

**Interfaces:**
- Consumes: `creator_embedding_document`, `text_hash`, `validate_package` (Task 4); `GeminiClient` (Task 6); `Database` (Task 3).
- Produces: `uv run python -m scripts.seed --reset`, which wipes M1 tables (not `auth.users` other than demo accounts) and inserts creators, packages, floors, and embeddings from the cache. It creates/updates three auth users through the Auth Admin API (`POST {SUPABASE_URL}/auth/v1/admin/users`, header `apikey: SUPABASE_SECRET_KEY`, `email_confirm: true`, password `DEMO_PASSWORD`):
  - brand `DEMO_BRAND_EMAIL`, with company "Lumen Audio", category `consumer_tech`, and product "Lumen Pods" ("Wireless earbuds with 40-hour battery and adaptive noise cancelling")
  - creator **Priya Raman** (`@priyareviews`), login + contact email `DEMO_HELPER_EMAIL`
  - creator **Arjun Mehta** (`@arjuntech`), login + contact email = `DEMO_HELPER_EMAIL` plus-tagged `+arjun`, phone `DEMO_HELPER_PHONE`, `phone_opt_in = true`
- Produces `plus_address(email: str, tag: str) -> str` in `scripts/seed.py`.

- [ ] **Step 1: Write the failing dataset tests**

```python
DATA = json.loads(Path("supabase/seed/creators.json").read_text())

def test_forty_creators_across_six_niches():
    assert len(DATA["creators"]) == 40
    assert {n for c in DATA["creators"] for n in c["niches"]} == set(NICHES)

def test_enough_demo_matches():
    hits = [c for c in DATA["creators"] if "consumer_tech" in c["niches"] and any(
        p["content_type"] == "short_video" and p["base_price_cents"] <= 200000 and p["status"] == "published"
        for p in c["packages"])]
    assert len(hits) >= 12

def test_every_package_passes_rules_and_has_floor_below_base(): ...
def test_handles_unique(): ...
def test_demo_creators_present():
    by = {c["handle"]: c for c in DATA["creators"]}
    assert by["arjuntech"]["phone_opt_in"] is True
    assert by["arjuntech"]["packages"][0]["preferred_channel"] == "phone_ok"
    assert by["priyareviews"]["packages"][0]["preferred_channel"] == "email_first"

def test_plus_address(): assert plus_address("a.b@x.com", "arjun") == "a.b+arjun@x.com"

def test_cache_covers_every_creator():
    cache = json.loads(Path("supabase/seed/embeddings.json").read_text())
    # every creator's text_hash(creator_embedding_document(...)) is a key with a 768-float value
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_seed_dataset.py -v`
Expected: FAIL (file missing).

- [ ] **Step 3: Author `creators.json`**

40 fictional creators: 14 `consumer_tech` (at least 12 with a published short-video package ≤ $2,000), 6 each in `beauty`, `fitness`, `food`, `gaming`, and 2 in `b2b_saas`. Each creator gets 1–3 packages with realistic $400–$6,000 base prices, followers between 8k and 1.2M, engagement between 1.5% and 9%, regions `US`/`IN`/`UK`/`CA`/`AU`, and a floor at 70–90% of base.
- Contact emails use `@example.com`; seeded creators have no phone and `phone_opt_in: false`.
- The JSON shape is `{"creators": [{handle, name, bio, niches, region, languages, platforms, followers, engagement_rate, email, phone, phone_opt_in, packages: [{...PackageTerms, status, floor_price_cents}]}]}`.
- Demo creators:
  - Arjun: "Launch Duo", 2 short videos/contract, $1,000, addon "Extra video" $400 (`unit: video`), lead time 14 days, `phone_ok`.
  - Priya: "Review Pair", 2 short videos/contract, $1,000, addon "Extra video" $450, lead time 21 days, `email_first`.

- [ ] **Step 4: Build the embedding cache**

Implement `scripts/build_embedding_cache.py`. It computes `(title, text)` for every creator, embeds only hashes missing from the cache, and writes `{hash: [768 floats rounded to 6 dp]}`.
Run: `uv run python -m scripts.build_embedding_cache`
Expected: `embedded 40 new, 0 cached`; the file is about 300 KB.

- [ ] **Step 5: Implement `scripts/seed.py` and its DB test**

```python
@pytest.mark.db
async def test_seed_is_idempotent_and_searchable(db): ...
    # run seed twice -> 40 creators; demo brand has 1 product;
    # match_creators(<Priya's cached vector>) returns Priya first
```

The seed fails with "embedding cache stale for <handle> — run scripts.build_embedding_cache" when a hash is missing (it never calls Gemini itself).

- [ ] **Step 6: Run all tests and seed for real**

Run: `uv run pytest tests/core/test_seed_dataset.py tests/db/test_seed.py -v` then `uv run python -m scripts.seed --reset`
Expected: all passed; prints `seeded 40 creators, 3 demo accounts`.

- [ ] **Step 7: Commit**

```bash
git add backend/supabase/seed backend/scripts backend/tests
git commit -m "feat(seed): 40-creator marketplace, embedding cache, demo accounts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Discovery API

**Files:**
- Create: `backend/app/schemas/discovery.py`, `backend/app/modules/discovery/repo.py`, `backend/app/modules/discovery/service.py`, `backend/app/api/routers/discovery.py`, `backend/app/api/routers/creators.py`
- Test: `backend/tests/api/test_discovery.py`

**Interfaces:**
- Consumes: `GeminiPort.embed_query`, `match_creators`, `package_one_liner`, `per_video_cents`, `require_role("brand")`.
- Produces:
  - `SearchFilters(niches: list[Niche] = [], content_types: list[ContentType] = [], max_price_cents: PositiveInt | None = None, min_followers: NonNegativeInt | None = None, region: str | None = None)`
  - `SearchRequest(query: str | None = None, filters: SearchFilters = SearchFilters(), limit: int = Field(24, ge=1, le=48))`
  - `PackageSummary(id, name, content_type, niche, volume_count, volume_basis, base_price_cents, per_video_cents, one_liner, lead_time_days, preferred_channel, addons: list[Addon])`
  - `CreatorCard(id, handle, name, initials, niches, region, followers, engagement_rate, packages: list[PackageSummary])` (published packages only)
  - `SearchResponse(query: str | None, filters: SearchFilters, results: list[CreatorCard])`
  - `POST /api/v1/discovery/search` (brand only), `GET /api/v1/creators/{id}` → `CreatorCard` (brand only; 404 for unknown)
  - `DiscoveryService.search(req: SearchRequest) -> SearchResponse`
  - dependency `get_gemini() -> GeminiPort` in `api/deps.py` (returns a process-wide `GeminiClient`)
  - test fixtures in `tests/conftest.py` (need the seeded DB from Task 7): `fake_gemini` (overrides `get_gemini` with `FakeGemini`; exposes `embed_calls`), `brand_client` (signed in as the seeded demo brand), `creator_client` (signed in as Priya), `other_package_id` (Arjun's published package id). Clients use `make_token(sub=<seeded auth user id>)` with `fake_jwks`.

- [ ] **Step 1: Write the failing tests** (seeded DB, `FakeGemini` injected through `get_gemini` override)

```python
async def test_filters_only_does_not_embed(brand_client, fake_gemini):
    r = await brand_client.post("/api/v1/discovery/search",
        json={"filters": {"niches": ["consumer_tech"], "content_types": ["short_video"], "max_price_cents": 200000}})
    assert r.status_code == 200 and len(r.json()["results"]) >= 12
    assert fake_gemini.embed_calls == 0
    assert all(any(p["base_price_cents"] <= 200000 and p["content_type"] == "short_video"
                   for p in c["packages"]) for c in r.json()["results"])

async def test_query_embeds_once(brand_client, fake_gemini): ...
async def test_response_never_contains_private_fields(brand_client):
    body = (await brand_client.post("/api/v1/discovery/search", json={})).text
    for key in ("floor_price_cents", "email", "phone", "phone_opt_in"): assert key not in body

async def test_creator_role_gets_403(creator_client): ...
async def test_package_strip_text(brand_client):
    # find arjuntech; packages[0].one_liner == "2 videos/contract · $1,000 · +1 video $400"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/api/test_discovery.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement repo, service, routers**

The repo loads cards for the matched ids in a single query (creator rows + published packages, `json_agg`) and keeps the `match_creators` order. `initials` is the first letter of the first two name words.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_discovery.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests/api/test_discovery.py
git commit -m "feat(discovery): hybrid semantic + filter search with package cards" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Voice backend — Scribe token and intent router

**Files:**
- Create: `backend/app/adapters/elevenlabs.py`, `backend/app/core/refs.py`, `backend/app/schemas/voice.py`, `backend/app/modules/voice/prompts.py`, `backend/app/modules/voice/service.py`, `backend/app/api/routers/voice.py`
- Test: `backend/tests/core/test_refs.py`, `backend/tests/api/test_voice.py`, `backend/tests/live/test_intent_live.py`

**Interfaces:**
- Consumes: `GeminiPort.generate_structured`, `SearchRequest`, `PackageDraft`, `merge_package_draft`.
- Produces:
  - `ElevenLabsPort.mint_scribe_token() -> ScribeToken(token: str, expires_at: str)`; dependency `get_elevenlabs() -> ElevenLabsPort`; `POST /api/v1/voice/scribe-token` (any onboarded user)
  - `CreatorRef(id: UUID, name: str, handle: str)`; `VoiceContext(visible_creators: list[CreatorRef] = [], package_draft: PackageDraft | None = None)`
  - `VoiceScreen = Literal["discover", "review", "packages", "any"]`
  - `VoiceCommandRequest(screen: VoiceScreen, transcript: str = Field(min_length=1, max_length=500), context: VoiceContext)`
  - `SelectArgs(creator_ids: list[UUID] = [], top_n: int | None = Field(None, ge=1, le=48))`
  - `VoiceIntent(kind: Literal["search","select","clear_selection","open_review","package_draft","navigate","unclear"], heard: str, search: SearchRequest | None = None, select: SelectArgs | None = None, package_draft: PackageDraft | None = None, navigate: str | None = None, suggestions: list[str] = [])`
  - `ALLOWED_INTENTS: dict[VoiceScreen, set[str]]` — discover/review: search, select, clear_selection, open_review, navigate; packages: package_draft, navigate; any: navigate
  - `resolve_creator_refs(names: list[str], visible: list[CreatorRef]) -> list[UUID]` (case-insensitive; matches full name, first name, or handle with/without `@`; fuzzy via `difflib.SequenceMatcher` ratio ≥ 0.8; unmatched names are dropped)
  - `VoiceService.route(req: VoiceCommandRequest) -> VoiceIntent`. Gemini returns a `RoutedIntent` (same shape, but `select.creator_names: list[str]` instead of ids); the service resolves names to ids, forces `kind="unclear"` when the kind is not in `ALLOWED_INTENTS[screen]`, and merges `package_draft` onto `context.package_draft`.
  - `POST /api/v1/voice/command`

- [ ] **Step 1: Write the failing tests**

```python
VIS = [CreatorRef(id=A, name="Maya Chen", handle="mayatech"), CreatorRef(id=B, name="Arjun Mehta", handle="arjuntech")]
def test_resolve_by_first_name(): assert resolve_creator_refs(["maya"], VIS) == [A]
def test_resolve_by_handle(): assert resolve_creator_refs(["@arjuntech"], VIS) == [B]
def test_resolve_fuzzy(): assert resolve_creator_refs(["Arjun Mehtaa"], VIS) == [B]
def test_unmatched_dropped(): assert resolve_creator_refs(["Zed"], VIS) == []

async def test_intent_not_allowed_on_screen_becomes_unclear(brand_client, fake_gemini):
    fake_gemini.queue_structured(RoutedIntent(kind="package_draft", heard="x", package_draft=PackageDraft()))
    r = await brand_client.post("/api/v1/voice/command",
        json={"screen": "discover", "transcript": "x", "context": {}})
    assert r.json()["kind"] == "unclear"

async def test_select_names_resolved_to_ids(brand_client, fake_gemini): ...
async def test_package_draft_merged_with_context(creator_client, fake_gemini): ...
async def test_negative_cents_from_model_rejected_as_unclear(brand_client, fake_gemini): ...
    # model returns max_price_cents=-5 -> validation fails -> kind "unclear", suggestions non-empty
async def test_scribe_token_requires_auth(client): assert (await client.post("/api/v1/voice/scribe-token")).status_code == 401

@pytest.mark.live
@pytest.mark.parametrize("phrase,cents", [("under two grand", 200000), ("below 1.5k", 150000),
    ("max twelve hundred dollars", 120000), ("under two thousand dollars", 200000)])
async def test_spoken_money_to_cents(settings, phrase, cents): ...
    # route(screen="discover", transcript=f"tech creators doing short videos {phrase}") -> search.filters.max_price_cents == cents
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/core/test_refs.py tests/api/test_voice.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the system prompt in `modules/voice/prompts.py`**

`ROUTER_SYSTEM` must state:
- the screen and its allowed intents
- the exact niche and content-type vocabularies
- that all money is integer US cents (convert "two grand" / "1.5k" / "twelve hundred")
- that "under/below/max X" means `max_price_cents`
- that "top N" / "first N" means `select.top_n`
- that names go in `select.creator_names`
- that package dictation fills `package_draft` fields only from what was said
- that `heard` echoes the transcript cleaned of filler words
- that the answer is `unclear` with 2–3 suggestions when unsure

The user prompt includes the transcript, the screen, the visible creator names, and the current draft JSON.

- [ ] **Step 4: Implement adapter, service, router**

`ElevenLabsClient` wraps `AsyncElevenLabs(api_key=...).tokens.single_use.create(token_type="realtime_scribe")`. A Pydantic `ValidationError` on the model output yields `VoiceIntent(kind="unclear", heard=transcript, suggestions=[...])`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/core/test_refs.py tests/api/test_voice.py -v`, then `uv run pytest -m live tests/live/test_intent_live.py -v`
Expected: all passed. If a live money case fails, refine `ROUTER_SYSTEM` and rerun. Do not loosen the assertion.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(voice): Scribe token endpoint and screen-scoped intent router" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Creator packages API

**Files:**
- Create: `backend/app/modules/packages/repo.py`, `backend/app/modules/packages/service.py`, `backend/app/api/routers/packages.py`; extend `backend/app/schemas/packages.py`
- Test: `backend/tests/api/test_packages.py`

**Interfaces:**
- Consumes: `validate_package`, `missing_fields`, `merge_package_draft`, `creator_embedding_document`, `text_hash`, `GeminiPort`, `require_role("creator")`, `ROUTER_SYSTEM`-style prompt for drafts.
- Produces (all under `/api/v1/me/packages`, creator only, scoped to the caller's creator row):
  - `GET ""` → `list[MyPackage]` where `MyPackage = PackageSummary + status + floor_price_cents | None`
  - `POST "/draft-from-speech"` body `DraftFromSpeechRequest(transcript: str, current: PackageDraft = PackageDraft())` → `DraftResult(draft: PackageDraft, missing: list[str], violations: list[RuleViolation], heard: str)`
  - `POST ""` body `PackageDraft` → `MyPackage` (status `draft`; 422 with `missing` when required fields absent)
  - `PATCH "/{id}"` body `PackageDraft` (partial) → `MyPackage`
  - `POST "/{id}/publish"` → `MyPackage` (422 with `violations` when rules fail; on success re-embeds the creator if `text_hash` changed)
  - `PUT "/{id}/floor"` body `FloorRequest(floor_price_cents: PositiveInt)` → `MyPackage` (422 if floor > base price)
  - another creator's id → 404; brand → 403

- [ ] **Step 1: Write the failing tests**

```python
async def test_draft_from_speech_merges_and_reports_missing(creator_client, fake_gemini):
    fake_gemini.queue_structured(PackageDraft(volume_count=2, volume_basis="per_contract", base_price_cents=100000))
    r = await creator_client.post("/api/v1/me/packages/draft-from-speech",
        json={"transcript": "two videos per contract for a thousand", "current": {"name": "Duo"}})
    assert r.json()["draft"]["name"] == "Duo" and r.json()["draft"]["volume_count"] == 2
    assert r.json()["missing"] == ["content_type", "niche", "preferred_channel"]

async def test_publish_blocked_with_violations(creator_client): ...   # niche outside creator niches -> 422
async def test_publish_reembeds_when_text_changes(creator_client, fake_gemini): ...  # embed_calls == 1, hash updated
async def test_publish_skips_embed_when_unchanged(creator_client, fake_gemini): ...  # second publish -> embed_calls unchanged
async def test_floor_above_base_422(creator_client): ...
async def test_other_creators_package_404(creator_client, other_package_id): ...
async def test_brand_403(brand_client): ...
async def test_published_package_visible_in_discovery(creator_client, brand_client, fake_gemini): ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/api/test_packages.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

The draft prompt reuses the money and vocabulary rules from `ROUTER_SYSTEM` (shared constant in `prompts.py`) and extracts `PackageDraft` from what was said only. Publish re-embedding happens in the same request, after the status update commits; if Gemini fails, the package stays published and the response includes `warnings: ["search index update pending"]`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_packages.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests/api/test_packages.py
git commit -m "feat(packages): voice-drafted package editor API with publish and floor" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend scaffold and typed API client

**Files:**
- Create: `frontend/` by copying root `package.json`, `package-lock.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `eslint.config.mjs`, `.prettierrc`, `.prettierignore`, `components.json`, `app/`, `components/`, `hooks/`, `lib/`, `public/` (not `node_modules`, `.next`, `tsconfig.tsbuildinfo`)
- Create: `frontend/.gitignore` (copy of root), `frontend/.env.example`, `backend/scripts/export_openapi.py`, `frontend/lib/api/openapi.json` (generated), `frontend/lib/api/schema.d.ts` (generated), `frontend/lib/api/client.ts`, `frontend/lib/supabase/browser.ts`, `frontend/vitest.config.ts`
- Test: `frontend/tests/unit/api-client.test.ts`

**Interfaces:**
- Produces: `createApiClient(opts: { baseUrl: string; getToken: () => Promise<string | null>; refresh: () => Promise<boolean>; onUnauthorized: (nextPath: string) => void }) -> Client<paths>` (openapi-fetch with middleware: adds `Authorization: Bearer`; on 401 calls `refresh()` once and retries; if still 401 calls `onUnauthorized(location.pathname)`); `useApi()` hook returning the singleton client; `npm run api:gen` script; `npm run test` (vitest), `npm run typecheck`.

- [ ] **Step 1: Copy the scaffold and install**

Run: copy the listed files into `frontend/`. Set `"name": "collabio-frontend"`. Then in `frontend/`: `npm install` and `npm install @supabase/supabase-js @supabase/ssr @tanstack/react-query openapi-fetch @elevenlabs/react gsap @gsap/react` and `npm install -D openapi-typescript vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/user-event @playwright/test`. Pin exact versions (`--save-exact`); commit the lockfile.
Add to `components.json` registries: `"@elevenlabs": "https://ui.elevenlabs.io/r/{name}.json"`.
Expected: `npm run build` succeeds on the copied starter page.

- [ ] **Step 2: Generate the API types**

`backend/scripts/export_openapi.py` writes `create_app().openapi()` to a path argument. Add `"api:gen": "cd ../backend && uv run python -m scripts.export_openapi ../frontend/lib/api/openapi.json && cd ../frontend && openapi-typescript lib/api/openapi.json -o lib/api/schema.d.ts"`.
Run: `npm run api:gen`
Expected: `schema.d.ts` contains `"/api/v1/discovery/search"`.

- [ ] **Step 3: Write the failing client tests**

```ts
it("adds bearer token", async () => { /* mock fetch; expect Authorization: "Bearer t1" */ })
it("401 refreshes once then retries", async () => { /* first 401, refresh -> true, second 200; refresh called 1x */ })
it("401 refreshes once then redirects", async () => {
  /* both 401; expect onUnauthorized called with "/brand/discover"; refresh called exactly once */ })
```

- [ ] **Step 4: Run them to see them fail**

Run: `npm run test -- api-client`
Expected: FAIL.

- [ ] **Step 5: Implement `client.ts` and `supabase/browser.ts`**

`browser.ts` exports `getSupabaseBrowser()` using `createBrowserClient(NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY)`. `useApi` wires `getToken` to `supabase.auth.getSession()`, `refresh` to `supabase.auth.refreshSession()`, and `onUnauthorized` to `router.replace("/sign-in?next=" + encodeURIComponent(path))`.

- [ ] **Step 6: Run tests and typecheck**

Run: `npm run test && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend backend/scripts/export_openapi.py
git commit -m "feat(frontend): Next 16 scaffold, typed OpenAPI client with session refresh" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Visual foundation and app shell

**REQUIRED SKILLS:** `gsap-react`, `gsap-core`. Use the shadcn MCP to view each registry item before adding it.

**Files:**
- Modify: `frontend/app/layout.tsx`, `frontend/app/globals.css`
- Create: `frontend/components/shell/app-shell.tsx`, `frontend/lib/money.ts`, registry components under `frontend/components/ui/`
- Test: `frontend/tests/unit/money.test.ts`, `frontend/tests/unit/app-shell.test.tsx`

**Interfaces:**
- Produces: `formatCents(cents: number): string` (same rule as backend `format_cents`); `<AppShell role="brand" | "creator">{children}</AppShell>` rendering the left rail (brand: Discover; creator: Packages, plus disabled "Offers", "Analytics" entries labelled "Soon") and a bottom slot for the Voice Dock; CSS tokens `--voice` (signature accent), `--gain`, `--loss`, `--font-display`, `--font-sans`, `--font-mono`; utility class `.num` (`font-variant-numeric: tabular-nums; font-family: var(--font-mono)`).
- Installed components: `npx shadcn@latest add @react-bits/SpotlightCard-TS-TW @react-bits/BlurText-TS-TW @react-bits/CountUp-TS-TW @elevenlabs/orb` plus shadcn primitives `badge toggle-group table dialog tooltip input label sonner`.

- [ ] **Step 1: Write the failing tests**

```ts
it("formats cents", () => {
  expect(formatCents(100000)).toBe("$1,000"); expect(formatCents(99950)).toBe("$999.50") })
it("brand shell shows Discover only", () => { /* render AppShell role="brand"; getByRole("link",{name:"Discover"}) */ })
it("creator shell shows Packages and disabled Offers", () => { /* Offers has aria-disabled="true" */ })
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm run test -- money app-shell`
Expected: FAIL.

- [ ] **Step 3: Implement tokens, fonts, shell; add registry components**

Fonts via `next/font/google`: `Instrument_Serif` (display, weight 400) → `--font-display`; keep `Geist` → `--font-sans` and `Geist_Mono` → `--font-mono`.
- Light theme: warm paper background `oklch(0.985 0.006 85)`, ink `oklch(0.2 0.01 60)`.
- Dark theme: `oklch(0.17 0.008 60)` with ink `oklch(0.95 0.006 85)`.
- `--voice: oklch(0.68 0.19 35)` (ember), `--gain: oklch(0.62 0.15 150)`, `--loss: oklch(0.6 0.19 25)`.
- Headings use `font-display`.

The shell rail is 64 px wide and icon-first with tooltips (lucide icons). The active item gets the `--voice` underline.

- [ ] **Step 4: Run tests and build**

Run: `npm run test && npm run build`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): deal-room visual tokens, fonts, registry components, app shell" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Auth flows, onboarding, role routing

**Files:**
- Create: `frontend/lib/supabase/server.ts`, `frontend/lib/supabase/proxy.ts`, `frontend/proxy.ts`, `frontend/lib/auth/routing.ts`, `frontend/app/(auth)/sign-in/page.tsx`, `frontend/app/(auth)/sign-up/page.tsx`, `frontend/app/(auth)/onboarding/page.tsx`, `frontend/app/brand/layout.tsx`, `frontend/app/creator/layout.tsx`; replace `frontend/app/page.tsx` with a redirect to the role home
- Test: `frontend/tests/unit/routing.test.ts`

**Interfaces:**
- Consumes: `GET /me`, `POST /onboarding` (Task 5), `AppShell` (Task 12).
- Produces: `resolveRoute(me: { role: "brand" | "creator" | null } | null, pathname: string): string | null` → redirect target or `null`:
  - no session → `/sign-in?next=<path>`
  - `role` null → `/onboarding`
  - a brand on `/creator/*` → `/brand/discover`
  - a creator on `/brand/*` → `/creator/packages`
  - an onboarded user on `/onboarding` → their home
- Produces `roleHome(role) -> "/brand/discover" | "/creator/packages"`.

- [ ] **Step 1: Read the Next.js guides**

Read `node_modules/next/dist/docs/01-app/02-guides/authentication.md` and `01-app/01-getting-started/16-proxy.md`.

- [ ] **Step 2: Write the failing routing tests**

```ts
it("anonymous → sign-in with next", () => expect(resolveRoute(null, "/brand/discover")).toBe("/sign-in?next=%2Fbrand%2Fdiscover"))
it("no role → onboarding", () => expect(resolveRoute({ role: null }, "/brand/discover")).toBe("/onboarding"))
it("brand on creator route", () => expect(resolveRoute({ role: "brand" }, "/creator/packages")).toBe("/brand/discover"))
it("creator on brand route", () => expect(resolveRoute({ role: "creator" }, "/brand/discover")).toBe("/creator/packages"))
it("allowed", () => expect(resolveRoute({ role: "brand" }, "/brand/discover/review")).toBeNull())
it("onboarded user on onboarding", () => expect(resolveRoute({ role: "creator" }, "/onboarding")).toBe("/creator/packages"))
```

- [ ] **Step 3: Run them to see them fail**

Run: `npm run test -- routing`
Expected: FAIL.

- [ ] **Step 4: Implement**

- `proxy.ts` refreshes the Supabase session cookie (the `@supabase/ssr` `updateSession` pattern) and does only the optimistic "no session → sign-in" redirect for `/brand/:path*`, `/creator/:path*`, `/onboarding`.
- Each role layout is an async server component: it gets the session from `server.ts`, calls `GET /me` with the access token, and applies `resolveRoute`.
- Onboarding is a two-card choice ("I sell products" / "I create content"), then a short form. Brand form: company, category chip, product name, one-line summary. Creator form: display name, handle, niche chips, region select. Typing is limited to names.
- Sign-in has a demo hint listing the seeded emails when `NEXT_PUBLIC_DEMO_MODE=1` (optional; add it to `frontend/.env.example`).

- [ ] **Step 5: Run tests, typecheck, and a manual check**

Run: `npm run test && npm run typecheck`, then start backend (`uv run uvicorn app.main:create_app --factory --port 8000`) and frontend (`npm run dev`).
Expected: tests green. Signing in as `DEMO_BRAND_EMAIL` lands on `/brand/discover`; Priya lands on `/creator/packages`; Priya visiting `/brand/discover` is redirected.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(frontend): Supabase auth, onboarding, and role-guarded app trees" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Voice Dock (command mode)

**Files:**
- Create: `frontend/lib/voice/dock-machine.ts`, `frontend/lib/voice/use-command-capture.ts`, `frontend/components/voice/voice-screen.tsx`, `frontend/components/voice/voice-dock.tsx`, `frontend/components/voice/heard-chip.tsx`
- Modify: `frontend/components/shell/app-shell.tsx` (mount the dock)
- Test: `frontend/tests/unit/dock-machine.test.ts`, `frontend/tests/unit/voice-dock.test.tsx`

**Interfaces:**
- Consumes: `POST /voice/scribe-token`, `POST /voice/command` (Task 9), `useApi` (Task 11), ElevenLabs `Orb` (Task 12).
- Produces:
  - `type DockState = { mode: "idle" | "connecting" | "listening" | "routing" | "heard" | "error"; input: "voice" | "text"; partial: string; heard: string | null; error: string | null }`
  - `type DockEvent = { type: "PRESS" } | { type: "CONNECTED" } | { type: "PARTIAL"; text: string } | { type: "RELEASE"; finalText: string } | { type: "ROUTED"; heard: string } | { type: "FAIL"; reason: string; fatal: boolean } | { type: "TEXT_SUBMIT"; text: string } | { type: "DISMISS" }`
  - `dockReducer(state: DockState, event: DockEvent): DockState`; `initialDockState`
  - `useCommandCapture({ onFinal, onPartial, onError }) -> { start(): Promise<void>; stop(): void; status }` wrapping `useScribe({ modelId: "scribe_v2_realtime" })`. `start` fetches a fresh token and calls `connect({ token, microphone: { echoCancellation: true, noiseSuppression: true } })`. `stop` computes the final text as all committed transcripts plus the current partial, then disconnects.
  - `useVoiceScreen(screen: VoiceScreen, getContext: () => VoiceContext, onIntent: (intent: VoiceIntent) => void)`: the registration a page calls. The dock posts `{screen, transcript, context}` and hands the result to the active page's `onIntent`.
  - Orb `agentState` mapping: listening → `"listening"`, connecting/routing → `"thinking"`, else `null`.

- [ ] **Step 1: Write the failing tests**

```ts
it("press → connecting → listening shows partial", ...)
it("release with empty text returns to idle without routing", ...)
it("release → routing → heard", ...)
it("error falls back to typing", () => {
  const s = dockReducer({ ...initialDockState, mode: "connecting" }, { type: "FAIL", reason: "Microphone blocked", fatal: true })
  expect(s.mode).toBe("error"); expect(s.input).toBe("text"); expect(s.error).toBe("Microphone blocked") })
it("text submit routes like voice", ...)
it("space inside input does not start capture", async () => {
  /* render dock + <input>; focus input; keydown " " -> start() not called; input value is " " */ })
it("holding space outside inputs starts, releasing stops", ...)
it("routed intent is delivered to the registered screen handler", ...)
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm run test -- dock`
Expected: FAIL.

- [ ] **Step 3: Implement**

Layout:
- The dock is fixed bottom-center: a frosted pill (`backdrop-filter: blur(16px)`, 1 px border, `--voice` ring while listening) with the Orb (40 px), then the live partial text, then a keyboard toggle.
- `HeardChip` appears above the dock after routing ("Heard: …"); tapping it puts the text into the text input for editing and resubmission. It auto-dismisses after 6 s.

Behaviour:
- Hold Space (ignored when the event target is an input, textarea, select, or contentEditable) or press-and-hold the orb.
- A fatal failure (microphone permission, token mint, auth error) switches `input` to `"text"`, and a toast explains why.
- The dock appears/disappears with a GSAP opacity/translate tween, skipped under reduced motion.

- [ ] **Step 4: Run tests and a manual check**

Run: `npm run test -- dock && npm run typecheck`. Then in the browser, hold Space on `/brand/discover` and say "hello". Live text should appear, then a "Heard" chip.
Expected: green; manual check passes. Denying the mic switches to the text box.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(voice): command-mode Voice Dock with Scribe realtime and text fallback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Brand Discover and Review

**REQUIRED SKILL:** `gsap-react` (Flip plugin for grid re-layout).

**Files:**
- Create: `frontend/lib/discover/state.ts`, `frontend/components/deal/package-strip.tsx`, `frontend/components/deal/creator-card.tsx`, `frontend/components/deal/filter-chips.tsx`, `frontend/components/deal/selection-tray.tsx`, `frontend/components/deal/compare-table.tsx`, `frontend/app/brand/discover/page.tsx`, `frontend/app/brand/discover/review/page.tsx`
- Test: `frontend/tests/unit/discover-state.test.ts`, `frontend/tests/unit/discover-page.test.tsx`

**Interfaces:**
- Consumes: `POST /discovery/search` (Task 8), `useVoiceScreen` (Task 14), `SpotlightCard`, `BlurText` (Task 12), `formatCents`.
- Produces:
  - `type DiscoverState = { query: string | null; filters: SearchFilters; selected: string[]; results: CreatorCard[] }`
  - `applySearchIntent(state, search: SearchRequest): DiscoverState` (replaces query + filters, keeps selection)
  - `removeFilter(state, chip: FilterChip): DiscoverState`
  - `selectionReducer(state, action: { type: "toggle"; id } | { type: "top_n"; n } | { type: "add"; ids } | { type: "clear" }): DiscoverState` (`top_n` picks the first n of the current results in order; selection capped at 10 with a toast "Batches are limited to 10 creators")
  - `chipsFor(filters: SearchFilters): FilterChip[]` (labels like "Consumer tech", "Short video", "≤ $2,000", "50k+ followers", "US")
  - Selected ids persist in `sessionStorage` key `collabio:selection` so Review can read them.

- [ ] **Step 1: Write the failing tests**

```ts
it("search intent sets chips", () => {
  const s = applySearchIntent(empty, { query: "short-form reviews", filters: { niches: ["consumer_tech"], content_types: ["short_video"], max_price_cents: 200000 } })
  expect(chipsFor(s.filters).map(c => c.label)).toEqual(["Consumer tech", "Short video", "≤ $2,000"]) })
it("top_n selects first n results in order", ...)
it("selection capped at 10", ...)
it("removing a chip clears that filter only", ...)
it("package strip renders one-liner and per-video price", () => {
  /* render PackageStrip with Arjun's summary; text "2 videos/contract · $1,000 · +1 video $400" and "$500/video" */ })
it("shows empty state with removable chips", async () => {
  /* mock search → results: []; expect text "No creators match" and a remove button per active chip */ })
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm run test -- discover`
Expected: FAIL.

- [ ] **Step 3: Implement**

Discover page, top to bottom:
- A `BlurText` heading "Who should tell your story?"
- The hint "Hold Space and describe the creators you want".
- Chip row, which can also be edited by click through a chip popover for adding a niche, format, or price.
- Responsive grid of `CreatorCard`s. Each card is a `SpotlightCard` with an initials avatar ringed in the niche colour, name, @handle, region, followers, and engagement in `.num`, then one `PackageStrip` per package (name, one-liner, `$X/video` in `.num`). A checkbox sits top-right.
- When results change, run GSAP `Flip.from` on the grid.
- `SelectionTray` slides up from the bottom (GSAP, above the Dock) showing selected avatars, "N selected", and **Review →**.

Review page: `CompareTable` with one column per selected creator and rows for package, price, $/video, volume, lead time, and preferred channel. Each row's best value is highlighted with `--gain`. The page has a disabled **Start negotiation** button with tooltip "Coming in M2".

Review registers `useVoiceScreen("review", …)`: `search` navigates back to Discover with the search applied; `select` and `clear_selection` edit the compared set.

Voice intents on Discover:
- `search` → `applySearchIntent` then refetch
- `select` → `selectionReducer` (`top_n` / `add`)
- `clear_selection`
- `open_review` → navigate

- [ ] **Step 4: Run tests and a manual check**

Run: `npm run test && npm run typecheck`. Manual: on `/brand/discover`, say "tech creators doing short-form reviews under two thousand dollars". The chips should read Consumer tech / Short video / ≤ $2,000 and at least 12 cards should appear. Then say "select the top ten" (tray shows 10) and "open review" (table shows 10 columns).
Expected: green; manual flow works.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(discover): voice discovery grid, filter chips, selection tray, review table" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Creator Packages page

**Files:**
- Create: `frontend/components/deal/package-draft-card.tsx`, `frontend/app/creator/packages/page.tsx`
- Test: `frontend/tests/unit/package-draft-card.test.tsx`

**Interfaces:**
- Consumes: `/me/packages*` endpoints (Task 10), `useVoiceScreen("packages", …)` (Task 14), `PackageStrip` (Task 15).
- Produces: `<PackageDraftCard draft missing violations onChange onSave onPublish />`. Fields are edited with chips (content type, niche limited to the creator's niches, volume basis, preferred channel), steppers (volume count, lead time, slots per month), money inputs (base price, addon prices), and an addon list (add/remove). Each field in `missing` shows a pulsing `--voice` outline. **Publish** is disabled while `missing` is non-empty, and `violations` render inline under their field. A floor-price field sits in a separate "Private — only you see this" panel with a lock icon.

- [ ] **Step 1: Write the failing tests**

```ts
it("missing fields are outlined and publish disabled", ...)
it("violations render under their field", ...)
it("voice draft merges into the card", async () => {
  /* register screen; deliver intent {kind:"package_draft", package_draft:{volume_count:2}}; stepper shows 2 */ })
it("floor field shows private label", ...)
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm run test -- package-draft`
Expected: FAIL.

- [ ] **Step 3: Implement**

The page lists the creator's packages as cards (status badge Draft/Published, `PackageStrip`) plus a **New package** card with the prompt "Hold Space and describe your package".
- A `package_draft` voice intent from the Dock opens or updates the draft card. Saving uses `POST`/`PATCH`; publishing uses `/publish`.
- When the response has `warnings`, show them as a toast.
- Count-up on the price only when its value changes (`CountUp`).

- [ ] **Step 4: Run tests and a manual check**

Run: `npm run test && npm run typecheck`. Manual: as Priya, say "short videos, tech, two per contract for nine hundred, extra video three fifty, email first". The draft card fills and only "name" stays pulsing. Type a name, publish, then as the brand search "tech short videos under a thousand" — Priya's new package appears.
Expected: green; manual flow works.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(packages): voice-dictated package editor with private floor price" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: M1 end-to-end smoke and run docs

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/tests/e2e/m1.spec.ts`, `backend/README.md`
- Modify: `frontend/README.md` (replace the copied template text). The root `README.md` belongs to the scaffold and is not touched.

**Interfaces:**
- Consumes: everything above. Voice is replaced by the Dock's text input (keyboard toggle), which exercises the same `/voice/command` path.

- [ ] **Step 1: Write the e2e spec**

```ts
test("brand discovers and reviews by typed command", async ({ page }) => {
  // sign in as DEMO_BRAND_EMAIL → /brand/discover
  // dock keyboard toggle → type "tech creators doing short-form reviews under two thousand dollars" → Enter
  // expect chips "Consumer tech", "Short video", "≤ $2,000"; expect ≥ 10 creator cards
  // type "select the top ten" → tray shows "10 selected"; click Review → 10 columns
})
test("creator drafts and publishes a package by typed command", async ({ page }) => {
  // sign in as Priya → /creator/packages → type package dictation → fill name → Publish → badge "Published"
})
test("brand cannot open creator routes", async ({ page }) => { /* /creator/packages → redirected to /brand/discover */ })
```

- [ ] **Step 2: Run the full stack and the suite**

Run: `supabase start` and `uv run python -m scripts.seed --reset` (backend), `uv run uvicorn app.main:create_app --factory --port 8000`, `npm run dev`, then `npx playwright test`.
Expected: 3 passed (these tests call real Gemini; they need `GEMINI_API_KEY`).

- [ ] **Step 3: Full verification**

Run: `uv run pytest -v && uv run ruff check .` (backend), `npm run test && npm run typecheck && npm run lint && npm run build` (frontend).
Expected: all green; record the counts in the commit message body.

- [ ] **Step 4: Write the READMEs**

Cover: prerequisites (Docker, uv, Node 22, keys), `.env` setup from `.env.example`, `supabase start`, seed, and the run/test commands from Steps 2–3.

- [ ] **Step 5: Commit**

```bash
git add frontend backend/README.md
git commit -m "test(m1): end-to-end smoke for voice discovery and package publishing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
