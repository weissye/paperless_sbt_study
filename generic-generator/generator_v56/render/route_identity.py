"""Opt-in route alias changes with owned identities and protected referrers."""
import hashlib
from .relationship_runtime_js import CODE

ROUTE_CODE=CODE.replace("  if(ctx.mode==='reject_link'){",r'''
  if(ctx.mode==='route_capture'){
    var evidenceRecord=read(ctx.route_variable),raw={phase:ctx.phase_index,kind:ctx.capture_kind,instance:ctx.instance,operation:ctx.operation,code:response.code,body:response.body};
    if(ctx.capture_kind==='write')raw.request_body=pvg.rtv.get(ctx.body_variable);
    if(!evidenceRecord.raw_observations)evidenceRecord.raw_observations=[];
    evidenceRecord.raw_observations.push(raw);store(ctx.route_variable,evidenceRecord);return;
  }
  if(ctx.mode==='reject_link'){''',1)
ROUTE_CODE=ROUTE_CODE.replace("  if(ctx.mode==='reject_link'){",r'''
  function routeFail(stage,expected,observed){var e={task_id:ctx.route_task,stage:stage,instance:ctx.instance,expected:expected,observed:observed};store('sbt_rel_route_failure',e);fail('Route identity mismatch: '+JSON.stringify(e));}
  if(ctx.mode==='route_old'){
    if(response.code===401||response.code===403)fail('Route authentication interrupted: '+response.code);
    var rec=read(ctx.route_variable),observed=response.code===200?JSON.parse(response.body):null,expected=ctx.expected_index?rec.ids[ctx.expected_index-1]:null;
    if(expected===null?response.code!==404:(response.code!==200||observed[ctx.identity_field]!==expected))routeFail('alias_resolution',{code:expected===null?404:200,id:expected},{code:response.code,body:observed});
    rec.alias_checks.push({phase:ctx.phase_index,code:response.code,expected_id:expected,observed_id:observed?observed[ctx.identity_field]:null});store(ctx.route_variable,rec);return;
  }
  if(ctx.mode==='route_target_after'&&response.code!==200){if(response.code===401||response.code===403)fail('Route authentication interrupted: '+response.code);routeFail('new_route_resolution',{code:200},{code:response.code,body:response.body});}
  if(ctx.mode==='reject_link'){''',1)
