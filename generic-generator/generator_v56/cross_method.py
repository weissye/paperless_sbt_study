"""OpenAPI-derived cross-method concurrency opportunities and proof gaps.

Discovery does not promote a candidate to an executable oracle: a matching
endpoint shape cannot by itself prove state effects or seed valid references.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .parsing.model import Document, Operation
from .verification import (_create_for_item, _op_id, _properties, _variant,
                           _observable_fields, _codes)


def _parent(path: str) -> str:
    parts = path.rstrip('/').split('/')
    return '/'.join(parts[:-1]) or '/'


def _array_keys(op: Operation) -> Dict[str, str]:
    media, schema = _variant(op, 'application/json')
    if media != 'application/json':
        return {}
    return {name: str(spec.get('items', {}).get('type', ''))
            for name, spec in _properties(schema).items()
            if spec.get('type') == 'array' and isinstance(spec.get('items'), dict)
            and spec['items'].get('type') in ('string', 'integer')}


def discover(doc: Document) -> List[Dict[str, Any]]:
    ops = {(o.path, o.method): o for o in doc.operations if not o.deprecated}
    candidates: List[Dict[str, Any]] = []
    for (path, method), left in sorted(ops.items()):
        if method not in ('PATCH', 'PUT'):
            continue
        right = ops.get((path, 'DELETE'))
        if right is None:
            continue
        parent = _parent(path)
        is_relation = not path.rsplit('/', 1)[-1].startswith('{')
        observation = ops.get((parent if is_relation else path, 'GET'))
        create, binding = _create_for_item(doc, observation) if observation else (None, None)
        if is_relation:
            arrays = {k: v for k, v in _array_keys(left).items()
                      if _array_keys(right).get(k) == v}
            for key in sorted(arrays):
                # Request-shape equality is a hypothesis about a relation.
                # Membership still needs a documented independent read.
                reason = ('no-parent-get' if not observation else
                          'no-parent-create-binding' if not (create and binding) else
                          'independent-membership-read-and-two-real-member-ids-needed')
                candidates.append({'candidate_id': 'cross-method::put-delete::' + _op_id(left) +
                                   '::' + _op_id(right) + '::' + key,
                                   'family': 'relation-put-delete', 'methods': ['PUT', 'DELETE'],
                                   'operation_ids': [_op_id(left), _op_id(right)],
                                   'path_template': path, 'parent_path_template': parent,
                                   'body_array_key': key, 'member_id_type': arrays[key],
                                   'observation_operation_id': _op_id(observation) if observation else None,
                                   'parent_create_operation_id': _op_id(create) if create else None,
                                   'parent_binding': binding,
                                   'runtime_ready': False, 'limitation': reason,
                                   'source_pointers': [left.pointer, right.pointer] +
                                       ([observation.pointer] if observation else [])})
        else:
            reason = ('no-item-get' if not observation else
                      'no-create-to-item-binding' if not (create and binding) else
                      'three-isolated-created-items-and-two-serial-absence-controls-needed')
            candidates.append({'candidate_id': 'cross-method::update-delete::' + _op_id(left) +
                               '::' + _op_id(right),
                               'family': 'update-delete', 'methods': [method, 'DELETE'],
                               'operation_ids': [_op_id(left), _op_id(right)],
                               'path_template': path,
                               'observation_operation_id': _op_id(observation) if observation else None,
                               'create_operation_id': _op_id(create) if create else None,
                               'create_binding': binding,
                               'runtime_ready': False, 'limitation': reason,
                               'source_pointers': [left.pointer, right.pointer] +
                                   ([observation.pointer] if observation else [])})
    return candidates


def empirical_update_delete(doc: Document, *, allow_put: bool = False,
                            selected_operation: str | None = None) -> List[Dict[str, Any]]:
    """Executable hypotheses only when three distinct creator results are available.

    Neither the delete effect nor an undocumented GET 404 is presumed true.
    Both orders of the serial control must establish absence empirically.
    """
    ops = {(o.path, o.method): o for o in doc.operations if not o.deprecated}
    result = []
    for candidate in discover(doc):
        if (candidate['family'] != 'update-delete' or
                candidate['methods'][0] not in (('PATCH', 'PUT') if allow_put else ('PATCH',)) or
                not candidate['create_binding'] or
                (selected_operation and candidate['operation_ids'][0] != selected_operation)):
            continue
        path = candidate['path_template']
        update = ops[(path, candidate['methods'][0])]
        delete = ops[(path, 'DELETE')]
        get = ops.get((path, 'GET'))
        if (get is None or not _codes(update, True) or not _codes(delete, True)
                or (delete.request_body and delete.request_body.required)):
            continue
        fields = [f for f in _observable_fields(update, get, 'application/json')
                  if f['type'] in ('string', 'boolean', 'integer', 'number')
                  and f.get('format') not in ('uuid', 'uri', 'url')]
        if not fields:
            continue
        field = fields[0]
        # PUT needs a complete request, reconstructed from a successful item
        # read. Do not invent an undocumented fixture for a missing property.
        request_fields = list(_properties(_variant(update, 'application/json')[1]))
        if update.method == 'PUT':
            observed = set()
            for response in get.success_responses:
                for schema in response.media_types.values():
                    observed.update(_properties(schema))
            if not request_fields or not set(request_fields).issubset(observed):
                continue
        result.append({'oracle_id': candidate['candidate_id'],
                       'kind': 'empirical-update-delete',
                       'operation_id': candidate['operation_ids'][0],
                       'method': update.method, 'methods': [update.method, 'DELETE'],
                       'path_template': path, 'fields': [field],
                       'media_type': field['media_type'], 'width': 2,
                       'request_fields': request_fields if update.method == 'PUT' else [],
                       'success_statuses': _codes(update, True),
                       'delete_success_statuses': _codes(delete, True),
                       'observation': {'method': 'GET', 'path_template': get.path,
                                       'success_statuses': _codes(get, True)},
                       'runtime': {'ready': True, 'create_operation_id': candidate['create_operation_id'],
                                   'create_source_pointer': next(o.pointer for o in doc.operations
                                       if _op_id(o) == candidate['create_operation_id']),
                                   'path_binding_from_create_response': candidate['create_binding']['response'],
                                   'path_binding_from_create_request_path': candidate['create_binding']['request_path'],
                                   'entity_key': _parent(path),
                                   'required_isolated_created_resources': 3,
                                   'limitation': None},
                       'execution': 'three-distinct-created-resources-two-serial-controls-one-barrier-epoch',
                       'source_pointers': candidate['source_pointers']})
    return result
