"""Bounded, owned-resource functional stage. Native scheduling; explicit transport adapter."""
import argparse, copy, hashlib, json, os, re, secrets, shutil, subprocess, sys, threading, time, uuid, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlencode

PIN='7840d7816133c13fdeb43e1cd9a3013c7fff886538f5612bff3d0b42b2119d0c'
class Incomplete(Exception): pass
class Discrepancy(Exception): pass

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')

def synthetic_pdf(text):
    # Printable ASCII PDF with embedded searchable text; unique input avoids duplicate ingestion.
    text=text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    stream=('BT /F1 14 Tf 40 740 Td ('+text+') Tj ET\n').encode('ascii')
    objs=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
          b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
          b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
          b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    data=b'%PDF-1.4\n';offsets=[0]
    for i,o in enumerate(objs,1):
        offsets.append(len(data));data+=str(i).encode()+b' 0 obj\n'+o+b'\nendobj\n'
    start=len(data);data+=b'xref\n0 6\n0000000000 65535 f \n'
    for o in offsets[1:]:data+=('%010d 00000 n \n'%o).encode()
    data+=b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n'
    return data

def multipart(fields,filename,data):
    boundary='sbt-'+uuid.uuid4().hex;out=b''
    for key,value in fields.items():
        out+=('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+str(value)+'\r\n').encode()
    out+=('--'+boundary+'\r\nContent-Disposition: form-data; name="document"; filename="'+filename+'"\r\nContent-Type: application/pdf\r\n\r\n').encode()+data+b'\r\n'
    out+=('--'+boundary+'--\r\n').encode()
    return out,'multipart/form-data; boundary='+boundary

class Transport:
    def __init__(self,base,out,username,password,owner):
        self.base=base;self.out=out;self.username=username;self.password=password;self.owner=owner
        self.token=None;self.sequence=0;self.lock=threading.Lock();self.step=None
    def request(self,method,path,body=None,content_type='application/json'):
        with self.lock:
            self.sequence+=1;seq=self.sequence
            headers={'Accept':'application/json; version=10'}
            if self.token:headers['Authorization']='Token '+self.token
            payload=body
            if body is not None:
                headers['Content-Type']=content_type
                if not isinstance(body,bytes):payload=json.dumps(body,separators=(',',':')).encode()
            started=time.time()
            try:
                with urlopen(Request(self.base+path,data=payload,headers=headers,method=method),timeout=25) as r:
                    code=r.status;raw=r.read()
            except HTTPError as e:code=e.code;raw=e.read()
            except Exception as e:
                dump(self.out/'http'/('%04d.json'%seq),{'sequence':seq,'step':self.step,'method':method,'path':path,'started':started,'transport_error':type(e).__name__})
                raise Incomplete('Target transport failed: '+type(e).__name__)
            try:response=json.loads(raw)
            except (ValueError,UnicodeDecodeError):response={'unparsed_body':raw.decode('utf-8',errors='replace')}
            # Authentication payloads are deliberately never persisted, even in native logs.
            saved_body=body if not isinstance(body,bytes) else {'multipart_bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
            saved_response=response
            if path=='/api/token/':saved_body={'username':self.username,'password':'<REDACTED>'};saved_response={'token_present':bool(isinstance(response,dict) and response.get('token'))}
            dump(self.out/'http'/('%04d.json'%seq),{'sequence':seq,'step':self.step,'method':method,'path':path,'started':started,'ended':time.time(),'content_type':headers.get('Content-Type'),'request_body':saved_body,'http_status':code,'response_body':saved_response})
            return code,response
    def login(self):
        code,b=self.request('POST','/api/token/',{'username':self.username,'password':self.password})
        if code!=200 or not isinstance(b,dict) or not b.get('token'):raise Incomplete('Ordinary user authentication failed.')
        self.token=b['token'];self.password=None

class Engine:
    def __init__(self,profile,case,namespace,transport,out):
        self.profile=profile;self.case=case;self.ns=namespace;self.t=transport;self.out=out
        self.ids={};self.tasks={};self.expected={};self.protected={};self.checks=[];self.done=[];self.failed=None
        self.mutex=threading.Lock();self.started=False;self.completed=False
    def resolve(self,value):
        if isinstance(value,list):return [self.resolve(x) for x in value]
        if isinstance(value,dict):return {k:self.resolve(v) for k,v in value.items()}
        if isinstance(value,str):
            if value=='$owner':return self.t.owner
            if value.startswith('$id:'):return self.ids[value[4:]]
            return value.replace('$namespace',self.ns)
        return value
    def path(self,spec):
        path=spec['path']
        if '{id}' in path:path=path.replace('{id}',str(self.ids[spec['entity']]))
        return path
    def expect_status(self,code,spec):
        if code not in spec['codes']:
            raise Incomplete('Unexpected target HTTP %s for %s %s; inspect saved response.'%(code,spec['method'],spec['path']))
    def record_check(self,label,expected,observed):
        item={'check':label,'expected':expected,'observed':observed,'passed':expected==observed,'native_step':self.t.step}
        self.checks.append(item);dump(self.out/'checks.json',self.checks)
        if not item['passed']:raise Discrepancy(label)
    def capture(self,entity,body):
        if not isinstance(body,dict) or not isinstance(body.get('id'),int) or isinstance(body.get('id'),bool):raise Incomplete('Missing returned resource identity.')
        if body['id'] in [self.ids[x] for x in ('A','B') if x in self.ids] and entity in ('A','B'):raise Discrepancy('Distinct documents resolved to one id')
        self.ids[entity]=body['id'];self.record_check(entity+'.owner',self.t.owner,body.get('owner'))
        if entity in ('A','B'):
            self.expected[entity]={'id':body['id'],'owner':self.t.owner,'tags':[],'document_type':None,'title':self.ns+'-'+entity}
            self.protected[entity]={k:copy.deepcopy(body[k]) for k in self.profile['document_protected_fields'] if k in body}
        dump(self.out/'bindings.json',{'ordinary_user_id':self.t.owner,'ids':self.ids,'ingestion_tasks':self.tasks})
    def verify(self,entity,body):
        for k,v in self.expected[entity].items():
            obs=body.get(k)
            if k=='tags':v=sorted(v);obs=sorted(obs) if isinstance(obs,list) else obs
            self.record_check(entity+'.'+k,v,obs)
        for k,v in self.protected.get(entity,{}).items():self.record_check(entity+'.protected.'+k,v,body.get(k))
    def wait(self,entity):
        entry=self.tasks[entity]
        if entry.get('ready'):return {'ready':True,'document_id':self.ids[entity]}
        deadline=min(entry['deadline'],time.monotonic()+self.profile['poll_window_seconds'])
        while True:
            code,b=self.t.request('GET','/api/tasks/?'+urlencode({'task_id':entry['task_id'],'page_size':100}))
            if code!=200:raise Incomplete('Task polling HTTP '+str(code))
            records=b if isinstance(b,list) else b.get('results',[]) if isinstance(b,dict) else []
            matched=[r for r in records if r.get('task_id')==entry['task_id']]
            if len(matched)>1:raise Incomplete('Ambiguous ingestion task binding.')
            if matched:
                task=matched[0];status=task.get('status')
                if status in ('failure','revoked'):raise Incomplete('Document ingestion '+status)
                if status=='success':
                    ids=task.get('related_document_ids')
                    if not isinstance(ids,list) or len(ids)!=1 or not isinstance(ids[0],int):raise Incomplete('Successful ingestion did not return exactly one document id.')
                    code,body=self.t.request('GET','/api/documents/%s/'%ids[0])
                    if code!=200:raise Incomplete('Ingested document read failed.')
                    self.capture(entity,body);self.verify(entity,body);entry['ready']=True
                    dump(self.out/'bindings.json',{'ordinary_user_id':self.t.owner,'ids':self.ids,'ingestion_tasks':self.tasks})
                    return {'ready':True,'document_id':ids[0]}
            if time.monotonic()>=entry['deadline']:raise Incomplete('Ingestion timeout; no semantic verdict.')
            if time.monotonic()>=deadline:return {'ready':False}
            time.sleep(min(1,max(0,deadline-time.monotonic())))
    def execute(self,step_id):
        with self.mutex:
            if self.failed:raise Incomplete('Prior step failed; further actuation stopped.')
            spec=self.case['steps'][step_id];self.t.step=step_id
            if step_id in self.done:raise Incomplete('Duplicate step dispatch.')
            if not set(spec.get('after',[])).issubset(self.done):raise Incomplete('Step prerequisite violation.')
            try:
                kind=spec['kind'];result={}
                if kind=='start':
                    self.t.login();self.started=True;result={'ordinary_user_id':self.t.owner}
                elif kind=='upload':
                    entity=spec['entity'];data=synthetic_pdf('Paperless SBT synthetic document '+self.ns+' '+entity)
                    file=self.out/'inputs'/(entity+'.pdf');file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
                    body,ct=multipart({'title':self.ns+'-'+entity},entity+'.pdf',data)
                    code,b=self.t.request('POST',spec['path'],body,ct);self.expect_status(code,spec)
                    if not isinstance(b,str) or not b:raise Incomplete('Upload returned no string task id.')
                    self.tasks[entity]={'task_id':b,'deadline':time.monotonic()+self.profile['ingestion_timeout_seconds'],'ready':False,'input_sha256':hashlib.sha256(data).hexdigest()}
                    result={'task_id':b}
                elif kind=='wait':result=self.wait(spec['entity'])
                elif kind=='ready':
                    if any(not self.tasks.get(x,{}).get('ready') for x in ('A','B')):raise Incomplete('Documents not ready after bounded wait.')
                elif kind in ('create','patch','read','metadata'):
                    body=self.resolve(spec.get('body'))
                    code,b=self.t.request(spec['method'],self.path(spec),body);self.expect_status(code,spec)
                    if kind=='create':
                        entity=spec['entity'];self.capture(entity,b)
                        self.expected[entity]={'id':self.ids[entity],'owner':self.t.owner,'name':body['name']}
                        self.verify(entity,b)
                    elif kind=='patch':
                        entity=spec['entity'];self.expected[entity].update(copy.deepcopy(body));self.verify(entity,b)
                    elif kind=='read':self.verify(spec['entity'],b)
                    else:
                        entity=spec['entity'];self.record_check(entity+'.original_checksum',self.tasks[entity]['input_sha256'],b.get('original_checksum'))
                        self.record_check(entity+'.original_mime_type','application/pdf',b.get('original_mime_type'))
                    result={'target_status':code}
                elif kind=='finish':
                    expected=set(self.case['steps'])-{step_id}
                    if set(self.done)!=expected:raise Incomplete('Missing completed native steps.')
                    self.record_check('distinct_document_checksums',False,self.tasks['A']['input_sha256']==self.tasks['B']['input_sha256'])
                    self.completed=True
                    result={'status':'STAGE1_NATIVE_RECEIPT','case':self.case['id'],'completed_steps':len(self.done)+1,'checks':len(self.checks),'ids':self.ids,'ordinary_user_id':self.t.owner,'target_http_responses':self.t.sequence}
                    dump(self.out/'runtime-receipt.json',result)
                else:raise Incomplete('Unknown policy step kind.')
                self.done.append(step_id);dump(self.out/'step-order.json',self.done)
                return {'ok':True,'step':step_id,'result':result}
            except Exception as e:
                self.failed={'classification':'SEMANTIC_CANDIDATE' if isinstance(e,Discrepancy) else 'INCOMPLETE','step':step_id,'error':str(e)}
                dump(self.out/'failure.json',self.failed);raise

def serve(engine):
    key=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self,*args):pass
        def do_POST(self):
            # Drain the request body before executing; explicitly close each response.
            self.close_connection = True
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                self.send_error(413);return
            if len(self.rfile.read(length)) != length:
                self.send_error(400);return
            if self.headers.get('X-SBT-Key')!=key:self.send_error(403);return
            match=re.fullmatch(r'/sbt/step/([a-zA-Z0-9_-]+)',self.path)
            if not match:self.send_error(404);return
            try:payload=engine.execute(match[1]);status=200
            except Exception:payload={'ok':False,'failure':engine.failed or {'classification':'INCOMPLETE'}};status=409
            data=json.dumps(payload).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers();self.wfile.write(data);self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server,key

CALLBACK=r'''function stage1Callback(){
var source="if(typeof Packages!=='undefined'){Packages.org.mozilla.javascript.Context.getCurrentContext().initStandardObjects(Packages.org.mozilla.javascript.ScriptableObject.getTopLevelScope(this));}"+
"var data=JSON.parse(response.body);if(response.code!==200||data.ok!==true){pvg.fail('Stage1 transport/oracle failure');throw new Error('Stage1 step failed');}"+
"if(data.result&&data.result.status==='STAGE1_NATIVE_RECEIPT'){pvg.rtv.set('stage1_receipt',JSON.stringify(data.result));pvg.success('STAGE1_NATIVE_RECEIPT '+JSON.stringify(data.result));}";
if(typeof Packages!=='undefined'){var scope=new Packages.org.mozilla.javascript.NativeObject();(new Packages.org.mozilla.javascript.ClassCache()).associate(scope);return Packages.org.mozilla.javascript.Context.getCurrentContext().compileFunction(scope,"function(response,arguments){"+source+"}","stage1-callback",1,null);}
return new Function('response',source);}
'''
def compile_model(contract,profile,case,project):
    # Every domain operation must exist in the contract. Scalar bindings and invariants are explicit policy.
    for spec in case['steps'].values():
        if spec.get('path') and spec['method'].lower() not in contract['paths'].get(spec['path'],{}):raise ValueError('Operation outside pinned OpenAPI: '+spec['path'])
    specdir=project/'spec/js';specdir.mkdir(parents=True);(project/'config').mkdir()
    (project/'config/provengo.yml').write_text('version: 2\n',encoding='utf-8')
    interface='// @provengo summon rest\n// Explicit stage1 profile; all domain HTTP delegated to the recording transport.\nvar stage1Service=new RESTSession("@{getEnv(\'SBT_STAGE1_BRIDGE\')}");\n'+CALLBACK
    for step_id,spec in case['steps'].items():
        name='stage1_'+step_id
        interface+='function '+name+'(){stage1Service.post("/sbt/step/'+step_id+'",{headers:{"X-SBT-Key":"@{getEnv(\'SBT_STAGE1_KEY\')}","Content-Type":"application/json"},body:"{}",expectedResponseCodes:[200],callback:stage1Callback()});}\n'
    # One scheduler admits a task at a time, but ready actors compete according to dependencies.
    deps={k:v.get('after',[]) for k,v in case['steps'].items()}
    stories='// @provengo summon rest\n// @provengo summon rtv\n'
    stories+='bthread("stage1-coordinator",function(){var done={},active=null,deps='+json.dumps(deps,separators=(',',':'))+';var count=0;while(count<'+str(len(deps))+'){var e=sync({waitFor:EventSet("s1-progress",function(e){return e.name==="S1:Step"||e.name==="S1:Done";}),block:EventSet("s1-not-ready",function(e){return e.name==="S1:Step"&&(active!==null||!(deps[e.data.id]||[]).every(function(id){return done[id];}));})});if(e.name==="S1:Step")active=e.data.id;else{if(active!==e.data.id)throw new Error("Step completion without ownership");done[active]=true;active=null;count++;}}sync({request:Event("S1:Complete",{steps:'+str(len(deps))+'})});});\n'
    for k in deps:stories+='bthread("step:'+k+'",function(){sync({request:Event("S1:Step",{id:"'+k+'"})});stage1_'+k+'();sync({request:Event("S1:Done",{id:"'+k+'"})});});\n'
    (specdir/'interfaces.paperless.stage1.js').write_text(interface,encoding='utf-8')
    (specdir/'stories.paperless.stage1.js').write_text(stories,encoding='utf-8')
    dump(project/'stage1-plan.json',case)

def audit_sample(samples,case):
    if not isinstance(samples,list) or len(samples)!=1:raise ValueError('Exactly one sampled schedule required.')
    done=set();active=None;completion=0;order=[];http_steps=[]
    for e in samples[0]:
        n=e.get('name');data=e.get('data') or {}
        if n=='S1:Step':
            k=data.get('id')
            if active is not None or k not in case['steps'] or k in done or not set(case['steps'][k].get('after',[])).issubset(done):raise ValueError('Invalid sampled admission.')
            active=k;order.append(k)
        elif n=='S1:Done':
            if active is None or data.get('id')!=active or http_steps[-1:]!=[active]:raise ValueError('Invalid sampled completion.')
            done.add(active);active=None
        elif n=='POST' and data.get('lib')=='REST':
            url=data.get('url','')
            if active is None or not url.endswith('/sbt/step/'+active):raise ValueError('Unexpected sampled transport action.')
            http_steps.append(active)
        elif n=='S1:Complete':
            if active is not None or done!=set(case['steps']) or data.get('steps')!=len(done):raise ValueError('Incomplete native sample.')
            completion+=1
    if completion!=1 or len(http_steps)!=len(case['steps']) or len(order)!=len(case['steps']):raise ValueError('Truncated native sample.')
    return order

def provision(container,username,password):
    # Explicit local fixture setup through Docker. The ordinary user has no staff/superuser privileges.
    script='''import django,json,sys,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","paperless.settings")
django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
p=json.load(sys.stdin)
codes=["add_document","view_document","change_document","add_tag","view_tag","change_tag","add_documenttype","view_documenttype","change_documenttype","view_paperlesstask"]
perms=list(Permission.objects.filter(content_type__app_label="documents",codename__in=codes))
if set(x.codename for x in perms)!=set(codes):raise RuntimeError("Required fixture permissions missing")
u=get_user_model().objects.create_user(username=p["username"],password=p["password"],is_staff=False,is_superuser=False,is_active=True)
u.user_permissions.set(perms)
print("SBT_FIXTURE "+json.dumps({"id":u.id,"username":u.username,"is_staff":u.is_staff,"is_superuser":u.is_superuser,"permissions":sorted(u.get_all_permissions())}))
'''
    result=subprocess.run(['docker','exec','-i','--workdir','/usr/src/paperless/src',container,'python','-c',script],input=json.dumps({'username':username,'password':password}),text=True,capture_output=True,timeout=60)
    if result.returncode:raise Incomplete('Local user fixture setup failed: '+result.stderr[-1500:])
    for line in result.stdout.splitlines():
        if line.startswith('SBT_FIXTURE '):
            identity=json.loads(line[12:])
            if identity['is_staff'] or identity['is_superuser']:raise Incomplete('Fixture is not an ordinary user.')
            return identity
    raise Incomplete('No fixture identity receipt.')

def discover_container():
    r=subprocess.run(['docker','ps','--filter','publish=9930','--format','{{.Names}}'],capture_output=True,text=True,timeout=20)
    names=[x for x in r.stdout.splitlines() if x.strip()]
    if r.returncode or len(names)!=1:raise Incomplete('Specify -Container: expected exactly one running container publishing port 9930.')
    return names[0]

def native(root,command,project,env):
    sys.path.insert(0,str(root/'generic-generator/tools'))
    from relationship_execution import windows_batch_command
    executable=shutil.which('provengo')
    if not executable:raise Incomplete('Provengo not found on PATH.')
    args=[executable]+command+[str(project)]
    if os.name=='nt' and executable.lower().endswith(('.bat','.cmd')):args=windows_batch_command(args,os.environ.get('COMSPEC','cmd.exe'))
    return subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,timeout=900)

