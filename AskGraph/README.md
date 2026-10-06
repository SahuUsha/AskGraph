# Multi-DB SQL AI Agent 🤖

A powerful AI-powered FastAPI application that translates natural language into SQL, executes queries against multiple database dialects (PostgreSQL, MySQL, Oracle, SQL Server), generates intelligent visualizations, and features self-healing capabilities for failed queries.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)

---

## 🌟 Features

- **🧠 Natural Language to SQL**: Convert plain English questions into optimized SQL queries using Google's Gemini AI
- **🔄 Self-Healing Queries**: Automatic retry mechanism with AI-powered error correction
- **📊 Smart Visualizations**: AI-generated charts and graphs using Matplotlib/Seaborn
- **🗄️ Multi-Database Support**: PostgreSQL, MySQL, Oracle, SQL Server with automatic dialect detection
- **🔒 Safe Mode**: Parser-enforced read-only guardrail (not a keyword blocklist)
- **⚡ Schema Caching**: TTL-backed schema cache in Postgres, with manual invalidation
- **📄 Server-Side Pagination**: Bounded, dialect-aware pagination
- **🎨 Modern Frontend**: Beautiful, responsive UI with real-time query execution
- **📈 Auto-Dashboard**: 5 AI-curated panels, built in parallel and **streamed as each one finishes** — the first chart appears without waiting for the slowest, downloadable individually or all at once as a zip
- **🩺 Data Health Check**: Finds nulls, orphaned foreign keys, duplicate keys and impossible dates — no question required, and no AI call
- **🔧 SQL Optimizer**: Analyze and optimize SQL queries for better performance

---

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- Database connection (PostgreSQL, MySQL, Oracle, or SQL Server)
- Google Gemini API key ([Get one here](https://ai.google.dev/))

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd SQLai
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**

Create a `.env` file in the root directory:
```env
GEMINI_API_KEY_1=your_gemini_api_key_here
GEMINI_API_KEY_2=your_second_key_optional
GEMINI_API_KEY_3=your_third_key_optional
GEMINI_API_KEY_4=your_fourth_key_optional
GEMINI_API_KEY_5=your_fifth_key_optional
CACHE_DB_URL=postgresql://user:password@host:port/dbname?sslmode=require
```

At least one of `GEMINI_API_KEY_1`–`GEMINI_API_KEY_5` is required. Extra keys are used for rotation.

5. **Run the application**

**Option A — Docker (recommended)**
```bash
docker compose up --build
```

**Option B — Local Python**
```bash
uvicorn app.main:app --reload
```

The application will be available at `http://localhost:8000`

### Running the tests

```bash
python tests/test_backend.py
```

23 checks covering the SQL guardrail, the chart sandbox, credential redaction,
the dashboard builder and its streaming order, the zip export (including zip-slip
titles), and the data health probes. No database or API key
required — the health checks run against a throwaway sqlite database seeded
with one of each defect.

---

## 🏗️ Architecture

### Project Structure

```
AskGraph/
├── app/
│   ├── main.py             # FastAPI app and route handlers
│   ├── config.py           # Settings (pydantic-settings, reads .env)
│   ├── models.py           # Request/response schemas
│   ├── utils.py            # Dialect detection, redaction, preset URLs
│   ├── sql_guard.py        # Parser-based read-only SQL guardrail
│   └── services/
│       ├── ai.py           # Gemini client, key rotation, SQL repair
│       ├── cache.py        # Pooled schema cache with TTL
│       ├── database.py     # Engines, schema inspection, safe identifiers
│       ├── dashboard.py    # Dashboard planning and parallel panel building
│       ├── health.py        # Deterministic data-quality probes
│       └── viz.py          # Sandboxed chart-script generation
├── tests/
│   └── test_backend.py     # Runnable regression checks
├── docs/
│   └── api-examples.md     # cURL examples per endpoint
├── frontend/
│   ├── index.html          # Main UI
│   ├── app.js              # Frontend logic
│   └── styles.css          # Styling
├── deploy/                 # Production compose + Caddy fragment
├── requirements.txt        # Python dependencies
├── Dockerfile              # Container image definition
├── docker-compose.yml      # Compose service (uses .env)
├── BACKEND_AUDIT.md        # Security/performance audit and fixes
└── .env                    # Environment variables (not committed)
```

The app is served as `app.main:app`.

### Technology Stack

**Backend:**
- FastAPI - Modern, fast web framework
- SQLAlchemy - Database ORM and query builder
- Pandas - Data manipulation and analysis
- Google Gemini AI - Natural language processing
- Matplotlib/Seaborn - Data visualization

**Frontend:**
- Vanilla JavaScript - Interactive UI
- CSS3 - Modern styling with animations
- HTML5 - Semantic markup

**Databases:**
- PostgreSQL
- MySQL
- Oracle
- SQL Server

---

## 📡 API Endpoints

### Base URL
`http://localhost:8000`

### 1. Get All Schemas
**`POST /schemas`**

Fetches the database schema (tables and columns) for a given connection string.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname"
}
```

**Response:**
```json
{
  "tables": {
    "users": [
      {"name": "id", "type": "INTEGER"},
      {"name": "username", "type": "VARCHAR(50)"}
    ]
  }
}
```

---

### 2. Get Table Details
**`POST /schemas/{table_name}`**

Provides metadata, row count, and preview (first 10 and last 10 rows) for a specific table.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname"
}
```

**Response:**
```json
{
  "table_name": "users",
  "row_count": 1500,
  "columns": ["id", "username", "email"],
  "first_10": [...],
  "last_10": [...]
}
```

---

### 3. Get Paginated Table Data
**`POST /schemas/{table_name}/data`** ⭐ NEW

Server-side pagination with dialect-aware LIMIT/OFFSET handling.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname",
  "page": 1,
  "limit": 100
}
```

**Response:**
```json
{
  "data": [...],
  "total_rows": 1500,
  "page": 1,
  "total_pages": 15,
  "error": null
}
```

---

### 4. Generate & Execute Analysis
**`POST /generate`**

Translates natural language into SQL, executes it, and returns data with AI-generated visualizations. Features **self-healing** with automatic retry on failure.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname",
  "query": "Show me the top 5 users by spend in the last month",
  "safe_mode": true
}
```

