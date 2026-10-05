"""Generate detach/delete tasks from owned many-to-many membership bindings."""
import hashlib


def append_detached_deletions(blueprint, info, entities, runtime, add_request,
                             request_schema, property_schema, root):
    rules = runtime.get('detached_target_deletions', [])
    if not isinstance(rules, list):
        raise ValueError('detached_target_deletions must be a list.')
    attached_rules = runtime.get('attached_target_deletions', [])
    if not isinstance(attached_rules, list):
        raise ValueError('attached_target_deletions must be a list.')
    combined = [(r, False) for r in rules] + [(r, True) for r in attached_rules]
    steps_by_task = {}; selected_types = set()
    deletion_prefix = [t['id'] for t in blueprint['tasks']]
    links = [t for t in blueprint['tasks'] if t['kind'] == 'link' and not t.get('lifecycle_phase')]
    for index, (rule, attached) in enumerate(combined):
        required = {'resource_type', 'operation', 'absent_codes'} | ({'success_policy'} if attached else set())
        if not isinstance(rule, dict) or set(rule) != required:
            raise ValueError('Detached deletion requires resource_type, operation and absent_codes.')
        if attached and rule['success_policy'] != 'remove_references':
            raise ValueError('Attached deletion requires an explicit remove_references success policy.')
        resource = rule['resource_type']; operation = rule['operation']; codes = rule['absent_codes']
        if not isinstance(resource, str) or resource not in blueprint['instances'] or resource in selected_types:
            raise ValueError('Detached deletion requires a unique selected resource type.')
        if not isinstance(operation, str) or not operation.startswith('DELETE ') or operation not in [o.op.method+' '+o.op.path for o in entities[resource].ops]:
            raise ValueError('Deletion operation must belong to its selected resource.')
        if not isinstance(codes, list) or not codes or any(type(c) is not int or c not in (404,410) for c in codes) or len(set(codes)) != len(codes):
            raise ValueError('Deletion absence codes must explicitly select 404 or 410.')
        selected_types.add(resource)
        for target in blueprint['instances'][resource]:
            references = [t for t in links if target in t['target_instances'] and info[t['source_instance']]['resource'] != resource]
            if len({r['source_instance'] for r in references}) < 2:
                raise ValueError('Detached deletion requires two distinct known referrers.')
            paths = {r['field_path'] for r in references}; source_types = {info[r['source_instance']]['resource'] for r in references}
            if len(paths) != 1 or len(source_types) != 1:
                raise ValueError('Detached deletion currently requires one source type and membership path.')
            field_path = next(iter(paths)); source_type = next(iter(source_types))
            if not field_path.endswith('[]') or '.' in field_path or field_path.count('[]') != 1:
                raise ValueError('Detached deletion requires a top-level membership array.')
            write_operations = {r['operation'] for r in references}
            if len(write_operations) != 1:
                raise ValueError('Detached deletion requires one contract-derived membership update.')
            write = next(iter(write_operations))
            leaf = root(property_schema(request_schema(write), field_path[:-2], writable=True))
            if leaf.get('minItems', 0) > 0:
                raise ValueError('Membership schema forbids complete detachment.')
            source_ep = entities[source_type]; source_get = source_ep.get_op.op.method+' '+source_ep.get_op.op.path
            ep = entities[resource]; getter = ep.get_op.op.method+' '+ep.get_op.op.path
            target_meta = info[target]; task_id = ('attached-delete:' if attached else 'detached-delete:')+str(index+1)+':'+target
            variable = 'rel_delete_'+hashlib.sha256(task_id.encode()).hexdigest()[:16]
            referrer_instances = {r['source_instance'] for r in references}
            checks = []
            for source in blueprint['instances'][source_type]:
                protected = sorted({t['field_path'] for t in links if t['source_instance']==source and t['field_path']!=field_path})
                checks.append({'instance':source,'field_path':field_path,'detached':source in referrer_instances,'protected_fields':protected})
            task = {'id':task_id,'kind':'attached_delete' if attached else 'detached_delete','source_instance':target,
                    'target_instances':[],'operation':operation,'membership_operation':write,
                    'absent_codes':codes,'checks':checks,'after':list(deletion_prefix) if runtime.get('interleave_mutations') else [t['id'] for t in blueprint['tasks']],
                    'executable':True}
            if attached:
                task['success_policy'] = rule['success_policy']
            if runtime.get('mutate_during_construction'):
                sources = set(blueprint['instances'][source_type])
                task['after'] = [t['id'] for t in blueprint['tasks']
                    if (t['kind']=='create' and t['instance'] in sources | {target})
                    or (t['kind']=='link' and not t.get('lifecycle_phase') and target in t['target_instances'])]
            steps = []
            for i, check in enumerate(checks):
                source = check['instance']
                context = dict(info[source], mode='delete_before', expectation_variable=variable,
                               target_snapshot=target_meta['snapshot_variable'], check_index=i, **{k:check[k] for k in ('field_path','detached','protected_fields')})
                steps.append(add_request(source_get,context,source))
            target_context = dict(target_meta,mode='delete_target_before',expectation_variable=variable,deletion_task_id=task_id)
            if attached:
                target_context['attached_at_delete'] = True
            steps.append(add_request(getter,target_context,target))
            for i, check in enumerate(checks):
                if attached:
                    continue
                if not check['detached']:
                    continue
                source = check['instance']; body_variable = variable+'_body_'+str(i)
                context = dict(info[source],mode='prepare_detach',expectation_variable=variable,
                               check_index=i,field_path=field_path,request_schema=request_schema(write),body_variable=body_variable)
                steps.extend([add_request(source_get,context,source),
                              add_request(write,{'mode':'write'},source,body_variable),
                              add_request(source_get,dict(info[source],mode='verify_detach',expectation_variable=variable,check_index=i,field_path=field_path),source)])
            steps.extend([add_request(operation,{'mode':'delete_write'},target),
                          add_request(getter,dict(target_meta,mode='delete_absent',expectation_variable=variable,absence_codes=codes),target)])
            for i, check in enumerate(checks):
                source = check['instance']
                context = dict(info[source],mode='delete_after',expectation_variable=variable,
                               check_index=i,field_path=field_path,check_count=len(checks),
                               task_id=task_id if i==len(checks)-1 else None)
                steps.append(add_request(source_get,context,source))
            blueprint['tasks'].append(task);steps_by_task[task_id]=steps
    return steps_by_task
