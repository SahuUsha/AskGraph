import base64
import io
import json
import math
import os
import tempfile

import pandas as pd
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.staticfiles import StaticFiles
from sqlalchemy import text

from .config import settings
from .models import (
    AnalysisResponse, ChartExportRequest, DBConnectionRequest, DashboardResponse,
    HealthReport, OptimizeRequest, OptimizeResponse, PaginationRequest,
    PaginationResponse, TableDetailsResponse, UserRequest,
)
from .services.ai import create_ai_service
from .services.cache import CacheManager
from .services.dashboard import DashboardBuilder
from .services.database import DatabaseManager
from .services.health import HealthChecker
from .services.viz import VizService
from .utils import build_charts_zip, get_dialect_name, get_hash, redact

# --- Configuration ---
# No load_dotenv() — pydantic-settings already reads .env in config.py.
CACHE_DB_URL = settings.CACHE_DB_URL

# --- Services ---
ai_service = create_ai_service(
    api_key=settings.NVIDIA_API_KEY,
    base_url=settings.LLM_BASE_URL,
    model=settings.LLM_MODEL,
    timeout_seconds=settings.AI_TIMEOUT_SECONDS,
)
cache_manager = CacheManager(
    cache_db_url=CACHE_DB_URL,
    ttl_hours=settings.SCHEMA_CACHE_TTL_HOURS,
    connect_timeout=settings.DB_CONNECT_TIMEOUT,
)
db_manager = DatabaseManager()
dashboard_builder = DashboardBuilder(ai_service=ai_service, db_manager=db_manager)
health_checker = HealthChecker(db_manager=db_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache_manager.init_cache_db()
    yield


app = FastAPI(title="Multi-DB SQL Agent", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # allow_credentials with a "*" origin is rejected by browsers anyway, and
    # this API is token-free, so nothing needs cookies forwarded.
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# main.py lives in app/, so the frontend is one level up at the repo root.
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
APP_VERSION = os.environ.get("APP_VERSION", "dev")
# Browsers cache /static/* aggressively; bump this each deploy via APP_VERSION.
NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


class NoCacheStaticFiles(StaticFiles):
    """Serve frontend assets without letting the browser reuse a stale bundle."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


@app.get("/health")
def health():
    """Liveness only — no DB or AI calls, so it stays cheap and honest."""
    return {"status": "ok"}


@app.get("/version")
def version():
    """Deployed build id — use after CI to confirm the live site picked up a push."""
    return {"version": APP_VERSION}


@app.get("/")
def serve_frontend():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "index.html"),
        headers=NO_CACHE,
    )


app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")


def _load_schema(db_url: str, dialect: str, want_context: bool = True):
    """Cached schema + context for a target DB, refetching on miss.

    Identical preamble in /generate, /gen-dashboard and /optimize.
    """
    db_hash = get_hash(db_url)
    cached = cache_manager.get_cached_schema(db_hash)
    if cached:
        return cached["schema"], cached["context"] or ""

    schema_str = db_manager.fetch_universal_schema(db_url)
    if not schema_str:
        return "", ""

    context_str = db_manager.fetch_unique_context(db_url, schema_str, ai_service) if want_context else ""
    cache_manager.save_cached_schema(db_hash, schema_str, context_str, dialect)
    return schema_str, context_str


@app.post("/schemas")
def get_all_schemas(req: DBConnectionRequest):
    return {"tables": db_manager.get_tables(req.db_url)}


@app.post("/cache/invalidate")
def invalidate_cache(req: DBConnectionRequest):
    """Force a schema refetch after a migration, instead of waiting out the TTL."""
    return {"invalidated": cache_manager.invalidate(get_hash(req.db_url))}


@app.get("/databases")
def get_neon_databases():
    """Names only. The frontend selects one as 'preset:<name>' and the server
    expands it — the connection string never reaches the browser."""
    try:
        engine = db_manager.get_engine(CACHE_DB_URL)
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datname != 'postgres';"
            )).fetchall()
        return {"databases": [row[0] for row in result]}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not list databases: {redact(e)}")


@app.post("/schemas/{table_name}", response_model=TableDetailsResponse)
def get_table_details(table_name: str, req: DBConnectionRequest):
    dialect = get_dialect_name(req.db_url)
    return TableDetailsResponse(**db_manager.get_table_details(req.db_url, table_name, dialect))


@app.post("/schemas/{table_name}/data", response_model=PaginationResponse)
def get_table_data(table_name: str, req: PaginationRequest):
    """Table data with server-side pagination. page/limit are bounded by the
    request model, so no caller can ask for the whole table."""
    try:
        # Table names cannot be bound as parameters — whitelist against the
        # live schema, then quote for the dialect.
        if table_name not in db_manager.get_tables(req.db_url):
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

        engine = db_manager.get_engine(req.db_url)
        dialect = get_dialect_name(req.db_url)
        qt = db_manager.quote(req.db_url, table_name)

        with engine.connect() as conn:
            total_rows = conn.execute(text(f"SELECT COUNT(*) FROM {qt}")).scalar() or 0
            offset = (req.page - 1) * req.limit
            total_pages = math.ceil(total_rows / req.limit) if total_rows > 0 else 1

            if dialect == "tsql":
                # MSSQL needs an ORDER BY before OFFSET; (SELECT NULL) is the
                # standard no-op sort when no key is known.
                data_sql = (
                    f"SELECT * FROM {qt} ORDER BY (SELECT NULL) "
                    f"OFFSET {offset} ROWS FETCH NEXT {req.limit} ROWS ONLY"
                )
            elif dialect == "oracle":
                data_sql = (
                    f"SELECT * FROM {qt} "
                    f"OFFSET {offset} ROWS FETCH NEXT {req.limit} ROWS ONLY"
                )
            else:
                data_sql = f"SELECT * FROM {qt} LIMIT {req.limit} OFFSET {offset}"

            df = pd.read_sql(text(data_sql), conn)

        return PaginationResponse(
            data=json.loads(df.to_json(orient="records", date_format="iso")),
            total_rows=total_rows,
            page=req.page,
            total_pages=total_pages,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error fetching data: {redact(e)}")


@app.post("/generate", response_model=AnalysisResponse)
def generate_response(req: UserRequest):
    dialect = get_dialect_name(req.db_url)
    schema_str, context_str = _load_schema(req.db_url, dialect)
    if not schema_str:
        return AnalysisResponse(sql_query="", error="Could not fetch database schema.")

    mode_instructions = "STRICTLY READ-ONLY. SELECT only." if req.safe_mode else "UNRESTRICTED MODE."
    system_prompt = f"""
    You are a {dialect.upper()} SQL Expert.
    Schema: {schema_str}
    Context: {context_str}
    MODE: {mode_instructions}
    Rules:
    - Return strictly raw SQL. No markdown.
    - Return exactly ONE statement. Never separate statements with ';'.
    - Handle date comparisons using dialect-specific functions.
    """

    sql_query = ai_service.gemini_call(system_prompt, req.query)
    if not sql_query:
        return AnalysisResponse(sql_query="", error="AI failed to generate SQL.")

    attempts = 0
    max_retries = 1
    last_error = None

    while attempts <= max_retries:
        if not ai_service.validate_sql_safety(sql_query, req.safe_mode, dialect):
            return AnalysisResponse(
                sql_query=sql_query,
                error="Safe Mode Violation: only a single read-only statement is allowed.",
            )

        try:
            engine = db_manager.get_engine(req.db_url)
            # In safe mode the guardrail already proved this is a SELECT.
            is_select = req.safe_mode or sql_query.strip().lower().startswith(("select", "with"))

            if is_select:
                with engine.connect() as conn:
                    df = pd.read_sql(text(sql_query), conn)

                if df.empty:
                    return AnalysisResponse(sql_query=sql_query, message="Query executed but returned no data.")

                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                csv_base64 = base64.b64encode(csv_buffer.getvalue().encode("utf-8")).decode("utf-8")

                with tempfile.TemporaryDirectory() as temp_dir:
                    graphs = VizService.generate_visualizations(df, req.query, ai_service, temp_dir)

                return AnalysisResponse(
                    sql_query=sql_query,
                    message="Data retrieved successfully." if attempts == 0
                    else "Data retrieved successfully after auto-correction.",
                    data_preview=json.loads(df.head(20).to_json(orient="records", date_format="iso")),
                    graphs_base64=graphs,
                    csv_base64=csv_base64,
                )

            with engine.begin() as conn:
                conn.execute(text(sql_query))
            return AnalysisResponse(
                sql_query=sql_query,
                message="Command executed successfully. Database updated." if attempts == 0
                else "Command executed successfully after auto-correction.",
                data_preview=None,
                graphs_base64=[],
            )
        except Exception as e:
            last_error = redact(e)
            attempts += 1
            if attempts > max_retries:
                break
            print(f"🔄 Retrying SQL correction... Attempt {attempts}. Error: {last_error}")
            sql_query = ai_service.fix_sql(sql_query, last_error, schema_str, dialect)
            if not sql_query:
                break

    return AnalysisResponse(sql_query=sql_query, error=f"SQL Execution Error: {last_error}")


@app.post("/gen-dashboard", response_model=DashboardResponse)
def generate_dashboard(req: DBConnectionRequest):
    dialect = get_dialect_name(req.db_url)
    schema_str, context_str = _load_schema(req.db_url, dialect)
    if not schema_str:
        return DashboardResponse(charts=[], error="Could not fetch database schema.")
    return dashboard_builder.build(req.db_url, dialect, schema_str, context_str)


@app.post("/gen-dashboard/stream")
def stream_dashboard(req: DBConnectionRequest):
    """Same dashboard, streamed as NDJSON so the first panel renders as soon as
    it is built instead of waiting on the slowest of five.

    One JSON object per line: a `plan` frame naming the panels, then a `chart`
    or `failed` frame per panel in completion order, then `done`. Each frame
    carries the panel's planned `index` so the client can still lay them out in
    the planned order. /gen-dashboard keeps returning the whole thing at once.
    """
    dialect = get_dialect_name(req.db_url)
    schema_str, context_str = _load_schema(req.db_url, dialect)

    def frames():
        if not schema_str:
            yield json.dumps({"type": "error", "error": "Could not fetch database schema."}) + "\n"
            return

        for kind, index, payload in dashboard_builder.iter_panels(
            req.db_url, dialect, schema_str, context_str
        ):
            if kind == "plan":
                yield json.dumps({"type": "plan", "panels": [
                    {"title": (spec.get("title") or "").strip() or "Untitled chart",
                     "description": (spec.get("description") or "").strip()}
                    for spec in payload
                ]}) + "\n"
            elif kind == "error":
                yield json.dumps({"type": "error", "error": payload}) + "\n"
            elif kind == "chart":
                yield json.dumps({"type": "chart", "index": index,
                                  "chart": payload.model_dump()}) + "\n"
            else:
                yield json.dumps({"type": "failed", "index": index,
                                  "failed": payload.model_dump()}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(
        frames(),
        media_type="application/x-ndjson",
        # Streaming dies silently behind a buffering proxy; Caddy and nginx both
        # honour this. Without it the client waits for the whole body anyway.
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.post("/dashboard/export")
def export_dashboard(req: ChartExportRequest):
    """Zip the charts the browser already holds — one .png and one .txt each.

    The client posts its rendered charts back rather than the server rebuilding
    them: regenerating would re-run every Gemini call, and caching them server
    side would mean holding dashboards in memory for a button most users never
    press.
    """
    try:
        archive = build_charts_zip(req.charts)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="askgraph-dashboard.zip"'},
    )


@app.post("/data-health", response_model=HealthReport)
def check_data_health(req: DBConnectionRequest):
    """What's wrong with the data. No question, no AI — just probes.

    Named /data-health, not /health-check, so it can't be mistaken for the
    liveness route above.
    """
    return health_checker.run(req.db_url, get_dialect_name(req.db_url))


@app.post("/optimize", response_model=OptimizeResponse)
def optimize_sql(req: OptimizeRequest):
    dialect = get_dialect_name(req.db_url)
    schema_str, _ = _load_schema(req.db_url, dialect, want_context=False)
    if not schema_str:
        raise HTTPException(status_code=400, detail="Could not fetch database schema.")

    system_prompt = f"""
    You are a Senior {dialect.upper()} DBA and SQL Performance Expert.
    Database Schema:
    {schema_str}

    Your Task:
    Analyze the user's input SQL query.
    1. Check for syntax errors.
    2. Check for logical errors.
    3. Optimize for performance.
    4. Ensure it is valid {dialect.upper()} SQL.

    Output strictly valid JSON:
    {{
        "optimized_sql": "THE_REFINED_SQL_QUERY",
        "explanation": "Brief markdown explanation.",
        "difference_score": 0
    }}
    """

    try:
        result = json.loads(ai_service.gemini_call(system_prompt, f"Input SQL: {req.query}"))
        return OptimizeResponse(
            original_query=req.query,
            optimized_query=result.get("optimized_sql", req.query),
            explanation=result.get("explanation", "Analysis complete."),
            difference_score=result.get("difference_score", 0),
        )
    except json.JSONDecodeError:
        return OptimizeResponse(
            original_query=req.query,
            optimized_query=req.query,
            explanation="AI Analysis failed to format response correctly. Returning original.",
            difference_score=0,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization Error: {redact(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
