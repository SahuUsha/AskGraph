#!/usr/bin/env python3
"""Capture or restore the public sample Neon database.

Usage:
  SAMPLE_DB_URL=postgresql://... python scripts/sample_db.py capture
  SAMPLE_DB_URL=postgresql://... python scripts/sample_db.py restore

Reload from Kaggle (preferred for resets):
  SAMPLE_DB_URL=... python scripts/load_ecommerce_sample.py

The baseline lives in data/sample_db_baseline.sql (gitignored; UK retail dataset).
Restore reloads customers, products, orders from that dump.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data" / "sample_db_baseline.sql"


def _url() -> str:
    url = os.environ.get("SAMPLE_DB_URL", "").strip()
    if not url:
        sys.exit("Set SAMPLE_DB_URL to the sample database connection string.")
    return url


def _parts(url: str):
    p = urlparse(url)
    if p.scheme not in ("postgresql", "postgres"):
        sys.exit("SAMPLE_DB_URL must be a PostgreSQL URL.")
    db = (p.path or "").lstrip("/") or "neondb"
    return p, db


def capture() -> None:
    p, db = _parts(_url())
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if p.password:
        env["PGPASSWORD"] = p.password
    cmd = [
        "pg_dump",
        "-h", p.hostname or "",
        "-p", str(p.port or 5432),
        "-U", p.username or "",
        "-d", db,
        "--schema=public",
        "--no-owner",
        "--no-privileges",
        "--clean",
        "--if-exists",
        "-f", str(BASELINE),
        "-t", "customers",
        "-t", "orders",
        "-t", "products",
    ]
    subprocess.run(cmd, env=env, check=True)
    _strip_psql_meta(BASELINE)
    print(f"Wrote baseline to {BASELINE} ({BASELINE.stat().st_size:,} bytes)")


def _strip_psql_meta(path: Path) -> None:
    """pg_dump 18 emits \\restrict lines that older psql builds reject."""
    lines = [
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.startswith("\\restrict") and not ln.startswith("\\unrestrict")
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def restore() -> None:
    if not BASELINE.is_file():
        sys.exit(f"Missing baseline: {BASELINE}. Run capture first.")

    p, db = _parts(_url())
    env = os.environ.copy()
    if p.password:
        env["PGPASSWORD"] = p.password
    subprocess.run(
        [
            "psql",
            "-h", p.hostname or "",
            "-p", str(p.port or 5432),
            "-U", p.username or "",
            "-d", db,
            "-v", "ON_ERROR_STOP=1",
            "-f", str(BASELINE),
        ],
        env=env,
        check=True,
    )
    print(f"Restored sample database from {BASELINE.name}")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("capture", "restore"):
        sys.exit(f"Usage: {sys.argv[0]} capture|restore")
    {"capture": capture, "restore": restore}[sys.argv[1]]()


if __name__ == "__main__":
    main()
