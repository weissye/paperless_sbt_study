import copy,json,os,shutil,socket,subprocess,tempfile,unittest
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples,find_receipt,redact
from tools.identity_receipts import validate_identity_receipts,IdentityMismatch
ROOT=Path(__file__).resolve().parents[1]

def generate(case,runtime=None,port=19876):
 return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'mealie',f'http://127.0.0.1:{port}',721,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/f'profiles/mealie-identity-{case}-scope.json').read_text()),relationship_runtime=runtime or json.loads((ROOT/f'profiles/mealie-identity-{case}-runtime.json').read_text()))

class ConfigurationTests(unittest.TestCase):
 def test_deterministic_explicit_tokens_http_separation(self):
  for c in ('shared','separate'):
   a,b=generate(c),generate(c);self.assertEqual(a.interfaces_js,b.interfaces_js);self.assertEqual(a.stories_js,b.stories_js);self.assertNotRegex(a.stories_js,r'\bsvc\.');self.assertIn('Bearer @{idp_token_A}',a.interfaces_js);self.assertIn('Bearer @{idp_token_B}',a.interfaces_js);self.assertEqual(a.resource_maps['relationship_compilation']['regular_actor_count'],2)
 def test_invalid_auth_operation_and_dependency_fail_closed(self):
  base=json.loads((ROOT/'profiles/mealie-identity-shared-runtime.json').read_text())
  for mutation in ('operation','actor','route','after'):
   r=copy.deepcopy(base);s=r['identity_program']['steps'][2];s[mutation]={'operation':'POST /missing','actor':'missing','route':{'unexpected':1},'after':['missing']}[mutation]
   with self.assertRaises(ValueError):generate('shared',r)
 def test_actor_passwords_and_token_logs_are_redacted(self):
  key='SBT_IDP_A_PASSWORD';previous=os.environ.get(key);os.environ[key]='Private & Password'
  try:self.assertNotIn('Private',redact('Private & Password Private%20%26%20Password'));self.assertNotIn('token-value',redact("setting 'idp_token_A' to 'token-value'"))
  finally:
   if previous is None:os.environ.pop(key,None)
   else:os.environ[key]=previous

@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java') and shutil.which('node'),'Native tools required')
class NativeTests(unittest.TestCase):
 def test_two_scopes_two_orders_and_injected_scope_owner_leak(self):
  command=['java','-Xmx512m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
  for case in ('shared','separate'):
   with tempfile.TemporaryDirectory() as folder:
    p=Path(folder)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    generated=generate(case,port=port);plan=generated.resource_maps['relationship_scenario_plan'];(p/'spec/js').mkdir(parents=True);(p/'config').mkdir();(p/'config/provengo.yml').write_text('version: 2\n');(p/'spec/js/interfaces.mealie.js').write_text(generated.interfaces_js);(p/'spec/js/stories.mealie.js').write_text(generated.stories_js)
    sample=subprocess.run(command+['sample','--size','2','--max-length','400','-o','samples.json',str(p)],capture_output=True,text=True,timeout=60);self.assertEqual(sample.returncode,0,sample.stdout+sample.stderr);self.assertTrue((p/'samples.json').exists(),sample.stdout+sample.stderr);data=json.loads((p/'samples.json').read_text());audit=audit_samples(data,plan);self.assertLess((p/'samples.json').stat().st_size,4*1024**2)
    captures=[]
    for index,fault in enumerate(['','','copy-owner','write-leak','regular-admin'] if case=='shared' else ['','','scope-leak']):
     env=dict(os.environ,IDENTITY_TEST_PORT=str(port),IDENTITY_TEST_FAULT=fault,SBT_REL_USERNAME='admin@example.invalid',SBT_REL_PASSWORD='admin-pass',SBT_IDP_A_PASSWORD='user-a-pass',SBT_IDP_B_PASSWORD='user-b-pass')
     server=subprocess.Popen(['node',str(ROOT/'tests/identity_http_mock.js')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
     try:
      self.assertEqual(server.stdout.readline().strip(),'READY');run=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if index==1 else 1),str(p)],env=env,capture_output=True,text=True,timeout=60);output=run.stdout+run.stderr;receipt=find_receipt(output)
      if fault=='regular-admin':self.assertNotEqual(run.returncode,0);self.assertIsNone(receipt);continue
      self.assertEqual(run.returncode,0,'\n'.join(l for l in output.splitlines() if 'WARN [' in l or 'ERR ' in l));self.assertIsNotNone(receipt)
      if fault:
       with self.assertRaises(IdentityMismatch,msg=case+' '+fault):validate_identity_receipts(receipt,plan)
      else:
       validate_identity_receipts(receipt,plan);captures.append(receipt);broken=copy.deepcopy(receipt);broken['identity_program']['observations'].pop('finish')
       with self.assertRaises(ValueError):validate_identity_receipts(broken,plan)
     finally:server.terminate();stdout,stderr=server.communicate(timeout=10);self.assertIn('"maximum_active":1',stdout)
    self.assertNotEqual(captures[0]['identity_program']['namespace'],captures[1]['identity_program']['namespace'])
    self.assertNotEqual(captures[0]['identity_program']['observations']['self_a']['body']['id'],captures[1]['identity_program']['observations']['self_a']['body']['id'])
