"""
Pipeline: PostgreSQL → MongoDB
Extracts tables from PostgreSQL, transforms rows, inserts into MongoDB.
"""

import datetime
import decimal
import uuid
from typing import Any, Dict

from sqlalchemy import create_engine, text
import pymongo

from .base import BasePipeline, extract_sql_schema


def _bson_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _bson_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bson_value(item) for item in value]
    return str(value)


def _rename_map(columns, src_to_tgt: Dict[str, str]) -> Dict[str, str]:
    """Map real column names onto the plan. Empty means the plan names missed, so copy all columns."""
    by_lower = {name.lower(): target for name, target in src_to_tgt.items()}
    rename = {}
    for column in columns:
        if column in src_to_tgt:
            rename[column] = src_to_tgt[column]
        elif column.lower() in by_lower:
            rename[column] = by_lower[column.lower()]
    return rename


def _row_to_doc(columns, row, rename: Dict[str, str]) -> Dict[str, Any]:
    doc = {}
    for col_name, value in zip(columns, row):
        if rename and col_name not in rename:
            continue
        doc[rename.get(col_name, col_name)] = _bson_value(value)
    return doc


class PostgresToMongoPipeline(BasePipeline):
    source_type = "postgresql"
    target_type = "mongodb"

    def test_source_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            engine = create_engine(config["connection_url"])
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            engine.dispose()
            return {"success": True, "message": "PostgreSQL connection successful"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def test_target_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            client = pymongo.MongoClient(config["connection_url"], serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            client.close()
            return {"success": True, "message": "MongoDB connection successful"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def extract_schema(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return extract_sql_schema(config["connection_url"])

    def execute(
        self,
        source_config: Dict[str, Any],
        target_config: Dict[str, Any],
        plan: Dict[str, Any],
        on_progress=None,
    ) -> Dict[str, Any]:
        mappings = plan.get("collections") or plan.get("tables") or []
        total = len(mappings)
        if on_progress:
            on_progress(0, total, "Connecting to PostgreSQL and MongoDB")

        engine = create_engine(
            source_config["connection_url"],
            connect_args={"connect_timeout": 15},
            pool_pre_ping=True,
        )
        client = pymongo.MongoClient(
            target_config["connection_url"],
            serverSelectionTimeoutMS=15000,
            connectTimeoutMS=15000,
        )
        client.admin.command("ping")
        database_name = (target_config.get("database") or "").strip() or "migrated_db"
        db = client[database_name]
        print(f"[step] execute | connected | tables={total} | mongo_db={database_name}", flush=True)

        results = {"tables_migrated": [], "errors": [], "total_rows": 0}

        try:
            for i, mapping in enumerate(mappings):
                source_table = mapping.get("source")
                target_coll = mapping.get("target") or source_table
                if not source_table:
                    results["errors"].append({"table": f"item {i + 1}", "error": "Plan item has no source table."})
                    continue

                copied = 0
                try:
                    if on_progress:
                        on_progress(i, total, f"Reading {source_table}")
                    print(f"[step] execute | table {i + 1}/{total} | reading {source_table} -> {target_coll}", flush=True)

                    field_maps = mapping.get("field_mappings") or []
                    src_to_tgt = {}
                    for fm in field_maps:
                        s_field = fm.get("source_field") or fm.get("source") or fm.get("source_column")
                        t_field = fm.get("target_field") or fm.get("target") or fm.get("target_column")
                        if s_field and t_field:
                            src_to_tgt[str(s_field)] = str(t_field)

                    coll = db[target_coll]
                    coll.drop()
                    with engine.connect() as conn:
                        result = conn.execution_options(stream_results=True).execute(
                            text(f'SELECT * FROM "{source_table}"')
                        )
                        columns = list(result.keys())
                        rename = _rename_map(columns, src_to_tgt)
                        if src_to_tgt and not rename:
                            print(
                                f"[step] execute | {source_table} | plan field names did not match columns; copying every column",
                                flush=True,
                            )
                        batch = []
                        for row in result:
                            batch.append(_row_to_doc(columns, row, rename))
                            if len(batch) >= 500:
                                coll.insert_many(batch, ordered=False)
                                copied += len(batch)
                                batch = []
                                if on_progress:
                                    on_progress(i, total, f"{source_table} — {copied} rows copied")
                        if batch:
                            coll.insert_many(batch, ordered=False)
                            copied += len(batch)

                    results["tables_migrated"].append({
                        "source": source_table,
                        "target": target_coll,
                        "rows": copied,
                    })
                    results["total_rows"] += copied
                    print(f"[step] execute | table {i + 1}/{total} | {source_table} copied {copied} rows", flush=True)
                    if on_progress:
                        on_progress(i + 1, total, f"Finished {source_table} ({copied} rows)")
                except Exception as e:
                    message = str(e)
                    results["errors"].append({"table": source_table, "error": message})
                    print(f"[step] execute | table {i + 1}/{total} | {source_table} failed | {message}", flush=True)
                    if on_progress:
                        on_progress(i + 1, total, f"Failed {source_table}")
        finally:
            engine.dispose()
            client.close()
        return results
