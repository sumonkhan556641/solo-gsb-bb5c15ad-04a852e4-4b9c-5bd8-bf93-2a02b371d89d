"""SQLite 建库与读写。

依赖及建库均随容器启动完成（见 main.py  lifespan 中的 init_db）。
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import List, Optional

DB_PATH = os.environ.get("SHEET_DB_PATH", "/data/sheet.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    feasible INTEGER NOT NULL,
    system_heights TEXT NOT NULL,
    boundary_rests TEXT NOT NULL,
    page_height REAL NOT NULL,
    min_safe_rest REAL NOT NULL,
    page_count INTEGER,
    min_turn_rest REAL,
    whitespace_square_sum REAL,
    infeasible_detail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL,
    start_system INTEGER NOT NULL,
    end_system INTEGER NOT NULL,
    used_height REAL NOT NULL,
    whitespace REAL NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pages_plan ON pages(plan_id);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


def insert_plan(
    conn: sqlite3.Connection,
    *,
    name: Optional[str],
    system_heights: List[float],
    boundary_rests: List[float],
    page_height: float,
    min_safe_rest: float,
    feasible: bool,
    page_count: Optional[int],
    min_turn_rest: Optional[float],
    whitespace_square_sum: Optional[float],
    infeasible_detail: Optional[dict],
    pages: Optional[List["Page"]] = None,
) -> int:
    """原子地保存完整方案；不可行时仅保存诊断，不保存任何分页。

    可行 / 不可行都属于"已完成的结论"，不存在半成品分页，
    因此整体在单个事务内提交。
    """
    infeasible_json = (
        json.dumps(infeasible_detail, ensure_ascii=False)
        if infeasible_detail is not None
        else None
    )

    cur = conn.execute(
        """
        INSERT INTO plans (name, feasible, system_heights, boundary_rests,
                           page_height, min_safe_rest, page_count,
                           min_turn_rest, whitespace_square_sum, infeasible_detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            1 if feasible else 0,
            json.dumps(system_heights),
            json.dumps(boundary_rests),
            page_height,
            min_safe_rest,
            page_count,
            min_turn_rest,
            whitespace_square_sum,
            infeasible_json,
        ),
    )
    plan_id = int(cur.lastrowid)

    if feasible and pages:
        conn.executemany(
            """
            INSERT INTO pages (plan_id, page_no, start_system, end_system,
                               used_height, whitespace)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (plan_id, no, p.start_system, p.end_system,
                 p.used_height, p.whitespace)
                for no, p in enumerate(pages, start=1)
            ],
        )
    return plan_id


def get_plan(conn: sqlite3.Connection, plan_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()


def get_pages(conn: sqlite3.Connection, plan_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM pages WHERE plan_id = ? ORDER BY page_no", (plan_id,)
    ).fetchall()


def list_plans(conn: sqlite3.Connection, limit: int, offset: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM plans ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()


def count_plans(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM plans").fetchone()["c"])
