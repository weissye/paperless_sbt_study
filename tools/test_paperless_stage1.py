"""Owned-resource fixture tests, including native Provengo replay when explicitly requested."""
import copy,hashlib,json,os,random,tempfile,threading,unittest,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import paperless_stage1 as s

class Fixture:
    def __init__(self,fault=None):self.objects={};self.tasks={};self.counter=0;self.fault=fault
    def next(self):self.counter+=1;return self.counter
    def request(self,method,path,body):
        parsed=urlsplit(path);path=parsed.path
        if path=='/api/token/':return 200,{'token':'LOCAL_FIXTURE_TOKEN'}
        if path=='/api/documents/post_document/':
            # Multipart is deliberately parsed enough to validate actual generated PDF bytes and title.
            boundary=body.split(b'\r\n',1)[0]
            parts=body.split(boundary)
            title=next(p.split(b'\r\n\r\n',1)[1].rstrip(b'\r\n').decode() for p in parts if b'name="title"' in p)
            pdf=next(p.split(b'\r\n\r\n',1)[1].rstrip(b'\r\n') for p in parts if b'name="document"' in p)
            assert pdf.startswith(b'%PDF-1.4') and pdf.endswith(b'%%EOF')
            pdf+=b'\n' # generated stream has exactly this final newline
            id=self.next();self.objects['/api/documents/%s/'%id]={'id':id,'owner':17,'title':title,'tags':[],'document_type':None,'content':'Synthetic '+title,'correspondent':None,'storage_path':None,'custom_fields':[],'notes':[],'original_file_name':'input.pdf','mime_type':'application/pdf','page_count':1,'root_document':id}
            self.objects['/api/documents/%s/metadata/'%id]={'original_checksum':hashlib.sha256(pdf).hexdigest(),'original_mime_type':'application/pdf'}
            task='fixture-task-'+str(id);self.tasks[task]={'task_id':task,'status':'success','related_document_ids':[id] if self.fault!='ambiguous-task' else [id,id+1]}
            return 200,task
        if path=='/api/tasks/':
            id=parse_qs(parsed.query)['task_id'][0];return 200,{'results':[self.tasks[id]]}
        if method=='POST' and path in ('/api/tags/','/api/document_types/'):
            obj={**body,'id':self.next()};self.objects[path+str(obj['id'])+'/']=obj;return 201,copy.deepcopy(obj)
        if path in self.objects:
            if method=='PATCH':
                self.objects[path].update(body)
                if self.fault=='shared-corruption' and 'tags' in body and not body['tags']:
                    for p,d in self.objects.items():
                        if p.startswith('/api/documents/') and '/metadata/' not in p and p!=path:d['tags']=[]
            return 200,copy.deepcopy(self.objects[path])
        return 404,{'detail':'missing'}

class Server:
    def __init__(self,fixture,port=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def handle_call(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
                body=raw if 'multipart' in self.headers.get('Content-Type','') else json.loads(raw) if raw else None
                try:code,data=fixture.request(self.command,self.path,body)
                except Exception as e:code,data=500,{'fixture_error':str(e)}
                out=json.dumps(data).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(out)));self.end_headers();self.wfile.write(out)
            do_GET=handle_call;do_POST=handle_call;do_PATCH=handle_call
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def close(self):self.server.shutdown();self.server.server_close()
    @property
    def url(self):return 'http://127.0.0.1:'+str(self.server.server_port)

def profile():return json.loads((Path(__file__).parent.parent/'profiles/paperless-stage1-runtime.json').read_text())

def execute_fixture(case_id,fault=None):
    p=profile();case=next(x for x in p['cases'] if x['id']==case_id);server=Server(Fixture(fault))
    with tempfile.TemporaryDirectory() as tmp:
        t=s.Transport(server.url,Path(tmp),'fixture_user','fixture_password',17);engine=s.Engine(p,case,'sbt-local-'+case_id,t,Path(tmp))
        rng=random.Random(42)
        try:
            while len(engine.done)<len(case['steps']):
                ready=[k for k,v in case['steps'].items() if k not in engine.done and set(v.get('after',[])).issubset(engine.done)]
                engine.execute(rng.choice(ready))
            if fault:raise AssertionError('Fault was not detected')
            assert engine.completed and all(x['passed'] for x in engine.checks)
            return {'steps':len(engine.done),'checks':len(engine.checks),'http':t.sequence}
        finally:server.close()

class Tests(unittest.TestCase):
    def test_three_cases_preserve_owned_links_and_bytes(self):
        for case in profile()['cases']:
            with self.subTest(case=case['id']):self.assertGreater(execute_fixture(case['id'])['checks'],50)
    def test_injected_other_document_link_corruption_is_detected(self):
        with self.assertRaises(s.Discrepancy):execute_fixture('S1-DETACH-REATTACH','shared-corruption')
    def test_successful_task_with_ambiguous_identity_stops(self):
        with self.assertRaises(s.Incomplete):execute_fixture('S1-CONTROL','ambiguous-task')
    def test_checksum_policy_and_fixture_are_sha256(self):
        self.assertEqual(profile()['original_checksum_algorithm'],'sha256')
        f=Fixture();pdf=s.synthetic_pdf('Checksum contract qualification')
        body,ct=s.multipart({'title':'checksum-fixture'},'A.pdf',pdf)
        code,task=f.request('POST','/api/documents/post_document/',body)
        document=f.tasks[task]['related_document_ids'][0]
        observed=f.objects['/api/documents/%s/metadata/'%document]['original_checksum']
        self.assertEqual(observed,hashlib.sha256(pdf).hexdigest())
        self.assertNotEqual(observed,hashlib.md5(pdf).hexdigest())
    def test_truncated_native_sample_is_rejected(self):
        with self.assertRaises(ValueError):s.audit_sample([[{'name':'S1:Complete','data':{'steps':0}}]],profile()['cases'][0])
    def test_synthetic_pdf_is_valid_and_unique(self):
        a=s.synthetic_pdf('A');b=s.synthetic_pdf('B');self.assertNotEqual(a,b)
        try:import fitz
        except ImportError:return
        doc=fitz.open(stream=a,filetype='pdf');self.assertEqual(len(doc),1);self.assertIn('A',doc[0].get_text())

if __name__=='__main__':unittest.main()
