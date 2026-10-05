"""Opt-in, contract-bound deletion qualification and post-deletion use.

The success/null and rejection/unchanged policies are declarative hypotheses,
not deductions from OpenAPI. Legacy callbacks and schedules are unchanged.
"""
import hashlib
from .relationship_runtime_js import CODE

REFERENCE_CODE = CODE.replace("  if(ctx.mode==='reject_link'){", r'''
  function refEvidence(stage,expected,observed){var evidence={task_id:ctx.reference_task_id,stage:stage,instance:ctx.instance,expected:expected,observed:observed};store('sbt_rel_reference_failure',evidence);fail('Reference lifecycle mismatch: '+JSON.stringify(evidence));}
  function refWalk(object,path,visit){var parts=segments(path);function walk(o,at){if(!o||typeof o!=='object')return;var p=parts[at];if(p.array){(o[p.name]||[]).forEach(function(v){if(at===parts.length-1)fail('Scalar nullable leaf required');else walk(v,at+1);});}else if(at===parts.length-1)visit(o,p.name);else walk(o[p.name],at+1);}walk(object,0);}
  function refFields(object){if(ctx.request_schema)object=project(ctx.request_schema,object,0,false);var out={};ctx.preserve_fields.forEach(function(field){out[field]=clone(object[field]);});(ctx.derived_fields||[]).forEach(function(path){refWalk(out,path,function(o,k){delete o[k];});});return out;}
  function refCheck(expected,observed,stage){if(stable(expected)!==stable(observed))refEvidence(stage,expected,observed);}
  if(ctx.mode==='reference_delete'){
    var rec=read(ctx.reference_variable);rec.delete_code=response.code;rec.deleted=ctx.success_codes.indexOf(response.code)>=0;rec.outcome=rec.deleted?'SUCCESS_NULL_POLICY_OBSERVED':'REJECTION_UNCHANGED_POLICY_OBSERVED';store(ctx.reference_variable,rec);return;
  }
  if(ctx.mode==='reference_target'){
    var rec=read(ctx.reference_variable);if(rec.deleted){if(ctx.absence_codes.indexOf(response.code)<0)refEvidence('target_absence',ctx.absence_codes,response.code);}else{if(response.code!==200)refEvidence('retained_target',200,response.code);var targetBody=JSON.parse(response.body);refCheck(rec.target_before,targetBody,'retained_target');identity(ctx,targetBody);}
    rec.target_checked=true;rec.target_reads.push({code:response.code,observed:rec.deleted?null:targetBody});store(ctx.reference_variable,rec);return;
  }
  if(ctx.mode==='reject_link'){''', 1)