**Response:**
```json
{
  "sql_query": "SELECT user_id, SUM(amount) as total FROM orders...",
  "message": "Data retrieved successfully.",
  "data_preview": [...],
  "graphs_base64": ["base64_encoded_image..."],
  "csv_base64": "base64_encoded_csv...",
  "error": null
}
```

---

### 5. Generate Dashboard
**`POST /gen-dashboard`**

Plans 5 panels covering distinct analytical angles (trend, ranking,
composition, comparison, distribution), then builds them **in parallel**.
The plan is requested with a response schema, so it can't be lost to a stray
prose preamble. Broken panel SQL is repaired once via the same self-healing
path `/generate` uses.

Panels that still fail are reported in `failed` with a reason rather than
silently disappearing — a dashboard that returns 3 charts now tells you why it
isn't 5.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname"
}
```

**Response:**
```json
{
  "charts": [
    {
      "title": "Revenue peaked in Q3",
      "description": "Month-over-month revenue trends",
      "graph_base64": "...",
      "sql_query": "SELECT DATE_TRUNC('month', created_at) AS month, ..."
    }
  ],
  "failed": [
    {"title": "Churn by cohort", "reason": "Query returned no rows."}
  ],
  "error": null
}
```

---

### 6. Stream the Dashboard
**`POST /gen-dashboard/stream`**

The same work as `/gen-dashboard`, delivered as **NDJSON** — one JSON object per
line, flushed as it is produced — so the first chart renders in about the time
one panel takes instead of the time all five take.

Frame order: a `plan` frame as soon as the planning call returns, then a `chart`
or `failed` frame per panel **in completion order**, then `done`. Every panel
frame carries its planned `index`, so the client renders titled placeholders
from the `plan` frame and swaps each one in place — panels finish out of order
but still land where they were planned.

```
{"type":"plan","panels":[{"title":"Revenue by month","description":"..."}, ...]}
{"type":"chart","index":2,"chart":{"title":"...","graph_base64":"...","sql_query":"..."}}
{"type":"failed","index":3,"failed":{"title":"Churn by cohort","reason":"Query returned no rows."}}
{"type":"done"}
```

A frame can be split across TCP chunks, so a client must buffer the partial
trailing line rather than parsing each chunk as if it were whole.

`/gen-dashboard` is unchanged and still returns the whole dashboard in one
response — both endpoints run the same builder.

---

### 7. Export Dashboard Charts
**`POST /dashboard/export`**

Returns a zip: one `.png` and one matching `.txt` (title, blank line,
description) per chart, numbered in dashboard order.

```
01-revenue-peaked-in-q3.png
01-revenue-peaked-in-q3.txt
02-orders-by-region.png
02-orders-by-region.txt
```

The **browser posts back the charts it already has** rather than the server
rebuilding them — regenerating would re-run every Gemini call, and caching
dashboards server-side would hold them in memory for a button most users never
press. The cost is one upload of images the client already holds.

That makes the payload untrusted, so each image is base64-decoded with
`validate=True` and checked for the PNG magic bytes (400 otherwise), the list
and per-image sizes are bounded, and **titles are slugified into the zip entry
names**. A chart titled `../../etc/passwd` becomes `01-etc-passwd.png` — a
model-written title must never become a path for whoever extracts the archive.
The numeric prefix also keeps two panels with the same title from collapsing
into one entry.

**Request:**
```json
{
  "charts": [
    {"title": "Revenue by month", "description": "...", "graph_base64": "iVBORw0KGgo..."}
  ]
}
```

**Response:** `application/zip` as an attachment.

---

### 8. Data Health Check
**`POST /data-health`**

The one surface that doesn't need you to know the question. Runs a fixed set of
probes across every table and ranks what it finds.

Deliberately **AI-free** — findings are counts compared against thresholds, so
the page still works when Gemini is rate-limited. Cost is one aggregate query
per table plus one per foreign key, and column stats are read from a capped
sample so a large table can't hang the request.

What it looks for:

| Finding | Severity |
|---|---|
| Empty table, column entirely null | high |
| Orphaned foreign key (child rows with no parent) | high |
| Duplicates in a uniqueness-implying column with no constraint | high |
| 90%+ null, single-valued column, negative quantity, implausible date | medium |
| Empty strings used alongside nulls | low |

`score` is 100 minus a penalty per finding, floored at 0. Tables that couldn't
be profiled are listed in `skipped` with a reason, so a partial report never
looks like a clean one.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname"
}
```

