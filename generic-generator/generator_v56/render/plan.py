"""Builds a rendering-agnostic plan (still just data, no JS text) from the
parsed Document + inference results. render/interfaces_js.py and
render/stories_js.py both consume this plan; neither of them re-derives
entities/keys/dependencies themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..parsing.model import Document, Operation
from ..inference.entities import EntityCandidate, _segments, _is_param
from ..inference.keys import KeyInfo
from ..inference.dependencies import DependencyEdge
from ..inference.graph import DependencyGraph
from ..inference.values import generate_value
from ..render.naming import safe_identifier, to_camel, to_pascal
from ..request_variants import select_request_variant


@dataclass
class OpFunctionPlan:
    js_name: str
    op: Operation
    kind: str                     # 'list' | 'create' | 'get' | 'update' | 'delete' | 'action' | 'standalone'
    entity_key: Optional[str]
    params: List[str]             # canonical JS parameter names, sorted
    path_param_map: Dict[str, str]  # openapi path-param name -> js param name
    query_params: List[str]        # openapi query-param names present in this op
    header_params: List[str]       # openapi header-param names present in this op
    cookie_params: List[str]       # openapi cookie-param names present in this op
    body_props: List[str]          # request-body top-level property names (non-readOnly) for this op
    body_prop_types: Dict[str, str]
    request_media_type: Optional[str]
    description_base: str
    success_codes: List[int]
    error_codes: List[int]
    has_default_response: bool
    emits_done_event: bool
    source_pointer: str
    server_assigned_key_fields: List[str] = field(default_factory=list)
    server_assigned_response_field: Optional[str] = None
    # (js_param_name, target_entity_key) pairs for action/standalone ops
    # whose own parameters were matched to an existing entity, so a story
    # can resolve a real value for them instead of a generic seeded one.
    story_dependencies: List[tuple] = field(default_factory=list)
    own_entity_key: Optional[str] = None  # entity this action operates ON (for action ops)


@dataclass
class EntityPlan:
    entity: EntityCandidate
    key: KeyInfo
    fields: List[str]                 # canonical field superset (sorted)
    ops: List[OpFunctionPlan] = field(default_factory=list)
    has_item_get: bool = False
    has_delete: bool = False
    create_op: Optional[OpFunctionPlan] = None
    delete_op: Optional[OpFunctionPlan] = None
    get_op: Optional[OpFunctionPlan] = None
    dependencies: List[DependencyEdge] = field(default_factory=list)


@dataclass
class Plan:
    doc: Document
    entities: List[EntityPlan]
    standalone_ops: List[OpFunctionPlan]
    graph: DependencyGraph
    seed: int
    instances_per_entity: int = 1
    instances_per_action: int = 1


def _prop_js_type(schema: Dict[str, Any]) -> str:
    t = schema.get("type") if isinstance(schema, dict) else None
    return t or "string"


def _request_body_props(op: Operation) -> (List[str], Dict[str, str]):
    media_type, schema = select_request_variant(op)
    if media_type is None:
        return [], {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    names = []
    types = {}
    for name, s in props.items():
        if isinstance(s, dict) and s.get("readOnly"):
            continue
        names.append(name)
        types[name] = _prop_js_type(s if isinstance(s, dict) else {})
    return sorted(names), types


def _request_body_prop_schemas(op: Operation) -> Dict[str, Dict[str, Any]]:
    """Return top-level writable request-body property schemas by raw name.

    This is used only for dependency *shape* inference (for example a bare
    ``site`` field whose schema is ``SiteRef{id}``), not for injecting any
    domain knowledge.  The first media variant matches the existing body
    rendering policy used by :func:`_request_body_props`.
    """
    media_type, schema = select_request_variant(op)
    if media_type is None:
        return {}
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for name, value in props.items():
        if isinstance(value, dict) and not value.get("readOnly"):
            out[name] = value
    return out


def _response_codes(op: Operation) -> (List[int], List[int], bool):
    success, error, has_default = [], [], False
    for r in op.responses:
        if r.is_default:
            has_default = True
            continue
        try:
            code = int(r.status)
        except ValueError:
            continue
        if 200 <= code < 300:
            success.append(code)
        else:
            error.append(code)
    return sorted(set(success)), sorted(set(error)), has_default


def _action_segment(path: str) -> str:
    segs = path.strip("/").split("/")
    static_tail = [s for s in segs if not (s.startswith("{") and s.endswith("}"))]
    return static_tail[-1] if static_tail else "action"


def _generic_fn_name(kind: str, entity_display: str, plural: str) -> str:
    if kind == "list":
        return to_camel("list_" + plural)
    if kind == "create":
        return to_camel("create_" + entity_display)
    if kind == "get":
        return to_camel("get_" + entity_display)
    if kind == "update":
        return to_camel("update_" + entity_display)
    if kind == "delete":
        return to_camel("delete_" + entity_display)
    return to_camel(entity_display)


def _op_kind(op: Operation, entity: EntityCandidate) -> str:
    if op.path == entity.collection_path:
        return "list" if op.method == "GET" else ("create" if op.method == "POST" else "action")
    if op.path == entity.item_path:
        if op.method == "GET":
            return "get"
        if op.method in ("PUT", "PATCH"):
            return "update"
        if op.method == "DELETE":
            return "delete"
        return "action"
    return "action"


def _norm(s: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", s.lower())


def _entity_has_create_op(entity: EntityCandidate) -> bool:
    return any(o.method == "POST" and o.path == entity.collection_path for o in entity.operations)


def _own_action_path_params(op: Operation, entity: EntityCandidate) -> List[str]:
    """Parameters in the entity-item prefix of an action path.

    For /tasks/{task}/labels/{label}, owned by tasks, only ``task`` belongs
    to the owning entity; ``label`` remains available for dependency
    matching against another entity.  Parameter aliases are matched by
    their structural positions rather than spelling.
    """
    if not entity.item_path:
        return []
    action_segments = _segments(op.path)
    item_segments = _segments(entity.item_path)
    if len(action_segments) < len(item_segments):
        return []
    own = []
    for action_segment, item_segment in zip(action_segments, item_segments):
        if _is_param(item_segment):
            if not _is_param(action_segment):
                return []
            own.append(action_segment[1:-1])
        elif action_segment != item_segment:
            return []
    return own


def build_op_plan(op: Operation, entity: Optional[EntityCandidate], kind: str,
                   fields: List[str], key_fields: Optional[List[str]] = None,
                   key_response_field: Optional[str] = None,
                   all_entities: Optional[List[EntityCandidate]] = None,
                   all_keys: Optional[Dict[str, KeyInfo]] = None) -> OpFunctionPlan:
    path_param_names = [s[1:-1] for s in _segments(op.path) if _is_param(s)]
    path_param_map = {p: safe_identifier(p) for p in path_param_names}
    query_params = [p.name for p in op.query_params]
    header_params = [p.name for p in op.header_params]
    cookie_params = [p.name for p in op.cookie_params]
    body_props, body_types = _request_body_props(op)
    request_media_type, _request_schema = select_request_variant(op)
    success, error, has_default = _response_codes(op)

    if entity is not None:
        if _looks_like_identifier(op.operation_id):
            js_name = op.operation_id
        elif kind == "action":
            js_name = to_camel(f"{_action_segment(op.path)}_{entity.display_name}")
        else:
            js_name = _generic_fn_name(kind, entity.display_name, entity.plural_display_name)
        params = fields
    else:
        js_name = op.operation_id if _looks_like_identifier(op.operation_id) else to_camel(op.path)
        params = sorted(set(path_param_names) | set(query_params) | set(header_params) | set(cookie_params) | set(body_props))

    description_base = " ".join(op.summary.split()) if op.summary else _default_description(op, entity, kind)
    emits_done = op.method in ("POST", "PUT", "PATCH", "DELETE")

    server_assigned: List[str] = []
    if kind == "create" and key_fields:
        own_input_norm = {_norm(p) for p in body_props} | {_norm(p) for p in query_params}
        server_assigned = [kf for kf in key_fields if _norm(kf) not in own_input_norm]

    story_deps: List[tuple] = []
    own_entity_key = None
    if kind in ("action", "update") and entity is not None and _entity_has_create_op(entity):
        # Both action sub-operations and update operations target an
        # EXISTING instance of their own entity, so both need a story that
        # waits for one to exist and uses its real key -- found missing
        # for `update` too while fixing the same gap for actions: PUT/
        # PATCH-based update operations (updateBook, updateGarage, ...)
        # were never invoked by any generated story either. Gated on the
        # entity actually being creatable -- an entity reachable only via
        # a read-only path can never satisfy this wait, which would hang
        # a real BP engine forever (see the analogous NetBox
        # BackgroundQueue fix in dependencies.py/stories_js.py).
        own_entity_key = entity.key
        own_path_params = (path_param_names if kind == "update"
                           else _own_action_path_params(op, entity))
        for pn in own_path_params:
            story_deps.append((safe_identifier(pn), entity.key))
    if kind in ("action", "standalone", "update") and all_entities is not None and all_keys is not None:
        from ..inference.dependencies import (
            match_field_to_entity,
            match_array_ids_to_entity,
            match_path_parameter_to_entity,
            match_schema_field_to_entity,
        )
        creatable_entities = [e for e in all_entities if _entity_has_create_op(e)]
        candidate_fields = set(body_props) | set(query_params) | set(header_params) | set(cookie_params) | set(path_param_names)
        body_schemas = _request_body_prop_schemas(op)
        # Never let Python hash/set iteration choose dependency order: that
        # changes dependency_position and therefore the multi-instance
        # cross-binding schedule across processes even with the same seed.
        for raw_name in sorted(candidate_fields):
            field_js_name = safe_identifier(raw_name)
            if any(field_js_name == p for p, _ in story_deps):
                continue
            match = None
            if raw_name in path_param_names:
                match = match_path_parameter_to_entity(
                    raw_name, creatable_entities,
                    exclude_key=(entity.key if entity else None),
                )
            if not match:
                match = match_field_to_entity(raw_name, creatable_entities, all_keys,
                                              exclude_key=(entity.key if entity else None))
            if not match and raw_name in body_schemas:
                match = match_array_ids_to_entity(
                    raw_name, body_schemas[raw_name], (entity.key if entity else None),
                    creatable_entities, all_keys, exclude_key=(entity.key if entity else None)
                )
            if not match and raw_name in body_schemas:
                match = match_schema_field_to_entity(
                    raw_name, body_schemas[raw_name], (entity.key if entity else None),
                    creatable_entities, all_keys, exclude_key=(entity.key if entity else None)
                )
            if match:
                story_deps.append((field_js_name, match[0]))
        # Generic fallback for an identifier alias that cannot be matched by
        # spelling alone (for example an abbreviated field): if the operation
        # summary names exactly one still-unbound creatable entity, bind the
        # sole remaining *Id field to that entity. This uses only OpenAPI text
        # and remains deliberately ambiguity-intolerant.
        bound_fields = {p for p, _ in story_deps}
        bound_targets = {target for _, target in story_deps}
        unresolved_ids = sorted(raw for raw in candidate_fields
                                if safe_identifier(raw) not in bound_fields
                                and _norm(raw).endswith("id"))
        summary_norm = _norm(op.summary or "")
        mentioned = [e for e in creatable_entities
                     if e.key not in bound_targets and any(
                         token and token in summary_norm for token in
                         (_norm(e.display_name), _norm(e.plural_display_name), _norm(e.family_segment)))]
        if len(unresolved_ids) == 1 and len(mentioned) == 1:
            story_deps.append((safe_identifier(unresolved_ids[0]), mentioned[0].key))

    # The list is semantically a mapping from operation field to producer.
    # Canonicalize it before rendering so PYTHONHASHSEED cannot affect JS.
    story_deps = sorted(story_deps, key=lambda x: (x[0], x[1]))

    return OpFunctionPlan(
        js_name=safe_identifier(js_name), op=op, kind=kind,
        entity_key=entity.key if entity else None,
        params=[safe_identifier(p) for p in params],
        path_param_map=path_param_map, query_params=query_params, header_params=header_params,
        cookie_params=cookie_params,
        body_props=body_props, body_prop_types=body_types,
        request_media_type=request_media_type,
        description_base=description_base, success_codes=success, error_codes=error,
        has_default_response=has_default, emits_done_event=emits_done,
        source_pointer=op.pointer,
        server_assigned_key_fields=[safe_identifier(k) for k in server_assigned],
        server_assigned_response_field=(key_response_field if server_assigned else None),
        story_dependencies=story_deps,
        own_entity_key=own_entity_key,
    )


def _looks_like_identifier(name: Optional[str]) -> bool:
    return bool(name) and not name[0].isdigit()


def _default_description(op: Operation, entity: Optional[EntityCandidate], kind: str) -> str:
    label = entity.display_name if entity else op.path.strip("/").replace("/", " ")
    plural = entity.plural_display_name if entity else label
    return {
        "list": f"List {plural}",
        "create": f"Create {label}",
        "get": f"Get {label}",
        "update": f"Update {label}",
        "delete": f"Delete {label}",
    }.get(kind, f"{op.method} {op.path}")


def build_plan(doc: Document, entities: List[EntityCandidate], keys: Dict[str, KeyInfo],
               dependencies: List[DependencyEdge], graph: DependencyGraph,
               standalone_ops: List[Operation], seed: int,
               instances_per_entity: int = 1, instances_per_action: int = 1) -> Plan:
    entity_plans: List[EntityPlan] = []
    for e in entities:
        key = keys[e.key]
        fields = set(key.fields)
        for op in e.operations:
            b_props, _ = _request_body_props(op)
            fields.update(b_props)
            fields.update(p.name for p in op.path_params)
            fields.update(p.name for p in op.query_params)
            fields.update(p.name for p in op.header_params)
            fields.update(p.name for p in op.cookie_params)
        fields_sorted = sorted(fields)

        ep = EntityPlan(entity=e, key=key, fields=[safe_identifier(f) for f in fields_sorted])
        raw_to_js = {f: safe_identifier(f) for f in fields_sorted}
        ep.fields = [raw_to_js[f] for f in fields_sorted]

        for op in sorted(e.operations, key=lambda o: (o.path, o.method)):
            kind = _op_kind(op, e)
            plan_op = build_op_plan(op, e, kind, fields_sorted, key_fields=key.fields,
                                     key_response_field=key.response_field,
                                     all_entities=entities, all_keys=keys)
            ep.ops.append(plan_op)
            if kind == "get":
                ep.has_item_get = True
                ep.get_op = plan_op
            if kind == "create":
                ep.create_op = plan_op
            if kind == "delete":
                ep.has_delete = True
                ep.delete_op = plan_op

        for op in sorted(e.action_operations, key=lambda o: (o.path, o.method)):
            action_fields = sorted(set(fields_sorted) |
                                    {p.name for p in op.path_params} |
                                    {p.name for p in op.query_params} |
                                    {p.name for p in op.header_params} |
                                    {p.name for p in op.cookie_params} |
                                    set(_request_body_props(op)[0]))
            plan_op = build_op_plan(op, e, "action", action_fields,
                                     all_entities=entities, all_keys=keys)
            ep.ops.append(plan_op)

        ep.dependencies = sorted(
            (d for d in dependencies if d.source == e.key),
            key=lambda d: (d.field_name, d.target, d.source),
        )
        entity_plans.append(ep)

    standalone_plans = []
    for op in standalone_ops:
        standalone_plans.append(build_op_plan(op, None, "standalone", [],
                                               all_entities=entities, all_keys=keys))

    _dedupe_function_names(entity_plans, standalone_plans, doc)

    return Plan(doc=doc, entities=entity_plans, standalone_ops=standalone_plans,
                graph=graph, seed=seed,
                instances_per_entity=max(1, int(instances_per_entity)),
                instances_per_action=max(1, int(instances_per_action)))


def _dedupe_function_names(entity_plans: List[EntityPlan], standalone_plans: List[OpFunctionPlan],
                            doc: Document) -> None:
    """Ensures every generated top-level function name is unique. Collisions
    are broken deterministically (stable operation order) by appending a
    numeric suffix, and every rename is recorded as a warning so it is
    visible in generation_report.json rather than silently changing
    behavior."""
    seen: Dict[str, int] = {}
    all_ops: List[OpFunctionPlan] = []
    for ep in entity_plans:
        all_ops.extend(ep.ops)
    all_ops.extend(standalone_plans)

    for op in all_ops:
        base = op.js_name
        if base not in seen:
            seen[base] = 1
            continue
        seen[base] += 1
        new_name = f"{base}_{seen[base]}"
        doc.warnings.append(
            f"Function name collision: '{base}' (from {op.op.method} {op.op.path}) "
            f"renamed to '{new_name}' to keep generated output loadable."
        )
        op.js_name = new_name
