"""Deterministic, schema-driven example value generation.

Priority order (per DEVELOPMENT_PROMPT.md #7):
1. an explicit `example` on the schema
2. `default`
3. `enum` (first value, deterministically)
4. format-specific generation (uuid, date, date-time, email, uri, int32...)
5. seeded generic value, derived from a stable hash of (seed, field-name
   path) so the same field always gets the same value for a given seed,
   independent of dict iteration order or wall-clock time.

Respects: required-ness (always filled), nullable (never emits null unless
nullable and no other guidance), readOnly (excluded from request bodies),
writeOnly (excluded from response expectations - not handled here), arrays
(min/maxItems), simple composition (allOf merges properties; oneOf/anyOf
picks the first branch deterministically), and numeric/string bounds.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


def _stable_int(seed: int, path: str, mod: int) -> int:
    h = hashlib.sha256(f"{seed}:{path}".encode("utf-8")).hexdigest()
    return int(h[:12], 16) % mod


def _merge_all_of(schema: Dict[str, Any]) -> Dict[str, Any]:
    if "allOf" not in schema:
        return schema
    merged: Dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
    props = dict(merged.get("properties", {}))
    required = list(merged.get("required", []))
    for sub in schema["allOf"]:
        sub = _merge_all_of(sub) if isinstance(sub, dict) else sub
        if not isinstance(sub, dict):
            continue
        props.update(sub.get("properties", {}))
        required.extend([r for r in sub.get("required", []) if r not in required])
        for k, v in sub.items():
            if k not in ("properties", "required", "allOf"):
                merged.setdefault(k, v)
    merged["properties"] = props
    merged["required"] = required
    if "type" not in merged:
        merged["type"] = "object"
    return merged


def generate_value(schema: Dict[str, Any], seed: int, path: str,
                    for_request: bool = True) -> Any:
    if not isinstance(schema, dict):
        return None

    schema = _merge_all_of(schema)

    if "oneOf" in schema and schema["oneOf"]:
        return generate_value(schema["oneOf"][0], seed, path, for_request)
    if "anyOf" in schema and schema["anyOf"]:
        return generate_value(schema["anyOf"][0], seed, path, for_request)

    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        idx = _stable_int(seed, path, len(schema["enum"]))
        return schema["enum"][idx]

    schema_type = schema.get("type")
    fmt = schema.get("format")

    if schema_type == "array" or (schema_type is None and "items" in schema):
        item_schema = schema.get("items", {})
        min_items = schema.get("minItems", 1)
        count = max(min_items, 1)
        return [generate_value(item_schema, seed, f"{path}[{i}]", for_request) for i in range(count)]

    if schema_type == "object" or "properties" in schema:
        result = {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for prop_name, prop_schema in props.items():
            if for_request and isinstance(prop_schema, dict) and prop_schema.get("readOnly"):
                continue
            if prop_name in required or _stable_int(seed, f"{path}.{prop_name}", 2) == 0:
                result[prop_name] = generate_value(prop_schema, seed, f"{path}.{prop_name}", for_request)
        return result

    if schema_type == "boolean":
        return _stable_int(seed, path, 2) == 0

    if schema_type == "integer":
        minimum = schema.get("minimum", 1)
        maximum = schema.get("maximum")
        if maximum is None:
            return minimum
        return minimum + _stable_int(seed, path, max(1, maximum - minimum + 1))

    if schema_type == "number":
        minimum = schema.get("minimum", 1)
        maximum = schema.get("maximum")
        if maximum is None:
            return minimum
        base = minimum + (_stable_int(seed, path, 1000) / 1000.0) * (maximum - minimum)
        return round(base, 2)

    if schema_type == "string" or schema_type is None:
        return _generate_string(schema, seed, path, fmt)

    return None


def _generate_string(schema: Dict[str, Any], seed: int, path: str, fmt: Optional[str]) -> str:
    n = _stable_int(seed, path, 100000)
    if fmt == "uuid":
        h = hashlib.sha256(f"{seed}:{path}".encode()).hexdigest()
        legacy = f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.fullmatch(pattern, legacy):
            # `format: uuid` alone says nothing about the UUID version.
            # Some contracts additionally require a version-4 nibble and
            # RFC 4122 variant. Honor that explicit constraint, retaining
            # the prior deterministic value for every unconstrained UUID.
            variant = format(8 + (int(h[16], 16) % 4), "x")
            v4 = f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-{variant}{h[17:20]}-{h[20:32]}"
            if re.fullmatch(pattern, v4):
                return v4
        return legacy
    if fmt == "date":
        day = 1 + _stable_int(seed, path, 28)
        month = 1 + _stable_int(seed, path + "m", 12)
        return f"2025-{month:02d}-{day:02d}"
    if fmt == "date-time":
        day = 1 + _stable_int(seed, path, 28)
        return f"2025-01-{day:02d}T00:00:00Z"
    if fmt == "email":
        return f"user{n}@example.test"
    if fmt in ("uri", "url"):
        return f"https://example.test/{n}"

    pattern = schema.get("pattern")
    if pattern:
        generated = _generate_from_pattern(pattern, seed, path)
        if generated is not None:
            return generated
        # Pattern didn't match the simple "one repeated character class"
        # shape we can synthesize for (see _generate_from_pattern); fall
        # through to the generic value below. This is a documented
        # limitation (DESIGN.md / TRACEABILITY.md): the generic value is
        # NOT guaranteed to satisfy an arbitrary regex, only the common
        # `^[charclass]{n}$` / `{min,max}` shape is actually synthesized.
        # Found missing entirely (pattern was read but never used at all)
        # while running the generated NetBox model against its real mock
        # SUT, which rejected a `color` field ("^[0-9a-f]{6}$") because a
        # generic value was sent with no attempt to honor the pattern.

    field_name = path.rsplit(".", 1)[-1].rsplit("[", 1)[0]
    field_name = re.sub(r"[^A-Za-z0-9]", "", field_name) or "val"
    min_len = schema.get("minLength", 0)
    val = f"{field_name}_{n}"
    if len(val) < min_len:
        val = val + ("x" * (min_len - len(val)))
    max_len = schema.get("maxLength")
    if max_len and len(val) > max_len:
        val = val[:max_len]
    return val


_CHAR_CLASS_SHORTHANDS = {"d": "0-9", "w": "A-Za-z0-9_", "s": " "}


def _expand_char_class(body: str) -> str:
    """Expands a regex character-class body (the part inside [...]) into
    the literal set of characters it matches, e.g. '0-9a-f' ->
    '0123456789abcdef'. Handles simple ranges and \\d/\\w shorthands;
    anything it can't confidently expand is dropped rather than guessed."""
    body = re.sub(r"\\d", _CHAR_CLASS_SHORTHANDS["d"], body)
    body = re.sub(r"\\w", _CHAR_CLASS_SHORTHANDS["w"], body)
    chars = []
    i = 0
    while i < len(body):
        if i + 2 < len(body) and body[i + 1] == "-" and body[i] != "\\":
            start, end = ord(body[i]), ord(body[i + 2])
            if start <= end:
                chars.extend(chr(c) for c in range(start, end + 1))
            i += 3
        else:
            if body[i] != "\\":
                chars.append(body[i])
            i += 1
    return "".join(dict.fromkeys(chars))  # de-duplicate, preserve order


def _generate_from_pattern(pattern: str, seed: int, path: str) -> Optional[str]:
    """Synthesizes a string matching a `pattern` schema constraint, for
    the common real-world shape of a single repeated character class:
    `^[<class>]{<n>}$` or `^[<class>]{<min>,<max>}$` (e.g. a hex color
    `^[0-9a-f]{6}$`, an alphanumeric code `^[A-Z0-9]{4,8}$`). This is a
    deliberately narrow, safe synthesizer -- not a general regex-to-string
    engine -- so it never emits something that merely *looks* plausible
    but doesn't actually satisfy the constraint. Returns None (caller
    falls back to a generic value) for any pattern outside this shape."""
    m = re.fullmatch(r"\^?\[([^\]]+)\]\{(\d+)(?:,(\d+))?\}\$?", pattern.strip())
    if not m:
        return None
    char_class, min_s, max_s = m.group(1), m.group(2), m.group(3)
    chars = _expand_char_class(char_class)
    if not chars:
        return None
    length = int(min_s) if max_s is None else int(min_s)  # deterministic: always use the minimum length
    result = []
    for i in range(length):
        idx = _stable_int(seed, f"{path}[pattern:{i}]", len(chars))
        result.append(chars[idx])
    return "".join(result)
