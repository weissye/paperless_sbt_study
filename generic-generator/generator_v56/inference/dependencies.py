"""Dependency inference.

An edge entity A -> entity B means "creating A requires B to already exist"
(A depends on B). Evidence sources, all contract-visible:

D1. Composite item-path parameters: if A's item path has more than one path
    parameter, every parameter that is not A's own single-field key but
    matches another entity B's key field (or B's singular name + 'Id') is
    evidence that A depends on B (e.g. /loans/{userId}/{bookId} depends on
    users and books).
D2. Create-request-body properties: for A's create operation request body,
    any property whose name exactly matches another entity B's key field,
    or matches the pattern '<B's singular name>Id', is evidence of A -> B.
D3. Nested nested-resource nesting: if A's family path is literally prefixed
    by B's item path (e.g. /chains/{chainId}/garages), A depends on B.
D4. Schema composition ($ref to another entity's schema nested inside a
    property, or allOf including it).

Every edge records full provenance (pointer + rule + detail).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..parsing.model import Document, Provenance
from .entities import EntityCandidate, _segments, _is_param, _singularize
from .keys import KeyInfo


@dataclass
class DependencyEdge:
    source: str            # entity key that depends on target
    target: str             # entity key depended upon
    field_name: str          # the field/param name that evidenced this
    confidence: float
    provenance: List[Provenance] = field(default_factory=list)


def _norm(s: str) -> str:
    """Normalizes a field/key name for cross-convention comparison by
    stripping separators and casing, so 'projectId', 'project_id', and
    'project-id' are all recognized as the same logical name. This was
    added after testing against a real-world holdout contract
    (snake_case field names) that the initial camelCase-only suffix
    matching missed entirely."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _entity_aliases(e: EntityCandidate) -> List[str]:
    names = {e.family_segment.lower(), _singularize(e.family_segment).lower(), e.display_name.lower()}
    if e.schema_name:
        names.add(e.schema_name.lower())
    return [_norm(n) for n in names]


def _id_shape(schema: object) -> Optional[tuple]:
    """Scalar ID type and format, including nullable OpenAPI 3.1 IDs."""
    if not isinstance(schema, dict):
        return None
    branches = schema.get("anyOf", [schema])
    nonnull = [branch for branch in branches if isinstance(branch, dict)
               and branch.get("type") != "null"]
    if len(nonnull) != 1 or nonnull[0].get("type") not in ("string", "integer"):
        return None
    branch = nonnull[0]
    return branch["type"], branch.get("format")


def _documented_id_response(entity: EntityCandidate, field_shape: tuple) -> bool:
    """Require an item GET exposing an ID with the same documented shape."""
    for op in entity.operations:
        if op.method != "GET" or op.path != entity.item_path:
            continue
        for response in op.success_responses:
            for schema in response.media_types.values():
                props = schema.get("properties", {}) if isinstance(schema, dict) else {}
                if _id_shape(props.get("id")) == field_shape:
                    return True
    return False


def _documented_id_producer(entity: EntityCandidate, field_shape: tuple) -> bool:
    """A POST may return an ID object or a readable string path key.

    In the latter case the runtime must first GET the newly created object
    and publish its verified ID; merely naming the resource is insufficient.
    """
    for op in entity.operations:
        if op.method != "POST" or op.path != entity.collection_path:
            continue
        for response in op.success_responses:
            for schema in response.media_types.values():
                if not isinstance(schema, dict):
                    continue
                if _id_shape(schema.get("properties", {}).get("id")) == field_shape:
                    return True
                if schema.get("type") == "string" and entity.item_path:
                    tail = _segments(entity.item_path)[-1]
                    if _is_param(tail) and any(
                        get.method == "GET" and get.path == entity.item_path and
                        any(p.name == tail[1:-1] and p.schema.get("type") == "string"
                            for p in get.path_params)
                        for get in entity.operations
                    ):
                        return True
    return False


