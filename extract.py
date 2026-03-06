"""模块 1：单个视频字幕提取器"""

import sys
import os
import re
import time
import urllib.request
from pathlib import Path

# 项目根目录和输出目录
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# 字幕语言优先级
LANG_PRIORITY = ["zh-Hans", "zh-Hant", "zh", "en"]


def get_video_info_and_subs(url):
    """一次调用获取视频信息和字幕数据"""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": LANG_PRIORITY,
        "subtitlesformat": "json3",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return info


def pick_subtitle_url(info):
    """从视频信息中选出最佳字幕的下载 URL（优先人工字幕）"""
    target_ext = "json3"

    # 先找人工字幕
    manual_subs = info.get("subtitles") or {}
    for lang in LANG_PRIORITY:
        if lang in manual_subs:
            for fmt in manual_subs[lang]:
                if fmt.get("ext") == target_ext:
                    return fmt["url"], lang, False
            # 没有目标格式，取第一个
            if manual_subs[lang]:
                return manual_subs[lang][0]["url"], lang, False

    # 再找自动字幕
    auto_subs = info.get("automatic_captions") or {}
    for lang in LANG_PRIORITY:
        if lang in auto_subs:
            for fmt in auto_subs[lang]:
                if fmt.get("ext") == target_ext:
                    return fmt["url"], lang, True
            if auto_subs[lang]:
                return auto_subs[lang][0]["url"], lang, True

    return None, None, None


def download_subtitle_content(sub_url):
    """直接用 urllib 下载字幕内容"""
    req = urllib.request.Request(sub_url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_subtitle(content):
    """解析字幕内容（自动检测 json3 或 VTT 格式），返回纯文本行列表"""
    # 尝试 json3 格式
    try:
        import json
        data = json.loads(content)
        return parse_json3(data)
    except (json.JSONDecodeError, ValueError):
        pass

    # 回退到 VTT 格式
    return parse_vtt(content)


def parse_json3(data):
    """解析 YouTube json3 格式字幕"""
    texts = []
    seen = set()

    events = data.get("events", [])
    for event in events:
        segs = event.get("segs")
        if not segs:
            continue
        line = "".join(seg.get("utf8", "") for seg in segs).strip()
        line = line.replace("\n", " ")
        if not line:
            continue
        if line not in seen:
            seen.add(line)
            texts.append(line)

    return texts


def parse_vtt(content):
    """解析 VTT 字幕内容，去除时间戳和重复行，返回纯文本行列表"""
    lines = content.split("\n")
    texts = []
    seen = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT"):
            continue
        if line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if line.startswith("NOTE"):
            continue
        # 时间戳行: 00:00:00.000 --> 00:00:00.000
        if re.match(r"\d{2}:\d{2}[:\.].*-->", line):
            continue
        # 数字序号行
        if re.match(r"^\d+$", line):
            continue

        clean = re.sub(r"<[^>]+>", "", line).strip()
        if not clean:
            continue

        if clean not in seen:
            seen.add(clean)
            texts.append(clean)

    return texts


def merge_into_paragraphs(lines, sentences_per_paragraph=5):
    """将字幕行合并成段落，提高可读性"""
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


def safe_filename(video_id, title):
    """生成安全的文件名"""
    safe_title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
    if len(safe_title) > 80:
        safe_title = safe_title[:80]
    return f"{video_id}_{safe_title}.txt"


def format_date(date_str):
    """将 YYYYMMDD 转成 YYYY-MM-DD"""
    if date_str and len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def extract(url):
    """主函数：提取单个视频字幕并保存到 output/ 目录

    返回输出文件路径，失败返回 None
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1. 获取视频信息和字幕数据
    print("正在获取视频信息...")
    info = get_video_info_and_subs(url)
    title = info.get("title", "未知标题")
    video_id = info["id"]
    print(f"视频: {title}")

    # 检查是否已处理
    out_file = OUTPUT_DIR / safe_filename(video_id, title)
    if out_file.exists():
        print(f"已存在，跳过: {out_file.name}")
        return str(out_file)

    # 2. 选择字幕
    sub_url, lang, is_auto = pick_subtitle_url(info)
    if not sub_url:
        print("未找到字幕（该视频可能没有字幕）")
        return None

    sub_type = "自动生成" if is_auto else "人工"
    print(f"找到{sub_type}字幕 ({lang})")

    # 3. 下载字幕内容
    print("正在下载字幕...")
    try:
        vtt_content = download_subtitle_content(sub_url)
    except Exception as e:
        print(f"字幕下载失败: {e}")
        return None

    # 4. 解析字幕
    lines = parse_subtitle(vtt_content)
    if not lines:
        print("字幕内容为空")
        return None

    # 5. 合并成段落并写入文件
    body = merge_into_paragraphs(lines)
    date_display = format_date(info.get("upload_date", "未知日期"))
    video_url = info.get("webpage_url", url)
    content = f"标题：{title}\n发布日期：{date_display}\nURL：{video_url}\n---\n{body}\n"

    out_file.write_text(content, encoding="utf-8")
    print(f"已保存: {out_file.name}")
    return str(out_file)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python extract.py <YouTube视频URL>")
        print('例如: python extract.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"')
        sys.exit(1)

    result = extract(sys.argv[1])
    if result:
        print(f"\n完成！文件保存在: {result}")
    else:
        print("\n提取失败")
        sys.exit(1)
