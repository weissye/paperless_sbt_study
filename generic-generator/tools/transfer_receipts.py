"""Independent checks for complete dependency transfer receipts. No HTTP."""
import copy
from datetime import datetime


def _walk(value,path,visitor):
    key,*rest=path.split('.')
    array=key.endswith('[]');key=key.removesuffix('[]')
    if not isinstance(value,dict):raise ValueError('Invalid dependency container.')
    if rest:
        children=value.get(key,[]) if array else [value.get(key)]
        for child in children:_walk(child,'.'.join(rest),visitor)
    else:visitor(value,key)


def _subset(template,target):
    if isinstance(template,dict):return isinstance(target,dict) and all(k in target and _subset(v,target[k]) for k,v in template.items())
    if isinstance(template,list):return isinstance(target,list) and len(template)==len(target) and all(_subset(a,b) for a,b in zip(template,target))
    return template==target


def validate_transfer_receipts(receipt,plan):
    tasks=[t for t in plan['tasks'] if t['kind']=='dependency_transfer']
    if not tasks:return
    records=receipt.get('dependency_transfers')
    if not isinstance(records,list) or len(records)!=len(tasks):raise ValueError('Missing dependency transfer receipts.')
    seen=set();owned={o['instance']:o['route'] for o in receipt.get('owned_records',[])}
    for record in records:
        task=next((t for t in tasks if t['id']==record.get('task_id')),None)
        if not task or task['id'] in seen:raise ValueError('Unknown or duplicate transfer task.')
        seen.add(task['id']);cfg=task['config'];field=cfg['target_field'];path=cfg['field_path'];sources=task['sources']
        ids=record.get('target_ids',[])
        if len(ids)!=3 or len(set(ids))!=3 or ids!=[owned.get(t,{}).get('id') for t in task['targets']]:raise ValueError('Transfer target identities are not three owned instances.')
        if record.get('source_ids')!={s:owned.get(s,{}).get('id') for s in sources}:raise ValueError('Transfer source identities are not owned.')
        templates=copy.deepcopy(record.get('initial_templates',{}));targets=copy.deepcopy(record.get('initial_targets',{}));baselines=record.get('baselines',{})
        if set(templates)!=set(ids) or set(targets)!=set(ids) or set(baselines)!=set(sources):raise ValueError('Incomplete transfer baselines.')
        for identity in ids:
            if templates[identity].get('id')!=identity or not _subset(templates[identity],targets[identity]) or field not in templates[identity]:raise ValueError('Embedded template is not derived from the owned target baseline.')
        for index,source in enumerate(sources):
            before=baselines[source]
            if sorted(before)!=sorted(cfg['preserve_fields']):raise ValueError('Protected baseline is incomplete.')
            observed=[]
            def baseline_slot(o,k):
                template=o.get(k)
                if not isinstance(template,dict) or template.get('id') not in ids or template!=templates[template['id']]:raise ValueError('Baseline dependency view disagrees with target.')
                observed.append(template['id'])
            _walk(before,path,baseline_slot)
            if observed!=([ids[0],ids[1]] if index<2 else [ids[2],ids[2]]):raise ValueError('Baseline topology is not A/B, A/B, C/C.')
        phases=record.get('phases',[])
        if len(phases)!=len(task['phases']) or not isinstance(record.get('namespace'),str) or not record['namespace']:raise ValueError('Incomplete transfer phase history.')
        assignments={s:1 for s in sources}
        for actual,phase in zip(phases,task['phases']):
            if actual.get('phase')!=phase:raise ValueError('Transfer phase order changed.')
            target=ids[phase['target_index']-1]
            if phase['kind']=='update':
                value=record['namespace']+'-'+phase['value'];expected=copy.deepcopy(targets[target]);expected[field]=value
                observed=actual.get('observed_target');protected=copy.deepcopy(observed)
                if not isinstance(observed,dict):raise ValueError('Missing observed target.')
                for timestamp in cfg.get('target_timestamp_fields',[]):
                    value_time=observed.get(timestamp)
                    if not isinstance(value_time,str):raise ValueError('Missing update timestamp.')
                    try:datetime.fromisoformat(value_time.replace('Z','+00:00'))
                    except ValueError as error:raise ValueError('Invalid update timestamp.') from error
                    if timestamp in expected:protected[timestamp]=expected[timestamp]
                    else:protected.pop(timestamp,None)
                if actual.get('value')!=value or actual.get('expected_target')!=expected or protected!=expected:raise ValueError('Target update receipt mismatch.')
                targets[target]=copy.deepcopy(observed);templates[target][field]=value
                for timestamp in cfg.get('target_timestamp_fields',[]):
                    if timestamp in templates[target]:templates[target][timestamp]=observed[timestamp]
            else:assignments[phase['source']]=phase['target_index']
            checks=actual.get('checks',[])
            if sorted(c.get('instance','') for c in checks)!=sorted(sources):raise ValueError('Missing or duplicate transfer source check.')
            for c in checks:
                source=c['instance'];expected=copy.deepcopy(baselines[source])
                def remap(o,k):
                    identity=o[k]['id']
                    if identity==ids[0]:identity=ids[assignments[source]-1]
                    o[k]=copy.deepcopy(templates[identity])
                _walk(expected,path,remap)
                if c.get('expected')!=expected or c.get('observed')!=expected:raise ValueError('Transfer reference, quantity or embedded view changed unexpectedly.')
        if record.get('targets')!=targets or record.get('templates')!=templates or record.get('assignments')!=assignments:raise ValueError('Final transfer state disagrees with phase history.')
