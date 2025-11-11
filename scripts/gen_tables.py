#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

repo_root = Path(__file__).resolve().parent.parent
tables_dir = repo_root / "tables"
outputs_dir = repo_root / "outputs"

DEFAULT_PROXY_PREFIX = "https://get.2sb.org/"


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
        # 统一规范：先反解码，再按 RFC 3986 重新编码，避免括号等字符在 gitee 上解析异常
        rest_decoded = unquote(rest)
        rest_encoded = quote(rest_decoded, safe="/-._~")
        return f"https://gitee.com/{owner}/{repo}/raw/{branch}/{rest_encoded}"


def setup():
    outputs_dir.mkdir(parents=True, exist_ok=True)

    if not tables_dir.is_dir():
        print(f"[ERROR] tables 目录不存在: {tables_dir}", file=sys.stderr)
        sys.exit(1)


def _git_capture(args):
    try:
        out = subprocess.check_output(args, cwd=repo_root, stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _get_owner_repo():
    url = _git_capture(["git", "config", "--get", "remote.origin.url"])
    if not url:
        return None, None
    m = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", url.strip())
    if not m:
        return None, None
    owner = m.group("owner")
    repo = m.group("repo")
    return owner, repo


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


def generate_tables_json():
    aggregated = []
    missing_info = []
    invalid_info = []
    missing_header = []

    owner, repo = _get_owner_repo()
    branch = _get_branch()
    # 用户要求使用 raw.githubusercontent.com
    base_raw = "https://raw.githubusercontent.com"

    for child in sorted(tables_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue

        info_path = child / "info.json"
        header_path = child / "header.json"
        if not header_path.is_file():
            missing_header.append(str(header_path))
            continue

        if not info_path.is_file():
            missing_info.append(str(child))
            continue

        try:
            text = info_path.read_text(encoding="utf-8")
            obj = json.loads(text)

            if not (owner and repo):
                # 获取不到仓库信息时保留原字段并提醒
                print(
                    f"[WARN] 无法获取 Git 仓库信息，未修改 url：{child}",
                    file=sys.stderr,
                )
                continue

            # 对目录名进行 URL 转义，避免空格与特殊字符
            encoded_child = quote(child.name, safe="-._~")
            raw_url = f"{base_raw}/{owner}/{repo}/{branch}/tables/{encoded_child}/header.json"
            obj["url_ori"] = obj["url"]
            obj["url"] = raw_url

            aggregated.append(obj)

        except Exception as e:
            print(f"[WARN] 解析失败: {info_path}: {e}", file=sys.stderr)
            invalid_info.append(str(info_path))

    output_path = outputs_dir / "tables.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    print(f"[OK] 写入 {output_path}，共 {len(aggregated)} 条。")
    if missing_info:
        print(f"[INFO] 缺少 info.json 的目录数量: {len(missing_info)}", file=sys.stderr)
    if invalid_info:
        print(f"[INFO] 无法解析的 JSON 文件数量: {len(invalid_info)}", file=sys.stderr)
    if missing_header:
        print(
            f"[INFO] 缺少 header.json 的目录数量: {len(missing_header)}",
            file=sys.stderr,
        )


def apply_proxy_modifier(data: Any, modifier: UrlProxyModifier):
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


def gen_tables_with_modifier():
    """
    统一生成多个中间版本：在函数内部使用 dict[Path, UrlProxyModifier]
    来描述输出目标与中间策略的映射。

    命令行参数（可选，仅用于 2sb 版本）
      - args[0]: 输入路径（默认 outputs/tables.json）
      - args[1]: 2sb 输出路径（默认 outputs/tables_2sb.json）
      - args[2]: 2sb 中间前缀（默认 DEFAULT_PROXY_PREFIX）
    """
    args = sys.argv[1:]
    input_path = Path(args[0]) if len(args) >= 1 else Path("outputs/tables.json")
    out_2sb = Path(args[1]) if len(args) >= 2 else Path("outputs/tables_2sb.json")
    prefix_2sb = args[2] if len(args) >= 3 else DEFAULT_PROXY_PREFIX

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    mapping: dict[Path, UrlProxyModifier] = {
        out_2sb: PrefixUrlProxyModifier(prefix_2sb),
        Path("outputs/tables_gh_proxy.json"): PrefixUrlProxyModifier("https://gh-proxy.com/"),
        Path("outputs/tables_gitee.json"): GiteeRawUrlProxyModifier(),
    }

    for output_path, modifier in mapping.items():
        proxied = apply_proxy_modifier(data, modifier)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(proxied, f, ensure_ascii=False, indent=2)
        # 在打印中体现当前使用的实现类与关键参数
        msg_prefix = modifier.prefix if isinstance(modifier, PrefixUrlProxyModifier) else ""
        print(f"Wrote {output_path} with UrlProxyModifier ({modifier.__class__.__name__}, prefix: {msg_prefix})")


if __name__ == "__main__":
    setup()
    generate_tables_json()
    gen_tables_with_modifier()