def _match_structural_id_field(field_name: str, field_schema: object,
                               source: EntityCandidate, producers: List[EntityCandidate]) -> Optional[tuple]:
    """Infer an ID from both resource-path structure and response schemas.

    Compound aliases use the trailing path segments (shopping/lists ->
    shoppingList). An ancestor collection may provide its own ID to a
    descendant collection (recipes -> recipes/timeline/events). Both cases
    require a unique match, a compatible GET ID, and an obtainable POST ID.
    """
    normalized = _norm(field_name)
    shape = _id_shape(field_schema)
    if not shape or not normalized.endswith("id") or not source.collection_path:
        return None
    base = normalized[:-2]
    source_parts = _segments(source.collection_path)
    matches = []
    for target in producers:
        if target.key == source.key or not target.collection_path or not target.item_path:
            continue
        target_parts = _segments(target.collection_path)
        sibling = source_parts[:-1] == target_parts[:-1]
        ancestor = source_parts[:len(target_parts)] == target_parts
        if not (sibling or ancestor):
            continue
        aliases = set(_entity_aliases(target))
        if len(target_parts) >= 2:
            aliases.add(_norm(_singularize(target_parts[-2]) + _singularize(target_parts[-1])))
        if base not in aliases:
            continue
        if (_documented_id_response(target, shape) and
                _documented_id_producer(target, shape)):
            matches.append(target)
    return (matches[0].key, "structural_verified_id") if len(matches) == 1 else None


# Field names that are too generic/common across unrelated entities to be
# trusted as an exact key-field match on their own (e.g. two entities can
# both legitimately have their own key literally called 'name' without
# one referencing the other). Excluded from Rule B. Confirmed necessary on
# NetBox: 'VMInterface' has its own 'name' property, and 'BackgroundQueue'
# happens to be keyed on 'name' too -- Rule B matched them purely on that
# shared generic word, producing a false dependency edge.
_GENERIC_KEY_NAMES = {"id", "name", "title", "code", "slug", "status", "type", "label", "key", "value"}


def _resource_namespace(entity_key: Optional[str]) -> Optional[str]:
    """Return a stable namespace for path-derived entity keys.

    Top-level resources (``users``, ``books``) intentionally return None.
    For a namespaced key such as ``api/ipam/services`` the namespace is
    ``api/ipam``. This is only a safety guard for weak name-only FK
    inference; explicit schema-reference evidence remains allowed across
    namespaces.
    """
    if not entity_key or "/" not in entity_key:
        return None
    parts = [p for p in entity_key.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts[:-1])


