"""Render a Provengo concurrency overlay from an OpenAPI-derived plan."""
from __future__ import annotations
import json
import re
from typing import Any, Dict, List


def _js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _cross_entity_lines(oracle: Dict[str, Any], index: int) -> List[str]:
    """Two independently prefixed items with separate controls and leased reads."""
    targets = []
    for target in oracle['targets']:
        parts = re.split(r'\{[^{}]+\}', target['path_template'])
        pattern = '^' + '[^/]+'.join(re.escape(part) for part in parts) + '$'
        targets.append({
            'operation_id': target['operation_id'], 'pattern': pattern,
            'method': target['method'], 'field': dict(target['fields'][0],
                candidate_a=_value(target['fields'][0], 'a'),
                candidate_b=_value(target['fields'][0], 'b')),
            'media_type': target.get('media_type') or 'application/json',
            'request_fields': [f['name'] for f in target.get('request_fields', [])],
            'success_statuses': target['success_statuses'],
        })
    minimum = int(oracle.get('prefix_min_rounds', 0))
    return [
        f'bthread("sbt:cross-entity:{_safe(oracle["oracle_id"])}",function(){{',
        f'  var __targets={_js(targets)}; var __minimum={minimum};',
        '  var __paths=[null,null],__stories=[null,null],__rounds=[0,0];',
        '  while(__rounds[0]<__minimum||__rounds[1]<__minimum){',
        '    var __next=sync({waitFor:EventSet("cross-entity verified prefix",function(e){',
        '      if(!e||e.name!=="SBT:PrefixVerified"||!e.data){return false;}',
        '      for(var k=0;k<2;k++){var t=__targets[k];if(e.data.operation_id===t.operation_id&&',
        '        new RegExp(t.pattern).test(e.data.path)&&__rounds[k]<__minimum&&',
        '        e.data.round===__rounds[k]+1&&(__paths[k]===null||__paths[k]===e.data.path)&&',
        '        (__stories[k]===null||__stories[k]===e.data.story)){return true;}}return false;})});',
        '    for(var k=0;k<2;k++){var t=__targets[k];if(__next.data.operation_id===t.operation_id&&',
        '      new RegExp(t.pattern).test(__next.data.path)&&__next.data.round===__rounds[k]+1&&',
        '      (__paths[k]===null||__paths[k]===__next.data.path)&&',
        '      (__stories[k]===null||__stories[k]===__next.data.story)){',
        '      __paths[k]=__next.data.path;__stories[k]=__next.data.story;__rounds[k]++;break;}}',
        '  }',
        f'  sync({{request:Event("SBT:ConcurrencyReady:{index}",{{oracle_id:{_js(oracle["oracle_id"])},paths:__paths,rounds:__rounds}})}});',
        f'  sync({{waitFor:Event("SBT:ConcurrencyPermit:{index}")}});',
        '  var __bodies=[],__baselines=[],__valid=true,__failure=null;',
        '  function __fail(stage,k){__valid=false;if(__failure===null){__failure={stage:stage,target_index:k};}}',
        '  for(var k=0;k<2;k++){',
        '    var __baseline=null;svc.get(__paths[k],{expectedResponseCodes:__sbtControlHttpStatuses,',
        '      callback:function(r){if(r.code===200){try{__baseline=JSON.parse(r.body);}catch(e){}}}});',
        '    var t=__targets[k];if(!__baseline||__baseline[t.field.name]===undefined||',
        '      t.request_fields.some(function(f){return __baseline[f]===undefined||__baseline[f]===null;})){__fail("baseline-unavailable",k);break;}',
        '    __baselines.push(__baseline);var __body={};',
        '    for(var p=0;p<t.request_fields.length;p++){var f=t.request_fields[p];__body[f]=__baseline[f];}',
        '    __body[t.field.name]=__sbtNextValue(__baseline[t.field.name],t.field);',
        '    if(__sbtEqual(__body[t.field.name],__baseline[t.field.name])){__fail("candidate-unchanged",k);break;}',
        '    __bodies.push(__body);',
        f'    var __ctrl="generated-control-{index}";',
        '    svc[t.method.toLowerCase()](__paths[k],{body:JSON.stringify(__body),',
        '      headers:{"Content-Type":t.media_type,"X-Provengo-Epoch-Id":__ctrl,',
        '      "X-Provengo-Operation-Id":__ctrl+"-op-"+k},expectedResponseCodes:__sbtControlHttpStatuses,',
        '      callback:function(r){if(t.success_statuses.indexOf(r.code)<0){__fail("control-status",k);}}});',
        '    var __check=null;svc.get(__paths[k],{headers:{"X-Provengo-Epoch-Id":__ctrl,',
        '      "X-Provengo-Operation-Id":__ctrl+"-observe-"+k},expectedResponseCodes:__sbtControlHttpStatuses,',
        '      callback:function(r){if(r.code===200){try{__check=JSON.parse(r.body);}catch(e){}}}});',
        '    if(!__check||!__sbtEqual(__check[t.field.name],__body[t.field.name])){__fail("control-readback",k);}',
        f'    var __reset="generated-reset-{index}";',
        '    var __carry={};for(var p=0;p<t.request_fields.length;p++){var f=t.request_fields[p];__carry[f]=__baseline[f];}',
        '    __carry[t.field.name]=__baseline[t.field.name];',
        '    svc[t.method.toLowerCase()](__paths[k],{body:JSON.stringify(__carry),',
        '      headers:{"Content-Type":t.media_type,"X-Provengo-Epoch-Id":__reset,',
        '      "X-Provengo-Operation-Id":__reset+"-op-"+k},expectedResponseCodes:__sbtControlHttpStatuses,',
        '      callback:function(r){if(t.success_statuses.indexOf(r.code)<0){__fail("reset-status",k);}}});',
        '    var __recheck=null;svc.get(__paths[k],{headers:{"X-Provengo-Epoch-Id":__reset,',
        '      "X-Provengo-Operation-Id":__reset+"-observe-"+k},expectedResponseCodes:__sbtControlHttpStatuses,',
        '      callback:function(r){if(r.code===200){try{__recheck=JSON.parse(r.body);}catch(e){}}}});',
        '    if(!__recheck||!__sbtEqual(__recheck[t.field.name],__baseline[t.field.name])){__fail("reset-readback",k);}',
        '  }',
        f'  if(!__valid){{sync({{request:Event("SBT:ConcurrencySkipped:{index}",{{reason:"cross-entity-control-failed",control_failure:__failure}})}});',
        f'    sync({{request:Event("SBT:ConcurrencyClosed:{index}")}});return;}}',
        # The mutation guard starts at Permit. Own controls are direct svc
        # calls, so it protects their readbacks without preventing their PUTs.
        f'  sync({{request:Event("SBT:CrossControlsComplete:{index}",{{oracle_id:{_js(oracle["oracle_id"])}}})}});',
        f'  var __epoch="generated-epoch-{index}";var __ops=[];',
        '  for(var k=0;k<2;k++){var t=__targets[k];__ops.push({operation_id:__epoch+"-op-"+k,',
        '    method:t.method,path:__paths[k],body:__bodies[k],delay_ms:0,',
        '    headers:{"Content-Type":t.media_type,"X-Provengo-Prefix-Phase":"epoch",',
        '      "X-Provengo-Prefix-Story":__stories[k],"X-Provengo-Prefix-Round":String(__rounds[k])}});}',
        f'  __sbtAdapter.post("/epochs",{{body:JSON.stringify({{epoch_id:__epoch,scenario:{_js(oracle["oracle_id"])},',
        '    operations:__ops,post_join_observations:__paths.map(function(p){return {method:"GET",path:p};})}),',
        '    expectedResponseCodes:[200]});',
        f'  sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{oracle_id:{_js(oracle["oracle_id"])}}})}});',
        '});',
    ]


