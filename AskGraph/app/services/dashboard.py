"""Dashboard planning and panel building.

Split out of main.py: the endpoint is now a thin caller and the panel logic
(plan -> SQL -> repair -> chart) is testable without an HTTP request.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from sqlalchemy import text

from ..models import ChartSpec, DashboardChart, DashboardResponse, FailedChart
from ..utils import redact
from .viz import VizService

CHART_COUNT = 5

# A chart is a summary. Past this, no plot is readable — and the rows would be
# pulled into memory first.
ROW_CAP = 5000

# Concurrency is capped below CHART_COUNT so a dashboard doesn't burst the
# Gemini rate limit and trigger key rotation on every panel at once.
MAX_WORKERS = 4


def _plan_prompt(dialect: str, schema_str: str, context_str: str) -> str:
    return f"""
    You are a senior analytics engineer writing {dialect.upper()} SQL. Design a
    {CHART_COUNT}-panel executive dashboard for the database below.

    Schema:
    {schema_str}

    Known column values:
    {context_str}

    Each panel must answer a question a decision-maker would actually ask
    ("which regions are shrinking?"), never a structural one ("how many rows
    are in orders?").

    COVER DIFFERENT ANGLES — do not return {CHART_COUNT} variations of one idea.
    Across the set, include at minimum:
      1. a trend over time (grouped by month or day, ordered chronologically)
      2. a top-N ranking of one category by a meaningful measure
      3. a breakdown/composition across a categorical dimension
      4. a comparison between two segments, periods, or cohorts
      5. one distribution, outlier, or ratio that would not already be obvious

    SQL REQUIREMENTS (a panel that breaks these is dropped):
    - A single read-only SELECT. No semicolons, no writing CTE, no DDL.
    - ALWAYS aggregate — GROUP BY with COUNT/SUM/AVG. Never select raw rows.
    - Return between 2 and 50 rows. One row cannot be charted; hundreds cannot
      be read. Use LIMIT on rankings and ORDER BY on everything.
    - Return exactly the columns the chart needs: one label/date column and one
      or two numeric measures. No id columns, no SELECT *.
    - Alias every aggregate to a readable name (revenue, not sum_1).
    - Use only tables and columns present in the schema above. Do not invent
      names. Respect real column types; cast text dates before date maths.
    - For time series, truncate to a period (e.g. DATE_TRUNC in Postgres) and
      order by that period ascending.

    'title' is a short business headline. 'description' is one sentence naming
    the insight the panel reveals.
    """


class DashboardBuilder:
    def __init__(self, ai_service, db_manager):
        self.ai = ai_service
        self.db = db_manager

    def _run_sql(self, db_url: str, sql: str, dialect: str, schema_str: str):
        """Execute one panel query, repairing it once if it errors.

        /generate has always self-healed broken SQL via fix_sql; the dashboard
        used to drop the panel instead. Same helper, same single retry.
        """
        engine = self.db.get_engine(db_url)

        for attempt in range(2):
            # Model-written SQL is never reviewed by a human before it runs, so
            # it is held to the read-only guardrail regardless of safe_mode.
            if not self.ai.validate_sql_safety(sql, True, dialect):
                return None, sql, "Query was not a single read-only statement."
            try:
                with engine.connect() as conn:
                    # chunksize caps what is materialised, rather than reading
                    # a million rows and trimming afterwards.
                    chunks = pd.read_sql(text(sql), conn, chunksize=ROW_CAP)
                    df = next(iter(chunks), None)
                if df is None or df.empty:
                    return None, sql, "Query returned no rows."
                return df, sql, None
            except Exception as e:
                if attempt == 1:
                    return None, sql, f"SQL failed: {redact(e)}"
                repaired = self.ai.fix_sql(sql, redact(e), schema_str, dialect)
                if not repaired:
                    return None, sql, f"SQL failed: {redact(e)}"
                sql = repaired

        return None, sql, "SQL failed."

    def build_panel(self, spec: dict, db_url: str, dialect: str, schema_str: str):
        """Plan entry -> (DashboardChart, None) or (None, FailedChart)."""
        title = (spec.get("title") or "").strip() or "Untitled chart"
        desc = (spec.get("description") or "").strip()
        sql = (spec.get("sql_query") or "").strip()

        if not sql:
            return None, FailedChart(title=title, reason="Plan contained no SQL.")

        try:
            df, used_sql, err = self._run_sql(db_url, sql, dialect, schema_str)
            if err:
                return None, FailedChart(title=title, reason=err)

            with tempfile.TemporaryDirectory() as temp_dir:
                graphs = VizService.generate_visualizations(
                    df, f"{title}. {desc}", self.ai, temp_dir, single_chart=True
                )
            if not graphs:
                return None, FailedChart(title=title, reason="Chart script failed to render.")

            return DashboardChart(
                title=title, description=desc, graph_base64=graphs[0], sql_query=used_sql
            ), None
        except Exception as e:
            return None, FailedChart(title=title, reason=redact(e))

    def iter_panels(self, db_url: str, dialect: str, schema_str: str, context_str: str):
        """Yields ("plan"|"chart"|"failed"|"error", index, payload) as work lands.

        Panels arrive in completion order, not planned order — that is the point:
        the caller can show the first chart without waiting on the slowest one.
        `index` is the panel's position in the plan, so a streaming caller can
        still place it where it was planned.
        """
        plan = self.ai.gemini_json(
            _plan_prompt(dialect, schema_str, context_str),
            f"Design the {CHART_COUNT}-panel dashboard.",
            response_schema=list[ChartSpec],
        )
        if not plan:
            yield "error", None, "Failed to generate a dashboard plan."
            return

        specs = [p if isinstance(p, dict) else p.model_dump() for p in plan[:CHART_COUNT]]
        if not specs:
            yield "error", None, "Dashboard plan was empty."
            return

        yield "plan", None, specs

        # Each panel costs 1-2 Gemini round trips; serially that was 30-60s of
        # wall clock. AI calls and SQL overlap here — only the matplotlib exec
        # serialises, behind the lock in VizService.
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(specs))) as pool:
            futures = {
                pool.submit(self.build_panel, spec, db_url, dialect, schema_str): i
                for i, spec in enumerate(specs)
            }
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    chart, failed = fut.result()
                except Exception as e:
                    chart, failed = None, FailedChart(
                        title=specs[i].get("title", "Unknown"), reason=redact(e)
                    )
                if chart is not None:
                    yield "chart", i, chart
                else:
                    print(f"Dashboard panel dropped — {failed.title}: {failed.reason}")
                    yield "failed", i, failed

    def build(self, db_url: str, dialect: str, schema_str: str, context_str: str) -> DashboardResponse:
        """Drains iter_panels into one response, for the non-streaming endpoint."""
        charts, failures = {}, {}

        for kind, index, payload in self.iter_panels(db_url, dialect, schema_str, context_str):
            if kind == "error":
                return DashboardResponse(charts=[], error=payload)
            if kind == "chart":
                charts[index] = payload
            elif kind == "failed":
                failures[index] = payload

        # Keep the planned order, not completion order.
        built = [charts[i] for i in sorted(charts)]
        failed = [failures[i] for i in sorted(failures)]

        error = None
        if not built:
            error = "No panels could be built. " + (failed[0].reason if failed else "")

        return DashboardResponse(charts=built, failed=failed, error=error)
