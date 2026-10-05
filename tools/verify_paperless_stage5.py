"""Offline evidence completeness check; no API requests and no bug classification."""
import hashlib,json,sys,zipfile
from pathlib import Path

def verify(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive names')
        summary=json.loads(z.read('campaign-summary.json'))
        if summary['status']!='STAGE5_SIX_RUNS_PASS' or len(summary['runs'])!=6:raise ValueError('Campaign is incomplete; preserve original before qualification')
        signatures={};counts={'checks':0,'responses':0}
        for result in summary['runs']:
            folder=result['case'].lower()+'-'+str(result['set'])+'/'
            accepted=json.loads(z.read(folder+'run-acceptance.json'));sample=json.loads(z.read(folder+'sample-acceptance.json'))
            if result!=accepted or accepted['status']!='STAGE5_FUNCTIONAL_PASS':raise ValueError('Inconsistent acceptance records')
            if hashlib.sha256(z.read(folder+'selected-sample.json')).hexdigest()!=sample['samples_sha256']:raise ValueError('Selected sample checksum mismatch')
            order=json.loads(z.read(folder+'step-order.json'))
            if order!=sample['order']:raise ValueError('Runtime/sample step order mismatch')
            checks=json.loads(z.read(folder+'checks.json'))
            if len(checks)!=result['checks'] or not all(c['passed'] and c['expected']==c['observed'] for c in checks):raise ValueError('Incomplete or failed semantic checks')
            http=[n for n in names if n.startswith(folder+'http/') and n.endswith('.json')]
            if len(http)!=result['responses']:raise ValueError('HTTP evidence count mismatch')
            for seq,name in enumerate(sorted(http),1):
                response=json.loads(z.read(name))
                if response['sequence']!=seq or 'response_body' not in response:raise ValueError('Missing response body/sequence')
            signature=tuple(sample['business_order']);signatures.setdefault(result['case'],set()).add(signature)
            counts['checks']+=len(checks);counts['responses']+=len(http)
        if len(signatures)!=3 or any(len(v)!=2 for v in signatures.values()):raise ValueError('Two distinct business orders were not executed per case')
    print('STAGE5_EVIDENCE_COMPLETE: six native executions; distinct business orders; '+str(counts['checks'])+' checks; '+str(counts['responses'])+' responses. No API requests sent.')
    return counts
if __name__=='__main__':verify(Path(sys.argv[1]))