ROUTE_CODE=ROUTE_CODE.replace("  if(ctx.mode==='prepare_action'){",r'''
  function routeFields(value){var out={};ctx.preserve_fields.forEach(function(f){if(Object.prototype.hasOwnProperty.call(value,f))out[f]=clone(value[f]);});return out;}
  function routeView(expected,targets){function walk(o){if(!o||typeof o!=='object')return;var target=targets[o[ctx.identity_field]];if(target)([ctx.route_field,ctx.change_field].concat(ctx.timestamp_fields)).forEach(function(f){if(Object.prototype.hasOwnProperty.call(o,f)&&Object.prototype.hasOwnProperty.call(target,f))o[f]=target[f];});if(target)(ctx.recreated_identity_paths||[]).forEach(function(path){var rows=valuesAt(o,path.slice(0,-5)),current=valuesAt(target,path.slice(0,-5));if(rows.length===1&&current.length===1&&Array.isArray(rows[0])&&Array.isArray(current[0])&&rows[0].length===current[0].length)rows[0].forEach(function(row,index){row.id=current[0][index].id;});});Object.keys(o).forEach(function(k){walk(o[k]);});}walk(expected);return expected;}
  if(ctx.mode==='route_initialize')store(ctx.route_variable,{task_id:ctx.route_task,namespace:pvg.rtv.get('sbt_rel_namespace'),ids:[],initial_targets:{},targets:{},initial_routes:[],baselines:{},source_ids:{},phases:[],alias_checks:[]});
  if(ctx.mode==='route_target_before'){
    identity(ctx,body);var rec=read(ctx.route_variable),id=body[ctx.identity_field];rec.ids[ctx.index-1]=id;rec.initial_routes[ctx.index-1]=body[ctx.route_field];rec.targets[id]=clone(body);rec.initial_targets[id]=clone(body);pvg.rtv.set(ctx.initial_route_variable,encodeURIComponent(body[ctx.route_field]));store(ctx.route_variable,rec);
  }
  if(ctx.mode==='route_source_before'){
    identity(ctx,body);var rec=read(ctx.route_variable);if(ctx.reference_path&&valuesAt(body,ctx.reference_path).map(idOf).indexOf(rec.ids[0])<0)routeFail('missing_initial_reference',rec.ids[0],body);rec.baselines[ctx.instance]=routeFields(body);rec.source_ids[ctx.instance]=body[ctx.identity_field];store(ctx.route_variable,rec);
  }
  if(ctx.mode==='route_prepare'){
    identity(ctx,body);var rec=read(ctx.route_variable),expected=rec.targets[body[ctx.identity_field]];if(stable(body)!==stable(expected))routeFail('target_changed_before_write',expected,body);
    var data=project(ctx.request_schema,body,0,false),value=ctx.phase.reuse_index?rec.initial_targets[rec.ids[ctx.phase.reuse_index-1]][ctx.change_field]:rec.namespace+'-'+ctx.phase.suffix,alias=ctx.phase.reuse_index?rec.initial_routes[ctx.phase.reuse_index-1]:rec.namespace+'-'+ctx.phase.suffix;
    data[ctx.change_field]=value;rec.pending={phase:ctx.phase,before:clone(body),value:value,expected:clone(body),checks:[]};rec.pending.expected[ctx.change_field]=value;if(ctx.changes_route)rec.pending.expected[ctx.route_field]=alias;
    pvg.rtv.set(ctx.old_route_variable,encodeURIComponent(body[ctx.route_field]));pvg.rtv.set(ctx.new_route_variable,encodeURIComponent(ctx.changes_route?alias:body[ctx.route_field]));pvg.rtv.set(ctx.body_variable,JSON.stringify(project(ctx.request_schema,data,0,false)));store(ctx.route_variable,rec);
  }
  if(ctx.mode==='route_target_after'){
    var rec=read(ctx.route_variable),expected=rec.pending.expected,protectedBody=clone(body);
    if(ctx.capture_route_evidence){var writes=rec.raw_observations.filter(function(x){return x.phase===ctx.phase_index&&x.kind==='write';});if(writes.length!==1||ctx.write_success_codes.indexOf(writes[0].code)<0)routeFail('write_status',ctx.write_success_codes,writes);if(writes[0].body){var written;try{written=JSON.parse(writes[0].body);}catch(e){routeFail('invalid_write_response_json','JSON',writes[0].body);}if(written&&typeof written==='object')([ctx.identity_field,ctx.route_field,ctx.change_field]).forEach(function(f){if(Object.prototype.hasOwnProperty.call(written,f)&&written[f]!==expected[f])routeFail('write_response_identity_or_route',expected,written);});}}
    ctx.timestamp_fields.forEach(function(f){var v=body[f];if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v)||isNaN(Date.parse(v.replace(/\.(\d+)(?=Z|[+-])/,function(_,d){return '.'+(d+'000').slice(0,3);}))))routeFail('invalid_timestamp',expected,body);if(Object.prototype.hasOwnProperty.call(expected,f))protectedBody[f]=expected[f];else delete protectedBody[f];});
    rec.pending.recreated_identities=[];
    (ctx.recreated_identity_paths||[]).forEach(function(path){var arrayPath=path.slice(0,-5),oldArray=valuesAt(expected,arrayPath),newArray=valuesAt(protectedBody,arrayPath);if(oldArray.length!==1||newArray.length!==1||!Array.isArray(oldArray[0])||!Array.isArray(newArray[0])||oldArray[0].length!==newArray[0].length)routeFail('child_identity_shape',expected,body);oldArray[0].forEach(function(row,index){var oldId=row.id,newId=newArray[0][index].id;if(typeof oldId!=='string'||typeof newId!=='string'||!/^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(oldId)||!/^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.test(newId))routeFail('invalid_child_identity',expected,body);if(oldId!==newId)rec.pending.recreated_identities.push({path:path,index:index,before:oldId,after:newId});newArray[0][index].id=oldId;});if(newArray[0].length!==valuesAt(body,path).filter(function(id,index,all){return all.indexOf(id)===index;}).length)routeFail('duplicate_child_identity',expected,body);});
    if(stable(expected)!==stable(protectedBody))routeFail('updated_target_identity_or_state',expected,body);
    var previous=read(ctx.record_variable);previous[ctx.route_parameter]=body[ctx.route_field];previous[ctx.route_field]=body[ctx.route_field];store(ctx.record_variable,previous);identity(ctx,body);
    rec.targets[body[ctx.identity_field]]=clone(body);rec.pending.observed=clone(body);store(ctx.route_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='route_source_after'){
    identity(ctx,body);var rec=read(ctx.route_variable),expected=routeView(clone(rec.baselines[ctx.instance]),rec.targets),observed=routeFields(body);if(stable(expected)!==stable(observed))routeFail('reference_or_quantity_changed',expected,observed);rec.pending.checks.push({instance:ctx.instance,expected:expected,observed:observed});store(ctx.route_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='route_phase_end'){
    identity(ctx,body);var rec=read(ctx.route_variable);if(rec.pending.checks.length!==ctx.source_count)routeFail('missing_checks',ctx.source_count,rec.pending.checks);rec.phases.push(rec.pending);store(ctx.route_variable,rec);
  }
  if(ctx.mode==='route_finish'){
    var rec=read(ctx.route_variable);if(rec.phases.length!==ctx.phase_count||rec.alias_checks.length!==ctx.alias_count)routeFail('incomplete_route_receipt',ctx.phase_count,rec);var all=read('sbt_rel_route_receipts');all.push(rec);store('sbt_rel_route_receipts',all);
  }
  if(ctx.mode==='prepare_action'){''',1)
