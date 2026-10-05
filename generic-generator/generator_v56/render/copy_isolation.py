"""Explicit, contract-checked copy operations; semantic qualification is independent."""
import copy
import hashlib
from .relationship_runtime_js import CODE

COPY_CODE = CODE.replace("  if(ctx.mode==='reject_link'){", r'''
  if(ctx.mode==='copy_observe'||ctx.mode==='copy_bind'){
    var record=read(ctx.copy_variable),entry={phase:ctx.phase,kind:ctx.kind,instance:ctx.instance,operation:ctx.operation,code:response.code,body:response.body};
    if(ctx.body_variable)entry.request_body=pvg.rtv.get(ctx.body_variable);
    record.observations.push(entry);store(ctx.copy_variable,record);
    if(ctx.mode==='copy_bind'){
      if(ctx.success_codes.indexOf(response.code)<0)fail('Copy operation did not return a documented success; raw evidence retained');
      var copied;try{copied=JSON.parse(response.body);project(ctx.response_schema,copied,0,false);}catch(e){fail('Copy response cannot bind an identity: '+e.message);}
      identity(ctx,copied);store(ctx.snapshot_variable,copied);var owned=read('sbt_rel_owned');owned.push({instance:ctx.instance,resource:ctx.resource,route:read(ctx.record_variable)});store('sbt_rel_owned',owned);
    }
    return;
  }
  if(ctx.mode==='reject_link'){''', 1).replace("  if(ctx.mode==='prepare_action'){", r'''
  function copySet(data,path,value){var parts=segments(path),count=0;function walk(node,at){var part=parts[at];if(!node||typeof node!=='object'||!Object.prototype.hasOwnProperty.call(node,part.name))fail('Copy mutation path missing: '+path);if(at===parts.length-1){if(part.array)fail('Copy scalar mutation expected');node[part.name]=value;count++;return;}var next=node[part.name];if(part.array){if(!Array.isArray(next)||!next.length)fail('Copy mutation array missing: '+path);next.forEach(function(child){walk(child,at+1);});}else walk(next,at+1);}walk(data,0);if(!count)fail('Copy mutation did not address a value');}
  if(ctx.mode==='copy_initialize')store(ctx.copy_variable,{task_id:ctx.copy_task,observations:[]});
  if(ctx.mode==='copy_seed'){
    identity(ctx,body);var data=project(ctx.request_schema,body,0,false),seed=clone(ctx.seed);
    if(ctx.internal_reference){var ids=valuesAt(body,ctx.internal_reference.target_path);if(!ids.length)fail('No source child identity to seed');setPath(seed,ctx.seed_schema,ctx.internal_reference.seed_path,[ids[0]],0);}
    data[ctx.seed_field]=[seed];pvg.rtv.set(ctx.body_variable,JSON.stringify(project(ctx.request_schema,data,0,false)));
  }
  if(ctx.mode==='copy_prepare'){
    identity(ctx,body);var data=project(ctx.request_schema,body,0,false),value=pvg.rtv.get('sbt_rel_namespace')+'-'+ctx.suffix;
    copySet(data,ctx.path,value);pvg.rtv.set(ctx.body_variable,JSON.stringify(project(ctx.request_schema,data,0,false)));
  }
  if(ctx.mode==='copy_prepare_duplicate'){
    identity(ctx,body);var data={};data[ctx.name_field]=pvg.rtv.get('sbt_rel_namespace')+'-independent-copy';pvg.rtv.set(ctx.body_variable,JSON.stringify(project(ctx.request_schema,data,0,false)));
  }
  if(ctx.mode==='copy_finish'){var records=read('sbt_rel_copy_receipts');records.push(read(ctx.copy_variable));store('sbt_rel_copy_receipts',records);}
  if(ctx.mode==='prepare_action'){''',1).replace("store('sbt_rel_owned',[]);", "store('sbt_rel_owned',[]);store('sbt_rel_copy_receipts',[]);",1).replace("store('sbt_rel_execution_receipt',receipt);", "if(ctx.expected_copy_tasks){var copies=read('sbt_rel_copy_receipts');if(copies.length!==ctx.expected_copy_tasks.length)fail('Incomplete copy evidence');receipt.copy_isolations=copies;}store('sbt_rel_execution_receipt',receipt);",1)


