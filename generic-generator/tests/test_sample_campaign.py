"""A campaign cannot count duplicate samples, mismatched logs or invented variation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.relationship_sample_campaign import summarize_reviews


class SampleCampaignTests(unittest.TestCase):
    def review(self,root,sample_id=1,fault=''):
        tasks=[{'id':x,'kind':'create','after':[]} for x in ['A','B']]
        plan={'tasks':tasks,'instances':{'type':['A','B']}}
        files={'relationship_scenario_plan.json':json.dumps(plan).encode(),
               'relationship_compilation.json':json.dumps({'http_requests_per_complete_schedule':2}).encode(),
               'spec/js/interfaces.test.js':b'// fixture'}
        sample={'status':'NATIVE_SYMBOLIC_SAMPLES_COMPLETE','samples_sha256':'sample-file',
                'model_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()},
                'task_orders':[['A','B'],['B','A']]}
        receipt={'status':'LIVE_CALLBACKS_COMPLETE','task_count':2,'response_count':2,'owned_instances':2,'negative_tests':[]}
        live={'status':'NATIVE_RELATIONSHIP_CALLBACKS_PASS','native_exit_code':0,'live_accepted':True,'sample_id':sample_id,'runtime_receipt':receipt}
        order=sample['task_orders'][sample_id-1]
        log='\n'.join('Selected: [SBT:RelTaskDone {owner:"fixture", id:"'+t+'"}]' for t in order)+'\nSelected: [GET {lib:"REST"}]\nSelected: [GET {lib:"REST"}]\nSBT_REL_LIVE_RECEIPT '+json.dumps(receipt)
        if fault=='exit':live['native_exit_code']=1
        elif fault=='log':log=log.replace('id:"A"','id:"wrong"')
        elif fault=='hash':files['spec/js/interfaces.test.js']=b'// changed'
        elif fault=='receipt':live['runtime_receipt']=dict(receipt,response_count=3)
        elif fault=='different-file':sample['samples_sha256']='another-native-file'
        files['execution-review/sample-acceptance.json']=json.dumps(sample).encode()
        files['execution-review/run-acceptance.json']=json.dumps(live).encode()
        files['execution-review/run-output.txt']=log.encode()
        path=Path(root)/('review-'+str(sample_id)+'-'+fault+'.zip')
        with zipfile.ZipFile(path,'w') as archive:
            for name,data in files.items():archive.writestr(name,data)
        return path

    def test_independent_sample_ids_and_honest_mutation_variation(self):
        with tempfile.TemporaryDirectory() as root:
            a=self.review(root,1);b=self.review(root,2)
            result=summarize_reviews([a,b],2)
            self.assertEqual(result['status'],'CONSISTENCY_CAMPAIGN_PASS')
            self.assertEqual(result['distinct_task_orders'],2)
            self.assertEqual(result['distinct_mutation_orders'],1)
            self.assertEqual(summarize_reviews([a,a],2)['accepted_runs'],1)
            self.assertEqual(summarize_reviews([a],2)['status'],'CONSISTENCY_CAMPAIGN_NOT_ACCEPTED')

    def test_failure_changed_models_and_inconsistent_evidence_are_rejected(self):
        for fault in ['exit','log','hash','receipt','different-file']:
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as root:
                a=self.review(root,1);b=self.review(root,2,fault)
                self.assertEqual(summarize_reviews([a,b],2)['status'],'CONSISTENCY_CAMPAIGN_NOT_ACCEPTED')
