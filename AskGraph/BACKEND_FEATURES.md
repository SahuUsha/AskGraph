# Backend Features — How They Work

This document describes every backend feature in AskGraph: what it does, which
code owns it, and the internal flow from request to response.

The backend is a **FastAPI** app (`app/main.py`) that connects to user databases
via SQLAlchemy, uses **Google Gemini** for natural-language SQL and chart
generation, and stores schema metadata in a **Postgres cache database**
(`CACHE_DB_URL`).

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Startup & Shared Infrastructure](#startup--shared-infrastructure)
3. [Database Connection & Presets](#database-connection--presets)
4. [Schema Exploration](#schema-exploration)
5. [Natural Language to SQL (`/generate`)](#natural-language-to-sql-generate)
6. [Auto-Dashboard (`/gen-dashboard`)](#auto-dashboard-gen-dashboard)
7. [Streaming Dashboard (`/gen-dashboard/stream`)](#streaming-dashboard-gen-dashboardstream)
8. [Dashboard Export (`/dashboard/export`)](#dashboard-export-dashboardexport)
9. [Data Health Check (`/data-health`)](#data-health-check-data-health)
10. [SQL Optimizer (`/optimize`)](#sql-optimizer-optimize)
11. [Schema Cache](#schema-cache)
12. [AI Service (Gemini)](#ai-service-gemini)
13. [Visualization Engine](#visualization-engine)
14. [SQL Safety (Safe Mode)](#sql-safety-safe-mode)
15. [Operational Endpoints](#operational-endpoints)
16. [Configuration Reference](#configuration-reference)

---

## Architecture Overview

```
┌─────────────┐     HTTP      ┌──────────────────────────────────────────────┐
│  Frontend   │ ────────────► │  app/main.py (FastAPI routes)                │
└─────────────┘               │                                              │
                              │  models.py  — request/response validation    │
                              │  config.py  — env settings                   │
                              │  utils.py   — dialect, redaction, presets    │
                              │  sql_guard.py — read-only SQL parser           │
                              └───────┬──────────────────────────────────────┘
                                      │
          ┌───────────────────────────┼───────────────────────────┐
          ▼                           ▼                           ▼
   ┌─────────────┐            ┌─────────────┐            ┌─────────────┐
   │ DatabaseMgr │            │  AIService  │            │ CacheManager│
   │ (SQLAlchemy)│            │  (Gemini)   │            │ (Postgres)  │
   └──────┬──────┘            └──────┬──────┘            └─────────────┘
          │                          │
          ▼                          ▼
   User databases              VizService / DashboardBuilder / HealthChecker
   (PG, MySQL, Oracle, MSSQL)
```

| Module | Role |
|--------|------|
| `app/main.py` | Route handlers, CORS, static frontend serving |
| `app/models.py` | Pydantic schemas; validates `db_url`, pagination bounds, export limits |
| `app/services/database.py` | Engine pooling, schema introspection, safe identifier quoting |
| `app/services/ai.py` | Gemini client, key rotation, SQL repair, JSON schema calls |
| `app/services/cache.py` | TTL-backed schema + context cache in Postgres |
| `app/services/viz.py` | AI-generated matplotlib/seaborn charts in a sandbox |
| `app/services/dashboard.py` | 5-panel dashboard planning and parallel build |
| `app/services/health.py` | Deterministic data-quality probes (no AI) |
| `app/sql_guard.py` | Parser-based read-only SQL enforcement via sqlglot |

---

## Startup & Shared Infrastructure

**Lifespan hook** (`main.py` → `lifespan`):

1. On app start, `CacheManager.init_cache_db()` creates the `schema_cache` table
   in the cache Postgres if it does not exist.
2. Service singletons are constructed at import time:
   - `AIService` — requires at least one Gemini API key
   - `CacheManager` — pooled connections to `CACHE_DB_URL`
   - `DatabaseManager` — stateless; engines are built on demand
   - `DashboardBuilder`, `HealthChecker` — wired with the above

**CORS** allows all origins with `GET` and `POST` only. There is no
authentication; the API accepts any `db_url` the caller provides.

**Frontend serving**: `GET /` returns `frontend/index.html`; `/static/*` serves
JS/CSS with `Cache-Control: no-cache` so deploys pick up new bundles via
`APP_VERSION`.

---

## Database Connection & Presets

### Connection strings

Every request that touches a user database carries a `db_url` field. The
`_DbRequest` base model in `models.py` runs it through `resolve_db_url()`:

- **Direct URL** — used as-is (e.g. `postgresql://user:pass@host/db`).
- **Preset alias** — `preset:<dbname>` is expanded server-side against
  `CACHE_DB_URL`, swapping only the database name in the path. The browser
  never sees credentials.

### Dialect detection

`utils.get_dialect_name()` reads the URL scheme (not substring-matching the
whole string) and maps to: `postgres`, `mysql`, `oracle`, `tsql`, or `sqlite`.

### Engine pooling

`database._build_engine()` is LRU-cached (max 32 URLs). Each engine gets:

- `pool_pre_ping=True` — drops stale connections
- `pool_size=5`, `max_overflow=5`, `pool_recycle=1800` (except SQLite)
- Dialect-specific `connect_timeout` from `DB_CONNECT_TIMEOUT`

### `GET /databases`

Lists database names on the cache Postgres host:

```sql
SELECT datname FROM pg_database
WHERE datistemplate = false AND datname != 'postgres';
```

The frontend uses these names as `preset:<name>` values.

---

## Schema Exploration

### `POST /schemas` — List all tables

**Flow:**

1. `DatabaseManager.get_engine(db_url)` → pooled SQLAlchemy engine
2. `inspect(engine).get_table_names()` → list of table names
3. Returns `{"tables": [...]}`

Note: this endpoint returns table **names** only. Column metadata is fetched
separately per table.

### `POST /schemas/{table_name}` — Table details

**Flow:**

1. Verify table exists via SQLAlchemy inspector
2. Quote table name with dialect-aware quoting (`DatabaseManager.quote`)
3. `SELECT COUNT(*)` for row count
4. Fetch first 10 and last 10 rows (dialect-specific pagination):
   - **Postgres/MySQL/SQLite**: `LIMIT 10` / `LIMIT 10 OFFSET n`
   - **Oracle/MSSQL**: `OFFSET … ROWS FETCH NEXT … ROWS ONLY`
5. Return `TableDetailsResponse`: name, row count, column list, first/last previews

### `POST /schemas/{table_name}/data` — Paginated table browse

**Flow:**

1. **Whitelist** — table name must appear in `get_tables()`; prevents SQL injection
   on dynamic identifiers
2. Quote the table name
3. `COUNT(*)` for total rows
4. Fetch one page with dialect-aware SQL:
   - MSSQL adds `ORDER BY (SELECT NULL)` before `OFFSET` (required by T-SQL)
   - Oracle uses `OFFSET/FETCH`
   - Others use `LIMIT/OFFSET`
5. Return `PaginationResponse` with data, `total_rows`, `page`, `total_pages`

**Bounds** (enforced by Pydantic): `page ≥ 1`, `limit` between 1 and
`MAX_PAGE_SIZE` (default 1000).

---

## Natural Language to SQL (`/generate`)

The core feature: turn a plain-English question into SQL, run it, and return
data plus AI-generated charts.

### Request

```json
{
  "db_url": "...",
  "query": "Show top 5 customers by revenue",
  "safe_mode": true
}
```

- `query`: 1–4000 characters
- `safe_mode`: default `true` — only read-only SELECT allowed

### Internal flow

```
1. Detect dialect from db_url
2. _load_schema(db_url, dialect)
   ├── Check schema cache (hash of db_url)
   ├── On miss: fetch_universal_schema() via SQLAlchemy inspector
   └── On miss: fetch_unique_context() — AI picks categorical columns,
       samples DISTINCT values (LIMIT 10 each), caches result
3. Build system prompt with schema, context, dialect, safe/unrestricted mode
4. AIService.gemini_call() → raw SQL string
5. validate_sql_safety() — if safe_mode, sql_guard.is_read_only() must pass
6. Execute SQL:
   ├── SELECT/WITH → pd.read_sql(), return data
   └── Other (unrestricted mode) → conn.execute() in a transaction
7. On execution error → fix_sql() once (AI repair), retry (max 1 retry)
8. For SELECT results:
   ├── data_preview: first 20 rows as JSON
   ├── csv_base64: full result set as base64 CSV
   └── graphs_base64: VizService.generate_visualizations()
9. Return AnalysisResponse
```

### Self-healing

If SQL execution fails, the backend:

1. Sends the original SQL, error message, and schema to Gemini via `fix_sql()`
2. Retries execution once with the corrected SQL
3. Message indicates whether auto-correction was used

### Safe vs unrestricted mode

| `safe_mode` | Behavior |
|-------------|----------|
| `true` (default) | Only parsed read-only SELECT/WITH/UNION; writes rejected before execution |
| `false` | Any SQL Gemini generates runs; used for INSERT/UPDATE/DDL when trusted |

---

## Auto-Dashboard (`/gen-dashboard`)

Generates a **5-panel executive dashboard** without the user asking a specific
question.

### Request

```json
{ "db_url": "..." }
```

### Internal flow (`DashboardBuilder`)

```
1. _load_schema() — same cached schema + context as /generate
2. Planning call — gemini_json() with response_schema=list[ChartSpec]
   └── Prompt asks for 5 panels covering: trend, ranking, composition,
       comparison, distribution
3. For each panel (parallel, max 4 workers):
   a. validate_sql_safety(sql, safe_mode=True) — always read-only
   b. Execute SQL with pd.read_sql(chunksize=5000) — caps memory
   c. On error → fix_sql() once, retry
   d. VizService.generate_visualizations(single_chart=True)
   e. Success → DashboardChart; failure → FailedChart with reason
4. Return DashboardResponse with charts[] and failed[]
```

### Design constraints (enforced by prompt, not code)

- Single read-only SELECT per panel
- Aggregated data (GROUP BY), 2–50 rows
- Label column + numeric measure(s); no raw row dumps
- Distinct analytical angles across the five panels

### Failed panels

Panels that fail SQL validation, return no rows, or fail chart rendering are
reported in `failed[]` with a human-readable `reason`. A dashboard returning
3 of 5 charts explicitly says why the other 2 failed.

---

## Streaming Dashboard (`/gen-dashboard/stream`)

Same work as `/gen-dashboard`, delivered as **NDJSON** (one JSON object per
line) so the UI can render panels as they finish.

### Frame types

| Type | When | Payload |
|------|------|---------|
| `plan` | After planning call | Array of `{title, description}` placeholders |
| `chart` | Panel succeeds | `{index, chart: DashboardChart}` |
| `failed` | Panel fails | `{index, failed: FailedChart}` |
| `error` | Fatal (no schema, empty plan) | `{error: "..."}` |
| `done` | All panels processed | `{}` |

Panels arrive in **completion order**, not planned order. Each frame carries
`index` so the client can place charts in the planned layout.

**Headers**: `X-Accel-Buffering: no` and `Cache-Control: no-cache` prevent
proxy buffering from defeating streaming.

---

## Dashboard Export (`/dashboard/export`)

Zips charts the **browser already rendered** — the server does not regenerate
them (that would re-run every Gemini call).

### Request

```json
{
  "charts": [
    {
      "title": "Revenue by month",
      "description": "...",
      "graph_base64": "iVBORw0KGgo..."
    }
  ]
}
```

**Bounds**: 1–20 charts; each image ≤ 8 MB base64.

### Internal flow (`utils.build_charts_zip`)

1. Base64-decode each image with `validate=True`
2. Verify PNG magic bytes (`\x89PNG\r\n\x1a\n`)
3. Slugify title → safe filename stem (prevents zip-slip via `../../etc/passwd`)
4. Write `{NN}-{slug}.png` and matching `{NN}-{slug}.txt` (title + description)
5. Return `application/zip` attachment

---

## Data Health Check (`/data-health`)

Profiles database tables for common data-quality problems. **No AI calls** —
pure SQL aggregates — so it works when Gemini is rate-limited.

### Request

```json
{ "db_url": "..." }
```

### What it checks

| Finding | Severity | Detection |
|---------|----------|-----------|
| Empty table | high | `COUNT(*) = 0` |
| Column entirely null | high | All values null in sample |
| Orphaned foreign key | high | LEFT JOIN parent; child rows with no match |
| Duplicates in key-like column | high | `COUNT(DISTINCT) < COUNT(*)` on columns named email, uuid, sku, etc. (excluding FK columns) |
| 90%+ null | medium | Null rate on sample ≥ 90% |
| Single-valued column | medium | One distinct value across all non-null rows |
| Negative quantity | medium | MIN < 0 on columns named price, amount, qty, etc. |
| Implausible date | medium | Year < 1900 or > current year + 5 |
| Empty strings as null | low | `SUM(CASE WHEN col = '' …)` on string columns |
| Columns not checked | low | Tables with > 60 columns only profile first 60 |

### Internal flow (`HealthChecker.run`)

```
1. List tables (max 40 per run; rest → skipped[])
2. For each table (parallel, max 4 workers):
   a. _profile_table() — one aggregate query over a capped sample
      (200,000 rows via LIMIT/TOP/FETCH FIRST)
   b. _findings_from_profile() — compare stats against thresholds
   c. _orphan_findings() — one query per foreign key (not sampled)
3. Sort findings: high → medium → low, then by table/column
4. score = 100 − Σ(severity penalties: high=10, medium=4, low=1), floored at 0
5. Return HealthReport
```

Tables that error during profiling appear in `skipped[]` with a reason, so a
partial report never looks like a clean one.

---

## SQL Optimizer (`/optimize`)

Analyzes user-supplied SQL for syntax, logic, and performance improvements.

### Request

```json
{
  "db_url": "...",
  "query": "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
}
```

- `query`: 1–20,000 characters

### Internal flow

```
1. _load_schema(db_url, dialect, want_context=False) — schema only, no context
2. System prompt: Senior DBA role, asks for JSON output
3. gemini_call() → parse JSON:
   {
     "optimized_sql": "...",
     "explanation": "markdown...",
     "difference_score": 0-100
   }
4. Return OptimizeResponse
```

On JSON parse failure, returns the original query with an explanation that
analysis failed. Does **not** execute either query against the database.

---

## Schema Cache

Schema introspection and AI context extraction are expensive. Results are
cached in Postgres (`CACHE_DB_URL`).

### Cache key

SHA-256 hash of the full `db_url` string (`utils.get_hash`).

### Cached payload

| Column | Content |
|--------|---------|
| `schema_text` | All tables and columns from SQLAlchemy inspector |
| `context_text` | Sampled categorical values (e.g. `orders.status: pending, shipped`) |
| `dialect` | Detected dialect name |
| `updated_at` | Timestamp for TTL enforcement |

### TTL

Entries older than `SCHEMA_CACHE_TTL_HOURS` (default 24) are treated as cache
misses and refetched.

### `_load_schema()` helper

Shared by `/generate`, `/gen-dashboard`, and `/optimize`:

```
1. db_hash = sha256(db_url)
2. cached = cache_manager.get_cached_schema(db_hash)
3. If hit → return cached schema + context
4. If miss:
   a. fetch_universal_schema()
   b. fetch_unique_context() (optional, skipped for /optimize)
   c. save_cached_schema()
5. Return schema_str, context_str
```

### `POST /cache/invalidate`

Deletes the cache row for a given `db_url` hash. Use after migrations instead
of waiting for TTL expiry.

### Context extraction detail

`fetch_unique_context()`:

1. Asks Gemini to return JSON list of `{table, column}` pairs for categorical columns
2. Validates each table/column against the live schema (model hallucinations are dropped)
3. Runs `SELECT DISTINCT col FROM table WHERE col IS NOT NULL LIMIT 10` per pair
4. Joins results into a text block appended to AI prompts

---

## AI Service (Gemini)

`AIService` wraps the Google GenAI SDK.

### Key rotation

- Up to 5 API keys (`GEMINI_API_KEY_1` … `_5`), cycled on 429/quota errors
- Model is pinned to the first entry in `GEMINI_MODELS`; only downgrades after
  **all** keys are exhausted for the current model
- Thread-safe via `threading.Lock` (sync endpoints run on Starlette threadpool)

### Methods

| Method | Purpose |
|--------|---------|
| `gemini_call(system, user)` | Free-text response; strips markdown fences |
| `gemini_json(system, user, schema)` | Structured JSON via `response_schema`; used for dashboard planning |
| `validate_sql_safety(sql, safe_mode, dialect)` | Delegates to `sql_guard.is_read_only` when safe_mode is on |
| `fix_sql(original, error, schema, dialect)` | One-shot SQL repair prompt |

### Timeouts

Each Gemini HTTP call uses `AI_TIMEOUT_SECONDS` (default 120s).

---

## Visualization Engine

`VizService.generate_visualizations()` turns a DataFrame into base64 PNG charts.

### Flow

```
1. Write DataFrame to temp CSV
2. Build prompt with: user query, column names, dtypes, 3 sample rows, design rules
3. gemini_call() → Python plotting script
4. Execute script in sandboxed globals (see Security below)
5. Glob *.png from temp dir → base64 encode
6. On exec failure → one repair attempt via gemini_call(fix_prompt)
```

### Chart design rules (prompt-enforced)

- Chart type matched to data shape (line for time series, barh for rankings, etc.)
- Aggregate before plotting; cap categories at 12 (+ "Other")
- Human-readable titles, axis labels, number formatting
- `figsize=(10, 6)`, seaborn whitegrid, single palette

### Concurrency

Matplotlib holds global state. All `exec()` of generated scripts runs behind
`_PLOT_LOCK` so parallel dashboard panels serialize plotting (SQL and AI calls
still overlap).

### Sandbox

`safe_exec_globals()` pins an explicit `__builtins__` safelist (~35 names).
Blocked: `__import__`, `open`, `eval`, `exec`, `compile`, `input`, `globals`,
`vars`, `breakpoint`. Pre-imported: `pd`, `plt`, `sns`.

---

## SQL Safety (Safe Mode)

Implemented in `app/sql_guard.py` using **sqlglot** — a real SQL parser, not a
keyword substring scan.

### What passes

- Single `SELECT`, `WITH … SELECT`, `UNION`, or subquery
- Dialect-aware parsing (postgres, mysql, tsql, oracle, sqlite, etc.)

### What is rejected

| Category | Examples |
|----------|----------|
| Multi-statement | `SELECT 1; DROP TABLE users` |
| Writes in CTEs | `WITH x AS (DELETE … RETURNING *) SELECT * FROM x` |
| DDL/DML | INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, MERGE, COPY, DO |
| Host file access | `pg_read_file()`, `lo_import()`, `load_file()` |
| Shell execution | `COPY … TO PROGRAM`, `xp_cmdshell`, `sys_exec()` |
| Dialect mismatch | Postgres `::` cast or `DISTINCT ON` against non-Postgres dialect |
| Unparseable SQL | Fails closed |

### Where it applies

- `/generate` when `safe_mode: true`
- **All dashboard SQL** — always read-only, regardless of client setting
- Not applied to `/optimize` (analysis only, no execution)

---

## Operational Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Liveness probe; no DB or AI calls |
| `/version` | GET | Returns `APP_VERSION` env var (set by CI on deploy) |
| `/` | GET | Serves frontend HTML |
| `/static/*` | GET | Serves frontend assets with no-cache headers |

---

## Configuration Reference

All settings come from `.env` via `app/config.py` (pydantic-settings).

| Variable | Required | Default | Effect |
|----------|----------|---------|--------|
| `GEMINI_API_KEY_1` … `_5` | At least one | — | Gemini API keys for rotation |
| `CACHE_DB_URL` | **Yes** | — | Postgres for schema cache + preset DB host |
| `GEMINI_MODELS` | No | `gemini-3.6-flash,…` | Comma-separated model fallbacks |
| `MAX_PAGE_SIZE` | No | `1000` | Hard cap on pagination `limit` |
| `SCHEMA_CACHE_TTL_HOURS` | No | `24` | Schema cache expiry |
| `DB_CONNECT_TIMEOUT` | No | `10` | Seconds before DB connect fails |
| `AI_TIMEOUT_SECONDS` | No | `120` | Seconds before Gemini call fails |
| `APP_VERSION` | No | `dev` | Exposed at `/version`; bumps static cache busting |

---

## Supported Databases

Detected from connection URL scheme:

| URL scheme | Dialect key | Notes |
|------------|-------------|-------|
| `postgresql://`, `postgres://` | `postgres` | Primary; also used for cache and presets |
| `mysql://`, `mariadb://` | `mysql` | |
| `oracle://` | `oracle` | OFFSET/FETCH pagination |
| `mssql://` | `tsql` | Requires ORDER BY before OFFSET |
| `sqlite://` | `sqlite` | Used in tests |

---

## Error Handling & Security Conventions

- **Credential redaction** — `utils.redact()` strips `user:password` from any
  error string before it reaches the client or logs
- **Safe identifiers** — dynamic table/column names are whitelisted against the
  live schema and dialect-quoted; values use bound parameters
- **Bounded payloads** — pagination limits, dashboard row cap (5000), export
  chart/image limits, health check table/column/sample caps
- **No authentication** — anyone who can reach the API can supply any `db_url`;
  deploy behind a network boundary or auth layer for production

For the full security audit and fixes applied, see [`BACKEND_AUDIT.md`](BACKEND_AUDIT.md).

---

## Endpoint Summary

| Endpoint | AI? | Executes SQL? | Description |
|----------|-----|---------------|-------------|
| `POST /schemas` | No | No (introspection) | List tables |
| `POST /schemas/{table}` | No | Yes (COUNT, previews) | Table metadata + first/last 10 rows |
| `POST /schemas/{table}/data` | No | Yes (paginated SELECT) | Browse table data |
| `POST /generate` | Yes | Yes | NL → SQL → data + charts |
| `POST /gen-dashboard` | Yes | Yes | 5-panel auto dashboard |
| `POST /gen-dashboard/stream` | Yes | Yes | Same, streamed as NDJSON |
| `POST /dashboard/export` | No | No | Zip browser-held chart PNGs |
| `POST /data-health` | No | Yes (aggregates) | Data quality report |
| `POST /optimize` | Yes | No | SQL analysis and rewrite |
| `POST /cache/invalidate` | No | No | Drop cached schema |
| `GET /databases` | No | Yes (catalog query) | List preset database names |
| `GET /health` | No | No | Liveness |
| `GET /version` | No | No | Build id |
