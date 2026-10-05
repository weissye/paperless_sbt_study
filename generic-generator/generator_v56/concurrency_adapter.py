"""Application-neutral HTTP barrier executor for generated concurrency epochs."""
from __future__ import annotations

import argparse
import http.client
import json
import re
import socket
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _endpoint(sock: socket.socket | None, peer: bool) -> str | None:
    if sock is None:
        return None
    try:
        value = sock.getpeername() if peer else sock.getsockname()
        return ":".join(str(part) for part in value[:2])
    except OSError:
        return None


def documented_json_delete_paths(spec: Dict[str, Any]) -> tuple:
    """Find DELETE routes that explicitly document a JSON request body."""
    patterns = []
    for path, item in spec.get("paths", {}).items():
        operation = item.get("delete", {})
        body = operation.get("requestBody", {})
        content = body.get("content", {})
        if "application/json" not in content:
            continue
        template = re.escape(path)
        template = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", template)
        patterns.append(re.compile("^" + template + "$"))
    return tuple(patterns)


def validate_epoch(value: object, max_width: int = 8, json_delete_paths: tuple = ()) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("epoch body must be an object")
    epoch_id, operations = value.get("epoch_id"), value.get("operations")
    if not isinstance(epoch_id, str) or not epoch_id or len(epoch_id) > 200:
        raise ValueError("epoch_id must be a non-empty string of at most 200 characters")
    if not isinstance(operations, list) or not 2 <= len(operations) <= max_width:
        raise ValueError(f"operations must contain 2..{max_width} entries")
    seen = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("each operation must be an object")
        operation_id = operation.get("operation_id")
        if (not isinstance(operation_id, str) or not operation_id.startswith(epoch_id + "-")
                or operation_id in seen):
            raise ValueError("operation ids must be unique and scoped to the epoch")
        seen.add(operation_id)
        method = str(operation.get("method", "")).upper()
        if method not in {"PUT", "PATCH", "DELETE"}:
            raise ValueError("generated epochs permit PUT, PATCH, and DELETE only")
        path = operation.get("path")
        parsed = urllib.parse.urlsplit(path) if isinstance(path, str) else None
        if (not parsed or not path.startswith("/") or parsed.scheme or parsed.netloc
                or parsed.query or parsed.fragment or ".." in parsed.path.split("/")):
            raise ValueError("operation path must be a safe relative HTTP path without query or fragment")
        delay_ms = operation.get("delay_ms", 0)
        if not isinstance(delay_ms, (int, float)) or not 0 <= delay_ms <= 60000:
            raise ValueError("delay_ms must be in the range 0..60000")
        body = operation.get("body")
        if method == "DELETE" and body not in (None, {}):
            if not isinstance(body, dict) or not any(p.fullmatch(path) for p in json_delete_paths):
                raise ValueError("DELETE JSON body requires an OpenAPI-documented route")
        if method in {"PUT", "PATCH"} and not isinstance(body, dict):
            raise ValueError("PUT/PATCH body must be a JSON object")
        headers = operation.get("headers", {})
        if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                for k, v in headers.items()):
            raise ValueError("headers must be a string-to-string object")
        if method == "DELETE" and body not in (None, {}):
            if any(k.lower() == "content-type" and v.split(";", 1)[0].strip().lower() != "application/json"
                   for k, v in headers.items()):
                raise ValueError("DELETE JSON body requires Content-Type application/json")
    observation = value.get("post_join_observation")
    observations = value.get("post_join_observations")
    if observation is not None and observations is not None:
        raise ValueError("choose one post-join observation mode")
    if observation is not None:
        if (not isinstance(observation, dict) or observation.get("method") != "GET"
                or not isinstance(observation.get("path"), str)
                or any(op["path"] != observation["path"] for op in operations)):
            raise ValueError("post-join GET must use the same concrete path as every epoch write")
    if observations is not None:
        paths = {op['path'] for op in operations}
        if (not isinstance(observations, list) or len(observations) != len(paths) or
                len(paths) != len(operations) or
                any(not isinstance(o, dict) or o.get('method') != 'GET' or
                    o.get('path') not in paths for o in observations) or
                {o['path'] for o in observations} != paths):
            raise ValueError('independent-resource epoch requires one GET for each distinct written path')
    preheld = value.get("preheld_resource_lease", False)
    if preheld and (preheld is not True or observation is None or observations is not None or
                    not epoch_id.startswith("generated-epoch-")):
        raise ValueError("preheld lease requires a same-resource post-join observation")
    return {"epoch_id": epoch_id, "operations": operations,
            "post_join_observation": observation, "post_join_observations": observations,
            "scenario": value.get("scenario"), "preheld_resource_lease": preheld}


