"""Generic finite lifecycle compiler: persisted prerequisite joins and entity actors."""
import json
from pathlib import Path
import paperless_stage1 as base

def expand(actors):
    steps={};chains={}
    for actor in actors:
        name=actor['entity'];chain=[];previous=None
        if name in chains:raise ValueError('Duplicate entity actor')
        for raw in actor['lifecycle']:
            item=dict(raw);key=item.pop('id')
            if key in steps:raise ValueError('Duplicate lifecycle step')
            deps=list(item.get('after',[]))
            if previous and previous not in deps:deps.append(previous)
            item['after']=deps;item['actor']=name;steps[key]=item;chain.append(key);previous=key
        chains[name]=chain
    for key,item in steps.items():
        if any(x not in steps for x in item['after']):raise ValueError('Unknown parent readiness event')
    done=set()
    while len(done)<len(steps):
        ready={k for k,v in steps.items() if k not in done and set(v['after'])<=done}
        if not ready:raise ValueError('Cyclic execution prerequisite graph')
        done|=ready
    return steps,chains

def compile_model(contract,profile,case,project):
    # Version operations and all checkpoint reads must be declared by the pinned contract.
    for path,method in [('/api/documents/merge_as_versions/','post'),('/api/documents/{id}/update_version/','post'),('/api/documents/{id}/versions/{version_id}/','patch'),('/api/documents/{id}/versions/{version_id}/','delete'),('/api/documents/{id}/','get'),('/api/documents/{id}/metadata/','get')]:
        if method not in contract['paths'].get(path,{}):raise ValueError('Version operation outside pinned contract: '+path)
    # Reuse the isolated native callback and common interfaces boundary.
    base.compile_model(contract,profile,case,project)
    chains=case['actor_steps'];deps={k:v['after'] for k,v in case['steps'].items()}
    stories='// @provengo summon rest\n// @provengo summon rtv\n'
    # Completion is persistent in the coordinator; actors need not observe a past parent event.
    # Only eligible frontiers are offered. A Ready event is consumed by exactly one entity actor.
    stories+='bthread("lifecycle-readiness",function(){var deps='+json.dumps(deps,separators=(',',':'))+',done={},count=0;while(count<Object.keys(deps).length){var eligible=Object.keys(deps).filter(function(k){return !done[k]&&deps[k].every(function(p){return done[p];});});if(!eligible.length)throw new Error("Lifecycle deadlock");var offered=eligible.map(function(k){return Event("S5:Ready",{id:k});});var chosen=sync({request:offered});var id=chosen.data.id;sync({waitFor:Event("S1:Step",{id:id})});sync({waitFor:Event("S1:Done",{id:id})});done[id]=true;count++;}sync({request:Event("S1:Complete",{steps:count})});});\n'
    for actor,chain in chains.items():
        stories+='bthread('+json.dumps('entity:'+actor)+',function(){'
        for key in chain:
            stories+='sync({waitFor:Event("S5:Ready",{id:'+json.dumps(key)+'})});sync({request:Event("S1:Step",{id:'+json.dumps(key)+'})});stage1_'+key+'();sync({request:Event("S1:Done",{id:'+json.dumps(key)+'})});'
        stories+='});\n'
    (project/'spec/js/stories.paperless.stage1.js').write_text(stories,encoding='utf-8')
    base.dump(project/'lifecycle-plan.json',{'actors':chains,'prerequisites':deps,'parent_completion_is_persistent':True,'http_concurrency':False})

def business_order(order,case):
    return [x for x in order if case['steps'][x].get('business')]
