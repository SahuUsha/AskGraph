"""Data health checks — what's wrong with a database, without being asked.

Every other surface in this app needs the user to already know the question.
This one runs a fixed set of probes and reports what it finds.

Deliberately AI-free: the findings are counts compared against thresholds, so
the page still works when Gemini is rate-limited, and it costs one query per
table plus one per foreign key.
"""

import datetime
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from sqlalchemy import inspect, text

from ..models import HealthFinding, HealthReport, SkippedTable
from ..utils import redact

# Rows scanned per table. Rates computed from a sample are labelled as such;
# a duplicate or a bad date found in the sample is a real one either way.
# ponytail: flat cap, no TABLESAMPLE. Raise it if false negatives show up on
# tables whose junk hides past row 200k.
SAMPLE_ROWS = 200_000

# A 400-column table would build a SELECT with 1200 aggregates in it.
MAX_COLUMNS = 60

# ponytail: bounded so one request can't fire 500 queries at a warehouse.
# Page the remainder if anyone actually points this at a schema that big.
MAX_TABLES = 40

MAX_WORKERS = 4

# Below this, a table is too small for "90% null" to mean anything.
MIN_ROWS_FOR_RATES = 20

NULL_RATE_THRESHOLD = 0.9

# Columns whose name implies uniqueness. Duplicates in these are usually a bug
# rather than a design choice — no constraint exists to say so.
# Deliberately excludes a bare "id": a name ending in _id means "reference to",
# not "unique", and foreign keys are supposed to repeat.
_KEY_NAME_HINTS = ("uuid", "guid", "email", "code", "slug", "sku", "isbn")

# Columns whose name implies a non-negative quantity.
_NONNEG_NAME_HINTS = ("price", "amount", "amt", "qty", "quantity", "count",
                      "total", "cost", "fee", "balance", "age", "stock")

_SEVERITY_PENALTY = {"high": 10, "medium": 4, "low": 1}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_NUMERIC_TYPES = (int, float, Decimal)
_DATE_TYPES = (datetime.date, datetime.datetime)


def _py_type(col):
    """The Python type behind a SQLAlchemy column, or None if the dialect
    can't say. Unknown types (json, arrays, blobs) get counted but not
    compared — COUNT(DISTINCT) on a Postgres json column is an error, not a
    finding."""
    try:
        return col["type"].python_type
    except (NotImplementedError, AttributeError):
        return None


def _sampled_source(quoted_table: str, dialect: str) -> str:
    """A subquery capping the rows the aggregates scan."""
    if dialect == "tsql":
        return f"(SELECT TOP {SAMPLE_ROWS} * FROM {quoted_table}) s"
    if dialect == "oracle":
        return f"(SELECT * FROM {quoted_table} FETCH FIRST {SAMPLE_ROWS} ROWS ONLY) s"
    return f"(SELECT * FROM {quoted_table} LIMIT {SAMPLE_ROWS}) s"


def _name_hits(column_name: str, hints) -> bool:
    """Whole-word match on the name or its last underscore-separated part.

    A substring test flagged `region` for containing `gio`-shaped hints and
    `customer_id` for containing `id`.
    """
    lowered = column_name.lower()
    return any(lowered == h or lowered.endswith(f"_{h}") for h in hints)


def _year_of(value):
    """Year from a date, datetime, or an ISO-ish string.

    sqlite and several drivers hand dates back as text, so reading .year alone
    silently skipped the check on exactly the databases most likely to hold a
    placeholder date.
    """
    year = getattr(value, "year", None)
    if year is not None:
        return year
    match = re.match(r"\s*(\d{4})-\d{2}-\d{2}", str(value))
    return int(match.group(1)) if match else None


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


