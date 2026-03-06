"""模块 1：单个视频字幕提取（通过 Railway API）"""

import sys
import re
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
API_BASE = "https://youtube-kb-production-45f3.up.railway.app"


def safe_filename(video_id, title):
    """生成安全的文件名"""
    safe_title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    if len(safe_title) > 80:
        safe_title = safe_title[:80]
    return f"{video_id}_{safe_title}.json"


def extract(url_or_id):
    """提取单个视频字幕，保存 JSON 到 output/ 并导入数据库

    返回 API 返回的数据 dict，失败返回 None
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 构造 API URL
    if "youtube.com" in url_or_id or "youtu.be" in url_or_id:
        api_url = f"{API_BASE}/extract?url={urllib.parse.quote(url_or_id)}"
    else:
        api_url = f"{API_BASE}/extract?video_id={url_or_id}"

    print("正在提取字幕...")
    try:
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"API 请求失败: {e}")
        return None

    if data.get("status") != "success":
        print(f"提取失败: {data.get('message', '未知错误')}")
        return None

    video_id = data["video_id"]
    title = data["title"]
    print(f"视频: {title}")
    print(f"字幕语言: {data.get('lang', '未知')}")

    # 保存 JSON
    out_file = OUTPUT_DIR / safe_filename(video_id, title)
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存: {out_file.name}")

    # 直接导入数据库
    from database import import_from_json
    if import_from_json(data):
        print("已导入数据库")
    else:
        print("数据库中已存在，跳过")

    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python extract.py <YouTube视频URL或ID>")
        print('例如: python extract.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"')
        sys.exit(1)

    result = extract(sys.argv[1])
    if result:
        print(f"\n完成！")
    else:
        print("\n提取失败")
        sys.exit(1)
