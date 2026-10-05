"""Version graph adapter. Target requests go through the common recording interface transport."""
import argparse,copy,hashlib,json,os,re,secrets,shutil,sys,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
import paperless_stage1 as s
from paperless_lifecycles import compile_model,business_order

class VersionEngine(s.Engine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.members={'A'};self.labels={};self.deleted=set();self.file_content={};self.pending=None
    def capture(self,entity,body):
        super().capture(entity,body)
        self.file_content[entity]=body.get('content')
    def request(self,method,path,body=None,content_type='application/json'):
        return self.t.request(method,path,body,content_type)
    def route(self,entity):return '/api/documents/%s/'%self.ids[entity]
    def checkpoint(self,key):
        # Capture the complete graph before interpreting any individual result.
        obs={}
        for entity in ('A','D','T','U','Y'):
            family='documents' if entity in ('A','D') else 'document_types' if entity=='Y' else 'tags'
            code,body=self.request('GET','/api/'+family+'/%s/'%self.ids[entity]);obs[entity]={'status':code,'body':body}
        for entity in sorted(self.members):
            query='?version='+str(self.ids[entity]);code,body=self.request('GET',self.route('A')+query);obs[entity+'_content']={'status':code,'body':body}
            code,body=self.request('GET',self.route('A')+'metadata/'+query);obs[entity+'_bytes']={'status':code,'body':body}
        code,body=self.request('GET',self.route('D')+'metadata/');obs['D_bytes']={'status':code,'body':body}
        code,body=self.request('GET',self.route('A')+'metadata/');obs['effective_bytes']={'status':code,'body':body}
        s.dump(self.out/'version-graph'/(key+'.json'),obs)
        for entity in ('A','D','T','U','Y'):self.record_check(entity+'.read_status',404 if entity in self.deleted else 200,obs[entity]['status'])
        # Root metadata is protected; content/file fields deliberately have version semantics.
        for field in ('id','owner','title','tags','document_type'):
            expected=self.expected['A'][field];actual=obs['A']['body'].get(field)
            if field=='tags':expected=sorted(expected);actual=sorted(actual) if isinstance(actual,list) else actual
            self.record_check('root.'+field,expected,actual)
        for field in ('correspondent','storage_path','custom_fields','notes'):
            if field in self.protected['A']:self.record_check('root.protected.'+field,self.protected['A'][field],obs['A']['body'].get(field))
        self.record_check('root.parent',None,obs['A']['body'].get('root_document'))
        self.verify('D',obs['D']['body'])
        for entity in ('T','U','Y'):
            if entity not in self.deleted:self.verify(entity,obs[entity]['body'])
        versions=obs['A']['body'].get('versions')
        if not isinstance(versions,list):raise s.Incomplete('Version response has no versions array')
        ids=[v.get('id') for v in versions]
        self.record_check('version.membership',sorted(self.ids[x] for x in self.members),sorted(ids))
        self.record_check('version.unique_ids',len(ids),len(set(ids)))
        for entity in sorted(self.members):
            entries=[v for v in versions if v.get('id')==self.ids[entity]]
            self.record_check(entity+'.one_version_entry',1,len(entries));entry=entries[0]
            self.record_check(entity+'.is_root',entity=='A',entry.get('is_root'))
            self.record_check(entity+'.entry_checksum',self.tasks[entity]['input_sha256'],entry.get('checksum'))
            if entity in self.labels:self.record_check(entity+'.label',self.labels[entity],entry.get('version_label'))
            for suffix in ('_content','_bytes'):self.record_check(entity+suffix+'.status',200,obs[entity+suffix]['status'])
            self.record_check(entity+'.input_checksum',self.tasks[entity]['input_sha256'],obs[entity+'_bytes']['body'].get('original_checksum'))
            if entity in self.file_content:self.record_check(entity+'.version_content',self.file_content[entity],obs[entity+'_content']['body'].get('content'))
        self.record_check('unselected.original_checksum',self.tasks['D']['input_sha256'],obs['D_bytes']['body'].get('original_checksum'))
        # Cross-view consistency, not an independent proof of newest-version selection order.
        self.record_check('effective.metadata_status',200,obs['effective_bytes']['status'])
        if versions:
            first=next((x for x in self.members if self.ids[x]==versions[0]['id']),None)
            self.record_check('effective.first_version_known',True,first is not None)
            self.record_check('effective.first_version_checksum',self.tasks[first]['input_sha256'],obs['effective_bytes']['body'].get('original_checksum'))
        if self.pending:self.record_check(self.pending['step']+'.http_status',self.pending['expected'],self.pending['observed']);self.pending=None
        return {'graph_reads_saved':len(obs)}
    def execute(self,key):
        spec=self.case['steps'][key]
        if spec['kind']!='version_action':return super().execute(key)
        with self.mutex:
            if self.failed or key in self.done or not set(spec['after'])<=set(self.done):raise s.Incomplete('Invalid lifecycle admission')
            self.t.step=key;op=spec['operation']
            try:
                code=None
                if op=='merge':
                    source=spec['source'];code,body=self.request('POST','/api/documents/merge_as_versions/',{'documents':[self.ids['A'],self.ids[source]],'root_document_id':self.ids['A']})
                    if code==200:self.members.add(source)
                elif op=='label':
                    source=spec['source'];label=self.ns+'-'+source+'-label';code,body=self.request('PATCH',self.route('A')+'versions/%s/'%self.ids[source],{'version_label':label})
                    if code==200:self.labels[source]=label
                elif op in ('rename_root','detach_root_tag','reattach_root_tag'):
                    change={'title':self.ns+'-A-renamed'} if op=='rename_root' else {'tags':[self.ids['U']] if op=='detach_root_tag' else [self.ids['T'],self.ids['U']]}
                    code,body=self.request('PATCH',self.route('A'),change)
                    if code==200:self.expected['A'].update(change)
                elif op in ('rename_tag','rename_type'):
                    entity='T' if op=='rename_tag' else 'Y';family='tags' if entity=='T' else 'document_types'
                    change={'name':self.ns+'-'+entity+'-renamed'};code,body=self.request('PATCH','/api/'+family+'/%s/'%self.ids[entity],change)
                    if code==200:self.expected[entity].update(change)
                elif op in ('delete_tag','delete_type'):
                    entity='T' if op=='delete_tag' else 'Y';family='tags' if entity=='T' else 'document_types'
                    code,body=self.request('DELETE','/api/'+family+'/%s/'%self.ids[entity])
                    if code==204:
                        self.deleted.add(entity)
                        for doc in ('A','D'):
                            if entity=='T':self.expected[doc]['tags']=[i for i in self.expected[doc]['tags'] if i!=self.ids[entity]]
                            else:self.expected[doc]['document_type']=None
                elif op=='upload_version':
                    data=s.synthetic_pdf('Paperless distinct new file version '+self.ns+' V');path=self.out/'inputs/V.pdf';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
                    payload,ct=s.multipart({'version_label':self.ns+'-V-upload'},'V.pdf',data)
                    code,body=self.request('POST',self.route('A')+'update_version/',payload,ct)
                    if code!=200 or not isinstance(body,str):
                        self.pending={'step':key,'expected':200,'observed':code};self.checkpoint(key);raise s.Incomplete('Version upload returned no task identity')
                    self.tasks['V']={'task_id':body,'deadline':time.monotonic()+180,'input_sha256':hashlib.sha256(data).hexdigest(),'ready':False}
                    result={'queued_task':body};self.done.append(key);s.dump(self.out/'step-order.json',self.done);return {'ok':True,'step':key,'result':result}
                elif op=='wait_version':
                    entry=self.tasks['V']
                    while True:
                        code,body=self.request('GET','/api/tasks/?'+urlencode({'task_id':entry['task_id'],'page_size':100}))
                        if code!=200:raise s.Incomplete('Version ingestion task read failed')
                        records=body if isinstance(body,list) else body.get('results',[])
                        matches=[r for r in records if r.get('task_id')==entry['task_id']]
                        if len(matches)>1:raise s.Incomplete('Ambiguous version ingestion task')
                        if matches and matches[0].get('status') in ('failure','revoked'):raise s.Incomplete('Version ingestion failed; inspect task receipt')
                        if matches and matches[0].get('status')=='success':break
                        if time.monotonic()>=entry['deadline']:raise s.Incomplete('Version ingestion timed out')
                        time.sleep(1)
                    code,body=self.request('GET',self.route('A'))
                    if code!=200:raise s.Incomplete('Version graph read failed after ingestion')
                    added={v['id'] for v in body.get('versions',[])}-{self.ids[x] for x in self.members}
                    if len(added)!=1:raise s.Discrepancy('Version upload did not add exactly one new graph member')
                    self.ids['V']=added.pop();self.members.add('V');entry['ready']=True;self.labels['V']=self.ns+'-V-upload';code=None
                    s.dump(self.out/'bindings.json',{'ordinary_user_id':self.t.owner,'ids':self.ids,'ingestion_tasks':self.tasks})
                elif op=='delete_version':
                    source=spec['source']
                    if source=='A' or source not in self.members:raise s.Incomplete('Only an owned non-root version can be removed')
                    code,body=self.request('DELETE',self.route('A')+'versions/%s/'%self.ids[source])
                    if code==200:self.members.remove(source);self.deleted.add(source)
                elif op!='checkpoint':raise s.Incomplete('Undeclared version graph operation')
                if code is not None:self.pending={'step':key,'expected':204 if op in ('delete_tag','delete_type') else 200,'observed':code}
                result=self.checkpoint(key)
                self.done.append(key);s.dump(self.out/'step-order.json',self.done)
                return {'ok':True,'step':key,'result':result}
            except Exception as e:
                self.failed={'classification':'SEMANTIC_CANDIDATE' if isinstance(e,s.Discrepancy) else 'INCOMPLETE','step':key,'error':str(e)};s.dump(self.out/'failure.json',self.failed);raise

def provision(container,username,password):
    script='''import django,json,sys,os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","paperless.settings");django.setup()
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
p=json.load(sys.stdin)
codes=["add_document","view_document","change_document","delete_document","delete_tag","delete_documenttype","add_tag","view_tag","change_tag","add_documenttype","view_documenttype","change_documenttype","view_paperlesstask"]
perms=list(Permission.objects.filter(content_type__app_label="documents",codename__in=codes))
if set(x.codename for x in perms)!=set(codes):raise RuntimeError("Missing ordinary fixture permissions")
u=get_user_model().objects.create_user(username=p["username"],password=p["password"],is_staff=False,is_superuser=False);u.user_permissions.set(perms)
print("SBT_FIXTURE "+json.dumps({"id":u.id,"username":u.username,"is_staff":False,"is_superuser":False,"permissions":sorted(u.get_all_permissions())}))
'''
    r=s.subprocess.run(['docker','exec','-i','--workdir','/usr/src/paperless/src',container,'python','-c',script],input=json.dumps({'username':username,'password':password}),text=True,capture_output=True,timeout=60)
    if r.returncode:raise s.Incomplete('Fixture setup failed: '+r.stderr[-1000:])
    lines=[x[12:] for x in r.stdout.splitlines() if x.startswith('SBT_FIXTURE ')]
    if len(lines)!=1:raise s.Incomplete('Missing fixture setup receipt')
    return json.loads(lines[0])

def run(args):
    root=args.root.resolve();raw=(root/'model/paperless-openapi.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=s.PIN:raise s.Incomplete('Pinned contract bytes differ; no requests sent')
    contract=json.loads(raw);profile_path=root/'profiles/paperless-stage5-runtime.json';p=json.loads(profile_path.read_text(encoding='utf-8-sig'))
    if args.base_url!='http://127.0.0.1:9930':raise s.Incomplete('Only the isolated loopback study service is supported')
    if not shutil.which('provengo'):raise s.Incomplete('Provengo not on PATH')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8];campaign=root/'runs'/('stage5-'+stamp);campaign.mkdir(parents=True)
    s.dump(campaign/'registration.json',{'contract_sha256':s.PIN,'profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),'planned_cases':[c['id'] for c in p['cases']],'fresh_sets':2,'native_candidates_per_case':16,'selection':'distinct projected business orders','http_concurrency':False,'root_deletion':False,'owned_non_root_version_deletion':True,'reset_replay_accepted':False})
    results=[];password=None;identity=None
    print('Evidence directory: '+str(campaign),flush=True)
    try:
        for case in p['cases']:
            pool=campaign/(case['id'].lower()+'-pool');project=pool/'model';compile_model(contract,p,case,project)
            env=os.environ.copy()
            if not any('-Xmx' in env.get(k,'') for k in ('JAVA_TOOL_OPTIONS','_JAVA_OPTIONS','JDK_JAVA_OPTIONS')):env['JAVA_TOOL_OPTIONS']=(env.get('JAVA_TOOL_OPTIONS','')+' -Xmx1g').strip()
            env.update(SBT_STAGE1_BRIDGE='http://127.0.0.1:1',SBT_STAGE1_KEY='symbolic')
            samples=pool/'samples.json';r=s.native(root,['--batch-mode','sample','--size','16','--algorithm','random','--max-length',str(5*len(case['steps'])+10),'-o',str(samples)],project,env)
            (pool/'sample-output.txt').write_text(r.stdout+r.stderr,encoding='utf-8')
            if r.returncode or not samples.exists():raise s.Incomplete('Native lifecycle sampling failed')
            all_samples=json.loads(samples.read_text(encoding='utf-8-sig'));selected=[];seen=set()
            for sample in all_samples:
                order=s.audit_sample([sample],case);ready=[e.get('data',{}).get('id') for e in sample if e.get('name')=='S5:Ready']
                if ready!=order:raise s.Incomplete('Native readiness events differ from the admitted lifecycle order')
                business=business_order(order,case);signature=tuple(business)
                if signature not in seen:seen.add(signature);selected.append((sample,order,business))
            s.dump(pool/'diversity.json',{'candidates':len(all_samples),'distinct_business_orders':len(seen),'business_orders':[x[2] for x in selected]})
            if len(selected)<2:raise s.Incomplete('Fewer than two distinct business orders; no live execution for this case')
            for repetition,(sample,order,business) in enumerate(selected[:2],1):
                folder=campaign/(case['id'].lower()+'-'+str(repetition));folder.mkdir();samplefile=folder/'selected-sample.json';s.dump(samplefile,[sample])
                s.dump(folder/'sample-acceptance.json',{'order':order,'business_order':business,'samples_sha256':hashlib.sha256(samplefile.read_bytes()).hexdigest(),'model_hashes':{str(f.relative_to(project)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in project.rglob('*') if f.is_file()}})
                if args.sample_only:results.append({'case':case['id'],'set':repetition,'status':'SAMPLE_ONLY'});continue
                if identity is None:
                    password=secrets.token_urlsafe(32);identity=provision(args.container or s.discover_container(),'sbt_versions_'+uuid.uuid4().hex[:16],password);s.dump(campaign/'ordinary-user.json',identity)
                transport=s.Transport(args.base_url,folder,identity['username'],password,identity['id']);engine=VersionEngine(p,case,'sbt-v-'+uuid.uuid4().hex[:16],transport,folder);server,key=s.serve(engine)
                env.update(SBT_STAGE1_BRIDGE='http://127.0.0.1:'+str(server.server_port),SBT_STAGE1_KEY=key)
                print('Running '+case['id']+' / fresh set '+str(repetition)+' / distinct business order',flush=True)
                try:r=s.native(root,['--batch-mode','run','--run-source',str(samplefile),'--run-id','1','--output-file',str(folder/'native-result.json')],project,env)
                finally:server.shutdown();server.server_close()
                text=(r.stdout+r.stderr).replace(key,'<REDACTED_LOCAL_KEY>');(folder/'run-output.txt').write_text(text,encoding='utf-8')
                resultfile=folder/'native-result.json'
                if resultfile.exists():resultfile.write_text(resultfile.read_text(encoding='utf-8-sig').replace(key,'<REDACTED_LOCAL_KEY>'),encoding='utf-8')
                receipt=re.search(r"(?:STAGE1_NATIVE_RECEIPT\s+|setting\s+'stage1_receipt'\s+to\s+')(\{[^\n]+\})",text)
                accepted=engine.completed and not engine.failed and r.returncode==0 and receipt is not None and 'Test Result: SUCCESS' in text and engine.done==order
                if accepted:accepted=json.JSONDecoder().raw_decode(receipt[1])[0]==json.loads((folder/'runtime-receipt.json').read_text())
                result={'case':case['id'],'set':repetition,'status':'STAGE5_FUNCTIONAL_PASS' if accepted else (engine.failed or {}).get('classification','INCOMPLETE'),'checks':len(engine.checks),'responses':transport.sequence,'business_order':business,'native_exit_code':r.returncode};s.dump(folder/'run-acceptance.json',result);results.append(result);print(result['status'],flush=True)
                if not accepted:raise s.Incomplete('Stopped at first incomplete or candidate; preserve campaign.zip')
    except Exception as e:s.dump(campaign/'campaign-error.json',{'error':str(e),'automatic_retry':False});raise
    finally:
        password=None;s.dump(campaign/'campaign-summary.json',{'status':'SAMPLES_COMPLETE' if args.sample_only and len(results)==6 else 'STAGE5_SIX_RUNS_PASS' if len(results)==6 and all(x['status']=='STAGE5_FUNCTIONAL_PASS' for x in results) else 'STAGE5_NOT_COMPLETE','runs':results,'reset_replay_accepted':False});print('Review ZIP: '+str(s.bundle(campaign)),flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--container');parser.add_argument('--sample-only',action='store_true');parser.add_argument('--base-url',default='http://127.0.0.1:9930')
    try:run(parser.parse_args())
    except Exception as e:print('STAGE5_NOT_ACCEPTED: '+str(e),file=sys.stderr);sys.exit(1)
