"""模块 4b：网页搜索界面"""

import os
from flask import Flask, render_template, request
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


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
