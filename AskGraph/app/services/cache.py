import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager

from ..utils import redact


class CacheManager:
    def __init__(self, cache_db_url: str, ttl_hours: int = 24, connect_timeout: int = 10):
        self.cache_db_url = cache_db_url
        self.ttl_hours = ttl_hours
        self.connect_timeout = connect_timeout
        self._pool = None

    @contextmanager
    def _conn(self):
        """Pooled connection.

        Every cache read and write used to open and close its own TCP+TLS
        connection to Neon — up to four per request.
        """
        if self._pool is None:
            self._pool = ThreadedConnectionPool(
                1, 5, self.cache_db_url, connect_timeout=self.connect_timeout
            )
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def init_cache_db(self):
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS schema_cache (
                            db_hash TEXT PRIMARY KEY,
                            schema_text TEXT,
                            context_text TEXT,
                            dialect TEXT,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                    cur.execute("ALTER TABLE schema_cache ADD COLUMN IF NOT EXISTS dialect TEXT;")
                conn.commit()
            print("✅ Cache table ready.")
        except Exception as e:
            print(f"❌ Cache Init Error: {redact(e)}")

    def get_cached_schema(self, db_hash: str):
        """Returns None once the entry is older than the TTL.

        updated_at was written but never read, so a migration on the target DB
        poisoned every later prompt with a stale schema, permanently.
        """
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT schema_text, context_text, dialect
                        FROM schema_cache
                        WHERE db_hash = %s
                          AND updated_at > CURRENT_TIMESTAMP - (%s * INTERVAL '1 hour')
                        """,
                        (db_hash, self.ttl_hours),
                    )
                    result = cur.fetchone()
                conn.rollback()  # end the read txn; don't hold it in the pool
            if result:
                return {"schema": result[0], "context": result[1], "dialect": result[2]}
            return None
        except Exception as e:
            print(f"⚠️ Cache Read Error: {redact(e)}")
            return None

    def save_cached_schema(self, db_hash: str, schema_text: str, context_text: str, dialect: str):
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO schema_cache (db_hash, schema_text, context_text, dialect)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (db_hash)
                        DO UPDATE SET
                            schema_text = EXCLUDED.schema_text,
                            context_text = EXCLUDED.context_text,
                            dialect = EXCLUDED.dialect,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (db_hash, schema_text, context_text, dialect))
                conn.commit()
        except Exception as e:
            print(f"⚠️ Cache Write Error: {redact(e)}")

    def invalidate(self, db_hash: str) -> bool:
        """Drop one cached schema so the next request refetches."""
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM schema_cache WHERE db_hash = %s", (db_hash,))
                    deleted = cur.rowcount
                conn.commit()
            return deleted > 0
        except Exception as e:
            print(f"⚠️ Cache Invalidate Error: {redact(e)}")
            return False
