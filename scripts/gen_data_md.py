#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse, quote, unquote
import subprocess
import re

TIPS = """
## 使用方式

1. 选择对应难度表的对应链接。如果不知道怎么选择，请往下看。
2. 鼠标右键该链接 -> 复制链接。
3. 粘贴到beatoraja/BeMusicSeeker，并在软件内部同步难度表内容。

### 如何选择链接？
- 一般建议选择`gitee.com`，能够确保链接稳定。每小时更新一次。
- 希望实时同步，选择`代理链接`下的任一可用链接。
> 注意，`代理链接`的有效性取决于难度表。
> 只有难度表`header.json`定义的`data_url`字段是相对链接时，代理才能被正确应用至获取`data.json`的过程中。

## 用于BeMusicSeeker的难度表清单链接：

- [raw.githubusercontent.com](https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [get.2sb.org](https://get.2sb.org/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [gh-proxy.com](https://gh-proxy.com/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- [gitee.com](https://gitee.com/MiyakoMeow/bms-table-mirror/raw/main/outputs/tables.json)

### 用法参考：
- [用法参考/数据来源](https://darksabun.club/table/tablelist.html)
"""

DEFAULT_PROXY_PREFIX = "https://get.2sb.org/"


class UrlProxyModifier:
    """
    代理设置接口类：用于按需修改 URL。
    用户可实现此类以自定义代理规则。
    """

    def modify_url(self, url: str) -> str:
        """返回修改后的 URL。默认直接返回原值。"""
        return url


class PrefixUrlProxyModifier(UrlProxyModifier):
    """基于前缀的代理实现类（默认使用 get.2sb.org）。"""

    def __init__(self, prefix: str = DEFAULT_PROXY_PREFIX):
        self.prefix = prefix

    def modify_url(self, url: str) -> str:
        if not isinstance(url, str) or not url:
            return url
        return url if url.startswith(self.prefix) else self.prefix + url


class GiteeRawUrlProxyModifier(UrlProxyModifier):
    """
    将 GitHub raw 链接转换为 gitee raw 格式：
    https://raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>
      -> https://gitee.com/<owner>/<repo>/raw/<branch>/<path>

    仅在匹配到 raw.githubusercontent.com 时执行转换，否则原样返回。
    为避免特殊字符（括号、全角符号、非 ASCII 等）在不同平台处理不一致，
    会先对路径进行一次反解码再以 RFC 3986 规范重新编码（保留 "/-._~" 与路径分隔符）。
    """

    def modify_url(self, url: str) -> str:
        if not isinstance(url, str) or not url:
            return url
        m = re.match(
            r"^https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.*)$",
            url,
        )
        if not m:
            return url
        owner, repo, branch, rest = m.groups()
        rest_decoded = unquote(rest)
        rest_encoded = quote(rest_decoded, safe="/-._~")
        return f"https://gitee.com/{owner}/{repo}/raw/{branch}/{rest_encoded}"


def apply_proxy_modifier(data: Any, modifier: UrlProxyModifier):
    """递归应用代理修改器到数据结构中的 url 字段。"""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key == "url" and isinstance(value, str):
                result[key] = modifier.modify_url(value)
            else:
                result[key] = apply_proxy_modifier(value, modifier)
        return result
    if isinstance(data, list):
        return [apply_proxy_modifier(item, modifier) for item in data]
    return data


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
                    for label, name_to_url in sorted(proxy_maps_by_label.items()):
                        # gitee 链接将被放入“仓库链接”列，不在“代理链接”中展示
                        if label == "gitee":
                            continue
                        u = to_str(name_to_url.get(name_raw, ""))
                        if u:
                            proxy_links.append(make_md_link(u))

                    # 使用域名作为显示文本
                    ori_link = make_md_link(url_ori)
                    # 仓库链接：先放 gitee.com，再放 raw.githubusercontent.com
                    gitee_url = GiteeRawUrlProxyModifier().modify_url(url_repo)
                    gitee_link = make_md_link(gitee_url) if gitee_url else ""
                    repo_link = " ".join(
                        [s for s in [gitee_link, make_md_link(url_repo)] if s]
                    )
                    proxy_link = " ".join(proxy_links) if proxy_links else ""

                    lines.append(
                        f"| {symbol_cell} | {name_cell} | {ori_link} | {repo_link} | {proxy_link} |"
                    )

                # Blank line between groups
                lines.append("")

    return "\n".join(lines) + "\n"


