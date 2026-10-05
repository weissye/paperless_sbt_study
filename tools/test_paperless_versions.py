"""Independent version fixture: graph membership, file selection, labels and root metadata."""
import copy,hashlib,json,random,tempfile,unittest
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import paperless_stage1 as s
import paperless_versions as v
from paperless_lifecycles import expand,business_order
from build_paperless_version_profile import profile
from test_paperless_stage1 import Fixture
from test_paperless_stage3 import Server

class VersionFixture(Fixture):
    def __init__(self,fault=None):super().__init__();self.fault=fault;self.group={};self.labels={};self.sequence=[]
    def members(self,root):return [root]+[i for i,r in self.group.items() if r==root]
    def document(self,id):return self.objects['/api/documents/%s/'%id]
    def view(self,id,version=None):
        root=self.group.get(id,id);members=self.members(root);out=copy.deepcopy(self.document(id));out['root_document']=self.group.get(id)
        out['versions']=[{'id':x,'is_root':x==root,'version_label':self.labels.get(x),'checksum':self.objects['/api/documents/%s/metadata/'%x]['original_checksum']} for x in sorted(members,key=lambda x:self.sequence.index(x),reverse=True)]
        effective=version or (members[-1] if id==root else id);out['content']=self.document(effective)['content']
        if self.fault=='wrong-content' and version is not None and len(members)>1:out['content']=self.document(root)['content']
        return out
    def request(self,method,path,body):
        parsed=urlsplit(path);route=parsed.path;query=parse_qs(parsed.query)
        if route=='/api/documents/merge_as_versions/':
            root=body['root_document_id'];source=next(x for x in body['documents'] if x!=root)
            self.group[source]=root;self.sequence.remove(source);self.sequence.append(source)
            if self.fault=='mutate-then-500':return 500,{'detail':'Injected error after graph write'}
            if self.fault=='missing-member':self.group.pop(source)
            if self.fault=='unselected-change':
                for r,d in self.objects.items():
                    if r.startswith('/api/documents/') and r.count('/')==4 and d['title'].endswith('-D'):d['tags']=[]
            return 200,{'result':'OK'}
        if '/update_version/' in route:
            root=int(route.split('/')[3]);label=next(x.split(b'\r\n\r\n',1)[1].rstrip(b'\r\n').decode() for x in body.split(body.split(b'\r\n',1)[0]) if b'name="version_label"' in x)
            raw=body.replace(b'name="version_label"',b'name="title"');code,task=super().request('POST','/api/documents/post_document/',raw)
            id=self.tasks[task]['related_document_ids'][0];self.sequence.append(id);self.document(id)['root_document']=root;self.group[id]=root;self.labels[id]=label;return code,task
        if '/versions/' in route:
            root=int(route.split('/')[3]);id=int(route.split('/')[5])
            if id not in self.members(root):return 404,{'detail':'Not a member'}
            if method=='DELETE':
                self.group.pop(id);return 200,{'result':'OK','current_version_id':self.members(root)[-1]}
            self.labels[id]=body['version_label'];return 200,{'id':id,'version_label':self.labels[id],'is_root':id==root}
        if method=='GET' and route.startswith('/api/documents/'):
            id=int(route.split('/')[3]);root=self.group.get(id,id);members=self.members(root);version=int(query['version'][0]) if 'version' in query else None
            if version is not None and version not in members:return 404,{'detail':'Invalid version'}
            if '/metadata/' in route:return 200,copy.deepcopy(self.objects['/api/documents/%s/metadata/'%(version or (members[-1] if id==root else id))])
            if route in self.objects:return 200,self.view(id,version)
        if method=='DELETE' and route in self.objects:
            self.objects.pop(route)
            id=int(route.split('/')[3])
            for r,d in self.objects.items():
                if r.startswith('/api/documents/') and r.count('/')==4:
                    if route.startswith('/api/tags/'):d['tags']=[t for t in d['tags'] if t!=id]
                    elif d['document_type']==id:d['document_type']=None
            return 204,{}
        result=super().request(method,path,body)
        if route=='/api/documents/post_document/':
            id=self.tasks[result[1]]['related_document_ids'][0];self.sequence.append(id);self.document(id)['root_document']=None
        if method=='PATCH' and route.startswith('/api/documents/') and result[0]==200:return 200,self.view(int(route.split('/')[3]))
        return result

def exercise(case,fault=None,seed=1):
    server=Server(VersionFixture(fault))
    with tempfile.TemporaryDirectory() as temp:
        out=Path(temp);engine=v.VersionEngine(profile(),case,'sbt-fixture',s.Transport(server.url,out,'fixture','password',17),out);rng=random.Random(seed)
        try:
            while len(engine.done)<len(case['steps']):
                ready=[k for k,item in case['steps'].items() if k not in engine.done and set(item['after'])<=set(engine.done)]
                engine.execute(rng.choice(ready))
            assert engine.completed
            return {'checks':len(engine.checks),'order':business_order(engine.done,case),'responses':engine.t.sequence}
        except s.Discrepancy:
            saved=json.loads((out/'version-graph'/(engine.failed['step']+'.json')).read_text());assert 'D_bytes' in saved and 'effective_bytes' in saved and all(x in saved for x in ('A','D','T','U','Y'))
            raise
        finally:server.close()
class Tests(unittest.TestCase):
    def test_all_three_cases_and_distinct_orders(self):
        for case in profile()['cases']:
            a=exercise(case,seed=4);b=exercise(case,seed=19);self.assertGreater(a['checks'],150)
        case=profile()['cases'][1];orders={tuple(exercise(case,seed=k)['order']) for k in (2,3,5)};self.assertGreater(len(orders),1)
    def test_missing_version_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'missing-member')
    def test_selected_file_content_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'wrong-content')
    def test_unselected_document_change_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'unselected-change')
    def test_500_after_write_preserves_complete_reads(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'mutate-then-500')
    def test_multi_parent_join_and_cycle_validation(self):
        steps,chains=expand([{'entity':'a','lifecycle':[{'id':'a','kind':'x'}]},{'entity':'b','lifecycle':[{'id':'b','kind':'x'}]},{'entity':'child','lifecycle':[{'id':'child','kind':'x','after':['a','b']}]}]);self.assertEqual(set(steps['child']['after']),{'a','b'})
        with self.assertRaises(ValueError):expand([{'entity':'x','lifecycle':[{'id':'x','kind':'x','after':['y']},{'id':'y','kind':'x'}]}])
if __name__=='__main__':unittest.main()
