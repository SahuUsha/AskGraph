"""NL→SQL benchmark for SQLAI: which LLM answers questions correctly?

Each model gets the same schema and system prompt the app uses (build_sql_prompt),
its SQL is executed read-only against a Postgres seeded from initial_migration/csvs,
and the rows are compared with a reference query's rows.

    python SQLAI/benchmark/run_benchmark.py \
        --db-url postgresql://user@localhost:5432/sqlai_bench \
        --models openai/gpt-oss-20b,nvidia/nemotron-3-super-120b-a12b --runs 2

Uses NVIDIA_API_KEY / LLM_BASE_URL from the repo-root .env. The database is seeded
on first run and is otherwise only read.
"""

import argparse
import datetime
import decimal
import itertools
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))

from sqlalchemy import create_engine, text  # noqa: E402

from ai_service import AIService, build_sql_prompt  # noqa: E402
from database_manager import DatabaseManager  # noqa: E402
from utils import get_dialect_name  # noqa: E402

CSV_DIR = os.path.join(ROOT, "initial_migration", "csvs")
DDL = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY, customer_name TEXT, email TEXT,
    city TEXT, country TEXT, loyalty_points INTEGER);
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY, product_name TEXT, category TEXT,
    price NUMERIC(10, 2), stock_quantity INTEGER, supplier_id TEXT);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers(customer_id),
    product_id TEXT REFERENCES products(product_id), order_date DATE,
    quantity INTEGER, total_price NUMERIC(10, 2));
"""
NUMERIC_TEXT = re.compile(r"^-?\d+(\.\d+)?$")


def seed(engine):
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(DDL)
        for table in ("customers", "products", "orders"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            if cur.fetchone()[0] == 0:
                with open(os.path.join(CSV_DIR, f"{table}.csv")) as f:
                    cur.copy_expert(f"COPY {table} FROM STDIN WITH CSV HEADER", f)
        raw.commit()
    finally:
        raw.close()


def run_sql(engine, sql):
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text("SET LOCAL statement_timeout = '10s'"))
        result = conn.execute(text(sql))
        rows = [tuple(_norm(v) for v in row) for row in result]
        conn.rollback()
    return rows


def _round(v):
    # Half-up like SQL ROUND(); float round() would turn 170.785 into 170.78.
    return float(decimal.Decimal(str(v)).quantize(decimal.Decimal("0.01"), decimal.ROUND_HALF_UP))


def _norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float, decimal.Decimal)):
        return _round(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    s = str(v).strip()
    return _round(s) if NUMERIC_TEXT.match(s) else s


def matches(gold, got, ordered):
    """Same rows as gold, allowing reordered or extra columns."""
    if len(gold) != len(got):
        return False
    if not gold:
        return True
    gold_cols, got_cols = list(zip(*gold)), list(zip(*got))
    key = (lambda c: list(c)) if ordered else (lambda c: sorted(map(repr, c)))
    candidates = [[j for j, g in enumerate(got_cols) if key(g) == key(col)] for col in gold_cols]
    for mapping in itertools.islice(itertools.product(*candidates), 1000):
        if len(set(mapping)) < len(mapping):
            continue
        projected = [tuple(row[j] for j in mapping) for row in got]
        if (projected == gold) if ordered else (Counter(projected) == Counter(gold)):
            return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db-url", default=os.getenv("BENCH_DB_URL"), required=not os.getenv("BENCH_DB_URL"))
    p.add_argument("--models", default=os.getenv("LLM_MODEL"), help="comma-separated model ids")
    p.add_argument("--runs", type=int, default=1, help="repeats per question, to average out sampling noise")
    p.add_argument("--workers", type=int, default=3, help="concurrent requests; the free tier rate-limits bursts")
    p.add_argument("--out", help="write per-attempt results as JSON")
    args = p.parse_args()

    engine = create_engine(args.db_url)
    seed(engine)
    questions = json.load(open(os.path.join(HERE, "questions.json")))
    gold = {q["id"]: run_sql(engine, q["gold_sql"]) for q in questions}
    prompt = build_sql_prompt(get_dialect_name(args.db_url), DatabaseManager.fetch_universal_schema(args.db_url), True)
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    def attempt(job):
        model, run, q = job
        svc = AIService()
        svc.model_name = model
        # The free NVIDIA tier answers bursts with 429/503; back off rather than
        # scoring the provider's capacity as a wrong answer.
        svc.client = svc.client.with_options(max_retries=8)
        out = dict(model=model, run=run, id=q["id"], ok=False, sql="", error=None, api_error=None)
        t = time.time()
        try:
            out["sql"] = svc.complete(prompt, q["question"])
        except Exception as e:
            out["api_error"] = str(e)[:200]
        out["latency"] = time.time() - t
        if out["api_error"]:
            return out
        try:
            out["ok"] = matches(gold[q["id"]], run_sql(engine, out["sql"]), q["ordered"])
        except Exception as e:
            out["error"] = str(e).splitlines()[0][:200]
        return out

    def logged(job):
        r = attempt(job)
        status = "ok" if r["ok"] else ("API" if r["api_error"] else "SQL error" if r["error"] else "wrong")
        print(f"  {r['model']:48} Q{r['id']:<2} run {r['run'] + 1}: {status:9} {r['latency']:5.1f}s", flush=True)
        return r

    # Interleaved so one slow model can't hold every worker.
    jobs = [(m, r, q) for r in range(args.runs) for q in questions for m in models]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(logged, jobs))

    by_model = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)

    total = len(questions) * args.runs
    print(f"\n| Model | Correct (of {total}) | Wrong rows | SQL error | API failure | Median latency | p90 latency |")
    print("|---|---|---|---|---|---|---|")
    ranked = sorted(by_model.items(), key=lambda kv: (-sum(r["ok"] for r in kv[1]),
                                                      statistics.median(r["latency"] for r in kv[1])))
    for model, rs in ranked:
        answered = [r for r in rs if not r["api_error"]]
        lat = sorted(r["latency"] for r in answered) or [float("nan")]
        print(f"| `{model}` | {sum(r['ok'] for r in rs)} | "
              f"{sum(not r['ok'] and not r['error'] for r in answered)} | {sum(bool(r['error']) for r in answered)} | "
              f"{len(rs) - len(answered)} | {statistics.median(lat):.1f}s | {lat[int(0.9 * (len(lat) - 1))]:.1f}s |")

    print("\nPer question (correct runs):\n")
    print("| # | Skill | " + " | ".join(f"`{m}`" for m, _ in ranked) + " |")
    print("|---|---|" + "---|" * len(ranked))
    for q in questions:
        cells = [f"{sum(r['ok'] for r in rs if r['id'] == q['id'])}/{args.runs}" for _, rs in ranked]
        print(f"| {q['id']} | {q['skill']} | " + " | ".join(cells) + " |")

    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