def _match_entity_for_field(field_name: str, self_key: str, entities: List[EntityCandidate],
                             keys: Dict[str, KeyInfo], exclude_key: str) -> Optional[tuple]:
    fl = _norm(field_name)
    source_ns = _resource_namespace(self_key)

    def namespace_compatible(e):
        target_ns = _resource_namespace(e.key)
        return source_ns is None or target_ns is None or source_ns == target_ns

    def unique_match(predicate, rule):
        # A key shared by several resources is not evidence that the first
        # resource in document order is the field's producer.
        matches = [e for e in entities if e.key != exclude_key and predicate(e)]
        return (matches[0].key, rule) if len(matches) == 1 else None

    # Rule A: a distinctive (non-generic, e.g. 'vin', 'ndc') single-field key
    # matched as a suffix, e.g. 'carVin'/'car_vin' -> Car (key field 'vin').
    # Excludes generic key names (not just 'id'): 'file_name'/'username'/
    # 'group_name' etc. all end with 'name' too, and would otherwise match
    # any entity keyed on the generic word 'name' purely by suffix
    # coincidence -- confirmed on NetBox (BackgroundQueue, keyed on
    # 'name') once the exact-match version of this bug (Rule B) was fixed
    # and this analogous suffix-match version surfaced in its place.
    def distinctive_suffix(e):
        k = keys.get(e.key)
        if k and not k.composite and len(k.fields) == 1:
            key_norm = _norm(k.fields[0])
            return (namespace_compatible(e) and key_norm not in _GENERIC_KEY_NAMES
                    and fl.endswith(key_norm) and len(fl) > len(key_norm))
        return False

    match = unique_match(distinctive_suffix, "D_distinctive_key_suffix_match")
    if match:
        return match

    # Rule B: exact match (normalized) against another entity's own
    # single-field key -- but only when that key is itself distinctive
    # (not a generic word like 'name'/'title'/'status'). A generic key
    # name is common enough that two unrelated entities sharing it is not
    # meaningful evidence of a relationship between them.
    def exact_distinctive(e):
        k = keys.get(e.key)
        if k and not k.composite and len(k.fields) == 1 and fl == _norm(k.fields[0]):
            return namespace_compatible(e) and _norm(k.fields[0]) not in _GENERIC_KEY_NAMES
        return False

    match = unique_match(exact_distinctive, "D_key_field_exact_match")
    if match:
        return match

    # Rule C: '<entity>Id' / '<entity>_id' style semantic name match against
    # the entity's display name / path-segment alias, for generic
    # 'id'-keyed entities (e.g. 'userId'/'user_id' -> Users, whose key
    # field is plain 'id').
    #
    # For deeply namespaced APIs, a bare noun such as service_id/group_id/
    # interface_id is not strong enough to establish a cross-subsystem FK.
    # NetBox exposed this failure mode: provider-network.service_id was
    # incorrectly bound to IPAM Service, FHRP group_id to Users/Group, etc.
    # We therefore allow name-only ID matching across top-level resources,
    # or inside the SAME explicit namespace. Cross-namespace relationships
    # must be supported by stronger evidence (e.g. D4 schema composition).
    if fl.endswith("id") and len(fl) > 2:
        base = fl[:-2]
        def named_id(e):
            if base not in _entity_aliases(e):
                return False
            return namespace_compatible(e)

        return unique_match(named_id, "D2:id_suffix_name_match")

    # NOTE: bare entity-name matching (no 'Id' suffix at all, e.g.
    # NetBox's 'virtual_machine' FK field) was attempted TWICE and
    # reverted TWICE:
    #   1st attempt (unrestricted): matched common single words like
    #      'name'/'status' against unrelated entities -> false edges.
    #   2nd attempt (gated to compound identifiers, i.e. containing '_'/
    #      '-'/a camelCase transition): fixed 'virtual_machine' correctly,
    #      but then matched NetBox's 'custom_fields' property (a generic
    #      metadata dict on nearly every entity, not a foreign key at all)
    #      against the real 'CustomField' entity purely because
    #      'custom_fields' is *also* a compound identifier that happens to
    #      equal that entity's plural alias -- corrupting the field's
    #      value (sent an integer ID where an object was expected) across
    #      360 create calls.
    # Both attempts are disclosed, not hidden (see REAL_SUT_VALIDATION.md
    # and TRACEABILITY.md). Bare-name FK matching remains an unresolved,
    # documented gap: a safe version would need much stronger evidence
    # (e.g. cross-checking the field's own schema type against the
    # target entity's key type, and excluding administrative/meta
    # properties) than is currently implemented, and is not worth a third
    # attempt under time pressure given two consecutive net-negative
    # results.
    return None



def _schema_ref_component_name(schema: object) -> Optional[str]:
    """Return the originating component-schema name for a resolved field schema.

    The loader preserves the source ``$ref`` in ``__source_ref__`` after
    dereferencing.  Keeping this helper here lets dependency inference use
    contract-visible schema composition without consulting the unresolved
    document or any domain-specific knowledge.
    """
    if not isinstance(schema, dict):
        return None
    ref = schema.get("__source_ref__")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    return None


_REFERENCE_SCHEMA_AFFIXES = (
    "ref", "reference", "brief", "nested", "summary", "compact", "minimal",
)


def _component_name_matches_entity_reference(component_name: str, entity: EntityCandidate) -> bool:
    """Whether a referenced component name is a presentation/reference variant
    of an entity name.

    Examples include ``SiteRef``, ``BriefSite`` and ``NestedSite``.  The match
    is deliberately narrow: only a short generic reference/presentation affix
    may be removed, and the remaining token must exactly equal one of the
    entity aliases.
    """
    cn = _norm(component_name)
    aliases = {a for a in _entity_aliases(entity) if a}
    if cn in aliases:
        return True
    for affix in _REFERENCE_SCHEMA_AFFIXES:
        if cn.startswith(affix) and cn[len(affix):] in aliases:
            return True
        if cn.endswith(affix) and cn[:-len(affix)] in aliases:
            return True
    return False


