"""Self-contained additive quantity and reference-remapping callback variant."""
from .relationship_runtime_js import CODE

BLOCK = r'''
  function scalar(object,path){var v=valuesAt(object,path);if(v.length!==1)fail('Ambiguous semantic scalar: '+path);return v[0];}
  function clean(map){var out={};Object.keys(map).sort().forEach(function(k){if(Math.abs(map[k])>ctx.semantic_config.tolerance)out[k]=map[k];});return out;}
  function closeMaps(expected,observed){var keys=Object.keys(expected).concat(Object.keys(observed));return keys.every(function(k){var a=expected[k]||0,b=observed[k]||0;return Math.abs(a-b)<=ctx.semantic_config.tolerance*Math.max(1,Math.abs(a),Math.abs(b));});}
  function measure(object,description){var out={};valuesAt(object,description.items_path).forEach(function(item){var keys=description.key_paths.map(function(path){var key=scalar(item,path);if(typeof key!=='string'||!key)fail('Missing semantic identity key');return key;});var amount=scalar(item,description.amount_path);if(typeof amount!=='number'||!isFinite(amount)||amount<0)fail('Invalid semantic quantity');var key=JSON.stringify(keys);out[key]=(out[key]||0)+amount;});return clean(out);}
  function referenceQuantities(object){var c=ctx.semantic_config.container_references,out={};valuesAt(object,c.items_path).forEach(function(item){var key=scalar(item,c.key_path),n=scalar(item,c.amount_path);if(typeof key!=='string'||typeof n!=='number'||!isFinite(n)||n<0)fail('Invalid contribution association');out[key]=(out[key]||0)+n;});return clean(out);}
  function observedView(object,kind){var c=ctx.semantic_config;var v={totals:measure(object,kind==='reference'?c.reference_measure:c.container_measure)};if(kind==='container')v.references=referenceQuantities(object);return v;}
  function checkView(expected,observed){if(!closeMaps(expected.totals,observed.totals)||(expected.references&&!closeMaps(expected.references,observed.references)))fail('Semantic consistency mismatch: '+JSON.stringify({instance:ctx.instance,expected:expected,observed:observed}));}
  function remap(totals,from,to){var out={};Object.keys(totals).forEach(function(k){var parts=JSON.parse(k);if(parts[ctx.semantic_config.merge_key_index]===from)parts[ctx.semantic_config.merge_key_index]=to;var key=JSON.stringify(parts);out[key]=(out[key]||0)+totals[k];});return clean(out);}
  if(ctx.mode==='semantic_init'){
    identity(ctx,body);store(ctx.snapshot_variable,body);var state=read(ctx.semantic_state),view=observedView(body,ctx.view_kind),c=ctx.semantic_config;
    if(ctx.view_kind==='container'){
      var sum=Object.keys(view.totals).reduce(function(n,k){return n+view.totals[k];},0);
      if(Math.abs(sum-c.baseline_container_total)>c.tolerance||Object.keys(view.references).length)fail('Initial manual contribution precondition failed');
    }else valuesAt(body,c.reference_measure.items_path).forEach(function(item){if(Math.abs(scalar(item,c.reference_measure.amount_path)-c.baseline_reference_item_quantity)>c.tolerance)fail('Initial source quantity precondition failed');});
    state.views[ctx.instance]=view;store(ctx.semantic_state,state);
    if(ctx.task_id){var receipts=read('sbt_rel_semantic_receipts');receipts.push({task_id:ctx.task_id,kind:'semantic_init',initial:clone(state.views)});store('sbt_rel_semantic_receipts',receipts);}
  }
  if(ctx.mode==='semantic_prepare_contribution'){
    identity(ctx,body);store(ctx.snapshot_variable,body);var state=read(ctx.semantic_state),before=clone(state.views);checkView(before[ctx.instance],observedView(body,'container'));
    var expected=clone(before),source=expected[ctx.reference_instance],target=expected[ctx.instance],reference=scalar(read(ctx.reference_snapshot),ctx.semantic_config.reference_identity),amount=ctx.amount;
    if(amount<0&&(target.references[reference]||0)<-amount-ctx.semantic_config.tolerance)fail('Removal exceeds the owned contribution');
    Object.keys(source.totals).forEach(function(k){target.totals[k]=(target.totals[k]||0)+amount*source.totals[k];if(target.totals[k]<-ctx.semantic_config.tolerance)fail('Negative expected quantity');});target.totals=clean(target.totals);
    target.references[reference]=(target.references[reference]||0)+amount;target.references=clean(target.references);
    var policy=ctx.semantic_config.contribution,data={};data[amount>0?policy.add_field:policy.remove_field]=Math.abs(amount);
    data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));pvg.rtv.set(ctx.target_variable,encodeURIComponent(reference));
    store(ctx.expectation_variable+'_semantic',{task_id:ctx.semantic_task_id,kind:'semantic_contribution',container:ctx.instance,reference_instance:ctx.reference_instance,reference_id:reference,amount:amount,before:before,expected:expected,checks:[]});
  }
  if(ctx.mode==='semantic_prepare_merge'){
    identity(ctx,body);var state=read(ctx.semantic_state),before=clone(state.views),expected=clone(before),from=scalar(body,ctx.semantic_config.resource_identity),to=scalar(read(ctx.target_snapshot),ctx.semantic_config.resource_identity);
    if(from===to)fail('Merge must use two distinct owned identities');
    Object.keys(expected).forEach(function(k){expected[k].totals=remap(expected[k].totals,from,to);});
    var data={},policy=ctx.semantic_config.merge;data[policy.from_field]=from;data[policy.to_field]=to;data=project(ctx.request_schema,data,0,false);pvg.rtv.set(ctx.body_variable,JSON.stringify(data));
    store(ctx.expectation_variable+'_semantic',{task_id:ctx.semantic_task_id,kind:'semantic_merge',from_instance:ctx.instance,from_id:from,to_instance:ctx.to_instance,to_id:to,before:before,expected:expected,checks:[],source_absent:false});
  }
  if(ctx.mode==='semantic_check'){
    identity(ctx,body);var pending=read(ctx.expectation_variable+'_semantic'),observed=observedView(body,ctx.view_kind);checkView(pending.expected[ctx.instance],observed);store(ctx.snapshot_variable,body);
    pending.checks.push({instance:ctx.instance,view_kind:ctx.view_kind,observed:observed});store(ctx.expectation_variable+'_semantic',pending);
    if(ctx.task_id){if(pending.checks.length!==ctx.check_count||(pending.kind==='semantic_merge'&&!pending.source_absent))fail('Incomplete semantic checks');store(ctx.semantic_state,{views:pending.expected});var receipts=read('sbt_rel_semantic_receipts');receipts.push(pending);store('sbt_rel_semantic_receipts',receipts);}
  }
'''

