"""Compile explicit merge and additive-contribution policies against an OpenAPI contract."""
import copy
import hashlib
import math


def append_semantic_program(blueprint, info, entities, config, add_request,
                            request_schema, response_schema, root, operations):
    required = {'family','resource_type','reference_type','container_type','resource_identity',
                'reference_identity','merge','contribution','reference_measure','container_measure',
                'container_references','merge_key_index','baseline_container_total',
                'baseline_reference_item_quantity','tolerance'}
    if not isinstance(config,dict) or not required.issubset(config) or set(config)-required-{'require_merge_collision','phases','baseline_reference_total'} or config['family'] not in ('merge','quantity','combined'):
        raise ValueError('Invalid explicit semantic program configuration.')
    if 'require_merge_collision' in config and type(config['require_merge_collision']) is not bool:
        raise ValueError('require_merge_collision must be a boolean.')
    if config.get('require_merge_collision') and config['family']=='quantity':
        raise ValueError('Merge collision requires a merge family.')
    types = [config[k] for k in ('resource_type','reference_type','container_type')]
    if len(set(types))!=3 or any(t not in blueprint['instances'] for t in types):
        raise ValueError('Semantic program requires three distinct selected resource types.')
    if any(len(blueprint['instances'][t])<3 for t in types):
        raise ValueError('Semantic program requires at least three instances per type.')
    for key in ('tolerance','baseline_container_total','baseline_reference_item_quantity'):
        value=config[key]
        if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (key!='baseline_container_total' and value==0):
            raise ValueError('Invalid semantic numeric policy: '+key)
    if config['tolerance']>0.0001:
        raise ValueError('Semantic tolerance must be at most 0.0001.')
    def leaf(node,path):
        def resolve(node):
            node=root(node)
            if 'anyOf' in node or 'oneOf' in node:
                return [v for b in node.get('anyOf',node.get('oneOf')) for v in resolve(b) if v.get('type')!='null']
            return [node]
        nodes=[node]
        for segment in path.split('.'):
            children=[]
            for n in nodes:
                for view in resolve(n):
                    child=view.get('properties',{}).get(segment.removesuffix('[]'))
                    if child is None:raise ValueError('Undocumented semantic path: '+path)
                    if segment.endswith('[]'):
                        child=root(child)
                        if child.get('type')!='array':raise ValueError('Semantic path is not an array: '+path)
                        child=child['items']
                    children.append(child)
            nodes=children
        return [v for n in nodes for v in resolve(n)]
    def getter(resource):
        op=entities[resource].get_op.op
        return op.method+' '+op.path
    for key,resource in [('resource_identity',types[0]),('reference_identity',types[1])]:
        if not isinstance(config[key],str) or not config[key] or any(v.get('type')!='string' for v in leaf(response_schema(getter(resource)),config[key])):
            raise ValueError('Semantic identity must be a documented string.')
    for name,resource in [('reference_measure',types[1]),('container_measure',types[2])]:
        measure=config[name]
        if not isinstance(measure,dict) or set(measure)!={'items_path','key_paths','amount_path'} or not isinstance(measure['key_paths'],list) or not measure['key_paths']:
            raise ValueError('A semantic measure needs items_path, key_paths and amount_path.')
        item=leaf(response_schema(getter(resource)),measure['items_path'])
        for path in measure['key_paths']:
            if not isinstance(path,str) or any(v.get('type')!='string' for n in item for v in leaf(n,path)):
                raise ValueError('Semantic grouping keys must be documented strings.')
        if any(v.get('type') not in ('number','integer') for n in item for v in leaf(n,measure['amount_path'])):
            raise ValueError('Semantic amount must be a documented number.')
    if len(config['reference_measure']['key_paths'])!=len(config['container_measure']['key_paths']) or type(config['merge_key_index']) is not int or not 0<=config['merge_key_index']<len(config['container_measure']['key_paths']):
        raise ValueError('Semantic source/container grouping dimensions must match.')
    refs=config['container_references']
    if not isinstance(refs,dict) or set(refs)!={'items_path','key_path','amount_path'}:
        raise ValueError('Semantic reference quantity view is incomplete.')
    item=leaf(response_schema(getter(types[2])),refs['items_path'])
    if any(v.get('type')!='string' for n in item for v in leaf(n,refs['key_path'])) or any(v.get('type') not in ('number','integer') for n in item for v in leaf(n,refs['amount_path'])):
        raise ValueError('Semantic contribution reference fields are not documented.')
    merge=config['merge']; contribution=config['contribution']
    if not isinstance(merge,dict) or set(merge)!={'operation','from_field','to_field','absent_codes'}:
        raise ValueError('Semantic merge requires explicit source, target and absence bindings.')
    def belongs(identity, resource):
        collection = entities[resource].create_op.op.path.rstrip('/')
        return identity in operations and operations[identity].path.startswith(collection + '/')
    if not belongs(merge['operation'], types[0]) or operations[merge['operation']].path_params or not merge['operation'].startswith(('PUT ','POST ')):
        raise ValueError('Semantic merge operation must belong to its resource type.')
    if not isinstance(merge['absent_codes'],list) or not merge['absent_codes'] or any(type(c) is not int or c not in (404,410) for c in merge['absent_codes']):
        raise ValueError('Semantic merge requires explicit 404/410 absence codes.')
    if merge['from_field']==merge['to_field']:
        raise ValueError('Merge source and target fields must differ.')
    for key in ['from_field','to_field']:
        if any(v.get('type')!='string' for v in leaf(request_schema(merge['operation']),merge[key])):
            raise ValueError('Merge request identity field is not documented.')
    if not isinstance(contribution,dict) or set(contribution)!={'add_operation','remove_operation','target_parameter','add_field','remove_field'}:
        raise ValueError('Contribution operation bindings are incomplete.')
    for action,field in [('add_operation','add_field'),('remove_operation','remove_field')]:
        identity=contribution[action]
        if identity not in operations or not identity.startswith('POST ') or not belongs(identity, types[2]):
            raise ValueError('Contribution operation must belong to its container type.')
        if contribution['target_parameter'] not in [p.name for p in operations[identity].path_params]:
            raise ValueError('Contribution target route parameter is not documented.')
        if any(v.get('type') not in ('number','integer') for v in leaf(request_schema(identity),contribution[field])):
            raise ValueError('Contribution increment/decrement field is not numeric.')
    if 'baseline_reference_total' in config:
        total = config['baseline_reference_total']
        if type(total) not in (int,float) or not math.isfinite(total) or total <= 0:
            raise ValueError('Invalid reference total baseline.')
    custom = config.get('phases')
    if 'phases' in config and custom is None:
        raise ValueError('Explicit semantic phases cannot be null.')
    if custom is not None:
        if not isinstance(custom,list) or not 1 <= len(custom) <= 32:
            raise ValueError('Explicit semantic phases require a nonempty bounded list.')
        balances = {}; retired = set(); merges = 0
        for phase_spec in custom:
            if not isinstance(phase_spec,dict):
                raise ValueError('Invalid semantic phase.')
            if phase_spec.get('kind') == 'contribution':
                if set(phase_spec) != {'kind','amount','offset'}:
                    raise ValueError('Contribution phase needs amount and offset.')
                amount, offset = phase_spec['amount'], phase_spec['offset']
                if type(amount) not in (int,float) or not math.isfinite(amount) or amount == 0 or abs(amount)>100 or type(offset) is not int or not 0 <= offset < len(blueprint['instances'][types[1]]):
                    raise ValueError('Invalid phase amount or reference offset.')
                for index in range(len(blueprint['instances'][types[2]])):
                    key=(index,(index+offset)%len(blueprint['instances'][types[1]]))
                    balances[key]=balances.get(key,0)+amount
                    if balances[key]<-config['tolerance']:
                        raise ValueError('Contribution phase would remove unavailable stock.')
            elif phase_spec.get('kind') == 'merge':
                if set(phase_spec) != {'kind','from_index','to_index'}:
                    raise ValueError('Merge phase needs explicit indices.')
                a,b=phase_spec['from_index'],phase_spec['to_index']
                if any(type(v) is not int or not 1<=v<=len(blueprint['instances'][types[0]]) for v in (a,b)) or a==b or a in retired or b in retired:
                    raise ValueError('Merge phase uses invalid or retired identity.')
                retired.add(a); merges+=1
            else:
                raise ValueError('Unknown semantic phase kind.')
        if config.get('require_merge_collision') and not merges:
            raise ValueError('Required collision needs a merge phase.')
    prefix=[t['id'] for t in blueprint['tasks']]
    containers=blueprint['instances'][types[2]]; references=blueprint['instances'][types[1]]; resources=blueprint['instances'][types[0]]
    state='rel_semantic_state';steps_by_task={}
    views=[{'instance':i,'view_kind':kind} for kind,typ in [('reference',types[1]),('container',types[2])] for i in blueprint['instances'][typ]]
    blueprint['semantic_program']=copy.deepcopy(config)
    def common():return {'semantic_config':config,'semantic_state':state}
    def add_task(task,steps):
        task['executable']=True;blueprint['tasks'].append(task);steps_by_task[task['id']]=steps
    init='semantic:init'
    steps=[]
    for index,view in enumerate(views):
        i=view['instance'];ctx=dict(info[i],mode='semantic_init',**common(),view_kind=view['view_kind'],task_id=init if index==len(views)-1 else None)
        steps.append(add_request(getter(info[i]['resource']),ctx,i))
    add_task({'id':init,'kind':'semantic_init','source_instance':containers[0],'target_instances':[], 'operation':getter(types[2]),'after':prefix,'checks':views},steps)
    barrier=[init];sequence=0
    def transition(kind,owner,target=None,amount=None,source=None):
        nonlocal sequence
        sequence+=1;task_id='semantic:'+str(sequence)+':'+kind+':'+owner
        body_var='rel_sem_'+hashlib.sha256(task_id.encode()).hexdigest()[:16]
        task={'id':task_id,'kind':'semantic_'+kind,'source_instance':owner,'target_instances':[target] if target else [],'after':list(barrier),'checks':views}
        ctx=dict(common(),expectation_variable=body_var,semantic_task_id=task_id,body_variable=body_var)
        steps=[]
        if kind=='merge':
            operation=merge['operation'];task.update(from_instance=source,to_instance=target,operation=operation,absent_codes=merge['absent_codes'])
            steps.append(add_request(getter(types[0]),dict(info[target],mode='snapshot'),target))
            steps.append(add_request(getter(types[0]),dict(info[source],mode='semantic_prepare_merge',**ctx,target_snapshot=info[target]['snapshot_variable'],to_instance=target,request_schema=request_schema(operation)),source))
            steps.append(add_request(operation,{'mode':'write'},None,body_var))
            steps.append(add_request(getter(types[0]),dict(info[source],mode='semantic_absent',**ctx,absence_codes=merge['absent_codes']),source))
            steps.append(add_request(getter(types[0]),dict(info[target],mode='snapshot'),target))
        else:
            operation=contribution['add_operation' if amount>0 else 'remove_operation'];task.update(operation=operation,amount=amount,reference_instance=target)
            steps.append(add_request(getter(types[2]),dict(info[owner],mode='semantic_prepare_contribution',**ctx,reference_instance=target,reference_snapshot=info[target]['snapshot_variable'],amount=amount,request_schema=request_schema(operation),target_variable=body_var+'_target'),owner))
            steps.append(add_request(operation,{'mode':'write'},owner,body_var,{contribution['target_parameter']:'@{'+body_var+'_target}'}))
        for index,view in enumerate(views):
            i=view['instance'];check=dict(info[i],mode='semantic_check',**ctx,view_kind=view['view_kind'],check_count=len(views),task_id=task_id if index==len(views)-1 else None)
            steps.append(add_request(getter(info[i]['resource']),check,i))
        add_task(task,steps);return task_id
    def phase(amount,offset=0):
        nonlocal barrier
        next_barrier=[]
        for index,container in enumerate(containers):
            next_barrier.append(transition('contribution',container,references[(index+offset)%len(references)],amount))
        barrier=next_barrier
    if custom is not None:
        for spec in custom:
            if spec['kind']=='contribution':
                phase(spec['amount'],spec['offset'])
            else:
                source=resources[spec['from_index']-1];target=resources[spec['to_index']-1]
                barrier=[transition('merge',source,target,source=source)]
        return steps_by_task
    family=config['family']
    phase(2)
    if family in ('quantity','combined'):phase(3,1)
    if family in ('merge','combined'):
        barrier=[transition('merge',resources[0],resources[1],source=resources[0])]
    if family in ('quantity','combined'):
        phase(-1);phase(0.5)
    if family in ('merge','combined'):
        barrier=[transition('merge',resources[1],resources[2],source=resources[1])]
    if family in ('quantity','combined'):
        phase(-3,1);phase(-1.5)
    return steps_by_task
