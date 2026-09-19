"""入库层: SQLite 存话题与文案, 提供简单查询。

选 SQLite 的理由: 零部署、单文件、Python 标准库自带, 管线落库够用。
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT,
    heat INTEGER DEFAULT 0,
    source TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS copies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER REFERENCES topics(id),
    topic TEXT,
    platform TEXT,
    title TEXT,
    hook TEXT,
    body TEXT,
    hashtags TEXT,
    audio_path TEXT,
    subtitle_path TEXT,
    created_at TEXT
);
"""


def _conn() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


def save_topics(topics: list[dict]) -> list[int]:
    """写入话题, 返回自增 id 列表(供文案表外键用)。"""
    now = datetime.now().isoformat(timespec="seconds")
    ids = []
    with _conn() as conn:
        conn.executescript(SCHEMA)
        for t in topics:
            cur = conn.execute(
                "INSERT INTO topics(title, summary, heat, source, fetched_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (t["title"], t.get("summary", ""), t.get("heat", 0),
                 t.get("source", ""), now),
            )
            ids.append(cur.lastrowid)
    return ids


def save_copy(copy: dict, topic_id: int | None = None,
              audio_path: str = "", subtitle_path: str = "") -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute(
            "INSERT INTO copies(topic_id, topic, platform, title, hook, body, "
            "hashtags, audio_path, subtitle_path, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (topic_id, copy.get("topic", ""), copy.get("platform", ""),
             copy.get("title", ""), copy.get("hook", ""), copy.get("body", ""),
             json_dumps(copy.get("hashtags", [])),
             audio_path, subtitle_path, now),
        )
        return cur.lastrowid


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def stats() -> dict:
    with _conn() as conn:
        conn.executescript(SCHEMA)
        n_topics = conn.execute("SELECT COUNT(*) c FROM topics").fetchone()["c"]
        n_copies = conn.execute("SELECT COUNT(*) c FROM copies").fetchone()["c"]
        by_platform = {
            r["platform"]: r["c"]
            for r in conn.execute(
                "SELECT platform, COUNT(*) c FROM copies GROUP BY platform")
        }
    return {"topics": n_topics, "copies": n_copies, "by_platform": by_platform}


def list_copies(limit: int = 5) -> list[sqlite3.Row]:
    with _conn() as conn:
        conn.executescript(SCHEMA)
        return conn.execute(
            "SELECT id, platform, title, created_at FROM copies "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


if __name__ == "__main__":
    init_db()
    print(stats())