SEMANTIC_CODE = CODE.replace("store('sbt_rel_owned',[]);", "store('sbt_rel_owned',[]);store('sbt_rel_semantic_receipts',[]);store('rel_semantic_state',{views:{}});")
SEMANTIC_CODE = SEMANTIC_CODE.replace("  var body;try{body=JSON.parse(response.body);}", r'''  if(ctx.mode==='semantic_absent'){
    var pending=read(ctx.expectation_variable+'_semantic');pending.source_absent=true;pending.absence_code=response.code;store(ctx.expectation_variable+'_semantic',pending);
    var owned=read('sbt_rel_owned');owned.forEach(function(record){if(record.instance===ctx.instance){record.deleted=true;record.merged_into=pending.to_id;}});store('sbt_rel_owned',owned);return;
  }
  var body;try{body=JSON.parse(response.body);}''')
SEMANTIC_CODE = SEMANTIC_CODE.replace("  if(ctx.mode==='prepare_action'){", BLOCK+"  if(ctx.mode==='prepare_action'){")
SEMANTIC_CODE = SEMANTIC_CODE.replace("store('sbt_rel_execution_receipt',receipt);", "if(ctx.expected_semantic_tasks){var semantic=read('sbt_rel_semantic_receipts');if(semantic.length!==ctx.expected_semantic_tasks.length)fail('Incomplete semantic program receipts');ctx.expected_semantic_tasks.forEach(function(id){if(!semantic.some(function(r){return r.task_id===id;}))fail('Missing semantic program receipt');});receipt.semantic_tests=semantic;}store('sbt_rel_execution_receipt',receipt);")


# Opt-in variant preserves previous semantic callback bytes when not selected.
COLLISION_CODE = SEMANTIC_CODE.replace(
    "Object.keys(expected).forEach(function(k){expected[k].totals=remap(expected[k].totals,from,to);});",
    "var collisions=0;Object.keys(expected).forEach(function(k){var oldCount=Object.keys(expected[k].totals).length;expected[k].totals=remap(expected[k].totals,from,to);collisions+=oldCount-Object.keys(expected[k].totals).length;});if(collisions<1)fail('Merge did not exercise a quantity group collision');"
).replace("source_absent:false});", "source_absent:false,collision_groups:collisions});")
