"""
QueryVista — Base Pipeline Module
Shared logic for schema extraction, AI plan generation, and ETL execution.
"""

import os
import json
import re
import datetime
import decimal
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import create_engine, inspect, text
import pymongo
import httpx

# ─── Logging Setup ───────────────────────────────────────────────────────────
def get_pipeline_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"QueryVista.{name}")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s | [%(levelname)s] | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)
    return logger

logger = get_pipeline_logger("Base")


load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# ─── LLM client (OpenAI-compatible; NVIDIA API by default) ───────────────────
_ai_client: Optional[OpenAI] = None

def get_ai_client() -> OpenAI:
    global _ai_client
    if _ai_client is None:
        _ai_client = OpenAI(
            base_url=os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            api_key=os.getenv("NVIDIA_API_KEY", ""),
            timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "120")),
        )
    return _ai_client

MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b")


# ─── JSON serialization helpers ──────────────────────────────────────────────
def safe_json(obj):
    """Make an object JSON-serializable."""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, datetime.timedelta):
        return str(obj)
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return "<binary>"
    if isinstance(obj, set):
        return list(obj)
    return str(obj)


def json_dumps(obj) -> str:
    return json.dumps(obj, default=safe_json, indent=2)


# ─── SQL Schema Extractor ────────────────────────────────────────────────────
def extract_sql_schema(connection_url: str) -> Dict[str, Any]:
    """Extract full schema metadata from any SQL database via SQLAlchemy."""
    logger.info("extract_sql_schema | connecting")
    print("[step] extract-schema | reading tables from SQL database", flush=True)
    engine = create_engine(
        connection_url,
        connect_args={"connect_timeout": 10},
        pool_pre_ping=True,
    )
    inspector = inspect(engine)

    schema_info = {}
    for table_name in inspector.get_table_names():
        columns = []
        for col in inspector.get_columns(table_name):
            columns.append({
                "name": col["name"],
                "type": str(col["type"]),
                "nullable": col.get("nullable", True),
                "default": str(col.get("default")) if col.get("default") else None,
            })

        pks = inspector.get_pk_constraint(table_name)
        fks = inspector.get_foreign_keys(table_name)
        indexes = inspector.get_indexes(table_name)

        schema_info[table_name] = {
            "columns": columns,
            "primary_keys": pks.get("constrained_columns", []) if pks else [],
            "foreign_keys": [
                {
                    "constrained_columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                }
                for fk in fks
            ],
            "indexes": [
                {"name": idx["name"], "columns": idx["column_names"]}
                for idx in indexes
            ],
            "row_count": None,  # populated next
        }

    # Get row counts
    with engine.connect() as conn:
        for table_name in schema_info:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))
                schema_info[table_name]["row_count"] = result.scalar()
            except Exception:
                try:
                    result = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                    schema_info[table_name]["row_count"] = result.scalar()
                except Exception:
                    schema_info[table_name]["row_count"] = "unknown"

    engine.dispose()
    return schema_info


# ─── MongoDB Schema Profiler ─────────────────────────────────────────────────
def extract_mongo_schema(connection_url: str, database: str, sample_size: int = 100) -> Dict[str, Any]:
    """Profile collections in a MongoDB database."""
    client = pymongo.MongoClient(connection_url)
    db = client[database]

    schema_info = {}
    for coll_name in db.list_collection_names():
        coll = db[coll_name]
        doc_count = coll.estimated_document_count()
        sample = list(coll.find().limit(sample_size))

        # Infer field types from sample
        field_types: Dict[str, set] = {}
        for doc in sample:
            for key, value in doc.items():
                if key not in field_types:
                    field_types[key] = set()
                field_types[key].add(type(value).__name__)

        schema_info[coll_name] = {
            "document_count": doc_count,
            "fields": {
                k: list(v) for k, v in field_types.items()
            },
            "sample_doc": json.loads(json_dumps(sample[0])) if sample else {},
        }

    client.close()
    return schema_info