REFERENCE_CODE = REFERENCE_CODE.replace("  if(ctx.mode==='prepare_action'){", r'''
  if(ctx.mode==='reference_initialize'){
    identity(ctx,body);store(ctx.reference_variable,{task_id:ctx.reference_task_id,target:ctx.instance,target_id:idOf(body),target_before:body,deleted:false,delete_code:null,outcome:'CONTROL_NO_DELETE',checks:[],followups:[],target_checked:false,target_reads:[]});
  }
  if(ctx.mode==='reference_before'){
    identity(ctx,body);var rec=read(ctx.reference_variable),before=refFields(body),ids=ctx.field_path?valuesAt(body,ctx.field_path).map(idOf):[];
    if(ctx.referrer&&ids.indexOf(rec.target_id)<0)refEvidence('precondition_shared_reference',rec.target_id,ids);
    store(ctx.reference_variable+'_before_'+ctx.instance,before);store(ctx.snapshot_variable,body);store(ctx.reference_variable+'_stale_original_'+ctx.instance,body);
  }
  if(ctx.mode==='reference_after'){
    identity(ctx,body);var rec=read(ctx.reference_variable),expected=read(ctx.reference_variable+'_before_'+ctx.instance);
    if(rec.deleted&&ctx.field_path)refWalk(expected,ctx.field_path,function(o,k){if(idOf(o[k])===rec.target_id)o[k]=null;});
    var observed=refFields(body);refCheck(expected,observed,'post_delete');
    rec.checks.push({instance:ctx.instance,referrer:ctx.referrer===true,before:read(ctx.reference_variable+'_before_'+ctx.instance),field_path:ctx.field_path,expected:expected,observed:observed});store(ctx.reference_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='reference_prepare_update'){
    identity(ctx,body);var rec=read(ctx.reference_variable),data=project(ctx.request_schema,body,0,false);data[ctx.update_field]=pvg.rtv.get('sbt_rel_namespace')+'-post-delete-'+ctx.instance.split('#').pop();data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));store(ctx.reference_variable+'_update',{field:ctx.update_field,value:data[ctx.update_field],expected:refFields(body)});
  }
  if(ctx.mode==='reference_verify_update'){
    identity(ctx,body);var rec=read(ctx.reference_variable),update=read(ctx.reference_variable+'_update');refCheck(update.value,body[update.field],'continued_update_field');refCheck(update.expected,refFields(body),'continued_update_preserves_dependencies');rec.followups.push({stage:'update',instance:ctx.instance,expected:update.expected,observed:refFields(body),field:update.field,expected_value:update.value,value:body[update.field]});store(ctx.reference_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='reference_prepare_rebind'){
    identity(ctx,body);var rec=read(ctx.reference_variable),replacement=read(ctx.replacement_snapshot),data=project(ctx.request_schema,body,0,false),before=read(ctx.reference_variable+'_before_'+ctx.instance),slots=[];
    refWalk(before,ctx.field_path,function(o,k){slots.push(idOf(o[k])===rec.target_id);});var pos=0;
    refWalk(data,ctx.field_path,function(o,k){if(slots[pos++])o[k]=clone(replacement);});
    data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));var replacementValues=valuesAt(data,ctx.field_path).filter(function(v){return idOf(v)===idOf(replacement);});if(!replacementValues.length)fail('Replacement binding was not prepared');rec.replacement_id=idOf(replacement);rec.replacement_value=replacementValues[0];store(ctx.reference_variable,rec);store(ctx.reference_variable+'_rebind',refFields(data));
  }
  if(ctx.mode==='reference_verify_rebind'){
    identity(ctx,body);var rec=read(ctx.reference_variable),expected=read(ctx.reference_variable+'_rebind');refCheck(expected,refFields(body),'continued_rebind');rec.followups.push({stage:'rebind',instance:ctx.instance,expected:expected,observed:refFields(body)});store(ctx.reference_variable,rec);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='reference_finish'){
    var rec=read(ctx.reference_variable);if(!rec.target_checked||rec.checks.length!==ctx.check_count||rec.followups.length!==2)fail('Incomplete reference lifecycle observations');var records=read('sbt_rel_reference_receipts');records.push(rec);store('sbt_rel_reference_receipts',records);
  }

  if(ctx.mode==='stale_prepare'){
    identity(ctx,body);var rec=read(ctx.reference_variable),snapshot=read(ctx.reference_variable+'_stale_original_'+ctx.instance),data=project(ctx.request_schema,snapshot,0,false);
    data[ctx.update_field]=pvg.rtv.get('sbt_rel_namespace')+'-stale-write';pvg.rtv.set(ctx.body_variable,JSON.stringify(data));rec.stale={source_id:idOf(body),before:refFields(body),description_before:body[ctx.update_field],field:ctx.update_field,value:data[ctx.update_field],submitted:refFields(data),checks:[]};store(ctx.reference_variable,rec);
  }
  if(ctx.mode==='stale_write'){var rec=read(ctx.reference_variable);rec.stale.code=response.code;rec.stale.accepted=ctx.success_codes.indexOf(response.code)>=0;store(ctx.reference_variable,rec);return;}
  if(ctx.mode==='stale_read'){
    identity(ctx,body);var rec=read(ctx.reference_variable),baseline=rec.checks.filter(function(c){return c.instance===ctx.instance;})[0].observed,observed=refFields(body);
    var expected=clone(baseline);
    if(rec.stale.accepted)(ctx.live_views||[]).forEach(function(view){[expected,observed].forEach(function(data,index){refWalk(data,view.path,function(o,k){var embedded=o[k];if(embedded&&embedded[view.identity_field]===rec.stale.source_id){if(index===0)embedded[rec.stale.field]=rec.stale.value;view.volatile_fields.forEach(function(f){delete embedded[f];});}});});});
    if(ctx.instance!==ctx.followup_source||!rec.stale.accepted)refCheck(expected,observed,'stale_atomicity_or_unrelated_source');
    if(ctx.instance===ctx.followup_source){var expectedValue=rec.stale.accepted?rec.stale.value:rec.stale.description_before;refCheck(expectedValue,body[rec.stale.field],'stale_description');}
    rec.stale.checks.push({instance:ctx.instance,expected:expected,observed:observed,field_value:body[rec.stale.field]});store(ctx.reference_variable,rec);
  }
  if(ctx.mode==='stale_target'){var rec=read(ctx.reference_variable);rec.stale.target_read={code:response.code,observed:response.code===200?JSON.parse(response.body):null};if(!rec.stale.accepted){if(rec.deleted){if(response.code===200)refEvidence('stale_rejection_resurrected_target',404,response.code);}else refCheck(rec.target_before,rec.stale.target_read.observed,'stale_rejection_changed_target');}store(ctx.reference_variable,rec);return;}
  if(ctx.mode==='stale_finish'){
    var rec=read(ctx.reference_variable);if(!rec.stale.target_read||rec.stale.checks.length!==ctx.check_count)fail('Incomplete stale observations');
    if(rec.delete_code===null&&!rec.stale.accepted)refEvidence('stale_control_rejected',200,rec.stale.code);
    if(rec.stale.accepted&&rec.deleted)refEvidence('stale_success_requires_policy_qualification',{new_bug_confirmed:false},rec.stale);
    var records=read('sbt_rel_reference_receipts');records.push(rec);store('sbt_rel_reference_receipts',records);
  }
  if(ctx.mode==='prepare_action'){''', 1)
