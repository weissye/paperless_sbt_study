"""Canonical OpenAPI request-body variant selection.

All generator layers must select the same representation.  In particular,
PATCH operations frequently advertise JSON Patch (an array) before Merge
Patch (an object).  Object-field stories cannot silently inspect one variant
while the interface serializes another.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .parsing.model import Operation, RequestBodyVariant


def select_request_variant(op: Operation,
                           preferred: Optional[str] = None
                           ) -> Tuple[Optional[str], Dict[str, Any]]:
    if not op.request_body or not op.request_body.variants:
        return None, {}
    variants = op.request_body.variants

    if preferred:
        exact = next((v for v in variants
                      if v.media_type.lower() == preferred.lower()), None)
        if exact is not None:
            return exact.media_type, exact.schema

    def is_object(v: RequestBodyVariant) -> bool:
        schema = v.schema if isinstance(v.schema, dict) else {}
        return schema.get("type") == "object" or isinstance(schema.get("properties"), dict)

    if op.method.upper() == "PATCH":
        merge = next((v for v in variants
                      if v.media_type.lower() == "application/merge-patch+json"
                      and is_object(v)), None)
        if merge is not None:
            return merge.media_type, merge.schema

    exact_json = next((v for v in variants
                       if v.media_type.lower() == "application/json"), None)
    if exact_json is not None:
        return exact_json.media_type, exact_json.schema

    json_object = next((v for v in variants
                        if "json" in v.media_type.lower() and is_object(v)), None)
    if json_object is not None:
        return json_object.media_type, json_object.schema

    json_variant = next((v for v in variants if "json" in v.media_type.lower()), None)
    selected = json_variant or variants[0]
    return selected.media_type, selected.schema
