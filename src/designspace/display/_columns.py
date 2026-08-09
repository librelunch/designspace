"""Column and status vocabularies for `pretty`'s selection arguments (API.md,
"Human-Readable Rendering").

`normalize_names` is the one guard behind `columns`, `show`, and `hide`
alike: a bare string or a sequence of them, checked against whichever
vocabulary applies, raising `TypeError` on an unrecognized name rather than
silently ignoring it. Kept dependency-free of `ir`/`builder`/`expr` so
`_pretty.py` can validate arguments before it commits to which renderer it is
dispatching to.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Columns a rendered `Space` row may carry.
SPACE_COLUMNS = frozenset({"kind", "domain", "prior", "default", "when", "tags", "constraints"})

#: `str(space)`'s existing shape, unchanged by this module: every column
#: except `tags`, which no corpus fixture uses and which `render_space`
#: rendered nowhere before `pretty` existed.
DEFAULT_SPACE_COLUMNS = SPACE_COLUMNS - {"tags"}

#: Columns a rendered config row may carry. `value` and `status` have no
#: analogue on a `Space`, which declares a domain but assigns nothing.
CONFIG_COLUMNS = frozenset(
    {"kind", "domain", "value", "status", "prior", "default", "when", "tags", "constraints"}
)

#: A config row's default omits `kind`: a container's kind already reads
#: through its value slot (`struct`, `count 4`), and a leaf's domain already
#: implies its kind.
DEFAULT_CONFIG_COLUMNS = CONFIG_COLUMNS - {"kind"}

#: The four words `evaluate_partial` distinguishes, spelled for a reader:
#: `active_unset` becomes `unset`.
STATUSES = frozenset({"set", "unset", "inactive", "unknown"})


def normalize_names(
    value: str | Iterable[str] | None, vocabulary: frozenset[str], argname: str
) -> frozenset[str] | None:
    """`value` as a `frozenset`, checked against `vocabulary`.

    `None` passes through unchanged, so a caller can distinguish "not
    given" from "given, and resolves to nothing". A bare string is one
    name, not a sequence of its characters.
    """
    if value is None:
        return None
    names = (value,) if isinstance(value, str) else tuple(value)
    unknown = sorted({name for name in names if name not in vocabulary})
    if unknown:
        raise TypeError(f"{argname} names {', '.join(unknown)}, not in {sorted(vocabulary)}")
    return frozenset(names)


def resolve_columns(
    columns: str | Iterable[str] | None, vocabulary: frozenset[str], default: frozenset[str]
) -> frozenset[str]:
    """`columns`, defaulted and validated against `vocabulary`."""
    resolved = normalize_names(columns, vocabulary, "columns")
    return default if resolved is None else resolved


def resolve_show_hide(
    show: str | Iterable[str] | None, hide: str | Iterable[str] | None
) -> frozenset[str]:
    """The statuses to keep, from `show` (keep exactly these) or `hide`
    (keep everything else). Passing both raises, since each already states
    the other's complement."""
    if show is not None and hide is not None:
        raise TypeError("pretty() takes show or hide, not both")
    shown = normalize_names(show, STATUSES, "show")
    if shown is not None:
        return shown
    hidden = normalize_names(hide, STATUSES, "hide")
    if hidden is not None:
        return STATUSES - hidden
    return STATUSES