**Response:**
```json
{
  "findings": [
    {
      "severity": "high",
      "table": "orders",
      "column": "customer_id",
      "issue": "Orphaned foreign key",
      "detail": "3 rows in orders point at a customers row that does not exist."
    }
  ],
  "score": 70,
  "tables_checked": 12,
  "skipped": [],
  "error": null
}
```

---

### 9. Optimize SQL
**`POST /optimize`**

Analyzes SQL queries for performance bottlenecks and logical errors.

**Request:**
```json
{
  "db_url": "postgresql://user:password@host:port/dbname",
  "query": "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
}
```

**Response:**
```json
{
  "original_query": "SELECT * FROM users...",
  "optimized_query": "SELECT u.id, u.username FROM users u...",
  "explanation": "Replaced subquery with JOIN for better performance...",
  "difference_score": 45
}
```

---

### 10. Liveness Check
**`GET /health`**

Liveness probe. Touches neither the database nor Gemini, so it stays cheap and
never reports healthy-but-broken.

```json
{"status": "ok"}
```

---

### 11. List Preset Databases
**`GET /databases`**

Returns the database **names** available on the cache host. The frontend
dropdown sends the chosen name back as `"db_url": "preset:<name>"`, which the
server expands against `CACHE_DB_URL`. The connection string never reaches the
browser.

```json
{"databases": ["neondb", "analytics"]}
```

---

### 12. Invalidate Schema Cache
**`POST /cache/invalidate`**

Forces a schema refetch after a migration instead of waiting out the TTL.

```json
{"invalidated": true}
```

---

## 💡 Usage Examples

