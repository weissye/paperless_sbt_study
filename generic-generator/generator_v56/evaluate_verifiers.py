"""Generic trace evaluator driven only by a generated verification manifest."""
from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    decoder = json.JSONDecoder()
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").replace("\x00", "").splitlines(), 1):
        rest = line.strip().lstrip("\ufeff")
        while rest:
            value, end = decoder.raw_decode(rest)
            if not isinstance(value, dict):
                raise ValueError(f"trace line {line_no} is not an object")
            value.setdefault("_index", len(rows))
            rows.append(value)
            rest = rest[end:].strip()
    return rows


def _pattern(template: str) -> re.Pattern[str]:
    parts, pos = [], 0
    for match in re.finditer(r"\{([^{}]+)\}", template):
        parts.append(re.escape(template[pos:match.start()]))
        parts.append(f"(?P<{re.sub(r'[^A-Za-z0-9_]', '_', match.group(1))}>[^/]+)")
        pos = match.end()
    parts.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(parts) + "$")


def _body(event: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = event.get(key)
    return value if isinstance(value, dict) else {}


def _request(event: Dict[str, Any]) -> Dict[str, Any]:
    return _body(event, "request") or _body(event, "request_body")


def _response(event: Dict[str, Any]) -> Dict[str, Any]:
    return _body(event, "response")


def _request_precondition(event: Dict[str, Any], oracle: Dict[str, Any]) -> Optional[str]:
    """Reject malformed generated inputs before judging the SUT response.

    A response-code mismatch is evidence against the SUT only when the
    request satisfies the request shape selected from the same OpenAPI
    operation.  Older traces without a recorded content type remain usable;
    body presence/shape can still be checked.
    """
    contract = oracle.get("request_contract")
    if not isinstance(contract, dict):
        return None
    request = event.get("request")
    if contract.get("required") and request is None:
        return "required-request-body-missing"
    if request is None:
        return None
    schema_type = contract.get("schema_type")
    if schema_type == "object" and not isinstance(request, dict):
        return "request-body-type-mismatch"
    if schema_type == "array" and not isinstance(request, list):
        return "request-body-type-mismatch"
    if isinstance(request, dict):
        missing = [name for name in contract.get("required_fields", [])
                   if name not in request]
        if missing:
            return "required-request-fields-missing:" + ",".join(sorted(missing))
    expected_media = str(contract.get("media_type") or "").lower()
    observed_media = str(event.get("request_content_type") or "").split(";", 1)[0].strip().lower()
    if expected_media and observed_media and expected_media != observed_media:
        return "request-content-type-mismatch"
    return None


def _find_next(events: List[Dict[str, Any]], start: int, method: str, concrete_path: str,
               stop_methods: Tuple[str, ...] = ()) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    for event in events[start + 1:]:
        if str(event.get("model_path", "")) != concrete_path:
            continue
        current = str(event.get("method", "")).upper()
        if current in stop_methods:
            return None, "superseded-before-observation"
        if current == method:
            return event, None
    return None, "observation-not-found"


def _prior_identity_change(events: List[Dict[str, Any]], observation: Dict[str, Any]) -> bool:
    """Recognize a stale path only with a preceding successful rename witness.

    A changed `name` in both the request and successful response must replace
    the final path segment; the later request must address that old path or a
    descendant. This does not infer success from a redirect on its own.
    """
    if observation.get("status") not in (301, 302, 307, 308):
        return False
    path = str(observation.get("model_path", ""))
    for event in events[:observation["_index"]]:
        old = str(event.get("model_path", "")).rstrip("/")
        if not old or not (path == old or path.startswith(old + "/")):
            continue
        if event.get("method", "").upper() not in ("PATCH", "PUT"):
            continue
        if not isinstance(event.get("status"), int) or not 200 <= event["status"] < 300:
            continue
        requested = _request(event).get("name")
        acknowledged = _response(event).get("name")
        if (isinstance(requested, str) and requested and requested == acknowledged and
                requested != old.rsplit("/", 1)[-1]):
            return True
    return False


def _contract_witnesses(events: List[Dict[str, Any]], manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for event in events:
        # Generated concurrency controls and epochs are judged once by the
        # concurrency layer. Counting their individual HTTP responses again
        # would inflate one invalid epoch into several contract violations.
        epoch_id = event.get("epoch_id")
        if isinstance(epoch_id, str) and epoch_id.startswith((
                "generated-control-", "generated-epoch-",
                "generated-reverse-control-", "generated-reset-reverse-",
                "cross-control-", "cross-baseline-")):
            continue
        method, path = str(event.get("method", "")).upper(), str(event.get("model_path", ""))
        candidates = [o for o in manifest["contract_oracles"] if o["method"] == method and _pattern(o["path_template"]).match(path)]
        if not candidates:
            continue
        oracle = candidates[0]
        precondition_error = _request_precondition(event, oracle)
        documented = set(oracle["success_statuses"]) | set(oracle["documented_error_statuses"])
        status = event.get("status")
        # A documented status match is observationally valid. An undocumented
        # rejection cannot establish a product contract fault: OpenAPI request
        # shape alone cannot prove authorization, resource existence, or
        # semantic validity of generated values. Keep the mismatch visible.
        # An undocumented successful response is independently observable.
        result = ("INCONCLUSIVE" if event.get("transport_error") else
                  "INCONCLUSIVE" if precondition_error else
                  "PASS" if status in documented else
                  "VIOLATED" if isinstance(status, int) and 200 <= status < 400 else
                  "INCONCLUSIVE")
        stale_identity = result == "VIOLATED" and _prior_identity_change(events, event)
        if stale_identity:
            result = "INCONCLUSIVE"
        out.append({"oracle_id": oracle["oracle_id"], "kind": oracle["kind"],
                    "trigger_event": event["_index"], "result": result,
                    "expected": {"status_in": sorted(documented)}, "observed": {"status": status},
                    **({} if result == "PASS" else {"reason":
                        "upstream-transport-failure" if event.get("transport_error") else
                        ("invalid-test-input:" + precondition_error)
                        if precondition_error else
                        "stale-path-after-observed-identity-change" if stale_identity else
                        "undocumented-response-status" if result == "VIOLATED" else
                        "undocumented-error-preconditions-unproven"})})
    return out


def _state_witnesses(events: List[Dict[str, Any]], manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    by_operation = {o["operation_id"]: o for o in manifest["state_oracles"]}
    contract = {o["operation_id"]: o for o in manifest["contract_oracles"]}
    for event in events:
        # An epoch-labelled mutation must be judged together with its peers
        # and the independent post-join read. Its response contract is still
        # checked above for every individual request.
        if isinstance(event.get("epoch_id"), str):
            continue
        method, path = str(event.get("method", "")).upper(), str(event.get("model_path", ""))
        matching = [c for c in contract.values() if c["method"] == method and _pattern(c["path_template"]).match(path)]
        if not matching:
            continue
        oracle = by_operation.get(matching[0]["operation_id"])
        if not oracle or event.get("status") not in oracle["trigger_success_statuses"]:
            continue
        kind, observation, reason = oracle["kind"], None, None
        concrete_observation_path = path
        if kind == "create-visibility":
            concrete_observation_path = oracle["observation"]["path_template"]
            response = _response(event)
            for parameter, field in oracle["observation"]["path_binding_from_response"].items():
                value: Any = response
                for part in str(field).split("."):
                    if not isinstance(value, dict) or part not in value:
                        value = None
                        break
                    value = value[part]
                if value is None:
                    reason = "created-identity-missing-from-response"
                    break
                concrete_observation_path = concrete_observation_path.replace("{" + parameter + "}", str(value))
            create_match = _pattern(oracle["path_template"]).match(path)
            create_params = create_match.groupdict() if create_match else {}
            for parameter, source_parameter in oracle["observation"].get("path_binding_from_request_path", {}).items():
                source_key = re.sub(r"[^A-Za-z0-9_]", "_", source_parameter)
                if source_key not in create_params:
                    reason = "created-parent-identity-missing-from-request-path"
                    break
                concrete_observation_path = concrete_observation_path.replace(
                    "{" + parameter + "}", str(create_params[source_key]))
        if reason is None:
            observation, reason = _find_next(events, event["_index"], "GET", concrete_observation_path,
                                             tuple(oracle.get("superseding_methods", ())))
        observed_body = _response(observation) if observation else {}
        request = _request(event)
        if observation is None:
            result = "INCONCLUSIVE"
        elif observation.get("transport_error"):
            result, reason = "INCONCLUSIVE", "observation-upstream-transport-failure"
        elif observation.get("status") in (401, 403):
            # The observation no longer has permission to read the resource.
            # It cannot establish whether an earlier acknowledged write persisted,
            # or whether a deleted resource still exists. Preserve the recorded
            # HTTP contract result separately; do not claim a state violation.
            result, reason = "INCONCLUSIVE", "observation-not-authorized"
        elif kind == "create-visibility" and observation.get("status") in (400, 409, 422):
            # A rejected item GET alone cannot distinguish a missing object
            # from an authorization/validation precondition. An independent
            # positive observation is required before asserting disappearance.
            result, reason = "INCONCLUSIVE", "item-read-rejected-without-independent-visibility"
        elif kind == "delete-absence":
            result = "PASS" if observation.get("status") in oracle["observation"]["absence_statuses"] else "VIOLATED"
            if result == "VIOLATED": reason = "deleted-resource-still-observable"
        else:
            allowed = oracle["observation"]["success_statuses"]
            fields = {f["name"] for f in oracle.get("fields", [])}
            acknowledged_body = _response(event)
            acknowledged = {k: acknowledged_body[k] for k in fields
                            if k in acknowledged_body}
            comparable_request = {k: v for k, v in request.items() if k in fields}
            if observation.get("status") not in allowed:
                if _prior_identity_change(events, observation):
                    result, reason = "INCONCLUSIVE", "stale-path-after-observed-identity-change"
                else:
                    result, reason = "VIOLATED", "state-observation-failed"
            elif not acknowledged:
                result, reason = "INCONCLUSIVE", "acknowledged-state-unobservable"
            elif any(k not in observed_body or not _same_value(observed_body[k], value)
                     for k, value in acknowledged.items()):
                result, reason = "VIOLATED", "acknowledged-field-not-persistent"
            elif any(k in acknowledged and not _same_value(acknowledged[k], value)
                     for k, value in comparable_request.items()):
                result, reason = "INCONCLUSIVE", "server-canonicalized-request-value"
            else:
                result = "PASS"
        out.append({"oracle_id": oracle["oracle_id"], "kind": kind,
                    "trigger_event": event["_index"],
                    "observation_event": observation.get("_index") if observation else None,
                    "resource_path": concrete_observation_path, "result": result,
                    **({"persistence_result": "PASS"}
                       if reason == "server-canonicalized-request-value" else {}),
                    **({} if not reason else {"reason": reason})})
    return out


def _time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _overlap(events: List[Dict[str, Any]]) -> bool:
    try:
        return max(_time(e["upstream_started_utc"]) for e in events) < min(
            _time(e["upstream_completed_utc"]) for e in events)
    except (KeyError, TypeError, ValueError):
        return False


def _intervening_write(events: List[Dict[str, Any]], operations: List[Dict[str, Any]],
                       observation: Optional[Dict[str, Any]], path: str) -> bool:
    """A post-epoch read cannot prove the epoch's final state after another write.

    Compare the actual upstream intervals where available; the trace order
    is used only for older traces without timestamps. Fail closed when an
    unrelated write overlaps the interval before the observation completes.
    """
    if observation is None:
        return False
    epoch_ids = {id(e) for e in operations}
    try:
        epoch_end = max(_time(e["upstream_completed_utc"]) for e in operations)
        read_end = _time(observation["upstream_completed_utc"])
    except (KeyError, TypeError, ValueError):
        epoch_end = read_end = None
    for event in events:
        if id(event) in epoch_ids or event.get("model_path") != path:
            continue
        if str(event.get("method", "")).upper() not in {"PUT", "PATCH", "POST", "DELETE"}:
            continue
        if epoch_end is not None:
            try:
                if (_time(event["upstream_started_utc"]) <= read_end and
                        _time(event["upstream_completed_utc"]) >= epoch_end):
                    return True
                continue
            except (KeyError, TypeError, ValueError):
                pass
        if (max(e.get("_index", -1) for e in operations) < event.get("_index", -1)
                < observation.get("_index", -1)):
            return True
    return False


def _varying_keys(bodies: List[Dict[str, Any]]) -> set[str]:
    """Return fields whose values differ across operation bodies.

    PUT requests contain baseline fields copied from the independent read.
    Those stable fields are transport requirements, not concurrent intents.
    """
    missing = object()
    keys = set().union(*(set(body) for body in bodies)) if bodies else set()
    return {key for key in keys
            if len({json.dumps(body.get(key, missing), sort_keys=True, default=str)
                    for body in bodies}) > 1}


def _same_value(left: Any, right: Any) -> bool:
    """Compare JSON-compatible values without requiring hashability."""
    return json.dumps(left, sort_keys=True, default=str) == json.dumps(
        right, sort_keys=True, default=str)


def _sequential_control_state(
        oracle: Dict[str, Any], operations: List[Dict[str, Any]],
        observation: Dict[str, Any], intent_fields: set[str]) -> tuple[bool, str]:
    """Validate that a successful sequential control persisted its intent.

    HTTP success alone is not a valid control: an API may accept a field but
    normalize, ignore, or reject it semantically.  Such a control cannot prove
    that a different concurrent outcome is a concurrency defect.
    """
    observed = _response(observation)
    if not isinstance(observed, dict):
        return False, "sequential-control-state-unobservable"

    kind = oracle.get("kind", "")
    bodies = [_request(event) for event in operations]
    successful = [body for body, event in zip(bodies, operations)
                  if event.get("status") in oracle.get("success_statuses", [])]

    if kind in {"same-field-one-successful-value-visible",
                "same-field-one-successful-value-visible-domain"}:
        if len(intent_fields) != 1:
            return False, "sequential-control-state-unresolved"
        field = next(iter(intent_fields))
        legal_values = [body[field] for body in successful if field in body]
        if not legal_values or field not in observed:
            return False, "sequential-control-state-unobservable"
        if not any(_same_value(observed[field], value) for value in legal_values):
            return False, "sequential-control-state-mismatch"
        return True, ""

    if kind == 'noop-versus-change':
        field = oracle['fields'][0]['name']
        if (len(bodies) != 2 or field not in bodies[1] or field not in observed or
                not _same_value(observed[field], bodies[1][field])):
            return False, 'noop-change-control-not-observed'
        return True, ''

    if kind in {"disjoint-writes-commute", "disjoint-writes-commute-domain"}:
        for field in intent_fields:
            values = []
            for body in successful:
                if field in body and not any(_same_value(body[field], old) for old in values):
                    values.append(body[field])
            # A unique value is required. Multiple values usually mean PUT
            # baseline reconstruction, where the intended value is ambiguous.
            if len(values) != 1:
                return False, "sequential-control-state-unresolved"
            if field not in observed:
                return False, "sequential-control-state-unobservable"
            if not _same_value(observed[field], values[0]):
                return False, "sequential-control-state-mismatch"
        return True, ""

    # Update/delete histories already have a dedicated absence oracle.  No
    # additional field-persistence claim is made here.
    return True, ""


def _verified_reset_state(events, reset_group, fields, epoch_operations,
                          require_quiet_until_epoch=False, success_statuses=()):
    """Prove a real item read sees the baseline after a generated reset."""
    writes = [e for e in reset_group if str(e.get('method', '')).upper() in ('PUT', 'PATCH')]
    reads = [e for e in reset_group if str(e.get('method', '')).upper() == 'GET' and
             str(e.get('operation_id', '')).endswith('-observe')]
    if len(writes) != 1 or len(reads) != 1 or not epoch_operations:
        return False
    write, read = writes[0], reads[0]
    if (write.get('status') not in success_statuses or read.get('status') != 200 or
            write.get('model_path') != read.get('model_path') or
            write.get('model_path') != epoch_operations[0].get('model_path')):
        return False
    body, observed = _request(write), _response(read)
    if not all(field in body and field in observed and _same_value(body[field], observed[field])
               for field in fields):
        return False
    try:
        write_end = _time(write['upstream_completed_utc'])
        read_start = _time(read['upstream_started_utc'])
        read_end = _time(read['upstream_completed_utc'])
        epoch_start = min(_time(e['upstream_started_utc']) for e in epoch_operations)
    except (KeyError, TypeError, ValueError):
        return False
    if not write_end <= read_start <= read_end < epoch_start:
        return False
    if require_quiet_until_epoch:
        for event in events:
            if (event.get('model_path') == write.get('model_path') and
                    str(event.get('method', '')).upper() in ('POST', 'PUT', 'PATCH', 'DELETE')):
                try:
                    started = _time(event['upstream_started_utc'])
                    ended = _time(event['upstream_completed_utc'])
                except (KeyError, TypeError, ValueError):
                    return False
                if started < epoch_start and ended > read_end:
                    return False
    return True


def _verified_prefix(events: List[Dict[str, Any]], operations: List[Dict[str, Any]],
                     path: str, minimum: int) -> tuple[bool, str, Dict[str, Any]]:
    """Check ordered tagged GET witnesses from the same story and item."""
    tags = {(str(e.get("prefix_story")), str(e.get("prefix_round"))) for e in operations}
    if len(tags) != 1:
        return False, "prefix-epoch-metadata-missing-or-inconsistent", {}
    story, count_str = next(iter(tags))
    if story in ("None", "") or not count_str.isdigit() or int(count_str) < minimum:
        return False, "prefix-epoch-depth-insufficient", {}
    try:
        epoch_start = min(_time(e["upstream_started_utc"]) for e in operations)
    except (KeyError, TypeError, ValueError):
        return False, "prefix-epoch-timing-unavailable", {}
    by_round: Dict[int, List[Dict[str, Any]]] = {}
    for e in events:
        if (e.get("prefix_phase") == "verified-round" and
                e.get("prefix_story") == story and
                e.get("method") == "GET" and e.get("model_path") == path and
                str(e.get("prefix_round", "")).isdigit()):
            by_round.setdefault(int(e["prefix_round"]), []).append(e)
    previous = None
    for number in range(1, minimum + 1):
        choices = by_round.get(number, [])
        if len(choices) != 1 or choices[0].get("status") != 200:
            return False, "prefix-verified-round-missing-or-rejected", {"round": number}
        try:
            completed = _time(choices[0]["upstream_completed_utc"])
        except (KeyError, TypeError, ValueError):
            return False, "prefix-round-timing-unavailable", {"round": number}
        if completed >= epoch_start or (previous is not None and completed <= previous):
            return False, "prefix-not-causally-before-epoch", {"round": number}
        previous = completed
    return True, "", {"story": story, "rounds": minimum,
                       "last_verified_utc": previous.isoformat(), "path": path}


def _independent_resource_witness(events, groups, epoch_id, operations, oracle):
    """Independent writes require separate controls, prefixes, and final reads."""
    ordered = sorted(operations, key=lambda e: str(e.get('operation_id', '')))
    targets = oracle['targets']
    prefixes = []
    reasons = []
    controls = groups.get(epoch_id.replace('generated-epoch-', 'generated-control-', 1), [])
    resets = groups.get(epoch_id.replace('generated-epoch-', 'generated-reset-', 1), [])
    observations = [e for e in groups[epoch_id] if e.get('method') == 'GET' and
                    '-observe-' in str(e.get('operation_id', ''))]
    for i, (op, target) in enumerate(zip(ordered, targets)):
        path = str(op.get('model_path', ''))
        if not _pattern(target['path_template']).match(path):
            reasons.append('target-path-mismatch')
            continue
        ok, why, detail = _verified_prefix(events, [op], path,
                                           int(oracle.get('prefix_min_rounds', 0)))
        if not ok:
            reasons.append(why)
        else:
            prefixes.append(detail)
        field = target['fields'][0]['name']
        change = next((e for e in controls if e.get('model_path') == path and
                       e.get('method') == target['method']), None)
        verified = next((e for e in controls if e.get('model_path') == path and
                         str(e.get('operation_id', '')).endswith('-observe-' + str(i))), None)
        reset = next((e for e in resets if e.get('model_path') == path and
                      e.get('method') == target['method']), None)
        restored = next((e for e in resets if e.get('model_path') == path and
                         str(e.get('operation_id', '')).endswith('-observe-' + str(i))), None)
        final = next((e for e in observations if e.get('model_path') == path and
                      str(e.get('operation_id', '')).endswith('-observe-' + str(i))), None)
        if (not change or change.get('status') not in target['success_statuses'] or
                not verified or verified.get('status') not in target['observation']['success_statuses'] or
                not reset or reset.get('status') not in target['success_statuses'] or
                not restored or restored.get('status') not in target['observation']['success_statuses']):
            reasons.append('independent-serial-control-failed')
            continue
        value = _request(change).get(field)
        if field not in _request(change) or not isinstance(_response(verified), dict) or not _same_value(
                _response(verified).get(field), value):
            reasons.append('independent-serial-control-state-mismatch')
        if field not in _request(reset) or not isinstance(_response(restored), dict) or not _same_value(
                _response(restored).get(field), _request(reset)[field]):
            reasons.append('independent-reset-state-mismatch')
        if final is None or final.get('status') not in target['observation']['success_statuses']:
            reasons.append('independent-final-read-failed')
        elif _intervening_write(events, [op], final, path):
            reasons.append('intervening-write-before-observation')
        elif not isinstance(_response(final), dict) or not _same_value(
                _response(final).get(field), _request(op).get(field)):
            reasons.append('independent-final-value-mismatch')
        if op.get('status') not in target['success_statuses']:
            reasons.append('independent-concurrent-write-failed')
    valid = len(ordered) == len(targets) == 2 and len(prefixes) == 2
    # A mismatch is a violation only when all controls and reads are valid;
    # missing prerequisites cannot be promoted into application bugs.
    prerequisites = {'target-path-mismatch', 'independent-serial-control-failed',
                     'independent-serial-control-state-mismatch',
                     'independent-reset-state-mismatch', 'independent-final-read-failed',
                     'intervening-write-before-observation'}
    result = ('INCONCLUSIVE' if not valid or any(r in prerequisites for r in reasons) else
              'VIOLATED' if reasons else 'PASS')
    return {'oracle_id': oracle['oracle_id'], 'kind': oracle['kind'], 'epoch_id': epoch_id,
            'trigger_events': [e['_index'] for e in ordered], 'result': result,
            'prefix_evidence': {'rounds': min((p['rounds'] for p in prefixes), default=0),
                                'last_verified_utc': max((p['last_verified_utc'] for p in prefixes), default=None),
                                'resources': prefixes},
            **({'reason': ','.join(sorted(set(reasons)))} if reasons else {})}


def _concurrency_witnesses(events: List[Dict[str, Any]], manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        epoch = event.get("epoch_id")
        if isinstance(epoch, str):
            groups.setdefault(epoch, []).append(event)
    out = []
    for epoch_id, group in sorted(groups.items()):
        operations = [e for e in group if str(e.get("method", "")).upper() in {"PUT", "PATCH", "DELETE"}
                      and not str(e.get("operation_id", "")).endswith("-observe")]
        observations = [e for e in group if str(e.get("method", "")).upper() == "GET"
                        and str(e.get("operation_id", "")).endswith("-observe")]
        if len(operations) < 2:
            continue
        if not _overlap(operations):
            # Sequential controls are evidence for the campaign model but are
            # not concurrent histories. Their HTTP contract witnesses remain
            # evaluated by the contract layer.
            continue
        direct = None
        if epoch_id.startswith('generated-epoch-'):
            try:
                executable = [o for o in manifest.get('concurrency_oracles', [])
                              if o.get('runtime', {}).get('ready') and
                              o.get('kind') != 'update-delete-linearizable']
                direct = executable[int(epoch_id.split('-')[-1])]
            except (IndexError, ValueError):
                pass
        if direct and direct.get('kind') == 'cross-entity-independent-writes':
            out.append(_independent_resource_witness(events, groups, epoch_id, operations, direct))
            continue
        path = str(operations[0].get("model_path", ""))
        if any(str(e.get("model_path", "")) != path for e in operations):
            continue
        methods = [str(e.get("method", "")).upper() for e in operations]
        bodies = [_request(e) for e in operations]
        keys = [set(body) for body in bodies]
        varying = _varying_keys(bodies)
        candidates = []
        for oracle in manifest.get("concurrency_oracles", []):
            if not _pattern(oracle["path_template"]).match(path):
                continue
            if "width" in oracle and oracle["width"] != len(operations):
                continue
            if "width_range" in oracle and not (oracle["width_range"][0] <= len(operations) <= oracle["width_range"][1]):
                continue
            if oracle["kind"] == "empirical-update-delete":
                continue  # Evaluated against three distinct created resources below.
            if oracle["kind"] == "update-delete-linearizable":
                if sorted(methods) == sorted(oracle["methods"]): candidates.append(oracle)
            elif any(method != oracle["method"] for method in methods):
                continue
            elif oracle["kind"] == "disjoint-writes-commute-domain":
                eligible = {f["name"] for f in oracle["eligible_fields"]}
                actual = varying
                if (oracle["width_range"][0] <= len(operations) <= oracle["width_range"][1]
                        and len(actual) == len(operations)
                        and actual <= eligible):
                    candidates.append(oracle)
            elif oracle["kind"] == "disjoint-writes-commute":
                wanted = {f["name"] for f in oracle["fields"]}
                if varying == wanted:
                    candidates.append(oracle)
            elif oracle['kind'] in ('noop-versus-change', 'disjoint-put-serial-outcomes'):
                if oracle is direct and varying == {field['name'] for field in oracle['fields']}:
                    candidates.append(oracle)
            elif oracle["kind"] == "same-field-one-successful-value-visible-domain":
                eligible = {f["name"] for f in oracle["eligible_fields"]}
                actual = varying
                if len(actual) == 1 and actual <= eligible:
                    candidates.append(oracle)
            elif oracle["kind"] == "same-field-one-successful-value-visible":
                wanted = oracle["fields"][0]["name"]
                if varying == {wanted}: candidates.append(oracle)
        if not candidates:
            continue
        # Prefer the oracle for the exact fields. It can demand controls
        # (including both serial orders) absent from the family template.
        oracle = next((candidate for candidate in candidates if candidate is direct and
                       candidate['kind'] in ('noop-versus-change', 'disjoint-put-serial-outcomes')),
                      None) or next((candidate for candidate in candidates
                       if not candidate["kind"].endswith("-domain")), candidates[0])
        observation = observations[-1] if observations else None
        reason = None
        statuses = [e.get("status") for e in operations]
        observed = _response(observation) if observation else {}
        control_id = epoch_id.replace("generated-epoch-", "generated-control-", 1)
        control_group = groups.get(control_id, [])
        control_operations = [e for e in control_group
                              if str(e.get("method", "")).upper() in {"PUT", "PATCH", "DELETE"}
                              and not str(e.get("operation_id", "")).endswith("-observe")]
        control_observations = [e for e in control_group
                                if str(e.get("method", "")).upper() == "GET"
                                and str(e.get("operation_id", "")).endswith("-observe")]
        reverse_group = groups.get(epoch_id.replace(
            "generated-epoch-", "generated-reverse-control-", 1), [])
        reverse_operations = [e for e in reverse_group
                              if str(e.get("method", "")).upper() in {"PUT", "PATCH", "DELETE"}
                              and not str(e.get("operation_id", "")).endswith("-observe")]
        reverse_observations = [e for e in reverse_group
                              if str(e.get("method", "")).upper() == "GET"
                                and str(e.get("operation_id", "")).endswith("-observe")]
        reset_group = groups.get(epoch_id.replace('generated-epoch-', 'generated-reset-', 1), [])
        reverse_reset_group = groups.get(epoch_id.replace(
            'generated-epoch-', 'generated-reset-reverse-', 1), [])
        prefix_ok, prefix_reason, prefix_evidence = True, "", {}
        if oracle.get("prefix_min_rounds"):
            prefix_ok, prefix_reason, prefix_evidence = _verified_prefix(
                events, operations, path, int(oracle["prefix_min_rounds"]))
        if observation is None:
            result, reason = "INCONCLUSIVE", "post-join-observation-missing"
        elif _intervening_write(events, operations, observation, path):
            result, reason = "INCONCLUSIVE", "intervening-write-before-observation"
        elif not prefix_ok:
            result, reason = "INCONCLUSIVE", prefix_reason
        elif (len(control_operations) < 2
              or any(e.get("status") not in oracle.get("success_statuses", [])
                     for e in control_operations)
              or not control_observations
              or control_observations[-1].get("status") not in oracle["observation"]["success_statuses"]):
            result, reason = "INCONCLUSIVE", "sequential-control-failed"
        elif oracle.get("reverse_sequential_control") and (
                len(reverse_operations) != len(operations)
                or any(e.get("status") not in oracle.get("success_statuses", [])
                       for e in reverse_operations)
                or not reverse_observations
                or reverse_observations[-1].get("status") not in oracle["observation"]["success_statuses"]):
            result, reason = "INCONCLUSIVE", "reverse-sequential-control-failed"
        elif oracle['kind'] == 'noop-versus-change' and not any(
                e.get('status') in oracle['observation']['success_statuses'] and
                isinstance(_response(e), dict) and
                _same_value(_response(e).get(oracle['fields'][0]['name']),
                            _request(control_operations[0]).get(oracle['fields'][0]['name']))
                for e in control_observations if str(e.get('operation_id', '')).endswith('-noop-observe')):
            result, reason = 'INCONCLUSIVE', 'noop-serial-state-not-observed'
        elif oracle['kind'] in ('noop-versus-change', 'disjoint-put-serial-outcomes') and (
                not _verified_reset_state(events, reset_group,
                                          {field['name'] for field in oracle['fields']}, operations,
                                          require_quiet_until_epoch=oracle['kind'] == 'noop-versus-change',
                                          success_statuses=oracle['success_statuses']) or
                (oracle['kind'] == 'disjoint-put-serial-outcomes' and not _verified_reset_state(
                    events, reverse_reset_group,
                    {field['name'] for field in oracle['fields']}, operations,
                    require_quiet_until_epoch=True,
                    success_statuses=oracle['success_statuses']))):
            result, reason = 'INCONCLUSIVE', 'pre-epoch-reset-state-not-verified'
        else:
            if oracle['kind'] == 'disjoint-put-serial-outcomes':
                names = {field['name'] for field in oracle['fields']}
                def matching_last(ops, reads):
                    state = _response(reads[-1]) if reads else None
                    last = _request(ops[-1]) if ops else None
                    return (isinstance(state, dict) and isinstance(last, dict) and
                            all(name in last and name in state and
                                _same_value(state[name], last[name]) for name in names))
                control_state_valid = (matching_last(control_operations, control_observations) and
                                       matching_last(reverse_operations, reverse_observations))
                control_state_reason = 'serial-put-outcome-not-observed'
            else:
                control_state_valid, control_state_reason = _sequential_control_state(
                    oracle, control_operations, control_observations[-1], varying)
            if control_state_valid and oracle.get("reverse_sequential_control") and oracle['kind'] != 'disjoint-put-serial-outcomes':
                control_state_valid, control_state_reason = _sequential_control_state(
                    oracle, reverse_operations, reverse_observations[-1], varying)
                if not control_state_valid:
                    control_state_reason = "reverse-" + control_state_reason
            if not control_state_valid:
                result, reason = "INCONCLUSIVE", control_state_reason
            elif oracle['kind'] == 'disjoint-put-serial-outcomes':
                fields = {field['name'] for field in oracle['fields']}
                states = [_response(control_observations[-1]), _response(reverse_observations[-1])]
                if any(s not in oracle['success_statuses'] for s in statuses):
                    result, reason = 'INCONCLUSIVE', 'concurrent-put-rejected'
                elif observation.get('status') not in oracle['observation']['success_statuses']:
                    result, reason = 'INCONCLUSIVE', 'post-join-read-failed'
                elif any(all(_same_value(observed.get(f), state.get(f)) for f in fields) for state in states):
                    result, reason = 'PASS', None
                else:
                    result, reason = 'VIOLATED', 'final-put-state-not-in-either-serial-outcome'
            elif oracle['kind'] == 'noop-versus-change':
                field = oracle['fields'][0]['name']
                if any(s not in oracle['success_statuses'] for s in statuses):
                    result, reason = 'INCONCLUSIVE', 'concurrent-noop-or-change-rejected'
                elif observation.get('status') not in oracle['observation']['success_statuses']:
                    result, reason = 'INCONCLUSIVE', 'post-join-read-failed'
                elif any(_same_value(observed.get(field), b.get(field)) for b in bodies):
                    result, reason = 'PASS', None
                else:
                    result, reason = 'VIOLATED', 'noop-change-final-value-not-serializable'
            elif oracle["kind"] in {"disjoint-writes-commute", "disjoint-writes-commute-domain"}:
                expected = {k: v for body in bodies for k, v in body.items()}
                if any(s not in oracle["success_statuses"] for s in statuses):
                    result, reason = "VIOLATED", "legal-concurrent-write-failed"
                elif observation.get("status") not in oracle["observation"]["success_statuses"]:
                    result, reason = "VIOLATED", "post-join-read-failed"
                elif any(observed.get(k) != v for k, v in expected.items()):
                    result, reason = "VIOLATED", "successful-disjoint-update-lost"
                else:
                    result = "PASS"
            elif oracle["kind"] in {"same-field-one-successful-value-visible", "same-field-one-successful-value-visible-domain"}:
                field = (oracle.get("fields") or oracle.get("eligible_fields"))[0]["name"]
                if oracle["kind"].endswith("-domain"):
                    field = next(iter(varying))
                legal_values = [body[field] for body, status in zip(bodies, statuses)
                                if status in oracle["success_statuses"] and field in body]
                if not legal_values or observation.get("status") not in oracle["observation"]["success_statuses"]:
                    result, reason = "VIOLATED", "same-field-operation-or-observation-failed"
                elif not any(_same_value(observed.get(field), value) for value in legal_values):
                    result, reason = "VIOLATED", "same-field-final-value-not-linearizable"
                else:
                    result = "PASS"
            else:
                delete_status = next((e.get("status") for e in operations if e.get("method") == "DELETE"), None)
                if delete_status not in oracle["delete_success_statuses"] or observation.get("status") not in oracle["observation"]["absence_statuses"]:
                    result, reason = "VIOLATED", "update-delete-outcome-not-linearizable"
                else:
                    result = "PASS"
        out.append({"oracle_id": oracle["oracle_id"], "kind": oracle["kind"],
                    "epoch_id": epoch_id, "trigger_events": [e["_index"] for e in operations],
                    "observation_event": observation.get("_index") if observation else None,
                    "statuses": statuses, "result": result,
                    **({"prefix_evidence": prefix_evidence} if prefix_evidence else {}),
                    **({} if reason is None else {"reason": reason})})
    return out


def _empirical_update_delete_witnesses(events: List[Dict[str, Any]],
                                       manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compare a race to both serial orders on separate verified creations."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        if isinstance(event.get('epoch_id'), str):
            groups.setdefault(event['epoch_id'], []).append(event)
    witnesses = []
    executable = [o for o in manifest.get('concurrency_oracles', [])
                  if o.get('runtime', {}).get('ready') and o.get('kind') != 'update-delete-linearizable']
    for index, oracle in enumerate(executable):
        if oracle.get('kind') != 'empirical-update-delete':
            continue
        for epoch_id, group in groups.items():
            if epoch_id != f'generated-epoch-{index}':
                continue
            suffix = epoch_id[len('generated-epoch-'):]
            update_method = oracle['method']
            writes = [e for e in group if e.get('method') in (update_method, 'DELETE')]
            if (len(writes) != 2 or sorted(e['method'] for e in writes) != sorted(['DELETE', update_method])
                    or not _pattern(oracle['path_template']).match(str(writes[0].get('model_path', '')))
                    or writes[0].get('model_path') != writes[1].get('model_path')):
                continue
            path = writes[0]['model_path']
            result, reason = 'INCONCLUSIVE', 'empirical-controls-not-proven'
            server_error_candidate = None
            baseline = [groups.get(f'cross-baseline-{suffix}-{i}', []) for i in range(3)]
            controls = [groups.get(f'cross-control-{side}-{suffix}', []) for side in ('a', 'b')]
            end_read = next((e for e in group if e.get('method') == 'GET'
                             and str(e.get('operation_id', '')).endswith('-observe')), None)
            baseline_ok = all(len(g) == 1 and g[0].get('method') == 'GET' and
                              g[0].get('status') in oracle['observation']['success_statuses']
                              for g in baseline)
            baseline_paths = [g[0]['model_path'] for g in baseline if g]
            distinct = len(set(baseline_paths)) == 3 and path == baseline_paths[-1]
            # The controller emits these requests in sequence. Verify that
            # ordering in the proxy trace as well before treating the two
            # controls as evidence of a stable serial result.
            def ordered(group):
                try:
                    return all(_time(a['upstream_completed_utc']) <=
                               _time(b['upstream_started_utc'])
                               for a, b in zip(group, group[1:]))
                except (KeyError, TypeError, ValueError):
                    return False

            controls_ok = True
            absence_reads = []
            for ctrl, expected_path, order in zip(controls, baseline_paths[:2],
                                                  ((update_method, 'DELETE'), ('DELETE', update_method))):
                ctrl_writes = sorted((e for e in ctrl if e.get('method') in (update_method, 'DELETE')),
                                     key=lambda e: e.get('_index', -1))
                ctrl_reads = sorted((e for e in ctrl if e.get('method') == 'GET'),
                                    key=lambda e: e.get('_index', -1))
                if (len(ctrl_writes) != 2 or len(ctrl_reads) != 2 or
                        tuple(e['method'] for e in ctrl_writes) != order or
                        not ordered(sorted(ctrl, key=lambda e: e.get('_index', -1))) or
                        [e['method'] for e in sorted(ctrl, key=lambda e: e.get('_index', -1))] !=
                        [order[0], 'GET', order[1], 'GET'] or
                        any(e.get('model_path') != expected_path for e in ctrl_writes + ctrl_reads)):
                    controls_ok = False
                    break
                first_expected = (oracle['success_statuses'] if order[0] == update_method
                                  else oracle['delete_success_statuses'])
                if ctrl_writes[0].get('status') not in first_expected:
                    controls_ok = False
                    break
                if (order[1] == 'DELETE' and ctrl_writes[1].get('status') not in
                        oracle['delete_success_statuses']):
                    controls_ok = False
                    break
                if (order[1] == update_method and ctrl_writes[1].get('status') not in
                        oracle['success_statuses'] + [400, 404, 409, 410, 422]):
                    controls_ok = False
                    break
                if (ctrl_reads[-1].get('status') not in (400, 404, 410) or
                        (order[0] == update_method and
                         (ctrl_reads[0].get('status') not in oracle['observation']['success_statuses']
                          or any(_response(ctrl_reads[0]).get(k) != v for k, v in _request(ctrl_writes[0]).items()))) or
                        (order[0] == 'DELETE' and
                         (ctrl_reads[0].get('status') != ctrl_reads[-1].get('status') or
                          _response(ctrl_reads[0]) != _response(ctrl_reads[-1])))):
                    controls_ok = False
                    break
                absence_reads.append(ctrl_reads[-1])
            # Undocumented absence codes are accepted only when both isolated
            # delete controls independently reproduce the exact response.
            absence_proven = (len(absence_reads) == 2 and
                              absence_reads[0].get('status') == absence_reads[1].get('status') and
                              _response(absence_reads[0]) == _response(absence_reads[1]) and
                              (absence_reads[0].get('status') != 400 or
                               bool(_response(absence_reads[0]))))
            # A normal generated story may still mutate a control item after
            # its baseline read. Such histories cannot establish a serial
            # reference for the concurrent epoch.
            allowed_groups = {f'cross-control-a-{suffix}', f'cross-control-b-{suffix}', epoch_id}
            final_index = end_read.get('_index', -1) if end_read else -1
            external_interference = any(
                event.get('model_path') == base_event.get('model_path') and
                event.get('method') in ('POST', 'PUT', 'PATCH', 'DELETE') and
                base_event.get('_index', -1) < event.get('_index', -1) < final_index and
                event.get('epoch_id') not in allowed_groups
                for base_group in baseline for base_event in base_group for event in events)
            # Distinct successful baseline reads are necessary before making
            # any claim about deletion. The two controls establish the concrete
            # absence signature; it is not an invented OpenAPI obligation.
            if (baseline_ok and distinct and controls_ok and absence_proven and
                    not external_interference and
                    end_read and _overlap(writes) and
                    max(e.get('_index', -1) for g in baseline + controls for e in g) <
                    min(e.get('_index', -1) for e in writes)):
                deletion = next(e for e in writes if e['method'] == 'DELETE')
                update = next(e for e in writes if e['method'] == update_method)
                try:
                    late_read = (_time(end_read['upstream_started_utc']) >
                                 max(_time(e['upstream_completed_utc']) for e in writes))
                except (KeyError, TypeError, ValueError):
                    late_read = False
                if late_read and deletion.get('status') in oracle['delete_success_statuses']:
                    # A race-only server error is useful evidence, but does not
                    # establish a non-linearizable final state. Require both
                    # serial orders and the same verified absence signature.
                    update_status = update.get('status')
                    if (isinstance(update_status, int) and 500 <= update_status <= 599
                            and end_read.get('status') == absence_reads[0].get('status')
                            and _response(end_read) == _response(absence_reads[0])):
                        server_error_candidate = {
                            'classification': 'SERVER_ERROR_CANDIDATE',
                            'operation_id': oracle.get('operation_id'),
                            'status': update_status,
                            'event_index': update['_index'],
                            'basis': 'both-serial-orders-valid-and-overlapping-update-returned-5xx',
                        }
                    if (update.get('status') in oracle['success_statuses'] or
                            update.get('status') in (400, 404, 409, 410, 422)):
                        if (end_read.get('status') == absence_reads[0].get('status') and
                                _response(end_read) == _response(absence_reads[0])):
                            result, reason = 'PASS', None
                        elif end_read.get('status') in oracle['observation']['success_statuses']:
                            result, reason = 'VIOLATED', 'resource-reappeared-despite-both-serial-absence-controls'
            witnesses.append({'oracle_id': oracle['oracle_id'], 'epoch_id': epoch_id,
                              'kind': oracle['kind'], 'result': result,
                              'trigger_events': [e['_index'] for e in writes],
                              'observation_event': end_read.get('_index') if end_read else None,
                              **({'server_error_candidate': server_error_candidate}
                                 if server_error_candidate else {}),
                              **({'reason': reason} if reason else {})})
    return witnesses


def evaluate(events: List[Dict[str, Any]], manifest: Dict[str, Any]) -> Dict[str, Any]:
    for index, event in enumerate(events): event.setdefault("_index", index)
    contract_witnesses = _contract_witnesses(events, manifest)
    state_witnesses = _state_witnesses(events, manifest)
    concurrency_witnesses = (_concurrency_witnesses(events, manifest) +
                             _empirical_update_delete_witnesses(events, manifest))
    witnesses = contract_witnesses + state_witnesses + concurrency_witnesses
    server_error_candidates = [dict(oracle_id=w['oracle_id'], epoch_id=w['epoch_id'],
                                    **w['server_error_candidate'])
                               for w in concurrency_witnesses if w.get('server_error_candidate')]
    if not events:
        witnesses.append({"oracle_id": "run::trace", "kind": "run-evidence",
                          "result": "INCONCLUSIVE", "reason": "empty-trace"})
    elif not witnesses:
        witnesses.append({"oracle_id": "run::coverage", "kind": "run-evidence",
                          "result": "INCONCLUSIVE", "reason": "no-generated-oracle-was-exercised"})
    ready_concurrency = [o for o in manifest.get("concurrency_oracles", [])
                         if o.get("runtime", {}).get("ready")]
    if events and ready_concurrency and not concurrency_witnesses:
        witnesses.append({"oracle_id": "run::concurrency-coverage",
                          "kind": "run-evidence", "result": "INCONCLUSIVE",
                          "reason": "no-concurrent-epoch-was-exercised"})
    counts = Counter(item["result"] for item in witnesses)
    exercised = {item["oracle_id"] for item in witnesses}
    required_contract = {o["oracle_id"] for o in manifest["contract_oracles"]}
    semantic_violation = any(
        item["result"] == "VIOLATED"
        for item in state_witnesses + concurrency_witnesses
    )
    contract_violation = any(item["result"] == "VIOLATED" for item in contract_witnesses)
    if counts["INCONCLUSIVE"] and not (contract_witnesses or state_witnesses or concurrency_witnesses):
        status = "INCONCLUSIVE"
    elif semantic_violation:
        status = "SEMANTIC_ANOMALY"
    elif contract_violation:
        status = "CONTRACT_DEVIATION"
    elif counts["INCONCLUSIVE"]:
        status = "INCONCLUSIVE"
    else:
        status = "PASS"
    def result_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
        layer = Counter(item["result"] for item in items)
        return {key: layer[key] for key in ("PASS", "VIOLATED", "INCONCLUSIVE")}

    return {"schema_version": 1, "profile": "openapi-only-generated-verifiers",
            "source": manifest["source"], "run_status": status,
            "counts": {k: counts[k] for k in ("PASS", "VIOLATED", "INCONCLUSIVE")},
            "layer_counts": {
                "contract": result_counts(contract_witnesses),
                "state": result_counts(state_witnesses),
                "concurrency": result_counts(concurrency_witnesses),
            },
            "contract_oracles_exercised": len(exercised & required_contract),
            "contract_oracles_generated": len(required_contract),
            "concurrency_oracles_ready": len(ready_concurrency),
            "concurrency_oracles_generated_ready": len(ready_concurrency),
            "concurrency_oracles_exercised": len(concurrency_witnesses),
            "concurrency_epochs_evaluated": len(concurrency_witnesses),
            "concurrency_oracle_families_exercised": len({w["oracle_id"] for w in concurrency_witnesses}),
            "server_error_candidates": server_error_candidates,
            "witnesses": witnesses,
            "note": "Not-exercised operations are coverage facts, not automatically semantic failures."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
    result = evaluate(load_jsonl(Path(args.trace)), manifest)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"run_status": result["run_status"], "counts": result["counts"]}, sort_keys=True))
    print("GENERATED_VERIFIERS_" + result["run_status"])
    return 0 if result["run_status"] == "PASS" else (
        2 if result["run_status"] in {"SEMANTIC_ANOMALY", "CONTRACT_DEVIATION"} else 3)


if __name__ == "__main__":
    raise SystemExit(main())
