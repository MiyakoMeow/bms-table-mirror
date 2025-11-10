#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_PREFIX = "https://get.2sb.org/"


def to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def escape_md_cell(text: str) -> str:
    # Escape Markdown table separators and normalize newlines
    return (
        text.replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def make_proxy_url(url: str, prefix: str) -> str:
    if not url:
        return ""
    return url if url.startswith(prefix) else prefix + url


def generate_md(rows: List[Dict[str, Any]], prefix: str) -> str:
    lines = []
    # Header
    lines.append("| symbol | name | url | url_proxy |")
    lines.append("| --- | --- | --- | --- |")

    for item in rows:
        symbol = escape_md_cell(to_str(item.get("symbol", "")))
        name = escape_md_cell(to_str(item.get("name", "")))
        url = to_str(item.get("url", ""))
        url_proxy = make_proxy_url(url, prefix)

        # For URL columns, we usually don't need to escape pipes, but do anyway for safety
        url_cell = escape_md_cell(url)
        url_proxy_cell = escape_md_cell(url_proxy)

        lines.append(f"| {symbol} | {name} | {url_cell} | {url_proxy_cell} |")

    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    # Defaults: read from outputs/tables.json and write to repo-root DATA.md
    input_path = Path(args[0]) if len(args) >= 1 else Path("outputs/tables.json")
    output_path = Path(args[1]) if len(args) >= 2 else Path("DATA.md")
    prefix = args[2] if len(args) >= 3 else DEFAULT_PREFIX

    if not input_path.exists():
        print(f"[ERROR] 输入文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] 读取/解析 JSON 失败: {input_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print(f"[ERROR] JSON 根节点应为数组: {input_path}", file=sys.stderr)
        sys.exit(1)

    md = generate_md(data, prefix)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(md)

    print(f"[OK] 写入 {output_path}，共 {len(data)} 行数据。代理前缀: {prefix}")


if __name__ == "__main__":
    main()
