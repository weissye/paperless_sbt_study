"""OpenAPI operation shapes plus explicit version semantics; no inferred ownership policy."""
import json
from pathlib import Path
from paperless_lifecycles import expand
from paperless_stage1 import PIN,dump

def task(key,kind,after=(),**kwargs):return dict(id=key,kind=kind,after=list(after),**kwargs)
def actor(entity,steps):return {'entity':entity,'lifecycle':steps}
def profile():
    cases=[]
    for mode in ('CONTROL','INTERLEAVED','REMOVE-VERSION'):
        actors=[actor('identity',[task('start','start')])]
        for entity,family in [('T','tags'),('U','tags'),('Y','document_types')]:
            flow=[task('create_'+entity,'create',['start'],entity=entity,method='POST',path='/api/'+family+'/',codes=[201],body={'name':'$namespace-'+entity,'owner':'$owner',**({'matching_algorithm':0,'parent':None,'is_inbox_tag':False} if family=='tags' else {'matching_algorithm':0})}),task('read_'+entity,'read',entity=entity,method='GET',path='/api/'+family+'/{id}/',codes=[200])]
            if entity=='T':
                flow.append(task('rename_T','version_action',['merge_B'],operation='rename_tag',business=True))
                if mode=='REMOVE-VERSION':flow.append(task('remove_T','version_action',['remove_B'],operation='delete_tag',business=True))
            if entity=='Y':
                flow.append(task('rename_Y','version_action',['merge_C'],operation='rename_type',business=True))
                if mode=='REMOVE-VERSION':flow.append(task('remove_Y','version_action',['remove_T'],operation='delete_type',business=True))
            actors.append(actor(entity,flow))
        for entity in ('A','B','C','D'):
            flow=[task('upload_'+entity,'upload',['start'],entity=entity,method='POST',path='/api/documents/post_document/',codes=[200]),task('wait_'+entity,'wait',entity=entity),task('read_'+entity,'read',entity=entity,method='GET',path='/api/documents/{id}/',codes=[200]),task('checksum_'+entity,'metadata',entity=entity,method='GET',path='/api/documents/{id}/metadata/',codes=[200]),task('link_'+entity,'patch',['read_T','read_U','read_Y'],entity=entity,method='PATCH',path='/api/documents/{id}/',codes=[200],body={'tags':['$id:T','$id:U'],'document_type':'$id:Y'})]
            if entity=='A':
                flow += [task('rename_A','version_action',['link_B','link_D'],operation='rename_root',business=True),task('detach_A','version_action',['merge_B'],operation='detach_root_tag',business=True),task('reattach_A','version_action',operation='reattach_root_tag',business=True)]
            if entity in ('B','C'):
                deps=['link_A','link_D']+(['label_B'] if mode=='CONTROL' and entity=='C' else [])
                flow += [task('merge_'+entity,'version_action',deps,operation='merge',source=entity,business=True),task('label_'+entity,'version_action',operation='label',source=entity,business=True)]
            if entity=='B' and mode=='REMOVE-VERSION':flow.append(task('remove_B','version_action',['label_V'],operation='delete_version',source='B',business=True))
            actors.append(actor(entity,flow))
        # A distinct uploaded version enters the existing graph after all independent actors join.
        join=['label_B','label_C','reattach_A','rename_T','rename_Y','link_D']
        vflow=[task('upload_V','version_action',join,operation='upload_version',business=True),task('wait_V','version_action',operation='wait_version'),task('label_V','version_action',operation='label',source='V',business=True)]
        if mode=='REMOVE-VERSION':vflow.append(task('remove_V','version_action',['remove_B'],operation='delete_version',source='V',business=True))
        actors.append(actor('V',vflow))
        finaldeps=['label_V']
        if mode=='REMOVE-VERSION':
            finaldeps=['remove_B','remove_V','remove_T','remove_Y']
        actors.append(actor('verdict',[task('final_graph','version_action',finaldeps,operation='checkpoint'),task('finish','finish')]))
        steps,chains=expand(actors)
        cases.append({'id':'S5-'+mode,'steps':steps,'actor_steps':chains,'sampling_policy':'two distinct business orders' if mode!='CONTROL' else 'two fresh controls'})
    return {'version':1,'contract_sha256':PIN,'identity_configuration':'one ordinary user / one client','original_checksum_algorithm':'sha256','document_entities':['A','B','C','D'],'document_protected_fields':['content','correspondent','storage_path','custom_fields','notes','original_file_name','mime_type','page_count','root_document'],'poll_window_seconds':180,'ingestion_timeout_seconds':180,'cases':cases,'version_policy':{'metadata_stays_on_root':True,'explicit_version_checksum':'original input SHA256','membership':'exact owned version IDs','root_deletion':'not covered','external_document_reference_fields':'not covered'}}
if __name__=='__main__':dump(Path(__file__).parent.parent/'profiles/paperless-stage5-runtime.json',profile())