def _git_capture(args):
    try:
        out = subprocess.check_output(
            args,
            cwd=Path(__file__).resolve().parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _get_owner_repo():
    url = _git_capture(["git", "config", "--get", "remote.origin.url"])
    if not url:
        return None, None
    m = re.search(
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
        url.strip(),
    )
    if not m:
        return None, None
    return m.group("owner"), m.group("repo")


def _get_branch():
    branch = _git_capture(["git", "branch", "--show-current"])
    if branch:
        return branch
    head = _git_capture(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if head:
        m = re.search(r"origin/(?P<branch>.+)$", head)
        if m:
            return m.group("branch")
    return "main"


def load_rows_from_tables(tables_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not tables_dir.is_dir():
        print(f"[ERROR] tables 目录不存在: {tables_dir}", file=sys.stderr)
        sys.exit(1)

    owner, repo = _get_owner_repo()
    branch = _get_branch()
    base_raw = "https://raw.githubusercontent.com"

    for child in sorted(tables_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue

        info_path = child / "info.json"
        header_path = child / "header.json"
        if not header_path.is_file():
            print(f"[INFO] 缺少 header.json: {header_path}", file=sys.stderr)
            continue

        if not info_path.is_file():
            print(f"[INFO] 缺少 info.json: {info_path}", file=sys.stderr)
            continue

        try:
            obj = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] 解析失败: {info_path}: {e}", file=sys.stderr)
            continue

        if not (owner and repo):
            print(f"[WARN] 无法获取 Git 仓库信息，跳过: {child}", file=sys.stderr)
            continue

        encoded_child = quote(child.name, safe="-._~")
        raw_url = (
            f"{base_raw}/{owner}/{repo}/{branch}/tables/{encoded_child}/header.json"
        )

        obj["url_ori"] = to_str(obj.get("url", ""))
        obj["url"] = raw_url
        rows.append(obj)

    return rows


def build_proxy_maps(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}

    # 反向代理（2sb 与 gh-proxy）：直接代理 info.json 中的 header_json_url 字段
    for label, prefix in (
        ("2sb", "https://get.2sb.org/"),
        ("gh_proxy", "https://gh-proxy.com/"),
    ):
        modifier = PrefixUrlProxyModifier(prefix)
        name_to_url: Dict[str, str] = {}
        for item in rows:
            name = to_str(item.get("name", ""))
            header_url = to_str(item.get("header_json_url", ""))
            if not (name and header_url):
                continue
            proxied = modifier.modify_url(header_url)
            if proxied:
                name_to_url[name] = proxied
        result[label] = name_to_url

    # gitee：将仓库的 raw 链接转换为 gitee raw
    gitee_modifier = GiteeRawUrlProxyModifier()
    name_to_gitee: Dict[str, str] = {}
    for item in rows:
        name = to_str(item.get("name", ""))
        repo_raw_url = to_str(item.get("url", ""))
        if not (name and repo_raw_url):
            continue
        gitee_url = gitee_modifier.modify_url(repo_raw_url)
        if gitee_url:
            name_to_gitee[name] = gitee_url
    result["gitee"] = name_to_gitee

    return result


def main():
    args = sys.argv[1:]
    # Defaults: read base from tables/*/info.json; write to repo-root DATA.md
    tables_dir = Path(args[0]) if len(args) >= 1 else Path("tables")
    output_path = Path(args[1]) if len(args) >= 2 else Path("DATA.md")

    rows = load_rows_from_tables(tables_dir)
    proxy_maps_by_label = build_proxy_maps(rows)

    md = generate_md(rows, proxy_maps_by_label)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(md)

    proxies_list = ", ".join(sorted(proxy_maps_by_label.keys()))
    print(
        f"[OK] 写入 {output_path}，共 {len(rows)} 行数据。基础: {tables_dir}；代理生成: [{proxies_list}]"
    )


if __name__ == "__main__":
    main()
