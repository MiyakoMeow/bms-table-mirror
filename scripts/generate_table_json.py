#!/usr/bin/env python3
import json
import sys
import subprocess
import re
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
tables_dir = repo_root / "tables"
outputs_dir = repo_root / "outputs"


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

        if info_path.is_file():
            try:
                text = info_path.read_text(encoding="utf-8")
                obj = json.loads(text)

                if owner and repo:
                    raw_url = f"{base_raw}/{owner}/{repo}/{branch}/tables/{child.name}/header.json"
                    obj["url"] = raw_url
                else:
                    # 获取不到仓库信息时保留原字段并提醒
                    print(
                        f"[WARN] 无法获取 Git 仓库信息，未修改 url：{child}",
                        file=sys.stderr,
                    )

                aggregated.append(obj)
            except Exception as e:
                print(f"[WARN] 解析失败: {info_path}: {e}", file=sys.stderr)
                invalid_info.append(str(info_path))
        else:
            missing_info.append(str(child))

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


if __name__ == "__main__":
    generate_tables_json()