def bundle(folder):
    target=folder/'campaign.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file() and p!=target:z.write(p,p.relative_to(folder).as_posix())
    return target

def run(args):
    root=args.root.resolve();contract_path=root/'model/paperless-openapi.json';original=contract_path.read_bytes()
    if hashlib.sha256(original).hexdigest()!=PIN:raise Incomplete('Pinned contract byte checksum mismatch. No requests sent.')
    contract=json.loads(original);profile_path=root/'profiles/paperless-stage1-runtime.json';profile=json.loads(profile_path.read_text(encoding='utf-8-sig'))
    if profile.get('original_checksum_algorithm')!='sha256':raise Incomplete('Explicit SHA256 document checksum policy is required.')
    parsed=urlsplit(args.base_url)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port!=9930 or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username:raise Incomplete('Stage1 targets only the local study service on loopback port 9930.')
    if not shutil.which('provengo'):raise Incomplete('Provengo is not on PATH.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    campaign=root/'runs'/('stage1-'+stamp);campaign.mkdir(parents=True)
    print('Evidence directory: '+str(campaign),flush=True)
    dump(campaign/'registration.json',{'contract_sha256':PIN,'profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),'phase':'generate_sample_then_run','server':args.base_url,'identity_configuration':'one ordinary user / one client','case_count':3,'fresh_sets_per_case':2,'http_concurrency':False,'automatic_retry':False,'automatic_deletion':False,'reset_replay_accepted':False})
    selected=[(case,repetition) for case in profile['cases'] for repetition in (1,2)]
    if getattr(args,'remaining_from',None):
        from verify_stage1_partial import verify
        verify(args.remaining_from)
        selected=[(case,repetition) for case in profile['cases'] for repetition in (1,2) if (case['id'],repetition) in [('S1-INTERLEAVED-RENAME',2),('S1-DETACH-REATTACH',1),('S1-DETACH-REATTACH',2)]]
        dump(campaign/'continuation.json',{'original_campaign_sha256':hashlib.sha256(args.remaining_from.read_bytes()).hexdigest(),'fresh_resources':True,'selected':[(case['id'],rep) for case,rep in selected]})
    registration=json.loads((campaign/'registration.json').read_text())
    registration.update({'planned_schedules':[(case['id'],rep) for case,rep in selected], 'planned_run_count':len(selected), 'fresh_sets_per_case':None if len(selected)==3 else 2, 'case_count':len(set(case['id'] for case,rep in selected))})
    dump(campaign/'registration.json',registration)
    results=[];identity=None;password=None
    try:
        if not args.sample_only:
            container=args.container or discover_container()
            password=secrets.token_urlsafe(32);username='sbt_stage1_'+uuid.uuid4().hex[:16]
            identity=provision(container,username,password);dump(campaign/'ordinary-user.json',identity)
            print('Created ordinary fixture user '+username+' (no staff/superuser privileges).',flush=True)
        for case,repetition in selected:
            namespace='sbt-s1-'+uuid.uuid4().hex[:16];folder=campaign/(case['id'].lower()+'-'+str(repetition));folder.mkdir()
            project=folder/'model';compile_model(contract,profile,case,project)
            files={str(p.relative_to(project)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file()}
            dump(folder/'model-hashes.json',files)
            env=os.environ.copy()
            if not any('-Xmx' in env.get(k,'') for k in ('JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS')):env['JAVA_TOOL_OPTIONS']=(env.get('JAVA_TOOL_OPTIONS','')+' -Xmx1g').strip()
            env['SBT_STAGE1_BRIDGE']='http://127.0.0.1:1';env['SBT_STAGE1_KEY']='symbolic'
            samples=project/'samples.json'
            print('Sampling '+case['id']+' / fresh set '+str(repetition),flush=True)
            r=native(root,['--batch-mode','sample','--size','1','--algorithm','random','--max-length',str(4*len(case['steps'])+10),'-o',str(samples)],project,env)
            (folder/'sample-output.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
            if r.returncode or not samples.exists():raise Incomplete('Native sampling failed; inspect '+str(folder))
            order=audit_sample(json.loads(samples.read_text(encoding='utf-8-sig')),case)
            dump(folder/'sample-acceptance.json',{'status':'NATIVE_SYMBOLIC_SAMPLE_VERIFIED','step_count':len(order),'order':order,'samples_sha256':hashlib.sha256(samples.read_bytes()).hexdigest(),'model_hashes':files,'native_exit_code':r.returncode})
            if args.sample_only:
                results.append({'case':case['id'],'repetition':repetition,'status':'SAMPLE_ONLY'});continue
            transport=Transport(args.base_url.rstrip('/'),folder,identity['username'],password,identity['id'])
            engine=Engine(profile,case,namespace,transport,folder);server,key=serve(engine)
            env['SBT_STAGE1_BRIDGE']='http://127.0.0.1:'+str(server.server_port);env['SBT_STAGE1_KEY']=key
            print('Running '+case['id']+' / fresh set '+str(repetition)+'; resources are retained.',flush=True)
            try:
                r=native(root,['--batch-mode','run','--run-source',str(samples),'--run-id','1','--output-file',str(folder/'native-result.json')],project,env)
                native_text=(r.stdout+r.stderr).replace(key,'<REDACTED_LOCAL_KEY>')
                result_file=folder/'native-result.json'
                if result_file.exists():result_file.write_text(result_file.read_text(encoding='utf-8-sig').replace(key,'<REDACTED_LOCAL_KEY>'),encoding='utf-8')
                (folder/'run-output.txt').write_text(native_text,encoding='utf-8')
            finally:server.shutdown();server.server_close()
            observed=re.search(r"(?:STAGE1_NATIVE_RECEIPT\s+|setting\s+'stage1_receipt'\s+to\s+')(\{[^\n]+\})",native_text)
            accepted=engine.completed and not engine.failed and r.returncode==0 and observed is not None and 'Test Result: SUCCESS' in native_text
            if accepted:
                receipt=json.JSONDecoder().raw_decode(observed[1])[0]
                accepted=receipt==json.loads((folder/'runtime-receipt.json').read_text()) and receipt['completed_steps']==len(case['steps']) and engine.done==order
            status='STAGE1_FUNCTIONAL_PASS' if accepted else (engine.failed or {}).get('classification','INCOMPLETE')
            result={'case':case['id'],'repetition':repetition,'status':status,'native_exit_code':r.returncode,'runtime_receipt_observed':bool(observed),'step_count':len(engine.done),'target_responses':transport.sequence,'checks':len(engine.checks),'reset_replay_accepted':False,'automatic_retry':False,'automatic_deletion':False}
            dump(folder/'run-acceptance.json',result);results.append(result);print(status,flush=True)
            # Preserve first discrepancy and stop. Fresh confirmation is an explicit later task.
            if not accepted:raise Incomplete('Campaign stopped at first incomplete or candidate run. See evidence directory.')
    except Exception as e:
        dump(campaign/'campaign-error.json',{'classification':'INCOMPLETE','error':str(e),'source_resources_preserved':True})
        raise
    finally:
        password=None
        dump(campaign/'campaign-summary.json',{'status':('STAGE1_SAMPLES_COMPLETE' if args.sample_only else ('STAGE1_REMAINING_THREE_PASS' if len(selected)==3 else 'STAGE1_SIX_RUNS_PASS')) if len(results)==len(selected) and all(x['status'] in ('SAMPLE_ONLY','STAGE1_FUNCTIONAL_PASS') for x in results) else 'STAGE1_NOT_COMPLETE','runs':results,'automatic_retry':False,'automatic_deletion':False,'reset_replay_accepted':False})
        print('Review ZIP: '+str(bundle(campaign)),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--base-url',default='http://127.0.0.1:9930');parser.add_argument('--container');parser.add_argument('--sample-only',action='store_true');parser.add_argument('--remaining-from',type=Path)
    try:run(parser.parse_args())
    except Exception as e:print('STAGE1_NOT_ACCEPTED: '+str(e),file=sys.stderr);sys.exit(1)
