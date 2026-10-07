"""Offline requalification of the first Stage2 false positive and representation deviation."""
import hashlib,json,sys,zipfile
from pathlib import Path
from paperless_stage1 import child_ids,audit_sample
PIN='cc3eecd261470ad0b0888c59f385a2201d8a68f22bfd1c4ae1693ba5efb07c42'
def verify(root):
    path=Path(root)/'evidence/stage2-children-oracle-20261005-181529/campaign-original.zip'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==PIN
    with zipfile.ZipFile(path) as z:
        def j(n):return json.loads(z.read(n))
        prefix='s2-hierarchy-control-1/'
        assert j(prefix+'failure.json')['error']=='T1.children'
        checks=j(prefix+'checks.json');failed=[c for c in checks if not c['passed']]
        assert len(failed)==1 and failed[0]['check']=='T1.children'
        assert child_ids(failed[0]['observed'])==failed[0]['expected']==[12]
        before=j(prefix+'hierarchy/check_A.json');after=j(prefix+'hierarchy/check_parent_2.json')
        assert len(before)==len(after)==7 and all(x['status']==200 for x in after.values())
        assert after['T2']['body']['parent']==13 and after['T1']['body']['parent'] is None
        embedded=after['T1']['body']['children'][0]
        assert embedded['id']==after['T2']['body']['id']==12 and embedded['parent']==13 and embedded['owner']==6
        for entity in ('A','B'):
            assert before[entity]['body']==after[entity]['body']
            assert after[entity+'_metadata']['body']['original_checksum']==hashlib.sha256(z.read(prefix+'inputs/'+entity+'.pdf')).hexdigest()
        for name,h in j(prefix+'model-hashes.json').items():assert hashlib.sha256(z.read(prefix+'model/'+name)).hexdigest()==h
        sample=j(prefix+'sample-acceptance.json')
        assert hashlib.sha256(z.read(prefix+'model/samples.json')).hexdigest()==sample['samples_sha256']
        assert audit_sample(j(prefix+'model/samples.json'),j(prefix+'model/stage1-plan.json'))==sample['order']
        responses=[j(n) for n in z.namelist() if n.startswith(prefix+'http/') and n.endswith('.json')]
        assert len(responses)==34 and all(r['http_status'] in (200,201) for r in responses)
        assert [r['step'] for r in responses if r['method']=='PATCH']==['attach_A','link_T2_T1']
    print('STAGE2_ORACLE_FALSE_POSITIVE_VERIFIED: direct child ID and parent match; document states/checksums preserved. Embedded children differ from pinned OpenAPI representation. No API requests sent.')
if __name__=='__main__':verify(sys.argv[1])
