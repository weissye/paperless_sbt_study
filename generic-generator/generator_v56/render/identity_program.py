"""Opt-in generic programs with explicit authentication and typed HTTP boundaries.

Application operations, scopes, expectations and templates live in profiles.
Legacy compilation is untouched when identity_program is absent.
"""
import copy
import json
import re

RUNTIME = r'''
function sbtIdentityRuntime(response,ctx,cfg){
 function uuid(){return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,function(c){var r=Math.floor(Math.random()*16);return (c==='x'?r:(r&3)|8).toString(16);});}
 function load(){var v=pvg.rtv.get('idp_state');return v?JSON.parse(v):{observations:{},order:[],namespace:'sbt-idp-'+uuid(),tokens:{}};}
 function path(node,p){if(!p)return node;var parts=p.split('.');for(var i=0;i<parts.length;i++){if(node===null||node===undefined)throw new Error('Missing template path '+p);node=node[parts[i]];}if(node===undefined)throw new Error('Missing template value '+p);return node;}
 if(ctx.step.id===cfg.steps[0].id)pvg.rtv.set('idp_state',JSON.stringify({observations:{},order:[],namespace:'sbt-idp-'+uuid(),tokens:{}}));
 var st=load();
 function resolve(v){if(v===null||typeof v!=='object')return v;if(Array.isArray(v))return v.map(resolve);if(v.$response){var ob=st.observations[v.$response[0]];if(!ob)throw new Error('Not ready');return path(ob.body,v.$response[1]);}if(v.$env){var e=String(Packages.java.lang.System.getenv(v.$env)||'');if(!e)throw new Error('Missing credential environment '+v.$env);return e;}if(v.$namespace!==undefined)return st.namespace+v.$namespace;if(v.$and)return v.$and.every(function(x){return resolve(x)===true;});if(v.$equal)return JSON.stringify(resolve(v.$equal[0]))===JSON.stringify(resolve(v.$equal[1]));if(v.$not_equal)return JSON.stringify(resolve(v.$not_equal[0]))!==JSON.stringify(resolve(v.$not_equal[1]));if(v.$uuid)return uuid();if(v.$merge){var out=JSON.parse(JSON.stringify(resolve(v.$merge[0]))),patch=resolve(v.$merge[1]);Object.keys(patch).forEach(function(k){out[k]=patch[k];});return out;}var o={};Object.keys(v).forEach(function(k){o[k]=resolve(v[k]);});return o;}
 function schema(n){while(n&&n.$ref)n=cfg.schemas[n.$ref.split('/').pop()];return n;}
 function project(n,v){n=schema(n)||{};if(v===null)return null;if(n.anyOf||n.oneOf){var branches=n.anyOf||n.oneOf;for(var i=0;i<branches.length;i++){var b=schema(branches[i]);if((b.type==='object'||b.properties)&&v&&typeof v==='object'&&!Array.isArray(v))return project(b,v);if(b.type==='array'&&Array.isArray(v))return project(b,v);if(b.type===typeof v)return project(b,v);}return v;}if(n.type==='array')return v.map(function(x){return project(n.items,x);});if(n.properties){var out={};Object.keys(v||{}).forEach(function(k){if(n.properties[k]&&!n.properties[k].readOnly)out[k]=project(n.properties[k],v[k]);});return out;}return v;}
 function prepare(){cfg.steps.forEach(function(s){try{var route=resolve(s.route||{});Object.keys(route).forEach(function(k){pvg.rtv.set('idp_route_'+s.id+'_'+k,String(route[k]));});if(s.authenticate){var a=cfg.actors[s.actor];pvg.rtv.set('idp_body_'+s.id,'grant_type=password&username='+encodeURIComponent(resolve(a.username))+'&password='+encodeURIComponent(resolve({$env:a.password_env})));}else if(s.body!==undefined)pvg.rtv.set('idp_body_'+s.id,JSON.stringify(project(s.request_schema,resolve(s.body))));}catch(e){/* Unready dependent input; admission is controlled by generated prerequisites. */}});}
 var s=ctx.step;
 if(ctx.bootstrap){pvg.rtv.set('idp_state',JSON.stringify(st));prepare();return;}
 var body;try{body=JSON.parse(response.body);}catch(e){body=response.body;}
 if(s.authenticate){if(response.code!==200||!body||!body.access_token)throw new Error('Identity login failed for '+s.actor);st.tokens[s.actor]=true;pvg.rtv.set('idp_token_'+s.actor,body.access_token);body={authenticated:true};}
 var ob={actor:s.actor,operation:s.operation,code:response.code,body:body};
 if(s.body!==undefined){try{ob.request_body=JSON.parse(pvg.rtv.get('idp_body_'+s.id));if(ob.request_body.password)ob.request_body.password='<REDACTED>';}catch(e){}}
 st.observations[s.id]=ob;st.order.push(s.id);
 pvg.rtv.set('idp_state',JSON.stringify(st));
 if(s.required&&s.expected_codes.indexOf(response.code)<0)throw new Error('Identity setup/control failed at '+s.id+' code '+response.code);
 if(s.guard){var g=resolve(s.guard);if(g!==true)throw new Error('Identity guard failed at '+s.id);}
 prepare();
 if(ctx.finish){var receipt={status:'LIVE_CALLBACKS_COMPLETE',task_count:cfg.steps.length,response_count:st.order.length,owned_instances:cfg.owned_count,identity_program:{observations:st.observations,order:st.order,namespace:st.namespace}};pvg.rtv.set('sbt_rel_execution_receipt',JSON.stringify(receipt));pvg.success('SBT_REL_LIVE_RECEIPT '+JSON.stringify(receipt));}
}
'''


