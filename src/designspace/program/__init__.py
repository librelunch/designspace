"""program: support types for `.symbolic()` and `.code()`.

See API.md, "Support Types" and "Parameter Types" > "Program".

`ast_error` and `program_value_error` are internal, reused by
`validate/_validate.py` and `resolve/_pipeline.py` and never called by a
user.
"""

from designspace.program._support import FloatLiteral, IntLiteral, Primitive, Signature

__all__ = ["FloatLiteral", "IntLiteral", "Primitive", "Signature"]
