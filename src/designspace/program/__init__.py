"""program: support types for `.symbolic()`/`.code()` (API.md, "Support
Types"; "Parameter Types" > "Program"; M12).

`ast_error`/`program_value_error` are internal — reused by
`validate/_validate.py` and `resolve/_pipeline.py`, never called directly
by users.
"""

from designspace.program._support import FloatLiteral, IntLiteral, Primitive, Signature

__all__ = ["FloatLiteral", "IntLiteral", "Primitive", "Signature"]
