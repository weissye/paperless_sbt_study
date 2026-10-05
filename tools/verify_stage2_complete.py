"""Offline verification of the completed live Paperless hierarchy campaign."""
import hashlib,json,sys,zipfile
from pathlib import Path
from paperless_stage1 import audit_sample,child_ids
PIN='e753d4f24334c50b3718cfa27548e2be562e153742b5a953bca17a127ea30727'
def verify(root):
    p=Path(root)/'evidence/stage2-complete-20261005-183241/campaign-original.zip'
    if hashlib.sha256(p.read_bytes()).hexdigest()!=PIN:raise ValueError('Original campaign checksum differs')
    with zipfile.ZipFile(p) as z:
        def j(n):return json.loads(z.read(n))
        summary=j('campaign-summary.json');user=j('ordinary-user.json')
        assert summary['status']=='STAGE2_SIX_RUNS_PASS' and len(summary['runs'])==6
        assert user['is_staff'] is False and user['is_superuser'] is False
        seen=set();entities={k:set() for k in ('T1','T2','T3','Y','A','B')};responses_total=checks_total=0
        for r in summary['runs']:
            key=(r['case'],r['repetition']);assert key not in seen;seen.add(key)
            prefix=r['case'].lower()+'-'+str(r['repetition'])+'/'
            assert j(prefix+'run-acceptance.json')==r
            ids=j(prefix+'bindings.json')['ids']
            assert len({ids[k] for k in ('T1','T2','T3')})==3 and ids['A']!=ids['B']
            for k in entities:assert ids[k] not in entities[k];entities[k].add(ids[k])
            checks=j(prefix+'checks.json');assert len(checks)==r['checks']==397 and all(c['passed'] is True for c in checks)
            assert r['native_exit_code']==0 and r['runtime_receipt_observed'] is True
            receipt=j(prefix+'runtime-receipt.json');assert receipt['completed_steps']==59 and receipt['ids']==ids and receipt['ordinary_user_id']==user['id']
            sample=j(prefix+'sample-acceptance.json');plan=j(prefix+'model/stage1-plan.json')
            assert hashlib.sha256(z.read(prefix+'model/samples.json')).hexdigest()==sample['samples_sha256']
            assert audit_sample(j(prefix+'model/samples.json'),plan)==sample['order']==j(prefix+'step-order.json')
            for name,h in j(prefix+'model-hashes.json').items():assert hashlib.sha256(z.read(prefix+'model/'+name)).hexdigest()==h
            http=sorted([j(n) for n in z.namelist() if n.startswith(prefix+'http/') and n.endswith('.json')],key=lambda x:x['sequence'])
            assert len(http)==r['target_responses']==receipt['target_http_responses']
            assert [x['sequence'] for x in http]==list(range(1,len(http)+1))
            mutation_step='reparent_T3' if r['case']=='S2-HIERARCHY-CONTROL' else 'attempt_cycle'
            writes=[x for x in http if x['method']=='PATCH'];last=writes[-1]
            assert last['step']==mutation_step and last['http_status']==(200 if mutation_step=='reparent_T3' else 400)
            assert all(x['http_status'] in (200,201) for x in http if x is not last)
            if mutation_step=='attempt_cycle':assert last['response_body']=={'parent':['Cannot set parent to a descendant.']}
            chain=j(prefix+'hierarchy/check_chain.json');final=j(prefix+'hierarchy/check_final.json')
            assert len(chain)==len(final)==7 and all(x['status']==200 for x in final.values())
            if mutation_step=='attempt_cycle':
                for k in ('T1','T2','T3','A','B'):assert chain[k]==final[k]
                for k in ('A_metadata','B_metadata'):assert chain[k]['body']['original_checksum']==final[k]['body']['original_checksum']
            expected_parents={'T1':None,'T2':ids['T1'],'T3':ids['T1'] if mutation_step=='reparent_T3' else ids['T2']}
            for k in expected_parents:
                b=final[k]['body'];assert b['id']==ids[k] and b['owner']==user['id'] and b['parent']==expected_parents[k]
                expected_children=sorted(ids[c] for c,parent in expected_parents.items() if parent==ids[k])
                assert child_ids(b['children'])==expected_children
            for k in ('A','B'):
                b=final[k]['body'];assert b['id']==ids[k] and b['owner']==user['id'] and b['document_type']==ids['Y']
                assert set(b['tags'])==({ids['T1']} if k=='A' else {ids['T1'],ids['T2']})
                assert chain[k]['body']==b
                assert final[k+'_metadata']['body']['original_checksum']==hashlib.sha256(z.read(prefix+'inputs/'+k+'.pdf')).hexdigest()
            # Confirm independent final reads happened after the last write.
            for entity in ('T1','T2','T3','A','B'):
                path='/api/'+('tags' if entity.startswith('T') else 'documents')+'/'+str(ids[entity])+'/'
                assert any(x['sequence']>last['sequence'] and x['method']=='GET' and x['path']==path and x['response_body']==final[entity]['body'] for x in http)
            checks_total+=len(checks);responses_total+=len(http)
        assert seen=={(case,rep) for case in ('S2-HIERARCHY-CONTROL','S2-CYCLE-2','S2-CYCLE-3') for rep in (1,2)}
        assert checks_total==2382 and responses_total==356
    print('STAGE2_COMPLETE_EVIDENCE_VERIFIED: six accepted native schedules; 2382 passing checks; 356 target responses; four cycle rejections with unchanged independent readbacks. No API requests sent.')
if __name__=='__main__':verify(sys.argv[1])
