"""Post-discovery confirmation of an undocumented no-op mutation response.

This tool is intentionally separate from generation.  It consumes an existing
generated manifest plus an explicitly selected discovery candidate and records
independent HTTP evidence.  It never feeds facts back into the generator.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_body(raw: bytes) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def request(base_url: str, method: str, path: str, token: str,
            body: Any = None, content_type: str | None = None) -> Dict[str, Any]:
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = content_type or "application/json"
    started_utc = utc_now()
    started_ns = time.perf_counter_ns()
    status = None
    response_headers: Dict[str, str] = {}
    response_body = None
    error = None
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            response_body = load_json_body(response.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        response_body = load_json_body(exc.read())
    except Exception as exc:  # infrastructure evidence, not a SUT verdict
        error = f"{type(exc).__name__}: {exc}"
    ended_ns = time.perf_counter_ns()
    return {
        "started_utc": started_utc,
        "ended_utc": utc_now(),
        "duration_ns": ended_ns - started_ns,
        "method": method,
        "path": path,
        "request_content_type": content_type if body is not None else None,
        "request": body,
        "status": status,
        "response_headers": response_headers,
        "response": response_body,
        "error": error,
    }


def oracle(manifest: Dict[str, Any], operation_id: str) -> Dict[str, Any]:
    matches = [row for row in manifest.get("contract_oracles", [])
               if row.get("operation_id") == operation_id]
    if len(matches) != 1:
        raise ValueError(f"expected one contract oracle for {operation_id!r}, found {len(matches)}")
    return matches[0]


def path_for(template: str, identifier: Any) -> str:
    import re
    return re.sub(r"\{[^{}]+\}", str(identifier), template)


def distinct_value(current: Any) -> Any:
    if isinstance(current, bool):
        return not current
    if isinstance(current, int) and not isinstance(current, bool):
        return current + 1
    if isinstance(current, float):
        return current + 1.0
    if isinstance(current, str):
        return current + "_sbt_changed"
    raise ValueError(f"unsupported scalar candidate value: {type(current).__name__}")


def classify_trial(trial: Dict[str, Any], documented_statuses: Iterable[int],
                   field: str) -> Tuple[str, str]:
    documented = set(documented_statuses)
    same_before = trial["same_before"]
    change = trial["change"]
    same_after = trial["same_after"]
    after_same_before = trial["after_same_before"]
    after_change = trial["after_change"]
    after_same_after = trial["after_same_after"]
    if any(step.get("error") for step in
           (same_before, after_same_before, change, after_change, same_after, after_same_after)):
        return "INCONCLUSIVE", "transport-error"
    observed_same_before = after_same_before.get("response")
    observed_same_after = after_same_after.get("response")
    if (not isinstance(observed_same_before, dict) or
            observed_same_before.get(field) != trial.get("baseline_value")):
        return "STATE_VIOLATION", "first-noop-mutation-changed-observed-state"
    if change.get("status") not in documented:
        return "INCONCLUSIVE", "state-changing-control-did-not-return-documented-success"
    observed = after_change.get("response")
    if not isinstance(observed, dict) or observed.get(field) != trial.get("changed_value"):
        return "INCONCLUSIVE", "state-changing-control-was-not-observed"
    if (not isinstance(observed_same_after, dict) or
            observed_same_after.get(field) != trial.get("changed_value")):
        return "STATE_VIOLATION", "second-noop-mutation-changed-observed-state"
    unexpected = [same_before.get("status") not in documented,
                  same_after.get("status") not in documented]
    if all(unexpected) and same_before.get("status") == same_after.get("status"):
        return "CONFIRMED", "repeatable-undocumented-noop-status-with-successful-changing-control"
    if any(unexpected):
        return "PARTIAL", "undocumented-noop-status-not-repeatable"
    return "NOT_REPRODUCED", "noop-returned-documented-status"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="API base including prefix, e.g. http://host/api/v2")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--create-operation", required=True)
    parser.add_argument("--read-operation", required=True)
    parser.add_argument("--mutation-operation", required=True)
    parser.add_argument("--delete-operation", required=True)
    create_body_source = parser.add_mutually_exclusive_group(required=True)
    create_body_source.add_argument("--create-body-json")
    create_body_source.add_argument("--create-body-file")
    parser.add_argument("--id-response-field", default="id")
    parser.add_argument("--field", required=True)
    parser.add_argument("--token-env", default="VIKUNJA_API_TOKEN")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(f"token environment variable {args.token_env!r} is empty")
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
    create_o = oracle(manifest, args.create_operation)
    read_o = oracle(manifest, args.read_operation)
    mutation_o = oracle(manifest, args.mutation_operation)
    delete_o = oracle(manifest, args.delete_operation)
    if args.create_body_file:
        create_body = json.loads(Path(args.create_body_file).read_text(encoding="utf-8-sig"))
    else:
        create_body = json.loads(args.create_body_json)
    documented = mutation_o.get("success_statuses", [])
    media_type = mutation_o.get("request_contract", {}).get("media_type") or "application/json"
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    trace_path = output / "confirmation-http-trace.jsonl"
    trials = []
    sequence = 0

    def emit(record: Dict[str, Any], trial_index: int, phase: str) -> Dict[str, Any]:
        nonlocal sequence
        row = {"trace_sequence": sequence, "trial": trial_index, "phase": phase, **record}
        sequence += 1
        with trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    for trial_index in range(1, args.trials + 1):
        trial: Dict[str, Any] = {"trial": trial_index}
        resource_id = None
        try:
            body = dict(create_body)
            for key, value in list(body.items()):
                if isinstance(value, str) and "{trial}" in value:
                    body[key] = value.replace("{trial}", str(trial_index))
            created = emit(request(args.base_url, create_o["method"], create_o["path_template"],
                                   token, body, "application/json"), trial_index, "create")
            trial["create"] = created
            if created.get("status") not in set(create_o.get("success_statuses", [])):
                trial.update(result="INCONCLUSIVE", reason="create-did-not-succeed")
                trials.append(trial)
                continue
            if not isinstance(created.get("response"), dict):
                trial.update(result="INCONCLUSIVE", reason="create-response-not-json-object")
                trials.append(trial)
                continue
            resource_id = created["response"].get(args.id_response_field)
            item_path = path_for(read_o["path_template"], resource_id)
            before = emit(request(args.base_url, read_o["method"], item_path, token),
                          trial_index, "before")
            trial["before"] = before
            if not isinstance(before.get("response"), dict) or args.field not in before["response"]:
                trial.update(result="INCONCLUSIVE", reason="baseline-field-not-observed")
                trials.append(trial)
                continue
            current = before["response"][args.field]
            changed = distinct_value(current)
            trial["baseline_value"] = current
            trial["changed_value"] = changed
            mutation_path = path_for(mutation_o["path_template"], resource_id)
            trial["same_before"] = emit(
                request(args.base_url, mutation_o["method"], mutation_path, token,
                        {args.field: current}, media_type), trial_index, "same-before")
            trial["after_same_before"] = emit(
                request(args.base_url, read_o["method"], item_path, token),
                trial_index, "after-same-before")
            trial["change"] = emit(
                request(args.base_url, mutation_o["method"], mutation_path, token,
                        {args.field: changed}, media_type), trial_index, "change")
            trial["after_change"] = emit(
                request(args.base_url, read_o["method"], item_path, token),
                trial_index, "after-change")
            trial["same_after"] = emit(
                request(args.base_url, mutation_o["method"], mutation_path, token,
                        {args.field: changed}, media_type), trial_index, "same-after")
            trial["after_same_after"] = emit(
                request(args.base_url, read_o["method"], item_path, token),
                trial_index, "after-same-after")
            result, reason = classify_trial(trial, documented, args.field)
            trial.update(result=result, reason=reason)
            trials.append(trial)
        except Exception as exc:
            trial.update(result="INCONCLUSIVE", reason=f"harness-error:{type(exc).__name__}:{exc}")
            trials.append(trial)
        finally:
            if resource_id is not None:
                emit(request(args.base_url, delete_o["method"],
                             path_for(delete_o["path_template"], resource_id), token),
                     trial_index, "cleanup")

    counts = {key: sum(t.get("result") == key for t in trials)
              for key in ("CONFIRMED", "STATE_VIOLATION", "PARTIAL",
                          "NOT_REPRODUCED", "INCONCLUSIVE")}
    if counts["STATE_VIOLATION"]:
        status = "STATE_VIOLATION"
    elif counts["CONFIRMED"] == args.trials and args.trials > 0:
        status = "CONFIRMED"
    elif counts["CONFIRMED"] or counts["PARTIAL"]:
        status = "PARTIAL"
    elif counts["NOT_REPRODUCED"]:
        status = "NOT_REPRODUCED"
    else:
        status = "INCONCLUSIVE"
    summary = {
        "schema_version": 1,
        "analysis_role": "post-discovery-confirmation-not-generator-input",
        "candidate": "undocumented-status-for-valid-noop-mutation",
        "source_openapi": manifest.get("source"),
        "mutation_operation_id": args.mutation_operation,
        "field": args.field,
        "documented_success_statuses": documented,
        "trial_count": args.trials,
        "counts": counts,
        "confirmation_status": status,
        "token_recorded": False,
        "trials": trials,
    }
    (output / "confirmation-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"confirmation_status": status, "counts": counts}, sort_keys=True))
    print("VIKUNJA_NOOP_PATCH_CANDIDATE_" + status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
