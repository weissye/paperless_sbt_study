"""Self-contained runtime callback code, serialized into REST events."""

CODE = r'''
function sbtRelRuntime(response, ctx, cfg, schemas) {
  function fail(message) { pvg.fail(message); throw new Error(message); }
  function read(key) { var value=pvg.rtv.get(key); if(value===undefined||value===null)fail("Missing binding: "+key); try{return JSON.parse(value);}catch(e){fail("Invalid binding: "+key);} }
  function store(key,value) { pvg.rtv.set(key,JSON.stringify(value)); }
  function schema(s) { var seen={}; while(s && s.$ref){var n=s.$ref.split('/').pop().replace(/~1/g,'/').replace(/~0/g,'~');if(seen[n]||!schemas[n])fail("Unresolved schema: "+n);seen[n]=true;s=schemas[n];}return s||{}; }
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  function stable(v){if(Array.isArray(v))return '['+v.map(stable).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(function(k){return JSON.stringify(k)+':'+stable(v[k]);}).join(',')+'}';return JSON.stringify(v);}
  function project(s,v,depth,minimal) {
    if(depth>32)fail("Projection depth exceeded"); s=schema(s);
    var branches=s.anyOf||s.oneOf;
    if(branches){var errors=[],best,score=-1;for(var i=0;i<branches.length;i++){try{var candidate=project(branches[i],v,depth+1,minimal),current=candidate&&typeof candidate==='object'?Object.keys(candidate).length:0;if(current>score){best=candidate;score=current;}}catch(e){errors.push(e.message);}}if(score>=0)return best;throw new Error("No schema branch accepts value: "+errors.join(';'));}
    if(s.allOf){var merged={type:'object',properties:{},required:[]};s.allOf.forEach(function(b){b=schema(b);Object.assign(merged.properties,b.properties||{});merged.required=merged.required.concat(b.required||[]);});return project(merged,v,depth+1,minimal);}
    if(s.type==='null'){if(v!==null)throw new Error("Null required");return null;}
    if(v===null){if(s.nullable)return null;throw new Error("Unexpected null");}
    if(s.enum && s.enum.indexOf(v)<0)throw new Error("Enum mismatch");
    if(s.type==='object'||s.properties){if(!v||typeof v!=='object'||Array.isArray(v))throw new Error("Object required");var out={},props=s.properties||{};
      Object.keys(props).forEach(function(k){if(props[k].readOnly)return;if(v[k]!==undefined && (!minimal||(s.required||[]).indexOf(k)>=0||k==='id'||k==='slug'||k==='name'))out[k]=project(props[k],v[k],depth+1,minimal);});
      (s.required||[]).forEach(function(k){if(!props[k]||props[k].readOnly)return;if(out[k]===undefined)throw new Error("Required request field missing: "+k);});
      if(s.additionalProperties===true)Object.keys(v).forEach(function(k){if(!props[k])out[k]=clone(v[k]);});
      else if(s.additionalProperties && typeof s.additionalProperties==='object')Object.keys(v).forEach(function(k){if(!props[k])out[k]=project(s.additionalProperties,v[k],depth+1,minimal);});
      return out;
    }
    if(s.type==='array'||s.items){if(!Array.isArray(v))throw new Error("Array required");if(s.minItems!==undefined&&v.length<s.minItems)throw new Error("Array too short");if(s.maxItems!==undefined&&v.length>s.maxItems)throw new Error("Array too long");return v.map(function(x){return project(s.items||{},x,depth+1,minimal);});}
    if(s.type==='string'){if(typeof v!=='string')throw new Error("String required");if(s.minLength!==undefined&&v.length<s.minLength)throw new Error("String too short");if(s.maxLength!==undefined&&v.length>s.maxLength)throw new Error("String too long");if(s.pattern&&!new RegExp(s.pattern).test(v))throw new Error("String pattern mismatch");if(s.format && /^uuid/.test(s.format)&&!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v))throw new Error("UUID mismatch");}
    if(s.type==='number'||s.type==='integer'){if(typeof v!=='number'||!isFinite(v)||(s.type==='integer'&&Math.floor(v)!==v))throw new Error("Number required");if(s.minimum!==undefined&&v<s.minimum)throw new Error("Below minimum");if(s.maximum!==undefined&&v>s.maximum)throw new Error("Above maximum");}
    if(s.type==='boolean'&&typeof v!=='boolean')throw new Error("Boolean required");return clone(v);
  }
  function empty(s){s=schema(s);if(s.default!==undefined)return clone(s.default);if(s.anyOf||s.oneOf){var b=s.anyOf||s.oneOf;for(var i=0;i<b.length;i++){if(schema(b[i]).type!=='null')return empty(b[i]);}return null;}if(s.type==='object'||s.properties)return {};if(s.type==='array'||s.items)return [];return undefined;}
  function segments(path){return path.split('.').map(function(p){return {name:p.replace(/\[\]$/,''),array:/\[\]$/.test(p)};});}
  function setPath(object,s,path,values,index) {
    var parts=segments(path);
    // Each existing array occurrence receives a target deterministically.
    function contextual(obj,node,at,itemIndex){node=schema(node);if(node.anyOf||node.oneOf)node=schema((node.anyOf||node.oneOf).filter(function(b){return schema(b).type!=='null';})[0]);var part=parts[at],prop=(node.properties||{})[part.name];if(!prop||prop.readOnly)fail("Unwritable relationship path: "+path);var ps=schema(prop);
      if(part.array){if(at===parts.length-1){obj[part.name]=values.map(function(v){return project(ps.items,v,0,true);});return;}var old=Array.isArray(obj[part.name])?obj[part.name]:[];var n=Math.max(old.length,values.length);obj[part.name]=[];for(var j=0;j<n;j++){var v=old[j]!==undefined?clone(old[j]):empty(ps.items);if(!v||typeof v!=='object')v={};contextual(v,ps.items,at+1,j);obj[part.name].push(v);}}
      else if(at===parts.length-1)obj[part.name]=project(prop,values[(itemIndex||0)%values.length],0,true);
      else {var child=obj[part.name];if(!child||typeof child!=='object')child=empty(prop)||{};contextual(child,prop,at+1,itemIndex);obj[part.name]=child;}}
    contextual(object,s,0,index||0);
  }
  function valuesAt(object,path){var parts=segments(path),values=[object];parts.forEach(function(p){var next=[];values.forEach(function(o){var v=o&&o[p.name];if(p.array){if(Array.isArray(v))next=next.concat(v);}else if(v!==undefined&&v!==null)next.push(v);});values=next;});return values;}
  function idOf(value){if(!value||typeof value!=='object')return value;return value.id!==undefined?value.id:value.slug;}
  function identity(task,value){var result={},previous=read(task.record_variable);task.route_fields.forEach(function(f){var v=typeof value==='string'||typeof value==='number'?value:value[f.response_field];if(v===undefined||v===null||v==='')fail("Missing documented route identity: "+f.parameter);if(previous[f.parameter]!==undefined&&previous[f.parameter]!==v)fail("Route identity changed on readback");result[f.parameter]=v;pvg.rtv.set(f.variable,encodeURIComponent(String(v)));});if(value&&typeof value==='object'){(task.identity_fields||[]).forEach(function(field){if(value[field]!==undefined){if(previous[field]!==undefined&&previous[field]!==value[field])fail("Coobserved identity changed");result[field]=value[field];}});}store(task.record_variable,result);var owned=read('sbt_rel_owned');owned.forEach(function(record){if(record.instance===task.instance)record.route=result;});store('sbt_rel_owned',owned);}
  if(ctx.codes.indexOf(response.code)<0)fail("Unexpected HTTP "+response.code+" for "+ctx.operation);
  if(ctx.mode==='auth')store('sbt_rel_progress',{responses:1,done:[]});else{var progress=read('sbt_rel_progress');progress.responses++;store('sbt_rel_progress',progress);}
  if(ctx.mode==='reject_link'){store(ctx.expectation_variable+'_rejection',{code:response.code,error_body:response.body});pvg.success('Qualified rejection observed; unchanged-state readback is pending');return;}
  if(ctx.mode==='write' && !response.body){pvg.success('Relationship write status accepted');return;}
  var body;try{body=JSON.parse(response.body);}catch(e){fail("Response is not JSON: "+ctx.operation);}
  if(ctx.mode==='auth'){if(!body.access_token||String(body.token_type||'bearer').toLowerCase()!=='bearer')fail("Invalid OAuth token response");pvg.rtv.set('sbt_rel_token',body.access_token);pvg.rtv.set('sbt_rel_namespace','rel-'+Date.now());store('sbt_rel_owned',[]);store('sbt_rel_negative_receipts',[]);store('sbt_rel_legal_receipts',[]);(ctx.identity_records||[]).forEach(function(key){store(key,{});});}
  if(ctx.mode==='bootstrap'){var selected={};ctx.fields.forEach(function(f){if(body[f]===undefined)fail("Missing bootstrap field: "+f);selected[f]=body[f];});store(ctx.variable,selected);(ctx.scope_checks||[]).forEach(function(check){var left=read('rel_bootstrap_'+check.left[0])[check.left[1]],right=read('rel_bootstrap_'+check.right[0])[check.right[1]];if(left===undefined||right===undefined||left!==right)fail('Bootstrap scope mismatch');});}
  if(ctx.mode==='prepare_create'){
    var data=clone(ctx.seed_body);if(data.name && typeof data.name==='string'){var ns=pvg.rtv.get('sbt_rel_namespace');data.name=ns+'-'+data.name;}
    ctx.parents.forEach(function(parent){var record=read(parent.snapshot);if(record[parent.field]===undefined)fail("Missing parent identifier");data[parent.body_field]=record[parent.field];});
    try{data=project(ctx.request_schema,data,0,false);}catch(e){fail("Create projection: "+e.message);}pvg.rtv.set(ctx.body_variable,JSON.stringify(data));
  }
  if(ctx.mode==='capture'){try{project(ctx.response_schema,body,0,false);}catch(e){fail("Create response contract: "+e.message);}if(ctx.capture_array){var candidates=body[ctx.capture_array];if(!Array.isArray(candidates)||candidates.length!==1)fail("Creation identity array is missing or ambiguous");body=candidates[0];}identity(ctx,body);var owned=read('sbt_rel_owned');owned.push({instance:ctx.instance,resource:ctx.resource,route:read(ctx.record_variable)});store('sbt_rel_owned',owned);}
  if(ctx.mode==='snapshot'){identity(ctx,body);store(ctx.snapshot_variable,body);}
  if(ctx.mode==='cycle_member_before'){identity(ctx,body);store(ctx.snapshot_variable,body);store(ctx.expectation_variable+'_member_'+ctx.member_index,body);}
  if(ctx.mode==='cycle_member_after'){
    var memberBefore=read(ctx.expectation_variable+'_member_'+ctx.member_index),probe=read(ctx.expectation_variable+'_probe');
    var memberUnchanged=stable(memberBefore)===stable(body);
    probe.member_checks.push({instance:ctx.instance,unchanged:memberUnchanged});store(ctx.expectation_variable+'_probe',probe);store('sbt_rel_last_cycle_probe',probe);
    if(!memberUnchanged)fail('Rejected relationship update changed cycle member state: '+JSON.stringify(probe));
    identity(ctx,body);store(ctx.snapshot_variable,body);
    if(ctx.task_id){if(probe.member_checks.length!==ctx.cycle_members.length||ctx.cycle_members.some(function(instance){return !probe.member_checks.some(function(check){return check.instance===instance&&check.unchanged===true;});}))fail('Incomplete cycle member readbacks');probe.all_members_unchanged=true;store('sbt_rel_last_cycle_probe',probe);var memberReceipts=read('sbt_rel_negative_receipts');memberReceipts.push(probe);store('sbt_rel_negative_receipts',memberReceipts);}
  }
  if(ctx.mode==='prepare_link'){
    if(ctx.rejection_probe){var cycle=ctx.cycle_snapshots.map(read);if(cycle.length<2||idOf(cycle[cycle.length-1])!==idOf(body))fail('Negative cycle source precondition failed');for(var c=0;c<cycle.length-1;c++){if(valuesAt(cycle[c],ctx.field_path).map(idOf).indexOf(idOf(cycle[c+1]))<0)fail('Negative cycle path was not observed');}if(ctx.targets.length!==1||idOf(read(ctx.targets[0]))!==idOf(cycle[0]))fail('Negative cycle target precondition failed');store(ctx.expectation_variable+'_before',body);}
    var data;try{data=project(ctx.request_schema,body,0,false);}catch(e){fail("Source projection: "+e.message);}
    var targets=ctx.targets.map(function(t){return read(t);}),expected=targets.map(idOf);
    if(ctx.unlink)targets=[null];
    if(ctx.write_view){var binding=ctx.write_view,field=binding.write_path.slice(0,-2),items=clone(data[field]||[]);expected=targets.map(function(target){var value=target[binding.target_field];if(value===undefined||value===null)fail('Missing collection target identity');if(!items.some(function(item){return item[binding.item_identity_field]===value;})){var entry=clone(binding.item_defaults);entry[binding.item_identity_field]=value;items.push(entry);}return value;});data[field]=items;}
    else setPath(data,ctx.request_schema,ctx.field_path,targets,0);
    var views=(ctx.identity_views||[]).map(function(view){var values=valuesAt(targets[0],view.target_field);if(values.length!==1)fail("Ambiguous target identity view: "+view.target_field);setPath(data,ctx.request_schema,view.write_path,values,0);return {path:view.readback_path,expected:values[0]};});
    (ctx.defaults||[]).forEach(function(rule){setPath(data,ctx.request_schema,rule.path,[rule.value],0);});
    try{data=project(ctx.request_schema,data,0,false);}catch(e){fail("Link projection: "+e.message);}pvg.rtv.set(ctx.body_variable,JSON.stringify(data));
    store(ctx.expectation_variable,expected);
    store(ctx.expectation_variable+'_views',views);
  }
  if(ctx.mode==='verify_link'){
    var expected=read(ctx.expectation_variable),observed=valuesAt(body,ctx.field_path).map(idOf);
    var viewObservations=(ctx.identity_views||[]).length?read(ctx.expectation_variable+'_views').map(function(view){return {path:view.path,expected:view.expected,observed:valuesAt(body,view.path)};}):[];
    var mismatch=(ctx.exact_empty&&observed.length!==0)||expected.some(function(id){return id===undefined||observed.indexOf(id)<0;})||viewObservations.some(function(view){return view.observed.length!==1||view.observed[0]!==view.expected;});
    if(mismatch){var evidence={task_id:ctx.task_id,field_path:ctx.field_path,expected:expected,observed:observed,identity_views:viewObservations};store('sbt_rel_failed_readback',evidence);fail("Relationship readback mismatch: "+JSON.stringify(evidence));}
    identity(ctx,body);store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='legal_target'){identity(ctx,body);var legal=read('sbt_rel_legal_receipts');var entry=legal.filter(function(r){return r.task_id===ctx.legal_task_id;})[0];if(!entry)fail('Missing legal source readback');entry.targets_read.push(ctx.instance);store('sbt_rel_legal_receipts',legal);}
  if(ctx.mode==='verify_link'&&ctx.legal_readback){var legal=read('sbt_rel_legal_receipts');legal.push({task_id:ctx.task_id,source_readback:true,expected:expected,observed:observed,targets_read:[]});store('sbt_rel_legal_receipts',legal);}
  if(ctx.mode==='verify_rejection'){
    var before=read(ctx.expectation_variable+'_before'),rejection=read(ctx.expectation_variable+'_rejection');
    var unchanged=stable(before)===stable(body),evidence={task_id:ctx.probe_task_id||ctx.task_id,cycle_length:ctx.cycle_length,code:rejection.code,source_unchanged:unchanged,error_body:rejection.error_body};store('sbt_rel_last_cycle_probe',evidence);
    if(ctx.rejection_codes.indexOf(rejection.code)<0)fail('Cycle probe returned an unqualified status: '+JSON.stringify(evidence));
    if(!unchanged)fail('Rejected relationship update changed source state: '+JSON.stringify(evidence));
    identity(ctx,body);store(ctx.snapshot_variable,body);
    if(ctx.verify_cycle_members){evidence.member_checks=[{instance:ctx.instance,unchanged:true}];store(ctx.expectation_variable+'_probe',evidence);}
    else{var receipts=read('sbt_rel_negative_receipts');receipts.push(evidence);store('sbt_rel_negative_receipts',receipts);}
  }
  if(ctx.mode==='prepare_action'){
    var target=read(ctx.target_snapshot);var value=target[ctx.target_field];if(value===undefined)fail("Missing action target identity");pvg.rtv.set(ctx.target_variable,encodeURIComponent(String(value)));store(ctx.expectation_variable,[value]);var actionBody=ctx.seed_body;if(ctx.request_schema){try{actionBody=project(ctx.request_schema,actionBody,0,false);}catch(e){fail("Action request projection: "+e.message);}}pvg.rtv.set(ctx.body_variable,JSON.stringify(actionBody));
  }
  if(ctx.task_id){var progress=read('sbt_rel_progress');if(progress.done.indexOf(ctx.task_id)>=0)fail("Duplicate task acceptance");progress.done.push(ctx.task_id);store('sbt_rel_progress',progress);}
  if(ctx.mode==='finish'){var progress=read('sbt_rel_progress'),owned=read('sbt_rel_owned'),negative=read('sbt_rel_negative_receipts');if(progress.responses!==ctx.expected_responses||progress.done.length!==ctx.expected_tasks.length||owned.length!==ctx.expected_instances)fail("Incomplete runtime execution");ctx.expected_tasks.forEach(function(id){if(progress.done.indexOf(id)<0)fail("Missing runtime task");});if(negative.length!==(ctx.expected_negative_tasks||[]).length)fail('Incomplete negative test receipts');(ctx.expected_negative_tasks||[]).forEach(function(id){if(!negative.some(function(r){return r.task_id===id&&r.source_unchanged===true;}))fail('Missing negative state verification');});var legal=read('sbt_rel_legal_receipts');if(legal.length!==(ctx.expected_legal_tasks||[]).length)fail('Incomplete legal relationship readbacks');(ctx.expected_legal_tasks||[]).forEach(function(id){if(!legal.some(function(r){return r.task_id===id&&r.source_readback===true;}))fail('Missing legal relationship receipt');});var receipt={status:'LIVE_CALLBACKS_COMPLETE',task_count:progress.done.length,response_count:progress.responses,owned_instances:owned.length,owned_records:owned,negative_tests:negative,reset_replay_accepted:false};if((ctx.expected_legal_tasks||[]).length)receipt.legal_tests=legal;store('sbt_rel_execution_receipt',receipt);pvg.success('SBT_REL_LIVE_RECEIPT '+JSON.stringify(receipt));}
  pvg.success('Relationship interface response accepted: '+ctx.mode);
}
'''


