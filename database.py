"""模块 3：内容入库与全文搜索索引"""

import sys
import sqlite3
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "kb.db"


def init_db(db_path=DB_PATH):
    """初始化数据库，创建表和 FTS5 索引"""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            title TEXT,
            date TEXT,
            url TEXT,
            thumbnail TEXT,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            content TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
            title, content,
            content=videos,
            content_rowid=rowid
        )
    """)
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS videos_ai AFTER INSERT ON videos BEGIN
            INSERT INTO videos_fts(rowid, title, content)
            VALUES (new.rowid, new.title, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS videos_ad AFTER DELETE ON videos BEGIN
            INSERT INTO videos_fts(videos_fts, rowid, title, content)
            VALUES ('delete', old.rowid, old.title, old.content);
        END;
        CREATE TRIGGER IF NOT EXISTS videos_au AFTER UPDATE ON videos BEGIN
            INSERT INTO videos_fts(videos_fts, rowid, title, content)
            VALUES ('delete', old.rowid, old.title, old.content);
            INSERT INTO videos_fts(rowid, title, content)
            VALUES (new.rowid, new.title, new.content);
        END;
    """)
    conn.commit()
    return conn


def import_from_json(data, db_path=DB_PATH):
    """从 API 返回的 JSON 数据直接导入数据库"""
    conn = init_db(db_path)

    video_id = data["video_id"]
    existing = conn.execute("SELECT id FROM videos WHERE id = ?", (video_id,)).fetchone()
    if existing:
        return False

    conn.execute(
        "INSERT INTO videos (id, title, date, url, thumbnail, view_count, like_count, content) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            video_id,
            data.get("title", ""),
            data.get("date", ""),
            data.get("url", ""),
            data.get("thumbnail", ""),
            data.get("view_count", 0),
            data.get("like_count", 0),
            data.get("subtitle_text", ""),
        ),
    )
    conn.commit()
    conn.close()
    return True


def import_files(output_dir=OUTPUT_DIR, db_path=DB_PATH):
    """将 output/ 下的所有 JSON 文件导入数据库"""
    conn = init_db(db_path)

    json_files = sorted(output_dir.glob("*.json"))
    imported = 0
    skipped = 0

    for filepath in json_files:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        video_id = data.get("video_id", "")

        if not video_id or not data.get("subtitle_text"):
            skipped += 1
            continue

        existing = conn.execute("SELECT id FROM videos WHERE id = ?", (video_id,)).fetchone()
        if existing:
            skipped += 1
            continue

        conn.execute(
            "INSERT INTO videos (id, title, date, url, thumbnail, view_count, like_count, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                video_id,
                data.get("title", ""),
                data.get("date", ""),
                data.get("url", ""),
                data.get("thumbnail", ""),
                data.get("view_count", 0),
                data.get("like_count", 0),
                data.get("subtitle_text", ""),
            ),
        )
        imported += 1
        print(f"导入: {data.get('title', video_id)}")

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    print(f"\n本次导入: {imported}, 跳过: {skipped}, 数据库总计: {total} 条")
    conn.close()


def search(keyword, db_path=DB_PATH, limit=20):
    """全文搜索，返回匹配结果列表"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = conn.execute("""
        SELECT
            v.id, v.title, v.date, v.url, v.thumbnail,
            v.view_count, v.like_count, v.content,
            snippet(videos_fts, 1, '<mark>', '</mark>', '...', 40) as snippet
        FROM videos_fts
        JOIN videos v ON v.rowid = videos_fts.rowid
        WHERE videos_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (keyword, limit)).fetchall()
    conn.close()
    return [dict(r) for r in results]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        if len(sys.argv) < 3:
            print("用法: python database.py search <关键词>")
            sys.exit(1)
        results = search(sys.argv[2])
        for r in results:
            print(f"\n{r['title']} ({r['date']})")
            print(f"  {r['snippet']}")
            print(f"  {r['url']}")
    else:
        import_files()
