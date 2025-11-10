#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

TIPS = """
## 使用方式

1. 选择对应难度表的对应链接。
2. 鼠标右键该链接 -> 复制链接。
3. 粘贴到beatoraja/BeMusicSeeker，并在软件内部同步难度表内容。

> 国内用户推荐使用下方的“代理链接”部分。
> 
> 偏好更新速度选反代（2sb或gh-proxy），偏好稳定连接选Gitee。

## 用于BeMusicSeeker的难度表清单链接：

- [raw.githubusercontent.com](https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [get.2sb.org](https://get.2sb.org/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [gh-proxy.com](https://gh-proxy.com/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [gitee.com](https://gitee.com/MiyakoMeow/bms-table-mirror/raw/main/outputs/tables.json)

### 用法参考：
- [用法参考/数据来源](https://darksabun.club/table/tablelist.html)
"""


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


def make_md_link(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or url
    except Exception:
        domain = url
    return f"[{domain}]({url})"


def generate_md(
    rows: List[Dict[str, Any]], proxy_maps_by_label: Dict[str, Dict[str, str]]
) -> str:
    # Group rows by tag_order > tag1 > tag2
    def _to_int(val: Any) -> Any:
        try:
            return int(str(val).strip())
        except Exception:
            return None

    groups: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}
    for item in rows:
        tag_order_raw = item.get("tag_order")
        tag_order_key = to_str(tag_order_raw) if tag_order_raw is not None else "N/A"
        tag1 = to_str(item.get("tag1", "")).strip() or "未分类"
        tag2 = to_str(item.get("tag2", "")).strip() or "未分类"
        groups.setdefault(tag_order_key, {}).setdefault(tag1, {}).setdefault(
            tag2, []
        ).append(item)

    # Sort tag_order keys: numeric first (ascending), then non-numeric
    def _sort_tag_order_keys(keys: List[str]) -> List[str]:
        def _key(k: str):
            i = _to_int(k)
            return (
                (0, i if i is not None else 0, str(k))
                if i is not None
                else (1, float("inf"), str(k))
            )

        return sorted(keys, key=_key)

    lines: List[str] = []
    # Top-level title
    lines.append("# BMS难度表镜像")
    lines.extend(TIPS.splitlines())
    lines.append("")

    for tag_order in _sort_tag_order_keys(list(groups.keys())):
        tag1_map = groups[tag_order]
        for tag1 in sorted(tag1_map.keys(), key=lambda s: (s == "未分类", s)):
            lines.append(f"## {tag_order} - {tag1}")
            lines.append("")

            tag2_map = tag1_map[tag1]
            for tag2 in sorted(tag2_map.keys(), key=lambda s: (s == "未分类", s)):
                lines.append(f"### {tag2}")
                lines.append("")

                # Table header for each group
                lines.append("| 标记 | 难度表名称 | 原链接 | 仓库链接 | 代理链接 |")
                lines.append("| --- | --- | --- | --- | --- |")

                for item in tag2_map[tag2]:
                    symbol_cell = escape_md_cell(to_str(item.get("symbol", "")))
                    name_raw = to_str(item.get("name", ""))
                    name_cell = escape_md_cell(name_raw)

                    url_ori = to_str(item.get("url_ori", ""))
                    url_repo = to_str(item.get("url", ""))

                    # Build proxy links labeled by their xxx derived from filename
                    proxy_links: List[str] = []
                    for _label, name_to_url in sorted(proxy_maps_by_label.items()):
                        u = to_str(name_to_url.get(name_raw, ""))
                        if u:
                            proxy_links.append(make_md_link(u))

                    # 使用域名作为显示文本
                    ori_link = make_md_link(url_ori)
                    repo_link = make_md_link(url_repo)
                    proxy_link = " ".join(proxy_links) if proxy_links else ""

                    lines.append(
                        f"| {symbol_cell} | {name_cell} | {ori_link} | {repo_link} | {proxy_link} |"
                    )

                # Blank line between groups
                lines.append("")

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
