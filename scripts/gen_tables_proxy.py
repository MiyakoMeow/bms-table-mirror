#!/usr/bin/env python3
import json
import sys
from pathlib import Path

DEFAULT_PREFIX = "https://get.2sb.org/"


def prefix_urls(data, prefix: str = DEFAULT_PREFIX):
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


def main():
    args = sys.argv[1:]
    input_path = Path(args[0]) if len(args) >= 1 else Path("outputs/tables.json")
    output_path = Path(args[1]) if len(args) >= 2 else Path("outputs/tables_proxy.json")
    prefix = args[2] if len(args) >= 3 else DEFAULT_PREFIX

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
    main()
