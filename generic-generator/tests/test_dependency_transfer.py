"""Native transfer schedules, independent receipts and injected corruption."""
import json,os,shutil,socket,subprocess,tempfile,unittest
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples,find_receipt
from tools.transfer_receipts import validate_transfer_receipts
ROOT=Path(__file__).resolve().parents[1]
def generate(resource='food',mode='transfer',config=None,base='http://127.0.0.1:9925'):
 name=f'mealie-transfer-{resource}-{mode}'
 runtime=config or json.loads((ROOT/'profiles'/(name+'-runtime.json')).read_text())
 return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'native',base,218,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/'profiles'/(name+'-scope.json')).read_text()),relationship_runtime=runtime)
class TransferConfigurationTests(unittest.TestCase):
 def test_generic_opt_in_is_deterministic_and_has_three_sources(self):
  a=generate();b=generate();self.assertEqual(a.interfaces_js,b.interfaces_js);self.assertEqual(a.stories_js,b.stories_js);self.assertNotRegex(a.stories_js,r'\bsvc\.')
  task=next(t for t in a.resource_maps['relationship_scenario_plan']['tasks'] if t['kind']=='dependency_transfer')
  self.assertEqual(len(task['phases']),7);self.assertEqual(len(task['sources']),3)
 def test_invalid_identity_and_control_mutations_are_rejected(self):
  base=json.loads((ROOT/'profiles/mealie-transfer-food-transfer-runtime.json').read_text())
  for mutation in ['identity','control','excluded_identity','timestamp_identity','timestamp_created']:
   runtime=json.loads(json.dumps(base));rule=runtime['dependency_transfer']
   if mutation=='identity':rule['target_field']='id'
   elif mutation=='control':rule['phases'][1]['source_index']=3
   elif mutation=='excluded_identity':rule['derived_fields']=['recipeIngredient[].quantity']
   else:rule['target_timestamp_fields']=['id' if mutation=='timestamp_identity' else 'createdAt']
   with self.assertRaises(ValueError):generate(config=runtime)
@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java'),'Native jar required')
class TransferNativeTests(unittest.TestCase):
 def test_native_healthy_schedules_and_corruption(self):
  command=['java','-Xmx512m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
  for resource in ['food','unit']:
   for mode in ['control','transfer']:
    with tempfile.TemporaryDirectory() as folder:
     project=Path(folder)
     with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
     result=generate(resource,mode,base='http://127.0.0.1:'+str(port))
     (project/'spec/js').mkdir(parents=True);(project/'config').mkdir();(project/'config/provengo.yml').write_text('version: 2\n')
     (project/'spec/js/interfaces.native.js').write_text(result.interfaces_js);(project/'spec/js/stories.native.js').write_text(result.stories_js)
     plan=result.resource_maps['relationship_scenario_plan'];(project/'relationship_scenario_plan.json').write_text(json.dumps(plan))
     sample=subprocess.run(command+['sample','--size','2','--max-length','700','-o','samples.json',str(project)],capture_output=True,text=True,timeout=60)
     self.assertEqual(sample.returncode,0,sample.stdout+sample.stderr);audit_samples(json.loads((project/'samples.json').read_text()),plan);self.assertLess((project/'samples.json').stat().st_size,8*1024*1024)
     for index,fault in enumerate(['','']+(['transfer-quantity','transfer-unrelated-target','transfer-unrelated-timestamp'] if mode=='transfer' else [])):
      env=dict(os.environ,NATIVE_MOCK_PORT=str(port),NATIVE_MOCK_FAULT=fault,SBT_REL_USERNAME='local',SBT_REL_PASSWORD='local')
      server=subprocess.Popen(['node',str(ROOT/'tests/native_http_mock.js'),str(project)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
      try:
       self.assertEqual(server.stdout.readline().strip(),'READY')
       run=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if index==1 else 1),str(project)],env=env,capture_output=True,text=True,timeout=60);output=run.stdout+run.stderr;receipt=find_receipt(output)
       if fault:self.assertNotEqual(run.returncode,0,fault);self.assertIsNone(receipt);self.assertIn('Dependency transfer mismatch:',output)
       else:
        self.assertEqual(run.returncode,0,'\n'.join(l for l in output.splitlines() if 'WARN [' in l or 'ERR [' in l));validate_transfer_receipts(receipt,plan)
        self.assertEqual(receipt['response_count'],result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
        forged=json.loads(json.dumps(receipt));forged['dependency_transfers'][0]['phases'][0]['checks'][0]['observed']['recipeIngredient'][0]['quantity']=999
        with self.assertRaises(ValueError):validate_transfer_receipts(forged,plan)
      finally:server.terminate();server.communicate(timeout=10)
