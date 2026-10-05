"""Offline verification of completed live linked-resource deletion."""
import hashlib,json,sys,zipfile
from pathlib import Path
from paperless_stage1 import audit_sample
PIN='28fa4aa61d7f1d1e8f22a55e34f09b052d377115db77d643c8c2d1edf16b8166'
def verify(root):
    path=Path(root)/'evidence/stage3-complete-20261005-190045/campaign-original.zip'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==PIN
    with zipfile.ZipFile(path) as z:
        def j(n):return json.loads(z.read(n))
        summary=j('campaign-summary.json');user=j('ordinary-user.json')
        assert summary['status']=='STAGE3_SIX_RUNS_PASS' and len(summary['runs'])==6
        assert not user['is_staff'] and not user['is_superuser']
        assert {'documents.delete_tag','documents.delete_documenttype'}.issubset(user['permissions'])
        assert 'documents.delete_document' not in user['permissions']
        seen=set();fresh={k:set() for k in ('T','U','Y','A','B')};total_checks=total_http=0
        for r in summary['runs']:
            key=(r['case'],r['repetition']);assert key not in seen;seen.add(key)
            prefix=r['case'].lower()+'-'+str(r['repetition'])+'/'
            assert j(prefix+'run-acceptance.json')==r and r['native_exit_code']==0 and r['runtime_receipt_observed']
            ids=j(prefix+'bindings.json')['ids'];assert ids['T']!=ids['U'] and ids['A']!=ids['B']
            for k in fresh:assert ids[k] not in fresh[k];fresh[k].add(ids[k])
            plan=j(prefix+'model/stage1-plan.json');sample=j(prefix+'sample-acceptance.json')
            assert hashlib.sha256(z.read(prefix+'model/samples.json')).hexdigest()==sample['samples_sha256']
            assert audit_sample(j(prefix+'model/samples.json'),plan)==sample['order']==j(prefix+'step-order.json')
            for n,h in j(prefix+'model-hashes.json').items():assert hashlib.sha256(z.read(prefix+'model/'+n)).hexdigest()==h
            receipt=j(prefix+'runtime-receipt.json');assert receipt['ids']==ids and receipt['ordinary_user_id']==user['id'] and receipt['completed_steps']==len(plan['steps'])==r['step_count']
            checks=j(prefix+'checks.json');assert len(checks)==r['checks']==receipt['checks'] and all(c['passed'] for c in checks)
            http=sorted([j(n) for n in z.namelist() if n.startswith(prefix+'http/') and n.endswith('.json')],key=lambda x:x['sequence'])
            assert len(http)==r['target_responses']==receipt['target_http_responses']
            assert [x['sequence'] for x in http]==list(range(1,len(http)+1))
            deletes=[x for x in http if x['method']=='DELETE'];assert len(deletes)==1 and deletes[0]['http_status']==204
            deleted='Y' if r['case']=='S3-SHARED-TYPE-DELETE' else 'T'
            assert deletes[0]['path']=='/api/'+('document_types' if deleted=='Y' else 'tags')+'/'+str(ids[deleted])+'/'
            assert all(x['http_status'] in (200,201,204,404) for x in http)
            before=j(prefix+'deletion/'+('check_detached' if r['case']=='S3-DETACHED-DELETE-CONTROL' else 'check_shared')+'.json')
            final=j(prefix+'deletion/check_deleted.json');assert len(before)==len(final)==7
            for k in ('T','U','Y','A','B'):
                assert before[k]['status']==200
                assert final[k]['status']==(404 if k==deleted else 200)
                if k not in (deleted,'A','B'):assert final[k]['body']==before[k]['body']
            for k in ('A','B'):
                b=before[k]['body'];f=final[k]['body'];assert f['id']==ids[k] and f['owner']==user['id']
                assert set(b['tags'])==({ids['U']} if r['case']=='S3-DETACHED-DELETE-CONTROL' else {ids['T'],ids['U']})
                assert b['document_type']==ids['Y']
                assert set(f['tags'])==({ids['U']} if deleted=='T' else {ids['T'],ids['U']})
                assert f['document_type']==(None if deleted=='Y' else ids['Y'])
                for field in ('id','owner','title','content','correspondent','storage_path','custom_fields','notes','original_file_name','mime_type','page_count','root_document','versions'):
                    assert b.get(field)==f.get(field),(r['case'],field)
                metadata=final[k+'_metadata'];assert metadata['status']==200
                assert metadata['body']['original_checksum']==hashlib.sha256(z.read(prefix+'inputs/'+k+'.pdf')).hexdigest()
            after=[x for x in http if x['sequence']>deletes[0]['sequence']]
            assert len(after)==7 and all(x['method']=='GET' for x in after)
            assert sorted(x['http_status'] for x in after)==[200]*6+[404]
            total_checks+=len(checks);total_http+=len(http)
        assert seen=={(c,n) for c in ('S3-DETACHED-DELETE-CONTROL','S3-SHARED-TAG-DELETE','S3-SHARED-TYPE-DELETE') for n in (1,2)}
        assert total_checks==2004 and total_http==343
    print('STAGE3_COMPLETE_EVIDENCE_VERIFIED: six accepted native schedules; 2004 passing checks; 343 responses; six 204 deletions with verified association cleanup and preserved document bytes. No API requests sent.')
if __name__=='__main__':verify(sys.argv[1])
