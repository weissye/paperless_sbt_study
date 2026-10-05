"""Load an OpenAPI 3.0/3.1 document (JSON or YAML) and resolve internal
(``#/...``) and local-file $ref values.

Remote (http/https) $ref targets are never fetched (network access is
forbidden at generation time). They are reported as unsupported constructs
instead of silently ignored.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


class LoadError(RuntimeError):
    pass


def load_raw(path: str) -> Dict[str, Any]:
    """Read a JSON or YAML file from disk into a plain dict."""
    p = Path(path)
    if not p.exists():
        raise LoadError(f"OpenAPI file not found: {path}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise LoadError("PyYAML is required to parse .yaml/.yml files but is not installed.")
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        # Sniff: try JSON first, fall back to YAML.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            if yaml is None:
                raise LoadError(
                    f"Could not parse {path} as JSON and PyYAML is not installed to try YAML."
                )
            data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise LoadError(f"Top-level OpenAPI document must be a JSON/YAML object: {path}")
    return data


def _pointer_get(doc: Dict[str, Any], pointer: str) -> Any:
    """Resolve a JSON pointer like '#/components/schemas/Book' within doc."""
    assert pointer.startswith("#/") or pointer == "#"
    if pointer == "#":
        return doc
    parts = pointer[2:].split("/")
    node: Any = doc
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                raise LoadError(f"Unresolvable $ref pointer segment '{part}' in '{pointer}'")
            node = node[part]
        else:
            raise LoadError(f"Cannot descend into non-container while resolving '{pointer}'")
    return node


class RefResolver:
    """Resolves $ref values against a root document, with local-file support
    and cycle-safe expansion (cycles are preserved as a marker rather than
    infinitely inlined)."""

    def __init__(self, root_doc: Dict[str, Any], base_dir: str, allow_list=None):
        self.root_doc = root_doc
        self.base_dir = base_dir
        self.allow_list = allow_list
        self.unsupported_refs: List[str] = []
        self._external_docs: Dict[str, Dict[str, Any]] = {}
        self._in_progress: Set[int] = set()

    def _load_external(self, file_path: str) -> Dict[str, Any]:
        resolved = str((Path(self.base_dir) / file_path).resolve())
        if resolved not in self._external_docs:
            if self.allow_list is not None:
                self.allow_list.add_file(resolved)
            self._external_docs[resolved] = load_raw(resolved)
        return self._external_docs[resolved]

    def resolve(self, node: Any, pointer_path: str = "#", _seen: Tuple[str, ...] = ()) -> Any:
        """Recursively walk `node`, replacing every $ref with the resolved
        value (deep-copied). Local file refs ('other.json#/Foo') are loaded
        (subject to the isolation allow-list) and file+pointer refs into
        `#/...` of the *current* document are resolved against root_doc."""
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref = node["$ref"]
                if ref.startswith("http://") or ref.startswith("https://"):
                    self.unsupported_refs.append(ref)
                    return {"__unsupported_ref__": ref}
                if ref in _seen:
                    # Cyclic schema reference (e.g. self-referential tree
                    # node). Preserve as an explicit marker instead of
                    # infinite recursion; renderer/inference must handle it.
                    return {"__cyclic_ref__": ref}
                if ref.startswith("#/") or ref == "#":
                    target = _pointer_get(self.root_doc, ref)
                elif "#" in ref:
                    file_part, _, frag = ref.partition("#")
                    ext_doc = self._load_external(file_part)
                    target = _pointer_get(ext_doc, "#/" + frag.lstrip("/"))
                else:
                    ext_doc = self._load_external(ref)
                    target = ext_doc
                resolved = self.resolve(copy.deepcopy(target), ref, _seen + (ref,))
                if isinstance(resolved, dict):
                    resolved = dict(resolved)
                    resolved.setdefault("__source_ref__", ref)
                return resolved
            return {k: self.resolve(v, f"{pointer_path}/{_esc(k)}", _seen) for k, v in node.items()}
        if isinstance(node, list):
            return [self.resolve(v, f"{pointer_path}/{i}", _seen) for i, v in enumerate(node)]
        return node


def _esc(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def load_and_resolve(path: str, allow_list=None) -> Tuple[Dict[str, Any], List[str]]:
    """Load an OpenAPI document and return (fully $ref-resolved copy, list of
    unsupported remote refs encountered)."""
    if allow_list is not None:
        allow_list.add_file(path)
    raw = load_raw(path)
    resolver = RefResolver(raw, base_dir=os.path.dirname(os.path.abspath(path)), allow_list=allow_list)
    resolved = resolver.resolve(raw)
    return resolved, resolver.unsupported_refs
