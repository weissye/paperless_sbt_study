"""Opt-in executable scenarios composed from OpenAPI-derived item oracles.

This module uses only the verified create-to-item binding and readable, writable
fields already established by verification.py.  Runtime controls still decide
whether any generated scenario is admissible.
"""
from __future__ import annotations

from copy import deepcopy


def compose(oracles, max_cross_pairs=2):
    ready = [o for o in oracles if o.get('runtime', {}).get('ready') and
             o.get('kind') == 'same-field-one-successful-value-visible' and
             o.get('width') == 2]
    result = []
    by_operation = {}
    by_entity = {}
    for oracle in ready:
        by_operation.setdefault(oracle['operation_id'], []).append(oracle)
        # An identity or foreign-key rewrite may invalidate the concrete GET
        # path or prerequisites mid-experiment. Keep these as ordinary
        # same-field candidates; require an explicitly rebindable resource for
        # composed cross-resource histories.
        field_name = oracle['fields'][0]['name'].lower()
        if not (field_name == 'id' or field_name.endswith('id')):
            by_entity.setdefault(oracle['runtime']['entity_key'], []).append(oracle)
    for operation, siblings in sorted(by_operation.items()):
        safe = [oracle for oracle in siblings if not (
            oracle['fields'][0]['name'].lower() == 'id' or
            oracle['fields'][0]['name'].lower().endswith('id'))]
        if not safe:
            continue
        first = safe[0]
        noop = deepcopy(first)
        noop['kind'] = 'noop-versus-change'
        noop['oracle_id'] = 'concurrency::noop::' + first['oracle_id']
        noop['execution'] = 'baseline-read-then-noop-control-then-change-control-then-barrier'
        result.append(noop)
        if first['method'] == 'PUT' and len(safe) >= 2:
            left, right = safe[:2]
            put = deepcopy(first)
            put['kind'] = 'disjoint-put-serial-outcomes'
            put['oracle_id'] = 'concurrency::disjoint-put::' + operation
            put['fields'] = [left['fields'][0], right['fields'][0]]
            put['reverse_sequential_control'] = True
            put['execution'] = 'both-serial-orders-and-barrier-with-read-derived-complete-put-bodies'
            result.append(put)
    entities = sorted(by_entity)
    for i, left in enumerate(entities):
        for right in entities[i + 1:]:
            a, b = by_entity[left][0], by_entity[right][0]
            if a['path_template'] == b['path_template']:
                continue
            result.append({
                'kind': 'cross-entity-independent-writes',
                'oracle_id': 'concurrency::cross-entity::' + a['operation_id'] + '::' + b['operation_id'],
                'operation_id': a['operation_id'], 'method': a['method'],
                'path_template': a['path_template'], 'width': 2,
                'fields': [a['fields'][0], b['fields'][0]],
                'targets': [deepcopy(a), deepcopy(b)],
                'success_statuses': a['success_statuses'], 'observation': a['observation'],
                'runtime': {'ready': True, 'entity_key': left,
                            'create_operation_id': a['runtime']['create_operation_id'],
                            'path_binding_from_create_response': a['runtime']['path_binding_from_create_response']},
                'source_pointers': a['source_pointers'] + b['source_pointers'],
                'execution': 'two-distinct-readable-resources-with-two-serial-controls',
            })
            if sum(o['kind'] == 'cross-entity-independent-writes' for o in result) >= max_cross_pairs:
                return result
    return result
