#!/usr/bin/env python3
import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
tables_dir = repo_root / "tables"
outputs_dir = repo_root / "outputs"

def setup():
    outputs_dir.mkdir(parents=True, exist_ok=True)

    if not tables_dir.is_dir():
        print(f"[ERROR] tables 目录不存在: {tables_dir}", file=sys.stderr)
        sys.exit(1)


def generate_tables_json():
    aggregated = []
    missing = []
    invalid = []

    for child in sorted(tables_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue

        info_path = child / "info.json"
        if info_path.is_file():
            try:
                text = info_path.read_text(encoding="utf-8")
                obj = json.loads(text)
                aggregated.append(obj)
            except Exception as e:
                print(f"[WARN] 解析失败: {info_path}: {e}", file=sys.stderr)
                invalid.append(str(info_path))
        else:
            missing.append(str(child))

    output_path = outputs_dir / "tables.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(aggregated, f, ensure_ascii=False, indent=2)

    print(f"[OK] 写入 {output_path}，共 {len(aggregated)} 条。")
    if missing:
        print(f"[INFO] 缺少 info.json 的目录数量: {len(missing)}", file=sys.stderr)
    if invalid:
        print(f"[INFO] 无法解析的 JSON 文件数量: {len(invalid)}", file=sys.stderr)


if __name__ == "__main__":
    generate_tables_json()