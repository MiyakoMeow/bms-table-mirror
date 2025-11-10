#!/usr/bin/env python3
import json
import sys
import subprocess
import re
from pathlib import Path
from urllib.parse import quote

repo_root = Path(__file__).resolve().parent.parent
tables_dir = repo_root / "tables"
outputs_dir = repo_root / "outputs"

DEFAULT_PROXY_PREFIX = "https://get.2sb.org/"


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
    m = re.search(
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", url.strip()
    )
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
            raw_url = (
                f"{base_raw}/{owner}/{repo}/{branch}/tables/{encoded_child}/header.json"
            )
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


def prefix_urls(data, prefix: str = DEFAULT_PROXY_PREFIX):
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key == "url" and isinstance(value, str):
                if value.startswith(prefix):
                    result[key] = value
                else:
                    result[key] = prefix + value
            else:
                result[key] = prefix_urls(value, prefix)
        return result
    if isinstance(data, list):
        return [prefix_urls(item, prefix) for item in data]
    return data


def gen_tables_proxy():
    args = sys.argv[1:]
    input_path = Path(args[0]) if len(args) >= 1 else Path("outputs/tables.json")
    output_path = Path(args[1]) if len(args) >= 2 else Path("outputs/tables_proxy.json")
    prefix = args[2] if len(args) >= 3 else DEFAULT_PROXY_PREFIX

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    proxied = prefix_urls(data, prefix)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(proxied, f, ensure_ascii=False, indent=2)

    print(f"Wrote {output_path} with prefixed urls: {prefix}")


if __name__ == "__main__":
    generate_tables_json()
    gen_tables_proxy()