REFERENCE_CODE = REFERENCE_CODE.replace("store('sbt_rel_owned',[]);", "store('sbt_rel_owned',[]);store('sbt_rel_reference_receipts',[]);", 1)
REFERENCE_CODE = REFERENCE_CODE.replace("store('sbt_rel_execution_receipt',receipt);", "if(ctx.expected_reference_tasks){var refs=read('sbt_rel_reference_receipts');if(refs.length!==ctx.expected_reference_tasks.length)fail('Incomplete reference lifecycle receipts');ctx.expected_reference_tasks.forEach(function(id){if(!refs.some(function(r){return r.task_id===id;}))fail('Missing reference receipt');});receipt.reference_lifecycles=refs;}store('sbt_rel_execution_receipt',receipt);", 1)

# Status-only and absent-target handlers must run before generic JSON parsing.
for _mode in ('stale_write','stale_target'):
    _start=REFERENCE_CODE.index("  if(ctx.mode==='"+_mode+"')")
    _end=REFERENCE_CODE.index('\n',_start)
    _handler=REFERENCE_CODE[_start:_end]
    REFERENCE_CODE=REFERENCE_CODE[:_start]+REFERENCE_CODE[_end:]
    REFERENCE_CODE=REFERENCE_CODE.replace("  if(ctx.mode==='reject_link'){",_handler+"\n  if(ctx.mode==='reject_link'){",1)


