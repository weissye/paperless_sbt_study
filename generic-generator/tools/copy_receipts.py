"""Independent qualification of actual copy/write/read response bodies."""
import copy
import json
import uuid


class CopyMismatch(ValueError):
    pass


def values(obj,path):
    nodes=[obj]
    for part in path.split('.'):
        array=part.endswith('[]');key=part[:-2] if array else part;out=[]
        for node in nodes:
            if not isinstance(node,dict) or key not in node:raise CopyMismatch('Missing protected path: '+path)
            value=node[key]
            if array:
                if value is None:value=[]
                if not isinstance(value,list):raise CopyMismatch('Invalid protected array: '+path)
                out.extend(value)
            else:out.append(value)
        nodes=out
    return nodes


def replace(obj,path,replacements):
    parts=path.split('.');index=[0]
    def walk(node,at):
        part=parts[at];array=part.endswith('[]');key=part[:-2] if array else part
        if at==len(parts)-1:
            if array:raise ValueError('Replacing whole arrays is not supported.')
            node[key]=replacements[index[0]];index[0]+=1;return
        for child in (node[key] or []) if array else [node[key]]:walk(child,at+1)
    walk(obj,0)
    if index[0]!=len(replacements):raise CopyMismatch('Replacement cardinality mismatch: '+path)


def validate_copy_receipts(receipt,plan):
    tasks=[t for t in plan['tasks'] if t['kind']=='copy_isolation']
    records=receipt.get('copy_isolations',[])
    if len(records)!=len(tasks):raise ValueError('Missing or extra copy receipts.')
    for task in tasks:
        matches=[r for r in records if r.get('task_id')==task['id']]
        if len(matches)!=1:raise ValueError('Ambiguous copy receipt.')
        evidence=copy.deepcopy(matches[0])
        try:result=qualify(evidence,task)
        except CopyMismatch as error:
            error.phase=evidence.get('_qualification_phase')
            error.task_id=task['id']
            raise
        owned={r['instance']:r['route'] for r in receipt.get('owned_records',[])}
        for instance,key in [(task['source_instance'],'source_id'),(task['copy_instance'],'copy_id')]:
            if owned.get(instance,{}).get(task['config']['identity_field'])!=result[key]:raise ValueError('Copy receipt identity is not owned by this run.')


