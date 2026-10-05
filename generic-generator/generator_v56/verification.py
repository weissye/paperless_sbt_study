"""OpenAPI-only verification and concurrency-plan derivation.

This module is deliberately application agnostic.  It derives only claims
that can be justified by the supplied contract.  When the contract is not
strong enough, the operation is reported as contract-only or unsupported;
no application-specific fact is guessed.
"""
from __future__ import annotations

import hashlib
import itertools
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .parsing.model import Document, Operation
from .request_variants import select_request_variant


MUTATIONS = {"POST", "PUT", "PATCH", "DELETE"}
PRIMITIVES = {"string", "integer", "number", "boolean"}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _op_id(op: Operation) -> str:
    return op.operation_id or f"{op.method.lower()}:{op.path}"


def _codes(op: Operation, success: bool) -> List[int]:
    specs = op.success_responses if success else op.error_responses
    out = []
    for item in specs:
        try:
            out.append(int(item.status))
        except ValueError:
            pass
    return sorted(set(out))


def _variant(op: Operation, preferred: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    return select_request_variant(op, preferred)


def _response_schema(op: Operation) -> Dict[str, Any]:
    for response in op.success_responses:
        for media_type, schema in response.media_types.items():
            if "json" in media_type.lower() and isinstance(schema, dict):
                return schema
    return {}


def _properties(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {str(k): v for k, v in props.items() if isinstance(v, dict)}


def _parameter_types(op: Operation) -> Dict[str, Optional[str]]:
    """Return documented path-parameter types, keyed by normalized name."""
    return {_norm(p.name): p.schema.get("type") for p in op.path_params}


def _compatible(expected: Optional[str], actual: Optional[str]) -> bool:
    if not expected or not actual:
        return True
    if expected == actual:
        return True
    if not isinstance(expected, str) or not isinstance(actual, str):
        return False
    return expected in {"integer", "number"} and actual in {"integer", "number"}


def _path_compatible(expected: Optional[str], actual: Optional[str]) -> bool:
    """Return whether a response primitive can be serialized into a path slot.

    OpenAPI path parameters are ultimately URI text.  Contracts commonly type
    an identifier as an integer in a response but as a constrained string in a
    path parameter.  That representation difference is safe for identity
    binding and must not remove an existing create/read witness.
    """
    if isinstance(expected, str) and isinstance(actual, str) \
            and expected in PRIMITIVES and actual in PRIMITIVES:
        return True
    return _compatible(expected, actual)


def _identity_inside(name: str, spec: Dict[str, Any], expected: Optional[str]) -> Optional[str]:
    """Choose a documented primitive identity inside a response object.

    The rule is vocabulary-independent: it first prefers a nested property
    matching the containing object's name and then common JSON identity
    roles. Type compatibility prevents, for example, binding a string path
    parameter to a numeric id when a documented string login is available.
    """
    nested = _properties(spec)
    roles = [_norm(name), "name", "username", "login", "slug", "key", "id"]
    for role in roles:
        for child, child_spec in nested.items():
            if (_norm(child) == role and child_spec.get("type") in PRIMITIVES
                    and _compatible(expected, child_spec.get("type"))):
                return f"{name}.{child}"
    return None


def _writable_fields(op: Operation, preferred: Optional[str] = None) -> List[Dict[str, Any]]:
    media_type, schema = _variant(op, preferred)
    result = []
    for name, spec in sorted(_properties(schema).items()):
        kind = spec.get("type")
        if spec.get("readOnly") or kind not in PRIMITIVES:
            continue
        result.append({
            "name": name,
            "type": kind,
            # Swagger 2.0 fields can describe an email address without
            # declaring format: email. Reuse only the field's own explicit
            # wording; this is the same opt-in evidence used by long stories.
            "format": spec.get("format") or (
                "email" if kind == "string" and
                "email address" in str(spec.get("description", "")).lower()
                else None),
            "example": spec.get("example"),
            "enum": list(spec.get("enum", [])) if isinstance(spec.get("enum"), list) else None,
            "minimum": spec.get("minimum"),
            "maximum": spec.get("maximum"),
            "minLength": spec.get("minLength"),
            "maxLength": spec.get("maxLength"),
            "pattern": spec.get("pattern"),
            "media_type": media_type,
            "source": "openapi-request-schema",
        })
    return result


def _observable_fields(op: Operation, get_op: Operation,
                       preferred: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return request fields directly observable under the same GET property.

    Mutation-response schemas are frequently omitted even when the runtime
    returns a complete object.  Requiring them here would erase otherwise
    valid oracles and break cross-system compatibility.  The evaluator uses
    an actual mutation response as stronger acknowledgement when available.
    """
    observed = _properties(_response_schema(get_op))
    result = []
    for field in _writable_fields(op, preferred):
        name = field["name"]
        observed_spec = observed.get(name)
        if not observed_spec:
            continue
        if not _compatible(field.get("type"), observed_spec.get("type")):
            continue
        result.append({**field,
                       "comparison_basis": "same-property-request-and-later-get",
                       "comparison_confidence": "high"})
    return result


def _state_fields(op: Operation, get_op: Operation,
                  preferred: Optional[str] = None) -> List[Dict[str, Any]]:
    """Preserve prior coverage while making comparison confidence explicit."""
    observable = {field["name"] for field in _observable_fields(op, get_op, preferred)}
    return [{**field,
             "comparison_basis": ("same-property-request-and-later-get"
                                  if field["name"] in observable
                                  else "runtime-acknowledgement-required"),
             "comparison_confidence": ("high" if field["name"] in observable else "runtime")}
            for field in _writable_fields(op, preferred)]


def _path_params(path: str) -> List[str]:
    return re.findall(r"\{([^{}]+)\}", path)


def _collection_for(item_path: str) -> Optional[str]:
    parts = [p for p in item_path.rstrip("/").split("/") if p]
    while parts and parts[-1].startswith("{") and parts[-1].endswith("}"):
        parts.pop()
    return "/" + "/".join(parts) if parts else None


def _observation_get(doc: Document, path: str) -> Optional[Operation]:
    return next((op for op in doc.operations if op.method == "GET" and op.path == path and not op.deprecated), None)


def _delete_for(doc: Document, path: str) -> Optional[Operation]:
    return next((op for op in doc.operations if op.method == "DELETE" and op.path == path and not op.deprecated), None)


def _binding(create: Operation, get_op: Operation) -> Optional[Dict[str, Dict[str, str]]]:
    params = _path_params(get_op.path)
    props = _properties(_response_schema(create))
    create_params = set(_path_params(create.path))
    parameter_types = _parameter_types(get_op)
    resource = _last_literal(_collection_for(get_op.path) or get_op.path) or ""
    singular_resource = resource[:-1] if resource.endswith("s") else resource
    if not params:
        return None
    response: Dict[str, str] = {}
    request_path: Dict[str, str] = {}
    evidence: Dict[str, Dict[str, str]] = {}
    unresolved = []
    for parameter in params:
        expected = parameter_types.get(_norm(parameter))
        exact = next((name for name, spec in props.items()
                      if _norm(name) == _norm(parameter)
                      and spec.get("type") in PRIMITIVES
                      and _path_compatible(expected, spec.get("type"))), None)
        metadata = next((name for name, spec in props.items()
                         if any(_norm(str(spec.get(key, ""))) == _norm(parameter)
                                for key in ("x-go-name", "title"))
                         and spec.get("type") in PRIMITIVES
                         and _path_compatible(expected, spec.get("type"))), None)
        inherited = next((name for name in create_params if _norm(name) == _norm(parameter)), None)
        if exact is not None:
            response[parameter] = exact
            evidence[parameter] = {"source": "openapi-property-name", "confidence": "high"}
        elif metadata is not None:
            response[parameter] = metadata
            evidence[parameter] = {"source": "openapi-schema-metadata", "confidence": "high"}
        elif inherited is not None:
            request_path[parameter] = inherited
            evidence[parameter] = {"source": "openapi-parent-path", "confidence": "high"}
        else:
            container = next((name for name in props if _norm(name) == _norm(parameter)), None)
            nested_identity = _identity_inside(container, props[container], expected) if container else None
            if nested_identity:
                response[parameter] = nested_identity
                evidence[parameter] = {"source": "openapi-nested-identity", "confidence": "medium"}
                continue
            # A path parameter named after the singular collection resource
            # (for example {repo} under /repos) denotes the created item.
            if _norm(parameter) == _norm(singular_resource):
                # Rank semantic resource names before generic numeric ids and
                # prefer an exact type match.  A URI can serialize every
                # primitive, but choosing a repository's numeric `id` for a
                # documented string `{repo}` slot is semantically weaker than
                # its documented string `name`.
                roles = {"name": 0, "slug": 1, "key": 2, "id": 3}
                choices = [(0 if _compatible(expected, spec.get("type")) else 1,
                            roles[_norm(name)], name)
                           for name, spec in props.items()
                           if _norm(name) in roles
                           and spec.get("type") in PRIMITIVES
                           and _path_compatible(expected, spec.get("type"))]
                identity = min(choices)[2] if choices else None
                if identity is not None:
                    response[parameter] = identity
                    evidence[parameter] = {"source": "openapi-resource-identity", "confidence": "medium"}
                    continue
            unresolved.append(parameter)
    if len(unresolved) == 1:
        parameter = unresolved[0]
        expected = parameter_types.get(_norm(parameter))
        identity = next((name for name, spec in props.items()
                         if _norm(name) == "id"
                         and _path_compatible(expected, spec.get("type"))), None)
        if identity is not None:
            response[parameter] = identity
            evidence[parameter] = {"source": "openapi-unique-id-fallback", "confidence": "medium"}
            unresolved.pop()
    if unresolved:
        return None
    return {"response": response, "request_path": request_path, "evidence": evidence}


def _last_literal(path: str) -> Optional[str]:
    literals = [part for part in path.strip("/").split("/")
                if part and not (part.startswith("{") and part.endswith("}"))]
    return literals[-1] if literals else None


def _create_for_item(doc: Document, get_op: Operation) -> Tuple[Optional[Operation], Optional[Dict[str, Dict[str, str]]]]:
    collection = _collection_for(get_op.path)
    resource = _last_literal(collection or get_op.path)
    candidates = []
    for candidate in doc.operations:
        if candidate.method != "POST" or candidate.deprecated:
            continue
        if candidate.path != collection and _last_literal(candidate.path) != resource:
            continue
        binding = _binding(candidate, get_op)
        # A create-visibility witness must bind at least one newly returned
        # identity. Reusing only parent path parameters proves collection
        # reachability, not visibility of the created item.
        if binding and binding["response"]:
            candidates.append((candidate, binding))
    exact = [item for item in candidates if item[0].path == collection]
    if len(exact) == 1:
        selected = exact
    else:
        # Prefer the documented producer requiring the fewest pre-existing
        # path resources. This is a contract-derived reachability rule: a
        # root producer is executable without inventing parent identities.
        minimum = min((len(item[0].path_params) for item in candidates), default=0)
        selected = [item for item in candidates if len(item[0].path_params) == minimum]
    return selected[0] if len(selected) == 1 else (None, None)


def _item_get_for_create(doc: Document, create: Operation) -> Tuple[Optional[Operation], Optional[Dict[str, Dict[str, str]]]]:
    resource = _last_literal(create.path)
    candidates = []
    for candidate in doc.operations:
        if candidate.method != "GET" or candidate.deprecated or not _path_params(candidate.path):
            continue
        if _last_literal(_collection_for(candidate.path) or candidate.path) != resource:
            continue
        binding = _binding(create, candidate)
        if binding and binding["response"]:
            candidates.append((candidate, binding))
    exact = [item for item in candidates if _collection_for(item[0].path) == create.path]
    selected = exact if len(exact) == 1 else candidates
    return selected[0] if len(selected) == 1 else (None, None)


def _entity_key(create: Operation) -> str:
    operation_id = _op_id(create)
    if operation_id.endswith("-create"):
        return operation_id[:-7]
    return _last_literal(create.path) or operation_id


def _contract_obligation(op: Operation) -> Dict[str, Any]:
    media_type, schema = _variant(op)
    request_contract = None
    if op.request_body is not None:
        request_contract = {
            "required": bool(op.request_body.required),
            "media_type": media_type,
            "schema_type": schema.get("type") if isinstance(schema, dict) else None,
            "required_fields": sorted(schema.get("required", []))
                if isinstance(schema, dict) else [],
        }
    return {
        "oracle_id": f"contract::{_op_id(op)}",
        "kind": "response-contract",
        "operation_id": _op_id(op),
        "method": op.method,
        "path_template": op.path,
        "success_statuses": _codes(op, True),
        "documented_error_statuses": _codes(op, False),
        "source_pointer": op.pointer,
        "request_contract": request_contract,
    }


def _semantic_obligation(doc: Document, op: Operation) -> Tuple[Optional[Dict[str, Any]], str]:
    if op.method in {"PUT", "PATCH"} and _path_params(op.path):
        get_op = _observation_get(doc, op.path)
        if not get_op:
            return None, "item-read-operation-not-documented"
        fields = _state_fields(
            op, get_op, "application/merge-patch+json" if op.method == "PATCH" else None)
        if not fields:
            return None, "no-stable-primitive-writable-fields-in-request-schema"
        return {
            "oracle_id": f"state::{_op_id(op)}",
            "kind": "written-fields-persist",
            "operation_id": _op_id(op),
            "method": op.method,
            "path_template": op.path,
            "trigger_success_statuses": _codes(op, True),
            "observation": {"method": "GET", "path_template": get_op.path,
                            "success_statuses": _codes(get_op, True)},
            "fields": fields,
            "superseding_methods": ["PUT", "PATCH", "DELETE"],
            "source_pointers": [op.pointer, get_op.pointer],
        }, ""
    if op.method == "DELETE" and _path_params(op.path):
        get_op = _observation_get(doc, op.path)
        if not get_op:
            return None, "item-read-operation-not-documented"
        absent = [code for code in _codes(get_op, False) if 400 <= code < 500]
        if not absent:
            return None, "absence-status-not-documented-by-item-read"
        return {
            "oracle_id": f"state::{_op_id(op)}",
            "kind": "delete-absence",
            "operation_id": _op_id(op),
            "method": "DELETE",
            "path_template": op.path,
            "trigger_success_statuses": _codes(op, True),
            "observation": {"method": "GET", "path_template": get_op.path,
                            "absence_statuses": absent},
            "source_pointers": [op.pointer, get_op.pointer],
        }, ""
    if op.method == "POST":
        get_op, binding = _item_get_for_create(doc, op)
        if not get_op:
            return None, "created-resource-item-read-not-documented"
        if not binding:
            return None, "created-identity-not-bindable-from-documented-response"
        fields = _state_fields(op, get_op)
        return {
            "oracle_id": f"state::{_op_id(op)}",
            "kind": "create-visibility",
            "operation_id": _op_id(op),
            "method": "POST",
            "path_template": op.path,
            "trigger_success_statuses": _codes(op, True),
            "observation": {"method": "GET", "path_template": get_op.path,
                            "success_statuses": _codes(get_op, True),
                            "path_binding_from_response": binding["response"],
                            "path_binding_from_request_path": binding["request_path"],
                            "path_binding_evidence": binding.get("evidence", {})},
            "fields": fields,
            "superseding_methods": ["PUT", "PATCH", "DELETE"],
            "source_pointers": [op.pointer, get_op.pointer],
        }, ""
    return None, "no-openapi-derived-state-observation-rule"


def _field_pairs(fields: List[Dict[str, Any]], maximum: int) -> Iterable[Tuple[Dict[str, Any], Dict[str, Any]]]:
    return itertools.islice(itertools.combinations(fields, 2), maximum)


def _documented_update_carry_fields(create_op: Optional[Operation], op: Operation,
                                    get_op: Operation) -> List[str]:
    """Opt into complete PATCH samples using fields documented in all three schemas.

    Swagger can describe a name and allowed redirect URIs without marking either
    required. A serial control can establish that a particular implementation
    accepts them together, but the schema alone cannot make that assertion.
    This only changes the generated request sample; it adds no oracle claim.
    """
    if op.method != "PATCH" or create_op is None:
        return []
    create_props = _properties(_variant(create_op)[1])
    update_props = _properties(_variant(op)[1])
    observed_props = _properties(_response_schema(get_op))
    names = [name for name, spec in create_props.items()
             if name.lower() == "name" and spec.get("type") == "string"
             and not spec.get("readOnly")
             and "name" in str(spec.get("description", "")).lower()]
    uris = [name for name, spec in create_props.items()
            if spec.get("type") == "array" and not spec.get("readOnly")
            and isinstance(spec.get("items"), dict)
            and spec["items"].get("type") == "string"
            and "redirect uri" in str(spec.get("description", "")).lower()]
    if len(names) != 1 or len(uris) != 1:
        return []
    fields = [names[0], uris[0]]
    for name in fields:
        create_spec = create_props[name]
        update_spec = update_props.get(name, {})
        observed_spec = observed_props.get(name, {})
        if update_spec.get("readOnly") or any(
                spec.get("type") != create_spec.get("type")
                for spec in (update_spec, observed_spec)):
            return []
        if create_spec["type"] == "array" and any(
                not isinstance(spec.get("items"), dict)
                or spec["items"].get("type") != "string"
                for spec in (update_spec, observed_spec)):
            return []
    return fields


def _concurrency_for(doc: Document, op: Operation, maximum_pairs: int,
                     json_disjoint: bool = False) -> List[Dict[str, Any]]:
    if op.method not in {"PUT", "PATCH"} or not _path_params(op.path):
        return []
    get_op = _observation_get(doc, op.path)
    if not get_op:
        return []
    create_op, create_binding = _create_for_item(doc, get_op)
    carry_fields = _documented_update_carry_fields(create_op, op, get_op)
    runtime = {
        "ready": bool(create_op and create_binding),
        "entity_key": _entity_key(create_op) if create_op else None,
        "create_operation_id": _op_id(create_op) if create_op else None,
        "path_binding_from_create_response": create_binding["response"] if create_binding else None,
        "path_binding_from_create_request_path": create_binding["request_path"] if create_binding else None,
        "path_binding_evidence": create_binding.get("evidence", {}) if create_binding else None,
        "limitation": None if create_op and create_binding else
            "requires-a-documented-create-response-to-item-path-binding",
    }
    merge_fields = _writable_fields(op, "application/merge-patch+json")
    default_fields = _writable_fields(op)
    # JSON PATCH does not itself promise merge semantics. Generate candidates
    # only for fields observable under GET; execution must establish both
    # sequential orders before a concurrent outcome can be judged.
    json_fields = (_observable_fields(op, get_op, "application/json")
                   if json_disjoint and op.method == "PATCH" else [])
    if op.method == "PATCH" and not default_fields and merge_fields:
        # JSON Patch variants are arrays and intentionally yield no object
        # fields.  When Merge Patch is also explicitly documented, it is the
        # OpenAPI-justified field source for generated object-patch oracles.
        default_fields = merge_fields
    plans = []
    disjoint_fields = (merge_fields if any(
        f.get("media_type", "").lower() == "application/merge-patch+json"
        for f in merge_fields) else json_fields)
    if op.method == "PATCH" and len(disjoint_fields) >= 2:
        disjoint_media = disjoint_fields[0]["media_type"]
        needs_reverse_control = disjoint_media.lower() == "application/json"
        if len(disjoint_fields) >= 2:
            plans.append({
                "oracle_id": f"concurrency::disjoint-domain::{_op_id(op)}",
                "kind": "disjoint-writes-commute-domain", "operation_id": _op_id(op),
                "method": "PATCH", "path_template": op.path,
                "media_type": disjoint_media, "width_range": [2, 3],
                "eligible_fields": disjoint_fields, "success_statuses": _codes(op, True),
                "observation": {"method": "GET", "path_template": get_op.path,
                                "success_statuses": _codes(get_op, True)},
                "execution": "generated-schedules-are-bounded-samples; evaluator-covers-any-eligible-subset",
                "runtime": {**runtime, "ready": False,
                            "limitation": "domain-oracle-is-instantiated-by-concrete-generated-schedules"},
                "source_pointers": [op.pointer, get_op.pointer],
            })
        for left, right in _field_pairs(disjoint_fields, maximum_pairs):
            plans.append({
                "oracle_id": f"concurrency::disjoint::{_op_id(op)}::{left['name']}::{right['name']}",
                "kind": "disjoint-writes-commute", "operation_id": _op_id(op),
                "method": "PATCH", "path_template": op.path,
                "media_type": disjoint_media, "width": 2,
                **({"reverse_sequential_control": True} if needs_reverse_control else {}),
                "fields": [left, right], "success_statuses": _codes(op, True),
                "observation": {"method": "GET", "path_template": get_op.path,
                                "success_statuses": _codes(get_op, True)},
                "execution": "barrier-release-distinct-connections-then-join-and-quiescence",
                "runtime": runtime,
                "source_pointers": [op.pointer, get_op.pointer],
            })
        if len(disjoint_fields) >= 3:
            for triple in itertools.islice(itertools.combinations(disjoint_fields, 3), maximum_pairs):
                names = "::".join(field["name"] for field in triple)
                plans.append({
                    "oracle_id": f"concurrency::disjoint3::{_op_id(op)}::{names}",
                    "kind": "disjoint-writes-commute", "operation_id": _op_id(op),
                    "method": "PATCH", "path_template": op.path,
                    "media_type": disjoint_media, "width": 3,
                    **({"reverse_sequential_control": True} if needs_reverse_control else {}),
                    "fields": list(triple), "success_statuses": _codes(op, True),
                    "observation": {"method": "GET", "path_template": get_op.path,
                                    "success_statuses": _codes(get_op, True)},
                    "execution": "barrier-release-distinct-connections-then-join-and-quiescence",
                    "runtime": runtime,
                    "source_pointers": [op.pointer, get_op.pointer],
                })
    if default_fields:
        plans.append({
            "oracle_id": f"concurrency::same-field-domain::{_op_id(op)}",
            "kind": "same-field-one-successful-value-visible-domain",
            "operation_id": _op_id(op), "method": op.method,
            "path_template": op.path, "width": 2, "eligible_fields": default_fields,
            "success_statuses": _codes(op, True),
            "observation": {"method": "GET", "path_template": get_op.path,
                            "success_statuses": _codes(get_op, True)},
            "execution": "generated-schedules-are-bounded-samples; evaluator-covers-any-eligible-field",
            "runtime": {**runtime, "ready": False,
                        "limitation": "domain-oracle-is-instantiated-by-concrete-generated-schedules"},
            "source_pointers": [op.pointer, get_op.pointer],
        })
    for field in default_fields[:maximum_pairs]:
        plans.append({
            "oracle_id": f"concurrency::same-field::{_op_id(op)}::{field['name']}",
            "kind": "same-field-one-successful-value-visible", "operation_id": _op_id(op),
            "method": op.method, "path_template": op.path, "width": 2,
            "fields": [field], "success_statuses": _codes(op, True),
            "request_fields": default_fields,
            **({"request_carry_fields": carry_fields} if carry_fields else {}),
            "media_type": field.get("media_type") or "application/json",
            "observation": {"method": "GET", "path_template": get_op.path,
                            "success_statuses": _codes(get_op, True)},
            "execution": "barrier-release-distinct-connections-then-join-and-quiescence",
            "runtime": runtime,
            "source_pointers": [op.pointer, get_op.pointer],
        })
    delete_op = _delete_for(doc, op.path)
    if delete_op:
        absence = [c for c in _codes(get_op, False) if 400 <= c < 500]
        if absence:
            plans.append({
                "oracle_id": f"concurrency::update-delete::{_op_id(op)}",
                "kind": "update-delete-linearizable", "operation_id": _op_id(op),
                "methods": [op.method, "DELETE"], "path_template": op.path, "width": 2,
                "update_success_statuses": _codes(op, True),
                "delete_success_statuses": _codes(delete_op, True),
                "observation": {"method": "GET", "path_template": get_op.path,
                                "absence_statuses": absence},
                "execution": "barrier-release-distinct-connections-then-join-and-quiescence",
                "runtime": {**runtime, "ready": False,
                            "limitation": "update-delete-needs-a-dedicated-created-resource"},
                "source_pointers": [op.pointer, delete_op.pointer, get_op.pointer],
            })
    return plans


def derive_verification(doc: Document, source_bytes: bytes, max_field_pairs: int = 6,
                        json_disjoint: bool = False) -> Dict[str, Any]:
    operations = [op for op in doc.operations if not op.deprecated]
    contracts = [_contract_obligation(op) for op in operations]
    semantic, coverage, concurrency = [], [], []
    for op in operations:
        obligation, reason = _semantic_obligation(doc, op)
        if obligation:
            semantic.append(obligation)
        if op.method in MUTATIONS:
            coverage.append({
                "operation_id": _op_id(op), "method": op.method, "path_template": op.path,
                "contract_verifier": True, "state_verifier": bool(obligation),
                "state_verifier_kind": obligation.get("kind") if obligation else None,
                "state_limitation": None if obligation else reason,
                "classification": "STATE_VERIFIED" if obligation else "CONTRACT_ONLY",
                "source_pointer": op.pointer,
            })
            concurrency.extend(_concurrency_for(doc, op, max_field_pairs, json_disjoint))
    counts = {
        "operations": len(operations), "contract_verifiers": len(contracts),
        "mutations": len(coverage), "state_verified_mutations": sum(x["state_verifier"] for x in coverage),
        "contract_only_mutations": sum(not x["state_verifier"] for x in coverage),
        "concurrency_oracles": len(concurrency),
    }
    manual = []
    return {
        "schema_version": 1,
        "profile": "openapi-only-verification-and-concurrency",
        "source": {"title": doc.title, "version": doc.version,
                   "openapi_version": doc.openapi_version,
                   "sha256": hashlib.sha256(source_bytes).hexdigest()},
        "policy": {
            "external_application_knowledge_allowed": False,
            "all_operations_receive_contract_verifier": True,
            "state_claims_require_openapi-derived-observation": True,
            "unobservable_mutations_are_reported_contract_only": True,
            "concurrency_executor_role": "transport-and-barrier-only",
            "decision_owner": "generated-provengo-model-and-oracle-manifest",
        },
        "counts": counts,
        "coverage_complete": len(contracts) == len(operations),
        "manual_assumptions": manual,
        "contract_oracles": contracts,
        "state_oracles": semantic,
        "concurrency_oracles": concurrency,
        "mutation_coverage": coverage,
    }
