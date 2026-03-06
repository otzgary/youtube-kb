"""模块 4a：命令行搜索"""

import sys
from database import search


def main():
    if len(sys.argv) < 2:
        print("用法: python search_cli.py <关键词>")
        print('例如: python search_cli.py "never gonna"')
        sys.exit(1)

    keyword = sys.argv[1]
    results = search(keyword)

    if not results:
        print(f"没有找到与 \"{keyword}\" 相关的内容")
        return

    print(f"找到 {len(results)} 条结果:\n")

    for i, (vid, title, date, url, snippet) in enumerate(results, 1):
        print(f"[{i}] {title} ({date})")
        print(f"    {snippet}")
        print(f"    {url}")
        print()


if __name__ == "__main__":
    main()