def _value(field: Dict[str, Any], suffix: str) -> Any:
    enum = field.get("enum") or []
    if enum:
        return enum[0 if suffix == "a" else min(1, len(enum) - 1)]
    kind = field.get("type")
    if kind == "string":
        # When OpenAPI supplies a hex-shaped example, retain its documented
        # shape for both distinct values instead of inventing unconstrained
        # prose. This rule depends on the example's syntax, not the field name.
        example = field.get("example")
        if isinstance(example, str) and re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", example):
            if suffix == "a":
                return example
            last = example[-1]
            replacement = format((int(last, 16) + 1) % 16, "X" if last.isupper() else "x")
            return example[:-1] + replacement
        formatted = {
            "date-time": ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
            "date": ("2026-01-01", "2026-01-02"),
            "uuid": ("00000000-0000-4000-8000-000000000001",
                     "00000000-0000-4000-8000-000000000002"),
            "email": ("sbt-a@example.invalid", "sbt-b@example.invalid"),
            "hostname": ("sbt-a.invalid", "sbt-b.invalid"),
            "ipv4": ("192.0.2.1", "192.0.2.2"),
            "uri": ("https://example.invalid/a", "https://example.invalid/b"),
            "url": ("https://example.invalid/a", "https://example.invalid/b"),
        }
        if field.get("format") in formatted:
            return formatted[field["format"]][0 if suffix == "a" else 1]
        candidate = f"sbt_generated_{suffix}_{field['name']}"
        minimum = field.get("minLength")
        maximum = field.get("maxLength")
        if isinstance(minimum, int) and len(candidate) < minimum:
            candidate += "x" * (minimum - len(candidate))
        if isinstance(maximum, int):
            candidate = candidate[:maximum]
        return candidate
    if kind == "boolean":
        return suffix == "a"
    low = field.get("minimum")
    high = field.get("maximum")
    base = int(low) if isinstance(low, (int, float)) else 1
    candidate = base if suffix == "a" else base + 1
    if isinstance(high, (int, float)):
        candidate = min(candidate, int(high))
    return candidate


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _instance_ready_entity(entity_key: str) -> str:
    """Return the base-story resource label using only the derived path key."""
    tail = str(entity_key or "resource").strip("/").split("/")[-1]
    words = [part for part in re.split(r"[^A-Za-z0-9]+", tail) if part]
    return "".join(word[:1].upper() + word[1:] for word in words) or "Resource"


