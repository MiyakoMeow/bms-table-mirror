#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

TIPS_DATA_MD = """
## 使用方式

1. 选择对应难度表的对应链接。
   - 一般建议选择`Gitee直链`，能够确保链接稳定。每小时更新一次。
   - 希望实时获取最新难度表内容，选择`中间链接`下的任一可用链接。
   - 可以将`GitHub中间链接`下的任一可用链接作为备选。同步频率与`Gitee直链`相同。
2. 复制选中链接。请尝试以下两种操作，并确保复制到的链接的域名与显示的相同：
   - a. （在`GitHub`上，或在`Gitee`使用`gitee.com`的链接时）鼠标右键点击链接，选择`复制链接`。
   - b. （在`Gitee`等平台上，打开其它网站的链接时）直接点击链接。
     - 如果弹出“确认跳转”页面，复制页面上显示的链接。
     - 如果直接跳转，复制地址栏链接。如果触发下载任务，复制该任务的下载链接。
   - 确保复制到的链接的域名，与显示的域名相同。如：显示`get.2sb.org`，则复制到的链接应以`https://get.2sb.org`开头。
3. 粘贴到beatoraja/BeMusicSeeker，并在软件内部同步难度表内容。

> 注意，`中间链接`会直接通过中间件从源难度表获取数据。中间件的有效性**取决于难度表自身**。
> 只有难度表`header.json`定义的`data_url`字段是`相对路径`时，中间件才能被正确应用至获取`data.json`的过程中。

## 用于BeMusicSeeker的难度表清单链接：

- （Gitee直链）[gitee.com](https://gitee.com/MiyakoMeow/bms-table-mirror/raw/main/outputs/tables.json)
- （GitHub中间链接）[get.2sb.org](https://get.2sb.org/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- （GitHub中间链接）[gh-proxy.com](https://gh-proxy.com/https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)
- （GitHub直链）[raw.githubusercontent.com](https://github.com/MiyakoMeow/bms-table-mirror/raw/refs/heads/main/outputs/tables.json)

### 用法参考：
- [用法参考/数据来源](https://darksabun.club/table/tablelist.html)
"""

# URL 版页面的提示内容
TIPS_DATA_URL_MD = """
# BMS难度表镜像链接（URL 数组版）

本页按照原有分组（tag_order > tag1 > tag2）组织内容，但不再使用表格。
改为“左右分栏”：左栏为难度表名称清单（文本代码块），右栏为对应链接的 JSON 数组。

使用方式示例：
- 从右栏复制 JSON 数组到 beatoraja / BeMusicSeeker 或其它工具中批量使用。
- 左栏名称清单可用于人工检索与比对。

说明：
- “中间链接”针对各难度表 header.json 中 `url_header_json` 字段，仅在该字段可用时生成。
- “GitHub中间链接”对 `raw.githubusercontent.com` 的仓库直链进行反向代理（保留 get.2sb.org 与 gh-proxy.com 两种）。
"""

# 全局定义：实际使用的反向代理前缀（保持原有两个反向代理）
PROXY_PREFIXES = {
    "2sb": "https://get.2sb.org/",
    "gh_proxy": "https://gh-proxy.com/",
}
# 默认代理前缀供通用中间使用（采用 2sb）
DEFAULT_PROXY_PREFIX = PROXY_PREFIXES["2sb"]
REPO_RAW_PREFIX = "https://raw.githubusercontent.com/"


class UrlProxyModifier:
    """
    中间设置接口类：用于按需修改 URL。
    用户可实现此类以自定义中间规则。
    """

    def modify_url(self, url: str) -> str:
        """返回修改后的 URL。默认直接返回原值。"""
        return url


class PrefixUrlProxyModifier(UrlProxyModifier):
    """基于前缀的中间实现类（默认使用 get.2sb.org）。"""

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


INTERMEDIATE_PROXY_MODIFIERS = {
    "2sb": PrefixUrlProxyModifier(PROXY_PREFIXES["2sb"]),
}

GITHUB_PROXY_MODIFIERS = {
    "2sb": PrefixUrlProxyModifier(PROXY_PREFIXES["2sb"]),
    "gh_proxy": PrefixUrlProxyModifier(PROXY_PREFIXES["gh_proxy"]),
}


def apply_proxy_modifier(data: Any, modifier: UrlProxyModifier) -> Any:
    """递归应用中间修改器到数据结构中的 url 字段。"""
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


