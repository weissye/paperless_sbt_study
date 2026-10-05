"""Independent route change receipt validation. No HTTP requests."""
import copy
import json
from datetime import datetime
from uuid import UUID


def _view(value,targets,cfg,change):
    value=copy.deepcopy(value)
    def walk(o):
        if isinstance(o,dict):
            target=targets.get(o.get(cfg['identity_field']))
            if target:
                for field in [cfg['route_field'],change]+cfg['timestamp_fields']:
                    if field in o and field in target:o[field]=target[field]
                for path in cfg.get('recreated_identity_paths',[]):
                    def child_rows(obj):
                        for key in path[:-5].split('.'):
                            if not isinstance(obj,dict):return None
                            obj=obj.get(key)
                        return obj
                    rows=child_rows(o);current=child_rows(target)
                    if isinstance(rows,list) and isinstance(current,list) and len(rows)==len(current):
                        for row,item in zip(rows,current):row['id']=item['id']
            for child in o.values():walk(child)
        elif isinstance(o,list):
            for child in o:walk(child)
    walk(value);return value


def validate_route_receipts(receipt,plan):
    tasks=[t for t in plan['tasks'] if t['kind']=='route_identity']
    if not tasks:return
    records=receipt.get('route_identities',[])
    if len(records)!=len(tasks):raise ValueError('Missing route receipts.')
    owned={o['instance']:o['route'] for o in receipt['owned_records']};seen=set()
    for record in records:
        task=next((t for t in tasks if t['id']==record.get('task_id')),None)
        if task is None or task['id'] in seen:raise ValueError('Unknown/duplicate route task.')
        seen.add(task['id']);cfg=task['config'];field=cfg['route_field'];identity=cfg['identity_field'];change=task['change_field'];ids=record['ids']
        if len(ids)!=3 or len(set(ids))!=3 or ids!=[owned[t][identity] for t in task['targets']]:raise ValueError('Route stable identities not owned.')
        targets=copy.deepcopy(record['initial_targets']);initial=record['initial_routes'];baselines=record['baselines']
        if set(targets)!=set(ids) or initial!=[targets[i][field] for i in ids]:raise ValueError('Invalid initial aliases.')
        refs=task['referrers']
        if set(baselines)!={r['instance'] for r in refs} or record['source_ids']!={r['instance']:owned[r['instance']][identity] for r in refs}:raise ValueError('Invalid referrer ownership.')
        if not isinstance(record.get('namespace'),str) or not record['namespace']:raise ValueError('Missing route namespace.')
        def values(value,path):
            parts=path.split('.');current=[value]
            for part in parts:
                array=part.endswith('[]');key=part.removesuffix('[]');following=[]
                for node in current:
                    if isinstance(node,dict) and key in node:
                        item=node[key];following.extend(item if array and isinstance(item,list) else [item])
                current=following
            return current
        for ref in refs:
            before=baselines[ref['instance']]
            if set(before)-set(ref['preserve_fields']):raise ValueError('Unknown protected baseline fields.')
            if ref.get('requires_reference') and ids[0] not in values(before,ref['reference_path']):raise ValueError('Initial referrer not linked to original target.')
        if len(record['phases'])!=len(task['phases']):raise ValueError('Incomplete route phases.')
        expected_alias=[]
        for n,(actual,phase) in enumerate(zip(record['phases'],task['phases'])):
            id=ids[phase['target_index']-1];before=targets[id];value=record['initial_targets'][ids[phase['reuse_index']-1]][change] if 'reuse_index' in phase else record['namespace']+'-'+phase['suffix'];expected=copy.deepcopy(before);expected[change]=value
            if cfg['mode']!='control':expected[field]=initial[phase['reuse_index']-1] if 'reuse_index' in phase else record['namespace']+'-'+phase['suffix']
            observed=actual.get('observed');protected=copy.deepcopy(observed)
            if not isinstance(observed,dict):raise ValueError('Missing route target observation.')
            for timestamp in cfg['timestamp_fields']:
                try:datetime.fromisoformat(observed[timestamp].replace('Z','+00:00'))
                except (KeyError,TypeError,AttributeError,ValueError) as e:raise ValueError('Invalid observed timestamp.') from e
                if timestamp in expected:protected[timestamp]=expected[timestamp]
                else:protected.pop(timestamp,None)
            changes=[]
            for path in cfg.get('recreated_identity_paths',[]):
                arrays=values(expected,path[:-5]);others=values(protected,path[:-5])
                if len(arrays)!=1 or len(others)!=1 or not isinstance(arrays[0],list) or not isinstance(others[0],list) or len(arrays[0])!=len(others[0]):raise ValueError('Child identity shape changed.')
                observed_ids=[]
                for index,(old,new) in enumerate(zip(arrays[0],others[0])):
                    try:UUID(old['id']);UUID(new['id'])
                    except (KeyError,TypeError,AttributeError,ValueError) as e:raise ValueError('Invalid child identity.') from e
                    observed_ids.append(new['id'])
                    if old['id']!=new['id']:changes.append(dict(path=path,index=index,before=old['id'],after=new['id']))
                    new['id']=old['id']
                if len(set(observed_ids))!=len(observed_ids):raise ValueError('Duplicate child identity.')
            if actual.get('recreated_identities',[])!=changes:raise ValueError('Unrecorded child identity replacement.')
            if actual.get('phase')!=phase or actual.get('before')!=before or actual.get('expected')!=expected or actual.get('value')!=value or protected!=expected:raise ValueError('Route identity or protected state mismatch.')
            if cfg.get('capture_route_evidence'):
                raw=[x for x in record.get('raw_observations',[]) if x.get('phase')==n]
                if len(raw)!=3+len(refs):raise ValueError('Incomplete raw route observations.')
                def one(kind):
                    rows=[x for x in raw if x.get('kind')==kind]
                    if len(rows)!=1:raise ValueError('Missing or duplicate '+kind+' observation.')
                    return rows[0]
                write=one('write');new_read=one('new_route');old_read=one('old_route')
                if write.get('operation')!=task['operation'] or write.get('instance')!=task['targets'][phase['target_index']-1] or write.get('code') not in task['write_success_codes']:raise ValueError('Invalid raw write observation.')
                try:request=json.loads(write['request_body'])
                except (KeyError,TypeError,ValueError) as e:raise ValueError('Missing exact write request.') from e
                if request.get(change)!=value:raise ValueError('Raw write did not contain the configured change.')
                if 'id' in request and request['id']!=id:raise ValueError('Raw write changed stable identity.')
                if not isinstance(write.get('body'),str):raise ValueError('Missing raw write response body.')
                if write['body']:
                    returned=json.loads(write['body'])
                    if isinstance(returned,dict) and any(f in returned and returned[f]!=expected[f] for f in (identity,field,change)):
                        raise ValueError('Raw write response changed identity or route.')
                if new_read.get('code')!=200 or json.loads(new_read['body'])!=observed:raise ValueError('Raw new-route read differs from validated state.')
                old_code=200 if cfg['mode']=='control' else 404
                if old_read.get('code')!=old_code:raise ValueError('Raw old-route status differs from policy.')
                if old_code==200 and json.loads(old_read['body']).get(identity)!=id:raise ValueError('Raw old-route identity differs.')
                source_rows=[x for x in raw if x.get('kind')=='referrer']
                if sorted(x['instance'] for x in source_rows)!=sorted(r['instance'] for r in refs):raise ValueError('Incomplete raw referrer reads.')
                for source in source_rows:
                    if source.get('code')!=200:raise ValueError('Raw referrer read failed.')
                    expected_check=next(c for c in actual['checks'] if c['instance']==source['instance'])
                    source_body=json.loads(source['body'])
                    rule=next(r for r in refs if r['instance']==source['instance'])
                    projected={f:source_body[f] for f in rule['preserve_fields'] if f in source_body}
                    if projected!=expected_check['observed']:raise ValueError('Raw referrer differs from validated state.')
            targets[id]=copy.deepcopy(observed)
            checks=actual.get('checks',[])
            if sorted(c['instance'] for c in checks)!=sorted(r['instance'] for r in refs):raise ValueError('Missing/duplicate referrer check.')
            for check in checks:
                expected_view=_view(baselines[check['instance']],targets,cfg,change)
                if check['expected']!=expected_view or check['observed']!=expected_view:raise ValueError('Reference migrated or quantity changed.')
            expected_id=id if cfg['mode']=='control' else None
            expected_alias.append({'phase':n,'code':200 if expected_id else 404,'expected_id':expected_id,'observed_id':expected_id})
        if cfg['mode']=='reuse':expected_alias.append({'phase':2,'code':200,'expected_id':ids[2],'observed_id':ids[2]})
        if cfg.get('capture_route_evidence') and len(record.get('raw_observations',[]))!=len(task['phases'])*(3+len(refs)):raise ValueError('Unexpected raw route observations.')
        if record['alias_checks']!=expected_alias or record['targets']!=targets:raise ValueError('Incorrect final alias resolution.')
        for id,target in zip(ids,task['targets']):
            if owned[target].get(field)!=targets[id][field]:raise ValueError('Final route binding is stale.')
