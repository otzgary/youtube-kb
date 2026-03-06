"""YouTube 知识库 — Railway 全栈服务
API + 搜索界面 + 数据库 一体化
"""

import os
import re
import json
import sqlite3
import threading
import time
from pathlib import Path
from markupsafe import escape
from flask import Flask, jsonify, request, render_template, abort, Response

app = Flask(__name__)

# 配置
LANG_PRIORITY = ["zh-Hans", "zh-Hant", "zh", "en"]
DB_PATH = Path(__file__).parent / "kb.db"


# ============================================================
# 数据库
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()


def db_save_video(data):
    """保存视频数据到数据库，返回是否新增"""
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute("SELECT id FROM videos WHERE id = ?", (data["video_id"],)).fetchone()
    if existing:
        conn.close()
        return False
    conn.execute(
        "INSERT INTO videos (id, title, date, url, thumbnail, view_count, like_count, content) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (data["video_id"], data.get("title", ""), data.get("date", ""),
         data.get("url", ""), data.get("thumbnail", ""),
         data.get("view_count", 0), data.get("like_count", 0),
         data.get("subtitle_text", "")),
    )
    conn.commit()
    conn.close()
    return True


def db_search(keyword, limit=20):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    results = conn.execute("""
        SELECT v.id, v.title, v.date, v.url, v.thumbnail,
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


def db_get_video(video_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, title, date, url, thumbnail, view_count, like_count, content "
        "FROM videos WHERE id = ?", (video_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ============================================================
# 模板过滤器
# ============================================================

def format_views(n):
    if not n:
        return "0"
    if n >= 10000_0000:
        return f"{n / 10000_0000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n:,}"


def format_date(d):
    if d and len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d or ""


app.jinja_env.filters["format_views"] = format_views
app.jinja_env.filters["format_date"] = format_date


# ============================================================
# 搜索界面（网页）
# ============================================================

@app.route("/")
def page_index():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        results = db_search(q)
    return render_template("search.html", query=q, results=results)


@app.route("/video/<video_id>")
def page_video(video_id):
    q = request.args.get("q", "").strip()
    video = db_get_video(video_id)
    if not video:
        abort(404)

    content_text = str(escape(video["content"]))
    if q:
        for word in q.split():
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            content_text = pattern.sub(lambda m: f"<mark>{m.group()}</mark>", content_text)

    return render_template("video.html", video=video, content_html=content_text, query=q)


# ============================================================
# API 接口
# ============================================================

def _extract_video(video_id):
    """核心提取逻辑，返回 dict 或抛异常"""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

    title = info.get("title", "未知标题")
    date = info.get("upload_date", "")
    webpage_url = info.get("webpage_url", f"https://www.youtube.com/watch?v={video_id}")
    thumbnail = info.get("thumbnail", "")
    view_count = info.get("view_count", 0)
    like_count = info.get("like_count", 0)

    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()

    transcript = None
    lang_used = None
    try:
        transcript_list = api.list(video_id)
        for lang in LANG_PRIORITY:
            try:
                transcript = transcript_list.find_transcript([lang]).fetch()
                lang_used = lang
                break
            except Exception:
                continue
        if not transcript:
            for lang in LANG_PRIORITY:
                try:
                    transcript = transcript_list.find_generated_transcript([lang]).fetch()
                    lang_used = lang
                    break
                except Exception:
                    continue
    except Exception:
        transcript = api.fetch(video_id)
        lang_used = "default"

    if not transcript:
        raise ValueError("未找到字幕")

    raw = transcript.to_raw_data()
    lines = [entry["text"].replace("\n", " ") for entry in raw if entry.get("text")]
    seen = set()
    unique_lines = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)

    subtitle_text = merge_into_paragraphs(unique_lines)

    result = {
        "status": "success",
        "video_id": video_id,
        "title": title,
        "date": date,
        "url": webpage_url,
        "thumbnail": thumbnail,
        "view_count": view_count,
        "like_count": like_count,
        "lang": lang_used,
        "subtitle_text": subtitle_text,
    }

    db_save_video(result)
    return result


@app.route("/api/extract")
def api_extract():
    """提取单个视频字幕并自动入库"""
    video_id = request.args.get("video_id") or ""
    url = request.args.get("url") or ""

    if not video_id and url:
        m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        if m:
            video_id = m.group(1)

    if not video_id:
        return jsonify({"status": "error", "message": "缺少 video_id 或 url 参数"}), 400

    try:
        result = _extract_video(video_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        msg = str(e)[:300]
        code = 404 if "transcript" in msg.lower() or "subtitle" in msg.lower() else 500
        return jsonify({"status": "error", "message": msg}), code


@app.route("/api/channel")
def api_channel():
    """获取频道所有视频 ID"""
    url = request.args.get("url") or ""
    if not url:
        return jsonify({"status": "error", "message": "缺少 url 参数"}), 400

    if "/videos" not in url and "/playlist" not in url:
        url = url.rstrip("/") + "/videos"

    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        channel = info.get("channel", info.get("title", "未知频道"))
        entries = info.get("entries", [])
        video_ids = [e["id"] for e in entries if e and e.get("id")]

        return jsonify({"status": "success", "channel": channel, "count": len(video_ids), "video_ids": video_ids})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:300]}), 500


@app.route("/api/batch")
def api_batch():
    """批量提取频道所有视频字幕（流式响应，逐条输出进度）"""
    import json as _json
    url = request.args.get("url") or ""
    if not url:
        return jsonify({"status": "error", "message": "缺少 url 参数"}), 400

    if "/videos" not in url and "/playlist" not in url:
        url = url.rstrip("/") + "/videos"

    def generate():
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            channel = info.get("channel", info.get("title", "未知频道"))
            entries = info.get("entries", [])
            video_ids = [e["id"] for e in entries if e and e.get("id")]

            yield _json.dumps({"event": "start", "channel": channel, "total": len(video_ids)}) + "\n"

            success = 0
            failed = []
            for i, vid in enumerate(video_ids, 1):
                existing = db_get_video(vid)
                if existing:
                    success += 1
                    yield _json.dumps({"event": "skip", "video_id": vid, "progress": f"{i}/{len(video_ids)}"}) + "\n"
                    continue
                try:
                    _extract_video(vid)
                    success += 1
                    yield _json.dumps({"event": "ok", "video_id": vid, "progress": f"{i}/{len(video_ids)}"}) + "\n"
                except Exception as e:
                    failed.append(vid)
                    yield _json.dumps({"event": "fail", "video_id": vid, "error": str(e)[:200], "progress": f"{i}/{len(video_ids)}"}) + "\n"

            yield _json.dumps({
                "event": "done",
                "channel": channel,
                "total": len(video_ids),
                "success": success,
                "failed": len(failed),
                "failed_ids": failed,
            }) + "\n"

        except Exception as e:
            yield _json.dumps({"event": "error", "message": str(e)[:300]}) + "\n"

    return Response(generate(), mimetype="application/x-ndjson")


# ============================================================
# 兼容旧 API 路径（本地 extract.py/batch.py 还在用）
# ============================================================

@app.route("/extract")
def api_extract_compat():
    """兼容旧路径"""
    return api_extract()


@app.route("/channel")
def api_channel_compat():
    """兼容旧路径"""
    return api_channel()


# ============================================================
# 后台管理
# ============================================================

# 任务状态存储（内存中，重启后清空）
_tasks = {}  # task_id -> {status, channel, total, success, failed, failed_ids, log, started_at}
_task_counter = 0
_task_lock = threading.Lock()


def _run_batch_task(task_id, channel_url):
    """后台线程：批量提取频道视频"""
    task = _tasks[task_id]
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)

        channel = info.get("channel", info.get("title", "未知频道"))
        entries = info.get("entries", [])
        video_ids = [e["id"] for e in entries if e and e.get("id")]

        task["channel"] = channel
        task["total"] = len(video_ids)
        task["status"] = "running"
        task["log"].append(f"频道: {channel}，共 {len(video_ids)} 个视频")

        for i, vid in enumerate(video_ids, 1):
            existing = db_get_video(vid)
            if existing:
                task["success"] += 1
                task["log"].append(f"[{i}/{len(video_ids)}] 跳过（已存在）: {vid}")
                continue
            try:
                result = _extract_video(vid)
                task["success"] += 1
                title = result.get("title", vid)
                task["log"].append(f"[{i}/{len(video_ids)}] 成功: {title}")
            except Exception as e:
                task["failed"] += 1
                task["failed_ids"].append(vid)
                task["log"].append(f"[{i}/{len(video_ids)}] 失败: {vid} - {str(e)[:100]}")

        task["status"] = "done"
        task["log"].append(f"完成！成功 {task['success']}，失败 {task['failed']}，共 {task['total']}")

    except Exception as e:
        task["status"] = "error"
        task["log"].append(f"出错: {str(e)[:200]}")


def db_stats():
    """获取数据库统计"""
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    conn.close()
    return {"total_videos": total}


@app.route("/admin")
def page_admin():
    stats = db_stats()
    return render_template("admin.html", tasks=_tasks, stats=stats)


@app.route("/admin/start", methods=["POST"])
def admin_start_task():
    global _task_counter
    url = request.form.get("url", "").strip()
    if not url:
        return jsonify({"status": "error", "message": "请输入频道 URL"}), 400

    if "/videos" not in url and "/playlist" not in url:
        url = url.rstrip("/") + "/videos"

    with _task_lock:
        _task_counter += 1
        task_id = str(_task_counter)

    _tasks[task_id] = {
        "status": "starting",
        "channel": "",
        "url": url,
        "total": 0,
        "success": 0,
        "failed": 0,
        "failed_ids": [],
        "log": [f"正在获取频道信息: {url}"],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    t = threading.Thread(target=_run_batch_task, args=(task_id, url), daemon=True)
    t.start()

    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/admin/task/<task_id>")
def admin_task_status(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"status": "error", "message": "任务不存在"}), 404
    # 返回最新的 log 行（客户端可以用 since 参数只获取新行）
    since = int(request.args.get("since", 0))
    return jsonify({
        "status": task["status"],
        "channel": task["channel"],
        "total": task["total"],
        "success": task["success"],
        "failed": task["failed"],
        "log": task["log"][since:],
        "log_offset": len(task["log"]),
    })


@app.route("/admin/videos")
def admin_videos():
    """列出所有已入库视频"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, date, url, thumbnail, view_count, like_count "
        "FROM videos ORDER BY date DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# 工具函数
# ============================================================

def merge_into_paragraphs(lines, sentences_per_paragraph=5):
    if not lines:
        return ""
    paragraphs = []
    current = []
    for line in lines:
        current.append(line)
        ends_sentence = line.endswith(("。", ".", "！", "!", "？", "?"))
        if ends_sentence and len(current) >= sentences_per_paragraph:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


# ============================================================
# 启动
# ============================================================

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
