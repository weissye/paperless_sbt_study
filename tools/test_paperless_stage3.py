"""HTTP fixture validation for linked deletion and retained fault readbacks."""
import copy,json,random,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import paperless_stage1 as s
from test_paperless_stage1 import Fixture
class DeletionFixture(Fixture):
    def request(self,method,path,body):
        if method=='DELETE' and path in self.objects:
            old=self.objects.pop(path)
            for route,doc in self.objects.items():
                if route.startswith('/api/documents/') and '/metadata/' not in route:
                    if path.startswith('/api/tags/') and self.fault!='stale-tag':doc['tags']=[x for x in doc['tags'] if x!=old['id']]
                    if path.startswith('/api/document_types/') and doc['document_type']==old['id']:doc['document_type']=None
                    if self.fault=='unrelated-loss':doc['tags']=[]
            if self.fault=='mutate-then-500':return 500,{'detail':'Injected post-mutation error'}
            return 204,None
        return super().request(method,path,body)
class Server:
    def __init__(self,fixture,port=0):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def handle_call(self):
                raw=self.rfile.read(int(self.headers.get('Content-Length',0)))
                body=raw if 'multipart' in self.headers.get('Content-Type','') else json.loads(raw) if raw else None
                try:code,data=fixture.request(self.command,self.path,body)
                except Exception as e:code,data=500,{'fixture_error':str(e)}
                out=b'' if code==204 else json.dumps(data).encode()
                self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(out)));self.end_headers();self.wfile.write(out)
            do_GET=handle_call;do_POST=handle_call;do_PATCH=handle_call;do_DELETE=handle_call
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def close(self):self.server.shutdown();self.server.server_close()
    @property
    def url(self):return 'http://127.0.0.1:'+str(self.server.server_port)
def profile():return json.loads((Path(__file__).parent.parent/'profiles/paperless-stage3-runtime.json').read_text())
def exercise(case,fault=None):
    server=Server(DeletionFixture(fault))
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);e=s.Engine(profile(),case,'sbt-s3-fixture',s.Transport(server.url,out,'fixture','password',17),out)
        rng=random.Random(19)
        try:
            while len(e.done)<len(case['steps']):
                ready=[k for k,v in case['steps'].items() if k not in e.done and set(v.get('after',[])).issubset(e.done)]
                e.execute(rng.choice(ready))
            assert e.completed
            return {'checks':len(e.checks),'http':e.t.sequence}
        except s.Discrepancy:
            observed=json.loads((out/'deletion/check_deleted.json').read_text())
            assert len(observed)==7
            assert observed['A']['status']==observed['B']['status']==200
            raise
        finally:server.close()
class Tests(unittest.TestCase):
    def test_all_three_lifecycle_cases_pass(self):
        for case in profile()['cases']:
            with self.subTest(case=case['id']):self.assertGreater(exercise(case)['checks'],150)
    def test_dangling_tag_reference_is_detected_after_all_reads(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][1],'stale-tag')
    def test_unrelated_tag_loss_is_detected_after_all_reads(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][2],'unrelated-loss')
    def test_mutation_followed_by_500_retains_readback(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][1],'mutate-then-500')
    def test_deleted_endpoint_must_be_in_contract(self):
        contract={'paths':{}}
        with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):s.compile_model(contract,profile(),profile()['cases'][0],Path(tmp)/'model')
if __name__=='__main__':unittest.main()