# ─── CouchDB Schema Profiler ─────────────────────────────────────────────────
def extract_couch_schema(host: str, username: str, password: str) -> Dict[str, Any]:
    """Profile databases in a CouchDB instance."""
    auth = (username, password)
    schema_info = {}

    r = httpx.get(f"{host}/_all_dbs", auth=auth, timeout=30)
    r.raise_for_status()
    all_dbs = [db for db in r.json() if not db.startswith("_")]

    for db_name in all_dbs:
        # Get db info
        info_r = httpx.get(f"{host}/{db_name}", auth=auth, timeout=30)
        info = info_r.json()

        # Sample docs
        docs_r = httpx.get(
            f"{host}/{db_name}/_all_docs",
            params={"include_docs": "true", "limit": 50},
            auth=auth,
            timeout=30,
        )
        docs_data = docs_r.json()
        rows = docs_data.get("rows", [])
        sample_docs = [row["doc"] for row in rows if "doc" in row]

        # Infer field types
        field_types: Dict[str, set] = {}
        for doc in sample_docs:
            for key, value in doc.items():
                if key.startswith("_"):
                    continue
                if key not in field_types:
                    field_types[key] = set()
                field_types[key].add(type(value).__name__)

        schema_info[db_name] = {
            "doc_count": info.get("doc_count", 0),
            "fields": {k: list(v) for k, v in field_types.items()},
            "sample_doc": sample_docs[0] if sample_docs else {},
        }

    return schema_info


def _repair_truncated_json(text: str) -> str:
    """Close a JSON document that was cut off mid-value."""
    text = text.rstrip()
    last_complete = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
                last_complete = i
            continue
        if ch == '"':
            in_str = True
        elif ch in "}]":
            last_complete = i

    if in_str and last_complete >= 0:
        text = text[: last_complete + 1]

    text = text.rstrip()
    text = re.sub(r",\s*$", "", text)
    text = re.sub(r',?\s*"[^"\\]*"\s*:\s*$', "", text)
    text = re.sub(r",\s*$", "", text)

    stack = []
    in_str = False
    escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()

    if in_str:
        text += '"'
    text += "".join(reversed(stack))
    return text


def parse_model_json(raw: str) -> Dict[str, Any]:
    """Parse model output, including JSON that was cut off by the token limit."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        return {"error": "The model did not return a JSON object.", "raw_response": raw}

    body = text[start:]
    try:
        plan = json.loads(body)
        if isinstance(plan, dict):
            return plan
    except json.JSONDecodeError:
        pass

    repaired = _repair_truncated_json(body)
    try:
        plan = json.loads(repaired)
    except json.JSONDecodeError as exc:
        return {
            "error": f"Could not parse the model JSON ({exc}).",
            "raw_response": raw,
        }

    if not isinstance(plan, dict):
        return {"error": "The model JSON was not an object.", "raw_response": raw}

    items = plan.get("collections") or plan.get("tables") or []
    plan["_warning"] = (
        f"The model response was cut off. Recovered {len(items)} table"
        f"{'' if len(items) == 1 else 's'}. Generate the plan again if a table is missing."
    )
    print(f"[step] generate-plan | repaired truncated JSON | tables={len(items)}", flush=True)
    return plan


# ─── AI Plan Generator ───────────────────────────────────────────────────────
def validate_migration_plan(plan: Dict[str, Any]) -> List[str]:
    """Return problems that would make the plan unsafe to show or execute."""
    issues: List[str] = []
    if not isinstance(plan, dict):
        return ["Plan is not a JSON object."]
    if plan.get("error"):
        issues.append(str(plan["error"]))
    if plan.get("_warning"):
        issues.append(str(plan["_warning"]))

    items = plan.get("collections")
    if items is None:
        items = plan.get("tables")
    if not isinstance(items, list) or not items:
        issues.append('Plan must contain a non-empty "collections" or "tables" list.')
        return issues

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            issues.append(f"Item {index} is not an object.")
            continue
        source = item.get("source")
        target = item.get("target")
        label = source or f"item {index}"
        if not source or not target:
            issues.append(f"{label} is missing source or target.")
        mappings = item.get("field_mappings")
        if not isinstance(mappings, list) or not mappings:
            issues.append(f"{label} has no field_mappings.")
            continue
        for mapping in mappings:
            if not isinstance(mapping, dict):
                issues.append(f"{label} has a field mapping that is not an object.")
                continue
            if not (mapping.get("source_field") or mapping.get("source")):
                issues.append(f"{label} has a mapping without source_field.")
            if not (mapping.get("target_field") or mapping.get("target")):
                issues.append(f"{label} has a mapping without target_field.")
    return issues


def _collect_model_text(client: OpenAI, messages: List[Dict[str, str]]) -> str:
    """Call the model, and once more if the answer is cut off by the token limit."""
    parts: List[str] = []
    for _ in range(2):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.2,
            top_p=1,
            max_tokens=8192,
        )
        piece = response.choices[0].message.content or ""
        finish = getattr(response.choices[0], "finish_reason", None)
        parts.append(piece)
        print(f"[step] generate-plan | model response received | finish={finish} | chars={len(piece)}", flush=True)
        if finish != "length":
            break
        print("[step] generate-plan | output hit the token limit, asking the model to continue", flush=True)
        messages.append({"role": "assistant", "content": piece})
        messages.append({
            "role": "user",
            "content": "The JSON was cut off. Continue from the exact stopping point. Do not repeat earlier text. Do not use markdown.",
        })
    return "".join(parts).strip()


def generate_migration_plan(
    source_type: str,
    target_type: str,
    schema_text: str,
    feedback: Optional[str] = None,
    existing_plan: Optional[str] = None,
) -> Dict[str, Any]:
    """Ask the configured NVIDIA model for a migration plan."""
    print(f"[step] generate-plan | model call | {source_type} -> {target_type}", flush=True)
    client = get_ai_client()

    system_prompt = f"""You are a database migration architect.
