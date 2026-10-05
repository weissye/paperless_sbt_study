// Execute the generated actors with a small BP-style scheduler and a fake REST server.
// This validates generated control flow and callbacks; it is not native Provengo.
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=process.argv[2],seed=Number(process.argv[3]||1),fault=process.argv[4]||'',missingMode=process.argv[5]||'';
const model=JSON.parse(fs.readFileSync(path.join(root,'relationship_scenario_plan.json'),'utf8'));
const expandedViews=model.tasks.some(t=>t.kind==='shared_update'&&t.referrers.some(r=>r.object_path));
const actors=[],rtv={},objects={},requests=[],selected=[],failures=[];
let callbackBytes=0,counter=0,random=seed,activeRequests=0,maximumActive=0,corrupt=false,currentTask=null,sharedChanged=false;
function uuid(){return '00000000-0000-4000-8000-'+String(++counter).padStart(12,'0');}
function pick(n){random=(Math.imul(random,1664525)+1013904223)>>>0;return random%n;}
function interpolate(value){return value.replace(/@\{([^}]+)\}/g,(_,key)=>key.startsWith('encodeURIComponent(getEnv')?'fake-credential':String(rtv[key]));}
const createOps={};
for(const t of model.tasks.filter(t=>t.kind==='create'))createOps[t.operation.split(' ')[1]]=t.resource;
const fakeScope={id:'11111111-1111-4111-8111-111111111111',groupId:'22222222-2222-4222-8222-222222222222',householdId:'33333333-3333-4333-8333-333333333333'};
function serve(method,url,options){
  url=interpolate(url);let body=options.body?interpolate(options.body):null;
  activeRequests++;maximumActive=Math.max(maximumActive,activeRequests);
  requests.push({method,url,task:currentTask});let result,status=method==='post'?201:200;
  try{
    const semantic=require('./semantic_http_fixture')(model,objects,uuid,fault,method,url,body);
    if(semantic){result=semantic.result;status=semantic.status;}
    else if(url.includes('/auth/token')){result={access_token:'FAKE_TOKEN',token_type:'bearer'};status=200;}
    else if(url==='/api/users/self')result=fakeScope;
    else if(url==='/api/groups/self')result={id:fault==='scope'?uuid():fakeScope.groupId};
    else if(url==='/api/households/self')result={id:fakeScope.householdId,groupId:fakeScope.groupId};
    else if(method==='post'&&createOps[url]){
      const data=JSON.parse(body),resource=createOps[url];const id=uuid(),slug='owned-'+counter;
      result={...data,id,slug,groupId:fakeScope.groupId,userId:fakeScope.id,householdId:fakeScope.householdId};
      if(resource==='api/recipes')Object.assign(result,{recipeIngredient:[],recipeCategory:[],tags:[]});
      if(resource==='api/households/shopping/lists')Object.assign(result,{listItems:[],recipeReferences:[]});
      if(resource==='api/households/shopping/items')Object.assign(result,{food:null,foodId:null,unit:fault==='projection-null'?17:null,unitId:null,referencedRecipe:null,recipeReferences:model.semantic_program?[]:[{id:uuid(),shoppingListItemId:id,recipeId:'44444444-4444-4444-8444-444444444444',recipeQuantity:2,recipeScale:1}]});
      const itemUrl=url+'/'+(resource==='api/recipes'?slug:id);objects[itemUrl]=result;
      if(resource==='api/recipes')result=slug;
      else if(resource==='api/households/shopping/items')result={createdItems:[result],updatedItems:[],deletedItems:[]};
      if(fault==='ambiguous-create'&&resource==='api/households/shopping/items')result.createdItems.push({...result.createdItems[0],id:uuid()});
    }else if(method==='get'&&objects[url]){result=objects[url];
      if(expandedViews&&fault!=='embedded-stale'){
        result=JSON.parse(JSON.stringify(result));
        function hydrate(node){if(!node||typeof node!=='object')return;for(const field of ['food','unit']){if(node[field]?.id){const family=field==='food'?'foods':'units',current=objects['/api/'+family+'/'+node[field].id];if(current)node[field]=JSON.parse(JSON.stringify(current));}}for(const value of Object.values(node))if(value&&typeof value==='object')hydrate(value);}
        hydrate(result);
      }
      if(fault==='shared-reference-changed'&&sharedChanged&&result.recipeIngredient?.some(x=>x.food)){result=JSON.parse(JSON.stringify(result));result.recipeIngredient.forEach(x=>{if(x.food)x.food.id=uuid();});}
      if(fault==='legal-target-id'&&currentTask?.endsWith(':legal-reverse')&&url!==Object.keys(objects).find(k=>objects[k].id===JSON.parse(rtv[model.instance_metadata[model.tasks.find(t=>t.id===currentTask).source_instance].snapshot_variable]).id))result={...result,id:uuid()};
      if(fault==='route-id'&&url.startsWith('/api/foods/'))result={...result,id:uuid()};
      if(fault==='readback'&&corrupt&&result.recipeIngredient?.some(x=>x.food)){
        result=JSON.parse(JSON.stringify(result));result.recipeIngredient.forEach(x=>{if(x.food)x.food.id=uuid();});corrupt=false;
      }
    }else if((method==='put'||method==='patch')&&objects[url]){const data=JSON.parse(body);
      const sharedUpdate=(url.startsWith('/api/foods/')||url.startsWith('/api/units/'))&&data.name?.includes('-updated');
      if(sharedUpdate){sharedChanged=true;if(fault==='shared-update-ignored')data.name=objects[url].name;}
      if(url.startsWith('/api/households/shopping/items/')){
        // Model an API whose scalar foreign keys determine hydrated relationship objects.
        for(const field of ['food','unit']){
          const family=field==='food'?'foods':'units',key=data[field+'Id'];
          data[field]=key?objects['/api/'+family+'/'+key]:null;
          assert(!key||data[field], 'Unknown foreign key');
        }
        // The inherited field is ignored; item-to-recipe associations are separate records.
        data.referencedRecipe=null;
        for(const old of objects[url].recipeReferences||[]){const retained=(data.recipeReferences||[]).find(x=>x.recipeId===old.recipeId);assert(retained&&retained.id===old.id,'Existing association identity was lost');assert.strictEqual(retained.recipeQuantity,old.recipeQuantity);}
        data.recipeReferences=(data.recipeReferences||[]).map(x=>({...x,id:x.id||uuid(),shoppingListItemId:objects[url].id}));
        if(fault==='association-readback'&&data.recipeReferences.length>1)data.recipeReferences[1].recipeId=uuid();
      }
      let cycle=false;
      if(url.startsWith('/api/recipes/')){
        if(model.tasks.some(t=>t.kind==='reference_lifecycle'))for(const ingredient of data.recipeIngredient||[]){ingredient.display=[ingredient.quantity,ingredient.unit?.name,ingredient.food?.name,ingredient.note].filter(v=>v!==undefined&&v!==null&&v!=='').join(' ');}
        const recipes=Object.values(objects).filter(x=>x.recipeIngredient),source=objects[url].id;
        function reaches(id,seen){if(id===source)return true;if(seen.has(id))return false;seen.add(id);const item=recipes.find(x=>x.id===id);return (item?.recipeIngredient||[]).some(x=>x.referencedRecipe&&reaches(x.referencedRecipe.id,seen));}
        cycle=(data.recipeIngredient||[]).some(x=>x.referencedRecipe&&reaches(x.referencedRecipe.id,new Set()));
      }
      if(fault==='alternate-path-ignored'&&currentTask?.endsWith(':reject-remaining-path'))cycle=false;
      if(cycle&&fault!=='cycle-accepted'){
        status=fault==='cycle-500'?500:400;result={detail:'Recursive Recipe Link Error'};
        if(fault==='cycle-mutates-on-reject')objects[url].description='PARTIAL_WRITE_DESPITE_REJECTION';
        if(fault==='cycle-target-mutates-on-reject'){const target=(data.recipeIngredient||[]).find(x=>x.referencedRecipe)?.referencedRecipe.id;const member=Object.values(objects).find(x=>x.id===target);assert(member);member.description='TARGET_WRITE_DESPITE_REJECTION';}
      }else if(fault==='legal-rejected'&&currentTask?.endsWith(':legal-reverse')){status=400;result={detail:'Incorrect rejection of acyclic link'};}
      else if((fault==='unlink-ignored'&&currentTask?.endsWith(':unlink'))||(fault==='alternate-unlink-ignored'&&currentTask?.endsWith(':remove-left'))){result=objects[url];}
      else if(data.description?.includes('-stale-write')&&model.tasks.some(t=>t.rule?.stale_snapshot&&t.rule.mode==='delete')&&fault!=='stale-accepted'){status=422;result={detail:'Removed dependency'};if(fault==='stale-partial')objects[url].description=data.description;if(fault==='stale-other-source')for(const other of Object.values(objects))if(other.recipeIngredient&&other.id!==objects[url].id)other.recipeIngredient[0].quantity=999;}
      else{if(currentTask?.startsWith('reference-lifecycle:')&&fault==='reference-followup-ignored')data.description=objects[url].description;
        if(currentTask?.startsWith('reference-lifecycle:')&&fault==='reference-rebind-ignored'&&data.recipeIngredient?.some(x=>x.food||x.unit))data.recipeIngredient=objects[url].recipeIngredient;
        objects[url]={...objects[url],...data};result=objects[url];corrupt=fault==='readback';
        if(fault==='identity-view'&&url.startsWith('/api/households/shopping/items/')&&data.foodId)result.foodId=uuid();
      }
    }
    else if(method==='delete'&&objects[url]){result=objects[url];status=200;
      const reference=model.tasks.find(t=>t.kind==='reference_lifecycle');
      

      if(reference&&(fault==='reference-reject'||fault==='reference-reject-partial')){status=409;if(fault==='reference-reject-partial')for(const object of Object.values(objects))if(object.recipeIngredient)object.recipeIngredient[0].quantity=999;}else if(fault!=='delete-ignored'){
        delete objects[url];
        if(reference&&fault!=='reference-dangling'){
          const field=reference.rule.field_path.split('.').pop();
          for(const object of Object.values(objects))for(const ingredient of object.recipeIngredient||[]){if(ingredient[field]?.id===result.id)ingredient[field]=null;}
          if(fault==='reference-unrelated')for(const object of Object.values(objects))if(object.recipeIngredient?.length)object.recipeIngredient[0].quantity=999;
        }
        if(model.tasks.some(t=>t.kind==='attached_delete')&&fault!=='delete-dangling'){
          const field=url.startsWith('/api/organizers/tags/')?'tags':url.startsWith('/api/organizers/categories/')?'recipeCategory':null;
          if(field)for(const object of Object.values(objects))if(Array.isArray(object[field]))object[field]=object[field].filter(x=>x.id!==result.id);
        }
      }
      if(fault==='delete-unrelated-links'){for(const object of Object.values(objects))if(object.recipeIngredient)object.recipeIngredient=[];}
      if(fault==='delete-cascades-source'){const recipe=Object.keys(objects).find(k=>k.startsWith('/api/recipes/'));if(recipe)delete objects[recipe];}
    }
    else if(method==='get'){status=404;result={detail:'Not found'};}
    else if(method==='post'&&url.includes('/recipe/')){const offset=url.lastIndexOf('/recipe/'),source=url.slice(0,offset),target=url.slice(offset+8);result=objects[source];assert(result);result.recipeReferences.push({recipeId:target});status=200;}
    else throw new Error('Unrecognized mock HTTP '+method+' '+url);
    callbackBytes+=Buffer.byteLength(JSON.stringify(options.callback.toString()));
    options.callback=vm.runInContext('('+options.callback.toString()+')',context);
    options.callback({code:status,body:JSON.stringify(result),headers:{}});
  }finally{activeRequests--;}
}
const context={console,Date:class extends Date{static now(){return 123456789;}},JSON,
  pvg:{rtv:{get:k=>rtv[k]===undefined&&missingMode==='opaque-object'?{}:rtv[k],set:(k,v)=>{rtv[k]=v;}},success:()=>{},fail:message=>{failures.push(message);}},
  Event:(name,data)=>({name,data}),EventSet:(name,matches)=>({name,matches}),
  bthread:(name,fn)=>{actors.push({name,iterator:fn(),state:null,done:false});},
  RESTSession:function(){for(const method of ['get','post','put','patch','delete'])this[method]=(url,options)=>serve(method,url,options);}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,fs.readdirSync(root).find(n=>/^interfaces\..+\.js$/.test(n))),'utf8'),context);