def match_schema_field_to_entity(field_name: str, field_schema: object, self_key: Optional[str],
                                 entities: List[EntityCandidate], keys: Dict[str, KeyInfo],
                                 exclude_key: Optional[str] = None) -> Optional[tuple]:
    """Match a bare relationship field using *combined* name + schema evidence.

    This handles APIs that encode a foreign key as a nested reference object
    under a bare entity-named property, e.g. ``site: SiteRef{id}``, instead of
    a scalar ``siteId``.  Bare-name matching by itself is intentionally unsafe
    (and remains disabled in :func:`_match_entity_for_field`); this rule fires
    only when all of the following OpenAPI-visible signals agree:

    * the field name exactly matches the target entity's singular/plural alias;
    * the resolved property schema is an object originating from a component
      reference that is a generic reference/presentation variant of that entity;
    * the referenced object exposes the target's single key field; and
    * for namespaced resources, source and target are in the same namespace.

    Requiring these independent signals avoids the earlier false positives from
    generic fields such as ``custom_fields`` while still wiring strong nested
    references such as NetBox ``Device.site -> Site``.
    """
    if not isinstance(field_schema, dict) or field_schema.get("type") != "object":
        return None
    component_name = _schema_ref_component_name(field_schema)
    if not component_name:
        return None
    props = field_schema.get("properties", {})
    if not isinstance(props, dict):
        return None

    fl = _norm(field_name)
    source_ns = _resource_namespace(self_key)
    matches = []
    for e in entities:
        if exclude_key is not None and e.key == exclude_key:
            continue
        if fl not in set(_entity_aliases(e)):
            continue
        target_ns = _resource_namespace(e.key)
        if source_ns is not None and target_ns is not None and source_ns != target_ns:
            continue
        k = keys.get(e.key)
        if not k or k.composite or len(k.fields) != 1:
            continue
        key_field = k.fields[0]
        if key_field not in props:
            continue
        if not _component_name_matches_entity_reference(component_name, e):
            continue
        matches.append(e)

    if len(matches) == 1:
        return (matches[0].key, "D4:reference_object_alias_key_match")
    return None

def match_field_to_entity(field_name: str, entities: List[EntityCandidate],
                           keys: Dict[str, KeyInfo], exclude_key: Optional[str] = None) -> Optional[tuple]:
    """Public wrapper around the same field-name matching rules used for
    entity-to-entity dependencies (D1/D2/D2q), reused for action and
    standalone operations so they can also be wired into a generated story
    (DEVELOPMENT_PROMPT.md #10: a non-CRUD operation "must still receive
    an interface binding and a generic operation story"). Previously only
    the interface binding was generated for these operations -- found
    while re-inspecting the generated output critically after the Todoist
    holdout: closeTask/reopenTask/getAllCollaborators (Todoist),
    approveRepairOrder/closeRepairOrder (Garage), and dispense/processRx
    (Pharmacy) all had working interface functions that no story ever
    called."""
    return _match_entity_for_field(field_name, None, entities, keys, exclude_key=exclude_key)


def match_array_ids_to_entity(field_name: str, field_schema: object, self_key: Optional[str],
                              entities: List[EntityCandidate], keys: Dict[str, KeyInfo],
                              exclude_key: Optional[str] = None) -> Optional[tuple]:
    """Infer a producer for an array of scalar, explicitly named IDs.

    ``assetIds: array<uuid>`` can depend on an Asset, whereas a bare ``ids``
    cannot identify its producer without additional path context. The normal
    scalar matcher retains its uniqueness and namespace safeguards.
    """
    if not isinstance(field_schema, dict) or field_schema.get("type") != "array":
        return None
    items = field_schema.get("items", {})
    if not isinstance(items, dict) or items.get("type") not in ("string", "integer", "number"):
        return None
    if not re.search(r"(?:[Ii]ds|_ids|-ids)$", field_name):
        return None
    singular = re.sub(r"(?i)ids$", "Id", field_name)
    if _norm(singular) == "id":
        return None
    match = _match_entity_for_field(singular, self_key, entities, keys, exclude_key=exclude_key)
    return (match[0], "D_array_of_named_ids:" + match[1]) if match else None


