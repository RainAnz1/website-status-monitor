import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("MONITOR_DB_PATH", os.path.join(BASE_DIR, "monitor.db"))

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 网站配置表
    c.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 检查记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            status TEXT NOT NULL,  -- 'up' 或 'down'
            status_code INTEGER,
            response_time REAL,     -- 毫秒
            ssl_days_left INTEGER,
            error_msg TEXT,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES sites(id)
        )
    """)
    
    # 宕机记录表
    c.execute("""
        CREATE TABLE IF NOT EXISTS outages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            started_at TIMESTAMP NOT NULL,
            ended_at TIMESTAMP,
            duration_seconds INTEGER,
            FOREIGN KEY (site_id) REFERENCES sites(id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_PATH)

def add_site(name: str, url: str):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO sites (name, url) VALUES (?, ?)", (name, url))
        conn.commit()
        site_id = c.lastrowid
    finally:
        conn.close()
    return site_id

def get_sites():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, url, created_at FROM sites ORDER BY created_at DESC, id DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "url": r[2], "created_at": r[3]} for r in rows]

def get_latest_check(site_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT status, status_code, response_time, ssl_days_left, error_msg, checked_at
        FROM checks WHERE site_id = ? ORDER BY checked_at DESC, id DESC LIMIT 1
    """, (site_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "status": row[0], "status_code": row[1], "response_time": row[2],
            "ssl_days_left": row[3], "error_msg": row[4], "checked_at": row[5]
        }
    return None

def save_check(site_id: int, status: str, status_code=None, response_time=None, 
                ssl_days_left=None, error_msg=None):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    c.execute("""
        INSERT INTO checks (site_id, status, status_code, response_time, ssl_days_left, error_msg, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (site_id, status, status_code, response_time, ssl_days_left, error_msg, now))
    check_id = c.lastrowid
    
    # 处理宕机记录
    if status == "down":
        # 检查是否已有ongoing的宕机记录
        c.execute("SELECT id FROM outages WHERE site_id = ? AND ended_at IS NULL", (site_id,))
        ongoing = c.fetchone()
        if not ongoing:
            c.execute("INSERT INTO outages (site_id, started_at) VALUES (?, ?)", 
                      (site_id, now))
    else:
        # 在线：关闭所有ongoing宕机记录
        c.execute("""
            UPDATE outages SET ended_at = ?, duration_seconds = 
            (strftime('%s', ?) - strftime('%s', started_at))
            WHERE site_id = ? AND ended_at IS NULL
        """, (now, now, site_id))
    
    conn.commit()
    conn.close()
    return check_id

def get_outages(site_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, started_at, ended_at, duration_seconds FROM outages
        WHERE site_id = ? ORDER BY started_at DESC LIMIT 20
    """, (site_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "started_at": r[1], "ended_at": r[2], 
             "duration_seconds": r[3]} for r in rows]

def get_recent_checks(site_id: int, limit: int = 30):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT status, status_code, response_time, ssl_days_left, error_msg, checked_at
        FROM checks WHERE site_id = ? ORDER BY checked_at DESC, id DESC LIMIT ?
    """, (site_id, limit))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "status": r[0],
            "status_code": r[1],
            "response_time": r[2],
            "ssl_days_left": r[3],
            "error_msg": r[4],
            "checked_at": r[5],
        }
        for r in rows
    ]

def get_recent_uptime(site_id: int, limit: int = 30):
    checks = get_recent_checks(site_id, limit)
    if not checks:
        return None

    up_count = sum(1 for check in checks if check["status"] == "up")
    return round(up_count / len(checks) * 100, 1)

def delete_site(site_id: int):
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM outages WHERE site_id = ?", (site_id,))
        c.execute("DELETE FROM checks WHERE site_id = ?", (site_id,))
        c.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        deleted = c.rowcount
        conn.commit()
    finally:
        conn.close()
    return deleted > 0
