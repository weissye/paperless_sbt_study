"""Bulk relationship fixture and independent selected/unselected readback checks."""
import json,random,tempfile,unittest
from pathlib import Path
import paperless_stage1 as s
from test_paperless_stage1 import Fixture
from test_paperless_stage3 import Server
class BulkFixture(Fixture):
    def request(self,method,path,body):
        if method=='POST' and path=='/api/documents/bulk_edit/':
            selected=body['documents'];tag=body['parameters']['tag'];operation=body['method']
            for n,doc_id in enumerate(selected):
                if self.fault=='partial-update' and n>0:continue
                doc=self.objects['/api/documents/%s/'%doc_id];tags=set(doc['tags'])
                if operation=='add_tag':tags.add(tag)
                else:tags.discard(tag)
                doc['tags']=sorted(tags)
                if self.fault=='duplicate-link' and operation=='add_tag':doc['tags'].append(tag)
                if self.fault=='unrelated-loss':doc['tags']=[tag] if operation=='add_tag' else []
            if self.fault=='unselected-update':
                for route,doc in self.objects.items():
                    if route.startswith('/api/documents/') and '/metadata/' not in route and doc['id'] not in selected:doc['tags']=sorted(set(doc['tags'])|{tag})
            return (500,{'detail':'Injected post-mutation error'}) if self.fault=='mutate-then-500' else (200,{'result':'OK'})
        return super().request(method,path,body)
def profile():return json.loads((Path(__file__).parent.parent/'profiles/paperless-stage4-runtime.json').read_text())
def exercise(case,fault=None):
    server=Server(BulkFixture(fault))
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp);e=s.Engine(profile(),case,'sbt-s4-fixture',s.Transport(server.url,out,'fixture','password',17),out)
        rng=random.Random(23)
        try:
            while len(e.done)<len(case['steps']):
                ready=[k for k,v in case['steps'].items() if k not in e.done and set(v.get('after',[])).issubset(e.done)]
                e.execute(rng.choice(ready))
            assert e.completed
            return {'checks':len(e.checks),'http':e.t.sequence}
        except s.Discrepancy:
            observed=json.loads((out/'bulk/check_add_1.json').read_text());assert len(observed)==9
            assert all(observed[k]['status']==200 for k in ('A','B','C'))
            raise
        finally:server.close()
class Tests(unittest.TestCase):
    def test_three_bulk_cases_pass(self):
        for case in profile()['cases']:
            with self.subTest(case=case['id']):self.assertGreater(exercise(case)['checks'],150)
    def test_unselected_document_mutation_is_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'unselected-update')
    def test_partial_update_is_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'partial-update')
    def test_duplicate_link_is_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'duplicate-link')
    def test_unrelated_tag_loss_is_detected(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'unrelated-loss')
    def test_500_after_mutation_retains_all_nine_reads(self):
        with self.assertRaises(s.Discrepancy):exercise(profile()['cases'][0],'mutate-then-500')
if __name__=='__main__':unittest.main()
