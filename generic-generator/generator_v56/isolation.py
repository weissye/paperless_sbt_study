"""Input isolation guard.

The generator must only ever read: the selected OpenAPI file, files it
`$ref`-includes (local/internal refs), and explicit CLI/config paths supplied
by the user (e.g. an overrides JSON file). It must never read reference JS
files, SUT source, or any other example's data.

This module installs a thin wrapper around ``builtins.open`` (and
``io.open``) for the duration of a generation run. Every open call is
checked against an allow-list of resolved absolute paths / allowed
directories. Any attempt to open a path outside the allow-list raises
``IsolationViolation`` immediately, and every *permitted* open is appended to
an audit log that is written into the generation report.

This is intentionally conservative: it is a real runtime guard, not just a
promise in documentation. It is used by ``cli.py`` around the ``generate``
command, and asserted against directly by
``tests/integration/test_isolation.py``.
"""
from __future__ import annotations

import builtins
import io
import os
import sysconfig
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Set


class IsolationViolation(RuntimeError):
    """Raised when generation code attempts to open a file outside the allow-list."""


@dataclass
class AccessAudit:
    opened: List[str] = field(default_factory=list)
    denied: List[str] = field(default_factory=list)


class InputAllowList:
    """Resolves whether a path may be opened during a generation run."""

    def __init__(self, allowed_files: Optional[List[str]] = None,
                 allowed_dirs: Optional[List[str]] = None):
        self.allowed_files: Set[str] = {str(Path(p).resolve()) for p in (allowed_files or [])}
        self.allowed_dirs: List[str] = [str(Path(p).resolve()) for p in (allowed_dirs or [])]

    def add_file(self, path: str) -> None:
        self.allowed_files.add(str(Path(path).resolve()))

    def add_dir(self, path: str) -> None:
        self.allowed_dirs.append(str(Path(path).resolve()))

    def permits(self, path: str) -> bool:
        try:
            resolved = str(Path(path).resolve())
        except Exception:
            resolved = os.path.abspath(path)
        if resolved in self.allowed_files:
            return True
        for d in self.allowed_dirs:
            if resolved == d or resolved.startswith(d + os.sep):
                return True
        return False


_lock = threading.Lock()
_active: Optional["IsolationSession"] = None


class IsolationSession:
    """Context manager that enforces an :class:`InputAllowList` on file opens.

    Only applies to the *current process*: standard library imports and
    Python's own module loading are exempt (checked via a path prefix
    allow-list for the interpreter/site-packages), so normal library code
    keeps working while user-data reads are gated.
    """

    def __init__(self, allow_list: InputAllowList, extra_exempt_prefixes: Optional[List[str]] = None):
        self.allow_list = allow_list
        self.audit = AccessAudit()
        self._orig_open = None
        self._orig_io_open = None
        # Exempt interpreter/stdlib/site-packages/output dirs from the check:
        # isolation is about *inputs* (reference/SUT/other-example data), not
        # about python itself being able to import modules or write outputs.
        # Exempt only Python runtime/library locations.  Using every entry in
        # sys.path is unsafe because the project root is commonly present there;
        # that would exempt all project data, including forbidden reference/SUT
        # inputs, and make the isolation guard ineffective.
        runtime_paths = {
            p for key, p in sysconfig.get_paths().items()
            if key in {"stdlib", "platstdlib", "purelib", "platlib"} and p
        }
        self._exempt_prefixes = [
            str(Path(p).resolve())
            for p in list(runtime_paths) + list(extra_exempt_prefixes or [])
            if p
        ]

    def _is_exempt(self, resolved: str) -> bool:
        return any(
            resolved == p or resolved.startswith(p + os.sep)
            for p in self._exempt_prefixes if p
        )

    def _guarded_open(self, orig: Callable):
        def guarded(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                resolved = str(Path(os.fspath(file)).resolve())
                mode = args[0] if args else kwargs.get("mode", "r")
                is_write = any(c in str(mode) for c in ("w", "a", "x", "+"))
                if not is_write and not self._is_exempt(resolved):
                    if self.allow_list.permits(resolved):
                        self.audit.opened.append(resolved)
                    else:
                        self.audit.denied.append(resolved)
                        raise IsolationViolation(
                            f"Generation process attempted to open a file outside "
                            f"the input allow-list: {resolved}"
                        )
                elif not is_write:
                    self.audit.opened.append(resolved)
            return orig(file, *args, **kwargs)
        return guarded

    def __enter__(self):
        global _active
        with _lock:
            self._orig_open = builtins.open
            self._orig_io_open = io.open
            builtins.open = self._guarded_open(self._orig_open)
            io.open = self._guarded_open(self._orig_io_open)
            _active = self
        return self

    def __exit__(self, exc_type, exc, tb):
        global _active
        with _lock:
            builtins.open = self._orig_open
            io.open = self._orig_io_open
            _active = None
        return False


def current_session() -> Optional[IsolationSession]:
    return _active
