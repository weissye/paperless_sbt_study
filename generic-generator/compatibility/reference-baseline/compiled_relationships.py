"""Compile typed relationship tasks through the existing Provengo REST boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import re

from ..inference.values import generate_value
from .relationship_runtime_js import CODE, SHARED_CODE, EXPANDED_CODE


def compile_relationships(plan, maps, raw, runtime):
    if not isinstance(runtime, dict) or set(runtime) - {'bootstrap', 'actions', 'write_defaults', 'contract_sha256', 'response_bindings', 'scope_checks', 'relationship_identity_views', 'relationship_write_views', 'compact_callbacks', 'shared_target_updates', 'detached_target_deletions', 'attached_target_deletions', 'interleave_mutations', 'mutate_during_construction', 'create_defaults', 'semantic_program'}:
        raise ValueError('Invalid relationship runtime configuration.')
    if 'semantic_program' in runtime and not runtime['semantic_program']:
        raise ValueError('semantic_program must be a nonempty explicit policy.')
    if 'compact_callbacks' in runtime and type(runtime['compact_callbacks']) is not bool:
        raise ValueError('compact_callbacks must be a boolean.')
    if 'interleave_mutations' in runtime and type(runtime['interleave_mutations']) is not bool:
        raise ValueError('interleave_mutations must be a boolean.')
    if 'mutate_during_construction' in runtime and type(runtime['mutate_during_construction']) is not bool:
        raise ValueError('mutate_during_construction must be a boolean.')
    embedded_checks = any(isinstance(r, dict) and r.get('verify_embedded_value') for r in runtime.get('shared_target_updates', []) or [])
    callback_code = EXPANDED_CODE if embedded_checks or runtime.get('detached_target_deletions') else (SHARED_CODE if runtime.get('shared_target_updates') else CODE)
    if runtime.get('attached_target_deletions'):
        from .relationship_runtime_js import ATTACHED_CODE
        callback_code = ATTACHED_CODE
    if runtime.get('semantic_program'):
        if any(runtime.get(k) for k in ('shared_target_updates','detached_target_deletions','attached_target_deletions')):
            raise ValueError('Semantic programs require a separate runtime profile from deletion/update programs.')
        from .semantic_runtime_js import SEMANTIC_CODE
        callback_code = SEMANTIC_CODE
        if runtime['semantic_program'].get('require_merge_collision'):
            from .semantic_runtime_js import COLLISION_CODE
            callback_code = COLLISION_CODE
    blueprint = copy.deepcopy(maps['relationship_scenario_plan'])
    schemas = raw.get('components', {}).get('schemas', {})
    aliases = {a['alias']: a['canonical'] for a in maps['resource_catalog']['entity_aliases']}
    canonical = lambda k: aliases.get(k, k)
    entities = {}
    for ep in plan.entities:
        key = canonical(ep.entity.key)
        if key not in entities or (ep.create_op and not entities[key].create_op):
            entities[key] = ep
    operations = {op.op.method + ' ' + op.op.path: op for ep in plan.entities for op in ep.ops}
    document_ops = {op.method + ' ' + op.path: op for op in plan.doc.operations}

    def operation_raw(identity):
        method, path = identity.split(' ', 1)
        if identity not in document_ops:
            raise ValueError('Runtime operation is outside the contract: ' + identity)
        return raw['paths'][path][method.lower()]

    def root(node):
        seen = set()
        while '$ref' in node:
            name = node['$ref'].split('/')[-1].replace('~1', '/').replace('~0', '~')
            if name in seen or name not in schemas:
                raise ValueError('Unsupported schema reference: ' + name)
            seen.add(name); node = schemas[name]
        return node

    def request_schema(identity):
        content = operation_raw(identity).get('requestBody', {}).get('content', {})
        if not content:
            return None
        if 'application/json' not in content:
            raise ValueError('Relationship writes require a documented JSON request body: ' + identity)
        return content['application/json']['schema']

    def response_schema(identity):
        for code, response in sorted(operation_raw(identity).get('responses', {}).items()):
            if code.isdigit() and 200 <= int(code) < 300 and 'application/json' in response.get('content', {}):
                return response['content']['application/json']['schema']
        raise ValueError('Relationship reads require a documented JSON success response: ' + identity)

    def property_schema(node, path, writable=False):
        for segment in path.split('.'):
            node = root(node)
            branches = node.get('anyOf', node.get('oneOf', []))
            if branches:
                nonnull = [root(b) for b in branches if root(b).get('type') != 'null']
                if len(nonnull) != 1:
                    raise ValueError('Ambiguous identity view schema: ' + path)
                node = nonnull[0]
            name = segment.removesuffix('[]')
            node = node.get('properties', {}).get(name)
            if node is None or (writable and node.get('readOnly')):
                raise ValueError('Undocumented or unwritable identity view: ' + path)
            if segment.endswith('[]'):
                node = root(node).get('items', {})
        return root(node)

    def embedded_string_view(node, path):
        # Nullable input/output alternatives may share the same readable label.
        nodes = [node]
        def alternatives(node):
            node = root(node)
            branches = node.get('anyOf', node.get('oneOf'))
            if branches:
                return [v for branch in branches for v in alternatives(branch) if v.get('type') != 'null']
            return [node]
        for segment in path.split('.'):
            next_nodes = []
            for node in nodes:
                for branch in alternatives(node):
                    child = branch.get('properties', {}).get(segment.removesuffix('[]'))
                    if child is None:
                        raise ValueError('Embedded value path is not documented in every nonnull view: ' + path)
                    if segment.endswith('[]'):
                        child = root(child).get('items', {})
                    next_nodes.append(child)
            nodes = next_nodes
        return bool(nodes) and all(view.get('type') == 'string' for node in nodes for view in alternatives(node))

    identity_views = runtime.get('relationship_identity_views', [])
    if not isinstance(identity_views, list):
        raise ValueError('Relationship identity views must be a list.')
    for view in identity_views:
        if not isinstance(view, dict) or set(view) != {'operation', 'field_path', 'write_path', 'target_field', 'readback_path'}:
            raise ValueError('Identity view requires explicit operation, relationship and identity paths.')
        if not all(isinstance(v, str) and v for v in view.values()):
            raise ValueError('Identity view paths must be nonempty strings.')
        matching = [t for t in blueprint['tasks'] if t['kind'] == 'link' and t['operation'] == view['operation'] and t['field_path'] == view['field_path']]
        if not matching:
            raise ValueError('Identity view does not match a selected relationship task.')
        if any(rule.get('path') == view['write_path'] for rule in runtime.get('write_defaults', {}).get(view['operation'], [])):
            raise ValueError('Identity view conflicts with a configured write default.')
        for task in matching:
            if len(task['target_instances']) != 1 or '[]' in view['write_path'] or '[]' in view['readback_path']:
                raise ValueError('Scalar identity views require exactly one target.')
            target_ep = entities[task['target_instances'][0].rsplit('#', 1)[0]]
            source_ep = entities[task['source_instance'].rsplit('#', 1)[0]]
            getter = source_ep.get_op.op.method + ' ' + source_ep.get_op.op.path
            target_getter = target_ep.get_op.op.method + ' ' + target_ep.get_op.op.path
            target = property_schema(response_schema(target_getter), view['target_field'])
            write = property_schema(request_schema(view['operation']), view['write_path'], True)
            readback = property_schema(response_schema(getter), view['readback_path'])
            for node in (write, readback):
                branches = node.get('anyOf', node.get('oneOf', [node]))
                if not any(root(b).get('type') == target.get('type') and root(b).get('format') == target.get('format') for b in branches):
                    raise ValueError('Identity view has incompatible wire types.')
            if target.get('type') not in ('string', 'integer', 'number'):
                raise ValueError('Identity view target must be scalar.')
    if len({(v['operation'], v['field_path'], v['write_path']) for v in identity_views}) != len(identity_views):
        raise ValueError('Duplicate relationship identity view.')

    write_views = runtime.get('relationship_write_views', [])
    if not isinstance(write_views, list):
        raise ValueError('Relationship write views must be a list.')
    for view in write_views:
        required = {'operation', 'field_path', 'write_path', 'readback_path', 'target_field', 'item_identity_field', 'item_defaults', 'evidence_sha256'}
        if not isinstance(view, dict) or set(view) != required or not isinstance(view['item_defaults'], dict):
            raise ValueError('Collection write view requires complete explicit configuration.')
        if not isinstance(view['evidence_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', view['evidence_sha256']):
            raise ValueError('Collection write view requires external shape evidence.')
        if not all(isinstance(view[k], str) and view[k] for k in required - {'item_defaults'}):
            raise ValueError('Collection write view paths must be strings.')
        if not re.fullmatch(r'[^.\[\]]+\[\]', view['write_path']):
            raise ValueError('Collection write view requires a top-level array path.')
        matches = [t for t in blueprint['tasks'] if t['kind'] == 'link' and t['operation'] == view['operation'] and t['field_path'] == view['field_path']]
        if not matches:
            raise ValueError('Collection write view does not match a selected relationship.')
        for task in matches:
            source_ep = entities[task['source_instance'].rsplit('#', 1)[0]]
            getter = source_ep.get_op.op.method + ' ' + source_ep.get_op.op.path
            item = property_schema(request_schema(view['operation']), view['write_path'], True)
            branches = [root(b) for b in item.get('anyOf', item.get('oneOf', [item]))]
            readback = property_schema(response_schema(getter), view['readback_path'])
            for target_instance in task['target_instances']:
                target_ep = entities[target_instance.rsplit('#', 1)[0]]
                target = property_schema(response_schema(target_ep.get_op.op.method + ' ' + target_ep.get_op.op.path), view['target_field'])
                alternatives = [root(b) for b in target.get('anyOf', target.get('oneOf', [target])) if root(b).get('type') != 'null']
                if len(alternatives) != 1:
                    raise ValueError('Collection write view target identity is ambiguous.')
                target = alternatives[0]
                fields = [b.get('properties', {}).get(view['item_identity_field'], {}) for b in branches] + [readback]
                if target.get('type') not in ('string', 'integer', 'number') or any(root(f).get('type') != target.get('type') or root(f).get('format') != target.get('format') for f in fields):
                    raise ValueError('Collection write view has incompatible identity types.')
            if view['item_identity_field'] in view['item_defaults'] or not any(set(b.get('required', [])) <= set(view['item_defaults']) | {view['item_identity_field']} for b in branches):
                raise ValueError('Collection write view cannot construct a documented item.')
            if any(not any(k in b.get('properties', {}) for b in branches) for k in view['item_defaults']):
                raise ValueError('Collection write view default is outside the contract.')
    if len({(v['operation'], v['field_path']) for v in write_views}) != len(write_views):
        raise ValueError('Duplicate collection write view.')

    def fields(ep, instance):
        if not ep.get_op or not ep.create_op:
            raise ValueError('A selected resource needs create and item GET: ' + ep.entity.key)
        props = root(response_schema(ep.get_op.op.method + ' ' + ep.get_op.op.path)).get('properties', {})
        result = []
        for parameter in ep.get_op.op.path_params:
            normalized = re.sub(r'[^a-z0-9]', '', parameter.name.lower())
            field = parameter.name if parameter.name in props else 'id' if normalized.endswith('id') and 'id' in props else 'slug' if normalized.endswith('slug') and 'slug' in props else None
            if field is None:
                raise ValueError('Route identity lacks response-schema evidence: ' + parameter.name)
            result.append({'parameter': parameter.name, 'response_field': field,
                           'variable': 'rel_route_' + hashlib.sha256((instance + ':' + parameter.name).encode()).hexdigest()[:16]})
        create_response = root(response_schema(ep.create_op.op.method + ' ' + ep.create_op.op.path))
        if create_response.get('type') in ('string', 'integer', 'number'):
            if len(result) != 1 or root(props[result[0]['response_field']]).get('type') != create_response['type']:
                raise ValueError('Scalar creation response cannot bind this route unambiguously.')
        elif any(f['response_field'] not in create_response.get('properties', {}) for f in result):
            operation = ep.create_op.op.method + ' ' + ep.create_op.op.path
            binding = runtime.get('response_bindings', {}).get(operation, {})
            if binding.get('array_field'):
                array = create_response.get('properties', {}).get(binding['array_field'], {})
                item_props = root(array.get('items', {})).get('properties', {})
                if array.get('type') != 'array' or any(f['response_field'] not in item_props for f in result):
                    raise ValueError('Configured response array cannot supply this identity.')
            elif not create_response and re.fullmatch('[0-9a-f]{64}', binding.get('evidence_sha256', '')):
                pass
            else:
                raise ValueError('Creation response lacks an item-route identity; an observed response binding is required: ' + operation)
        return result

    info = {}
    for key, instances in blueprint['instances'].items():
        ep = entities[key]
        for instance in instances:
            prefix = 'rel_' + hashlib.sha256(instance.encode()).hexdigest()[:16]
            response_props = root(response_schema(ep.get_op.op.method + ' ' + ep.get_op.op.path)).get('properties', {})
            info[instance] = {'instance': instance, 'resource': key, 'route_fields': fields(ep, instance),
                              'record_variable': prefix + '_identity', 'snapshot_variable': prefix + '_snapshot',
                              'identity_fields': [f for f in ('id', 'slug') if f in response_props]}

    bootstrap = runtime.get('bootstrap', [])
    if not bootstrap:
        raise ValueError('A documented bootstrap GET is required for runtime body preparation.')
    bootstrap_contexts = []
    for index, entry in enumerate(bootstrap):
        if set(entry) != {'operation', 'fields'} or not entry['operation'].startswith('GET ') or not isinstance(entry['fields'], list):
            raise ValueError('Bootstrap entries require a GET operation and selected fields.')
        op = document_ops[entry['operation']]
        if op.path_params:
            raise ValueError('Bootstrap operations cannot need unbound path identities.')
        props = root(response_schema(entry['operation'])).get('properties', {})
        if any(field not in props for field in entry['fields']):
            raise ValueError('Bootstrap field is outside its response schema.')
        bootstrap_contexts.append({'mode': 'bootstrap', 'operation': entry['operation'],
            'fields': entry['fields'], 'variable': 'rel_bootstrap_' + str(index),
            'codes': [int(r.status) for r in op.success_responses]})

    checks = runtime.get('scope_checks', [])
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'left', 'right'}:
            raise ValueError('Scope checks require two bootstrap field references.')
        for side in ('left', 'right'):
            reference = check[side]
            if not isinstance(reference, list) or len(reference) != 2:
                raise ValueError('A scope field reference is [bootstrap index, field].')
            index, field = reference
            if not isinstance(index, int) or index < 0 or index >= len(bootstrap) or field not in bootstrap[index]['fields']:
                raise ValueError('Scope check references an undeclared bootstrap field.')
    bootstrap_contexts[-1]['scope_checks'] = checks

    # OAuth password authentication is inferred from the declared security flow.
    flows = [s.get('flows', {}).get('password') for s in raw.get('components', {}).get('securitySchemes', {}).values()]
    flows = [f for f in flows if f]
    urls = sorted({f['tokenUrl'] for f in flows})
    if len(urls) != 1 or not urls[0].startswith('/'):
        raise ValueError('One local documented OAuth password token URL is required.')
    auth_identity = 'POST ' + urls[0]
    auth_schema = root(response_schema(auth_identity))
    if auth_schema and 'access_token' not in auth_schema.get('properties', {}):
        raise ValueError('OAuth token response does not document access_token.')
    auth_op = operation_raw(auth_identity)
    form = auth_op.get('requestBody', {}).get('content', {}).get('application/x-www-form-urlencoded', {}).get('schema')
    if not form or not {'username', 'password'}.issubset(root(form).get('properties', {})):
        raise ValueError('OAuth password request fields are not documented.')

    contexts = []; functions = []
    def add_request(identity, context, instance=None, body_variable=None, route_override=None):
        op = document_ops[identity]; method, path = identity.split(' ', 1)
        # Probe responses are captured before the unchanged-state GET, even
        # when the server accepts an invalid cycle or returns a server error.
        codes = list(range(200, 600)) if context.get('mode') == 'reject_link' else context.get('absence_codes', [int(r.status) for r in op.success_responses])
        context = dict(context, operation=identity, codes=codes)
        route = {f['parameter']: '@{' + f['variable'] + '}' for f in info[instance]['route_fields']} if instance else {}
        route.update(route_override or {})
        for param in op.path_params:
            if param.name not in route:
                raise ValueError('Unbound HTTP path parameter: ' + identity + ' ' + param.name)
            path = path.replace('{' + param.name + '}', route[param.name])
        function = 'sbtRelHttp_' + str(len(functions) + 1)
        options = {'headers': {'Authorization': 'Bearer @{sbt_rel_token}'}}
        if body_variable:
            options['headers']['Content-Type'] = 'application/json'
            options['body'] = '@{' + body_variable + '}'
        rendered = json.dumps(options, separators=(',', ':'))[:-1] + ',expectedResponseCodes:' + json.dumps(context['codes']) + ',callback:sbtRelCallback(' + json.dumps(context, separators=(',', ':')) + ')}'
        functions.append('function ' + function + '(){svc.' + method.lower() + '(' + json.dumps(path) + ',' + rendered + ');}')
        contexts.append(context)
        return function + '();'

    interface_steps = {}
    by_task = {t['id']: t for t in blueprint['tasks']}
    for task in blueprint['tasks']:
        instance = task.get('instance') or task['source_instance']; meta = info[instance]
        ep = entities[meta['resource']]
        getter = ep.get_op.op.method + ' ' + ep.get_op.op.path
        body_variable = 'rel_body_' + hashlib.sha256(task['id'].encode()).hexdigest()[:16]
        if task['kind'] == 'create':
            schema = request_schema(task['operation']); props = root(schema).get('properties', {})
            names = set(root(schema).get('required', [])) | ({'name'} if 'name' in props else set())
            seed_body = {field: generate_value(root(props[field]), plan.seed, instance + '.' + field) for field in sorted(names) if not props[field].get('readOnly')}
            create_defaults = runtime.get('create_defaults', {})
            if not isinstance(create_defaults, dict):
                raise ValueError('create_defaults must map operations to documented fields.')
            for operation, values in create_defaults.items():
                if operation not in operations or not operation.startswith('POST ') or not isinstance(values, dict):
                    raise ValueError('Invalid creation default operation.')
                documented = root(request_schema(operation)).get('properties', {})
                if any(field not in documented or documented[field].get('readOnly') for field in values):
                    raise ValueError('Undocumented creation default field.')
            seed_body.update(copy.deepcopy(create_defaults.get(task['operation'], {})))
            parents = []
            for edge in ep.dependencies:
                key = canonical(edge.target)
                if key not in blueprint['instances']:
                    raise ValueError('Creation parent is outside the selected scope: ' + key)
                parent = next((by_task[p]['instance'] for p in task['after'] if p in by_task and by_task[p].get('resource') == key), None)
                if parent is None:
                    raise ValueError('Creation parent task is not bound.')
                parent_ep = entities[key]
                parent_props = root(response_schema(parent_ep.get_op.op.method + ' ' + parent_ep.get_op.op.path)).get('properties', {})
                field = 'id' if 'id' in parent_props else info[parent]['route_fields'][0]['response_field']
                parents.append({'snapshot': info[parent]['snapshot_variable'], 'field': field, 'body_field': edge.field_name})
            steps = [add_request(bootstrap[0]['operation'], {'mode': 'prepare_create', 'request_schema': schema,
                'seed_body': seed_body, 'parents': parents, 'body_variable': body_variable}),
                add_request(task['operation'], dict(meta, mode='capture', response_schema=response_schema(task['operation']),
                    capture_array=runtime.get('response_bindings', {}).get(task['operation'], {}).get('array_field')),
                            instance, body_variable), add_request(getter, dict(meta, mode='snapshot', task_id=task['id']), instance)]
        else:
            negative = task['kind'] == 'negative_link'
            unlink = task['kind'] == 'unlink'
            if unlink:
                leaf = root(property_schema(request_schema(task['operation']), task['field_path'], writable=True))
                if not (leaf.get('nullable') or any(root(b).get('type') == 'null' for b in leaf.get('anyOf', []) + leaf.get('oneOf', []))):
                    raise ValueError('Relationship removal requires a documented nullable field.')
            if negative and (not re.fullmatch('[0-9a-f]{64}', task.get('evidence_sha256', '')) or
                    not task.get('rejection_codes') or any(type(code) is not int or not 400 <= code < 500 for code in task['rejection_codes'])):
                raise ValueError('Negative relationship task requires qualified rejection evidence.')
            defaults = runtime.get('write_defaults', {}).get(task['operation'], [])
            views = [v for v in identity_views if v['operation'] == task['operation'] and v['field_path'] == task['field_path']]
            binding = next((v for v in write_views if v['operation'] == task['operation'] and v['field_path'] == task['field_path']), None)
            if negative and binding:
                raise ValueError('A negative cycle probe cannot substitute its relationship representation.')
            task['configured_write_view'] = binding
            expectation_variable = body_variable + '_expected'
            all_members = negative and task.get('verify_cycle_members', False)
            members = task.get('cycle_path', [])[:-1] if all_members else []
            before_steps = []
            after_steps = []
            for member_index, member in enumerate(members):
                member_meta = info[member]
                member_ep = entities[member_meta['resource']]
                member_get = member_ep.get_op.op.method + ' ' + member_ep.get_op.op.path
                before_steps.append(add_request(member_get, dict(member_meta, mode='cycle_member_before',
                    expectation_variable=expectation_variable, member_index=member_index), member))
                after_steps.append(add_request(member_get, dict(member_meta, mode='cycle_member_after',
                    expectation_variable=expectation_variable, member_index=member_index,
                    probe_task_id=task['id'], cycle_members=task['cycle_path'],
                    task_id=task['id'] if member_index == len(members)-1 else None), member))
            steps = [add_request(getter, {'mode': 'prepare_link', 'request_schema': request_schema(task['operation']),
                'targets': [info[t]['snapshot_variable'] for t in task['target_instances']],
                'field_path': task['field_path'], 'defaults': defaults, 'identity_views': views,
                'write_view': binding,
                'rejection_probe': negative, 'unlink': unlink,
                'cycle_snapshots': [info[t]['snapshot_variable'] for t in task.get('cycle_path', [])],
                'verify_cycle_members': all_members,
                'body_variable': body_variable, 'expectation_variable': expectation_variable}, instance),
                add_request(task['operation'], {'mode': 'reject_link', 'rejection_codes': task['rejection_codes'],
                    'expectation_variable': expectation_variable} if negative else {'mode': 'write'}, instance, body_variable),
                add_request(getter, dict(meta, mode='verify_rejection' if negative else 'verify_link', field_path=binding['readback_path'] if binding else task['field_path'],
                    expectation_variable=expectation_variable, identity_views=views, task_id=None if all_members else task['id'],
                    probe_task_id=task['id'], verify_cycle_members=all_members,
                    legal_readback=bool(task.get('legal_readback')), exact_empty=unlink,
                    rejection_codes=task.get('rejection_codes', []), cycle_length=len(task.get('cycle_path', []))), instance)]
            steps = before_steps + steps + after_steps
            if task.get('legal_readback') and not negative:
                # Fresh target GETs establish resolvable identities without mutation.
                for target in task['target_instances']:
                    target_meta = info[target]
                    target_ep = entities[target_meta['resource']]
                    target_get = target_ep.get_op.op.method + ' ' + target_ep.get_op.op.path
                    steps.append(add_request(target_get, dict(target_meta, mode='legal_target',
                        legal_task_id=task['id']), target))
        interface_steps[task['id']] = steps

    qualified = runtime.get('actions', [])
    for index, action in enumerate(qualified):
        required = {'operation', 'source_type', 'target_type', 'target_parameter', 'target_field', 'readback_path', 'body', 'evidence_sha256'}
        if set(action) != required or not re.fullmatch('[0-9a-f]{64}', action['evidence_sha256']):
            raise ValueError('Qualified relationship action requires complete external evidence configuration.')
        if action['source_type'] not in blueprint['instances'] or action['target_type'] not in blueprint['instances']:
            raise ValueError('Qualified action type is outside the selected scope.')
        matching = [a for a in blueprint['action_candidates'] if a['operation'] == action['operation'] and a['source_type'] == action['source_type'] and a['target_type'] == action['target_type'] and a['path_slot'] == action['target_parameter']]
        if len(matching) != 1 or not action['operation'].startswith('POST '):
            raise ValueError('Qualified action is not a contract-derived relationship candidate.')
        for i, source in enumerate(blueprint['instances'][action['source_type']]):
            for target in (blueprint['instances'][action['target_type']][i], blueprint['instances'][action['target_type']][(i + 1) % len(blueprint['instances'][action['target_type']])]):
                task_id = 'action:' + str(index + 1) + ':' + str(i + 1) + ':' + target
                dependencies = ['create:' + source, 'create:' + target]
                dependencies += [t['id'] for t in blueprint['tasks'] if t['kind'] == 'link' and not t.get('lifecycle_phase') and t['source_instance'] == target]
                task = {'id': task_id, 'kind': 'qualified_action', 'source_instance': source,
                    'target_instances': [target], 'operation': action['operation'], 'after': dependencies,
                    'evidence_sha256': action['evidence_sha256'], 'executable': True}
                meta = info[source]; getter_ep = entities[action['source_type']]
                getter = getter_ep.get_op.op.method + ' ' + getter_ep.get_op.op.path
                body_var = 'rel_action_' + hashlib.sha256(task_id.encode()).hexdigest()[:16]
                steps = [add_request(getter, {'mode': 'prepare_action', 'target_snapshot': info[target]['snapshot_variable'],
                    'target_field': action['target_field'], 'target_variable': body_var + '_target',
                    'body_variable': body_var, 'seed_body': action['body'], 'request_schema': request_schema(action['operation']), 'expectation_variable': body_var + '_expected'}, source),
                    add_request(action['operation'], {'mode': 'write'}, source, body_var,
                                {action['target_parameter']: '@{' + body_var + '_target}'}),
                    add_request(getter, dict(meta, mode='verify_link', field_path=action['readback_path'],
                        expectation_variable=body_var + '_expected', task_id=task_id), source)]
                blueprint['tasks'].append(task); interface_steps[task_id] = steps

    for task in blueprint['tasks']:
        if task.get('lifecycle_phase') and task['kind'] == 'unlink':
            task['after'] += [t['id'] for t in blueprint['tasks'] if t['kind'] == 'qualified_action']

    shared_updates = runtime.get('shared_target_updates', [])
    if not isinstance(shared_updates, list):
        raise ValueError('shared_target_updates must be a list.')
    shared_keys = set()
    shared_prefix = [t['id'] for t in blueprint['tasks']]
    for index, rule in enumerate(shared_updates):
        if not isinstance(rule, dict) or set(rule) - {'resource_type', 'operation', 'field', 'value', 'verify_embedded_value'} or not {'resource_type', 'operation', 'field', 'value'}.issubset(rule):
            raise ValueError('Shared update requires resource_type, operation, field and value.')
        if 'verify_embedded_value' in rule and type(rule['verify_embedded_value']) is not bool:
            raise ValueError('verify_embedded_value must be a boolean.')
        resource = rule['resource_type']; operation = rule['operation']; field = rule['field']
        if not isinstance(resource, str) or resource not in blueprint['instances'] or not isinstance(field, str) or '.' in field or field in {'id', 'slug'}:
            raise ValueError('Shared update requires a selected resource and a non-identity scalar field.')
        ep = entities[resource]
        if not isinstance(operation, str) or not operation.startswith(('PUT ', 'PATCH ')) or operation not in [o.op.method + ' ' + o.op.path for o in ep.ops]:
            raise ValueError('Shared update operation must belong to its resource.')
        if (resource, field) in shared_keys:
            raise ValueError('Duplicate shared update rule.')
        if any(field == route['response_field'] for instance in blueprint['instances'][resource] for route in info[instance]['route_fields']):
            raise ValueError('Shared update cannot change a route identity field.')
        shared_keys.add((resource, field))
        writable = root(property_schema(request_schema(operation), field, writable=True))
        getter = ep.get_op.op.method + ' ' + ep.get_op.op.path
        readable = root(property_schema(response_schema(getter), field, writable=False))
        if writable.get('type') != 'string' or readable.get('type') != 'string' or not isinstance(rule['value'], str) or not rule['value']:
            raise ValueError('Shared update currently requires a documented string field and value.')
        selected = []
        for target in blueprint['instances'][resource]:
            references = {}
            for link in blueprint['tasks']:
                if link['kind'] != 'link' or link.get('lifecycle_phase') or target not in link['target_instances']:
                    continue
                source = link['source_instance']
                if info[source]['resource'] == resource:
                    continue
                view = link.get('configured_write_view')
                path = view['readback_path'] if view else link['field_path']
                identity_view = next((v for v in identity_views if v['operation'] == link['operation'] and v['field_path'] == link['field_path']), None)
                if identity_view:
                    path = identity_view['readback_path']
                reference = {'instance': source, 'field_path': path}
                if rule.get('verify_embedded_value'):
                    source_ep = entities[info[source]['resource']]
                    source_get = source_ep.get_op.op.method + ' ' + source_ep.get_op.op.path
                    if not embedded_string_view(response_schema(source_get), link['field_path'] + '.' + field):
                        raise ValueError('Embedded update check requires a documented string view.')
                    reference.update(object_path=link['field_path'], value_field=field)
                references[(source, path)] = reference
            if len({source for source, path in references}) < 2:
                continue
            selected.append(target)
            task_id = 'shared-update:' + str(index + 1) + ':' + target
            task = {'id': task_id, 'kind': 'shared_update', 'source_instance': target,
                    'target_instances': [], 'operation': operation, 'field': field,
                    'value': rule['value'], 'referrers': list(references.values()),
                    'after': list(shared_prefix) if runtime.get('interleave_mutations') else [t['id'] for t in blueprint['tasks']], 'executable': True}
            if runtime.get('mutate_during_construction'):
                sources = {r['instance'] for r in task['referrers']}
                task['after'] = [t['id'] for t in blueprint['tasks']
                    if (t['kind'] == 'create' and t['instance'] in sources | {target})
                    or (t['kind'] == 'link' and not t.get('lifecycle_phase') and target in t['target_instances'])]
            meta = info[target]; variable = 'rel_shared_' + hashlib.sha256(task_id.encode()).hexdigest()[:16]
            steps = []
            for reference_index, reference in enumerate(task['referrers']):
                source = reference['instance']; source_ep = entities[info[source]['resource']]
                source_get = source_ep.get_op.op.method + ' ' + source_ep.get_op.op.path
                steps.append(add_request(source_get, dict(info[source], mode='shared_before',
                    field_path=reference['field_path'], target_snapshot=meta['snapshot_variable'],
                    expectation_variable=variable, reference_index=reference_index), source))
            steps += [add_request(getter, dict(meta, mode='prepare_shared_update', field=field,
                         value=rule['value'], request_schema=request_schema(operation),
                         body_variable=variable, expectation_variable=variable), target),
                      add_request(operation, {'mode': 'write'}, target, variable),
                      add_request(getter, dict(meta, mode='shared_updated', field=field,
                         expectation_variable=variable), target)]
            for reference_index, reference in enumerate(task['referrers']):
                source = reference['instance']; source_ep = entities[info[source]['resource']]
                source_get = source_ep.get_op.op.method + ' ' + source_ep.get_op.op.path
                steps.append(add_request(source_get, dict(info[source], mode='shared_after',
                    field_path=reference['field_path'], expectation_variable=variable,
                    **({key: reference[key] for key in ('object_path', 'value_field')} if rule.get('verify_embedded_value') else {}),
                    reference_index=reference_index, reference_count=len(task['referrers']),
                    shared_task_id=task_id,
                    task_id=task_id if reference_index == len(task['referrers']) - 1 else None), source))
            blueprint['tasks'].append(task); interface_steps[task_id] = steps
        if not selected:
            raise ValueError('Shared update has no target with two distinct referrers: ' + resource)

    from .relationship_deletion import append_detached_deletions
    deletion_tasks = append_detached_deletions(blueprint, info, entities, runtime, add_request, request_schema, property_schema, root)
    interface_steps.update(deletion_tasks)
    semantic_tasks = {}
    if runtime.get('semantic_program'):
        from .semantic_campaign import append_semantic_program
        semantic_tasks = append_semantic_program(blueprint, info, entities, runtime['semantic_program'],
            add_request, request_schema, response_schema, root, document_ops)
        interface_steps.update(semantic_tasks)

    if runtime.get('mutate_during_construction'):
        mutation_ids = [t['id'] for t in blueprint['tasks'] if t['kind'] in ('shared_update', 'detached_delete', 'attached_delete')]
        late_actions = [t for t in blueprint['tasks'] if t['kind'] == 'qualified_action']
        if not mutation_ids or not late_actions:
            raise ValueError('Construction interleaving requires mutations and later construction actions.')
        for task in late_actions:
            task['after'] = list(dict.fromkeys(task['after'] + mutation_ids))

    # Each actor retains its own order. The coordinator admits one complete task
    # at a time while choosing among ready actors; no HTTP requests overlap.
    owners = {}
    for task in blueprint['tasks']:
        owner = task.get('instance') or task['source_instance']
        previous = owners.setdefault(owner, [])
        if previous:
            task['after'].append(previous[-1])
        task['after'] = sorted(set(task['after'])); previous.append(task['id']); task['executable'] = True
    completed = set()
    while len(completed) < len(blueprint['tasks']):
        ready = [t['id'] for t in blueprint['tasks'] if t['id'] not in completed and set(t['after']).issubset(completed)]
        if not ready:
            raise ValueError('Relationship task dependencies contain a required creation/execution cycle.')
        completed.update(ready)
    blueprint.update(status='COMPILED_NOT_LIVE_ACCEPTED', blockers=[], instance_metadata=info,
                     compiled_task_count=len(blueprint['tasks']), rollback_implemented=False, reset_replay_accepted=False)

    oauth_codes = [int(r.status) for r in document_ops[auth_identity].success_responses]
    auth_ctx = {'mode': 'auth', 'operation': auth_identity, 'codes': oauth_codes,
                'identity_records': sorted(meta['record_variable'] for meta in info.values())}
    auth_options = '{headers:{"Content-Type":"application/x-www-form-urlencoded"},body:"grant_type=password&username=@{encodeURIComponent(getEnv(\'SBT_REL_USERNAME\'))}&password=@{encodeURIComponent(getEnv(\'SBT_REL_PASSWORD\'))}",expectedResponseCodes:' + json.dumps(oauth_codes) + ',callback:sbtRelCallback(' + json.dumps(auth_ctx) + ')}'
    functions.insert(0, 'function sbtRelAuthenticate(){svc.post(' + json.dumps(urls[0]) + ',' + auth_options + ');}')
    bootstrap_calls = ['sbtRelAuthenticate();'] + [add_request(c['operation'], c) for c in bootstrap_contexts]
    finish_context = {'mode': 'finish', 'expected_tasks': [t['id'] for t in blueprint['tasks']],
        'expected_instances': len(info), 'expected_responses': len(contexts) + 2,
        'expected_negative_tasks': [t['id'] for t in blueprint['tasks'] if t['kind'] == 'negative_link'],
        'expected_legal_tasks': [t['id'] for t in blueprint['tasks'] if t.get('legal_readback') and t['kind'] != 'negative_link']}
    if shared_updates:
        finish_context['expected_shared_tasks'] = [t['id'] for t in blueprint['tasks'] if t['kind'] == 'shared_update']
    if deletion_tasks:
        finish_context['expected_deletion_tasks'] = list(deletion_tasks)
    if semantic_tasks:
        finish_context['expected_semantic_tasks'] = list(semantic_tasks)
    finish_call = add_request(bootstrap[0]['operation'], finish_context)
    factory = '''
function sbtRelCallback(ctx){var selected={};function collect(node){if(!node||typeof node!=="object")return;if(node.$ref){var n=node.$ref.split('/').pop().replace(/~1/g,'/').replace(/~0/g,'~');if(!selected[n]&&sbtRelSchemas[n]){selected[n]=sbtRelSchemas[n];collect(selected[n]);}}Object.keys(node).forEach(function(k){if(['example','examples','default','enum','const'].indexOf(k)<0)collect(node[k]);});}collect(ctx);return new Function("response","("+sbtRelRuntime.toString()+")(response,"+JSON.stringify(ctx)+",{},"+JSON.stringify(selected)+");");}
'''
    if runtime.get('compact_callbacks'):
        # Preserve a self-contained callback while storing schemas/runtime once.
        # Native sampling serializes functions, so closures/global references are unsafe.
        factory = r'''
function sbtRelCallback(ctx){
var contextJson=JSON.stringify(JSON.stringify(ctx));
var invocation="var code='function(response,contextJson,schemaJson,pvg){return ('+pvg.rtv.get('sbt_rel_runtime_code')+')(response,JSON.parse(contextJson),{},JSON.parse(schemaJson));}';"+
"var fn;if(typeof Packages!=='undefined'){var cx=Packages.org.mozilla.javascript.Context.getCurrentContext();fn=cx.compileFunction(cx.initStandardObjects(),code,'relationship-runtime',1,null);}else{fn=eval('('+code+')');}"+
"fn(response,"+contextJson+",pvg.rtv.get('sbt_rel_schema_registry'),pvg);";
var setup=ctx.mode==="auth"?"pvg.rtv.set('sbt_rel_runtime_code',"+JSON.stringify(sbtRelRuntime.toString())+");pvg.rtv.set('sbt_rel_schema_registry',"+JSON.stringify(JSON.stringify(sbtRelSchemas))+");":"";
var hydrate="if(typeof Packages!=='undefined'){Packages.org.mozilla.javascript.Context.getCurrentContext().initStandardObjects(Packages.org.mozilla.javascript.ScriptableObject.getTopLevelScope(this));}";
var source=hydrate+setup+invocation;
if(typeof Packages!=="undefined"){
// Keep the sampled callback detached; hydrate standard builtins only during live execution.
// Shadow arguments to avoid Rhino creating its builtin Arguments object before hydration.
var scope=new Packages.org.mozilla.javascript.NativeObject();
(new Packages.org.mozilla.javascript.ClassCache()).associate(scope);
return Packages.org.mozilla.javascript.Context.getCurrentContext().compileFunction(scope,"function(response,arguments){"+source+"}","generated-relationship-callback",1,null);
}
return new Function("response",source);}


'''
    interfaces = '\n// Compiled relationship interfaces: all HTTP and callbacks remain here.\nconst sbtRelSchemas=' + json.dumps(schemas, separators=(',', ':')) + ';\n' + callback_code + factory + '\n'.join(functions)
    dependencies = {t['id']: t['after'] for t in blueprint['tasks']}
    stories = ['// @provengo summon rest\n// @provengo summon rtv\n// Generated from OpenAPI relationship maps. One HTTP request at a time.',
        'bthread("relationship-bootstrap",function(){' + ''.join(bootstrap_calls) + 'sync({request:Event("SBT:RelBootstrapDone")});});',
        'bthread("relationship-coordinator",function(){var complete={},active=null,boot=false;var deps=' + json.dumps(dependencies) + ';var total=' + str(len(dependencies)) + ';var count=0;while(count<total){var event=sync({waitFor:EventSet("relationship-progress",function(e){return ["SBT:RelBootstrapDone","SBT:RelTask","SBT:RelTaskDone"].indexOf(e.name)>=0;}),block:EventSet("relationship-not-ready",function(e){if(e.name!=="SBT:RelTask")return false;if(!boot||active!==null)return true;return !(deps[e.data.id]||[]).every(function(id){return complete[id];});})});if(event.name==="SBT:RelBootstrapDone")boot=true;else if(event.name==="SBT:RelTask")active=event.data.id;else{if(active!==event.data.id)throw new Error("Task completion without ownership");complete[event.data.id]=true;active=null;count++;}}' + finish_call + 'sync({request:Event("SBT:RelScenarioComplete",{tasks:total})});});']
    for owner, task_ids in owners.items():
        body = ['sync({waitFor:Event("SBT:RelBootstrapDone")});']
        for task_id in task_ids:
            data = json.dumps({'id': task_id, 'owner': owner}, separators=(',', ':'))
            body += ['sync({request:Event("SBT:RelTask",' + data + ')});'] + interface_steps[task_id] + ['sync({request:Event("SBT:RelTaskDone",' + data + ')});']
        stories.append('bthread(' + json.dumps('relationship:' + owner) + ',function(){' + ''.join(body) + '});')
    report = {'status': 'COMPILED_NOT_LIVE_ACCEPTED', 'active_operations': sorted({c['operation'] for c in contexts} | {auth_identity}),
        'task_count': len(blueprint['tasks']), 'symbolic_actor_count': len(owners),
        'http_requests_per_complete_schedule': len(contexts) + 1, 'bootstrap_selected_fields_only': True,
        'qualified_actions': len(qualified), 'live_accepted': False, 'full_json_schema_validator': False,
        'configured_identity_views': identity_views, 'identity_view_semantics': 'EXPLICIT_CONFIGURATION_PENDING_LIVE_VERIFICATION',
        'negative_task_count': sum(t['kind'] == 'negative_link' for t in blueprint['tasks']),
        'configured_write_views': write_views,
        'write_view_semantics': 'EXPLICIT_ASSOCIATION_CONFIGURATION_PENDING_NATIVE_WRITE_VERIFICATION',
        'negative_task_policy': 'qualified status rejection plus full source snapshot equality after GET'}
    if any(t.get('legal_readback') for t in blueprint['tasks']):
        report['legal_readback_tasks'] = [t['id'] for t in blueprint['tasks'] if t.get('legal_readback') and t['kind'] != 'negative_link']
        report['graph_lifecycle_tasks'] = [t['id'] for t in blueprint['tasks'] if t.get('lifecycle_phase')]
    member_tasks = [task for task in blueprint['tasks'] if task.get('verify_cycle_members')]
    if member_tasks:
        report['cycle_member_verification_tasks'] = [task['id'] for task in member_tasks]
        report['additional_cycle_member_gets'] = sum(2 * (len(task['cycle_path']) - 1) for task in member_tasks)
        report['negative_task_policy'] = 'qualified status rejection; source equality and opt-in full cycle member equality using fresh before/after GETs'
    if runtime.get('mutate_during_construction'):
        report['mutate_during_construction'] = True
    if runtime.get('attached_target_deletions'):
        report['attached_deletion_policy'] = 'EXPLICIT_REMOVE_REFERENCES_ON_SUCCESS_PENDING_LIVE_VERIFICATION'
    if semantic_tasks:
        report['semantic_family'] = runtime['semantic_program']['family']
        report['semantic_policy'] = 'EXPLICIT_CONFIGURATION_PENDING_LIVE_VERIFICATION'
    return interfaces, '\n'.join(stories) + '\n', blueprint, report, contexts
