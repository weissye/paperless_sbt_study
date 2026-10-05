"""Compile a reviewable instance/link plan from maps and generic scope config.

This intermediate plan deliberately refuses to advertise live executability
before response projection, bootstrap and readback bindings are validated.
"""
from __future__ import annotations
import re


def build_relationship_blueprint(plan, maps, profile):
    allowed = {'resource_types', 'instances_per_type', 'recursive_relationships', 'excluded_relationships', 'target_bindings'}
    if not isinstance(profile, dict) or set(profile) - allowed:
        raise ValueError('Unsupported relationship profile field.')
    catalog = maps['resource_catalog']
    resources = {r['type']: r for r in catalog['resources'] if r['kind'] == 'endpoint_resource'}
    selected = profile.get('resource_types', sorted(resources))
    count = profile.get('instances_per_type', 3)
    if not isinstance(selected, list) or not selected or any(not isinstance(k, str) or k not in resources for k in selected):
        raise ValueError('Relationship scope must contain known canonical endpoint resource types.')
    if type(count) is not int or not 2 <= count <= 8:
        raise ValueError('Relationship instance count must be an integer between 2 and 8.')
    selected = sorted(set(selected))
    policies = profile.get('recursive_relationships', [])
    if not isinstance(policies, list):
        raise ValueError('Recursive relationship policies must be a list.')
    policy_by_path = {}
    for policy in policies:
        required = {'source_type', 'field_path', 'rejection_codes', 'evidence_sha256'}
        if not isinstance(policy, dict) or not required.issubset(policy) or set(policy) - required - {'cycle_lengths', 'verify_cycle_members', 'legal_lifecycle', 'alternate_paths'}:
            raise ValueError('Recursive rejection policy requires explicit relationship and evidence.')
        if not all(isinstance(policy[k], str) for k in ('source_type', 'field_path')):
            raise ValueError('Recursive relationship type and path must be strings.')
        signature = (policy['source_type'], policy['field_path'])
        codes = policy['rejection_codes']
        if signature[0] not in selected or not isinstance(signature[1], str) or not signature[1] or signature in policy_by_path:
            raise ValueError('Unknown or duplicate recursive relationship policy.')
        if not isinstance(codes, list) or not codes or any(type(c) is not int or not 400 <= c < 500 for c in codes):
            raise ValueError('Recursive rejection codes must be explicit client error codes.')
        if not isinstance(policy['evidence_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', policy['evidence_sha256']):
            raise ValueError('Recursive rejection requires observed external evidence.')
        if 'legal_lifecycle' in policy and type(policy['legal_lifecycle']) is not bool:
            raise ValueError('legal_lifecycle must be a boolean.')
        if 'alternate_paths' in policy and type(policy['alternate_paths']) is not bool:
            raise ValueError('alternate_paths must be a boolean.')
        if policy.get('alternate_paths') and (not policy.get('legal_lifecycle') or count < 4):
            raise ValueError('Alternate paths require legal lifecycle and at least four instances.')
        lengths = policy.get('cycle_lengths', [2])
        if 'verify_cycle_members' in policy and type(policy['verify_cycle_members']) is not bool:
            raise ValueError('verify_cycle_members must be a boolean.')
        if not isinstance(lengths, list) or not lengths or any(type(n) is not int or not 2 <= n <= count for n in lengths) or len(set(lengths)) != len(lengths):
            raise ValueError('Cycle lengths must be distinct integers within the instance count.')
        policy_by_path[signature] = policy
    aliases = {a['alias']: a['canonical'] for a in catalog['entity_aliases']}
    canonical = lambda key: aliases.get(key, key)
    by_type = {}
    for ep in plan.entities:
        key = canonical(ep.entity.key)
        if key not in by_type or (ep.create_op and not by_type[key].create_op):
            by_type[key] = ep
    instances = {}; tasks = []; blockers = []
    for key in selected:
        ep = by_type[key]
        instances[key] = [key + '#' + str(i + 1) for i in range(count)]
        if not ep.create_op:
            blockers.append({'resource': key, 'reason': 'no_create_operation'})
        for identity in instances[key]:
            tasks.append({'id': 'create:' + identity, 'kind': 'create', 'instance': identity,
                'resource': key, 'operation': (ep.create_op.op.method + ' ' + ep.create_op.op.path) if ep.create_op else None,
                'after': [], 'binding': 'capture_documented_response_identity', 'executable': False})
    # Retain legacy creation prerequisites rather than deriving prerequisites
    # from read-only object references or recursive response schemas.
    for key in selected:
        ep = by_type[key]
        for edge in ep.dependencies:
            parent = canonical(edge.target)
            if parent not in instances:
                blockers.append({'resource': key, 'field': edge.field_name,
                                 'reason': 'parent_outside_scope', 'parent': parent})
                continue
            for i, identity in enumerate(instances[key]):
                task = next(t for t in tasks if t['id'] == 'create:' + identity)
                task['after'].append('create:' + instances[parent][i % count])

    operation_kinds = {op.op.method + ' ' + op.op.path: op.kind for ep in plan.entities for op in ep.ops}
    choices = {}
    for relation in maps['relationship_map']['templates']:
        operation = relation['operation']
        source, target = relation['source'], relation['target']
        if source not in instances or target not in instances or not operation:
            continue
        if relation['rule'] != 'explicit_schema_reference' or operation_kinds.get(operation) != 'update':
            continue
        # A field in a PUT/PATCH body is writable evidence. The nested object
        # projection and alternate union branches still require validation.
        field = relation['field_path']
        signature = (source, target, field)
        previous = choices.get(signature)
        if previous is None or (operation.startswith('PUT '), operation) > (previous['operation'].startswith('PUT '), previous['operation']):
            choices[signature] = relation
    matched_policies = set()
    excluded = profile.get('excluded_relationships', [])
    if not isinstance(excluded, list) or any(not isinstance(e, dict) or set(e) != {'source_type','field_path'} or not all(isinstance(v,str) for v in e.values()) for e in excluded):
        raise ValueError('Excluded relationships require source_type and field_path.')
    excluded_keys = {(e['source_type'],e['field_path']) for e in excluded}
    available = {(s,f) for s,t,f in choices}
    if len(excluded_keys) != len(excluded) or not excluded_keys <= available or excluded_keys & set(policy_by_path):
        raise ValueError('Unknown, duplicate or policy-conflicting excluded relationship.')
    bindings = profile.get('target_bindings', [])
    if not isinstance(bindings, list):
        raise ValueError('target_bindings must be a list.')
    binding_by_path = {}
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) not in ({'source_type','target_type','field_path','target_index','after_fields'}, {'source_type','target_type','field_path','target_indices','after_fields'}, {'source_type','target_type','field_path','target_indices_by_source','after_fields'}):
            raise ValueError('Explicit target binding requires typed relationship and dependencies.')
        if any(not isinstance(binding[k],str) for k in ('source_type','target_type','field_path')):
            raise ValueError('Target binding types and path must be strings.')
        signature = (binding['source_type'],binding['target_type'],binding['field_path'])
        key = (binding['source_type'],binding['field_path'])
        if signature not in choices or key in binding_by_path or key in excluded_keys or key in policy_by_path:
            raise ValueError('Target binding is unknown, duplicate, excluded or recursive.')
        rows = binding.get('target_indices_by_source')
        if rows is not None and (not isinstance(rows,list) or len(rows)!=count or any(not isinstance(row,list) or not 1<=len(row)<=8 for row in rows)):
            raise ValueError('Target binding requires one occurrence list per source instance.')
        indices = [i for row in rows for i in row] if rows is not None else binding.get('target_indices', [binding.get('target_index')])
        if not isinstance(indices, list) or not 1 <= len(indices) <= (8*count if rows is not None else 8) or any(type(i) is not int or not 1 <= i <= count for i in indices):
            raise ValueError('Target binding index is outside selected instances.')
        if ('target_indices' in binding or rows is not None) and '[]' not in binding['field_path']:
            raise ValueError('Multiple target occurrences require an array relationship.')
        if binding['source_type'] == binding['target_type'] or any(canonical(e.target)==binding['source_type'] for e in by_type[binding['target_type']].dependencies):
            raise ValueError('Target binding cannot override recursive or contained-child ownership.')
        after = binding['after_fields']
        if not isinstance(after,list) or any(not isinstance(f,str) or (binding['source_type'],f) not in available or f==binding['field_path'] or (binding['source_type'],f) in excluded_keys for f in after) or len(set(after))!=len(after):
            raise ValueError('Invalid target-binding relationship dependencies.')
        binding_by_path[key] = binding
    for index, (signature, relation) in enumerate(sorted(choices.items()), 1):
        source, target, field = signature
        if (source,field) in excluded_keys:
            continue
        policy = policy_by_path.get((source, field)) if source == target else None
        if policy:
            matched_policies.add((source, field))
        for i, source_instance in enumerate(instances[source]):
            # Two source instances share one target. For array-valued paths,
            # both sources also reuse a second target, exercising many-to-many.
            if policy:
                targets = [instances[target][i + 1]] if i < count - 1 else [instances[target][count - max(policy.get('cycle_lengths', [2]))]]
            elif target == source:
                targets = [t for t in instances[target] if t != source_instance][:2] if '[]' in field else [instances[target][(i + 1) % count]]
            elif any(canonical(edge.target) == source for edge in by_type[target].dependencies):
                # A contained child belongs to its captured parent. An array
                # response alone is not proof that this child can be shared.
                targets = [instances[target][i]]
            elif '[]' in field:
                targets = [instances[target][i % count], instances[target][(i + 1) % count]]
            else:
                targets = [instances[target][0 if i < 2 else i % count]]
            binding = binding_by_path.get((source,field))
            if binding:
                selected = binding['target_indices_by_source'][i] if 'target_indices_by_source' in binding else binding.get('target_indices', [binding.get('target_index')])
                targets = [instances[target][n-1] for n in selected]
            task_id = 'link:' + str(index) + ':' + str(i + 1)
            tasks.append({'id': task_id, 'kind': 'link', 'source_instance': source_instance,
                'target_instances': targets, 'field_path': field, 'operation': relation['operation'],
                'after': ['create:' + source_instance] + ['create:' + t for t in targets],
                'pointer': relation['pointer'], 'binding': 'response_projection_into_request_schema',
                'readback': 'must_resolve_documented_get_and_relationship_path', 'executable': False})
            if policy and i == count - 1:
                tasks[-1].update(kind='negative_link', expected_outcome='rejected_and_source_unchanged',
                    rejection_codes=policy['rejection_codes'], evidence_sha256=policy['evidence_sha256'],
                    cycle_path=instances[source][-max(policy.get('cycle_lengths', [2])):],
                    after=tasks[-1]['after'] + ['link:' + str(index) + ':' + str(j + 1) for j in range(count - 1)])
                if policy.get('verify_cycle_members'):
                    tasks[-1].update(verify_cycle_members=True, expected_outcome='rejected_and_all_cycle_members_unchanged')
                template = tasks[-1]
                for length in sorted(policy.get('cycle_lengths', [2]), reverse=True)[1:]:
                    tasks.append(dict(template, id='negative:' + str(index) + ':' + str(i + 1) + ':cycle-' + str(length),
                        target_instances=[instances[target][-length]], cycle_path=instances[source][-length:]))
    for task in tasks:
        binding = binding_by_path.get((task.get('source_instance','').rsplit('#',1)[0],task.get('field_path')))
        if binding:
            for field in binding['after_fields']:
                matches = [t['id'] for t in tasks if t.get('source_instance')==task['source_instance'] and t.get('field_path')==field and t['kind']=='link']
                if len(matches)!=1:
                    raise ValueError('Target binding prerequisite does not resolve uniquely.')
                task['after'] += matches
    # Explicit opt-in: remove one edge, accept the formerly cyclic reverse
    # edge, then reject restoring the removed edge. No server-specific paths.
    for signature, policy in policy_by_path.items():
        if not policy.get('legal_lifecycle'):
            continue
        source, field = signature
        chain = instances[source]
        positives = [t for t in tasks if t['kind'] == 'link' and
                     t['source_instance'] in chain and t['field_path'] == field]
        for task in positives:
            task['legal_readback'] = True
        template = next(t for t in positives if t['source_instance'] == chain[0])
        baseline = [t['id'] for t in tasks]
        prefix = 'lifecycle:' + source + ':' + field
        unlink = dict(template, id=prefix + ':unlink', kind='unlink',
                      target_instances=[], after=baseline, lifecycle_phase=True)
        reverse = dict(template, id=prefix + ':legal-reverse', source_instance=chain[-1],
                       target_instances=[chain[0]], after=[unlink['id']], lifecycle_phase=True)
        reject = dict(template, id=prefix + ':reject-restore', kind='negative_link',
                      after=[reverse['id']], lifecycle_phase=True, legal_readback=False,
                      rejection_codes=policy['rejection_codes'], evidence_sha256=policy['evidence_sha256'],
                      cycle_path=chain[1:] + chain[:1], verify_cycle_members=True)
        tasks.extend([unlink, reverse, reject])
        if policy.get('alternate_paths'):
            previous = reject['id']
            def transition(label, owner, targets, kind='link', cycle=None):
                nonlocal previous
                task = dict(template, id=prefix + ':alternate:' + label,
                            source_instance=owner, target_instances=targets, kind=kind,
                            after=[previous], lifecycle_phase=True, legal_readback=kind != 'negative_link')
                if cycle:
                    task.update(cycle_path=cycle, verify_cycle_members=True,
                                rejection_codes=policy['rejection_codes'], evidence_sha256=policy['evidence_sha256'])
                tasks.append(task)
                previous = task['id']
            # Start from an observed empty graph; keep the owned instances.
            for i, owner in enumerate(chain):
                transition('clear-' + str(i + 1), owner, [], 'unlink')
            a, b, c, d = chain[:4]
            transition('fork', a, [b, c])
            transition('left', b, [d])
            transition('right', c, [d])
            transition('reject-both-paths', d, [a], 'negative_link', [a, b, d])
            transition('remove-left', b, [], 'unlink')
            transition('reject-remaining-path', d, [a], 'negative_link', [a, c, d])
            transition('remove-right', c, [], 'unlink')
            transition('accept-after-both-removed', d, [a])

    if matched_policies != set(policy_by_path):
        raise ValueError('Recursive rejection policy does not match a writable self-relationship.')
    action_candidates = []
    read_pairs = {(r['source'], r['target']) for r in maps['relationship_map']['templates']
                  if r['operation'] is None and r['rule'] == 'explicit_schema_reference'}
    for operation in maps['operation_map']['operations']:
        source = operation['resource_type']
        if source not in instances or operation_kinds.get(operation['operation']) != 'action':
            continue
        for slot in operation['path_slots']:
            target = slot['business_type']
            if target in instances and target != source and (source, target) in read_pairs:
                action_candidates.append({'operation': operation['operation'], 'source_type': source,
                    'target_type': target, 'path_slot': slot['name'],
                    'status': 'relationship_effect_requires_observation', 'executable': False})
    blockers.extend([{'reason': 'bootstrap_and_authentication_binding_not_validated'},
                     {'reason': 'response_projection_and_readback_bindings_not_validated'},
                     {'reason': 'instance_aliases_require_runtime_coobservation'}])
    return {'version': 1, 'status': 'REVIEW_PLAN_ONLY', 'instances': instances,
            'tasks': tasks, 'action_candidates': action_candidates, 'blockers': blockers, 'server_requests_sent': 0,
            'http_policy': 'one HTTP request at a time; scheduling belongs to stories, transport to interfaces',
            'cycle_policy': 'Optional relationship links follow instance creation. Required create cycles remain blocked.',
            'recursive_relationship_policies': policies,
            'coverage_limit': 'Only explicit nested references writable in an inferred update operation become link tasks. Other relationships remain in the map for review.'}
