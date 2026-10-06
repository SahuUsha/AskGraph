"""Dialect-aware SELECT guardrail.

Replaces the substring keyword scan that used to live in ai_service.py. That
scan blocked `SELECT * FROM updates` while letting `COPY ... TO PROGRAM` and
`pg_read_file()` through. The parser logic here was recovered from the
dialect guardrails in the old copy_of_postgres.py prototype (since deleted;
see BACKEND_AUDIT.md).
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# Expressions the given dialect cannot execute; parsing succeeds but the DB rejects.
DENYLIST = {
    "postgres": (exp.Qualify, exp.Pivot, exp.Struct),
    "mysql": (exp.Qualify, exp.Pivot, exp.Struct),
    "tsql": (exp.Qualify, exp.Struct),
    "bigquery": (exp.Pivot,),
    "snowflake": (exp.Struct,),
    "oracle": (exp.Qualify, exp.Struct),
    "sqlite": (exp.Qualify, exp.Pivot, exp.Struct),
}

# Functions that read/write the host filesystem or shell out. A SELECT wrapping
# one of these is still a SELECT to the parser, so match them by name.
DANGEROUS_FUNCS = frozenset({
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "dblink", "dblink_connect",
    "load_file", "sys_exec", "sys_eval", "xp_cmdshell",
    "utl_file", "utl_http", "dbms_lob",
})

DIALECT_ALIASES = {
    "postgresql": "postgres", "psycopg2": "postgres", "pg": "postgres",
    "mssql": "tsql", "sqlserver": "tsql", "pymysql": "mysql",
    "mariadb": "mysql", "oracledb": "oracle", "cx_oracle": "oracle",
}


def _has_pg_cast(sql_query: str) -> bool:
    return "::" in sql_query


def _has_distinct_on(parsed) -> bool:
    d = parsed.find(exp.Distinct)
    return bool(d and d.args.get("on"))


def _uses_dangerous_func(parsed) -> bool:
    for node in parsed.find_all(exp.Anonymous, exp.Func):
        name = (node.sql_name() or "").lower()
        if name in DANGEROUS_FUNCS:
            return True
        this = node.args.get("this")
        if isinstance(this, str) and this.lower() in DANGEROUS_FUNCS:
            return True
    return False


def is_read_only(sql_query: str, dialect: str = "postgres") -> bool:
    """True only if sql_query is a single, executable, read-only statement.

    Anything unparseable, multi-statement, non-SELECT, or touching the
    filesystem/shell is rejected. Fails closed.
    """
    if not sql_query or not sql_query.strip():
        return False

    dialect = DIALECT_ALIASES.get(dialect.lower(), dialect.lower())
    if dialect not in DENYLIST:
        dialect = "postgres"  # unknown driver: use the strictest table we have

    try:
        statements = sqlglot.parse(sql_query, dialect=dialect)
    except ParseError:
        return False

    # `SELECT 1; DROP TABLE users` parses as two statements. Allow exactly one.
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return False

    parsed = statements[0]

    # COPY/DO/CALL/CREATE and friends parse as Command or their own node types.
    if not isinstance(parsed, (exp.Select, exp.With, exp.Union, exp.Subquery)):
        return False

    if isinstance(parsed, exp.With) and not isinstance(
        parsed.this, (exp.Select, exp.Union)
    ):
        return False

    # A CTE body can hold INSERT/UPDATE/DELETE ... RETURNING in Postgres.
    for writer in (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
                   exp.Create, exp.Command, exp.Merge):
        if parsed.find(writer):
            return False

    if _uses_dangerous_func(parsed):
        return False

    for forbidden in DENYLIST[dialect]:
        if parsed.find(forbidden):
            return False

    if dialect != "postgres":
        if _has_distinct_on(parsed) or _has_pg_cast(sql_query):
            return False

    return True