You are migrating data from {source_type.upper()} to {target_type.upper()}.

Given the source schema metadata, produce a JSON migration plan.

The plan must be a JSON object with a key "collections" (or "tables") that is a list.
Each item should have:
- "source": the source table/collection name
- "target": the target table/collection name
- "field_mappings": a list of {{ "source_field", "target_field", "type", "notes" }}
- "strategy": one of "flat", "embed", "reference", "normalize", "denormalize"
- "notes": one short sentence, or ""
- "embedding": omit this key unless related rows should be nested

Keep the JSON compact. Include every source table. Return ONLY valid JSON. No markdown.
"""

    messages = [{"role": "system", "content": system_prompt}]

    if existing_plan and feedback:
        messages.append({
            "role": "user",
            "content": f"Here is the current migration plan:\n\n{existing_plan}\n\nUser feedback:\n{feedback}\n\nPlease update the plan based on the feedback. Return ONLY the updated JSON.",
        })
    else:
        messages.append({
            "role": "user",
            "content": f"Source {source_type} schema:\n\n{schema_text}\n\nGenerate the migration plan to {target_type}. Return ONLY valid JSON.",
        })

    last_issues: List[str] = ["The model did not return a plan."]
    for attempt in range(1, 4):
        raw = _collect_model_text(client, messages)
        plan = parse_model_json(raw)
        last_issues = validate_migration_plan(plan)
        table_count = len((plan.get("collections") or plan.get("tables") or [])) if isinstance(plan, dict) else 0
        if not last_issues:
            plan.pop("_warning", None)
            plan.pop("raw_response", None)
            plan.pop("error", None)
            print(f"[step] generate-plan | validated | attempt={attempt} | tables={table_count}", flush=True)
            return plan

        print(f"[step] generate-plan | rejected | attempt={attempt} | issues={len(last_issues)}", flush=True)
        for issue in last_issues:
            print(f"[step] generate-plan | issue | {issue}", flush=True)
        if attempt == 3:
            break
        messages.append({"role": "assistant", "content": raw})
        issues_text = "\n".join(f"- {issue}" for issue in last_issues)
        messages.append({
            "role": "user",
            "content": (
                "This plan failed review. Fix every issue and return the full corrected JSON only.\n"
                f"{issues_text}"
            ),
        })

    raise ValueError("Migration plan was still invalid after 3 reviews: " + "; ".join(last_issues))


# ─── Base Pipeline Class ─────────────────────────────────────────────────────
class BasePipeline(ABC):
    """Abstract base for all migration pipelines."""

    source_type: str = ""
    target_type: str = ""

    @abstractmethod
    def test_source_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test connection to source DB. Returns {"success": bool, "message": str}."""
        pass

    @abstractmethod
    def test_target_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test connection to target DB. Returns {"success": bool, "message": str}."""
        pass

    @abstractmethod
    def extract_schema(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract schema from source DB."""
        pass

    @abstractmethod
    def execute(
        self,
        source_config: Dict[str, Any],
        target_config: Dict[str, Any],
        plan: Dict[str, Any],
        on_progress: Any = None,
    ) -> Dict[str, Any]:
        """Execute the migration based on the approved plan."""
        pass
