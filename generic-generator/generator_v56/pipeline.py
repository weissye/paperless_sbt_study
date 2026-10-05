"""Orchestration for `generate` and `inspect`. This module is imported by
`generate` and `inspect` only -- `compare/reference_comparator.py` must
never import from here in a way that feeds reference data back into it.
"""
from __future__ import annotations
import re

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .parsing.loader import load_and_resolve
from .parsing.normalize import normalize
from .parsing.model import Document
from .inference.entities import infer_entities, standalone_operations
from .inference.keys import infer_key
from .inference.dependencies import infer_dependencies
from .inference.graph import build_graph
from .render.plan import build_plan
from .render.interfaces_js import render_interfaces
from .render.stories_js import render_stories
from .render.http_interfaces import HttpInterfaceRegistry
from .report.generation_report import build_generation_report, build_dependency_graph_report


@dataclass
class PipelineResult:
    doc: Document
    plan: object
    interfaces_js: str
    stories_js: str
    generation_report: Dict[str, Any]
    dependency_graph_report: Dict[str, Any]
    unsupported_refs: List[str]
    transport_manifest: list = field(default_factory=list)
    resource_maps: dict = field(default_factory=dict)


def run_pipeline(openapi_path: str, name: str, base_url: str, seed: int,
                  allow_list=None, overrides: Optional[Dict[str, Any]] = None,
                  cli_args: Optional[Dict[str, Any]] = None,
                  instances_per_entity: int = 1,
                  instances_per_action: int = 1,
                  story_profile: str = "full",
                  long_rounds: tuple[int, int] = (3, 6),
                  emit_prefix_witnesses: bool = False,
                  json_delete_bodies: bool = False,
                  optional_enum_dependency_branch: bool = False,
                  verified_values: Optional[Dict[str, Dict[str, object]]] = None,
                  verified_update_carry: tuple[str, ...] = (),
                  logical_processes: int = 1,
                  auth_token_env: Optional[str] = None,
                  include_resource_maps: bool = False,
                  relationship_profile: Optional[Dict[str, Any]] = None,
                  compile_relationship_model: bool = False,
                  relationship_runtime: Optional[Dict[str, Any]] = None) -> PipelineResult:
    resolved, unsupported_refs = load_and_resolve(openapi_path, allow_list=allow_list)
    raw_unresolved, _ = _load_raw_only(openapi_path, allow_list)
    doc = normalize(resolved, raw_unresolved)

    if unsupported_refs:
        doc.unsupported.append(
            f"{len(unsupported_refs)} remote $ref value(s) were not resolved (network access is "
            f"forbidden at generation time): {unsupported_refs}"
        )

    entities = infer_entities(doc)
    keys = {e.key: infer_key(doc, e) for e in entities}

    applied_overrides = []
    if overrides:
        applied_overrides = _apply_overrides(entities, keys, overrides)

    dependencies = infer_dependencies(doc, entities, keys)
    graph = build_graph([e.key for e in entities], dependencies)
    standalone_ops = standalone_operations(doc, entities)

    ambiguities = []
    for e in entities:
        if e.confidence < 1.0:
            ambiguities.append(
                f"Entity '{e.key}' has no component-schema evidence; name derived from path segment "
                f"(confidence={e.confidence})."
            )
    for e in entities:
        k = keys[e.key]
        if k.confidence < 0.85:
            ambiguities.append(
                f"Key inference for entity '{e.key}' has reduced confidence ({k.confidence}); "
                f"path parameter(s) {k.fields} could not be fully cross-validated against the schema."
            )
    if graph.had_cycle:
        ambiguities.append(
            f"Dependency graph contained a cycle; {len(graph.cycle_edges_removed)} lowest-confidence "
            f"edge(s) were removed to allow a deterministic creation order. See dependency_graph.json."
        )
    ambiguities.extend(applied_overrides)

    plan = build_plan(doc, entities, keys, dependencies, graph, standalone_ops,
                      seed, instances_per_entity=instances_per_entity,
                      instances_per_action=instances_per_action)

    if verified_values:
        from .render.naming import safe_identifier
        from .request_variants import select_request_variant
        operations = [op for ep in plan.entities for op in ep.ops] + plan.standalone_ops
        by_id = {op.op.operation_id: op for op in operations}
        for operation_id, values in verified_values.items():
            op = by_id.get(operation_id)
            if op is None or op.kind not in ("action", "update", "create") or not isinstance(values, dict):
                raise ValueError("Verified values require a known action, update or create operationId")
            _media, schema = select_request_variant(op.op)
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            for field, value in values.items():
                matched = [(name, s) for name, s in props.items()
                           if safe_identifier(name) == field and isinstance(s, dict)]
                if (field not in op.params or field in dict(op.story_dependencies) or
                        len(matched) != 1 or matched[0][1].get("readOnly")):
                    raise ValueError("Verified values must match a writable body field")
                prop = matched[0][1]
                if op.kind == "create":
                    # A separately observed serial create can supply optional
                    # documented strings. Never infer these server conditions
                    # from an optional OpenAPI property alone.
                    if (prop.get("type") != "string" or not isinstance(value, str) or not value or
                            len(value) < prop.get("minLength", 0) or
                            (prop.get("maxLength") is not None and len(value) > prop["maxLength"])):
                        raise ValueError("Verified create values must be nonempty documented strings")
                    if prop.get("pattern") and not re.fullmatch(prop["pattern"], value):
                        raise ValueError("Verified create value does not match documented pattern")
                    if prop.get("enum") and value not in prop["enum"]:
                        raise ValueError("Verified create value does not match documented enum")
                elif (prop.get("type") != "array" or
                      prop.get("items", {}).get("type") != "string" or
                      not isinstance(value, list) or not value or
                      any(not isinstance(item, str) or not item for item in value)):
                    raise ValueError("Verified values must match a writable array<string> body field")

    parsed_base = base_url.rstrip("/")
    host, port, protocol = _split_base_url(parsed_base)

    interfaces_js = render_interfaces(plan, name, host, port, protocol,
                                      json_delete_bodies=json_delete_bodies,
                                      correlate_requests=story_profile in (
                                          "long-interleaving", "concurrency-breadth", "parallel-crud"),
                                      auth_token_env=auth_token_env,
                                      allow_opaque_body=story_profile == "parallel-crud")
    if verified_update_carry:
        operations = [op for ep in plan.entities for op in ep.ops]
        by_id = {op.op.operation_id: op for op in operations}
        for operation_id in verified_update_carry:
            op = by_id.get(operation_id)
            if not op or op.kind != "update" or op.op.method not in ("PUT", "PATCH"):
                raise ValueError("Verified read carry requires a documented update operationId")
    transport_registry = HttpInterfaceRegistry()
    stories_js = render_stories(plan, name, story_profile=story_profile,
                                request_rules=(overrides or {}).get('request_rules'),
                                auth_token_env=auth_token_env,
                                long_rounds=long_rounds,
                                emit_prefix_witnesses=emit_prefix_witnesses,
                                optional_enum_dependency_branch=optional_enum_dependency_branch,
                                verified_values=verified_values,
                                verified_update_carry=verified_update_carry,
                                logical_processes=logical_processes,
                                transport_registry=transport_registry)
    interfaces_js += transport_registry.render()
    if re.search(r'\bsvc\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(', stories_js):
        raise ValueError('Generated stories contain a direct HTTP request outside interfaces.')

    gen_report = build_generation_report(
        doc, plan, unsupported_refs, ambiguities,
        isolation_audit=(allow_list and getattr(allow_list, "_audit", None)),
        cli_args=cli_args,
    )
    dep_report = build_dependency_graph_report(plan, dependencies)
    resource_maps = {}
    if include_resource_maps or relationship_profile is not None:
        from .inference.resource_maps import build_resource_maps
        resource_maps = build_resource_maps(raw_unresolved, plan)
        if relationship_profile is not None:
            from .render.relationship_blueprint import build_relationship_blueprint
            resource_maps['relationship_scenario_plan'] = build_relationship_blueprint(plan, resource_maps, relationship_profile)
    if compile_relationship_model:
        if relationship_profile is None or relationship_runtime is None:
            raise ValueError('Relationship compilation requires scope and runtime configurations.')
        import hashlib
        from pathlib import Path
        from .render.compiled_relationships import compile_relationships
        actual_hash = hashlib.sha256(Path(openapi_path).read_bytes()).hexdigest()
        if relationship_runtime.get('contract_sha256') != actual_hash:
            raise ValueError('Relationship runtime configuration belongs to a different contract.')
        extra, stories_js, blueprint, compilation, contexts = compile_relationships(plan, resource_maps, raw_unresolved, relationship_runtime)
        interfaces_js += extra
        resource_maps['relationship_scenario_plan'] = blueprint
        resource_maps['relationship_compilation'] = compilation
        if re.search(r'\bsvc\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(', stories_js):
            raise ValueError('Compiled relationship stories contain a direct HTTP request.')

    return PipelineResult(
        doc=doc, plan=plan, interfaces_js=interfaces_js, stories_js=stories_js,
        generation_report=gen_report, dependency_graph_report=dep_report,
        unsupported_refs=unsupported_refs,
        transport_manifest=transport_registry.entries,
        resource_maps=resource_maps,
    )


