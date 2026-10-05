"""Native stale snapshot controls, rejection and observation-only success."""
import json,os,shutil,socket,subprocess,tempfile,unittest
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples,find_receipt
from tools.reference_receipts import validate_reference_receipts
from tools.reference_receipts import _live_view_expected
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java'),'Native jar required')
class StaleSnapshotTests(unittest.TestCase):
 def test_native_stale_controls_rejections_and_faults(self):
  command=['java','-Xmx512m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
  for resource in ['food','unit']:
   for mode in ['control','delete']:
    with tempfile.TemporaryDirectory() as folder:
     project=Path(folder);name=f'mealie-stale-{resource}-{mode}'
     with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
     result=run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'native','http://127.0.0.1:'+str(port),218,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/'profiles'/(name+'-scope.json')).read_text()),relationship_runtime=json.loads((ROOT/'profiles'/(name+'-runtime.json')).read_text()))
     (project/'spec/js').mkdir(parents=True);(project/'config').mkdir();(project/'config/provengo.yml').write_text('version: 2\n')
     (project/'spec/js/interfaces.native.js').write_text(result.interfaces_js);(project/'spec/js/stories.native.js').write_text(result.stories_js)
     self.assertNotRegex(result.stories_js,r'\bsvc\.')
     plan=result.resource_maps['relationship_scenario_plan'];(project/'relationship_scenario_plan.json').write_text(json.dumps(plan))
     sample=subprocess.run(command+['sample','--size','2','--max-length','500','-o','samples.json',str(project)],capture_output=True,text=True,timeout=60)
     self.assertEqual(sample.returncode,0,sample.stdout+sample.stderr);audit_samples(json.loads((project/'samples.json').read_text()),plan);self.assertLess((project/'samples.json').stat().st_size,4*1024*1024)
     for index,fault in enumerate(['','']+(['stale-partial','stale-other-source','stale-accepted'] if mode=='delete' else ['stale-list-quantity','stale-view-name'])):
      env=dict(os.environ,NATIVE_MOCK_PORT=str(port),NATIVE_MOCK_FAULT=fault,SBT_REL_USERNAME='local',SBT_REL_PASSWORD='local')
      server=subprocess.Popen(['node',str(ROOT/'tests/native_http_mock.js'),str(project)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
      try:
       self.assertEqual(server.stdout.readline().strip(),'READY')
       run=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if index==1 else 1),str(project)],env=env,capture_output=True,text=True,timeout=60);output=run.stdout+run.stderr;receipt=find_receipt(output)
       if fault:
        self.assertNotEqual(run.returncode,0,resource+' '+fault);self.assertIsNone(receipt)
        self.assertIn('stale_success_requires_policy_qualification' if fault=='stale-accepted' else 'stale_',output)
       else:
        self.assertEqual(run.returncode,0,'\n'.join(l for l in output.splitlines() if 'WARN [' in l or 'ERR [' in l));validate_reference_receipts(receipt,plan)
        self.assertEqual(receipt['response_count'],result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
        forged=json.loads(json.dumps(receipt));forged['reference_lifecycles'][0]['stale']['checks'].pop()
        with self.assertRaises(ValueError):validate_reference_receipts(forged,plan)
      finally:server.terminate();server.communicate(timeout=10)

class StaleConfigurationTests(unittest.TestCase):
 def test_live_view_changes_are_scoped_to_owned_source_and_accepted_write(self):
  baseline={'recipeReferences':[{'recipeId':'source','recipeQuantity':1,'recipe':{'id':'source','description':'old','dateUpdated':'old','updatedAt':'old','name':'retain'}},{'recipeId':'other','recipeQuantity':2,'recipe':{'id':'other','description':'other','dateUpdated':'old','updatedAt':'old'}}]}
  original=json.loads(json.dumps(baseline))
  config={'live_views':[{'path':'recipeReferences[].recipe','identity_field':'id','volatile_fields':['dateUpdated','updatedAt']}]}
  stale={'accepted':True,'source_id':'source','field':'description','value':'new'}
  expected=_live_view_expected(baseline,config,stale)
  self.assertEqual(expected['recipeReferences'][0]['recipe'],{'id':'source','description':'new','name':'retain'})
  self.assertEqual(expected['recipeReferences'][1],baseline['recipeReferences'][1])
  self.assertEqual(expected['recipeReferences'][0]['recipeQuantity'],1)
  self.assertEqual(baseline,original)
  stale['accepted']=False
  self.assertEqual(_live_view_expected(baseline,config,stale),baseline)

 def test_invalid_flag_fails_and_generation_is_deterministic(self):
  name='mealie-stale-food-delete'
  scope=json.loads((ROOT/'profiles'/(name+'-scope.json')).read_text())
  runtime=json.loads((ROOT/'profiles'/(name+'-runtime.json')).read_text())
  def generate(config):return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'native','http://127.0.0.1:9925',218,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=scope,relationship_runtime=config)
  a=generate(runtime);b=generate(runtime)
  self.assertEqual(a.interfaces_js,b.interfaces_js);self.assertEqual(a.stories_js,b.stories_js)
  runtime['reference_lifecycle']['stale_snapshot']='automatic'
  with self.assertRaises(ValueError):generate(runtime)
