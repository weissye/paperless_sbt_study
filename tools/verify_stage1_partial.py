"""Offline verification of the pinned partial live campaign. No HTTP requests."""
import hashlib,json,re,sys,zipfile
from pathlib import Path
PIN='c15f19f99de8138a8c0f488c70e60fad66b0d09644d441ceaae1a122859839cc'
def verify(path):
    path=Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=PIN:raise ValueError('This continuation requires the archived 20261005-174618 campaign.')
    with zipfile.ZipFile(path) as z:
        def read(n):return json.loads(z.read(n))
        summary=read('campaign-summary.json');assert len(summary['runs'])==4
        total=0
        for i,r in enumerate(summary['runs']):
            prefix=r['case'].lower()+'-'+str(r['repetition'])+'/'
            checks=read(prefix+'checks.json');assert all(c['passed'] for c in checks);total+=len(checks)
            sample=read(prefix+'sample-acceptance.json');order=read(prefix+'step-order.json')
            assert hashlib.sha256(z.read(prefix+'model/samples.json')).hexdigest()==sample['samples_sha256']
            for name,digest in read(prefix+'model-hashes.json').items():assert hashlib.sha256(z.read(prefix+'model/'+name)).hexdigest()==digest
            from paperless_stage1 import audit_sample
            case=read(prefix+'model/stage1-plan.json')
            assert audit_sample(read(prefix+'model/samples.json'),case)==sample['order']
            assert order==sample['order'][:len(order)]
            http=[read(n) for n in z.namelist() if n.startswith(prefix+'http/') and n.endswith('.json')]
            assert len(http)==r['target_responses'] and all(x['http_status'] in (200,201) for x in http)
            log=z.read(prefix+'run-output.txt').decode()
            if i<3:
                assert r['status']=='STAGE1_FUNCTIONAL_PASS' and 'Test Result: SUCCESS' in log and order[-1]=='finish'
                receipt=read(prefix+'runtime-receipt.json')
                assert receipt['completed_steps']==len(order) and receipt['checks']==len(checks)
            else:
                assert r['status']=='INCOMPLETE' and order[-1]=='wait_B_11' and len(order)==21
                assert len(http)==13 and not any(x['method']=='PATCH' for x in http)
                assert 'HTTP/1.1 header parser received no bytes' in log and 'Test Fail Mode, skipping actuation' in log
        assert total==663
    print('PARTIAL_CAMPAIGN_VERIFIED: three complete passes; fourth stopped at local bridge transport; no relationship PATCH in fourth run. No API requests sent.')
    return True
if __name__=='__main__':verify(sys.argv[1])
