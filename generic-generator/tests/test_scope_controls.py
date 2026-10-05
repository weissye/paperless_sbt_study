import copy,json,os,shutil,socket,subprocess,tempfile,unittest
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.identity_receipts import IdentityMismatch,validate_identity_receipts
from tools.relationship_execution import find_receipt,audit_samples
ROOT=Path(__file__).resolve().parents[1]
CASES=('reference-controls','household-controls')

def generate(case,port=19876):
 return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'mealie',f'http://127.0.0.1:{port}',721,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/f'profiles/mealie-{case}-scope.json').read_text()),relationship_runtime=json.loads((ROOT/f'profiles/mealie-{case}-runtime.json').read_text()))

class ConfigurationTests(unittest.TestCase):
 def test_profiles_generate_deterministically_without_story_http(self):
  for c in CASES:
   a,b=generate(c),generate(c)
   self.assertEqual(a.interfaces_js,b.interfaces_js);self.assertEqual(a.stories_js,b.stories_js)
   self.assertNotRegex(a.stories_js,r'\bsvc\.')
   self.assertEqual(a.resource_maps['relationship_compilation']['regular_actor_count'],2)
 def test_three_controls_and_distinct_household_policy(self):
  for c in CASES:
   p=json.loads((ROOT/f'profiles/mealie-{c}-runtime.json').read_text())['identity_program'];s={x['id']:x for x in p['steps']}
   for a in ('a','b'):
    self.assertTrue(s['add_'+a]['required']);self.assertEqual(s['add_'+a]['expected_codes'],[200])
    if c=='reference-controls':
     self.assertEqual(s['cross_add_'+a]['expected_codes'],[403,404]);self.assertEqual(s['missing_read_'+a]['expected_codes'],[404]);self.assertNotIn(500,s['missing_add_'+a]['expected_codes'])
    else:
     self.assertEqual(s['cross_add_'+a]['expected_codes'],[200]);self.assertEqual(s['other_list_add_'+a]['expected_codes'],[403,404])
   group=next(x for x in p['checks'] if x['id']=='scope-groupId')
   house=next(x for x in p['checks'] if x['id']=='scope-householdId')
   self.assertEqual(group['operator'],'equal' if c=='household-controls' else 'not_equal');self.assertEqual(house['operator'],'not_equal')

@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java') and shutil.which('node'),'Native tools required')
class NativeTests(unittest.TestCase):
 def test_native_fresh_runs_and_injected_reference_failure(self):
  command=['java','-Xmx512m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
  for case in CASES:
   with tempfile.TemporaryDirectory() as folder:
    p=Path(folder)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    generated=generate(case,port);plan=generated.resource_maps['relationship_scenario_plan']
    (p/'spec/js').mkdir(parents=True);(p/'config').mkdir();(p/'config/provengo.yml').write_text('version: 2\n')
    (p/'spec/js/interfaces.mealie.js').write_text(generated.interfaces_js);(p/'spec/js/stories.mealie.js').write_text(generated.stories_js)
    sample=subprocess.run(command+['sample','--size','2','--max-length','400','-o','samples.json',str(p)],capture_output=True,text=True,timeout=60)
    self.assertEqual(sample.returncode,0,sample.stdout+sample.stderr);self.assertTrue((p/'samples.json').exists(),sample.stdout+sample.stderr)
    audit_samples(json.loads((p/'samples.json').read_text()),plan);self.assertLess((p/'samples.json').stat().st_size,4*1024**2)
    namespaces=[]
    faults=['','','missing-add-500'] if case=='reference-controls' else ['','']
    for n,fault in enumerate(faults):
     env=dict(os.environ,IDENTITY_TEST_PORT=str(port),IDENTITY_TEST_FAULT=fault,SBT_REL_USERNAME='admin@example.invalid',SBT_REL_PASSWORD='admin-pass',SBT_IDP_A_PASSWORD='user-a-pass',SBT_IDP_B_PASSWORD='user-b-pass')
     server=subprocess.Popen(['node',str(ROOT/'tests/scope_controls_http_mock.js')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
     try:
      self.assertEqual(server.stdout.readline().strip(),'READY')
      ran=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if n==1 else 1),str(p)],env=env,capture_output=True,text=True,timeout=60)
      receipt=find_receipt(ran.stdout+ran.stderr)
      self.assertEqual(ran.returncode,0,'\n'.join(l for l in (ran.stdout+ran.stderr).splitlines() if 'WARN [' in l or 'ERR ' in l));self.assertIsNotNone(receipt)
      if fault:
       with self.assertRaises(IdentityMismatch) as mismatch:validate_identity_receipts(receipt,plan)
       self.assertIn('missing_add_',str(mismatch.exception));self.assertIn('500',str(mismatch.exception))
      else:
       validate_identity_receipts(receipt,plan);namespaces.append(receipt['identity_program']['namespace'])
       broken=copy.deepcopy(receipt);broken['identity_program']['observations'].pop('finish')
       with self.assertRaises(ValueError):validate_identity_receipts(broken,plan)
     finally:
      server.terminate();stdout,stderr=server.communicate(timeout=10);self.assertIn('"maximum_active":1',stdout)
    self.assertNotEqual(namespaces[0],namespaces[1])

if __name__=='__main__':unittest.main()
