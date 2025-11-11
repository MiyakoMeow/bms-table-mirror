#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

TIPS = """
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


# 仅对 header.json 的“中间链接”使用 2sb
INTERMEDIATE_PROXY_MODIFIERS = {
    "2sb": PrefixUrlProxyModifier(PROXY_PREFIXES["2sb"]),
}

# 对 GitHub raw 仓库直链使用两个反向代理
GITHUB_PROXY_MODIFIERS = {
    "2sb": PrefixUrlProxyModifier(PROXY_PREFIXES["2sb"]),
    "gh_proxy": PrefixUrlProxyModifier(PROXY_PREFIXES["gh_proxy"]),
}


def to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def html_escape(s: str) -> str:
    """最小化的 HTML 转义（用于 <pre><code> 内部）。"""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def generate_url_md(rows: list[dict[str, Any]]) -> str:
    # 分组：tag_order > tag1 > tag2
    groups: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    for item in rows:
        tag_order_raw = item.get("tag_order")
        tag_order_key = to_str(tag_order_raw) if tag_order_raw is not None else "N/A"
        tag1 = to_str(item.get("tag1", "")).strip() or "未分类"
        tag2 = to_str(item.get("tag2", "")).strip() or "未分类"
        groups.setdefault(tag_order_key, {}).setdefault(tag1, {}).setdefault(tag2, []).append(item)

    out_lines: list[str] = []
    out_lines.extend(TIPS.splitlines())
    out_lines.append("")

    # 预先定义展示顺序（按列的语义顺序）
    order_keys = [
        "ori",
        "gitee",
        "intermediate:2sb",
        "github",
        "github_proxy:2sb",
        "github_proxy:gh_proxy",
    ]

    # 显示名称映射（根据 key）
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

    gitee_modifier = GiteeRawUrlProxyModifier()

    for tag_order in _sort_tag_order_keys(list(groups.keys())):
        tag1_map = groups[tag_order]
        for tag1 in sorted(tag1_map.keys(), key=lambda s: (s == "未分类", s)):
            out_lines.append(f"## {tag_order} - {tag1}")
            out_lines.append("")

            tag2_map = tag1_map[tag1]
            for tag2 in sorted(tag2_map.keys(), key=lambda s: (s == "未分类", s)):
                out_lines.append(f"### {tag2}")
                out_lines.append("")

                # 为当前小组收集各链接类型的名称与 URL
                names_by_key: dict[str, list[str]] = {k: [] for k in order_keys}
                urls_by_key: dict[str, list[str]] = {k: [] for k in order_keys}

                for item in tag2_map[tag2]:
                    name = to_str(item.get("name", "")).strip()
                    if not name:
                        name = "(未命名)"
                    url_ori = to_str(item.get("url_ori", ""))
                    repo_raw_url = to_str(item.get("url", ""))
                    header_url = to_str(item.get("url_header_json", ""))

                    # 原链接
                    if url_ori:
                        names_by_key["ori"].append(name)
                        urls_by_key["ori"].append(url_ori)

                    # Gitee 直链（仓库 raw 转换）
                    if repo_raw_url:
                        gitee_url = gitee_modifier.modify_url(repo_raw_url)
                        if gitee_url:
                            names_by_key["gitee"].append(name)
                            urls_by_key["gitee"].append(gitee_url)

                    # 中间链接（header.json，经 2sb 反向代理）
                    if header_url:
                        proxied = INTERMEDIATE_PROXY_MODIFIERS["2sb"].modify_url(header_url)
                        if proxied:
                            names_by_key["intermediate:2sb"].append(name)
                            urls_by_key["intermediate:2sb"].append(proxied)

                    # GitHub 直链（仓库 raw 到 header.json）
                    if repo_raw_url:
                        names_by_key["github"].append(name)
                        urls_by_key["github"].append(repo_raw_url)

                    # GitHub 中间链接（2sb 与 gh-proxy）
                    if repo_raw_url.startswith(REPO_RAW_PREFIX):
                        prox_2sb = GITHUB_PROXY_MODIFIERS["2sb"].modify_url(repo_raw_url)
                        if prox_2sb:
                            names_by_key["github_proxy:2sb"].append(name)
                            urls_by_key["github_proxy:2sb"].append(prox_2sb)
                        prox_gh = GITHUB_PROXY_MODIFIERS["gh_proxy"].modify_url(repo_raw_url)
                        if prox_gh:
                            names_by_key["github_proxy:gh_proxy"].append(name)
                            urls_by_key["github_proxy:gh_proxy"].append(prox_gh)

                # 依次输出各链接类型的分栏块
                for key in order_keys:
                    block_lines = _make_dual_column_block(
                        names_by_key.get(key, []),
                        urls_by_key.get(key, []),
                        _display_name_for_key(key),
                    )
                    out_lines.extend(block_lines)

    return "\n".join(out_lines) + "\n"


def main() -> None:
    args = sys.argv[1:]
    # 默认：tables/*/info.json + header.json -> 写到仓库根目录 DATA_URL.md
    tables_dir = Path(args[0]) if len(args) >= 1 else Path("tables")
    output_path = Path(args[1]) if len(args) >= 2 else Path("DATA_URL.md")

    rows = load_rows_from_tables(tables_dir)
    md = generate_url_md(rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write(md)

    print(f"[OK] 写入 {output_path}，共 {len(rows)} 行数据。基础: {tables_dir}")


if __name__ == "__main__":
    main()