class HealthChecker:
    def __init__(self, db_manager):
        self.db = db_manager

    # --- probes -------------------------------------------------------

    def _profile_table(self, db_url: str, dialect: str, table: str, columns: list):
        """One aggregate query covering every column of one table."""
        qt = self.db.quote(db_url, table)
        selects = ["COUNT(*) AS n_rows"]
        plan = []

        for i, col in enumerate(columns):
            name, ptype = col["name"], _py_type(col)
            qc = self.db.quote(db_url, name)
            selects.append(f"COUNT({qc}) AS c{i}_n")
            plan.append((i, name, ptype))

            if ptype is None:
                continue  # countable, but not safely comparable
            selects.append(f"COUNT(DISTINCT {qc}) AS c{i}_d")
            if ptype is str:
                selects.append(f"SUM(CASE WHEN {qc} = '' THEN 1 ELSE 0 END) AS c{i}_e")
            elif ptype in _NUMERIC_TYPES:
                selects.append(f"MIN({qc}) AS c{i}_min")
            elif ptype in _DATE_TYPES:
                selects.append(f"MIN({qc}) AS c{i}_min")
                selects.append(f"MAX({qc}) AS c{i}_max")

        sql = f"SELECT {', '.join(selects)} FROM {_sampled_source(qt, dialect)}"
        engine = self.db.get_engine(db_url)
        with engine.connect() as conn:
            row = conn.execute(text(sql)).mappings().first()

        # Oracle upper-cases unquoted aliases.
        return {k.lower(): v for k, v in dict(row).items()}, plan

    def _findings_from_profile(self, table: str, stats: dict, plan: list, sampled: bool,
                               fk_columns: frozenset = frozenset()):
        scanned = int(stats.get("n_rows") or 0)
        out = []

        if scanned == 0:
            return [HealthFinding(
                severity="high", table=table, column=None, issue="Empty table",
                detail=f"{table} has no rows at all.",
            )]

        scope = f"the first {scanned:,} rows" if sampled else f"all {scanned:,} rows"
        this_year = datetime.date.today().year

        for i, name, ptype in plan:
            non_null = stats.get(f"c{i}_n")
            if non_null is None:
                continue
            non_null = int(non_null)
            distinct = stats.get(f"c{i}_d")
            distinct = int(distinct) if distinct is not None else None

            if non_null == 0:
                out.append(HealthFinding(
                    severity="high", table=table, column=name, issue="Column is entirely null",
                    detail=f"{table}.{name} is null in {scope}.",
                ))
                continue

            null_rate = 1 - (non_null / scanned)
            if scanned >= MIN_ROWS_FOR_RATES and null_rate >= NULL_RATE_THRESHOLD:
                out.append(HealthFinding(
                    severity="medium", table=table, column=name, issue="Mostly null",
                    detail=f"{table}.{name} is {null_rate:.0%} null across {scope}.",
                ))

            if distinct is not None and distinct == 1 and non_null >= MIN_ROWS_FOR_RATES:
                out.append(HealthFinding(
                    severity="medium", table=table, column=name, issue="Single value",
                    detail=f"{table}.{name} holds the same value in all {non_null:,} "
                           f"non-null rows — it carries no information.",
                ))

            if (distinct is not None and distinct < non_null
                    and name not in fk_columns
                    and _name_hits(name, _KEY_NAME_HINTS)):
                out.append(HealthFinding(
                    severity="high", table=table, column=name, issue="Duplicate values in a key-like column",
                    detail=f"{table}.{name} has {_count(non_null - distinct, 'duplicate')} "
                           f"({distinct:,} distinct in {non_null:,} rows) and no unique "
                           f"constraint stopping them.",
                ))

            empties = stats.get(f"c{i}_e")
            if empties:
                out.append(HealthFinding(
                    severity="low", table=table, column=name, issue="Empty strings used as null",
                    detail=f"{table}.{name} has {_count(int(empties), 'empty-string row')} "
                           f"alongside its nulls — two ways to say 'missing'.",
                ))

            low = stats.get(f"c{i}_min")
            if ptype in _NUMERIC_TYPES and low is not None and low < 0 \
                    and _name_hits(name, _NONNEG_NAME_HINTS):
                out.append(HealthFinding(
                    severity="medium", table=table, column=name, issue="Negative quantity",
                    detail=f"{table}.{name} goes as low as {low}, which its name says "
                           f"should not happen.",
                ))

            if ptype in _DATE_TYPES:
                high = stats.get(f"c{i}_max")
                for label, value in (("an earliest", low), ("a latest", high)):
                    year = _year_of(value) if value is not None else None
                    if year is not None and (year < 1900 or year > this_year + 5):
                        out.append(HealthFinding(
                            severity="medium", table=table, column=name, issue="Implausible date",
                            detail=f"{table}.{name} has {label} value of {value} — "
                                   f"usually a placeholder or a bad parse.",
                        ))

        return out

    def _orphan_findings(self, db_url: str, table: str, fks: list, known_tables: set):
        """Child rows whose parent doesn't exist. Not sampled — a broken
        reference anywhere in the table is the finding."""
        engine = self.db.get_engine(db_url)
        out = []

        for fk in fks:
            parent = fk.get("referred_table")
            child_cols = fk.get("constrained_columns") or []
            parent_cols = fk.get("referred_columns") or []
            if parent not in known_tables or not child_cols or len(child_cols) != len(parent_cols):
                continue

            qc_table = self.db.quote(db_url, table)
            qp_table = self.db.quote(db_url, parent)
            on = " AND ".join(
                f"c.{self.db.quote(db_url, a)} = p.{self.db.quote(db_url, b)}"
                for a, b in zip(child_cols, parent_cols)
            )
            not_null = " AND ".join(
                f"c.{self.db.quote(db_url, a)} IS NOT NULL" for a in child_cols
            )
            first_parent = self.db.quote(db_url, parent_cols[0])
            sql = (f"SELECT COUNT(*) FROM {qc_table} c "
                   f"LEFT JOIN {qp_table} p ON {on} "
                   f"WHERE {not_null} AND p.{first_parent} IS NULL")

            try:
                with engine.connect() as conn:
                    orphans = conn.execute(text(sql)).scalar() or 0
            except Exception:
                continue  # an unjoinable FK is a schema quirk, not a finding

            if orphans:
                out.append(HealthFinding(
                    severity="high", table=table, column=", ".join(child_cols),
                    issue="Orphaned foreign key",
                    detail=f"{_count(orphans, 'row')} in {table} "
                           f"{'points' if orphans == 1 else 'point'} at a {parent} row "
                           f"that does not exist.",
                ))

        return out

    def _check_table(self, db_url: str, dialect: str, table: str, columns: list,
                     fks: list, known_tables: set):
        findings = []
        stats, plan = self._profile_table(db_url, dialect, table, columns[:MAX_COLUMNS])
        fk_columns = frozenset(
            c for fk in fks for c in (fk.get("constrained_columns") or [])
        )
        findings += self._findings_from_profile(
            table, stats, plan,
            sampled=int(stats.get("n_rows") or 0) >= SAMPLE_ROWS,
            fk_columns=fk_columns,
        )
        if int(stats.get("n_rows") or 0) > 0:
            findings += self._orphan_findings(db_url, table, fks, known_tables)
        if len(columns) > MAX_COLUMNS:
            findings.append(HealthFinding(
                severity="low", table=table, column=None, issue="Columns not checked",
                detail=f"{table} has {len(columns)} columns; only the first "
                       f"{MAX_COLUMNS} were profiled.",
            ))
        return findings

    # --- entry point --------------------------------------------------

    def run(self, db_url: str, dialect: str) -> HealthReport:
        try:
            inspector = inspect(self.db.get_engine(db_url))
            all_tables = inspector.get_table_names()
        except Exception as e:
            return HealthReport(findings=[], error=f"Could not read the schema: {redact(e)}")

        if not all_tables:
            return HealthReport(findings=[], error="This database has no tables.")

        known = set(all_tables)
        tables = all_tables[:MAX_TABLES]
        skipped = [SkippedTable(table=t, reason=f"Over the {MAX_TABLES}-table limit for one run.")
                   for t in all_tables[MAX_TABLES:]]

        jobs = {}
        for table in tables:
            try:
                jobs[table] = (inspector.get_columns(table), inspector.get_foreign_keys(table))
            except Exception as e:
                skipped.append(SkippedTable(table=table, reason=redact(e)))

        findings = []
        checked = 0
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(jobs)))) as pool:
            futures = {
                pool.submit(self._check_table, db_url, dialect, t, cols, fks, known): t
                for t, (cols, fks) in jobs.items()
            }
            for fut in as_completed(futures):
                table = futures[fut]
                try:
                    findings += fut.result()
                    checked += 1
                except Exception as e:
                    skipped.append(SkippedTable(table=table, reason=redact(e)))

        # Worst first, then stable by table/column so repeat runs match.
        findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], f.table, f.column or ""))

        score = max(0, 100 - sum(_SEVERITY_PENALTY[f.severity] for f in findings))
        return HealthReport(
            findings=findings,
            score=score,
            tables_checked=checked,
            skipped=skipped,
        )
