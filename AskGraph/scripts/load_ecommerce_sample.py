#!/usr/bin/env python3
"""Load the Kaggle UK online retail dataset into the public sample Neon DB.

Usage:
  SAMPLE_DB_URL=postgresql://... python scripts/load_ecommerce_sample.py
  SAMPLE_DB_URL=... python scripts/load_ecommerce_sample.py /path/to/data.csv

Tables created: customers, products, orders (replaces any prior sample tables).
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
KAGGLE_DATASET = "carrie1/ecommerce-data"


def _url() -> str:
    url = os.environ.get("SAMPLE_DB_URL", "").strip()
    if not url:
        sys.exit("Set SAMPLE_DB_URL to the sample database connection string.")
    return url


def _csv_path(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    try:
        import kagglehub
    except ImportError:
        sys.exit("Install kagglehub: pip install kagglehub")
    return Path(kagglehub.dataset_download(KAGGLE_DATASET)) / "data.csv"


def _prepare(csv: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(csv, encoding="latin-1")
    df["InvoiceNo"] = df["InvoiceNo"].astype(str)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], dayfirst=False, errors="coerce")
    df["Description"] = df["Description"].fillna("").astype(str).str.slice(0, 500)
    df["Country"] = df["Country"].fillna("Unknown").astype(str)
    df["StockCode"] = df["StockCode"].astype(str)

    customers = (
        df.dropna(subset=["CustomerID"])
        .groupby("CustomerID", as_index=False)["Country"]
        .first()
        .rename(columns={"CustomerID": "customer_id", "Country": "country"})
    )
    customers["customer_id"] = customers["customer_id"].astype(int)

    products = (
        df.groupby("StockCode", as_index=False)
        .agg(description=("Description", "first"), unit_price=("UnitPrice", "median"))
        .rename(columns={"StockCode": "stock_code"})
    )
    products["unit_price"] = products["unit_price"].round(2)

    orders = df.rename(columns={
        "InvoiceNo": "invoice_no",
        "StockCode": "stock_code",
        "CustomerID": "customer_id",
        "Quantity": "quantity",
        "InvoiceDate": "invoice_date",
        "UnitPrice": "unit_price",
        "Country": "country",
    })[["invoice_no", "stock_code", "customer_id", "quantity", "invoice_date", "unit_price", "country"]]
    orders["customer_id"] = orders["customer_id"].astype("Int64")

    return customers, products, orders


def _copy(cur, table: str, df: pd.DataFrame, columns: list[str]) -> None:
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cols = ", ".join(columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)


def load(csv: Path) -> None:
    customers, products, orders = _prepare(csv)
    conn = psycopg2.connect(_url())
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET search_path TO public")
        cur.execute("DROP TABLE IF EXISTS orders CASCADE")
        cur.execute("DROP TABLE IF EXISTS products CASCADE")
        cur.execute("DROP TABLE IF EXISTS customers CASCADE")

        cur.execute("""
            CREATE TABLE customers (
                customer_id INTEGER PRIMARY KEY,
                country TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE products (
                stock_code TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                unit_price NUMERIC(10, 2) NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE orders (
                id SERIAL PRIMARY KEY,
                invoice_no TEXT NOT NULL,
                stock_code TEXT NOT NULL REFERENCES products(stock_code),
                customer_id INTEGER REFERENCES customers(customer_id),
                quantity INTEGER NOT NULL,
                invoice_date TIMESTAMP NOT NULL,
                unit_price NUMERIC(10, 2) NOT NULL,
                country TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX orders_invoice_no_idx ON orders (invoice_no)")
        cur.execute("CREATE INDEX orders_customer_id_idx ON orders (customer_id)")
        cur.execute("CREATE INDEX orders_invoice_date_idx ON orders (invoice_date)")

        _copy(cur, "customers", customers, ["customer_id", "country"])
        _copy(cur, "products", products, ["stock_code", "description", "unit_price"])
        _copy(cur, "orders", orders, [
            "invoice_no", "stock_code", "customer_id", "quantity", "invoice_date", "unit_price", "country",
        ])

    conn.close()
    print(
        f"Loaded {len(customers):,} customers, {len(products):,} products, "
        f"{len(orders):,} order lines from {csv.name}"
    )


def main() -> None:
    csv = _csv_path(sys.argv[1] if len(sys.argv) > 1 else None)
    if not csv.is_file():
        sys.exit(f"CSV not found: {csv}")
    load(csv)


if __name__ == "__main__":
    main()
