"""Value validation for `.symbolic()`/`.code()` (API.md, "Parameter Types"
> "Program").

Shared by `validate/_validate.py::_domain_error_reason` and
`resolve/_pipeline.py::_validate_default` — one reason-string vocabulary
(`"wrong_type"`/`"out_of_bounds"`), mirroring `CustomDomain`'s own
convention: a raising validator behaves like a malformed value
(`"wrong_type"`), a `False`-returning validator is a declared-rule
violation (`"out_of_bounds"`) — the value has already passed the
structural AST/shape check by the time a validator runs, so a raise here
is a genuine defensive catch, not the expected failure mode.
"""

from __future__ import annotations

from typing import Any

from designspace.ir import CodeDomain, SymbolicDomain
from designspace.program._ast import ast_error


def _run_validators(validators: Any, value: Any) -> str | None:
    if validators is None:
        return None
    for v in validators:
        try:
            ok = v(value)
        except Exception:
            return "wrong_type"
        if not ok:
            return "out_of_bounds"
    return None


def program_value_error(domain: SymbolicDomain | CodeDomain, value: Any) -> str | None:
    if isinstance(domain, SymbolicDomain):
        if not isinstance(value, dict) or "ast" not in value:
            return "wrong_type"
        if "source" in value and not isinstance(value["source"], str):
            return "wrong_type"
        reason = ast_error(domain, value["ast"])
        if reason is not None:
            return reason
        return _run_validators(domain.validators, value["ast"])
    if not isinstance(value, dict) or not isinstance(value.get("source"), str):
        return "wrong_type"
    return _run_validators(domain.validators, value["source"])