# Additive runtime extension: legacy callback source remains identical.
SHARED_CODE = CODE.replace("  if(ctx.mode==='prepare_action'){", r'''  if(ctx.mode==='shared_before'){
    identity(ctx,body);var ids=valuesAt(body,ctx.field_path).map(idOf),targetId=idOf(read(ctx.target_snapshot));
    if(ids.indexOf(targetId)<0)fail('Shared target was not observed in referrer: '+ctx.instance);
    store(ctx.expectation_variable+'_reference_'+ctx.reference_index,ids);
  }
  if(ctx.mode==='prepare_shared_update'){
    identity(ctx,body);var update=project(ctx.request_schema,body,0,false);
    var value=pvg.rtv.get('sbt_rel_namespace')+'-'+ctx.value+'-'+ctx.instance.split('#').pop();
    if(body[ctx.field]===value)fail('Shared update does not change the field');
    update[ctx.field]=value;update=project(ctx.request_schema,update,0,false);
    pvg.rtv.set(ctx.body_variable,JSON.stringify(update));
    store(ctx.expectation_variable+'_update',{field:ctx.field,expected:value,before:body[ctx.field],target:ctx.instance,target_id:idOf(body),referrers:[]});
  }
  if(ctx.mode==='shared_updated'){
    var update=read(ctx.expectation_variable+'_update');
    if(body[ctx.field]!==update.expected)fail('Shared target update was not observed');
    identity(ctx,body);store(ctx.snapshot_variable,body);update.target_readback=true;store(ctx.expectation_variable+'_update',update);
  }
  if(ctx.mode==='shared_after'){
    identity(ctx,body);var beforeIds=read(ctx.expectation_variable+'_reference_'+ctx.reference_index),afterIds=valuesAt(body,ctx.field_path).map(idOf);
    if(stable(beforeIds.slice().sort())!==stable(afterIds.slice().sort()))fail('Shared update changed referrer identities: '+ctx.instance);
    store(ctx.snapshot_variable,body);var update=read(ctx.expectation_variable+'_update');
    update.referrers.push({instance:ctx.instance,field_path:ctx.field_path,before:beforeIds,after:afterIds,identities_preserved:true});
    store(ctx.expectation_variable+'_update',update);
    if(ctx.task_id){if(!update.target_readback||update.referrers.length!==ctx.reference_count)fail('Incomplete shared update readbacks');
      var receipts=read('sbt_rel_shared_receipts');update.task_id=ctx.shared_task_id;receipts.push(update);store('sbt_rel_shared_receipts',receipts);}
  }
''' + "  if(ctx.mode==='prepare_action'){").replace("store('sbt_rel_execution_receipt',receipt);", "if(ctx.expected_shared_tasks){var shared=read('sbt_rel_shared_receipts');if(shared.length!==ctx.expected_shared_tasks.length)fail('Incomplete shared update receipts');ctx.expected_shared_tasks.forEach(function(id){if(!shared.some(function(r){return r.task_id===id&&r.target_readback===true;}))fail('Missing shared update receipt');});receipt.shared_updates=shared;}" + "store('sbt_rel_execution_receipt',receipt);")