def compile_identity_program(raw, runtime):
    if set(runtime) != {'contract_sha256','identity_program'}:
        raise ValueError('Identity programs require an isolated explicit runtime profile.')
    cfg=copy.deepcopy(runtime['identity_program'])
    if set(cfg)!= {'actors','bootstrap_actor','steps','checks','label'}:
        raise ValueError('Invalid identity program keys.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',cfg['label']):raise ValueError('Invalid program label.')
    schemas=raw.get('components',{}).get('schemas',{})
    def root(n):
        while '$ref' in n:n=schemas[n['$ref'].split('/')[-1]]
        return n
    def raw_op(identity):
        method,path=identity.split(' ',1)
        if method not in ('GET','POST','PUT','PATCH','DELETE') or path not in raw['paths'] or method.lower() not in raw['paths'][path]:raise ValueError('Operation outside OpenAPI: '+identity)
        return raw['paths'][path][method.lower()]
    flows=[s.get('flows',{}).get('password') for s in raw.get('components',{}).get('securitySchemes',{}).values()]
    urls={f['tokenUrl'] for f in flows if f}
    if len(urls)!=1 or not next(iter(urls)).startswith('/'):raise ValueError('One documented local password flow required.')
    auth='POST '+next(iter(urls)); authraw=raw_op(auth)
    form=root(authraw.get('requestBody',{}).get('content',{}).get('application/x-www-form-urlencoded',{}).get('schema',{}))
    if not {'username','password'}.issubset(form.get('properties',{})):raise ValueError('Undocumented OAuth password fields.')
    if cfg['bootstrap_actor'] not in cfg['actors']:raise ValueError('Unknown bootstrap actor.')
    for actor,a in cfg['actors'].items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',actor) or set(a)!= {'username','password_env'} or not re.fullmatch(r'[A-Z][A-Z0-9_]*',a['password_env']):raise ValueError('Invalid actor credential policy.')
    ids=[]; tasks=[]; calls={}; functions=[]; contexts=[]; owners={}; owned=[]
    def refs(value):
        if isinstance(value,dict):
            if '$response' in value:
                if set(value)!={'$response'} or not isinstance(value['$response'],list) or len(value['$response'])!=2:raise ValueError('Invalid response reference.')
                yield value['$response'][0]
            else:
                for v in value.values():yield from refs(v)
        elif isinstance(value,list):
            for v in value:yield from refs(v)
    for s in cfg['steps']:
        if set(s)-{'id','actor','operation','after','route','body','expected_codes','required','authenticate','owned','guard'}:raise ValueError('Unknown identity step policy.')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',s['id']) or s['id'] in ids or s['actor'] not in cfg['actors']:raise ValueError('Invalid/duplicate step identity.')
        op=raw_op(s['operation']); method,path=s['operation'].split(' ',1)
        if s.get('authenticate') and s['operation']!=auth:raise ValueError('Authentication outside declared flow.')
        if not isinstance(s.get('expected_codes'),list) or not s['expected_codes'] or any(type(c)!=int or not 200<=c<600 for c in s['expected_codes']):raise ValueError('Invalid expected HTTP codes.')
        if s.get('required') and any(str(c) not in op['responses'] for c in s['expected_codes']):raise ValueError('Required success is not documented.')
        params={p['name'] for p in op.get('parameters',[]) if p['in']=='path'}
        if params!=set(s.get('route',{})):raise ValueError('Every path parameter needs an explicit binding.')
        deps=set(s.get('after',[]))|set(refs(s.get('route',{})))|set(refs(s.get('body',{})))|(set(refs(s.get('guard',{})))-{s['id']})
        actor_prev=owners.get(s['actor']);
        if actor_prev:deps.add(actor_prev)
        if deps-set(ids):raise ValueError('Unresolved/forward dependency at '+s['id'])
        if not s.get('authenticate') and s['actor']!=cfg['bootstrap_actor'] and not any(x.get('authenticate') and x['actor']==s['actor'] for x in cfg['steps'][:len(ids)]):raise ValueError('Actor used before explicit login.')
        if 'body' in s:
            content=op.get('requestBody',{}).get('content',{})
            if 'application/json' not in content:raise ValueError('JSON body not documented.')
            s['request_schema']=content['application/json']['schema']
        elif op.get('requestBody',{}).get('required') and not s.get('authenticate'):raise ValueError('Missing required request body.')
        if s.get('owned'):owned.append(s['id'])
        task={'id':s['id'],'kind':'identity_program','instance':s['actor'],'source_instance':s['actor'],'after':sorted(deps),'executable':True}
        tasks.append(task);ids.append(s['id']);owners[s['actor']]=s['id']
        for p in params:path=path.replace('{'+p+'}','@{idp_route_'+s['id']+'_'+p+'}')
        options={'expectedResponseCodes':list(range(200,600)),'headers':{}}
        if s.get('authenticate'):options['headers']['Content-Type']='application/x-www-form-urlencoded';options['body']='@{idp_body_'+s['id']+'}'
        else:options['headers']['Authorization']='Bearer @{idp_token_'+s['actor']+'}'
        if 'body' in s:options['headers']['Content-Type']='application/json';options['body']='@{idp_body_'+s['id']+'}'
        if not ids[:-1] and s.get('authenticate'):
            a=cfg['actors'][s['actor']]
            if not isinstance(a['username'],dict) or set(a['username'])!={'$env'}:raise ValueError('Bootstrap username requires an environment binding.')
            options['body']="grant_type=password&username=@{encodeURIComponent(getEnv('"+a['username']['$env']+"'))}&password=@{encodeURIComponent(getEnv('"+a['password_env']+"'))}"
        name='sbtIdentityHttp_'+str(len(functions)+1);ctx={'step':s,'finish':False}
        rendered=json.dumps(options,separators=(',',':'))[:-1]+',callback:sbtIdentityCallback('+json.dumps(ctx,separators=(',',':'))+')}';functions.append('function '+name+'(){svc.'+method.lower()+'('+json.dumps(path)+','+rendered+');}')
        calls[s['id']]=name+'();';contexts.append({'operation':s['operation'],'actor':s['actor']})
    if not ids:raise ValueError('Empty identity program.')
    def response_node(step_id,path):
        if step_id not in ids:raise ValueError('Unknown response reference: '+step_id)
        step=cfg['steps'][ids.index(step_id)];op=raw_op(step['operation'])
        responses=[v['content']['application/json']['schema'] for c,v in op['responses'].items() if c.isdigit() and 200<=int(c)<300 and 'application/json' in v.get('content',{})]
        if not responses:raise ValueError('No documented JSON response: '+step['operation'])
        node=responses[0]
        for part in path.split('.') if path else []:
            n=root(node);branches=n.get('anyOf',n.get('oneOf',[n]));nodes=[root(x) for x in branches if root(x).get('type')!='null']
            if part.isdigit():
                arrays=[x for x in nodes if x.get('type')=='array']
                if len(arrays)!=1:raise ValueError('Invalid response array index.')
                node=arrays[0]['items'];continue
            name=part.removesuffix('[]');matches=[x['properties'][name] for x in nodes if name in x.get('properties',{})]
            if not matches:raise ValueError('Undocumented response path: '+step_id+'.'+path)
            node=matches[0]
            if part.endswith('[]'):
                n=root(node);branches=n.get('anyOf',n.get('oneOf',[n]));arrays=[root(x) for x in branches if root(x).get('type')=='array']
                if len(arrays)!=1:raise ValueError('Invalid response array path.')
                node=arrays[0]['items']
        return node
    def inspect_refs(value):
        if isinstance(value,dict):
            if '$response' in value:response_node(*value['$response'])
            for v in value.values():inspect_refs(v)
        elif isinstance(value,list):
            for v in value:inspect_refs(v)
    def validate_template(node,value):
        if value is None:return
        n=root(node);branches=n.get('anyOf',n.get('oneOf',[n]));nodes=[root(x) for x in branches if root(x).get('type')!='null']
        if isinstance(value,dict) and any(k.startswith('$') for k in value):
            if len(value)!=1 or next(iter(value)) not in {'$merge','$response','$env','$namespace','$uuid','$equal','$not_equal','$and'}:raise ValueError('Unknown template instruction.')
            if '$merge' in value:validate_template(node,value['$merge'][1])
            return
        if isinstance(value,dict):
            for key,v in value.items():
                children=[x['properties'][key] for x in nodes if key in x.get('properties',{}) and not x['properties'][key].get('readOnly')]
                if not children:raise ValueError('Undocumented writable body field: '+key)
                validate_template(children[0],v)
        elif isinstance(value,list):
            arrays=[x for x in nodes if x.get('type')=='array']
            if len(arrays)!=1:raise ValueError('Undocumented body array.')
            for v in value:validate_template(arrays[0]['items'],v)
    for step in cfg['steps']:
        inspect_refs(step)
        if 'body' in step:validate_template(step['request_schema'],step['body'])
    for c in cfg['checks']:
        if set(c)!={'id','operator','left','right'} or c['operator'] not in {'equal','not_equal','subset'}:raise ValueError('Invalid independent qualification check.')
        for side in ('left','right'):
            if isinstance(c[side],dict) and set(c[side])=={'response'}:response_node(*c[side]['response'])
    # A final dedicated observation is ordered after all actors, rather than relying on source order.
    tasks[-1]['after']=ids[:-1]
    functions[-1]=functions[-1].replace('"finish":false','"finish":true')
    selected={}
    def collect(node):
        if isinstance(node,dict):
            if '$ref' in node:
                name=node['$ref'].split('/')[-1]
                if name not in selected:selected[name]=schemas[name];collect(selected[name])
            for k,v in node.items():
                if k not in ('example','examples','default','enum','const'):collect(v)
        elif isinstance(node,list):
            for v in node:collect(v)
    for s in cfg['steps']:collect(s.get('request_schema'))
    cfg['schemas']=selected;cfg['owned_count']=len(owned)
    factory = r'''function sbtIdentityCallback(ctx){
var setup=ctx.step.id===sbtIdentityConfig.steps[0].id?"pvg.rtv.set('idp_runtime',"+JSON.stringify(sbtIdentityRuntime.toString())+");pvg.rtv.set('idp_config',"+JSON.stringify(JSON.stringify(sbtIdentityConfig))+");":"";
var invocation="var code='function(response,contextJson,configJson,pvg){return ('+pvg.rtv.get('idp_runtime')+')(response,JSON.parse(contextJson),JSON.parse(configJson));}';var cx=Packages.org.mozilla.javascript.Context.getCurrentContext();var fn=cx.compileFunction(cx.initStandardObjects(),code,'identity-runtime',1,null);fn(response,"+JSON.stringify(JSON.stringify(ctx))+",pvg.rtv.get('idp_config'),pvg);";
var hydrate="Packages.org.mozilla.javascript.Context.getCurrentContext().initStandardObjects(Packages.org.mozilla.javascript.ScriptableObject.getTopLevelScope(this));";
if(typeof Packages!=="undefined"){var scope=new Packages.org.mozilla.javascript.NativeObject();(new Packages.org.mozilla.javascript.ClassCache()).associate(scope);return Packages.org.mozilla.javascript.Context.getCurrentContext().compileFunction(scope,"function(response,arguments){"+hydrate+setup+invocation+"}","identity-callback",1,null);}
return new Function("response","("+sbtIdentityRuntime.toString()+")(response,"+JSON.stringify(ctx)+","+JSON.stringify(sbtIdentityConfig)+");");}
'''
    interfaces='\nconst sbtIdentityConfig='+json.dumps(cfg,separators=(',',':'))+';\n'+RUNTIME+factory+'\n'+ '\n'.join(functions)
    # Initialize only during the first live authentication callback, never at sampling time.
    first=cfg['steps'][0]
    if not first.get('authenticate') or first['actor']!=cfg['bootstrap_actor']:raise ValueError('Bootstrap must authenticate the configured provisioning actor.')
    dependencies={t['id']:t['after'] for t in tasks}
    stories=['// @provengo summon rest\n// @provengo summon rtv\n// Explicit actor contexts; serial HTTP admission.',
      'bthread("identity-bootstrap",function(){sync({request:Event("SBT:RelBootstrapDone")});});',
      'bthread("identity-coordinator",function(){var done={},active=null,n=0,deps='+json.dumps(dependencies)+';while(n<'+str(len(tasks))+'){var e=sync({waitFor:EventSet("idp-progress",function(e){return e.name==="SBT:RelTask"||e.name==="SBT:RelTaskDone";}),block:EventSet("idp-admission",function(e){return e.name==="SBT:RelTask"&&(active!==null||!deps[e.data.id].every(function(x){return done[x];}));})});if(e.name==="SBT:RelTask")active=e.data.id;else{if(active!==e.data.id)throw new Error("Unowned task");done[e.data.id]=true;active=null;n++;}}sync({request:Event("SBT:RelScenarioComplete",{tasks:n})});});']
    for actor in cfg['actors']:
        body='sync({waitFor:Event("SBT:RelBootstrapDone")});'
        for t in tasks:
            if t['instance']!=actor:continue
            data=json.dumps({'id':t['id'],'owner':actor});body+='sync({request:Event("SBT:RelTask",'+data+')});'+calls[t['id']]+'sync({request:Event("SBT:RelTaskDone",'+data+')});'
        stories.append('bthread('+json.dumps('identity:'+actor)+',function(){'+body+'});')
    blueprint={'status':'COMPILED_NOT_LIVE_ACCEPTED','tasks':tasks,'instances':{'identity_program':owned},'identity_program':{k:v for k,v in cfg.items() if k!='schemas'},'reset_replay_accepted':False}
    report={'status':'COMPILED_NOT_LIVE_ACCEPTED','task_count':len(tasks),'http_requests_per_complete_schedule':len(tasks),'symbolic_actor_count':len(cfg['actors']),'identity_actor_count':len(cfg['actors']),'regular_actor_count':len(cfg['actors'])-1,'active_operations':sorted({s['operation'] for s in cfg['steps']}),'live_accepted':False,'full_json_schema_validator':False,'policy':'EXPLICIT_PER_ACTOR_AUTHENTICATION_AND_SCOPE_EXPECTATIONS'}
    return interfaces,'\n'.join(stories)+'\n',blueprint,report,contexts