### Example 1: Natural Language Query
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "db_url": "postgresql://user:pass@localhost:5432/mydb",
    "query": "What are the top 10 products by revenue this year?",
    "safe_mode": true
  }'
```

### Example 2: Browse Table with Pagination
```bash
curl -X POST http://localhost:8000/schemas/orders/data \
  -H "Content-Type: application/json" \
  -d '{
    "db_url": "postgresql://user:pass@localhost:5432/mydb",
    "page": 2,
    "limit": 50
  }'
```

### Example 3: Generate Dashboard
```bash
curl -X POST http://localhost:8000/gen-dashboard \
  -H "Content-Type: application/json" \
  -d '{
    "db_url": "postgresql://user:pass@localhost:5432/mydb"
  }'
```

---

## 🎨 Frontend Features

The modern web interface includes:

- **Schema Explorer**: Browse database tables and columns with pagination
- **AI Query Interface**: Natural language to SQL with real-time execution
- **Visualization Gallery**: Auto-generated charts and graphs
- **SQL Optimizer**: Analyze and improve query performance
- **Dashboard Generator**: One-click comprehensive insights
- **Dark Mode UI**: Modern, responsive design with smooth animations
- **Export Options**: Download results as CSV

Access the frontend at `http://localhost:8000`

---

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY_1` … `GEMINI_API_KEY_5` | Gemini API keys, used for rotation | **at least one required** |
| `CACHE_DB_URL` | Postgres URL for the schema cache | **required** — no default |
| `GEMINI_MODELS` | Comma-separated models, best first | `gemini-3.6-flash,…` |
| `MAX_PAGE_SIZE` | Hard cap on pagination `limit` | `1000` |
| `SCHEMA_CACHE_TTL_HOURS` | Age at which a cached schema is refetched | `24` |
| `DB_CONNECT_TIMEOUT` | Seconds before a DB connect gives up | `10` |
| `AI_TIMEOUT_SECONDS` | Seconds before a Gemini call gives up | `120` |

`CACHE_DB_URL` deliberately has no fallback: a committed default is a committed
password, and it lets a missing env var silently point production at a dev
database.

### Safe Mode

With `safe_mode: true`, generated SQL must **parse** (via `sqlglot`) as a single
read-only statement. This is a real parse, not a keyword scan, so it correctly
allows `SELECT * FROM updates` while rejecting:

- statement stacking — `SELECT 1; DROP TABLE users`
- shell execution — `COPY (SELECT 1) TO PROGRAM '…'`
- host file access — `pg_read_file()`, `lo_import()`, `dblink()`
- writes hidden in CTEs — `WITH x AS (DELETE … RETURNING *) SELECT * FROM x`
- any DDL, or anything that fails to parse (fails closed)

Dashboard SQL is **always** held to this guardrail, regardless of `safe_mode`,
because it is model-written and never reviewed by a human before it runs.

---

## 🛡️ Security

- **Parser-based read-only enforcement** — see Safe Mode above
- **Sandboxed chart scripts** — generated plotting code runs with a pinned
  `__builtins__` safelist; `__import__`, `open`, `eval`, `exec` are shadowed
- **Credential redaction** — driver errors embed the DSN, so every error string
  reaching a client or a log is stripped of `user:password`
- **No credentials in the browser** — the database dropdown uses server-side
  `preset:<name>` aliases
- **Safe identifiers** — table and column names are whitelisted against the live
  schema and dialect-quoted; values are always bound parameters
- **Bounded requests** — pagination limits, dashboard row caps, and connect
  timeouts on every database and AI call

> ⚠️ **The API currently has no authentication** and accepts an arbitrary
> `db_url`, so anyone who can reach it can make the server connect outward.
> Put it behind auth or a network boundary before exposing it. See
> [`BACKEND_AUDIT.md`](BACKEND_AUDIT.md) for the full audit.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📝 License

This project is licensed under the MIT License.

---

## 🙏 Acknowledgments

- Google Gemini AI for natural language processing
- FastAPI for the excellent web framework
- Neon Postgres for serverless database caching
- The open-source community

---

## 📧 Support

For issues, questions, or suggestions, please open an issue on GitHub.

---

**Built with ❤️ using FastAPI and Google Gemini AI**
