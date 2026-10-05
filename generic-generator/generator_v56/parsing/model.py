"""Intermediate representation (IR) for a normalized OpenAPI document.

This IR is deliberately generic: nothing in this module or any consumer of
it may reference concrete resource/entity names. All names arrive at
runtime from the parsed document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Provenance:
    """Pointer to the exact OpenAPI location an inference was derived from,
    plus the name of the rule that produced it."""
    pointer: str        # JSON-Pointer-like path, e.g. "#/paths/~1books/get"
    rule: str            # name of the inference rule/function
    detail: str = ""     # optional free-text explanation

    def to_dict(self) -> Dict[str, Any]:
        return {"pointer": self.pointer, "rule": self.rule, "detail": self.detail}


@dataclass
class Schema:
    """A normalized JSON Schema fragment (already $ref-resolved)."""
    raw: Dict[str, Any] = field(default_factory=dict)
    source_pointer: str = ""
    name: Optional[str] = None  # component schema name if this came from #/components/schemas/*

    @property
    def type(self) -> Optional[str]:
        return self.raw.get("type")

    @property
    def properties(self) -> Dict[str, Any]:
        return self.raw.get("properties", {}) or {}

    @property
    def required(self) -> List[str]:
        return self.raw.get("required", []) or []


@dataclass
class Parameter:
    name: str
    location: str  # path | query | header | cookie
    required: bool
    schema: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    pointer: str = ""


@dataclass
class RequestBodyVariant:
    media_type: str
    schema: Dict[str, Any] = field(default_factory=dict)
    pointer: str = ""


@dataclass
class RequestBody:
    required: bool = False
    variants: List[RequestBodyVariant] = field(default_factory=list)
    description: str = ""


@dataclass
class ResponseSpec:
    status: str  # "200", "404", "default", ...
    media_types: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # media_type -> schema
    pointer: str = ""
    is_default: bool = False


@dataclass
class Operation:
    operation_id: Optional[str]
    method: str          # get|post|put|patch|delete|...
    path: str             # normalized template path, e.g. /books/{id}
    tags: List[str] = field(default_factory=list)
    summary: str = ""
    parameters: List[Parameter] = field(default_factory=list)
    request_body: Optional[RequestBody] = None
    responses: List[ResponseSpec] = field(default_factory=list)
    security: List[Dict[str, Any]] = field(default_factory=list)
    pointer: str = ""
    deprecated: bool = False

    @property
    def success_responses(self) -> List[ResponseSpec]:
        out = []
        for r in self.responses:
            if r.is_default:
                continue
            try:
                code = int(r.status)
            except ValueError:
                continue
            if 200 <= code < 300:
                out.append(r)
        return out

    @property
    def error_responses(self) -> List[ResponseSpec]:
        out = []
        for r in self.responses:
            if r.is_default:
                continue
            try:
                code = int(r.status)
            except ValueError:
                continue
            if code >= 300:
                out.append(r)
        return out

    @property
    def path_params(self) -> List[Parameter]:
        return [p for p in self.parameters if p.location == "path"]

    @property
    def query_params(self) -> List[Parameter]:
        return [p for p in self.parameters if p.location == "query"]

    @property
    def header_params(self) -> List[Parameter]:
        return [p for p in self.parameters if p.location == "header"]

    @property
    def cookie_params(self) -> List[Parameter]:
        return [p for p in self.parameters if p.location == "cookie"]

    @property
    def all_response_codes(self) -> List[str]:
        return [r.status for r in self.responses if not r.is_default]


@dataclass
class SecurityScheme:
    name: str
    type_: str
    scheme: str = ""
    location: str = ""   # for apiKey: header|query|cookie
    param_name: str = ""


@dataclass
class Document:
    title: str
    version: str
    openapi_version: str
    servers: List[str] = field(default_factory=list)
    operations: List[Operation] = field(default_factory=list)
    component_schemas: Dict[str, Schema] = field(default_factory=dict)
    security_schemes: Dict[str, SecurityScheme] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    unsupported: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