def _apply_overrides(entities, keys, overrides: Dict[str, Any]) -> List[str]:
    """Applies generic, user-supplied overrides for genuinely ambiguous
    contract elements. Overrides are keyed by the *generic* entity key
    (the inferred family path, visible via `inspect`), never by a
    hard-coded example name, and every applied override is recorded here
    so it shows up in generation_report.json (never a silent special
    case). Supported override shape:

        {
          "entities": {
            "<entity_key>": {
              "display_name": "Widget",
              "key_fields": ["id"]
            }
          }
        }
    """
    applied = []
    entity_overrides = overrides.get("entities", {}) if isinstance(overrides, dict) else {}
    by_key = {e.key: e for e in entities}
    for entity_key, patch in entity_overrides.items():
        e = by_key.get(entity_key)
        if not e:
            applied.append(f"Override ignored: no entity with key '{entity_key}' was inferred from this contract.")
            continue
        if "display_name" in patch:
            old = e.display_name
            e.display_name = patch["display_name"]
            from .inference.entities import _pluralize_display
            e.plural_display_name = patch.get("plural_display_name", _pluralize_display(e.display_name))
            applied.append(f"Override applied: entity '{entity_key}' display_name '{old}' -> '{e.display_name}' "
                            f"(plural '{e.plural_display_name}'). Note: an explicit OpenAPI operationId still wins "
                            f"over any generic name derived from display_name for that specific operation.")
        if "key_fields" in patch and entity_key in keys:
            old = keys[entity_key].fields
            keys[entity_key].fields = list(patch["key_fields"])
            applied.append(f"Override applied: entity '{entity_key}' key_fields {old} -> {keys[entity_key].fields}.")
    return applied


def _load_raw_only(path, allow_list):
    from .parsing.loader import load_raw
    return load_raw(path), None


def _split_base_url(base_url: str):
    import re
    m = re.match(r"^(https?)://([^:/]+)(?::(\d+))?", base_url)
    if not m:
        return "localhost", 5000, "http"
    protocol, host, port = m.group(1), m.group(2), m.group(3)
    return host, int(port) if port else (443 if protocol == "https" else 80), protocol