def _empirical_update_delete(oracle: Dict[str, Any], index: int,
                             post_join_observation: bool = False) -> List[str]:
    """Generate isolated serial controls and a real two-method adapter epoch."""
    runtime = oracle['runtime']
    label = runtime['instance_ready_label']
    field = oracle['fields'][0]
    ident = _safe(oracle['oracle_id'])
    value = _value(field, 'b')
    template = oracle['path_template']
    method = oracle['method'].lower()
    request_fields = oracle.get('request_fields', []) if method == 'put' else []
    read_statuses = [200, 400, 401, 403, 404, 409, 410, 422]
    update_statuses = sorted(set(oracle['success_statuses'] + [400, 401, 403, 404, 409, 410, 422]))
    delete_statuses = sorted(set(oracle['delete_success_statuses'] + [400, 401, 403, 404, 409, 410, 422]))
    dependencies = runtime.get('wait_for_closed_oracles', [])
    lines = []
    if dependencies:
        # Start the observer before any InstanceReady event can be emitted.
        # It remembers both signals, regardless of which arrives first.
        lines += [
            f'bthread("sbt:cross-method-dependency-gate:{index}", function(){{',
            '  var __closed={}; var __ready=false;',
            f'  var __children={_js(dependencies)};',
            '  while(!__ready || Object.keys(__closed).length<__children.length){',
            '    var __signal=sync({waitFor:EventSet("cross-method prerequisites",function(e){',
            '      if(!e || typeof e.name!=="string"){return false;}',
            f'      if(e.name==="SBT:EmpiricalDependencyReady:{index}"){{return !__ready;}}',
            '      for(var __k=0;__k<__children.length;__k++){',
            '        if(e.name==="SBT:ConcurrencyClosed:"+__children[__k] && !__closed[__children[__k]]){return true;}',
            '      } return false;',
            '    })});',
            f'    if(__signal.name==="SBT:EmpiricalDependencyReady:{index}"){{__ready=true;}}',
            '    else{__closed[__signal.name.substring("SBT:ConcurrencyClosed:".length)]=true;}',
            '  }',
            f'  sync({{request:Event("SBT:EmpiricalDependencyPermit:{index}")}});',
            '});',
        ]
    lines += [
        f'bthread("sbt:cross-method:{ident}", function(){{',
        '  var __paths=[];',
        '  var __readyByName={};',
        f'  var __readyPrefix={_js("InstanceReady:" + label + ":")};',
        '  for(var __i=0;__i<3;__i++){',
        '    var __created=sync({waitFor:EventSet("Cross-method verified instance",function(e){',
        '      if(!e || typeof e.name!=="string" || !e.data || e.name.indexOf(__readyPrefix)!==0){return false;}',
        '      var __number=e.name.substring(__readyPrefix.length);',
        '      return (__number==="1" || __number==="2" || __number==="3") && !__readyByName[e.name];',
        '    })});',
        '    __readyByName[__created.name]=__created.data;',
        '  }',
        '  for(var __i=1;__i<=3;__i++){',
        '    var __ready=__readyByName[__readyPrefix+__i];',
        f'    var __path={_js(template)};',
    ]
    for parameter, prop in sorted(runtime['path_binding_from_create_response'].items()):
        lines.append(f'    __path=__path.replace({_js("{"+parameter+"}")},String(__sbtReadPath(__ready,{_js(prop)})));')
    for parameter, prop in sorted(runtime['path_binding_from_create_request_path'].items()):
        lines.append(f'    __path=__path.replace({_js("{"+parameter+"}")},String(__ready[{_js(prop)}]));')
    lines += [
        '    if(__path.indexOf("{")>=0 || __path.indexOf("undefined")>=0 || __paths.indexOf(__path)>=0){return;}',
        '    __paths.push(__path);',
        '  }',
        f'  var __body={_js({field["name"]: value})};',
        *([f'  sync({{request:Event("SBT:EmpiricalDependencyReady:{index}")}});',
           f'  sync({{waitFor:Event("SBT:EmpiricalDependencyPermit:{index}")}});']
          if dependencies else []),
        '  var __bodies=[]; var __serialOk=true;',
        '  for(var __j=0;__j<3;__j++){',
        f'    var __check="cross-baseline-{index}-"+__j;',
        f'    svc.get(__paths[__j],{{headers:{{"X-Provengo-Epoch-Id":__check,"X-Provengo-Operation-Id":__check+"-observe"}},expectedResponseCodes:{_js(read_statuses)},callback:function(r){{try{{var __item=JSON.parse(r.body);var __full={{}};for(var __f of {_js(request_fields)}){{if(__item[__f]===undefined){{__serialOk=false;}}else{{__full[__f]=__item[__f];}}}}__full[{_js(field["name"])}]={_js(value)};__bodies.push(__full);if({_js(oracle["observation"]["success_statuses"])}.indexOf(r.code)<0){{__serialOk=false;}}}}catch(__e){{__serialOk=false;}}}}}});',
        '  }',
    ]
    if request_fields:
        lines.append('  if(!__serialOk || __bodies.length!==3){sync({request:Event("SBT:ConcurrencySkipped:%s",{reason:"read-derived-body-unavailable"})});sync({request:Event("SBT:ConcurrencyClosed:%s")});return;}' % (index,index))
    for side in ('a', 'b'):
        lines += [f'  var __ctrl="cross-control-{side}-{index}";',
                  f'  var __cp=__paths[{0 if side == "a" else 1}];']
        methods = ('update', 'delete') if side == 'a' else ('delete', 'update')
        for j, operation in enumerate(methods):
            if operation == 'update':
                # The reverse control establishes absence after DELETE.
                # A rejected update keeps the item absent; a successful PUT
                # might recreate it and needs a separate oracle, so stop this
                # update/delete experiment if the reverse PUT succeeds.
                accepted = (oracle['success_statuses'] if side == 'a' else
                            [code for code in (400, 404, 409, 410, 422)
                             if code not in oracle['success_statuses']])
                lines.append(f'  svc.{method}(__cp,{{body:JSON.stringify(__bodies[{0 if side == "a" else 1}]),headers:{{"Content-Type":{_js(oracle["media_type"])} ,"X-Provengo-Epoch-Id":__ctrl,"X-Provengo-Operation-Id":__ctrl+"-op-{j}"}},expectedResponseCodes:{_js(update_statuses)},callback:function(r){{if({_js(accepted)}.indexOf(r.code)<0){{__serialOk=false;}}}}}});')
            else:
                lines.append(f'  svc.delete(__cp,{{headers:{{"X-Provengo-Epoch-Id":__ctrl,"X-Provengo-Operation-Id":__ctrl+"-op-{j}"}},expectedResponseCodes:{_js(delete_statuses)},callback:function(r){{if({_js(oracle["delete_success_statuses"])}.indexOf(r.code)<0){{__serialOk=false;}}}}}});')
            absence = operation == 'delete' or (side == 'b' and operation == 'update')
            allowed = [400, 404, 410] if absence else oracle['observation']['success_statuses']
            lines.append(f'  svc.get(__cp,{{headers:{{"X-Provengo-Epoch-Id":__ctrl,"X-Provengo-Operation-Id":__ctrl+"-read-{j}"}},expectedResponseCodes:{_js(read_statuses)},callback:function(r){{if({_js(allowed)}.indexOf(r.code)<0){{__serialOk=false;}}}}}});')
    lines.append('  if(!__serialOk){sync({request:Event("SBT:ConcurrencySkipped:%s",{reason:"serial-control-failed"})});sync({request:Event("SBT:ConcurrencyClosed:%s")});return;}' % (index,index))
    lines += [
        '  sync({request:Event("SBT:ConcurrencyReady:%s",{oracle_id:%s})});' % (index, _js(oracle['oracle_id'])),
        f'  sync({{waitFor:Event("SBT:ConcurrencyPermit:{index}")}});',
        f'  var __epoch="generated-epoch-{index}";',
        '  var __ops=[{operation_id:__epoch+"-op-0",method:'+_js(oracle['method'])+',path:__paths[2],body:__bodies[2],headers:{"Content-Type":'+_js(oracle['media_type'])+'}},',
        '             {operation_id:__epoch+"-op-1",method:"DELETE",path:__paths[2],headers:{}}];',
        f'  __sbtAdapter.post("/epochs",{{body:JSON.stringify({{epoch_id:__epoch,scenario:{_js(oracle["oracle_id"])},operations:__ops'+(',post_join_observation:{method:"GET",path:__paths[2]}' if post_join_observation else '')+'}),expectedResponseCodes:[200]});',
        *([] if post_join_observation else [f'  svc.get(__paths[2],{{headers:{{"X-Provengo-Epoch-Id":__epoch,"X-Provengo-Operation-Id":__epoch+"-observe"}},expectedResponseCodes:{_js(read_statuses)}}});',]),
        '  sync({request:Event("SBT:ConcurrencyClosed:%s",{oracle_id:%s,path:__paths[2]})});' % (index, _js(oracle['oracle_id'])),
        '});',
    ]
    return lines


