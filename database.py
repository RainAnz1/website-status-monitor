import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("MONITOR_DB_PATH", os.path.join(BASE_DIR, "monitor.db"))
DB_TIMEOUT_SECONDS = 10


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {DB_TIMEOUT_SECONDS * 1000}")
    return conn


@contextmanager
def database_connection():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库结构和常用查询索引。"""
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(db_dir, exist_ok=True)

    with database_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                status_code INTEGER,
                response_time REAL,
                ssl_days_left INTEGER,
                error_msg TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS outages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                duration_seconds INTEGER,
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checks_site_checked
                ON checks(site_id, checked_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_outages_site_started
                ON outages(site_id, started_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_outages_site_open
                ON outages(site_id) WHERE ended_at IS NULL;
            """
        )


def add_site(name: str, url: str):
    with database_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO sites (name, url) VALUES (?, ?)",
            (name, url),
        )
        return cursor.lastrowid


def get_site(site_id: int):
    with database_connection() as conn:
        row = conn.execute(
            "SELECT id, name, url, created_at FROM sites WHERE id = ?",
            (site_id,),
        ).fetchone()
    return dict(row) if row else None


def get_sites():
    with database_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, url, created_at FROM sites "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_site_statuses(check_limit: int = 30, outage_limit: int = 20):
    """批量读取展示页所需状态，避免按站点重复查询数据库。"""
    check_limit = max(1, min(int(check_limit), 1000))
    outage_limit = max(1, min(int(outage_limit), 1000))

    with database_connection() as conn:
        conn.execute("BEGIN")
        site_rows = conn.execute(
            """
            SELECT
                s.id, s.name, s.url, s.created_at,
                c.status, c.status_code, c.response_time, c.ssl_days_left,
                c.error_msg, c.checked_at
            FROM sites AS s
            LEFT JOIN checks AS c ON c.id = (
                SELECT id
                FROM checks
                WHERE site_id = s.id
                ORDER BY checked_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY s.created_at DESC, s.id DESC
            """
        ).fetchall()

        uptime_rows = conn.execute(
            """
            WITH recent_checks AS (
                SELECT
                    site_id,
                    status,
                    ROW_NUMBER() OVER (
                        PARTITION BY site_id
                        ORDER BY checked_at DESC, id DESC
                    ) AS row_number
                FROM checks
            )
            SELECT
                site_id,
                COUNT(*) AS total_count,
                SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) AS up_count
            FROM recent_checks
            WHERE row_number <= ?
            GROUP BY site_id
            """,
            (check_limit,),
        ).fetchall()

        outage_rows = conn.execute(
            """
            WITH recent_outages AS (
                SELECT
                    id, site_id, started_at, ended_at, duration_seconds,
                    ROW_NUMBER() OVER (
                        PARTITION BY site_id
                        ORDER BY started_at DESC, id DESC
                    ) AS row_number
                FROM outages
            )
            SELECT id, site_id, started_at, ended_at, duration_seconds
            FROM recent_outages
            WHERE row_number <= ?
            ORDER BY site_id, started_at DESC, id DESC
            """,
            (outage_limit,),
        ).fetchall()

    uptime_by_site = {
        row["site_id"]: round(row["up_count"] / row["total_count"] * 100, 1)
        for row in uptime_rows
    }
    outages_by_site = {}
    for row in outage_rows:
        outages_by_site.setdefault(row["site_id"], []).append(
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "duration_seconds": row["duration_seconds"],
            }
        )

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "created_at": row["created_at"],
            "status": row["status"] or "unknown",
            "status_code": row["status_code"],
            "response_time": row["response_time"],
            "ssl_days_left": row["ssl_days_left"],
            "error_msg": row["error_msg"],
            "checked_at": row["checked_at"],
            "uptime": uptime_by_site.get(row["id"]),
            "outages": outages_by_site.get(row["id"], []),
        }
        for row in site_rows
    ]


def get_latest_check(site_id: int):
    with database_connection() as conn:
        row = conn.execute(
            """
            SELECT status, status_code, response_time, ssl_days_left,
                   error_msg, checked_at
            FROM checks
            WHERE site_id = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
            """,
            (site_id,),
        ).fetchone()
    return dict(row) if row else None


def save_check(
    site_id: int,
    status: str,
    status_code=None,
    response_time=None,
    ssl_days_left=None,
    error_msg=None,
):
    now = utc_now_iso()
    with database_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            INSERT INTO checks (
                site_id, status, status_code, response_time,
                ssl_days_left, error_msg, checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                site_id,
                status,
                status_code,
                response_time,
                ssl_days_left,
                error_msg,
                now,
            ),
        )

        if status == "down":
            ongoing = conn.execute(
                "SELECT id FROM outages WHERE site_id = ? AND ended_at IS NULL",
                (site_id,),
            ).fetchone()
            if not ongoing:
                conn.execute(
                    "INSERT INTO outages (site_id, started_at) VALUES (?, ?)",
                    (site_id, now),
                )
        else:
            conn.execute(
                """
                UPDATE outages
                SET ended_at = ?,
                    duration_seconds = strftime('%s', ?) - strftime('%s', started_at)
                WHERE site_id = ? AND ended_at IS NULL
                """,
                (now, now, site_id),
            )

        return cursor.lastrowid


def get_outages(site_id: int, limit: int = 20):
    limit = max(1, min(int(limit), 1000))
    with database_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, ended_at, duration_seconds
            FROM outages
            WHERE site_id = ?
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (site_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_checks(site_id: int, limit: int = 30):
    limit = max(1, min(int(limit), 1000))
    with database_connection() as conn:
        rows = conn.execute(
            """
            SELECT status, status_code, response_time, ssl_days_left,
                   error_msg, checked_at
            FROM checks
            WHERE site_id = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
            """,
            (site_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_uptime(site_id: int, limit: int = 30):
    checks = get_recent_checks(site_id, limit)
    if not checks:
        return None

    up_count = sum(1 for check in checks if check["status"] == "up")
    return round(up_count / len(checks) * 100, 1)


def delete_site(site_id: int):
    with database_connection() as conn:
        # 兼容早期未启用 ON DELETE CASCADE 的现有数据库。
        conn.execute("DELETE FROM outages WHERE site_id = ?", (site_id,))
        conn.execute("DELETE FROM checks WHERE site_id = ?", (site_id,))
        cursor = conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        return cursor.rowcount > 0