def append_reference_lifecycle(blueprint, info, entities, runtime, add_request,
                               request_schema, property_schema, root, response_schema):
    if 'reference_lifecycle' not in runtime:
        return {}
    rule = runtime['reference_lifecycle']
    required = {'resource_type','target_index','replacement_index','source_type','field_path',
                'operation','update_operation','update_field','preserve_fields','absence_codes',
                'rejection_codes','mode','controls'}
    if not isinstance(rule, dict) or set(rule)-{'derived_fields','stale_snapshot'} != required:
        raise ValueError('Reference lifecycle requires a complete explicit policy.')
    if rule['mode'] not in ('delete','control'):
        raise ValueError('Reference lifecycle mode must be delete or control.')
    if 'stale_snapshot' in rule and rule['stale_snapshot'] is not True:
        raise ValueError('Stale snapshot must explicitly be true.')
    resource=rule['resource_type'];source_type=rule['source_type']
    if resource not in blueprint['instances'] or source_type not in blueprint['instances']:
        raise ValueError('Reference resource and source must be selected.')
    indices=[rule['target_index'],rule['replacement_index']]
    if any(type(i) is not int or not 1<=i<=len(blueprint['instances'][resource]) for i in indices) or indices[0]==indices[1]:
        raise ValueError('Deletion and replacement indices must be distinct owned instances.')
    for name,allowed in [('absence_codes',{404,410}),('rejection_codes',{400,409,422})]:
        codes=rule[name]
        if not isinstance(codes,list) or not codes or any(type(c) is not int or c not in allowed for c in codes) or len(set(codes))!=len(codes):
            raise ValueError('Invalid explicit reference '+name+'.')
    delete=rule['operation'];update=rule['update_operation'];field=rule['field_path']
    def operation_for(key,identity,verbs):
        if not isinstance(identity,str) or identity.split(' ',1)[0] not in verbs or identity not in [o.op.method+' '+o.op.path for o in entities[key].ops]:
            raise ValueError('Reference operation must belong to its selected resource.')
    operation_for(resource,delete,{'DELETE'});operation_for(source_type,update,{'PUT','PATCH'})
    leaf=root(property_schema(request_schema(update),field,writable=True))
    if field.endswith('[]') or not (leaf.get('nullable') or any(root(b).get('type')=='null' for b in leaf.get('anyOf',[])+leaf.get('oneOf',[]))):
        raise ValueError('Reference success hypothesis requires a documented nullable scalar/object leaf.')
    update_schema=root(property_schema(request_schema(update),rule['update_field'],writable=True))
    if not any(root(b).get('type')=='string' for b in update_schema.get('anyOf',update_schema.get('oneOf',[update_schema]))) or '.' in rule['update_field']:
        raise ValueError('Followup update requires a documented top-level string field.')
    protected=rule['preserve_fields']
    if not isinstance(protected,list) or not protected or len(set(protected))!=len(protected) or field.split('.')[0].replace('[]','') not in protected:
        raise ValueError('Protected fields must include the relationship container.')
    for p in protected:
        if not isinstance(p,str) or '.' in p or '[]' in p:raise ValueError('Protected fields must be top-level names.')
        property_schema(request_schema(update),p,writable=True)
    derived=rule.get('derived_fields',[])
    if not isinstance(derived,list) or len(set(derived))!=len(derived) or any(not isinstance(f,str) or not f.startswith(field.rsplit('.',1)[0]+'.') or f==field or f.split('.')[-1] in ('id','quantity','food','unit','note','referenceId') for f in derived):
        raise ValueError('Derived exclusions require explicit non-identity paths in the protected container.')
    for f in derived:property_schema(request_schema(update),f,writable=True)
    target=blueprint['instances'][resource][indices[0]-1];replacement=blueprint['instances'][resource][indices[1]-1]
    links=[t for t in blueprint['tasks'] if t['kind']=='link' and not t.get('lifecycle_phase')]
    refs=[t for t in links if t['source_instance'] in blueprint['instances'][source_type] and t['field_path']==field and target in t['target_instances']]
    sources=sorted({t['source_instance'] for t in refs})
    if len(sources)<2:raise ValueError('Reference lifecycle requires two observed referrers.')
    if any(t['operation']!=update for t in refs):raise ValueError('Followup update must match the inferred link operation.')
    checks=[{'instance':s,'field_path':field,'referrer':s in sources,'preserve_fields':protected,'request_schema':request_schema(update),'derived_fields':derived} for s in blueprint['instances'][source_type]]
    controls=rule['controls']
    if not isinstance(controls,list):raise ValueError('Reference controls must be a list.')
    for control in controls:
        if not isinstance(control,dict) or set(control)-{'live_views'}!={'resource_type','preserve_fields'}:raise ValueError('Invalid reference control.')
        key=control['resource_type'];fields=control['preserve_fields']
        if key not in blueprint['instances'] or key in (resource,source_type) or not isinstance(fields,list) or not fields or any(not isinstance(f,str) or '.' in f or '[]' in f for f in fields) or len(set(fields))!=len(fields):raise ValueError('Invalid control resource/fields.')
        get=entities[key].get_op.op
        for f in fields:property_schema(response_schema(get.method+' '+get.path),f)
        views=control.get('live_views',[])
        if not isinstance(views,list) or ('live_views' in control and not rule.get('stale_snapshot')):raise ValueError('Live views require an opt-in stale snapshot policy.')
        for view in views:
            if not isinstance(view,dict) or set(view)!={'path','identity_field','volatile_fields'}:raise ValueError('Invalid live view mapping.')
            path=view['path'];identity_field=view['identity_field'];volatile=view['volatile_fields']
            if not isinstance(path,str) or path.split('.')[0].replace('[]','') not in fields or not isinstance(identity_field,str) or identity_field not in ('id','slug'):raise ValueError('Live view must retain an explicit identity in a protected field.')
            if not isinstance(volatile,list) or len(set(volatile))!=len(volatile) or any(f not in ('dateUpdated','updatedAt') for f in volatile):raise ValueError('Only explicit update timestamps may be volatile.')
            for f in [identity_field,rule['update_field']]+volatile:property_schema(response_schema(get.method+' '+get.path),path+'.'+f)
        for s in blueprint['instances'][key]:
            check={'instance':s,'field_path':None,'referrer':False,'preserve_fields':fields,'request_schema':None,'derived_fields':[]}
            if views:check['live_views']=views
            checks.append(check)
    if len({c['instance'] for c in checks})!=len(checks):raise ValueError('Duplicate reference control.')
    actions=[t for t in blueprint['tasks'] if t['kind']=='qualified_action']
    if len(actions)<2:raise ValueError('Reference lifecycle requires actions before and after deletion.')
    prefix=actions[0];task_id='reference-lifecycle:'+resource+':'+rule['mode']
    # All structural bindings are established; one action precedes the probe,
    # while the remaining association construction is explicitly deferred.
    after=[t['id'] for t in blueprint['tasks'] if t['kind']!='qualified_action']+[prefix['id']]
    for action in actions[1:]:action['after']=list(dict.fromkeys(action['after']+[task_id]))
    variable='rel_reference_'+hashlib.sha256(task_id.encode()).hexdigest()[:16]
    task={'id':task_id,'kind':'reference_lifecycle','source_instance':target,'target_instances':[],
          'operation':delete,'after':after,'executable':True,'rule':rule,'checks':checks,
          'prefix_action':prefix['id'],'deferred_actions':[a['id'] for a in actions[1:]],'followup_source':sources[0],'replacement':replacement}
    getter=lambda s:entities[info[s]['resource']].get_op.op.method+' '+entities[info[s]['resource']].get_op.op.path
    def context(s,mode,**extra):
        return dict(info[s],mode=mode,reference_variable=variable,reference_task_id=task_id,**extra)
    stale=rule.get('stale_snapshot',False)
    steps=[add_request(getter(target),context(target,'reference_initialize'),target)]
    for check in checks:
        s=check['instance'];steps.append(add_request(getter(s),context(s,'reference_before',**{k:check[k] for k in ('field_path','referrer','preserve_fields','request_schema','derived_fields')}),s))
    success=[int(r.status) for o in entities[resource].ops if o.op.method+' '+o.op.path==delete for r in o.op.success_responses]
    if rule['mode']=='delete':steps.append(add_request(delete,context(target,'reference_delete',success_codes=success,absence_codes=success+rule['rejection_codes']),target))
    target_ctx={'absence_codes':[200]+rule['absence_codes']}
    steps.append(add_request(getter(target),context(target,'reference_target',**target_ctx),target))
    for check in checks:
        s=check['instance'];steps.append(add_request(getter(s),context(s,'reference_after',**{k:check[k] for k in ('field_path','referrer','preserve_fields','request_schema','derived_fields')}),s))
    s=sources[0];body=variable+'_body';shared={'derived_fields':derived,'preserve_fields':protected,'field_path':field,'request_schema':request_schema(update),'body_variable':body}
    if stale:
        shared['update_field']=rule['update_field']
        steps.append(add_request(getter(s),context(s,'stale_prepare',**shared),s))
        steps.append(add_request(update,context(s,'stale_write',success_codes=[200,204],absence_codes=[200,204]+rule['rejection_codes']),s,body))
        for check in checks:
            inst=check['instance']
            extra={k:check[k] for k in ('field_path','referrer','preserve_fields','request_schema','derived_fields')}
            if check.get('live_views'):extra['live_views']=check['live_views']
            steps.append(add_request(getter(inst),context(inst,'stale_read',followup_source=s,**extra),inst))
        steps.append(add_request(getter(target),context(target,'stale_target',absence_codes=[200]+rule['absence_codes']),target))
        steps.append(add_request(getter(replacement),context(replacement,'stale_finish',check_count=len(checks),task_id=task_id),replacement))
        blueprint['tasks'].append(task)
        return {task_id:steps}
    steps.extend([add_request(getter(s),context(s,'reference_prepare_update',update_field=rule['update_field'],**shared),s),add_request(update,{'mode':'write'},s,body),add_request(getter(s),context(s,'reference_verify_update',**shared),s),
                  add_request(getter(replacement),context(replacement,'snapshot'),replacement),
                  add_request(getter(s),context(s,'reference_prepare_rebind',replacement_snapshot=info[replacement]['snapshot_variable'],**shared),s),add_request(update,{'mode':'write'},s,body),add_request(getter(s),context(s,'reference_verify_rebind',**shared),s),
                  add_request(getter(target),context(target,'reference_target',**target_ctx),target),
                  add_request(getter(replacement),context(replacement,'reference_finish',check_count=len(checks),task_id=task_id),replacement)])
    blueprint['tasks'].append(task)
    return {task_id:steps}