def _git_capture(args: list[str]) -> str | None:
    try:
        out = subprocess.check_output(
            args,
            cwd=Path(__file__).resolve().parent.parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _get_owner_repo() -> tuple[str | None, str | None]:
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


def _get_branch() -> str:
    branch = _git_capture(["git", "branch", "--show-current"])
    if branch:
        return branch
    head = _git_capture(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if head:
        m = re.search(r"origin/(?P<branch>.+)$", head)
        if m:
            return m.group("branch")
    return "main"


def to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def escape_md_cell(text: str) -> str:
    # Escape Markdown table separators and normalize newlines
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def make_md_link(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or url
    except Exception:
        domain = url
    return f"[{domain}]({url})"


def html_escape(s: str) -> str:
    """最小化的 HTML 转义（用于 <pre><code> 内部）。"""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def derive_item_links(item: dict[str, Any]) -> dict[str, str]:
    """
    统一派生某个难度表条目的各类链接，供表格版与 URL 数组版复用。
    返回的字典可能包含以下键（若不可用则缺失或为空字符串）：
    - ori: 原链接（url_ori）
    - gitee: 将仓库 raw 链接转换为 gitee raw 链接
    - intermediate:2sb: 针对 header.json 的中间链接（get.2sb.org）
    - github: 仓库 raw 直链（raw.githubusercontent.com）
    - github_proxy:2sb: GitHub raw 的 2sb 反向代理
    - github_proxy:gh_proxy: GitHub raw 的 gh-proxy 反向代理
    """
    url_ori = to_str(item.get("url_ori", ""))
    repo_raw_url = to_str(item.get("url", ""))
    header_url = to_str(item.get("url_header_json", ""))

    out: dict[str, str] = {}
    if url_ori:
        out["ori"] = url_ori

    if repo_raw_url:
        # gitee raw
        gitee_url = GiteeRawUrlProxyModifier().modify_url(repo_raw_url)
        if gitee_url:
            out["gitee"] = gitee_url
        # github raw
        out["github"] = repo_raw_url
        # github proxies
        if repo_raw_url.startswith(REPO_RAW_PREFIX):
            prox_2sb = GITHUB_PROXY_MODIFIERS["2sb"].modify_url(repo_raw_url)
            if prox_2sb:
                out["github_proxy:2sb"] = prox_2sb
            prox_gh = GITHUB_PROXY_MODIFIERS["gh_proxy"].modify_url(repo_raw_url)
            if prox_gh:
                out["github_proxy:gh_proxy"] = prox_gh

    if header_url:
        prox_intermediate = INTERMEDIATE_PROXY_MODIFIERS["2sb"].modify_url(header_url)
        if prox_intermediate:
            out["intermediate:2sb"] = prox_intermediate

    return out


def _group_rows_by_tags(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, list[dict[str, Any]]]]]:
    """按 tag_order > tag1 > tag2 对 rows 进行分组（供多处生成函数复用）。"""
    groups: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    for item in rows:
        tag_order_raw = item.get("tag_order")
        tag_order_key = to_str(tag_order_raw) if tag_order_raw is not None else "N/A"
        tag1 = to_str(item.get("tag1", "")).strip() or "未分类"
        tag2 = to_str(item.get("tag2", "")).strip() or "未分类"
        groups.setdefault(tag_order_key, {}).setdefault(tag1, {}).setdefault(tag2, []).append(item)
    return groups


def generate_data_md(rows: list[dict[str, Any]]) -> str:
    # 使用公共分组逻辑：tag_order > tag1 > tag2（保持原有排序与分组行为）
    groups = _group_rows_by_tags(rows)

    lines: list[str] = []
    lines.append("# BMS难度表镜像")
    lines.extend(TIPS_DATA_MD.splitlines())
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

                # 表头
                lines.append("| 标记 | 难度表名称 | 原链接 | Gitee直链 | 中间链接 | GitHub直链 | GitHub中间链接 |")
                lines.append("| --- | --- | --- | --- | --- | --- | --- |")

                for item in tag2_map[tag2]:
                    symbol_cell = escape_md_cell(to_str(item.get("symbol", "")))
                    name_cell = escape_md_cell(to_str(item.get("name", "")))

                    links = derive_item_links(item)
                    ori_link = make_md_link(links.get("ori", ""))
                    gitee_link = make_md_link(links.get("gitee", ""))
                    github_link = make_md_link(links.get("github", ""))
                    proxy_link = make_md_link(links.get("intermediate:2sb", ""))

                    github_proxy = []
                    if links.get("github_proxy:2sb"):
                        github_proxy.append(make_md_link(links["github_proxy:2sb"]))
                    if links.get("github_proxy:gh_proxy"):
                        github_proxy.append(make_md_link(links["github_proxy:gh_proxy"]))
                    github_proxy_cell = " ".join([p for p in github_proxy if p])

                    lines.append(
                        f"| {symbol_cell} | {name_cell} | {ori_link} | {gitee_link} "
                        f"| {proxy_link} | {github_link} | {github_proxy_cell} |"
                    )

                lines.append("")

    return "\n".join(lines) + "\n"


def _to_int(val: Any) -> Any:
    try:
        return int(str(val).strip())
    except Exception:
        return None


def _sort_tag_order_keys(keys: list[str]) -> list[str]:
    def _key(k: str) -> tuple[int, float, str]:
        i = _to_int(k)
        return (0, float(i), str(k)) if i is not None else (1, float("inf"), str(k))

    return sorted(keys, key=_key)


def _make_dual_column_block(names: list[str], urls: list[str], title: str) -> list[str]:
    """返回一个左右分栏的 HTML 表格代码块（不使用 div）。"""
    if not urls:
        return []
    lines: list[str] = []
    lines.append(f"#### {title}")
    lines.append("")
    names_text = "\n".join(names) if names else ""
    json_text = json.dumps(urls, ensure_ascii=False, indent=2)
    lines.append('<table style="width:100%; table-layout:fixed;">')
    lines.append("<tr>")
    # 左栏：名称清单（文本代码块）
    lines.append('<td style="width:50%; vertical-align:top;">')
    lines.append('<pre><code class="language-text">')
    lines.append(html_escape(names_text))
    lines.append("</code></pre>")
    lines.append("</td>")
    # 右栏：JSON 数组
    lines.append('<td style="width:50%; vertical-align:top;">')
    lines.append('<pre><code class="language-json">')
    lines.append(html_escape(json_text))
    lines.append("</code></pre>")
    lines.append("</td>")
    lines.append("</tr>")
    lines.append("</table>")
    lines.append("")
    return lines


def generate_data_url_md(rows: list[dict[str, Any]]) -> str:
    # 分组：tag_order > tag1 > tag2（共享派生链接，复用公共分组函数）
    groups = _group_rows_by_tags(rows)

    out_lines: list[str] = []
    out_lines.extend(TIPS_DATA_URL_MD.splitlines())
    out_lines.append("")

    # 展示顺序（与表格版一致）
    order_keys = [
        "ori",
        "gitee",
        "intermediate:2sb",
        "github",
        "github_proxy:2sb",
        "github_proxy:gh_proxy",
    ]

    def _display_name_for_key(k: str) -> str:
        if k == "ori":
            return "原链接"
        if k == "gitee":
            return "Gitee直链"
        if k == "intermediate:2sb":
            return "中间链接 (get.2sb.org)"
        if k == "github":
            return "GitHub直链"
        if k == "github_proxy:2sb":
            return "GitHub中间链接 (get.2sb.org)"
        if k == "github_proxy:gh_proxy":
            return "GitHub中间链接 (gh-proxy.com)"
        return k

    for tag_order in _sort_tag_order_keys(list(groups.keys())):
        tag1_map = groups[tag_order]
        for tag1 in sorted(tag1_map.keys(), key=lambda s: (s == "未分类", s)):
            out_lines.append(f"## {tag_order} - {tag1}")
            out_lines.append("")

            tag2_map = tag1_map[tag1]
            for tag2 in sorted(tag2_map.keys(), key=lambda s: (s == "未分类", s)):
                out_lines.append(f"### {tag2}")
                out_lines.append("")

                # 收集名称与 URL
                names_by_key: dict[str, list[str]] = {k: [] for k in order_keys}
                urls_by_key: dict[str, list[str]] = {k: [] for k in order_keys}

                for item in tag2_map[tag2]:
                    name = to_str(item.get("name", "")).strip() or "(未命名)"
                    links = derive_item_links(item)

                    for key in order_keys:
                        url = links.get(key, "")
                        if url:
                            names_by_key[key].append(name)
                            urls_by_key[key].append(url)

                for key in order_keys:
                    block_lines = _make_dual_column_block(
                        names_by_key.get(key, []),
                        urls_by_key.get(key, []),
                        _display_name_for_key(key),
                    )
                    out_lines.extend(block_lines)

    return "\n".join(out_lines) + "\n"


def load_rows_from_tables(tables_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
        raw_url = f"{base_raw}/{owner}/{repo}/{branch}/tables/{encoded_child}/header.json"

        obj["url_ori"] = to_str(obj.get("url", ""))
        obj["url"] = raw_url
        rows.append(obj)

    return rows


def build_proxy_maps(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}

    # 反向中间（2sb 与 gh-proxy）：直接中间 info.json 中的 url_header_json 字段
    for label, prefix in PROXY_PREFIXES.items():
        modifier = PrefixUrlProxyModifier(prefix)
        name_to_url: dict[str, str] = {}
        for item in rows:
            name = to_str(item.get("name", ""))
            header_url = to_str(item.get("url_header_json", ""))
            if not (name and header_url):
                continue
            proxied = modifier.modify_url(header_url)
            if proxied:
                name_to_url[name] = proxied
        result[label] = name_to_url

    # gitee：将仓库的 raw 链接转换为 gitee raw
    gitee_modifier = GiteeRawUrlProxyModifier()
    name_to_gitee: dict[str, str] = {}
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


def write_data_md(rows: list[dict[str, Any]], tables_dir: Path, out_md_path: Path) -> None:
    """
    基于读取到的 rows，生成表格版 Markdown 并写入到指定路径。

    - 自动构建中间映射并生成表格内容；
    - 确保输出目录存在；
    - 写入完成后输出简要日志。
    """
    proxy_maps_by_label = build_proxy_maps(rows)
    md_table = generate_data_md(rows)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    with out_md_path.open("w", encoding="utf-8") as f:
        f.write(md_table)
    proxies_list = ", ".join(sorted(proxy_maps_by_label.keys()))
    print(f"[OK] 写入 {out_md_path}，共 {len(rows)} 行数据。基础: {tables_dir}；中间生成: [{proxies_list}]")


def write_data_url_md(rows: list[dict[str, Any]], tables_dir: Path, out_url_path: Path) -> None:
    """
    基于读取到的 rows，生成 URL 数组版 Markdown 并写入到指定路径。

    - 生成右栏 JSON 数组并与名称清单组成左右分栏；
    - 确保输出目录存在；
    - 写入完成后输出简要日志。
    """
    md_url = generate_data_url_md(rows)
    out_url_path.parent.mkdir(parents=True, exist_ok=True)
    with out_url_path.open("w", encoding="utf-8") as f:
        f.write(md_url)
    print(f"[OK] 写入 {out_url_path}，共 {len(rows)} 行数据。基础: {tables_dir}；中间生成: [2sb, gh_proxy, gitee]")


def _write_json(output_path: Path, data: Any) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_tables_outputs(rows: list[dict[str, Any]], outputs_dir: Path | None = None) -> None:
    """写出 outputs 下的 tables.json 及代理变体（合并原 gen_tables.py 逻辑）。

    - `tables.json`：包含 info.json 的字段，且 `url` 为仓库 raw 直链，`url_ori`为原字段。
    - `tables_2sb.json` / `tables_gh_proxy.json`：对 `url` 应用前缀代理。
    - `tables_gitee.json`：将 GitHub raw 直链转换为 gitee raw 直链。
    """
    base = outputs_dir or Path(__file__).resolve().parent.parent / "outputs"
    base.mkdir(parents=True, exist_ok=True)

    # 原始聚合（raw.githubusercontent.com 直链）
    out_tables = base / "tables.json"
    _write_json(out_tables, rows)
    print(f"[OK] 写入 {out_tables}，共 {len(rows)} 条。")

    # 代理变体映射
    mapping: dict[Path, UrlProxyModifier] = {
        base / "tables_2sb.json": PrefixUrlProxyModifier(PROXY_PREFIXES["2sb"]),
        base / "tables_gh_proxy.json": PrefixUrlProxyModifier(PROXY_PREFIXES["gh_proxy"]),
        base / "tables_gitee.json": GiteeRawUrlProxyModifier(),
    }

    for output_path, modifier in mapping.items():
        proxied = apply_proxy_modifier(rows, modifier)
        _write_json(output_path, proxied)
        msg_prefix = modifier.prefix if isinstance(modifier, PrefixUrlProxyModifier) else ""
        print(f"Wrote {output_path} with UrlProxyModifier ({modifier.__class__.__name__}, prefix: {msg_prefix})")


def main() -> None:
    args = sys.argv[1:]
    # Defaults: read base from tables/*/info.json; write to repo-root DATA.md
    tables_dir = Path(args[0]) if len(args) >= 1 else Path("tables")
    base_output = Path(args[1]) if len(args) >= 2 else Path("DATA.md")

    # 始终生成两个文件：表格版和 URL 数组版；基于传入路径决定输出目录
    out_dir = base_output.parent
    if "URL" in base_output.name.upper():
        out_url_path = base_output
        out_md_path = out_dir / "DATA.md"
    else:
        out_md_path = base_output
        out_url_path = out_dir / "DATA_URL.md"

    rows = load_rows_from_tables(tables_dir)

    # 生成并写入表格版（输出函数1）
    write_data_md(rows, tables_dir, out_md_path)

    # 生成并写入 URL 数组版（输出函数2）
    write_data_url_md(rows, tables_dir, out_url_path)

    # 生成 outputs 下的 tables*.json（输出函数3，沿用原有实现）
    generate_tables_outputs(rows)


if __name__ == "__main__":
    main()
