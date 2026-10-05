"""Prepare a disposable Provengo runtime copy for non-terminating observation.

Generated source remains contract-exact.  Only the disposable runtime copy is
changed so Provengo's REST actuator transports every HTTP status to callbacks;
the external trace evaluator remains the sole contract oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


EXPECTED_CODES = re.compile(r"expectedResponseCodes\s*:\s*\[[^\]]*\]")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_runtime_file(path: Path) -> dict:
    before = path.read_bytes()
    text = before.decode("utf-8-sig")
    updated, replacements = EXPECTED_CODES.subn(
        "expectedResponseCodes: __sbtObservedHttpStatuses", text
    )
    if replacements == 0:
        raise ValueError(f"no expectedResponseCodes arrays found in {path}")
    path.write_text(updated, encoding="utf-8")
    after = path.read_bytes()
    return {
        "path": str(path),
        "replacements": replacements,
        "source_sha256": _sha(before),
        "runtime_sha256": _sha(after),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    rows = [patch_runtime_file(Path(item)) for item in args.file]
    report = {
        "schema_version": 1,
        "policy": "non-terminating-http-observation",
        "scope": "disposable-provengo-runtime-copy-only",
        "contract_oracle": "external-preserved-http-trace-evaluator",
        "source_artifacts_modified": False,
        "files": rows,
    }
    Path(args.report).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"files": len(rows), "replacements": sum(r["replacements"] for r in rows)}))
    print("OPENAPI_SBT_RUNTIME_OBSERVATION_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
