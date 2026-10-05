"""Opt-in dependency transfer with target updates between binding operations."""
import hashlib
from .relationship_runtime_js import CODE

TRANSFER_CODE = CODE.replace("  if(ctx.mode==='prepare_action'){", r'''
  function transferFail(stage,expected,observed){var evidence={task_id:ctx.transfer_task,phase:ctx.phase,stage:stage,instance:ctx.instance,expected:expected,observed:observed};store('sbt_rel_transfer_failure',evidence);fail('Dependency transfer mismatch: '+JSON.stringify(evidence));}
  function transferWalk(object,path,visit){var parts=segments(path);function walk(o,at){if(!o||typeof o!=='object')return;var p=parts[at];if(p.array){(o[p.name]||[]).forEach(function(v){walk(v,at+1);});}else if(at===parts.length-1)visit(o,p.name);else walk(o[p.name],at+1);}walk(object,0);}
  function transferFields(body){var data=project(ctx.source_schema,body,0,false),out={};ctx.protected_fields.forEach(function(f){out[f]=clone(data[f]);});ctx.derived_fields.forEach(function(f){transferWalk(out,f,function(o,k){delete o[k];});});return out;}
  function transferExpected(rec,instance){var expected=clone(rec.baselines[instance]);var current=rec.assignments[instance],oldId=rec.target_ids[0];transferWalk(expected,ctx.field_path,function(o,k){var id=idOf(o[k]);if(id===oldId)id=rec.target_ids[current-1];if(id!==undefined&&id!==null){if(!rec.templates[id])transferFail('unknown_dependency',rec.target_ids,id);o[k]=clone(rec.templates[id]);}});return expected;}
  if(ctx.mode==='transfer_target_before'){
    identity(ctx,body);var rec=read(ctx.transfer_variable);rec.target_ids[ctx.target_index-1]=idOf(body);rec.targets[idOf(body)]=clone(body);rec.initial_targets[idOf(body)]=clone(body);store(ctx.transfer_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='transfer_source_before'){
    identity(ctx,body);var rec=read(ctx.transfer_variable),before=transferFields(body);rec.baselines[ctx.instance]=before;rec.assignments[ctx.instance]=1;
    transferWalk(before,ctx.field_path,function(o,k){var id=idOf(o[k]);if(id!==undefined&&id!==null){if(rec.target_ids.indexOf(id)<0)transferFail('unowned_baseline_dependency',rec.target_ids,id);if(rec.templates[id]&&stable(rec.templates[id])!==stable(o[k]))transferFail('inconsistent_initial_views',rec.templates[id],o[k]);rec.templates[id]=clone(o[k]);rec.initial_templates[id]=clone(o[k]);}});
    rec.source_ids[ctx.instance]=idOf(body);store(ctx.transfer_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='transfer_prepare'){
    identity(ctx,body);var rec=read(ctx.transfer_variable),data=project(ctx.request_schema,body,0,false);
    if(ctx.phase.kind==='update'){var id=rec.target_ids[ctx.phase.target_index-1];if(stable(body)!==stable(rec.targets[id]))transferFail('target_changed_before_update',rec.targets[id],body);var value=pvg.rtv.get('sbt_rel_namespace')+'-'+ctx.phase.value;data[ctx.target_field]=value;rec.pending={phase:ctx.phase,expected_target:clone(body),value:value};rec.pending.expected_target[ctx.target_field]=value;}
    else {var expected=transferExpected(rec,ctx.instance);if(stable(transferFields(body))!==stable(expected))transferFail('source_changed_before_rebind',expected,transferFields(body));rec.pending={phase:ctx.phase};var replacement=rec.templates[rec.target_ids[ctx.phase.target_index-1]],baseline=rec.baselines[ctx.instance],slots=[];transferWalk(baseline,ctx.field_path,function(o,k){slots.push(idOf(o[k])===rec.target_ids[0]);});var pos=0;transferWalk(data,ctx.field_path,function(o,k){if(slots[pos++])o[k]=clone(replacement);});}
    data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));store(ctx.transfer_variable,rec);
  }
  if(ctx.mode==='transfer_target_after'){
    identity(ctx,body);var rec=read(ctx.transfer_variable),id=idOf(body),expected=rec.pending.expected_target,protectedBody=clone(body);(ctx.target_timestamp_fields||[]).forEach(function(f){if(typeof body[f]!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(body[f])||isNaN(Date.parse(body[f].replace(/\.(\d+)(?=Z|[+-])/,function(_,digits){return '.'+(digits+'000').slice(0,3);}))))transferFail('invalid_update_timestamp',expected,body);if(Object.prototype.hasOwnProperty.call(expected,f))protectedBody[f]=expected[f];else delete protectedBody[f];});if(stable(protectedBody)!==stable(expected))transferFail('target_update',expected,body);
    rec.targets[id]=clone(body);rec.templates[id][ctx.target_field]=rec.pending.value;(ctx.target_timestamp_fields||[]).forEach(function(f){if(Object.prototype.hasOwnProperty.call(rec.templates[id],f))rec.templates[id][f]=body[f];});rec.pending.observed_target=clone(body);store(ctx.transfer_variable,rec);
  }
  if(ctx.mode==='transfer_phase_begin'){
    var rec=read(ctx.transfer_variable);if(ctx.phase.kind==='rebind')rec.assignments[ctx.phase.source]=ctx.phase.target_index;rec.pending.checks=[];store(ctx.transfer_variable,rec);
  }
  if(ctx.mode==='transfer_source_after'){
    identity(ctx,body);var rec=read(ctx.transfer_variable),expected=transferExpected(rec,ctx.instance),observed=transferFields(body);if(stable(expected)!==stable(observed))transferFail('source_or_dependency_view',expected,observed);rec.pending.checks.push({instance:ctx.instance,expected:expected,observed:observed});store(ctx.transfer_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='transfer_target_check'){
    identity(ctx,body);var rec=read(ctx.transfer_variable),expected=rec.targets[idOf(body)];if(stable(expected)!==stable(body))transferFail('unrelated_target_changed',expected,body);
    if(ctx.last){if(rec.pending.checks.length!==ctx.source_count)fail('Missing dependency transfer checks');rec.phases.push(rec.pending);store(ctx.transfer_variable,rec);}
  }
  if(ctx.mode==='transfer_finish'){
    var rec=read(ctx.transfer_variable);if(rec.phases.length!==ctx.phase_count)fail('Incomplete dependency transfer phases');var records=read('sbt_rel_transfer_receipts');records.push(rec);store('sbt_rel_transfer_receipts',records);
  }
  if(ctx.mode==='prepare_action'){''',1)
