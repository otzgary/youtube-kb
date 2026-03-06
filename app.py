"""Railway API 服务：提取 YouTube 视频字幕"""

import os
import re
from flask import Flask, jsonify, request

app = Flask(__name__)

# 字幕语言优先级
LANG_PRIORITY = ["zh-Hans", "zh-Hant", "zh", "en"]


@app.route("/")
def index():
    return "YouTube 知识库 - 服务运行中"


@app.route("/extract")
def extract():
    """提取单个视频的字幕

    参数: ?video_id=dQw4w9WgXcQ 或 ?url=https://youtube.com/watch?v=xxx
    返回: { status, video_id, title, date, subtitle_text }
    """
    video_id = request.args.get("video_id") or ""
    url = request.args.get("url") or ""

    # 从 URL 中提取 video_id
    if not video_id and url:
        m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        if m:
            video_id = m.group(1)

    if not video_id:
        return jsonify({"status": "error", "message": "缺少 video_id 或 url 参数"}), 400

    try:
        # 获取视频信息
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

        title = info.get("title", "未知标题")
        date = info.get("upload_date", "")
        webpage_url = info.get("webpage_url", f"https://www.youtube.com/watch?v={video_id}")

        # 获取字幕
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()

        # 尝试按优先级获取字幕
        transcript = None
        lang_used = None
        try:
            transcript_list = api.list(video_id)
            # 先找人工字幕
            for lang in LANG_PRIORITY:
                try:
                    transcript = transcript_list.find_transcript([lang]).fetch()
                    lang_used = lang
                    break
                except Exception:
                    continue
            # 再找自动翻译的
            if not transcript:
                for lang in LANG_PRIORITY:
                    try:
                        transcript = transcript_list.find_generated_transcript([lang]).fetch()
                        lang_used = lang
                        break
                    except Exception:
                        continue
        except Exception:
            # 回退到默认
            transcript = api.fetch(video_id)
            lang_used = "default"

        if not transcript:
            return jsonify({"status": "error", "message": "未找到字幕"}), 404

        # 组装纯文本
        raw = transcript.to_raw_data()
        lines = [entry["text"].replace("\n", " ") for entry in raw if entry.get("text")]
        # 去重
        seen = set()
        unique_lines = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)

        # 合并成段落
        subtitle_text = merge_into_paragraphs(unique_lines)

        return jsonify({
            "status": "success",
            "video_id": video_id,
            "title": title,
            "date": date,
            "url": webpage_url,
            "lang": lang_used,
            "subtitle_text": subtitle_text,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:300]}), 500


@app.route("/channel")
def channel_videos():
    """获取频道的所有视频 ID 列表

    参数: ?url=https://youtube.com/@频道名
    返回: { status, channel, video_ids: [...] }
    """
    url = request.args.get("url") or ""
    if not url:
        return jsonify({"status": "error", "message": "缺少 url 参数"}), 400

    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        channel = info.get("channel", info.get("title", "未知频道"))
        entries = info.get("entries", [])
        video_ids = [e["id"] for e in entries if e and e.get("id")]

        return jsonify({
            "status": "success",
            "channel": channel,
            "count": len(video_ids),
            "video_ids": video_ids,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)[:300]}), 500


def merge_into_paragraphs(lines, sentences_per_paragraph=5):
    """将字幕行合并成段落"""
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
