#!/usr/bin/env python3
"""从已提交Git blob生成含不可变revision/manifest摘要的契约制品."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()

    def blob(path: str) -> bytes:
        return subprocess.check_output(["git", "show", f"{revision}:{path}"], cwd=ROOT)

    manifest_bytes = blob("contracts/manifest.json")
    manifest = json.loads(manifest_bytes)
    files = {name: blob(f"contracts/{name}") for name in manifest["files"]}
    for name, content in files.items():
        if "sha256:" + hashlib.sha256(content).hexdigest() != manifest["files"][name]:
            raise ValueError("committed contract manifest is inconsistent")
    provenance = {
        "repository": "https://github.com/lirji/platform-agentscope.git",
        "revision": revision,
        "manifest_digest": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        # 固定时间戳及排序, 同一Git revision可重建相同zip摘要.
        for name, content in sorted(
            {
                **{f"contracts/{name}": data for name, data in files.items()},
                "contracts/manifest.json": manifest_bytes,
                "source.json": (json.dumps(provenance, sort_keys=True) + "\n").encode(),
            }.items()
        ):
            bundle.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), content)
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"PASS: contract artifact revision={revision} sha256={checksum}")


if __name__ == "__main__":
    main()
