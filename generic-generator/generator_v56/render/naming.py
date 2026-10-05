"""Helpers for turning OpenAPI names into safe, readable JS identifiers."""
from __future__ import annotations

import re

_JS_RESERVED = {
    "break", "case", "catch", "class", "const", "continue", "debugger", "default",
    "delete", "do", "else", "export", "extends", "finally", "for", "function", "if",
    "import", "in", "instanceof", "new", "return", "super", "switch", "this", "throw",
    "try", "typeof", "var", "void", "while", "with", "let", "static", "yield", "await",
}


def to_camel(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    parts = [p for p in parts if p]
    if not parts:
        return "value"
    out = parts[0][:1].lower() + parts[0][1:]
    for p in parts[1:]:
        out += p[:1].upper() + p[1:]
    return out


def to_pascal(name: str) -> str:
    c = to_camel(name)
    return c[:1].upper() + c[1:]


def safe_identifier(name: str) -> str:
    ident = to_camel(name)
    if not ident or not re.match(r"^[A-Za-z_$]", ident):
        ident = "_" + ident
    if ident in _JS_RESERVED:
        ident = ident + "_"
    return ident


def js_string(s: str) -> str:
    escaped = (str(s).replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return '"' + escaped + '"'

def identifier_suffix(name: str) -> str:
    return to_pascal(name)
