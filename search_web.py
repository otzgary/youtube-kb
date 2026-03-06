"""模块 4b：网页搜索界面"""

import os
import re
import sqlite3
from markupsafe import escape
from flask import Flask, render_template, request, abort
from database import search, init_db, DB_PATH

app = Flask(__name__)


def format_views(n):
    """格式化播放量"""
    if not n:
        return "0"
    if n >= 10000_0000:
        return f"{n / 10000_0000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n:,}"


def format_date(d):
    """YYYYMMDD → YYYY-MM-DD"""
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d or ""


app.jinja_env.filters["format_views"] = format_views
app.jinja_env.filters["format_date"] = format_date


@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = search(q)
    return render_template("search.html", query=q, results=results)


@app.route("/video/<video_id>")
def video_detail(video_id):
    q = request.args.get("q", "").strip()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, title, date, url, thumbnail, view_count, like_count, content FROM videos WHERE id = ?",
        (video_id,),
    ).fetchone()
    conn.close()

    if not row:
        abort(404)

    video = dict(row)

    # 如果有搜索词，在文稿中高亮
    content_text = str(escape(video["content"]))
    if q:
        for word in q.split():
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            content_text = pattern.sub(lambda m: f"<mark>{m.group()}</mark>", content_text)

    return render_template("video.html", video=video, content_html=content_text, query=q)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