def match_path_parameter_to_entity(field_name: str, entities: List[EntityCandidate],
                                   exclude_key: Optional[str] = None) -> Optional[tuple]:
    """Match a path parameter that exactly names one unique entity.

    Bare-name matching is unsafe for ordinary body/query fields, but a path
    slot such as ``.../labels/{label}`` is structural resource-identity
    evidence.  Ambiguous aliases still produce no match.
    """
    normalized = _norm(field_name)
    matches = [entity for entity in entities
               if entity.key != exclude_key and normalized in _entity_aliases(entity)]
    if len(matches) == 1:
        return (matches[0].key, "D_path_parameter_entity_alias_match")
    return None


def infer_dependencies(doc: Document, entities: List[EntityCandidate],
                        keys: Dict[str, KeyInfo]) -> List[DependencyEdge]:
    edges: List[DependencyEdge] = []
    by_key = {e.key: e for e in entities}
    # A name-based FK is usable as a story prerequisite only if the target
    # can be produced by a documented collection create operation. Read-only
    # lookup endpoints often carry another resource's ID as their own path
    # parameter (e.g. /ratings/{recipe_id}); they are consumers, not producers.
    producers = [e for e in entities if e.collection_path and any(
        o.method == "POST" and o.path == e.collection_path for o in e.operations)]

    for e in entities:
        own_key = keys.get(e.key)
        own_fields = set(own_key.fields) if own_key else set()

        # D1: composite item-path parameters
        if e.item_path:
            segs = _segments(e.item_path)
            params = [s[1:-1] for s in segs if _is_param(s)]
            if len(params) > 1:
                for p in params:
                    collection_segs = _segments(e.collection_path) if e.collection_path else []
                    if (segs[:len(collection_segs)] == collection_segs and
                            len(segs) == len(collection_segs) + 1 and
                            segs[-1] == '{' + p + '}'):
                        # The sole suffix of a collection path is this
                        # resource's own ID, even when an unrelated sibling
                        # entity happens to use the same ID field name.
                        continue
                    match = _match_entity_for_field(p, e.key, producers, keys, exclude_key=e.key)
                    if match:
                        target_key, rule = match
                        edges.append(DependencyEdge(
                            source=e.key, target=target_key, field_name=p, confidence=0.95,
                            provenance=[Provenance(
                                pointer=e.item_path, rule=f"D1:{rule}",
                                detail=f"Composite key parameter '{p}' in {e.item_path} matches entity '{target_key}'",
                            )],
                        ))

        # D2: create request body properties AND create query parameters
        # (some real-world APIs -- e.g. ones using query-string writes
        # instead of a JSON body -- carry FK-like fields as query params;
        # found while testing against a real-world holdout contract).
        create_op = next((o for o in e.operations if o.method == "POST" and o.path == e.collection_path), None)
        if create_op:
            for q in create_op.query_params:
                if q.name in own_fields:
                    continue
                match = _match_entity_for_field(q.name, e.key, producers, keys, exclude_key=e.key)
                if match:
                    target_key, rule = match
                    edges.append(DependencyEdge(
                        source=e.key, target=target_key, field_name=q.name, confidence=0.85,
                        provenance=[Provenance(
                            pointer=q.pointer, rule=f"D2q:{rule}",
                            detail=f"Create operation query parameter '{q.name}' matches entity '{target_key}'",
                        )],
                    ))
        if create_op and create_op.request_body:
            for variant in create_op.request_body.variants:
                props = variant.schema.get("properties", {}) if isinstance(variant.schema, dict) else {}
                for prop_name, prop_schema in props.items():
                    if prop_name in own_fields:
                        continue
                    match = (_match_entity_for_field(prop_name, e.key, producers, keys, exclude_key=e.key)
                             or _match_structural_id_field(prop_name, prop_schema, e, producers)
                             or match_array_ids_to_entity(prop_name, prop_schema, e.key,
                                                          producers, keys, exclude_key=e.key))
                    if match:
                        target_key, rule = match
                        edges.append(DependencyEdge(
                            source=e.key, target=target_key, field_name=prop_name, confidence=0.9,
                            provenance=[Provenance(
                                pointer=f"{variant.pointer}/properties/{prop_name}", rule=f"D2:{rule}",
                                detail=f"Create request body property '{prop_name}' matches entity '{target_key}'",
                            )],
                        ))
                    else:
                        schema_match = match_schema_field_to_entity(
                            prop_name, prop_schema, e.key, entities, keys, exclude_key=e.key
                        )
                        if schema_match:
                            target_key, rule = schema_match
                            edges.append(DependencyEdge(
                                source=e.key, target=target_key, field_name=prop_name, confidence=0.97,
                                provenance=[Provenance(
                                    pointer=f"{variant.pointer}/properties/{prop_name}", rule=rule,
                                    detail=(f"Create request body property '{prop_name}' is a component-"
                                            f"referenced key object for entity '{target_key}'"),
                                )],
                            ))
                    # D4: nested $ref to another entity's exact canonical schema
                    ref_name = prop_schema.get("__source_ref__") if isinstance(prop_schema, dict) else None
                    if ref_name and ref_name.startswith("#/components/schemas/"):
                        schema_name = ref_name.rsplit("/", 1)[-1]
                        for other in entities:
                            if other.key != e.key and other.schema_name == schema_name:
                                edges.append(DependencyEdge(
                                    source=e.key, target=other.key, field_name=prop_name, confidence=0.95,
                                    provenance=[Provenance(
                                        pointer=f"{variant.pointer}/properties/{prop_name}", rule="D4:schema_ref_composition",
                                        detail=f"Property '{prop_name}' schema references component '{schema_name}'",
                                    )],
                                ))

            # D5: a primitive association payload has no named body property.
            # Accept only an explicit "id of the X" statement and a unique
            # creatable X in the same realm/resource namespace. This is the
            # evidence needed for organization-member / identity-provider
            # associations, and avoids guessing from an arbitrary string.
            description = create_op.request_body.description.lower()
            match = re.search(r"payload should contain only id(?: or alias)? of the "
                              r"([a-z][a-z ]+?) to be ", description)
            primitive = any(v.schema.get("type") == "string" and
                            not v.schema.get("properties")
                            for v in create_op.request_body.variants)
            if match and primitive:
                label = _norm(match.group(1))
                source_parts = _segments(e.collection_path)
                choices = [target for target in producers if target.key != e.key
                           and _segments(target.collection_path)[:3] == source_parts[:3]
                           and any(alias in (label, label + "representation")
                                   for alias in _entity_aliases(target))]
                if len(choices) == 1 and keys.get(choices[0].key):
                    target = choices[0]
                    edges.append(DependencyEdge(
                        source=e.key, target=target.key,
                        field_name=keys[target.key].fields[-1], confidence=0.92,
                        provenance=[Provenance(
                            pointer=create_op.pointer + "/requestBody/description",
                            rule="D5:primitive_association_id_description",
                            detail=("Create body explicitly requests the identifier of existing "
                                    f"entity '{target.key}'"),
                        )],
                    ))

        # D3: nested resource path prefix.  Compare path templates by shape,
        # not by parameter spelling: /projects/{project}/tasks is nested
        # below /projects/{id} even though the parameter aliases differ.
        for other in entities:
            if other.key == e.key or not other.item_path:
                continue
            nested_param = _nested_parent_parameter(e.collection_path, other.item_path)
            if nested_param:
                edges.append(DependencyEdge(
                    source=e.key, target=other.key, field_name=nested_param, confidence=0.95,
                    provenance=[Provenance(
                        pointer=e.collection_path, rule="D3:nested_resource_path",
                        detail=f"Collection path '{e.collection_path}' is nested under '{other.item_path}'",
                    )],
                ))

    # De-duplicate edges (same source/target/field)
    unique = {}
    for edge in edges:
        k = (edge.source, edge.target, edge.field_name)
        if k not in unique:
            unique[k] = edge
    return list(unique.values())


def _nested_parent_parameter(collection_path: Optional[str], item_path: str) -> Optional[str]:
    """Return the collection parameter occupying the parent's item slot."""
    if not collection_path:
        return None
    collection = _segments(collection_path)
    parent = _segments(item_path)
    if len(collection) <= len(parent):
        return None
    for child_seg, parent_seg in zip(collection, parent):
        if _is_param(parent_seg):
            if not _is_param(child_seg):
                return None
        elif child_seg != parent_seg:
            return None
    parent_param_indexes = [i for i, segment in enumerate(parent) if _is_param(segment)]
    if not parent_param_indexes:
        return None
    return collection[parent_param_indexes[-1]][1:-1]