def build_server(args: argparse.Namespace) -> ThreadingHTTPServer:
    upstream = urllib.parse.urlsplit(args.upstream)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise ValueError("--upstream must be an absolute HTTP(S) URL")
    upstream_port = upstream.port or (443 if upstream.scheme == "https" else 80)
    upstream_prefix = upstream.path.rstrip("/")
    source_spec = getattr(args, "openapi_path", None)
    json_delete_paths = documented_json_delete_paths(
        json.loads(Path(source_spec).read_text(encoding="utf-8"))) if source_spec else ()
    epoch_log = Path(args.epoch_log)
    epoch_log.parent.mkdir(parents=True, exist_ok=True)
    log_lock = threading.Lock()

    def proxy_request(method: str, path: str, payload: Dict[str, Any] | None = None,
                      headers: Dict[str, str] | None = None) -> tuple[int, Any]:
        cls = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
        conn = cls(upstream.hostname, upstream_port, timeout=args.timeout)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            conn.request(method, upstream_prefix + path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, _decode(response.read())
        finally:
            conn.close()

    def execute_with_observation(epoch: Dict[str, Any]) -> Dict[str, Any]:
        observation = epoch.get("post_join_observation")
        observations = epoch.get('post_join_observations')
        if observations:
            # Acquire leases in a stable order and release all acquired leases
            # even if a request fails. Existing one-resource protocol is intact.
            acquired = []
            try:
                for path in sorted(o['path'] for o in observations):
                    resource = {'path': path, 'epoch_id': epoch['epoch_id']}
                    status, _ = proxy_request('POST', '/__sbt/lease', resource,
                                              {'Content-Type': 'application/json'})
                    if status != 200:
                        raise RuntimeError('cannot obtain resource HTTP observation lease')
                    acquired.append(resource)
                result = execute_epoch(epoch)
                result['post_join_observations'] = []
                for index, item in enumerate(observations):
                    status, body = proxy_request('GET', item['path'], headers={
                        'X-Provengo-Epoch-Id': epoch['epoch_id'],
                        'X-Provengo-Operation-Id': epoch['epoch_id'] + '-observe-' + str(index)})
                    result['post_join_observations'].append({
                        'path': item['path'], 'status': status, 'response': body})
                return result
            finally:
                for resource in reversed(acquired):
                    status, _ = proxy_request('POST', '/__sbt/release', resource,
                                              {'Content-Type': 'application/json'})
                    if status != 200:
                        raise RuntimeError('cannot release resource HTTP observation lease')
        if not observation:
            return execute_epoch(epoch)
        resource = {"path": observation["path"], "epoch_id": epoch["epoch_id"]}
        if epoch.get("preheld_resource_lease"):
            status, _ = proxy_request("POST", "/__sbt/assert-lease", resource,
                                      {"Content-Type": "application/json"})
            if status != 200:
                raise RuntimeError("exclusive controls lease was not held for the epoch")
            result = execute_epoch(epoch)
            status, body = proxy_request("GET", observation["path"], headers={
                "X-Provengo-Epoch-Id": epoch["epoch_id"],
                "X-Provengo-Operation-Id": epoch["epoch_id"] + "-observe"})
            result["post_join_observation"] = {"status": status, "response": body}
            return result
        status, _ = proxy_request("POST", "/__sbt/lease", resource,
                                  {"Content-Type": "application/json"})
        if status != 200:
            raise RuntimeError("cannot obtain same-resource HTTP observation lease")
        try:
            result = execute_epoch(epoch)
            status, body = proxy_request("GET", observation["path"], headers={
                "X-Provengo-Epoch-Id": epoch["epoch_id"],
                "X-Provengo-Operation-Id": epoch["epoch_id"] + "-observe"})
            result["post_join_observation"] = {"status": status, "response": body}
            return result
        finally:
            status, _ = proxy_request("POST", "/__sbt/release", resource,
                                      {"Content-Type": "application/json"})
            if status != 200:
                raise RuntimeError("cannot release same-resource HTTP observation lease")

    def execute_epoch(epoch: Dict[str, Any]) -> Dict[str, Any]:
        operations = epoch["operations"]
        barrier = threading.Barrier(len(operations) + 1, timeout=args.timeout)
        release: Dict[str, Any] = {}

        def invoke(operation: Dict[str, Any]) -> Dict[str, Any]:
            connection_id, request_id = str(uuid.uuid4()), str(uuid.uuid4())
            cls = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
            connection = cls(upstream.hostname, upstream_port, timeout=args.timeout)
            connected_utc = None
            try:
                connection.connect()
                connected_utc = _now()
                local_endpoint = _endpoint(connection.sock, False)
                peer_endpoint = _endpoint(connection.sock, True)
                barrier.wait()
                delay_ms = float(operation.get("delay_ms", 0))
                if delay_ms:
                    time.sleep(delay_ms / 1000.0)
                started_ns, started_utc = time.perf_counter_ns(), _now()
                method, body = str(operation["method"]).upper(), operation.get("body")
                payload = None if method == "DELETE" and body in (None, {}) else json.dumps(body, separators=(",", ":")).encode()
                headers = {str(k): str(v) for k, v in operation.get("headers", {}).items()
                           if str(k).lower() not in {"authorization", "host", "content-length"}}
                if method == "DELETE" and payload is not None and not any(
                        key.lower() == "content-type" for key in headers):
                    headers["Content-Type"] = "application/json"
                headers["X-Provengo-Epoch-Id"] = epoch["epoch_id"]
                headers["X-Provengo-Operation-Id"] = operation["operation_id"]
                headers["X-Request-ID"] = request_id
                connection.request(method, upstream_prefix + operation["path"], body=payload, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                ended_ns = time.perf_counter_ns()
                return {
                    "operation_id": operation["operation_id"], "request_id": request_id,
                    "connection_id": connection_id, "local_endpoint": local_endpoint,
                    "peer_endpoint": peer_endpoint, "connected_utc": connected_utc,
                    "started_utc": started_utc, "ended_utc": _now(),
                    "invocation_offset_ns": started_ns - release["ns"],
                    "duration_ns": ended_ns - started_ns, "method": method,
                    "path": operation["path"], "request_body": body,
                    "delay_ms": delay_ms, "status": response.status,
                    "response": _decode(raw), "error": None,
                }
            except Exception as exc:
                return {"operation_id": operation.get("operation_id"), "request_id": request_id,
                        "connection_id": connection_id, "connected_utc": connected_utc,
                        "method": operation.get("method"), "path": operation.get("path"),
                        "status": None, "response": None,
                        "error": f"{type(exc).__name__}: {exc}"}
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(operations), thread_name_prefix="sbt-epoch") as pool:
            futures = [pool.submit(invoke, operation) for operation in operations]
            deadline = time.monotonic() + args.timeout
            while barrier.n_waiting < len(operations):
                if time.monotonic() >= deadline:
                    barrier.abort()
                    raise TimeoutError("workers did not reach the barrier")
                time.sleep(0.0001)
            release["utc"], release["ns"] = _now(), time.perf_counter_ns()
            barrier.wait()
            results = [future.result(timeout=args.timeout) for future in futures]
        if args.quiescence_ms:
            time.sleep(args.quiescence_ms / 1000.0)
        intervals = [(r.get("invocation_offset_ns"), r.get("invocation_offset_ns", 0) + r.get("duration_ns", 0))
                     for r in results if r.get("status") is not None]
        overlap = len(intervals) == len(results) and max(v[0] for v in intervals) < min(v[1] for v in intervals)
        starts = [r["invocation_offset_ns"] for r in results if r.get("invocation_offset_ns") is not None]
        record = {"schema_version": 1, "epoch_id": epoch["epoch_id"],
                  "scenario": epoch.get("scenario"), "width": len(results),
                  "release_utc": release["utc"], "all_workers_ready_before_release": True,
                  "release_skew_ns": max(starts) - min(starts) if starts else None,
                  "overlap_observed": overlap, "quiescence_ms": args.quiescence_ms,
                  "operations": results}
        with log_lock, epoch_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def send_json(self, status: int, value: object) -> None:
            raw = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.send_json(200, {"status": "ready", "component": "openapi-sbt-concurrency-adapter"}) \
                if self.path == "/health" else self.send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/epochs":
                self.send_json(404, {"error": "not found"})
                return
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                epoch = validate_epoch(json.loads(raw.decode()), args.max_width, json_delete_paths)
                self.send_json(200, execute_with_observation(epoch))
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except Exception as exc:
                self.send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=3459)
    parser.add_argument("--upstream", default="http://127.0.0.1:3457")
    parser.add_argument("--epoch-log", required=True)
    parser.add_argument("--max-width", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--quiescence-ms", type=int, default=100)
    parser.add_argument("--openapi-path", default=None,
                        help="Optional OpenAPI document authorizing JSON DELETE bodies per route")
    args = parser.parse_args(argv)
    server = build_server(args)
    print(f"OPENAPI_SBT_CONCURRENCY_ADAPTER_READY http://{args.listen_host}:{args.listen_port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
