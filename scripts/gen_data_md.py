#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


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


def make_md_link(label: str, url: str) -> str:
    if not url:
        return ""
    return f"[{label}]({url})"


def generate_md(
    rows: List[Dict[str, Any]], proxy_maps_by_label: Dict[str, Dict[str, str]]
) -> str:
    lines = []
    # Header (Chinese column names as requested)
    lines.append("| 标记 | 难度表名称 | 原链接 | 仓库链接 | 代理链接 |")
    lines.append("| --- | --- | --- | --- | --- |")

    for item in rows:
        symbol_cell = escape_md_cell(to_str(item.get("symbol", "")))
        name_raw = to_str(item.get("name", ""))
        name_cell = escape_md_cell(name_raw)

        url_ori = to_str(item.get("url_ori", ""))
        url_repo = to_str(item.get("url", ""))
        # Build proxy links labeled by their xxx derived from filename
        proxy_links: List[str] = []
        for label, name_to_url in sorted(proxy_maps_by_label.items()):
            u = to_str(name_to_url.get(name_raw, ""))
            if u:
                proxy_links.append(make_md_link(label, u))

        # Use markdown link syntax to avoid displaying long URLs directly
        ori_link = make_md_link("原", url_ori)
        repo_link = make_md_link("仓库", url_repo)
        proxy_link = " ".join(proxy_links) if proxy_links else ""

        lines.append(
            f"| {symbol_cell} | {name_cell} | {ori_link} | {repo_link} | {proxy_link} |"
        )

    return "\n".join(lines) + "\n"


def _derive_label(path: Path) -> str:
    stem = path.stem
    if stem.startswith("tables_"):
        return stem[len("tables_") :]
    if stem.startswith("table_"):
        return stem[len("table_") :]
    return stem


def _scan_proxy_files(proxies_dir: Path) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    if not proxies_dir.exists():
        return mapping
    # Support both patterns: tables_*.json and table_*.json
    for p in proxies_dir.glob("tables_*.json"):
        if p.name == "tables.json":
            continue
        mapping[_derive_label(p)] = p
    for p in proxies_dir.glob("table_*.json"):
        mapping[_derive_label(p)] = p
    return mapping


def main():
    args = sys.argv[1:]
    # Defaults: read base from outputs/tables.json; auto-scan proxies in outputs; write to repo-root DATA.md
    input_path = Path(args[0]) if len(args) >= 1 else Path("outputs/tables.json")
    output_path = Path(args[1]) if len(args) >= 2 else Path("DATA.md")
    proxies_dir = Path(args[2]) if len(args) >= 3 else Path("outputs")

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
        print(f"[ERROR] 基础 JSON 根节点应为数组: {input_path}", file=sys.stderr)
        sys.exit(1)

    proxy_files = _scan_proxy_files(proxies_dir)
    proxy_maps_by_label: Dict[str, Dict[str, str]] = {}
    for label, path in proxy_files.items():
        try:
            with path.open("r", encoding="utf-8") as f:
                arr = json.load(f)
            if isinstance(arr, list):
                name_to_url: Dict[str, str] = {}
                for item in arr:
                    name = to_str(item.get("name", ""))
                    url = to_str(item.get("url", ""))
                    if name and url:
                        name_to_url[name] = url
                proxy_maps_by_label[label] = name_to_url
        except Exception as e:
            print(f"[WARN] 读取代理文件失败: {path}: {e}", file=sys.stderr)

    md = generate_md(data, proxy_maps_by_label)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(md)

    proxies_list = ", ".join(
        [f"{lbl}:{p.name}" for lbl, p in sorted(proxy_files.items())]
    )
    print(
        f"[OK] 写入 {output_path}，共 {len(data)} 行数据。基础: {input_path}；代理扫描目录: {proxies_dir}；已加载: [{proxies_list}]"
    )


if __name__ == "__main__":
    main()
