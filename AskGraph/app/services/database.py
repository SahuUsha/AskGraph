import json
from functools import lru_cache
from typing import List

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from ..config import settings
from ..utils import get_dialect_name, redact

# Drivers that accept a connect_timeout in connect_args, by dialect.
_CONNECT_TIMEOUT_ARG = {
    "postgres": "connect_timeout",
    "mysql": "connect_timeout",
    "tsql": "timeout",
}


@lru_cache(maxsize=32)
def _build_engine(db_url: str) -> Engine:
    """One pooled Engine per URL.

    create_engine was called per request and never disposed, so every request
    leaked a connection pool until the target DB refused new connections.
    ponytail: LRU of 32 engines; evicted ones are GC'd with their pools. Swap
    for an explicit registry with dispose() if you need deterministic teardown.
    """
    dialect = get_dialect_name(db_url)
    connect_args = {}
    if arg := _CONNECT_TIMEOUT_ARG.get(dialect):
        connect_args[arg] = settings.DB_CONNECT_TIMEOUT

    kwargs = {
        "connect_args": connect_args,
        "pool_pre_ping": True,  # drop connections the DB closed while idle
    }
    # SQLite uses SingletonThreadPool/StaticPool, which reject queue sizing.
    if dialect != "sqlite":
        kwargs.update(pool_size=5, max_overflow=5, pool_recycle=1800)

    return create_engine(db_url, **kwargs)


class DatabaseManager:
    @staticmethod
    def get_engine(db_url: str) -> Engine:
        try:
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
            return _build_engine(db_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Database Connection Error: {redact(e)}")

    @staticmethod
    def get_tables(db_url: str) -> List[str]:
        try:
            inspector = inspect(DatabaseManager.get_engine(db_url))
            return inspector.get_table_names()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Database Error: {redact(e)}")

    @staticmethod
    def quote(db_url: str, identifier: str) -> str:
        """Quote a table/column name for this dialect.

        Identifiers can't be bound as parameters, so anything interpolated into
        SQL must be both whitelisted against the live schema and quoted.
        """
        return DatabaseManager.get_engine(db_url).dialect.identifier_preparer.quote(identifier)

    @staticmethod
    def fetch_universal_schema(db_url: str) -> str:
        try:
            inspector = inspect(DatabaseManager.get_engine(db_url))
            output = []
            for table in inspector.get_table_names():
                output.append(f"\nTable: {table}")
                col_strs = [f"{c['name']} ({c['type']})" for c in inspector.get_columns(table)]
                output.append(f"Columns: {', '.join(col_strs)}")
            return "\n".join(output)
        except Exception as e:
            print(f"❌ Schema Fetch Error: {redact(e)}")
            return ""

    @staticmethod
    def fetch_unique_context(db_url: str, schema_str: str, ai_service, limit: int = 10) -> str:
        if not schema_str:
            return ""
        prompt = (
            "Analyze schema. Find categorical columns. Return JSON list: "
            '[{"table": "t", "column": "c"}]\nSchema: ' + schema_str
        )
        try:
            resp = ai_service.gemini_call(prompt, "Extract context")
            cols = json.loads(resp)
            engine = DatabaseManager.get_engine(db_url)
            inspector = inspect(engine)

            # The model picks these names; verify each against the live schema
            # before it reaches a query string.
            real_tables = set(inspector.get_table_names())
            lines = []
            with engine.connect() as conn:
                for item in cols:
                    table, column = item.get("table"), item.get("column")
                    if table not in real_tables:
                        continue
                    if column not in {c["name"] for c in inspector.get_columns(table)}:
                        continue
                    try:
                        qt = DatabaseManager.quote(db_url, table)
                        qc = DatabaseManager.quote(db_url, column)
                        # LIMIT in SQL, not a Python slice — this used to scan
                        # every distinct value in the table and throw them away.
                        query = text(
                            f"SELECT DISTINCT {qc} FROM {qt} WHERE {qc} IS NOT NULL LIMIT :lim"
                        )
                        rows = conn.execute(query, {"lim": limit}).fetchall()
                        vals = [str(r[0]) for r in rows if r[0] is not None]
                        if vals:
                            lines.append(f"{table}.{column}: {', '.join(vals)}")
                    except Exception:
                        continue
            return "\n".join(lines)
        except Exception:
            return ""

    @staticmethod
    def get_table_details(db_url: str, table_name: str, dialect_name: str):
        try:
            engine = DatabaseManager.get_engine(db_url)
            inspector = inspect(engine)
            if not inspector.has_table(table_name):
                raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")

            col_names = [c["name"] for c in inspector.get_columns(table_name)]
            qt = DatabaseManager.quote(db_url, table_name)

            with engine.connect() as conn:
                row_count = conn.execute(text(f"SELECT COUNT(*) FROM {qt}")).scalar() or 0
                offset = max(0, row_count - 10)

                if dialect_name in ("oracle", "tsql"):
                    q_first = f"SELECT * FROM {qt} OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY"
                    q_last = f"SELECT * FROM {qt} OFFSET {offset} ROWS FETCH NEXT 10 ROWS ONLY"
                else:
                    # LIMIT/OFFSET covers postgres, mysql, sqlite. Unknown
                    # dialects used to fall through to a full table scan.
                    q_first = f"SELECT * FROM {qt} LIMIT 10"
                    q_last = f"SELECT * FROM {qt} LIMIT 10 OFFSET {offset}"

                df_first = pd.read_sql(text(q_first), conn)
                df_last = pd.read_sql(text(q_last), conn)

            return {
                "table_name": table_name,
                "row_count": row_count,
                "columns": col_names,
                "first_10": json.loads(df_first.to_json(orient="records", date_format="iso")),
                "last_10": json.loads(df_last.to_json(orient="records", date_format="iso")),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database Error: {redact(e)}")