def append_copy_isolation(blueprint, info, entities, cfg, add_request, request_schema, response_schema, property_schema, root):
    keys={'resource_type','copy_operation','write_operation','identity_field','route_field','name_field','content_fields','fresh_child_paths','recreated_write_paths','derived_paths','source_links','referrers','seed_field','seed','internal_reference','mutations'}
    if not isinstance(cfg,dict) or set(cfg)!=keys: raise ValueError('Invalid explicit copy isolation policy.')
    typ=cfg['resource_type']; originals=list(blueprint['instances'].get(typ,[]))
    if len(originals)!=3: raise ValueError('Copy isolation requires three owned source resources.')
    get=entities[typ].get_op.op; getter=get.method+' '+get.path; write=cfg['write_operation']; duplicate=cfg['copy_operation']
    if not write.startswith(('PUT ','PATCH ')) or not duplicate.startswith('POST '): raise ValueError('Copy and update methods must be explicit.')
    rs=request_schema(write); ds=request_schema(duplicate); result=response_schema(duplicate)
    original_property=property_schema
    def property_schema(node,path,writable=False):
        for segment in path.split('.'):
            node=root(node); branches=node.get('anyOf',node.get('oneOf',[node])); nonnull=[root(b) for b in branches if root(b).get('type')!='null']
            if len(nonnull)!=1:raise ValueError('Ambiguous copy schema: '+path)
            node=original_property(nonnull[0],segment.removesuffix('[]'),writable=writable)
            if segment.endswith('[]'):
                node=root(node); branches=node.get('anyOf',node.get('oneOf',[node])); nonnull=[root(b) for b in branches if root(b).get('type')!='null']
                if len(nonnull)!=1 or nonnull[0].get('type')!='array':raise ValueError('Invalid copy array: '+path)
                node=nonnull[0]['items']
        return root(node)

    for field in (cfg['identity_field'],cfg['route_field']):
        property_schema(result,field);property_schema(response_schema(getter),field)
    if cfg['identity_field']==cfg['route_field']: raise ValueError('Copy needs distinct stable identity and route alias.')
    if root(property_schema(ds,cfg['name_field'],writable=True)).get('type') not in ('string',None): raise ValueError('Copy name must be a writable string.')
    for field in cfg['content_fields']: property_schema(response_schema(getter),field);property_schema(result,field)
    for path in cfg['fresh_child_paths']+cfg['recreated_write_paths']:
        node=root(property_schema(response_schema(getter),path)); branches=node.get('anyOf',[node]);nodes=[root(b) for b in branches if root(b).get('type')!='null']
        if len(nodes)!=1 or not str(nodes[0].get('format','')).startswith('uuid') or path.count('[]')!=1: raise ValueError('Child identity policy requires a documented array UUID.')
    if not cfg['fresh_child_paths'] or set(cfg['recreated_write_paths'])-set(cfg['fresh_child_paths']): raise ValueError('Invalid child identity policy.')
    for path in cfg['derived_paths']:
        node=root(property_schema(response_schema(getter),path));nodes=[root(x) for x in node.get('anyOf',[node]) if root(x).get('type')!='null']
        if path in cfg['fresh_child_paths'] or 'id' in path.split('.')[-1].lower() or len(nodes)!=1 or nodes[0].get('type')!='string':raise ValueError('Derived exclusions cannot suppress identities or non-string state.')

    seed_node=root(property_schema(rs,cfg['seed_field'],writable=True)); seed_nodes=[root(x) for x in seed_node.get('anyOf',[seed_node]) if root(x).get('type')!='null']
    if len(seed_nodes)!=1 or seed_nodes[0].get('type')!='array': raise ValueError('Seed requires a documented array.')
    seed_schema=seed_nodes[0]['items']
    internal=cfg['internal_reference']
    if internal:
        if set(internal)!={'target_path','reference_path','seed_path'} or internal['target_path'] not in cfg['fresh_child_paths']: raise ValueError('Invalid internal reference policy.')
        property_schema(response_schema(getter),internal['reference_path']);property_schema(seed_schema,internal['seed_path'],writable=True)
    for mutation in cfg['mutations']:
        if set(mutation)!={'side','path','suffix'} or mutation['side'] not in ('source','copy'): raise ValueError('Invalid copy mutation.')
        node=root(property_schema(rs,mutation['path'],writable=True)); nodes=[root(x) for x in node.get('anyOf',[node]) if root(x).get('type')!='null']
        if len(nodes)!=1 or nodes[0].get('type')!='string' or mutation['path'].split('.')[0] in (cfg['identity_field'],cfg['route_field'],cfg['name_field']) or mutation['path'].split('.')[0].removesuffix('[]') not in cfg['content_fields']: raise ValueError('Copy mutation must be a writable non-routing string.')
    source=originals[0]; copied=typ+'#copy'; meta=copy.deepcopy(info[source]);meta['instance']=copied
    for key in ('record_variable','snapshot_variable'):meta[key]='rel_copy_'+hashlib.sha256((copied+key).encode()).hexdigest()[:16]
    for field in meta['route_fields']: field['variable']='rel_copy_route_'+hashlib.sha256((copied+field['parameter']).encode()).hexdigest()[:16]
    info[copied]=meta;blueprint['instances'][typ].append(copied)
    task='copy-isolation:'+typ;variable='rel_copy_test_'+hashlib.sha256(task.encode()).hexdigest()[:12];body=variable+'_body';steps=[]
    common={'copy_task':task,'copy_variable':variable}
    def ctx(instance,mode,**extra):return dict(info[instance],mode=mode,**common,**extra)
    steps.append(add_request(getter,ctx(source,'copy_initialize'),source))
    for link in cfg['source_links']:
        if set(link)!={'source_index','target_index','field_path'} or link['source_index'] not in (1,2) or link['target_index'] not in (1,3) or link['source_index']==link['target_index']:raise ValueError('Invalid acyclic copy source link.')
        a=originals[link['source_index']-1];b=originals[link['target_index']-1];property_schema(rs,link['field_path'],writable=True);expect=variable+'_link'
        steps.extend([add_request(getter,dict(info[a],mode='prepare_link',request_schema=rs,field_path=link['field_path'],targets=[info[b]['snapshot_variable']],body_variable=body,expectation_variable=expect,defaults=[]),a),add_request(write,{'mode':'write'},a,body),add_request(getter,dict(info[a],mode='verify_link',field_path=link['field_path'],expectation_variable=expect),a)])
    steps.append(add_request(getter,ctx(source,'copy_seed',seed=cfg['seed'],seed_field=cfg['seed_field'],seed_schema=seed_schema,internal_reference=internal,request_schema=rs,body_variable=body),source))
    steps.append(add_request(write,{'mode':'write'},source,body))
    refs=[]
    for rule in cfg['referrers']:
        if set(rule)!={'resource_type','preserve_fields','reference_path'} or rule['resource_type'] not in blueprint['instances']:raise ValueError('Invalid copy referrer.')
        ep=entities[rule['resource_type']];op=ep.get_op.op.method+' '+ep.get_op.op.path
        for f in rule['preserve_fields']:property_schema(response_schema(op),f)
        property_schema(response_schema(op),rule['reference_path'])
        for instance in blueprint['instances'][rule['resource_type']]:
            if instance!=copied:refs.append(dict(rule,instance=instance,operation=op))
    def observe(phase):
        for instance in [source,copied]+[r['instance'] for r in refs if r['instance'] not in (source,copied)]:
            if phase=='before' and instance==copied:continue
            op=getter if instance in originals+[copied] else next(r['operation'] for r in refs if r['instance']==instance)
            steps.append(add_request(op,ctx(instance,'copy_observe',phase=phase,kind='read',absence_codes=list(range(200,600))),instance))
    observe('before')
    steps.append(add_request(getter,ctx(source,'copy_prepare_duplicate',name_field=cfg['name_field'],request_schema=ds,body_variable=body),source))
    # The route belongs to the original; the callback binds the returned copy.
    codes=[int(code) for code in result_codes(duplicate,entities,typ)]
    if not codes: raise ValueError('Copy success codes must be documented on the selected resource.')
    steps.append(add_request(duplicate,ctx(copied,'copy_bind',phase='duplicate',kind='write',body_variable=body,response_schema=result,success_codes=codes,absence_codes=list(range(200,600))),source,body))
    observe('duplicate')
    for i,mutation in enumerate(cfg['mutations']):
        instance=source if mutation['side']=='source' else copied;phase='mutation-'+str(i)
        steps.append(add_request(getter,ctx(instance,'copy_prepare',request_schema=rs,body_variable=body,path=mutation['path'],suffix=mutation['suffix']),instance))
        steps.append(add_request(write,ctx(instance,'copy_observe',phase=phase,kind='write',body_variable=body,absence_codes=list(range(200,600))),instance,body));observe(phase)
    steps.append(add_request(getter,ctx(source,'copy_finish',task_id=task),source))
    blueprint['tasks'].append({'id':task,'kind':'copy_isolation','source_instance':source,'copy_instance':copied,'target_instances':[],'after':[t['id'] for t in blueprint['tasks']],'operation':duplicate,'config':cfg,'referrers':refs,'originals':originals,'copy_success_codes':codes,'write_success_codes':[int(x) for x in result_codes(write,entities,typ)],'executable':True})
    return {task:steps}


def result_codes(operation,entities,typ):
    return [str(r.status) for o in entities[typ].ops if o.op.method+' '+o.op.path==operation for r in o.op.success_responses]
