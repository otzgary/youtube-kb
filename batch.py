"""模块 2：频道批量处理（通过 Railway API）"""

import sys
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from extract import extract, OUTPUT_DIR

API_BASE = "https://youtube-kb-production-45f3.up.railway.app"


def get_channel_videos(channel_url):
    """获取频道的所有视频 ID 列表"""
    api_url = f"{API_BASE}/channel?url={urllib.parse.quote(channel_url)}"

    print(f"正在获取频道视频列表...")
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("status") != "success":
        raise Exception(data.get("message", "获取频道信息失败"))

    print(f"频道: {data['channel']}")
    print(f"视频总数: {data['count']}")
    return data["video_ids"]


def batch_extract(channel_url, delay=2):
    """批量提取频道所有视频的字幕

    Args:
        channel_url: YouTube 频道 URL
        delay: 每个视频之间的间隔秒数，避免限流
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 获取视频列表
    video_ids = get_channel_videos(channel_url)

    # 统计
    total = len(video_ids)
    success = 0
    skipped = 0
    failed = []

    for i, vid in enumerate(video_ids, 1):
        print(f"\n[{i}/{total}] 处理视频: {vid}")

        try:
            result = extract(vid)
            if result:
                success += 1
            else:
                failed.append(vid)
        except Exception as e:
            print(f"  出错: {e}")
            failed.append(vid)

        # 间隔，避免限流（最后一个不用等）
        if i < total:
            time.sleep(delay)

    # 汇总
    print(f"\n{'='*50}")
    print(f"处理完成！")
    print(f"  成功: {success}")
    print(f"  失败: {len(failed)}")
    print(f"  总计: {total}")

    if failed:
        print(f"\n失败的视频 ID:")
        for vid in failed:
            print(f"  - {vid}")
        # 保存失败列表
        fail_file = OUTPUT_DIR / "_failed.txt"
        fail_file.write_text("\n".join(failed), encoding="utf-8")
        print(f"失败列表已保存到: {fail_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python batch.py <YouTube频道URL>")
        print('例如: python batch.py "https://www.youtube.com/@频道名"')
        sys.exit(1)

    batch_extract(sys.argv[1])
