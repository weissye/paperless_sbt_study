"""Evidence-bearing resource views, operation slots and relationship templates.

This additive analysis does not alter legacy scheduling or invent runtime facts.
"""
from __future__ import annotations

import re
from collections import defaultdict


def pointer(value):
    return value.replace('~', '~0').replace('/', '~1')


def ref_name(node):
    ref = node.get('$ref', '') if isinstance(node, dict) else ''
    prefix = '#/components/schemas/'
    return ref[len(prefix):].replace('~1', '/').replace('~0', '~') if ref.startswith(prefix) else None


def token(value):
    value = re.sub(r'([a-z])([A-Z])', r'\1_\2', value).lower()
    value = re.sub(r'[^a-z0-9]', '', value)
    return value[:-3] + 'y' if value.endswith('ies') else value[:-1] if value.endswith('s') else value


def wire_types(node, schemas, seen=()):
    name = ref_name(node)
    if name:
        if name in seen:
            return []
        return wire_types(schemas.get(name, {}), schemas, seen + (name,))
    result = []
    if node.get('type'):
        result.append({'type': node['type'], 'format': node.get('format')})
    for branch in ('anyOf', 'oneOf', 'allOf'):
        for child in node.get(branch, []):
            result.extend(wire_types(child, schemas, seen))
    return [{'type': kind, 'format': fmt} for kind, fmt in
            sorted({(x['type'], x['format']) for x in result}, key=str)]


def components(node, schemas, seen=()):
    """Unwrap only an array or a pagination envelope, never arbitrary children."""
    name = ref_name(node)
    if name:
        if name in seen:
            return []
        target = schemas.get(name, {})
        if 'id' in target.get('properties', {}) or 'slug' in target.get('properties', {}):
            return [name]
        children = components(target, schemas, seen + (name,))
        return children or [name]
    if node.get('type') == 'array':
        return components(node.get('items', {}), schemas, seen)
    props = node.get('properties', {})
    arrays = [v for v in props.values() if isinstance(v, dict) and v.get('type') == 'array']
    scalars = [v for v in props.values() if isinstance(v, dict) and v.get('type') in ('integer', 'number')]
    if len(arrays) == 1 and scalars:
        return components(arrays[0], schemas, seen)
    return []


def schema_cycles(schemas):
    """Keep recursive schema components as SCCs, not creation prerequisites."""
    adjacency = {name: set() for name in schemas}
    def collect(node, output):
        if isinstance(node, dict):
            name = ref_name(node)
            if name in schemas:
                output.add(name)
            for key, value in node.items():
                if key not in ('example', 'examples', 'default', 'enum', 'const'):
                    collect(value, output)
        elif isinstance(node, list):
            for value in node:
                collect(value, output)
    for name, node in schemas.items():
        collect(node, adjacency[name])
    index = {}; low = {}; stack = []; active = set(); cycles = []
    def visit(name):
        index[name] = low[name] = len(index); stack.append(name); active.add(name)
        for child in sorted(adjacency[name]):
            if child not in index:
                visit(child); low[name] = min(low[name], low[child])
            elif child in active:
                low[name] = min(low[name], index[child])
        if low[name] == index[name]:
            members = []
            while True:
                child = stack.pop(); active.remove(child); members.append(child)
                if child == name:
                    break
            if len(members) > 1 or name in adjacency[name]:
                cycles.append(sorted(members))
    for name in sorted(schemas):
        if name not in index:
            visit(name)
    return sorted(cycles)


