"""Value validation for `.symbolic()`/`.code()` (API.md, "Parameter Types"
> "Program").

Shared by `_domain_error_reason` in `validate/_validate.py` and
`_validate_default` in `resolve/_pipeline.py`, under one reason-string
vocabulary of `"wrong_type"` and `"out_of_bounds"`. That mirrors
`CustomDomain`'s convention: a raising validator behaves like a malformed
value and gives `"wrong_type"`, while a `False`-returning validator is a
declared-rule violation and gives `"out_of_bounds"`. The value has already
passed the structural AST and shape check by the time a validator runs, so a
raise here is a defensive catch rather than the expected failure mode.
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
