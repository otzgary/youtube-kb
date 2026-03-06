"""Railway 测试服务：验证能否访问 YouTube 字幕"""

from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def index():
    return "YouTube 知识库 - 服务运行中"


@app.route("/test")
def test_youtube():
    """测试能否从 YouTube 获取字幕"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        transcript = api.fetch("dQw4w9WgXcQ")
        data = transcript.to_raw_data()
        return jsonify({
            "status": "success",
            "message": f"成功获取 {len(data)} 条字幕",
            "sample": data[:3],
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)[:200],
        }), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