SHARED_CODE = SHARED_CODE.replace("store('sbt_rel_owned',[]);", "store('sbt_rel_owned',[]);store('sbt_rel_shared_receipts',[]);")


# Additional assertions are opt-in; earlier runtime variants stay byte-identical.
EXPANDED_CODE = SHARED_CODE.replace(
    "    update.referrers.push({instance:ctx.instance,field_path:ctx.field_path,before:beforeIds,after:afterIds,identities_preserved:true});",
    r"""    var check={instance:ctx.instance,field_path:ctx.field_path,before:beforeIds,after:afterIds,identities_preserved:true};
    if(ctx.object_path){var objects=valuesAt(body,ctx.object_path).filter(function(o){return idOf(o)===update.target_id;});
      var embedded=objects.map(function(o){return o[ctx.value_field];});
      if(!embedded.length||embedded.some(function(v){return v!==update.expected;}))fail('Embedded shared value is stale: '+JSON.stringify({instance:ctx.instance,path:ctx.object_path,expected:update.expected,observed:embedded}));
      check.embedded_values=embedded;check.object_path=ctx.object_path;check.value_field=ctx.value_field;}
    update.referrers.push(check);""")

EXPANDED_CODE = EXPANDED_CODE.replace("  if(ctx.mode==='reject_link'){", r"""  if(ctx.mode==='delete_write'){pvg.success('Owned target deletion status accepted; absence readback is pending');return;}
  if(ctx.mode==='delete_absent'){
    var deletion=read(ctx.expectation_variable+'_deletion');deletion.absence_code=response.code;deletion.target_deleted=true;
    store(ctx.expectation_variable+'_deletion',deletion);var owned=read('sbt_rel_owned');
    owned.forEach(function(record){if(record.instance===ctx.instance)record.deleted=true;});store('sbt_rel_owned',owned);return;}
  if(ctx.mode==='reject_link'){""")