def build_resource_maps(raw, plan):
    schemas = raw.get('components', {}).get('schemas', {})
    entities = {ep.entity.key: ep for ep in plan.entities}
    owners = defaultdict(set); views = defaultdict(set); operation_owner = {}
    ambiguities = []
    for key, ep in entities.items():
        for op_plan in ep.ops:
            op = op_plan.op
            operation_owner[(op.path, op.method.lower())] = key
            original = raw.get('paths', {}).get(op.path, {}).get(op.method.lower(), {})
            nodes = []
            if op_plan.kind in ('get', 'list', 'create', 'update'):
                for status, response in original.get('responses', {}).items():
                    if str(status).isdigit() and 200 <= int(status) < 300:
                        nodes.extend(x.get('schema', {}) for x in response.get('content', {}).values())
                if op_plan.kind in ('create', 'update'):
                    nodes.extend(x.get('schema', {}) for x in original.get('requestBody', {}).get('content', {}).values())
            for node in nodes:
                for name in components(node, schemas):
                    owners[name].add(key); views[key].add(name)

    # Merge an alternate lookup view only with shared schema and path-family proof.
    canonical = {key: key for key in entities}
    merges = []
    for left in sorted(entities, key=lambda k: (len(k), k)):
        if canonical[left] != left:
            continue
        for right in sorted(entities):
            if left == right or canonical[right] != right or (len(left), left) >= (len(right), right):
                continue
            same_family = token(left.rsplit('/', 1)[-1]) == token(right.rsplit('/', 1)[-1])
            lookup_view = right.startswith(left + '/') and len(right.split('/')) == len(left.split('/')) + 1
            common = views[left] & views[right]
            identity_views = [n for n in common if 'id' in schemas.get(n, {}).get('properties', {})]
            if identity_views and (same_family or lookup_view):
                canonical[right] = canonical[left]
                merges.append({'alias': right, 'canonical': canonical[left], 'schemas': sorted(identity_views),
                               'rule': 'shared_identity_schema_and_path_family'})
    for name in owners:
        owners[name] = {canonical[key] for key in owners[name]}
    endpoint_evidence = {name: set(values) for name, values in owners.items()}
    for name, values in sorted(endpoint_evidence.items()):
        if len(values) > 1:
            ambiguities.append({'kind': 'shared_schema_multiple_resource_owners', 'schema': name,
                                'candidates': sorted(values)})

    # Input/output views with the same declared title are candidates. Adopt a
    # business type only when endpoint evidence gives one unambiguous owner.
    titles = defaultdict(list)
    for name, schema in schemas.items():
        if schema.get('title'):
            titles[schema['title']].append(name)
    for title, names in titles.items():
        candidates = set().union(*(owners[name] for name in names))
        if len(candidates) == 1:
            for name in names:
                owners[name] |= candidates
        elif len(candidates) > 1:
            ambiguities.append({'kind': 'schema_owner', 'title': title, 'candidates': sorted(candidates)})

    def schema_type(name):
        candidates = owners[name]
        if len(candidates) == 1:
            return next(iter(candidates))
        title = schemas.get(name, {}).get('title')
        names = titles.get(title, [])
        bases = {re.sub(r'-(Input|Output)$', '', n) for n in names}
        if title and len(names) > 1 and len(bases) == 1:
            return 'schema:' + next(iter(bases))
        return 'schema:' + name

    resources = {}
    for key, ep in entities.items():
        root = canonical[key]
        entry = resources.setdefault(root, {'type': root, 'kind': 'endpoint_resource', 'path_views': [],
                                            'schema_views': [], 'identity_slots': []})
        entry['path_views'].append({'entity': key, 'collection': ep.entity.collection_path, 'item': ep.entity.item_path})
    for name, schema in schemas.items():
        kind = schema_type(name)
        if kind not in resources:
            resources[kind] = {'type': kind, 'kind': 'schema_component', 'path_views': [], 'schema_views': [], 'identity_slots': []}
        resources[kind]['schema_views'].append(name)
        resources[kind].setdefault('schema_view_evidence', []).append({'schema': name,
            'pointer': '#/components/schemas/' + pointer(name), 'declared_title': schema.get('title'),
            'rule': 'endpoint_schema' if kind in endpoint_evidence.get(name, set()) else
                    'unambiguous_declared_title_view' if resources[kind]['kind'] == 'endpoint_resource' else
                    'declared_title_and_input_output_base_name' if kind != 'schema:' + name else 'unassigned_schema_component'})
        for field, definition in schema.get('properties', {}).items():
            if field.lower() in ('id', 'slug'):
                resources[kind]['identity_slots'].append({'schema': name, 'field': field,
                    'wire_types': wire_types(definition, schemas), 'role': 'identifier_view',
                    'pointer': '#/components/schemas/' + pointer(name) + '/properties/' + pointer(field)})

    slots = []; relations = []; operation_rows = []; seen_relations = set()
    def relationship(source, target, path, location, required, many, rule, operation=None, candidates=None):
        signature = (source, target, path, location, operation, rule)
        if signature in seen_relations:
            return
        seen_relations.add(signature)
        relations.append({'source': source, 'target': target, 'field_path': path, 'pointer': location,
            'required_in_this_context': required, 'many': many, 'rule': rule,
            'operation': operation, 'candidates': candidates or [], 'runtime_fact': False,
            'execution_role': 'unclassified' if candidates else 'relationship_template'})

    def walk(node, source, path, location, required=False, many=False, seen=(), operation=None):
        if not isinstance(node, dict):
            return
        name = ref_name(node)
        if name:
            target = schema_type(name)
            if path:
                relationship(source, target, path, location, required, many, 'explicit_schema_reference', operation)
                if resources[target]['kind'] == 'endpoint_resource':
                    return
            if name in seen:
                return
            walk(schemas.get(name, {}), source, path, '#/components/schemas/' + pointer(name),
                 required, many, seen + (name,), operation)
            return
        for composition in ('anyOf', 'oneOf', 'allOf'):
            branches = node.get(composition, [])
            for i, branch in enumerate(branches):
                walk(branch, source, path, location + '/' + composition + '/' + str(i),
                     required and composition == 'allOf', many, seen, operation)
        if 'items' in node:
            walk(node['items'], source, path + '[]', location + '/items', required, True, seen, operation)
        props = node.get('properties', {})
        for field, child in props.items():
            child_path = path + '.' + field if path else field
            child_location = location + '/properties/' + pointer(field)
            normalized = re.sub(r'([a-z])([A-Z])', r'\1_\2', field).lower()
            is_identifier = normalized.endswith('_id') or normalized.endswith('_ids') or normalized in ('id', 'slug')
            if is_identifier:
                stem = re.sub(r'_ids?$', '', normalized)
                candidates = sorted({canonical[k] for k in entities if token(k.rsplit('/', 1)[-1]) == token(stem)})
                target = source if normalized in ('id', 'slug') and not path else candidates[0] if normalized not in ('id', 'slug') and len(candidates) == 1 else None
                slots.append({'source': source, 'field_path': child_path, 'business_type': target,
                              'wire_types': wire_types(child, schemas), 'pointer': child_location,
                              'operation': operation, 'candidate_types': candidates,
                              'evidence': 'owner_identity' if normalized in ('id', 'slug') and not path else 'nested_identity_unresolved' if normalized in ('id', 'slug') else 'unique_resource_name_candidate'})
                if normalized not in ('id', 'slug') and (target or candidates):
                    relationship(source, target, child_path, child_location,
                                 required and field in node.get('required', []), many,
                                 'identifier_name_candidate', operation, candidates)
            walk(child, source, child_path, child_location,
                 required and field in node.get('required', []), many, seen, operation)

    for name, schema in sorted(schemas.items()):
        walk(schema, schema_type(name), '', '#/components/schemas/' + pointer(name), True, seen=(name,))
    for path, item in sorted(raw.get('paths', {}).items()):
        for method, op in sorted(item.items()):
            if method.lower() not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options') or not isinstance(op, dict):
                continue
            identity = method.upper() + ' ' + path
            owner = canonical.get(operation_owner.get((path, method.lower())))
            row = {'operation': identity, 'operation_id': op.get('operationId'), 'resource_type': owner,
                   'request_schemas': [], 'response_schemas': [], 'path_slots': []}
            for param in item.get('parameters', []) + op.get('parameters', []):
                if param.get('in') == 'path':
                    stem = re.sub(r'_?id$', '', re.sub(r'([a-z])([A-Z])', r'\1_\2', param['name']).lower())
                    candidates = sorted({canonical[k] for k in entities if token(k.rsplit('/', 1)[-1]) == token(stem)})
                    linked = sorted({r['target'] for r in relations if r['source'] == owner and
                                     r['operation'] is None and r['rule'] == 'explicit_schema_reference' and
                                     r['target'] in candidates})
                    contextual_candidates = linked if len(candidates) > 1 and len(linked) == 1 else candidates
                    owning_views = [ep for ep in entities.values() if canonical[ep.entity.key] == owner and ep.entity.item_path and
                                    (path == ep.entity.item_path or path.startswith(ep.entity.item_path + '/')) and
                                    ('{' + param['name'] + '}') in ep.entity.item_path]
                    slot_type = owner if owning_views else contextual_candidates[0] if len(contextual_candidates) == 1 else None
                    row['path_slots'].append({'name': param['name'], 'wire_types': wire_types(param.get('schema', {}), schemas),
                        'business_type': slot_type, 'candidate_types': candidates,
                        'evidence': 'owning_item_path' if owning_views else 'identifier_name_and_response_relation_candidate' if contextual_candidates != candidates else 'identifier_name_candidate',
                        'binding_status': 'requires_identity_evidence'})
            for media, body in op.get('requestBody', {}).get('content', {}).items():
                node = body.get('schema', {}); row['request_schemas'].extend(components(node, schemas))
                walk(node, owner or 'operation:' + identity, '', '#/paths/' + pointer(path) + '/' + method + '/requestBody/content/' + pointer(media) + '/schema',
                     bool(op.get('requestBody', {}).get('required')), operation=identity)
            for status, response in op.get('responses', {}).items():
                if str(status).isdigit() and 200 <= int(status) < 300:
                    for body in response.get('content', {}).values():
                        row['response_schemas'].extend(components(body.get('schema', {}), schemas))
            operation_rows.append(row)

    return {'resource_catalog': {'version': 1, 'resources': [resources[k] for k in sorted(resources)],
            'entity_aliases': merges, 'identity_slots': slots, 'ambiguities': ambiguities,
            'instance_bindings': [], 'policy': 'Wire UUID equality never merges business types or instances.'},
        'operation_map': {'version': 1, 'operations': operation_rows},
        'relationship_map': {'version': 1, 'templates': sorted(relations, key=lambda r: str((r['source'], r['field_path'], r['target'], r['operation'], r['pointer']))),
            'schema_cycles': schema_cycles(schemas), 'runtime_edges': [],
            'cycle_policy': 'Preserve graph cycles. Create instances first; bind optional links later. Required create cycles require an observed bootstrap or remain blocked.',
            'planning_status': 'analysis_only; legacy execution dependencies unchanged'}}
