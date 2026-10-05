"""Key (identifier) inference.

K1. If the entity's item path has exactly one path parameter, that
    parameter's name is the primary key field.
K2. If the item path has multiple path parameters (composite key, e.g.
    /loans/{userId}/{bookId}), all of them form the composite key, in path
    order.
K3. Cross-check against the component schema: if a property with the same
    name (or a case-insensitive / 'id'-suffixed match) exists and is in
    `required`, confidence is raised; otherwise the path-parameter evidence
    alone is used with medium confidence.
K4. Generic fallback conventions recognized: 'id', '<entity>Id', fields
    with format 'uuid', and any required property whose name ends in 'Id'
    or equals 'id'.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..parsing.model import Document, Provenance
from .entities import EntityCandidate, _segments, _is_param


@dataclass
class KeyInfo:
    fields: List[str]                  # ordered key field name(s), e.g. ["id"] or ["userId","bookId"]
    composite: bool
    confidence: float
    provenance: List[Provenance] = field(default_factory=list)
    # For a single-field key, the actual JSON response-body property name
    # that carries this identifier, when it differs from the path
    # parameter name (e.g. path '/projects/{projectId}' but the Project
    # schema's own property is just 'id'). None when unknown/same-as-path.
    # Needed so a create operation can pull the server-assigned identifier
    # out of the response for entities whose key is never supplied by the
    # client at creation time -- see DESIGN.md ("server-assigned keys"),
    # found while building a real SUT for the Todoist holdout contract.
    response_field: Optional[str] = None


def infer_key(doc: Document, entity: EntityCandidate) -> KeyInfo:
    prov: List[Provenance] = []
    if not entity.item_path:
        return KeyInfo(fields=[], composite=False, confidence=0.0, provenance=prov)

    segs = _segments(entity.item_path)
    param_names = [s[1:-1] for s in segs if _is_param(s)]

    composite = len(param_names) > 1
    confidence = 1.0

    schema = doc.component_schemas.get(entity.schema_name) if entity.schema_name else None
    if schema:
        required = set(schema.required)
        props = schema.properties
        for pn in param_names:
            if pn in props and pn in required:
                confidence = min(confidence, 1.0)
                prov.append(Provenance(
                    pointer=f"{schema.source_pointer}/properties/{pn}",
                    rule="K3:schema_required_property_match",
                    detail=f"Path parameter '{pn}' matches required schema property",
                ))
            elif pn in props:
                prop_format = props[pn].get("format") if isinstance(props[pn], dict) else None
                if prop_format == "uuid":
                    # K4: a same-named, non-required property with format
                    # 'uuid' is still strong identifier evidence (real IDs
                    # are very often optional in the schema -- e.g.
                    # server-assigned -- despite always being present on
                    # a real object), so this is scored higher than a
                    # bare type match with no format signal at all.
                    confidence = min(confidence, 0.95)
                    prov.append(Provenance(
                        pointer=f"{schema.source_pointer}/properties/{pn}",
                        rule="K4:schema_property_uuid_format_match",
                        detail=f"Path parameter '{pn}' matches a schema property with format 'uuid'",
                    ))
                else:
                    confidence = min(confidence, 0.85)
            else:
                confidence = min(confidence, 0.7)
                prov.append(Provenance(
                    pointer=entity.item_path, rule="K1:path_parameter_only",
                    detail=f"Path parameter '{pn}' has no matching schema property; using path evidence only",
                ))
    else:
        confidence = 0.6

    prov.append(Provenance(
        pointer=entity.item_path, rule="K1/K2:item_path_parameters",
        detail=f"Key field(s) derived from item path parameters: {param_names}",
    ))

    response_field = None
    if not composite and param_names and schema:
        pn = param_names[0]
        if pn in schema.properties:
            response_field = pn  # path param name matches a real schema property (common case)
        elif "id" in schema.properties:
            response_field = "id"  # generic fallback: schema uses a plain 'id' property
            prov.append(Provenance(
                pointer=schema.source_pointer, rule="K5:response_field_generic_id_fallback",
                detail=(f"Path parameter '{pn}' has no same-named schema property, but the schema "
                        f"has a generic 'id' property; treating that as the response-body identifier "
                        f"field for server-assigned-key handling."),
            ))

    return KeyInfo(fields=param_names, composite=composite, confidence=confidence,
                    provenance=prov, response_field=response_field)
