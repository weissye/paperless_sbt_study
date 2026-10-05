"""Configurable authenticated proxy that preserves verifier-ready HTTP traces."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade"}


def authorization_value(scheme: str, token: str) -> str:
    """Build a runtime-configured Authorization value without SUT knowledge."""
    clean_scheme = str(scheme or "").strip()
    clean_token = str(token or "").strip()
    return f"{clean_scheme} {clean_token}".strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return raw.decode("utf-8", errors="replace")


def build_server(args: argparse.Namespace) -> ThreadingHTTPServer:
    target = urllib.parse.urlsplit(args.target)
    if target.scheme not in {"http", "https"} or not target.hostname:
        raise ValueError("--target must be an absolute HTTP(S) URL")
    target_port = target.port or (443 if target.scheme == "https" else 80)
    prefix = (target.path.rstrip("/") + "/" + args.api_prefix.strip("/")).rstrip("/")
    if prefix == "/":
        prefix = ""
    token = os.environ.get(args.bearer_token_env, "").strip() if args.bearer_token_env else ""
    if args.require_bearer_token and not token:
        raise ValueError(f"required bearer token environment variable is empty: {args.bearer_token_env}")
    trace_path = Path(args.trace)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    lock, sequence = threading.Lock(), {"value": 0}
    # Optional epoch lease: exclude *other* writes to the same concrete path
    # through observation. Provengo event blocking alone cannot guard HTTP
    # requests from already running stories.
    gate = threading.Condition()
    leases: dict[str, str] = {}
    inflight: dict[str, int] = {}
    mutating = {"POST", "PUT", "PATCH", "DELETE"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self): self.forward()
        def do_POST(self):
            if self.path in ("/__sbt/lease", "/__sbt/release", "/__sbt/assert-lease"):
                self.lease_command()
            else:
                self.forward()
        def do_PUT(self): self.forward()
        def do_PATCH(self): self.forward()
        def do_DELETE(self): self.forward()
        def do_HEAD(self): self.forward()
        def do_OPTIONS(self): self.forward()
        def log_message(self, *_args): return

        def lease_command(self):
            path, epoch = None, None
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
                data = json.loads(raw)
                path, epoch = data.get("path"), data.get("epoch_id")
                parsed = urllib.parse.urlsplit(path) if isinstance(path, str) else None
                if (not isinstance(epoch, str) or not epoch.startswith("generated-epoch-")
                        or not parsed or not path.startswith("/") or parsed.query or parsed.fragment
                        or ".." in parsed.path.split("/")):
                    raise ValueError("invalid lease resource or epoch")
                with gate:
                    if self.path == "/__sbt/assert-lease":
                        if leases.get(path) != epoch:
                            raise ValueError("resource lease is not owned by the epoch")
                    elif self.path == "/__sbt/lease":
                        # Refuse a duplicate owner: a lease must have one release.
                        if leases.get(path) == epoch:
                            raise ValueError("epoch already holds lease")
                        if not gate.wait_for(lambda: path not in leases and not inflight.get(path), args.timeout):
                            raise TimeoutError("resource lease timed out")
                        leases[path] = epoch
                    else:
                        if leases.get(path) != epoch:
                            raise ValueError("resource lease owner mismatch")
                        del leases[path]
                        gate.notify_all()
                status, payload = 200, b'{"ok":true}'
            except (ValueError, TimeoutError, TypeError, json.JSONDecodeError):
                status, payload = 409, b'{"ok":false}'
            if (self.headers.get("X-SBT-Research-Lifecycle") == "exclusive" and
                    isinstance(path, str) and isinstance(epoch, str)):
                event = {"timestamp_utc": _now(), "method": "SBT_LEASE" if self.path.endswith("/lease") else "SBT_RELEASE",
                         "model_path": path, "epoch_id": epoch, "status": status}
                with lock, trace_path.open("a", encoding="utf-8") as handle:
                    event["trace_sequence"] = sequence["value"]
                    sequence["value"] += 1
                    handle.write(json.dumps(event, sort_keys=True) + "\n")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def forward(self):
            received_utc, received_ns = _now(), time.perf_counter_ns()
            length = int(self.headers.get("Content-Length", "0") or 0)
            request_body = self.rfile.read(length) if length else b""
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_BY_HOP and k.lower() not in
                       {"host", "authorization", "x-provengo-invocation"}}
            if token:
                headers["Authorization"] = authorization_value(args.authorization_scheme, token)
            model_path = self.path if self.path.startswith("/") else "/" + self.path
            if self.command in mutating:
                with gate:
                    owner = self.headers.get("X-SBT-Research-Owner") or self.headers.get("X-Provengo-Epoch-Id")
                    if not gate.wait_for(lambda: model_path not in leases or leases[model_path] == owner,
                                         args.timeout):
                        self.send_error(503, "resource lease timed out")
                        return
                    inflight[model_path] = inflight.get(model_path, 0) + 1
            upstream_path = prefix + model_path
            cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            connection = cls(target.hostname, target_port, timeout=args.timeout)
            status, response_body = 502, b""
            response_headers = []
            transport_error = None
            upstream_started_utc, upstream_started_ns = _now(), time.perf_counter_ns()
            try:
                connection.request(self.command, upstream_path, body=request_body, headers=headers)
                response = connection.getresponse()
                status, response_body = response.status, response.read()
                response_headers = response.getheaders()
            except (OSError, http.client.HTTPException) as exc:
                # Upstream transport failures are proxy evidence, never SUT
                # response-contract violations. Always reply to the client.
                transport_error = type(exc).__name__
                status = 502
                response_body = b'{"proxy_error":"upstream-transport-failure"}'
                response_headers = [("Content-Type", "application/json")]
            finally:
                upstream_completed_ns, upstream_completed_utc = time.perf_counter_ns(), _now()
                connection.close()
                try:
                    self.send_response(status)
                    for key, value in response_headers:
                        if key.lower() not in HOP_BY_HOP and key.lower() != "content-length":
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(response_body)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(response_body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                try:
                    event = {
                    "timestamp_utc": upstream_completed_utc,
                    "request_received_utc": received_utc,
                    "upstream_started_utc": upstream_started_utc,
                    "upstream_completed_utc": upstream_completed_utc,
                    "proxy_queue_ns": upstream_started_ns - received_ns,
                    "upstream_duration_ns": upstream_completed_ns - upstream_started_ns,
                    "method": self.command, "model_path": model_path,
                    "sut_path": upstream_path, "request": _decode(request_body),
                    "request_content_type": self.headers.get("Content-Type"),
                    "status": status, "response": _decode(response_body),
                    "transport_error": transport_error,
                    "epoch_id": self.headers.get("X-Provengo-Epoch-Id"),
                    "operation_id": self.headers.get("X-Provengo-Operation-Id"),
                    "request_id": self.headers.get("X-Request-ID"),
                    "proxy_worker": threading.current_thread().name,
                }
                    for header, field in (("X-Provengo-Prefix-Phase", "prefix_phase"),
                                      ("X-Provengo-Prefix-Story", "prefix_story"),
                                      ("X-Provengo-Prefix-Round", "prefix_round"),
                                      ("X-Provengo-Prefix-Total", "prefix_total"),
                                      ("X-Provengo-Invocation", "invocation_id")):
                        value = self.headers.get(header)
                        if value is not None:
                            event[field] = value[:200]
                    with lock, trace_path.open("a", encoding="utf-8") as handle:
                        event["trace_sequence"] = sequence["value"]
                        sequence["value"] += 1
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
                finally:
                    if self.command in mutating:
                        with gate:
                            inflight[model_path] -= 1
                            if not inflight[model_path]:
                                del inflight[model_path]
                            gate.notify_all()

    server = ThreadingHTTPServer((args.listen_host, args.listen_port), Handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=3457)
    parser.add_argument("--target", required=True)
    parser.add_argument("--api-prefix", default="")
    parser.add_argument("--trace", required=True)
    parser.add_argument("--bearer-token-env", default="")
    parser.add_argument("--require-bearer-token", action="store_true")
    parser.add_argument("--authorization-scheme", default="Bearer")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    server = build_server(args)
    print(f"OPENAPI_SBT_TRACE_PROXY_READY http://{args.listen_host}:{args.listen_port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
