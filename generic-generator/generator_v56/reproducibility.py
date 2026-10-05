"""Path-independent reproducibility metadata for generated SBT models."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_reproducibility_block(*, source_sha256: str, generator_version: str,
                                seed: int, instances_per_entity: int,
                                instances_per_action: int, base_url: str,
                                interfaces_js: str, stories_js: str,
                                dependency_graph_report: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deterministic fingerprint excluding filesystem/output paths.

    The generated report used to embed the output directory, so two identical
    generations into different folders were not byte-identical.  records
    only semantic generation inputs plus content hashes here.
    """
    artifacts = {
        "interfaces_js": sha256_text(interfaces_js),
        "stories_js": sha256_text(stories_js),
        "dependency_graph_json": sha256_text(
            json.dumps(dependency_graph_report, indent=2, sort_keys=True)
        ),
    }
    identity = {
        "generator_version": generator_version,
        "source_openapi_sha256": source_sha256,
        "seed": int(seed),
        "instances_per_entity": int(instances_per_entity),
        "instances_per_action": int(instances_per_action),
        "base_url": base_url.rstrip("/"),
        "artifact_sha256": artifacts,
    }
    return {
        **identity,
        "content_fingerprint_sha256": sha256_text(canonical_json(identity)),
        "scope": "semantic inputs and generated artifacts; filesystem paths and run-time ports are excluded",
    }
