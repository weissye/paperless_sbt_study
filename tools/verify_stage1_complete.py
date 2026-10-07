"""Verify both preserved Stage1 live archives without server requests."""
import hashlib,json,re,sys,zipfile
from pathlib import Path
from paperless_stage1 import audit_sample
from verify_stage1_partial import verify as verify_partial
PIN='63dc147d98010f0af4354432eee251c001288e7ac766738806b1a439cb6cfb97'
def verify(root):
    root=Path(root);partial=root/'evidence/stage1-partial-20261005-174618/campaign-original.zip';verify_partial(partial)
    archive=root/'evidence/stage1-complete-20261005-180052/campaign-original.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==PIN
    with zipfile.ZipFile(archive) as z:
        def j(n):return json.loads(z.read(n))
        assert j('continuation.json')['original_campaign_sha256']==hashlib.sha256(partial.read_bytes()).hexdigest()
        assert j('campaign-summary.json')['status']=='STAGE1_REMAINING_THREE_PASS'
        runs=j('campaign-summary.json')['runs'];assert [(r['case'],r['repetition']) for r in runs]==[('S1-INTERLEAVED-RENAME',2),('S1-DETACH-REATTACH',1),('S1-DETACH-REATTACH',2)]
        checks=0;responses=0
        for r in runs:
            prefix=r['case'].lower()+'-'+str(r['repetition'])+'/'
            assert r['native_exit_code']==0 and r['status']=='STAGE1_FUNCTIONAL_PASS'
            c=j(prefix+'checks.json');assert all(x['passed'] for x in c);checks+=len(c)
            order=j(prefix+'step-order.json');sa=j(prefix+'sample-acceptance.json');receipt=j(prefix+'runtime-receipt.json')
            assert order==sa['order']==audit_sample(j(prefix+'model/samples.json'),j(prefix+'model/stage1-plan.json'))
            assert hashlib.sha256(z.read(prefix+'model/samples.json')).hexdigest()==sa['samples_sha256']
            for n,h in j(prefix+'model-hashes.json').items():assert hashlib.sha256(z.read(prefix+'model/'+n)).hexdigest()==h
            http=[j(n) for n in z.namelist() if n.startswith(prefix+'http/') and n.endswith('.json')]
            assert len(http)==r['target_responses'] and all(x['http_status'] in (200,201) for x in http);responses+=len(http)
            assert receipt['completed_steps']==len(order) and receipt['checks']==len(c)
            log=z.read(prefix+'run-output.txt').decode();assert 'Test Result: SUCCESS' in log
            match=re.search(r"(?:STAGE1_NATIVE_RECEIPT\s+|setting\s+'stage1_receipt'\s+to\s+')(\{[^\n]+\})",log)
            assert match and json.JSONDecoder().raw_decode(match[1])[0]==receipt
        assert checks==937 and responses==150
    print('STAGE1_COMPLETE_EVIDENCE_VERIFIED: six accepted live schedules; 1562 passing checks; 261 responses in accepted runs. No API requests sent.')
if __name__=='__main__':verify(sys.argv[1])