EXPANDED_CODE = EXPANDED_CODE.replace("  if(ctx.mode==='prepare_action'){", r"""  function relationshipState(object,fields){var out={};fields.forEach(function(path){out[path]=valuesAt(object,path).map(idOf).sort();});return out;}
  function checkDeleteSource(object,baseline,detached){
    var ids=valuesAt(object,ctx.field_path).map(idOf).sort(),expected=(detached?baseline.before.filter(function(id){return id!==baseline.target_id;}):baseline.before).slice().sort();
    if(stable(ids)!==stable(expected))fail('Detach/delete changed membership unexpectedly: '+ctx.instance);
    var protectedState=relationshipState(object,Object.keys(baseline.protected));
    if(stable(protectedState)!==stable(baseline.protected))fail('Detach/delete changed another relationship: '+ctx.instance);
    return {after:ids,expected:expected};
  }
  if(ctx.mode==='delete_before'){
    identity(ctx,body);var targetId=idOf(read(ctx.target_snapshot)),ids=valuesAt(body,ctx.field_path).map(idOf);
    if((ids.indexOf(targetId)>=0)!==ctx.detached)fail('Unexpected deletion membership precondition: '+ctx.instance);
    store(ctx.expectation_variable+'_check_'+ctx.check_index,{instance:ctx.instance,field_path:ctx.field_path,detached:ctx.detached,target_id:targetId,before:ids,protected:relationshipState(body,ctx.protected_fields)});
  }
  if(ctx.mode==='delete_target_before'){
    identity(ctx,body);store(ctx.expectation_variable+'_deletion',{task_id:ctx.deletion_task_id,target:ctx.instance,target_id:idOf(body),target_deleted:false,checks:[]});
  }
  if(ctx.mode==='prepare_detach'){
    identity(ctx,body);var baseline=read(ctx.expectation_variable+'_check_'+ctx.check_index);
    checkDeleteSource(body,baseline,false);
    var data=project(ctx.request_schema,body,0,false),field=ctx.field_path.slice(0,-2);
    if(!Array.isArray(data[field]))fail('Membership array missing from writable projection');
    data[field]=data[field].filter(function(item){return idOf(item)!==baseline.target_id;});
    data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));
  }
  if(ctx.mode==='verify_detach'){
    identity(ctx,body);var baseline=read(ctx.expectation_variable+'_check_'+ctx.check_index);checkDeleteSource(body,baseline,true);
    store(ctx.snapshot_variable,body);
  }
  if(ctx.mode==='delete_after'){
    identity(ctx,body);var baseline=read(ctx.expectation_variable+'_check_'+ctx.check_index),observed=checkDeleteSource(body,baseline,baseline.detached);
    var deletion=read(ctx.expectation_variable+'_deletion');
    if(!deletion.target_deleted)fail('Target absence was not observed');
    deletion.checks.push({instance:ctx.instance,field_path:ctx.field_path,detached:baseline.detached,before:baseline.before,after:observed.after,expected:observed.expected,protected_before:baseline.protected,protected_after:relationshipState(body,Object.keys(baseline.protected)),other_relationships_preserved:true});
    store(ctx.snapshot_variable,body);store(ctx.expectation_variable+'_deletion',deletion);
    if(ctx.task_id){if(deletion.checks.length!==ctx.check_count)fail('Incomplete detach/delete checks');var deletions=read('sbt_rel_deletion_receipts');deletions.push(deletion);store('sbt_rel_deletion_receipts',deletions);}
  }
  if(ctx.mode==='prepare_action'){""")
EXPANDED_CODE = EXPANDED_CODE.replace("store('sbt_rel_shared_receipts',[]);", "store('sbt_rel_shared_receipts',[]);store('sbt_rel_deletion_receipts',[]);")
EXPANDED_CODE = EXPANDED_CODE.replace("store('sbt_rel_execution_receipt',receipt);", "if(ctx.expected_deletion_tasks){var deletions=read('sbt_rel_deletion_receipts');if(deletions.length!==ctx.expected_deletion_tasks.length)fail('Incomplete deletion receipts');ctx.expected_deletion_tasks.forEach(function(id){if(!deletions.some(function(d){return d.task_id===id&&d.target_deleted===true;}))fail('Missing deletion receipt');});receipt.detached_deletions=deletions;}store('sbt_rel_execution_receipt',receipt);")

# A separate source variant preserves all previously generated callback bytes.
ATTACHED_CODE = EXPANDED_CODE.replace(
    "target_deleted:false,checks:[]});",
    "target_deleted:false,attached_at_delete:ctx.attached_at_delete===true,checks:[]});")
