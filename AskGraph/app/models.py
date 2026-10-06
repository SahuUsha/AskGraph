from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, field_validator

from .config import settings
from .utils import resolve_db_url


class _DbRequest(BaseModel):
    """Base for every request carrying a connection string.

    The db_url validator lives here so 'preset:<name>' is expanded once,
    for all endpoints, instead of the frontend holding cache-DB credentials.
    """

    db_url: str = Field(..., description="Connection string, or preset:<dbname>")

    @field_validator("db_url")
    @classmethod
    def _resolve(cls, v: str) -> str:
        return resolve_db_url(v.strip(), settings.CACHE_DB_URL, settings.SAMPLE_DB_URL)


class DBConnectionRequest(_DbRequest):
    pass


class UserRequest(_DbRequest):
    query: str = Field(..., min_length=1, max_length=4000, description="Natural language question")
    safe_mode: bool = Field(True, description="True = SELECT only.")


class AnalysisResponse(BaseModel):
    sql_query: str
    message: Optional[str] = "Query executed successfully."
    data_preview: Optional[List[Dict[str, Any]]] = None
    graphs_base64: List[str] = []
    csv_base64: Optional[str] = None
    error: Optional[str] = None


class TableDetailsResponse(BaseModel):
    table_name: str
    row_count: int
    columns: List[str]
    first_10: List[Dict[str, Any]]
    last_10: List[Dict[str, Any]]


class ChartSpec(BaseModel):
    """One planned chart. Doubles as the response_schema for the planning call,
    so the model returns typed JSON instead of prose we have to parse."""

    title: str
    description: str
    sql_query: str


class DashboardChart(BaseModel):
    title: str
    description: str
    graph_base64: str
    sql_query: Optional[str] = None


class FailedChart(BaseModel):
    """A chart that was planned but couldn't be built, and why.

    Failures used to be swallowed by a bare `continue`, so a dashboard that
    returned 2 of 5 charts looked identical to one that only planned 2.
    """

    title: str
    reason: str


class DashboardResponse(BaseModel):
    charts: List[DashboardChart]
    failed: List[FailedChart] = []
    error: Optional[str] = None


class HealthFinding(BaseModel):
    """One thing wrong with the data. severity is high | medium | low."""

    severity: str
    table: str
    column: Optional[str] = None
    issue: str
    detail: str


class SkippedTable(BaseModel):
    """A table the run couldn't profile, and why — same reasoning as
    FailedChart: a partial report must not look like a clean one."""

    table: str
    reason: str


class HealthReport(BaseModel):
    findings: List[HealthFinding] = []
    score: int = 100
    tables_checked: int = 0
    skipped: List[SkippedTable] = []
    error: Optional[str] = None


# Bounds on the export payload: the browser posts the rendered charts back up,
# so the request is as big as the dashboard. A panel PNG is well under 1 MB.
MAX_EXPORT_CHARTS = 20
MAX_EXPORT_IMAGE_CHARS = 8_000_000


class ChartExport(BaseModel):
    """One chart the browser already has, sent back to be zipped."""

    title: str = Field("", max_length=300)
    description: str = Field("", max_length=2000)
    graph_base64: str = Field(..., min_length=1, max_length=MAX_EXPORT_IMAGE_CHARS)


class ChartExportRequest(BaseModel):
    charts: List[ChartExport] = Field(..., min_length=1, max_length=MAX_EXPORT_CHARTS)


class OptimizeRequest(_DbRequest):
    query: str = Field(..., min_length=1, max_length=20000, description="The SQL query to analyze")


class OptimizeResponse(BaseModel):
    original_query: str
    optimized_query: str
    explanation: str
    difference_score: int = Field(..., description="0-100 score of how much changed")


class PaginationRequest(DBConnectionRequest):
    page: int = Field(1, ge=1)
    # Unbounded limit let a caller pull an entire table into memory.
    limit: int = Field(100, ge=1, le=settings.MAX_PAGE_SIZE)


class PaginationResponse(BaseModel):
    data: List[Dict[str, Any]]
    total_rows: int
    page: int
    total_pages: int
    error: Optional[str] = None