const source=fs.readFileSync(path.join(root,fs.readdirSync(root).find(n=>/^stories\..+\.js$/.test(n))),'utf8').replace(/function\(\)\{/g,'function*(){').replace(/\bsync\(/g,'yield (');
vm.runInContext(source,context);
function matches(pattern,event){if(!pattern)return false;if(Array.isArray(pattern))return pattern.some(p=>matches(p,event));if(pattern.matches)return pattern.matches(event);return pattern.name===event.name&&JSON.stringify(pattern.data)===JSON.stringify(event.data);}
function advance(actor){const next=actor.iterator.next(actor.event);actor.done=next.done;actor.state=next.value;}
let error=null;
try{
  actors.forEach(advance);
  for(let rounds=0;rounds<1000&&actors.some(a=>!a.done);rounds++){
    const candidates=actors.filter(a=>!a.done&&a.state?.request).map(a=>a.state.request).filter(event=>!actors.some(a=>!a.done&&matches(a.state?.block,event)));
    assert(candidates.length,'Generated actor graph deadlocked');const event=candidates[pick(candidates.length)];selected.push(event);
    if(event.name==='SBT:RelTask')currentTask=event.data.id;
    if(event.name==='SBT:RelTaskDone')currentTask=null;
    const resume=actors.filter(a=>!a.done&&(matches(a.state?.request,event)||matches(a.state?.waitFor,event)));
    for(const actor of resume){actor.event=event;advance(actor);}
  }
  assert(actors.every(a=>a.done),'Actor budget exhausted');assert(selected.some(e=>e.name==='SBT:RelScenarioComplete'));
  assert.strictEqual(selected.filter(e=>e.name==='SBT:RelTaskDone').length,model.tasks.length);
  assert.strictEqual(maximumActive,1);
  assert.strictEqual(JSON.parse(rtv.sbt_rel_owned).length,Object.values(model.instances).reduce((n,x)=>n+x.length,0));
  assert.strictEqual(failures.length,0);
  for(const task of model.tasks.filter(t=>t.kind==='attached_delete')){
    const calls=requests.filter(r=>r.task===task.id);
    assert.strictEqual(calls.filter(r=>r.method==='delete').length,1);
    assert(!calls.some(r=>r.method==='put'||r.method==='patch'),'Attached deletion silently detached before deleting');
  }
  const receipt=JSON.parse(rtv.sbt_rel_execution_receipt);
  assert.strictEqual(receipt.task_count,model.tasks.length);assert.strictEqual(receipt.response_count,requests.length);
  assert.strictEqual(receipt.negative_tests.length,model.tasks.filter(t=>t.kind==='negative_link').length);
  for(const r of receipt.negative_tests){assert.strictEqual(r.code,400);assert.strictEqual(r.source_unchanged,true);const task=model.tasks.find(t=>t.id===r.task_id);if(task.verify_cycle_members){assert.strictEqual(r.all_members_unchanged,true);assert.deepStrictEqual(r.member_checks.map(x=>x.instance).sort(),[...task.cycle_path].sort());assert(r.member_checks.every(x=>x.unchanged));}}
  for(const task of model.tasks.filter(t=>t.legal_readback&&t.kind!=='negative_link')){const record=receipt.legal_tests.find(r=>r.task_id===task.id);assert(record&&record.source_readback);assert.deepStrictEqual(record.targets_read.sort(),[...task.target_instances].sort());if(task.kind==='unlink')assert.strictEqual(record.observed.length,0);}
  for(const task of model.tasks.filter(t=>t.verify_cycle_members)){
    function route(instance){const snapshot=JSON.parse(rtv[model.instance_metadata[instance].snapshot_variable]);return Object.keys(objects).find(url=>objects[url].id===snapshot.id);}
    const members=task.cycle_path.slice(0,-1).map(route),source=route(task.source_instance),observed=requests.filter(r=>r.task===task.id);
    assert.deepStrictEqual(observed.map(r=>r.url),[...members,source,source,source,...members]);
    assert.deepStrictEqual(observed.map(r=>r.method),[...members.map(()=> 'get'),'get','put','get',...members.map(()=> 'get')]);
  }
}catch(e){error=e;}
if(fault&&fault!=='reference-reject'){assert(error,'Injected fault was not rejected');assert(!selected.some(e=>e.name==='SBT:RelScenarioComplete'));if(['unsynchronized-view','identity-view','ignored-recipe-field','association-readback'].includes(fault))assert(failures.some(message=>message.startsWith('Relationship readback mismatch:')), 'Expected identity readback failure');if(fault==='projection-null')assert(failures.some(message=>message.startsWith('Source projection:')||message.startsWith('Create response contract:')));if(fault.startsWith('cycle-')){assert.strictEqual(requests[requests.length-1].method,'get');const evidence=JSON.parse(rtv.sbt_rel_last_cycle_probe);assert(evidence.cycle_length>=2);if(fault==='cycle-mutates-on-reject')assert.strictEqual(evidence.source_unchanged,false);else if(fault==='cycle-target-mutates-on-reject'){assert.strictEqual(evidence.source_unchanged,true);assert(evidence.member_checks.some(x=>!x.unchanged));}else assert.notStrictEqual(evidence.code,400);}process.stdout.write('PASS: rejected '+fault+'; no scenario completion.\n');}
else{if(error)throw error;process.stdout.write(JSON.stringify({result:'NODE_STUB_PASS',seed,tasks:model.tasks.length,http_requests:requests.length,serialized_callback_bytes:callbackBytes,max_active_http:maximumActive,receipt:JSON.parse(rtv.sbt_rel_execution_receipt),shared_updates:JSON.parse(rtv.sbt_rel_execution_receipt).shared_updates||[],detached_deletions:JSON.parse(rtv.sbt_rel_execution_receipt).detached_deletions||[],task_order:selected.filter(e=>e.name==='SBT:RelTask').map(e=>e.data.id)})+'\n');}
