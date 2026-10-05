"""Normalize a fully $ref-resolved OpenAPI dict into the Document IR."""
from __future__ import annotations

from typing import Any, Dict, List

from .model import (
    Document, Operation, Parameter, RequestBody, RequestBodyVariant,
    ResponseSpec, Schema, SecurityScheme,
)

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _esc(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def normalize(resolved: Dict[str, Any], raw_unresolved: Dict[str, Any]) -> Document:
    openapi_version = resolved.get("openapi") or resolved.get("swagger", "")
    is_swagger2 = str(resolved.get("swagger", "")) == "2.0"
    info = resolved.get("info", {}) or {}
    title = info.get("title", "Untitled API")
    version = str(info.get("version", "0.0.0"))

    servers = []
    for s in resolved.get("servers", []) or []:
        url = s.get("url") if isinstance(s, dict) else None
        if url:
            servers.append(url)
    if is_swagger2 and not servers and resolved.get("host"):
        schemes = resolved.get("schemes", []) or ["http"]
        base_path = str(resolved.get("basePath", "") or "")
        servers.append(f"{schemes[0]}://{resolved['host']}{base_path}")

    doc = Document(title=title, version=version, openapi_version=str(openapi_version),
                    servers=servers, raw=raw_unresolved)

    # --- component schemas (kept for entity/key/dependency inference) ---
    schemas_raw = resolved.get("components", {}).get("schemas", {}) or {}
    schema_pointer_root = "#/components/schemas"
    if is_swagger2:
        schemas_raw = resolved.get("definitions", {}) or {}
        schema_pointer_root = "#/definitions"
    for name, schema_dict in schemas_raw.items():
        if not isinstance(schema_dict, dict):
            continue
        doc.component_schemas[name] = Schema(
            raw=schema_dict,
            source_pointer=f"{schema_pointer_root}/{_esc(name)}",
            name=name,
        )

    # --- security schemes ---
    sec_schemes = resolved.get("components", {}).get("securitySchemes", {}) or {}
    if is_swagger2:
        sec_schemes = resolved.get("securityDefinitions", {}) or {}
    for name, s in sec_schemes.items():
        if not isinstance(s, dict):
            continue
        doc.security_schemes[name] = SecurityScheme(
            name=name,
            type_=s.get("type", ""),
            scheme=s.get("scheme", ""),
            location=s.get("in", ""),
            param_name=s.get("name", ""),
        )

    global_security = resolved.get("security", []) or []
    global_consumes = resolved.get("consumes", []) or []
    global_produces = resolved.get("produces", []) or []

    # --- paths / operations ---
    paths = resolved.get("paths", {}) or {}
    for path_template, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        shared_params_raw = path_item.get("parameters", []) or []
        for method in HTTP_METHODS:
            op_dict = path_item.get(method)
            if not isinstance(op_dict, dict):
                continue
            pointer = f"#/paths/{_esc(path_template)}/{method}"
            op_id = op_dict.get("operationId")
            params: List[Parameter] = []
            body_params: List[Dict[str, Any]] = []
            form_params: List[Dict[str, Any]] = []
            seen_param_keys = set()
            for p in list(shared_params_raw) + list(op_dict.get("parameters", []) or []):
                if not isinstance(p, dict) or "name" not in p or "in" not in p:
                    continue
                key = (p["name"], p["in"])
                if key in seen_param_keys:
                    continue
                seen_param_keys.add(key)
                if is_swagger2 and p["in"] == "body":
                    body_params.append(p)
                    continue
                if is_swagger2 and p["in"] == "formData":
                    form_params.append(p)
                    continue
                parameter_schema = p.get("schema", {}) or {}
                if is_swagger2 and not parameter_schema:
                    parameter_schema = {
                        name: p[name] for name in (
                            "type", "format", "items", "enum", "default", "minimum",
                            "maximum", "minLength", "maxLength", "pattern",
                            "minItems", "maxItems", "uniqueItems",
                        ) if name in p
                    }
                params.append(Parameter(
                    name=p["name"],
                    location=p["in"],
                    required=bool(p.get("required", p["in"] == "path")),
                    schema=parameter_schema,
                    description=p.get("description", ""),
                    pointer=f"{pointer}/parameters",
                ))

            request_body = None
            rb = op_dict.get("requestBody")
            if isinstance(rb, dict):
                variants = []
                for media_type, media_obj in (rb.get("content", {}) or {}).items():
                    if not isinstance(media_obj, dict):
                        continue
                    variants.append(RequestBodyVariant(
                        media_type=media_type,
                        schema=media_obj.get("schema", {}) or {},
                        pointer=f"{pointer}/requestBody/content/{_esc(media_type)}",
                    ))
                request_body = RequestBody(required=bool(rb.get("required", False)), variants=variants,
                                           description=rb.get("description", "") or "")
            elif is_swagger2 and body_params:
                consumes = op_dict.get("consumes", []) or global_consumes or ["application/json"]
                body = body_params[0]
                request_body = RequestBody(
                    required=bool(body.get("required", False)),
                    variants=[RequestBodyVariant(
                        media_type=media_type,
                        schema=body.get("schema", {}) or {},
                        pointer=f"{pointer}/parameters/body",
                    ) for media_type in consumes],
                )
            elif is_swagger2 and form_params:
                consumes = (op_dict.get("consumes", []) or global_consumes
                            or ["application/x-www-form-urlencoded"])
                properties = {}
                required = []
                for form_param in form_params:
                    properties[form_param["name"]] = {
                        name: form_param[name] for name in (
                            "type", "format", "items", "enum", "default",
                        ) if name in form_param
                    }
                    if form_param.get("required"):
                        required.append(form_param["name"])
                schema = {"type": "object", "properties": properties}
                if required:
                    schema["required"] = required
                request_body = RequestBody(
                    required=bool(required),
                    variants=[RequestBodyVariant(
                        media_type=media_type,
                        schema=schema,
                        pointer=f"{pointer}/parameters/formData",
                    ) for media_type in consumes],
                )

            responses: List[ResponseSpec] = []
            for status, resp_obj in (op_dict.get("responses", {}) or {}).items():
                if not isinstance(resp_obj, dict):
                    continue
                media_types = {}
                for mt, mobj in (resp_obj.get("content", {}) or {}).items():
                    if isinstance(mobj, dict):
                        media_types[mt] = mobj.get("schema", {}) or {}
                if is_swagger2 and not media_types and isinstance(resp_obj.get("schema"), dict):
                    produces = op_dict.get("produces", []) or global_produces or ["application/json"]
                    media_types = {media_type: resp_obj["schema"] for media_type in produces}
                responses.append(ResponseSpec(
                    status=str(status),
                    media_types=media_types,
                    pointer=f"{pointer}/responses/{_esc(str(status))}",
                    is_default=(status == "default"),
                ))

            security = op_dict.get("security", global_security)

            doc.operations.append(Operation(
                operation_id=op_id,
                method=method.upper(),
                path=path_template,
                tags=op_dict.get("tags", []) or [],
                summary=op_dict.get("summary") or op_dict.get("description", "") or "",
                parameters=params,
                request_body=request_body,
                responses=responses,
                security=security,
                pointer=pointer,
                deprecated=bool(op_dict.get("deprecated", False)),
            ))

    return doc
