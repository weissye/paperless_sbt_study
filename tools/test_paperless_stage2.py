import copy,json,random,tempfile,unittest
from pathlib import Path
import paperless_stage1 as s
from test_paperless_stage1 import Fixture,Server
class HierarchyFixture(Fixture):
    children_objects=True
    def request(self,method,path,body):
        if method=='PATCH' and path.startswith('/api/tags/') and 'parent' in body:
            current=int(path.rstrip('/').split('/')[-1]);parent=body['parent'];seen=set();cursor=parent
            while cursor is not None and cursor not in seen:
                if cursor==current:
                    if self.fault=='mutate-on-reject':self.objects[path]['parent']=parent
                    return 400,{'parent':['Cannot set parent to a descendant.']}
                seen.add(cursor);cursor=self.objects['/api/tags/%s/'%cursor].get('parent')
        code,b=super().request(method,path,body)
        if path.startswith('/api/tags/') and isinstance(b,dict) and 'id' in b:
            b=copy.deepcopy(b);b['children']=sorted(o['id'] for p,o in self.objects.items() if p.startswith('/api/tags/') and o.get('parent')==b['id'])
            if self.children_objects:
                b['children']=[copy.deepcopy(self.objects['/api/tags/%s/'%id]) for id in b['children']]
                for child in b['children']:child['children']=[]
        return code,b

def profile():return json.loads((Path(__file__).parent.parent/'profiles/paperless-stage2-runtime.json').read_text())
def exercise(case,fault=None):
    server=Server(HierarchyFixture(fault))
    with tempfile.TemporaryDirectory() as tmp:
        e=s.Engine(profile(),case,'sbt-stage2-fixture',s.Transport(server.url,Path(tmp),'fixture','password',17),Path(tmp))
        try:
            rng=random.Random(17)
            while len(e.done)<len(case['steps']):
                ready=[k for k,v in case['steps'].items() if k not in e.done and set(v.get('after',[])).issubset(e.done)]
                e.execute(rng.choice(ready))
            assert e.completed
            return len(e.checks)
        finally:server.close()
class Tests(unittest.TestCase):
    def test_three_hierarchy_policies_pass(self):
        for case in profile()['cases']:
            with self.subTest(case=case['id']):self.assertGreater(exercise(case),100)
    def test_rejected_write_that_mutates_is_detected(self):
        for case in profile()['cases'][1:]:
            with self.subTest(case=case['id']),self.assertRaises(s.Discrepancy):exercise(case,'mutate-on-reject')
    def test_integer_children_form_also_passes(self):
        HierarchyFixture.children_objects=False
        try:
            for case in profile()['cases']:self.assertGreater(exercise(case),100)
        finally:HierarchyFixture.children_objects=True
    def test_identity_normalization_is_strict(self):
        self.assertEqual(s.child_ids([2,1]),[1,2])
        self.assertEqual(s.child_ids([{'id':2,'parent':1}]),[2])
        for invalid in ([{'name':'missing'}],[True],[{'id':2},2],'bad'):
            with self.subTest(invalid=invalid),self.assertRaises(s.Discrepancy):s.child_ids(invalid)
    def test_every_dependency_is_declared(self):
        for case in profile()['cases']:
            for spec in case['steps'].values():self.assertTrue(set(spec.get('after',[])).issubset(case['steps']))
if __name__=='__main__':unittest.main()