ROUTE_CODE=ROUTE_CODE.replace("store('sbt_rel_owned',[]);","store('sbt_rel_owned',[]);store('sbt_rel_route_receipts',[]);",1)
ROUTE_CODE=ROUTE_CODE.replace("store('sbt_rel_execution_receipt',receipt);","if(ctx.expected_route_tasks){var routeRecords=read('sbt_rel_route_receipts');if(routeRecords.length!==ctx.expected_route_tasks.length)fail('Missing route receipts');receipt.route_identities=routeRecords;}store('sbt_rel_execution_receipt',receipt);",1)


def append_route_identity(blueprint,info,entities,cfg,add_request,request_schema,response_schema,property_schema,root):
    required={'resource_type','operation','route_field','identity_field','timestamp_fields','mode','control_field','source_link','referrers'}
    if not isinstance(cfg,dict) or set(cfg)-{'recreated_identity_paths','route_driver_field','capture_route_evidence'}!=required or cfg['mode'] not in ('control','rename','reuse'):raise ValueError('Invalid explicit route identity policy.')
    capture=cfg.get('capture_route_evidence',False)
    if not isinstance(capture,bool):raise ValueError('Capture route evidence must be boolean.')
    typ=cfg['resource_type'];targets=blueprint['instances'].get(typ,[])
    if len(targets)!=3:raise ValueError('Route testing requires three owned targets.')
    op=cfg['operation'];getter=entities[typ].get_op.op;get=getter.method+' '+getter.path
    if not op.startswith(('PUT ','PATCH ')) or op not in [o.op.method+' '+o.op.path for o in entities[typ].ops]:raise ValueError('Route write belongs to another resource.')
    field=cfg['route_field'];identity=cfg['identity_field']
    if field==identity:raise ValueError('Stable identity and route alias must differ.')
    route=[f for f in info[targets[0]]['route_fields'] if f['response_field']==field]
    if len(route)!=1:raise ValueError('Changed field must be a documented route binding.')
    parameter=route[0]['parameter']
    driver=cfg.get('route_driver_field',field)
    driver_schema=root(property_schema(request_schema(op),driver,writable=True));driver_nodes=[root(x) for x in driver_schema.get('anyOf',[driver_schema]) if root(x).get('type')!='null']
    if driver==identity or len(driver_nodes)!=1 or driver_nodes[0].get('type')!='string':raise ValueError('Route driver must be a writable string distinct from stable identity.')
    property_schema(response_schema(get),driver)
    recreated=cfg.get('recreated_identity_paths',[])
    if not isinstance(recreated,list) or len(set(recreated))!=len(recreated):raise ValueError('Invalid recreated identity paths.')
    for path in recreated:
        if not isinstance(path,str) or path.count('[]')!=1 or not path.endswith('[].id'):raise ValueError('Recreated identity must be an explicit child array UUID ID.')
        array=root(property_schema(response_schema(get),path[:-5]));array_nodes=[root(x) for x in array.get('anyOf',[array]) if root(x).get('type')!='null']
        if len(array_nodes)!=1 or array_nodes[0].get('type')!='array':raise ValueError('Recreated identity requires a documented child array.')
        schema=root(property_schema(array_nodes[0].get('items',{}),'id'));branches=schema.get('anyOf',[schema]);nodes=[root(x) for x in branches if root(x).get('type')!='null']
        if len(nodes)!=1 or nodes[0].get('format')!='uuid':raise ValueError('Recreated identity must be a documented UUID.')
    if root(property_schema(request_schema(op),field,writable=True)).get('type')!='string':raise ValueError('Route field must be writable string.')
    property_schema(response_schema(get),identity)
    times=cfg['timestamp_fields']
    if not isinstance(times,list) or len(set(times))!=len(times):raise ValueError('Invalid update timestamp fields.')
    for f in times:
        if f not in ('dateUpdated','updatedAt','updated_at'):raise ValueError('Only update timestamps may vary.')
        schema=root(property_schema(response_schema(get),f));branches=schema.get('anyOf',[schema]);nodes=[root(x) for x in branches if root(x).get('type')!='null']
        if len(nodes)!=1 or nodes[0].get('format')!='date-time':raise ValueError('Timestamp must be documented date-time.')
    link=cfg['source_link']
    if set(link)!={'source_index','target_index','field_path'} or link['source_index']!=2 or link['target_index']!=1:raise ValueError('Explicit acyclic owned link R2 to R1 required.')
    property_schema(request_schema(op),link['field_path'],writable=True)
    refs=[]
    for rule in cfg['referrers']:
        if set(rule)!={'resource_type','preserve_fields','reference_path'} or rule['resource_type'] not in blueprint['instances']:raise ValueError('Invalid route referrer policy.')
        ep=entities[rule['resource_type']];readop=ep.get_op.op.method+' '+ep.get_op.op.path
        for f in rule['preserve_fields']:property_schema(response_schema(readop),f)
        property_schema(response_schema(readop),rule['reference_path'])
        for instance in blueprint['instances'][rule['resource_type']]:refs.append(dict(rule,instance=instance,operation=readop))
    if len({r['resource_type'] for r in refs})<2:raise ValueError('Two referrer families required.')
    task_id='route-identity:'+typ;variable='rel_route_test_'+hashlib.sha256(task_id.encode()).hexdigest()[:12]
    common={'route_task':task_id,'route_variable':variable,'route_field':field,'identity_field':identity,'timestamp_fields':times,'recreated_identity_paths':recreated,'route_parameter':parameter,'changes_route':cfg['mode']!='control','change_field':cfg['control_field'] if cfg['mode']=='control' else driver}
    def ctx(instance,mode,**extra):return dict(info[instance],mode=mode,**common,**extra)
    steps=[]
    # Establish an acyclic source reference after generic prefix construction.
    body=variable+'_body';expect=variable+'_link'
    steps += [add_request(get,dict(info[targets[1]],mode='prepare_link',request_schema=request_schema(op),field_path=link['field_path'],targets=[info[targets[0]]['snapshot_variable']],body_variable=body,expectation_variable=expect,defaults=[]),targets[1]),add_request(op,{'mode':'write'},targets[1],body),add_request(get,dict(info[targets[1]],mode='verify_link',field_path=link['field_path'],expectation_variable=expect),targets[1])]
    steps.append(add_request(get,ctx(targets[0],'route_initialize'),targets[0]))
    for i,target in enumerate(targets):steps.append(add_request(get,ctx(target,'route_target_before',index=i+1,initial_route_variable=variable+'_initial_'+str(i+1)),target))
    for r in refs:
        refers=(r['instance']==targets[1]) if r['resource_type']==typ else any(t['kind']=='qualified_action' and t['source_instance']==r['instance'] and targets[0] in t['target_instances'] for t in blueprint['tasks'])
        r['requires_reference']=refers
        reference=r['reference_path'] if refers else None
        steps.append(add_request(r['operation'],ctx(r['instance'],'route_source_before',preserve_fields=r['preserve_fields'],reference_path=reference),r['instance']))
    phases=[{'target_index':1,'suffix':'route-first'},{'target_index':3,'reuse_index':1}] if cfg['mode']=='reuse' else [{'target_index':1,'suffix':'route-first'},{'target_index':1,'suffix':'route-second'}]
    change=cfg['control_field'] if cfg['mode']=='control' else driver
    if cfg['control_field'] in (field,identity):raise ValueError('Control field must not change route or stable identity.')
    property_schema(request_schema(op),cfg['control_field'],writable=True)
    for i,phase in enumerate(phases):
        target=targets[phase['target_index']-1];oldvar=variable+'_old';newvar=variable+'_new'
        steps.append(add_request(get,ctx(target,'route_prepare',phase=phase,request_schema=request_schema(op),old_route_variable=oldvar,new_route_variable=newvar,body_variable=body),target))
        if capture:
            success_codes=[int(r.status) for o in entities[typ].ops if o.op.method+' '+o.op.path==op for r in o.op.success_responses]
            steps.append(add_request(op,ctx(target,'route_capture',phase_index=i,capture_kind='write',body_variable=body,absence_codes=list(range(200,600))),target,body))
            for kind,variable_name in [('old_route',oldvar),('new_route',newvar)]:
                steps.append(add_request(get,ctx(target,'route_capture',phase_index=i,capture_kind=kind,absence_codes=list(range(200,600))),target,route_override={parameter:'@{'+variable_name+'}'}))
            for r in refs:
                steps.append(add_request(r['operation'],ctx(r['instance'],'route_capture',phase_index=i,capture_kind='referrer',absence_codes=list(range(200,600))),r['instance'],route_override={parameter:'@{'+newvar+'}'} if r['instance']==target else None))
        else:
            steps.append(add_request(op,{'mode':'write'},target,body))
        after_ctx=ctx(target,'route_target_after',absence_codes=list(range(200,600)))
        if capture:after_ctx.update(capture_route_evidence=True,phase_index=i,write_success_codes=success_codes)
        steps.append(add_request(get,after_ctx,target,route_override={parameter:'@{'+newvar+'}'}))
        steps.append(add_request(get,ctx(target,'route_old',phase_index=i,expected_index=phase['target_index'] if cfg['mode']=='control' else None,absence_codes=list(range(200,600))),target,route_override={parameter:'@{'+oldvar+'}'}))
        for r in refs:steps.append(add_request(r['operation'],ctx(r['instance'],'route_source_after',preserve_fields=r['preserve_fields']),r['instance']))
        steps.append(add_request(get,ctx(target,'route_phase_end',source_count=len(refs)),target))
    if cfg['mode']=='reuse':steps.append(add_request(get,ctx(targets[2],'route_old',phase_index=2,expected_index=3,absence_codes=list(range(200,600))),targets[2],route_override={parameter:'@{'+variable+'_initial_1}'}))
    steps.append(add_request(get,ctx(targets[0],'route_finish',phase_count=2,alias_count=3 if cfg['mode']=='reuse' else 2,task_id=task_id),targets[0]))
    blueprint['tasks'].append({'id':task_id,'kind':'route_identity','source_instance':targets[0],'target_instances':[], 'operation':op,'after':[t['id'] for t in blueprint['tasks']],'executable':True,'config':cfg,'targets':targets,'referrers':refs,'phases':phases,'change_field':change})
    if capture:blueprint['tasks'][-1]['write_success_codes']=success_codes
    return {task_id:steps}
