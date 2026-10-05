"""Entity inference.

Rules (all generic, no hard-coded resource names):

E1. Group operations by their leading static path segment ("family"),
    e.g. /books and /books/{id} both belong to family "books".
E2. A family is a CRUD-like *entity* if it has an item path (a path in the
    family with exactly one trailing path parameter and no further static
    segments after it), e.g. /books/{id}. Families that only ever appear as
    a flat action endpoint (no item path, no path parameters anywhere) are
    treated as standalone *operations*, not entities.
E3. The entity's schema is taken, in priority order, from:
      (a) the request-body schema of the family's POST (create) operation
      (b) the response schema (or array item schema) of the family's GET
          list/collection operation
      (c) the response schema of the item GET operation
    identified via the '__source_ref__' marker left by the $ref resolver
    when the schema originated at #/components/schemas/<Name>.
E4. If no component-schema reference is found, the entity name is derived
    from the family's path segment itself (last static segment, converted
    to a display name), and this is recorded as lower-confidence.
E5. Path segments that occur *after* an item parameter (e.g.
    /repair-orders/{roId}/approve) are lifecycle/action sub-operations of
    the parent entity, not new entities.
E6. A path that ends in the unique family segment of another inferred
    entity (e.g. /projects/{project}/tasks when /tasks/{task} exists) is
    that entity's nested collection.  Its collection operations are moved
    from the parent's action set to the child entity.  Ambiguous matches
    are left unchanged.
E7. A nested collection below an ancestor path parameter is a distinct
    resource when it has a POST and a direct item GET at collection/{key}.
    The parent parameter is retained in both templates. Other paths below
    its item remain actions unless they themselves satisfy this structural
    collection/item proof. A weak path prefix alone is not sufficient.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..parsing.model import Document, Operation, Provenance


@dataclass
class EntityCandidate:
    key: str                       # stable internal key, e.g. "books"
    display_name: str              # e.g. "Book"
    plural_display_name: str       # e.g. "Books"
    schema_name: Optional[str]     # component schema name, if any
    family_segment: str            # the leading static path segment, e.g. "books"
    collection_path: Optional[str] = None
    item_path: Optional[str] = None
    operations: List[Operation] = field(default_factory=list)
    action_operations: List[Operation] = field(default_factory=list)  # sub-actions under item path
    confidence: float = 1.0
    provenance: List[Provenance] = field(default_factory=list)


def _segments(path: str) -> List[str]:
    return [s for s in path.strip("/").split("/") if s != ""]


def _is_param(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def _schema_ref_name(schema: dict) -> Optional[str]:
    if not isinstance(schema, dict):
        return None
    # DRF-style pagination envelope: {count, next, previous, results: [...]}.
    # Checked FIRST, before the direct $ref check below, because the
    # envelope schema itself typically has its own component name (e.g.
    # NetBox's 'PaginatedDeviceList') that would otherwise be returned
    # immediately without ever inspecting its contents. Without unwrapping,
    # the wrapper's own name ends up used as the entity's display name
    # verbatim (confirmed: every NetBox entity was named 'Paginated<X>List'
    # instead of '<X>' when running the generated model against NetBox's
    # real mock SUT, which also produced near-identical STATE-tracker
    # description prefixes for different entities, causing the
    # reverse-deletion lifecycle to wait forever on an entity whose
    # completion event kept getting misattributed to a different,
    # textually-similar entity).
    props = schema.get("properties", {})
    results = props.get("results") if isinstance(props, dict) else None
    if isinstance(results, dict) and results.get("type") == "array":
        inner = _schema_ref_name(results)
        if inner:
            return inner
    ref = schema.get("__source_ref__")
    if ref and ref.startswith("#/components/schemas/"):
        return ref.rsplit("/", 1)[-1]
    # array of refs
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return _schema_ref_name(items) if isinstance(items, dict) else None
    return None


def _singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("ses") and len(word) > 3:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _display_from_segment(seg: str) -> str:
    words = re.split(r"[-_]", seg)
    singular = _singularize(words[-1]) if words else seg
    words = words[:-1] + [singular] if words else [singular]
    return "".join(w[:1].upper() + w[1:] for w in words if w)


def _family_key(path: str) -> str:
    """The static path prefix before the first path parameter, e.g.
    '/api/dcim/devices/{id}/napalm' -> 'api/dcim/devices'; '/books' ->
    'books'; '/loans/{userId}/{bookId}' -> 'loans'. This groups an
    operation family by its resource root regardless of how deeply the API
    is namespaced (fixes the 'group by first segment only' bug, which
    collapsed every '/api/...'-prefixed resource into a single family)."""
    segs = _segments(path)
    first_param = next((i for i, s in enumerate(segs) if _is_param(s)), len(segs))
    prefix = segs[:first_param] if first_param > 0 else segs[:1]
    return "/".join(prefix)


def _nested_resource_roots(doc: Document) -> set[str]:
    """Find proven nested collection roots using method and path evidence.

    This intentionally excludes a nested path that only happens to end in a
    noun: a POST on the collection and a GET on exactly one direct item
    template must both be declared in the OpenAPI. Ambiguous item templates
    are left in their legacy parent family.
    """
    methods: Dict[str, set[str]] = {}
    for op in doc.operations:
        methods.setdefault(op.path, set()).add(op.method)
    roots = set()
    for collection, declared in methods.items():
        segments = _segments(collection)
        if ("POST" not in declared or not segments or _is_param(segments[-1])
                or not any(_is_param(part) for part in segments)):
            continue
        item_paths = [item for item, item_methods in methods.items()
                      if "GET" in item_methods and len(_segments(item)) == len(segments) + 1
                      and _segments(item)[:-1] == segments and _is_param(_segments(item)[-1])]
        if len(item_paths) == 1:
            roots.add(collection.strip("/"))
    return roots


def infer_entities(doc: Document) -> List[EntityCandidate]:
    families: Dict[str, List[Operation]] = {}
    nested_roots = sorted(_nested_resource_roots(doc), key=lambda root: (-len(_segments(root)), root))
    for op in doc.operations:
        segs = _segments(op.path)
        if not segs:
            continue
        family = _family_key(op.path)
        # Match complete slash-delimited templates, never a textual prefix
        # such as /users accidentally matching /users2. Prefer the most
        # specific nested resource whose structural pair is documented.
        for root in nested_roots:
            if op.path.strip("/") == root or op.path.strip("/").startswith(root + "/"):
                family = root
                break
        families.setdefault(family, []).append(op)

    candidates: List[EntityCandidate] = []
    for family, ops in families.items():
        # Within a family, classify each path:
        #  - collection: no path parameters at all (the family root itself)
        #  - item: the family root plus a trailing run of path parameter(s)
        #    and nothing else (single or composite key)
        #  - action: a static segment appears *after* the trailing
        #    parameter run (a sub-action on an item, or a nested collection)
        item_ops, collection_ops, action_ops = [], [], []
        for o in ops:
            segs = _segments(o.path)
            if family in nested_roots:
                suffix = segs[len(_segments(family)):]
                if not suffix:
                    collection_ops.append(o)
                elif all(_is_param(s) for s in suffix):
                    item_ops.append(o)
                else:
                    action_ops.append(o)
                continue
            param_idxs = [i for i, s in enumerate(segs) if _is_param(s)]
            if not param_idxs:
                collection_ops.append(o)
            else:
                last_static_after_param = any(not _is_param(s) for s in segs[param_idxs[0]:])
                if last_static_after_param:
                    action_ops.append(o)
                else:
                    item_ops.append(o)

        is_entity = bool(item_ops)
        if not is_entity:
            continue  # standalone operation family, handled separately

        item_path = item_ops[0].path
        collection_path = collection_ops[0].path if collection_ops else None

        schema_name = None
        prov: List[Provenance] = []
        if family in nested_roots:
            prov.append(Provenance(
                pointer=collection_path, rule="E7:nested_collection_item_pair",
                detail=(f"POST {collection_path} and GET {item_path} establish a nested "
                        "resource boundary below an ancestor path parameter"),
            ))

        # Priority: response schemas (E3b, E3c) reflect the canonical "read"
        # representation of the entity (e.g. 'Book'), which is preferred
        # over the create-request variant (e.g. 'BookCreate') so display
        # names don't pick up a Create/Update suffix. The create body is
        # used only as a fallback when no response schema is documented.
        list_op = next((o for o in collection_ops if o.method == "GET"), None)
        if list_op:
            for r in list_op.success_responses:
                for mt, schema in r.media_types.items():
                    name = _schema_ref_name(schema)
                    if name:
                        schema_name = name
                        prov.append(Provenance(
                            pointer=r.pointer, rule="E3b:list_response_schema",
                            detail=f"List operation {list_op.method} {list_op.path} response {r.status} references {name}",
                        ))
                        break
                if schema_name:
                    break

        if not schema_name:
            get_item = next((o for o in item_ops if o.method == "GET"), None)
            if get_item:
                for r in get_item.success_responses:
                    for mt, schema in r.media_types.items():
                        name = _schema_ref_name(schema)
                        if name:
                            schema_name = name
                            prov.append(Provenance(
                                pointer=r.pointer, rule="E3c:item_response_schema",
                                detail=f"Item GET {get_item.path} response {r.status} references {name}",
                            ))
                            break
                    if schema_name:
                        break

        post_op = next((o for o in collection_ops if o.method == "POST"), None)
        if not schema_name and post_op and post_op.request_body and post_op.request_body.variants:
            for variant in post_op.request_body.variants:
                name = _schema_ref_name(variant.schema)
                if name:
                    schema_name = name
                    prov.append(Provenance(
                        pointer=variant.pointer, rule="E3a:create_request_body",
                        detail=f"Create operation {post_op.method} {post_op.path} request body references {name}",
                    ))
                    break

        if schema_name:
            canonical = _strip_variant_suffix(schema_name)
            if canonical != schema_name and canonical in doc.component_schemas:
                prov.append(Provenance(
                    pointer=f"#/components/schemas/{canonical}", rule="E3d:canonical_schema_name",
                    detail=f"'{schema_name}' normalized to sibling component schema '{canonical}'",
                ))
                schema_name = canonical

        last_segment = family.split("/")[-1] if family else family
        confidence = 1.0
        if not schema_name:
            confidence = 0.5
            prov.append(Provenance(
                pointer=item_path, rule="E4:derived_from_path_segment",
                detail=f"No component schema reference found; entity name derived from path segment '{last_segment}'",
            ))

        display = _display_from_segment(last_segment) if not schema_name else _entity_display_from_schema(schema_name)
        plural = last_segment[:1].upper() + last_segment[1:].replace("-", "_")

        candidates.append(EntityCandidate(
            key=family,
            display_name=display,
            plural_display_name=_pluralize_display(display),
            schema_name=schema_name,
            family_segment=last_segment,
            collection_path=collection_path,
            item_path=item_path,
            operations=collection_ops + item_ops,
            action_operations=action_ops,
            confidence=confidence,
            provenance=prov,
        ))
    _assign_nested_collections(candidates)
    return candidates


def _assign_nested_collections(candidates: List[EntityCandidate]) -> None:
    """Recognize collection endpoints nested below another resource item.

    This deliberately relies only on path structure and on entity families
    already established by E1/E2.  Requiring a unique child-family match
    avoids guessing when two inferred entities share the same trailing
    segment.  Only GET/POST are collection operations; deeper paths remain
    actions of their originally inferred owner.
    """
    by_segment: Dict[str, List[EntityCandidate]] = {}
    for entity in candidates:
        by_segment.setdefault(entity.family_segment, []).append(entity)

    owners_by_operation = {
        (op.method, op.path): owner
        for owner in candidates
        for op in owner.action_operations
    }

    for path in sorted({op.path for owner in candidates for op in owner.action_operations}):
        segs = _segments(path)
        if len(segs) < 3 or _is_param(segs[-1]):
            continue
        matches = by_segment.get(segs[-1], [])
        if len(matches) != 1:
            continue
        child = matches[0]
        if child.collection_path is not None or path == child.item_path:
            continue

        collection_ops = []
        for method in ("GET", "POST"):
            owner = owners_by_operation.get((method, path))
            if owner is None or owner.key == child.key:
                continue
            operation = next(
                (op for op in owner.action_operations
                 if op.method == method and op.path == path),
                None,
            )
            if operation is not None:
                collection_ops.append((owner, operation))

        if not collection_ops:
            continue

        child.collection_path = path
        for owner, operation in collection_ops:
            owner.action_operations.remove(operation)
            child.operations.append(operation)
        child.provenance.append(Provenance(
            pointer=path,
            rule="E6:nested_collection_path",
            detail=(f"Path '{path}' ends in the unique inferred entity family "
                    f"'{child.family_segment}' and is assigned as its nested collection"),
        ))


_VARIANT_SUFFIXES = ("Create", "Update", "Input", "Payload", "Request", "New", "Patch")


def _strip_variant_suffix(schema_name: str) -> str:
    for suf in _VARIANT_SUFFIXES:
        if schema_name.endswith(suf) and len(schema_name) > len(suf):
            return schema_name[: -len(suf)]
    return schema_name


def _entity_display_from_schema(schema_name: str) -> str:
    # Display name strips Create/Update/... variant suffixes for readability
    # even when no sibling base schema exists (e.g. only 'DrugCreate' is
    # defined); the underlying schema_name used for data lookups is
    # unaffected unless a true sibling schema was found (see E3d above).
    return _strip_variant_suffix(schema_name)


def _pluralize_display(display: str) -> str:
    if display.endswith("y") and not display.endswith(("ay", "ey", "iy", "oy", "uy")):
        return display[:-1] + "ies"
    if display.endswith(("s", "x", "sh", "ch")):
        return display + "es"
    return display + "s"


def standalone_operations(doc: Document, entities: List[EntityCandidate]) -> List[Operation]:
    """Operations that belong to no entity family's CRUD/action set at all:
    top-level action endpoints such as POST /dispense or POST /process-rx."""
    covered_paths = set()
    for e in entities:
        for o in e.operations + e.action_operations:
            covered_paths.add((o.method, o.path))
    return [o for o in doc.operations if (o.method, o.path) not in covered_paths]
