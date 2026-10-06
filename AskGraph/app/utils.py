import base64
import hashlib
import io
import re
import zipfile
from urllib.parse import urlparse, urlunparse

# Frontend picks a database by name from /databases; it must never be handed
# the cache host's credentials to build a URL with. It sends preset:<name>
# instead and the server expands it against CACHE_DB_URL.
PRESET_SCHEME = "preset:"

_CREDS = re.compile(r"://[^/@\s]*:[^/@\s]*@")


def get_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_dialect_name(db_url: str) -> str:
    """Dialect from the URL scheme.

    Substring-matching the whole URL meant a password containing 'oracle'
    silently switched dialects.
    """
    scheme = urlparse(db_url).scheme.lower()
    driver = scheme.split("+")[0]
    return {
        "postgresql": "postgres",
        "postgres": "postgres",
        "mysql": "mysql",
        "mariadb": "mysql",
        "oracle": "oracle",
        "mssql": "tsql",
        "sqlite": "sqlite",
    }.get(driver, "sql")


def redact(text: str) -> str:
    """Strip user:password out of anything headed for a client or a log.

    Driver connection errors embed the full DSN, so returning str(e) verbatim
    handed the caller the database password.
    """
    return _CREDS.sub("://***:***@", str(text))


def resolve_db_url(db_url: str, cache_db_url: str, sample_db_url: str | None = None) -> str:
    """Expand 'preset:<dbname>' into a full URL on the cache DB host.

    'preset:sample' expands to SAMPLE_DB_URL instead, so the demo database's
    password stays on the server too.
    """
    if not db_url.startswith(PRESET_SCHEME):
        return db_url

    name = db_url[len(PRESET_SCHEME):].strip().strip("/")
    if name == "sample":
        if not sample_db_url:
            raise ValueError("Sample database is not configured (set SAMPLE_DB_URL).")
        return sample_db_url
    if not name or "/" in name or "?" in name or "@" in name:
        raise ValueError("Invalid database name.")

    parts = urlparse(cache_db_url)
    return urlunparse(parts._replace(path=f"/{name}"))


def slugify(text: str, max_length: int = 60) -> str:
    """A filename-safe stem. Mirrors slugify() in the frontend.

    This is the only thing standing between a model-written chart title and a
    zip entry named '../../etc/passwd', so it strips to [a-z0-9-] rather than
    blocklisting separators.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())[:max_length].strip("-")
    return slug or "chart"


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def build_charts_zip(charts) -> bytes:
    """Zip of one .png plus one .txt per chart, ordered as the dashboard shows
    them. Raises ValueError on anything that isn't a real PNG.

    The images come back from the browser, so they are decoded and checked
    here rather than trusted — and the numeric prefix keeps two panels with the
    same title from colliding into one entry.
    """
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, chart in enumerate(charts, 1):
            try:
                png = base64.b64decode(chart.graph_base64, validate=True)
            except Exception:
                raise ValueError(f"Chart {i} is not valid base64.")
            if not png.startswith(PNG_MAGIC):
                raise ValueError(f"Chart {i} is not a PNG image.")

            title = (chart.title or "").strip() or "Chart"
            description = (chart.description or "").strip() or "No description."
            stem = f"{i:02d}-{slugify(title)}"

            zf.writestr(f"{stem}.png", png)
            zf.writestr(f"{stem}.txt", f"{title}\n\n{description}\n")

    return buf.getvalue()