def qualify(record,task):
    cfg=task['config'];source=task['source_instance'];copied=task['copy_instance'];identity=cfg['identity_field'];route=cfg['route_field']
    refs={r['instance']:r for r in task['referrers']};instances=[source,copied]+[i for i in refs if i!=source]
    phases=['before','duplicate']+['mutation-'+str(i) for i in range(len(cfg['mutations']))]
    rows=record.get('observations',[]);expected_count=len(instances)*len(phases)-1+1+len(cfg['mutations'])
    if len(rows)!=expected_count:raise ValueError('Incomplete copy raw observations.')
    prior={};initial={};clone_initial=None
    def fields(body,names):
        if not isinstance(body,dict) or any(name not in body for name in names):raise CopyMismatch('Missing protected content fields.')
        return {k:copy.deepcopy(body[k]) for k in names}
    def normalized(body,ignore):
        result=fields(body,cfg['content_fields'])
        for path in ignore:
            if path.split('.')[0].removesuffix('[]') in result:replace(result,path,['<derived>']*len(values(result,path)))
        return result
    def child_ids(body,path):
        result=values(body,path)
        if not result or len(result)!=len(set(result)):raise CopyMismatch('Missing or duplicate child identities: '+path)
        try:
            for value in result:uuid.UUID(value)
        except (ValueError,TypeError,AttributeError):raise CopyMismatch('Invalid child UUID: '+path)
        return result
    def read(phase,instance):
        found=[r for r in rows if r.get('phase')==phase and r.get('kind')=='read' and r.get('instance')==instance]
        if len(found)!=1:raise ValueError('Incomplete phase read: '+phase+' '+instance)
        row=found[0]
        expected_op=refs.get(instance,{}).get('operation','GET '+task['config']['write_operation'].split(' ',1)[1])
        if row.get('operation')!=expected_op:raise ValueError('Unexpected copy read operation.')
        if row.get('code') in (401,403):raise ValueError('Copy campaign authentication interrupted.')
        if row.get('code')!=200:raise CopyMismatch('Copy read status mismatch: '+phase+' '+instance)
        try:return json.loads(row['body'])
        except (TypeError,ValueError):raise ValueError('Invalid read JSON evidence.')
    def internal(body):
        rule=cfg['internal_reference']
        if rule:
            ids=child_ids(body,rule['target_path']);links=values(body,rule['reference_path'])
            if not links or any(x not in ids for x in links):raise CopyMismatch('Dangling internal child reference.')
    for phase in phases:
        record['_qualification_phase']=phase
        current={i:read(phase,i) for i in instances if phase!='before' or i!=copied}
        for i,body in current.items():
            if i in prior and (body.get(identity)!=prior[i].get(identity) or body.get(route)!=prior[i].get(route) or body.get(cfg['name_field'])!=prior[i].get(cfg['name_field'])):raise CopyMismatch('Copy phase changed a protected resource identity: '+i)
        if phase=='before':
            initial=copy.deepcopy(current)
            for link in cfg['source_links']:
                a=task['originals'][link['source_index']-1];b=task['originals'][link['target_index']-1]
                if not values(current[a],link['field_path']) or any(x.get(identity)!=current[b][identity] for x in values(current[a],link['field_path'])):raise ValueError('Source link setup not observed.')
            for path in cfg['fresh_child_paths']:child_ids(current[source],path)
            try:internal(current[source])
            except CopyMismatch as error:raise ValueError('Source internal-reference precondition was not satisfied: '+str(error)) from error
            for family in {r['resource_type'] for r in refs.values()}:
                linked=False
                for instance,rule in refs.items():
                    if rule['resource_type']!=family or instance==source:continue
                    # Non-links may be null; only this precondition allows them.
                    try:linked=linked or current[source][identity] in values(current[instance],rule['reference_path'])
                    except CopyMismatch:pass
                if not linked:raise ValueError('No observed incoming source reference in family: '+family)

        else:
            writes=[r for r in rows if r.get('phase')==phase and r.get('kind')=='write']
            if len(writes)!=1:raise ValueError('Missing copy phase write evidence.')
            write=writes[0]
            if write.get('operation')!=cfg['copy_operation' if phase=='duplicate' else 'write_operation']:raise ValueError('Unexpected copy write operation.')
            if write.get('code') in (401,403):raise ValueError('Copy campaign authentication interrupted.')
            if write.get('code') not in task['copy_success_codes' if phase=='duplicate' else 'write_success_codes']:raise CopyMismatch('Copy write status mismatch: '+phase)
            try:written=json.loads(write['body']);request=json.loads(write['request_body'])
            except (ValueError,KeyError,TypeError):raise ValueError('Missing raw write JSON.')
            if phase=='duplicate':
                new=current[copied];old=current[source]
                if new.get(identity) in [v.get(identity) for v in initial.values()] or not new.get(route) or new[route]==old[route]:raise CopyMismatch('Copy did not acquire a new independent identity.')
                if new.get(cfg['name_field'])!=request.get(cfg['name_field']):raise CopyMismatch('Copy name differs from requested name.')
                left=normalized(old,cfg['derived_paths']);right=normalized(new,cfg['derived_paths'])
                mappings={}
                for path in cfg['fresh_child_paths']:
                    a=child_ids(old,path);b=child_ids(new,path)
                    if len(a)!=len(b) or set(a)&set(b):raise CopyMismatch('Copy reused child identity: '+path)
                    mappings[path]=dict(zip(a,b));replace(right,path,a)
                rule=cfg['internal_reference']
                if rule:
                    internal(new);expected=[mappings[rule['target_path']][x] for x in values(old,rule['reference_path'])]
                    if values(new,rule['reference_path'])!=expected:raise CopyMismatch('Internal references were not remapped to copied ingredients.')
                    replace(right,rule['reference_path'],values(old,rule['reference_path']))
                if left!=right:raise CopyMismatch('Copied content or outgoing resource links differ.')
                clone_initial=copy.deepcopy(new);changed=None
            else:
                mutation=cfg['mutations'][int(phase.split('-')[1])];changed=source if mutation['side']=='source' else copied
                before=prior[changed];after=current[changed];expect=normalized(before,cfg['derived_paths']);observed=normalized(after,cfg['derived_paths'])
                wanted=values(request,mutation['path']);previous=values(before,mutation['path'])
                if not wanted or len(wanted)!=len(previous) or wanted==previous or any(not isinstance(x,str) or not x.endswith('-'+mutation['suffix']) for x in wanted):raise ValueError('Mutation request did not enact the declared change.')
                replace(expect,mutation['path'],wanted)
                for path in cfg['recreated_write_paths']:
                    a=child_ids(before,path);b=child_ids(after,path)
                    if len(a)!=len(b):raise CopyMismatch('Updated child cardinality changed.')
                    replace(observed,path,a)
                if expect!=observed:raise CopyMismatch('Changed resource differs beyond the declared mutation: '+changed)
                internal(after)
            target=current[copied] if phase=='duplicate' else current[changed]
            for name in (identity,route,cfg['name_field']):
                if written.get(name)!=target.get(name):raise CopyMismatch('Write response identity does not match readback.')
            # Both counterpart content and its child identities remain exact.
            for instance in (source,copied):
                if instance in prior and instance!=changed and normalized(prior[instance],[])!=normalized(current[instance],[]):raise CopyMismatch('Source/copy content leaked into its counterpart: '+instance)
            # Compare configured incoming views, refreshing only copied content
            # of embedded source UUIDs after an intentionally validated update.
            targets={current[source][identity]:current[source],current[copied][identity]:current[copied]}
            def refresh(node):
                if isinstance(node,dict):
                    match=targets.get(node.get(identity))
                    if match:
                        for name in cfg['content_fields']+['dateUpdated','updatedAt']:
                            if name in node and name in match:node[name]=copy.deepcopy(match[name])
                    for value in node.values():refresh(value)
                elif isinstance(node,list):
                    for value in node:refresh(value)
            for instance,rule in refs.items():
                if instance in (source,copied):continue
                expected=fields(prior[instance],rule['preserve_fields']);refresh(expected)
                if expected!=fields(current[instance],rule['preserve_fields']):raise CopyMismatch('Incoming references, identities or quantities changed: '+instance)
        prior=current
    return {'source_id':initial[source][identity],'copy_id':clone_initial[identity],'raw_observations':len(rows),'mutations':len(cfg['mutations'])}
