"""Native compact callback tests against a fault-injected HTTP fixture."""
import copy,hashlib,json,os,shutil,socket,subprocess,tempfile,unittest,zipfile
from tools.classify_reference_review import classify
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples,find_receipt
from tools.copy_receipts import validate_copy_receipts,CopyMismatch
ROOT=Path(__file__).resolve().parents[1]


def generate(case='control',runtime=None,base='http://127.0.0.1:9925'):
    return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'native',base,771233,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/f'profiles/mealie-copy-{case}-scope.json').read_text()),relationship_runtime=runtime or json.loads((ROOT/f'profiles/mealie-copy-{case}-runtime.json').read_text()))


class CopyConfigurationTests(unittest.TestCase):
    def test_deterministic_and_http_only_in_interfaces(self):
        for case in ('control','source-first','copy-first','internal-reference'):
            a=generate(case);b=generate(case);self.assertEqual(a.stories_js,b.stories_js);self.assertEqual(a.interfaces_js,b.interfaces_js);self.assertNotRegex(a.stories_js,r'\bsvc\.');self.assertEqual(len(a.resource_maps['relationship_scenario_plan']['instances']['api/recipes']),4)
    def test_invalid_policy_rejected(self):
        base=json.loads((ROOT/'profiles/mealie-copy-control-runtime.json').read_text())
        for key,value in [('identity_field','slug'),('fresh_child_paths',['description']),('copy_operation','POST /missing'),('mutations',[{'side':'copy','path':'slug','suffix':'wrong'}]),('internal_reference',{'target_path':'bad'})]:
            cfg=copy.deepcopy(base);cfg['copy_isolation'][key]=value
            with self.assertRaises((ValueError,KeyError)):generate(runtime=cfg)


@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java'),'Native jar required')
class CopyNativeTests(unittest.TestCase):
    def test_native_healthy_and_injected_faults(self):
        command=['java','-Xmx512m','-jar',str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())]
        for case in ('control','source-first','copy-first','internal-reference'):
            with tempfile.TemporaryDirectory() as folder:
                project=Path(folder)
                with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                result=generate(case,base=f'http://127.0.0.1:{port}');plan=result.resource_maps['relationship_scenario_plan']
                (project/'spec/js').mkdir(parents=True);(project/'config').mkdir();(project/'config/provengo.yml').write_text('version: 2\n');(project/'spec/js/interfaces.native.js').write_text(result.interfaces_js);(project/'spec/js/stories.native.js').write_text(result.stories_js);(project/'relationship_scenario_plan.json').write_text(json.dumps(plan))
                sampled=subprocess.run(command+['sample','--size','2','--max-length','700','-o','samples.json',str(project)],capture_output=True,text=True,timeout=60)
                self.assertEqual(sampled.returncode,0,sampled.stdout+sampled.stderr);audit_samples(json.loads((project/'samples.json').read_text()),plan);self.assertLess((project/'samples.json').stat().st_size,128*1024**2)
                faults=['','','copy-child-reuse','copy-quantity','copy-incoming-migrated','copy-leak']+(['copy-dangling'] if case=='internal-reference' else [])
                if os.environ.get('COPY_TEST_INTEGRATION_ONLY'):faults=['','']+(['copy-dangling'] if case=='internal-reference' else [])
                for i,fault in enumerate(faults):
                    env=dict(os.environ,NATIVE_MOCK_PORT=str(port),NATIVE_MOCK_FAULT=fault,NATIVE_MOCK_UUID_PREFIX=hashlib.sha256((case+str(i)).encode()).hexdigest()[:8],SBT_REL_USERNAME='local',SBT_REL_PASSWORD='local');server=subprocess.Popen(['node',str(ROOT/'tests/native_http_mock.js'),str(project)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    try:
                        self.assertEqual(server.stdout.readline().strip(),'READY');run=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if i==1 else 1),str(project)],env=env,capture_output=True,text=True,timeout=60);output=run.stdout+run.stderr;receipt=find_receipt(output)
                        self.assertEqual(run.returncode,0,'\n'.join(x for x in output.splitlines() if 'WARN [' in x or 'ERR [' in x));self.assertIsNotNone(receipt)
                        review=project/'classification.zip'
                        with zipfile.ZipFile(review,'w') as z:
                            z.writestr('execution-review/run-acceptance.json',json.dumps({'live_accepted':not bool(fault),'runtime_receipt':receipt}))
                            z.writestr('execution-review/run-output.txt',output)
                            z.writestr('relationship_scenario_plan.json',json.dumps(plan))
                        self.assertEqual(classify(review)['status'],'COPY_CANDIDATE' if fault else 'PASS')
                        if os.environ.get('COPY_TEST_CAPTURE') and not fault:
                            capture=Path(os.environ['COPY_TEST_CAPTURE'])/case;capture.mkdir(parents=True,exist_ok=True);shutil.copyfile(review,capture/('live-'+str(2 if i==1 else 1)+'.zip'))
                        if fault:
                            with self.assertRaises(CopyMismatch,msg=case+' '+fault):validate_copy_receipts(receipt,plan)
                        else:
                            validate_copy_receipts(receipt,plan);self.assertEqual(receipt['owned_instances'],13);self.assertEqual(receipt['response_count'],result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
                            broken=copy.deepcopy(receipt);broken['copy_isolations'][0]['observations'].pop()
                            with self.assertRaises(ValueError):validate_copy_receipts(broken,plan)
                    finally:server.terminate();server.communicate(timeout=10)