def render_verification_js(derived: Dict[str, Any], name: str,
                           story_profile: str = "full", *runtime_options: Any) -> str:
    # The Stage 6 verifier CLI supplies its generation profile and an
    # additional runtime option. Preserve the original full-profile renderer;
    # the long profile also needs producer-outcome completion to avoid waiting
    # forever when a dependency cannot be created.
    long_interleaving = (story_profile == "long-interleaving" or
                         "long-interleaving" in runtime_options)
    post_join_observation = "post-join-observation" in runtime_options
    require_serial_controls = "require-serial-controls" in runtime_options
    executable = [o for o in derived["concurrency_oracles"]
                  if o.get("runtime", {}).get("ready") and o["kind"] != "update-delete-linearizable"]
    lines: List[str] = [
        "//@provengo summon rest",
        f"// OpenAPI-only generated verifier/concurrency overlay for {name}.",
        "// No application names, business rules, or hidden SUT facts are inputs.",
        'var sbtConcurrencyAdapterUrl = (typeof sbtConcurrencyAdapterUrl !== "undefined") ? sbtConcurrencyAdapterUrl : "http://127.0.0.1:3459";',
        'const __sbtAdapter = new RESTSession(sbtConcurrencyAdapterUrl, "sbt-generated-concurrency", {headers:{"Content-Type":"application/json"}});',
        f"const __sbtVerificationCoverage = {_js(derived['counts'])};",
        'bthread("sbt:verification-coverage", function(){ sync({request:Event("SBT:VerificationCoverageReady", __sbtVerificationCoverage)}); });',
        'function __sbtReadPath(value,path){var parts=String(path).split("."); for(var i=0;i<parts.length;i++){if(value===null||typeof value==="undefined"){return undefined;} value=value[parts[i]];} return value;}',
        'function __sbtCreateEvent(operationId){ return EventSet("SBT created resource", function(e){ return !!(e && e.name && e.name.indexOf("Done: ")===0 && e.data && e.data.__operationId===operationId && e.data.__httpResponse); }); }',
    ]
    if derived.get('policy', {}).get('combined_campaign'):
        lines.extend([
            'function __sbtEqual(a,b){return JSON.stringify(a)===JSON.stringify(b);}',
            'function __sbtNextValue(current,field){return __sbtEqual(current,field.candidate_b)?field.candidate_a:field.candidate_b;}',
        ])
    if require_serial_controls:
        lines.append('var __sbtControlHttpStatuses=[]; for(var __sc=100;__sc<=599;__sc++){__sbtControlHttpStatuses.push(__sc);}')

    # A successful producer may be rendered as a standalone/action story rather
    # than the canonical CRUD creator.  Those stories publish Done events but
    # not InstanceReady events, leaving downstream OpenAPI-derived chains
    # unreachable.  Publish one generic compatibility event per distinct
    # producer.  Its name and keys are derived entirely from the concurrency
    # runtime binding; no SUT vocabulary or business rule is supplied here.
    producers: Dict[str, Dict[str, Any]] = {}
    for oracle in executable:
        runtime = oracle["runtime"]
        operation_id = runtime["create_operation_id"]
        producer = producers.setdefault(operation_id, {
            "entity_key": runtime.get("entity_key") or "resource",
            "response": {},
            "request": {},
        })
        producer["response"].update(runtime.get("path_binding_from_create_response", {}))
        producer["request"].update(runtime.get("path_binding_from_create_request_path", {}))
    contract_by_id = {o["operation_id"]: o for o in derived["contract_oracles"]}
    for operation_id, producer in sorted(producers.items()):
        ident = _safe(operation_id)
        ready_name = f'InstanceReady:{_instance_ready_entity(producer["entity_key"])}:1'
        exploration_ready = f'SBT:InstanceReady:{producer["entity_key"]}:1'
        if (long_interleaving and len(producer["response"]) > 1 and not producer["request"]):
            # A response-only composite identity can be published by both the
            # canonical creator and this compatibility bridge. Keep its
            # unavailable event from overtaking the bridge's completion.
            lines.extend([
                f'bthread("sbt:resource-bridge-guard:{ident}", function(){{',
                f'  sync({{waitFor:Event({_js("SBT:ResourceBridgeFinished:" + operation_id)}),'
                f'block:Event({_js("SBT:InstanceUnavailable:" + producer["entity_key"] + ":1")})}});',
                '});',
            ])
        lines.extend([
            f'bthread("sbt:resource-bridge:{ident}", function(){{',
            (f'  var __created = sync({{waitFor:EventSet("SBT producer outcome",function(e){{return !!(e && e.data && ((e.name && e.name.indexOf("Done: ")===0 && e.data.__operationId==={_js(operation_id)}) || (e.name==="SBT:OperationOutcome" && e.data.operation_id==={_js(operation_id)})));}})}});'
             if long_interleaving else
             f'  var __created = sync({{waitFor:__sbtCreateEvent({_js(operation_id)})}});'),
            *([
                '  if(__created.name==="SBT:OperationOutcome"){',
                f'    sync({{request:Event({_js("SBT:ResourceBridgeFinished:" + operation_id)},{{operation_id:{_js(operation_id)},valid:false}})}});',
                '    return;',
                '  }',
            ] if long_interleaving else []),
            '  var __resourceData={};',
            '  for(var __key in __created.data){if(__key.indexOf("__")!==0){__resourceData[__key]=__created.data[__key];}}',
        ])
        for parameter, response_field in sorted(producer["response"].items()):
            lines.append(f'  __resourceData[{_js(parameter)}]=__sbtReadPath(__created.data.__httpResponse,{_js(response_field)});')
        for parameter, request_parameter in sorted(producer["request"].items()):
            lines.append(f'  __resourceData[{_js(parameter)}]=__created.data[{_js(request_parameter)}];')
        if long_interleaving:
            bound = list(dict.fromkeys(list(producer["response"]) + list(producer["request"])))
            valid = (f'{_js(contract_by_id[operation_id]["success_statuses"])}.indexOf(__created.data.__httpCode)>=0' +
                     ''.join(f' && __resourceData[{_js(key)}]!==undefined && __resourceData[{_js(key)}]!==null'
                             for key in bound))
            lines.extend([
                f'  var __valid = {valid};',
                '  if(__valid){',
                f'    sync({{request:Event({_js(ready_name)},__resourceData)}});',
                f'    sync({{request:Event({_js(exploration_ready)},__resourceData)}});',
                f'    sync({{request:Event("SBT:ResourceBridgePublished",{{operation_id:{_js(operation_id)},ready_event:{_js(exploration_ready)}}})}});',
                '  }',
                f'  sync({{request:Event({_js("SBT:ResourceBridgeFinished:" + operation_id)},{{operation_id:{_js(operation_id)},valid:__valid}})}});',
                '});',
            ])
        else:
            lines.extend([
                f'  sync({{request:Event({_js(ready_name)},__resourceData)}});',
                f'  sync({{request:Event("SBT:ResourceBridgePublished",{{operation_id:{_js(operation_id)},ready_event:{_js(ready_name)}}})}});',
                '});',
            ])
    prefix_isolation_lines: List[str] = []
    for index, oracle in enumerate(executable):
        if oracle['kind'] == 'cross-entity-independent-writes':
            lines.extend(_cross_entity_lines(oracle, index))
            prefix_isolation_lines.extend([
                f'bthread("sbt:cross-isolation:{index}",function(){{',
                f'  sync({{waitFor:Event("SBT:ConcurrencyPermit:{index}")}});',
                f'  sync({{waitFor:Event("SBT:ConcurrencyClosed:{index}"),block:EventSet("block other mutation stories",function(e){{return !!(e&&["POST","PUT","PATCH","DELETE"].indexOf(e.name)>=0);}})}});',
                '});',
            ])
            continue
        if oracle['kind'] == 'empirical-update-delete':
            lines.extend(_empirical_update_delete(oracle, index, post_join_observation))
            continue
        runtime, fields = oracle["runtime"], oracle["fields"]
        bodies = []
        if oracle["kind"] in ('disjoint-writes-commute', 'disjoint-put-serial-outcomes'):
            suffixes = ["a", "b", "c", "d"]
            bodies = [{field["name"]: _value(field, suffixes[i])}
                      for i, field in enumerate(fields)]
        else:
            bodies = [{fields[0]["name"]: _value(fields[0], "a")},
                      {fields[0]["name"]: _value(fields[0], "b")}]
        ident = _safe(oracle["oracle_id"])
        binding = runtime["path_binding_from_create_response"]
        path_expr = _js(oracle["path_template"])
        lines.append(f'bthread("sbt:concurrency:{ident}", function(){{')
        if oracle.get("prefix_min_rounds"):
            # Multiple instances of the same OpenAPI resource can be created.
            # Binding the gated oracle to the first create leaves it stranded
            # when the long story executes against a later instance. Instead
            # bind to a successful, generated round 1 on this operation's
            # documented item path. The evaluator still verifies every HTTP
            # witness and the complete same-resource prefix before the epoch.
            parts = re.split(r"\{[^{}]+\}", oracle["path_template"])
            concrete_pattern = "^" + "[^/]+".join(re.escape(part) for part in parts) + "$"
            lines.extend([
                '  var __prefixStory=null; var __prefixCount=0;',
                f'  var __prefixPathPattern=new RegExp({_js(concrete_pattern)});',
                '  var __first=sync({waitFor:EventSet("verified matching prefix start",function(e){return !!(e&&e.name==="SBT:PrefixVerified"&&e.data&&e.data.round===1&&',
                f'    e.data.operation_id==={_js(oracle["operation_id"])}&&__prefixPathPattern.test(e.data.path));}})}});',
                '  var __path=__first.data.path; __prefixStory=__first.data.story; __prefixCount=1;',
            ])
            lines.extend([
                f'  while(__prefixCount < {int(oracle["prefix_min_rounds"])}){{',
                '    var __step=sync({waitFor:EventSet("verified same-resource prefix",function(e){return !!(e&&e.name==="SBT:PrefixVerified"&&e.data&&e.data.path===__path&&e.data.round===__prefixCount+1&&(__prefixStory===null||e.data.story===__prefixStory));})});',
                '    if(__prefixStory===null){__prefixStory=__step.data.story;} __prefixCount++;',
                '  }',
                f'  sync({{request:Event("SBT:PrefixAdmitted:{index}",{{oracle_id:{_js(oracle["oracle_id"])},path:__path,story:__prefixStory,rounds:__prefixCount}})}});',
                f'  sync({{request:Event("SBT:ConcurrencyReady:{index}",{{oracle_id:{_js(oracle["oracle_id"])},prefix_story:__prefixStory,prefix_rounds:__prefixCount}})}});',
                f'  sync({{waitFor:Event("SBT:ConcurrencyPermit:{index}")}});',
            ])
            # Adapter traffic bypasses Provengo's event picker. While this
            # oracle executes, prevent other generated stories from mutating
            # the observed resource (and thus confounding its final read).
            prefix_isolation_lines.extend([
                f'bthread("sbt:prefix-isolation:{index}",function(){{',
                f'  sync({{waitFor:Event("SBT:PrefixAdmitted:{index}")}});',
                f'  sync({{waitFor:Event("SBT:ConcurrencyClosed:{index}"),block:EventSet("block other mutation stories",function(e){{return !!(e&&["POST","PUT","PATCH","DELETE"].indexOf(e.name)>=0);}})}});',
                '});',
            ])
        else:
            lines.extend([
                f'  var __created = sync({{waitFor:__sbtCreateEvent({_js(runtime["create_operation_id"])})}});',
                f'  sync({{request:Event("SBT:ConcurrencyReady:{index}",{{oracle_id:{_js(oracle["oracle_id"])}}})}});',
                f'  sync({{waitFor:Event("SBT:ConcurrencyPermit:{index}")}});',
                f'  var __path = {path_expr};',
            ])
            for parameter, response_field in binding.items():
                lines.append(f'  __path = __path.replace({_js("{" + parameter + "}")}, String(__sbtReadPath(__created.data.__httpResponse,{_js(response_field)})));')
            for parameter, request_parameter in runtime.get("path_binding_from_create_request_path", {}).items():
                lines.append(f'  __path = __path.replace({_js("{" + parameter + "}")}, String(__created.data[{_js(request_parameter)}]));')
        exclusive = bool(oracle.get('exclusive_control_lease'))
        if exclusive:
            # The proxy waits for in-flight writers before granting the lease.
            # Keep it until after the adapter's final read; all control writes
            # retain their original epoch tags for the existing evaluator.
            lines.extend([
                f'  var __leaseOwner="generated-epoch-{index}";',
                '  var __leaseBody=JSON.stringify({path:__path,epoch_id:__leaseOwner});',
                '  svc.post("/__sbt/lease",{body:__leaseBody,headers:{"Content-Type":"application/json","X-SBT-Research-Lifecycle":"exclusive"},expectedResponseCodes:[200]});',
                '  try {',
            ])
        control_start = len(lines)
        lines.extend([
            f'  var __bodies = {_js(bodies)};',
            '  var __baseline = null;',
            '  svc.get(__path,{expectedResponseCodes:[200],callback:function(r){try{__baseline=JSON.parse(r.body);}catch(e){__baseline=null;}}});',
        ])
        if oracle['kind'] == 'noop-versus-change':
            field = oracle['fields'][0]
            lines.extend([
                f'  if(!__baseline||__baseline[{_js(field["name"])}]===undefined){{sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{reason:"noop-baseline-unavailable"}})}});return;}}',
                f'  __bodies[0][{_js(field["name"])}]=__baseline[{_js(field["name"])}];',
                f'  __bodies[1][{_js(field["name"])}]=__sbtNextValue(__baseline[{_js(field["name"])}],{{candidate_a:{_js(_value(field,"a"))},candidate_b:{_js(_value(field,"b"))}}});',
                f'  if(__sbtEqual(__bodies[0][{_js(field["name"])}],__bodies[1][{_js(field["name"])}])){{sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{reason:"noop-distinct-value-unavailable"}})}});return;}}',
            ])
        if oracle["method"] == "PUT" or oracle.get("request_carry_fields"):
            request_fields = ([field["name"] for field in oracle.get("request_fields", [])]
                              if oracle["method"] == "PUT" else oracle["request_carry_fields"])
            lines.extend([
                f'  var __requestFields = {_js(request_fields)};',
                *([f'  if(!__baseline || __requestFields.some(function(__rf){{return __baseline[__rf]===undefined || __baseline[__rf]===null;}})){{sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{oracle_id:{_js(oracle["oracle_id"])},reason:"documented-carry-fields-unavailable"}})}});return;}}']
                  if oracle.get("request_carry_fields") else []),
                '  for(var __m=0;__m<__bodies.length;__m++){var __full={}; for(var __n=0;__n<__requestFields.length;__n++){var __rf=__requestFields[__n]; if(__baseline && __baseline[__rf]!==undefined){__full[__rf]=__baseline[__rf];}} for(var __override in __bodies[__m]){__full[__override]=__bodies[__m][__override];} __bodies[__m]=__full;}',
            ])
        method_lower = oracle["method"].lower()
        media_type = oracle.get("media_type") or "application/json"
        noop_mid = ''
        if oracle['kind'] == 'noop-versus-change':
            field_name = _js(oracle['fields'][0]['name'])
            noop_mid = (' if(__i===0){var __noopRead=null;svc.get(__path,{headers:{"X-Provengo-Epoch-Id":__controlEpoch,'
                        '"X-Provengo-Operation-Id":__controlEpoch+"-noop-observe"},expectedResponseCodes:__sbtControlHttpStatuses,'
                        'callback:function(r){if(r.code===200){try{__noopRead=JSON.parse(r.body);}catch(e){}}}});'
                        'if(!__noopRead||!__sbtEqual(__noopRead[' + field_name + '],__baseline[' + field_name + '])){__serialOk=false;}}')
        lines.extend([
            f'  var __controlEpoch = "generated-control-{index}";',
            *(['  var __serialOk=true;'] if require_serial_controls else []),
            f'  for(var __i=0;__i<__bodies.length;__i++){{ svc.{method_lower}(__path,{{body:JSON.stringify(__bodies[__i]),headers:{{"Content-Type":{_js(media_type)},"X-Provengo-Epoch-Id":__controlEpoch,"X-Provengo-Operation-Id":__controlEpoch+"-op-"+__i}},expectedResponseCodes:' + ('__sbtControlHttpStatuses' if require_serial_controls else _js(oracle["success_statuses"])) + (',callback:function(r){if('+_js(oracle["success_statuses"])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else '') + '});' + noop_mid + ' }',
            '  svc.get(__path,{headers:{"X-Provengo-Epoch-Id":__controlEpoch,"X-Provengo-Operation-Id":__controlEpoch+"-observe"},expectedResponseCodes:' + ('__sbtControlHttpStatuses,callback:function(r){if('+_js(oracle['observation']['success_statuses'])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else '[200]') + '});',
            *([f'  if(!__serialOk){{sync({{request:Event("SBT:ConcurrencySkipped:{index}",{{reason:"sequential-control-failed",oracle_id:{_js(oracle["oracle_id"])}}})}});sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{reason:"sequential-control-failed"}})}});return;}}'] if require_serial_controls else []),
            f'  if(__baseline){{ var __reset={{}}; for(var __j=0;__j<__bodies.length;__j++){{for(var __f in __bodies[__j]){{if(__baseline[__f]!==undefined){{__reset[__f]=__baseline[__f];}}}}}} var __resetEpoch="generated-reset-{index}"; svc.{method_lower}(__path,{{body:JSON.stringify(__reset),headers:{{"Content-Type":{_js(media_type)},"X-Provengo-Epoch-Id":__resetEpoch,"X-Provengo-Operation-Id":__resetEpoch+"-op-0"}},expectedResponseCodes:' + ('__sbtControlHttpStatuses,callback:function(r){if('+_js(oracle['success_statuses'])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else _js(oracle["success_statuses"])) + '}); }',
        ])
        if oracle['kind'] in ('disjoint-put-serial-outcomes', 'noop-versus-change'):
            checked = _js([field['name'] for field in oracle['fields']])
            lines.extend([
                f'  var __resetRead=null;svc.get(__path,{{headers:{{"X-Provengo-Epoch-Id":"generated-reset-{index}","X-Provengo-Operation-Id":"generated-reset-{index}-observe"}},expectedResponseCodes:__sbtControlHttpStatuses,callback:function(r){{if(r.code===200){{try{{__resetRead=JSON.parse(r.body);}}catch(e){{}}}}}}}});',
                f'  if(!__baseline||!__resetRead||{checked}.some(function(f){{return __baseline[f]===undefined||__resetRead[f]===undefined||!__sbtEqual(__resetRead[f],__baseline[f]);}})){{__serialOk=false;}}',
            ])
        if oracle.get("reverse_sequential_control"):
            lines.extend([
                f'  var __reverseEpoch = "generated-reverse-control-{index}";',
                f'  for(var __r=__bodies.length-1;__r>=0;__r--){{ svc.{method_lower}(__path,{{body:JSON.stringify(__bodies[__r]),headers:{{"Content-Type":{_js(media_type)},"X-Provengo-Epoch-Id":__reverseEpoch,"X-Provengo-Operation-Id":__reverseEpoch+"-op-"+__r}},expectedResponseCodes:' + ('__sbtControlHttpStatuses,callback:function(r){if('+_js(oracle['success_statuses'])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else _js(oracle["success_statuses"])) + '}); }',
                '  svc.get(__path,{headers:{"X-Provengo-Epoch-Id":__reverseEpoch,"X-Provengo-Operation-Id":__reverseEpoch+"-observe"},expectedResponseCodes:' + ('__sbtControlHttpStatuses,callback:function(r){if('+_js(oracle['observation']['success_statuses'])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else '[200]') + '});',
                f'  if(__baseline){{ var __resetReverse={{}}; for(var __j=0;__j<__bodies.length;__j++){{for(var __f in __bodies[__j]){{if(__baseline[__f]!==undefined){{__resetReverse[__f]=__baseline[__f];}}}}}} var __resetReverseEpoch="generated-reset-reverse-{index}"; svc.{method_lower}(__path,{{body:JSON.stringify(__resetReverse),headers:{{"Content-Type":{_js(media_type)},"X-Provengo-Epoch-Id":__resetReverseEpoch,"X-Provengo-Operation-Id":__resetReverseEpoch+"-op-0"}},expectedResponseCodes:' + ('__sbtControlHttpStatuses,callback:function(r){if('+_js(oracle['success_statuses'])+'.indexOf(r.code)<0){__serialOk=false;}}' if require_serial_controls else _js(oracle["success_statuses"])) + '}); }',
            ])
            if oracle['kind'] == 'disjoint-put-serial-outcomes':
                checked = _js([field['name'] for field in oracle['fields']])
                lines.extend([
                    f'  var __reverseResetRead=null;svc.get(__path,{{headers:{{"X-Provengo-Epoch-Id":"generated-reset-reverse-{index}","X-Provengo-Operation-Id":"generated-reset-reverse-{index}-observe"}},expectedResponseCodes:__sbtControlHttpStatuses,callback:function(r){{if(r.code===200){{try{{__reverseResetRead=JSON.parse(r.body);}}catch(e){{}}}}}}}});',
                    f'  if(!__baseline||!__reverseResetRead||{checked}.some(function(f){{return __baseline[f]===undefined||__reverseResetRead[f]===undefined||!__sbtEqual(__reverseResetRead[f],__baseline[f]);}})){{__serialOk=false;}}',
                ])
        if require_serial_controls:
            lines.append(f'  if(!__serialOk){{sync({{request:Event("SBT:ConcurrencySkipped:{index}",{{reason:"sequential-reset-or-reverse-failed",oracle_id:{_js(oracle["oracle_id"])}}})}});sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{reason:"sequential-reset-or-reverse-failed"}})}});return;}}')
        lines.extend([
            f'  var __epoch = "generated-epoch-{index}";',
            '  var __ops=[]; for(var __k=0;__k<__bodies.length;__k++){__ops.push({operation_id:__epoch+"-op-"+__k,method:' + _js(oracle["method"]) + ',path:__path,body:__bodies[__k],delay_ms:0,headers:{"Content-Type":' + _js(media_type) + (',"X-Provengo-Prefix-Phase":"epoch","X-Provengo-Prefix-Story":__prefixStory,"X-Provengo-Prefix-Round":String(__prefixCount)' if oracle.get("prefix_min_rounds") else '') + '}});}',
            f'  __sbtAdapter.post("/epochs",{{body:JSON.stringify({{epoch_id:__epoch,scenario:{_js(oracle["oracle_id"])},operations:__ops'+(',preheld_resource_lease:true' if exclusive else '')+(',post_join_observation:{method:"GET",path:__path}' if post_join_observation else '')+'}),expectedResponseCodes:[200]});',
            *([] if post_join_observation else ['  svc.get(__path,{headers:{"X-Provengo-Epoch-Id":__epoch,"X-Provengo-Operation-Id":__epoch+"-observe"},expectedResponseCodes:[200]});']),
            f'  sync({{request:Event("SBT:ConcurrencyClosed:{index}",{{oracle_id:{_js(oracle["oracle_id"])},path:__path}})}});',
        ])
        if exclusive:
            for line_index in range(control_start, len(lines)):
                lines[line_index] = lines[line_index].replace(
                    '"X-Provengo-Epoch-Id":',
                    '"X-SBT-Research-Owner":__leaseOwner,"X-Provengo-Epoch-Id":')
            lines.append('  } finally {svc.post("/__sbt/release",{body:__leaseBody,headers:{"Content-Type":"application/json","X-SBT-Research-Lifecycle":"exclusive"},expectedResponseCodes:[200]});}')
        lines.append('});')
    lines.extend(prefix_isolation_lines)
    lines.append('function __sbtNamedEvent(__name){ return EventSet("SBT named event "+__name,function(e){return !!(e&&e.name===__name);}); }')
    lines.append('function __sbtAnyConcurrencyReady(){ return EventSet("SBT any concurrency ready",function(e){return !!(e&&e.name&&e.name.indexOf("SBT:ConcurrencyReady:")===0);}); }')
    lines.append('function __sbtAnyHttpDelete(){ return EventSet("SBT any HTTP DELETE",function(e){return !!(e&&e.name==="DELETE");}); }')
    empirical_only = bool(executable) and all(o['kind'] == 'empirical-update-delete' for o in executable)
    if empirical_only:
        # Both serial orders deliberately contain DELETE. The standard
        # controller's global DELETE block deadlocks the controls, including
        # when another oracle reaches Ready first. This opt-in profile's
        # generated stories do not request destructive cleanup operations.
        lines.append('function __sbtConcurrencyBusyBlock(){ return __sbtAnyConcurrencyReady(); }')
    else:
        lines.append('function __sbtConcurrencyBusyBlock(){ return EventSet("SBT concurrency admission or cleanup",function(e){return !!(e&&e.name&&(e.name==="DELETE"||e.name.indexOf("SBT:ConcurrencyReady:")===0));}); }')
    lines.append('bthread("sbt:concurrency-controller",function(){')
    # Admit each runtime-ready oracle independently. Some OpenAPI-derived
    # oracles can remain unrealizable in a concrete run because their producer
    # resource was never created. A global all-ready barrier would therefore
    # deadlock every otherwise executable oracle. While one oracle is active,
    # block additional Ready events so their requests remain pending and are
    # consumed by the controller after the active oracle closes.
    lines.append(f'  var __readySeen={{}}; var __readyCount=0; var __readyTotal={len(executable)};')
    lines.append('  while(__readyCount<__readyTotal){')
    if empirical_only:
        lines.append('    var __readyEvent=sync({waitFor:__sbtAnyConcurrencyReady()});')
    else:
        lines.append('    var __readyEvent=sync({waitFor:__sbtAnyConcurrencyReady(),block:__sbtAnyHttpDelete()});')
    lines.append('    if(__readySeen[__readyEvent.name]){continue;}')
    lines.append('    __readySeen[__readyEvent.name]=true; __readyCount++;')
    lines.append('    var __readyIndex=__readyEvent.name.substring("SBT:ConcurrencyReady:".length);')
    lines.append('    sync({request:Event("SBT:ConcurrencyPermit:"+__readyIndex),block:__sbtConcurrencyBusyBlock()});')
    # Closed includes diagnostic payload; match it by name. Keep other Ready
    # requests blocked until the active oracle has completed.
    lines.append('    sync({waitFor:__sbtNamedEvent("SBT:ConcurrencyClosed:"+__readyIndex),block:__sbtConcurrencyBusyBlock()});')
    lines.append('  }')
    lines.append('  sync({request:Event("SBT:AllGeneratedConcurrencyClosed")});')
    lines.append('});')
    return "\n".join(lines) + "\n"