TRANSFER_CODE=TRANSFER_CODE.replace("store('sbt_rel_owned',[]);","store('sbt_rel_owned',[]);store('sbt_rel_transfer_receipts',[]);",1)
TRANSFER_CODE=TRANSFER_CODE.replace("store('sbt_rel_execution_receipt',receipt);","if(ctx.expected_transfer_tasks){var records=read('sbt_rel_transfer_receipts');if(records.length!==ctx.expected_transfer_tasks.length)fail('Missing transfer receipts');receipt.dependency_transfers=records;}store('sbt_rel_execution_receipt',receipt);",1)
# Initialize state after response parsing, before the first target read handler.
TRANSFER_CODE=TRANSFER_CODE.replace("  if(ctx.mode==='transfer_target_before'){","  if(ctx.mode==='transfer_initialize'){store(ctx.transfer_variable,{task_id:ctx.transfer_task,namespace:pvg.rtv.get('sbt_rel_namespace'),target_ids:[],targets:{},initial_targets:{},templates:{},initial_templates:{},baselines:{},source_ids:{},assignments:{},phases:[]});}\n  if(ctx.mode==='transfer_target_before'){",1)


def append_dependency_transfer(blueprint,info,entities,config,add_request,request_schema,response_schema,property_schema,root,embedded_string_view):
    required={'target_type','source_type','target_operation','source_operation','field_path','target_field','preserve_fields','derived_fields','phases'}
    if not isinstance(config,dict) or not required.issubset(config) or set(config)-required-{'target_timestamp_fields'}:raise ValueError('Dependency transfer requires a complete explicit configuration.')
    target_type=config['target_type'];source_type=config['source_type']
    if target_type==source_type or any(t not in blueprint['instances'] or len(blueprint['instances'][t])!=3 for t in (target_type,source_type)):raise ValueError('Transfer requires three owned sources and three distinct targets.')
    def getter(t):
        op=entities[t].get_op.op;return op.method+' '+op.path
    for typ,key in [(target_type,'target_operation'),(source_type,'source_operation')]:
        op=config[key]
        if not isinstance(op,str) or not op.startswith(('PUT ','PATCH ')) or op not in [o.op.method+' '+o.op.path for o in entities[typ].ops]:raise ValueError('Transfer update operation belongs to a different resource.')
    field=config['target_field']
    if not isinstance(field,str) or '.' in field or field in ('id','slug'):raise ValueError('Transfer requires a non-identity descriptive field.')
    if any(field==route['response_field'] for instance in blueprint['instances'][target_type] for route in info[instance]['route_fields']):raise ValueError('Transfer may not update a route identity.')
    for schema in [request_schema(config['target_operation']),response_schema(getter(target_type))]:
        node=root(property_schema(schema,field,writable=schema is not None))
        if node.get('type')!='string':raise ValueError('Transfer target field must be a documented string.')
    timestamps=config.get('target_timestamp_fields',[])
    if not isinstance(timestamps,list) or len(set(timestamps))!=len(timestamps):raise ValueError('Timestamp fields must be a distinct list.')
    for timestamp in timestamps:
        if timestamp not in ('updatedAt','dateUpdated','updated_at','updated'):raise ValueError('Only explicit update timestamps may vary.')
        node=root(property_schema(response_schema(getter(target_type)),timestamp))
        variants=node.get('anyOf',node.get('oneOf',[node]));nonnull=[root(n) for n in variants if root(n).get('type')!='null']
        if len(nonnull)!=1 or nonnull[0].get('type')!='string' or nonnull[0].get('format')!='date-time':raise ValueError('Update timestamp must be documented as date-time.')
    sources=blueprint['instances'][source_type];targets=blueprint['instances'][target_type];path=config['field_path'];protected=config['preserve_fields'];derived=config['derived_fields']
    source_schema=request_schema(config['source_operation'])
    property_schema(source_schema,path,writable=True)
    if not embedded_string_view(response_schema(getter(source_type)),path+'.'+field):raise ValueError('Transfer requires a documented embedded string view.')
    if not isinstance(protected,list) or not protected or path.split('.')[0].replace('[]','') not in protected:raise ValueError('Transfer protected fields must include dependency container.')
    for f in protected:
        if not isinstance(f,str) or '.' in f or '[]' in f:raise ValueError('Transfer protected fields must be top-level.')
        property_schema(source_schema,f,writable=True)
    if not isinstance(derived,list) or any(not isinstance(f,str) or not f.startswith(path.rsplit('.',1)[0]+'.') or f.split('.')[-1] in ('id','quantity','food','unit','referenceId','note') for f in derived):raise ValueError('Transfer derived exclusions may not hide identities or quantities.')
    for f in derived:property_schema(source_schema,f,writable=True)
    links=[t for t in blueprint['tasks'] if t['kind']=='link' and t['field_path']==path and not t.get('lifecycle_phase')]
    for s,expected in zip(sources,([targets[0],targets[1]],[targets[0],targets[1]],[targets[2],targets[2]])):
        found=[t for t in links if t['source_instance']==s]
        if len(found)!=1 or found[0]['target_instances']!=expected or found[0]['operation']!=config['source_operation']:raise ValueError('Transfer baseline must be A/B, A/B and C/C.')
    phases=config['phases']
    if not isinstance(phases,list) or not phases or len(phases)>12:raise ValueError('Transfer requires one to twelve explicit phases.')
    for phase in phases:
        if not isinstance(phase,dict) or phase.get('kind') not in ('update','rebind'):raise ValueError('Unknown transfer phase.')
        if type(phase.get('target_index')) is not int or phase['target_index'] not in (1,2):raise ValueError('Only A/B targets may be changed; C is a protected control.')
        if phase['kind']=='update':
            if set(phase)!={'kind','target_index','value'} or not isinstance(phase['value'],str) or not phase['value']:raise ValueError('Transfer update requires a value suffix.')
        elif set(phase)!={'kind','target_index','source_index'} or type(phase['source_index']) is not int or phase['source_index'] not in (1,2):raise ValueError('Only sources one and two may be rebound.')
    task_id='dependency-transfer:'+target_type;variable='rel_transfer_'+hashlib.sha256(task_id.encode()).hexdigest()[:16]
    common={'transfer_variable':variable,'transfer_task':task_id,'field_path':path,'target_field':field,'source_schema':source_schema,'protected_fields':protected,'derived_fields':derived,'target_timestamp_fields':timestamps}
    def ctx(instance,mode,**extra):return dict(info[instance],mode=mode,**common,**extra)
    steps=[add_request(getter(target_type),ctx(targets[0],'transfer_initialize'),targets[0])]
    for index,s in enumerate(targets):steps.append(add_request(getter(target_type),ctx(s,'transfer_target_before',target_index=index+1),s))
    for s in sources:steps.append(add_request(getter(source_type),ctx(s,'transfer_source_before'),s))
    compiled=[]
    for index,phase in enumerate(phases):
        p=dict(phase)
        if phase['kind']=='rebind':p['source']=sources[p.pop('source_index')-1]
        compiled.append(p);s=targets[p['target_index']-1] if p['kind']=='update' else p['source'];typ=target_type if p['kind']=='update' else source_type
        operation=config['target_operation'] if p['kind']=='update' else config['source_operation'];body=variable+'_body'
        steps.append(add_request(getter(typ),ctx(s,'transfer_prepare',phase=p,request_schema=request_schema(operation),body_variable=body),s))
        steps.append(add_request(operation,{'mode':'write'},s,body))
        if p['kind']=='update':steps.append(add_request(getter(typ),ctx(s,'transfer_target_after',phase=p),s))
        steps.append(add_request(getter(source_type),ctx(sources[0],'transfer_phase_begin',phase=p),sources[0]))
        for source in sources:steps.append(add_request(getter(source_type),ctx(source,'transfer_source_after',phase=p),source))
        for pos,target in enumerate(targets):steps.append(add_request(getter(target_type),ctx(target,'transfer_target_check',phase=p,last=pos==2,source_count=len(sources)),target))
    steps.append(add_request(getter(target_type),ctx(targets[2],'transfer_finish',phase_count=len(phases),task_id=task_id),targets[2]))
    task={'id':task_id,'kind':'dependency_transfer','source_instance':targets[0],'target_instances':[], 'operation':config['source_operation'],'after':[t['id'] for t in blueprint['tasks']], 'executable':True,'config':config,'sources':sources,'targets':targets,'phases':compiled}
    blueprint['tasks'].append(task)
    return {task_id:steps}
