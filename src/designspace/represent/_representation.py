"""`Representation`: the whole-space `Space` to `Space` morphism.

See API.md, "The Representation Layer" and "IR".

`decode` and `encode` are stored callables rather than delegating methods.
There is no separate method of either name, so `rep.decode` and `rep.encode`
are the functions passed at construction, called directly as `rep.decode(g)`.
That is what makes the spec's own supplied-tier constructor call,
`Representation(source=..., target=..., decode=..., encode=None)`,
type-check verbatim. It also avoids the field-and-method name collision this
codebase handles elsewhere with a paired spelling, as in
`ParamExpr.meta_map` beside `.meta()` and `Space.meta_map` beside `.meta()`:
here there is no method to collide with, the field being the whole public
surface either name needs.

`__post_init__` derives `invertible` from whether `encode` was supplied.
When it was not, it replaces the stored `None` with `_not_invertible`, so
that `rep.encode(x)` raises with a real message rather than
`NoneType is not callable`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from designspace.builder._space import Seed, Space
from designspace.display._hooks import displayable
from designspace.ir import Constraint, RepresentationCheck, RepresentationCheckFailure

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)

Config = dict[str, Any]
"""A configuration: one point of a space, keyed by instance path.

Every config-shaped surface holds this: `sample_one()`'s return value,
what `validate()` and `config_hash()` accept, what `decode`/`encode` map
between. Values are in **phenotype** form (the JSON-safe form), not a
custom type's native form; inactive params are absent rather than null.
"""


def _approx_equal(a: Any, b: Any) -> bool:
    """Structural equality, with numeric tolerance for `float` leaves.

    API.md, "The Representation Layer" states the law as
    `decode(encode(x)) == x`. A log or logit chart's `from_unit` and
    `to_unit` compose through `exp` and `log`, which are not bit-exact
    inverses at IEEE-754 precision, so the law holds up to that unavoidable
    slack rather than under literal float equality. The tolerance convention
    is `_isclose`'s, in `charts/_grid.py`.
    """
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_approx_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_approx_equal(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def _not_invertible(_phenotype: Config) -> Config:
    raise TypeError(
        "this Representation is not invertible (no applied encoding supplied "
        "encode()); rep.encode() is unavailable, and rep.invertible says so"
    )


def _sorted_union(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(a) | set(b)))


@displayable("designspace.display._results.render_representation")
@dataclass(frozen=True)
class Representation:
    """A `Space → Space` morphism carrying a value-level `decode`/`encode`
    pair. Two tiers construct one: **derived**, from
    `Space.represent(*rules)`, and **supplied**, from this constructor
    called directly. A derived
    representation *is* a supplied one; both compose through `then` and
    are checked through `check()`.

    `source` is the phenotype and `target` the genotype, an ordinary `Space`,
    so a solver asks it the same questions it would ask any space. Never
    enters the IR, `to_json`, or the fingerprint preimage; `target`
    serializes as an ordinary `Space` in its own right.

    Attributes
    ----------
    source : Space
        The phenotype space, the one you declared.
    target : Space
        The genotype space, the one a solver works in. An ordinary
        `Space`, so all the usual introspection applies to it.
    decode : Callable[[Config], Config]
        Genotype configuration to phenotype configuration. Total: every
        configuration valid for `target` decodes to one valid for
        `source`.
    encoded : tuple[str, ...]
        Paths that an encoding actually re-expressed.
    excluded_by_prop : tuple[str, ...]
        Paths left alone because a `.repeat()` count or a `.prop()` reads
        them.
    opaque_conditions : tuple[str, ...]
        Conditions carried across as opaque callables rather than
        rewritten structurally.
    opaque_constraints : tuple[Constraint, ...]
        Constraints carried across the same way.
    dropped_defaults : tuple[str, ...]
        Phenotype defaults that `encode` could not carry over.
    dropped_anchors : tuple[str, ...]
        Anchor names likewise dropped. An anchor drops as a whole.
    encode : Callable[[Config], Config] | None
        Phenotype to genotype, when the morphism is invertible. Raises if
        it is not.
    measure_preserving : bool
        Whether every applied encoding declared that it preserves the
        declared measure. Never assumed: an encoding that says nothing
        counts as `False`.
    invertible : bool
        Whether `encode` is usable. Derived from whether one was supplied.
    """

    source: Space
    target: Space
    decode: Callable[[Config], Config]  # total: every target-valid config decodes
    encoded: tuple[str, ...] = ()
    excluded_by_prop: tuple[str, ...] = ()  # params a repeat() count or .prop() reads
    opaque_conditions: tuple[str, ...] = ()  # transported opaquely, not structurally
    opaque_constraints: tuple[Constraint, ...] = ()
    dropped_defaults: tuple[str, ...] = ()  # phenotype defaults no encode() could carry
    dropped_anchors: tuple[str, ...] = ()  # anchor keys likewise (an anchor drops whole)
    # phenotype -> genotype; raises unless invertible
    encode: Callable[[Config], Config] | None = None
    measure_preserving: bool = False  # true only if every encoding declares it
    invertible: bool = field(init=False, default=False)  # every applied encoding supplies encode()

    def __post_init__(self) -> None:
        if self.encode is None:
            object.__setattr__(self, "invertible", False)
            object.__setattr__(self, "encode", _not_invertible)
        else:
            object.__setattr__(self, "invertible", True)

    def then(self, other: Representation) -> Representation:
        """Compose `self` (source → target) with `other` (target → its own
        target), producing a single morphism from `self.source` all the
        way to `other.target`. Requires `other.source` to fingerprint-equal
        `self.target` (a `TypeError` otherwise, which is misuse rather than resolution).
        `decode` composes right-to-left (`self.decode(other.decode(g))`,
        `other` first, since it is closer to the composed target); `encode`
        the reverse (`other.encode(self.encode(x))`), and only when both
        sides are invertible.

        Parameters
        ----------
        other : Representation
            A morphism whose source is this one's target.

        Returns
        -------
        Representation
            The composite, from `self.source` to `other.target`.

        Raises
        ------
        TypeError
            If `other.source` does not fingerprint-equal `self.target`.

        Examples
        --------
        The identity of composition is a representation onto the same
        space, so composing with one changes nothing observable:

        >>> s = ds.space(ds.param("depth").integer(1, 8))
        >>> rep = s.represent()
        >>> identity = ds.Representation(
        ...     source=rep.target, target=rep.target, decode=lambda g: g
        ... )
        >>> composed = rep.then(identity)
        >>> composed.source.fingerprint() == s.fingerprint()
        True
        >>> composed.decode({"depth": 0.5}) == rep.decode({"depth": 0.5})
        True

        Composing morphisms that do not meet is refused:

        >>> other = ds.space(ds.param("width").integer(1, 8))
        >>> rep.then(other.represent())
        Traceback (most recent call last):
            ...
        TypeError: then(): other.source does not fingerprint-equal self.target ...
        """
        if other.source.fingerprint("full") != self.target.fingerprint("full"):
            raise TypeError(
                "then(): other.source does not fingerprint-equal self.target "
                "and so these two representations do not compose"
            )
        self_decode, other_decode = self.decode, other.decode

        def composed_decode(genotype: Config) -> Config:
            return self_decode(other_decode(genotype))

        composed_encode: Callable[[Config], Config] | None = None
        if self.invertible and other.invertible:
            # `invertible` is derived from `encode is not None` in
            # `__post_init__`, but mypy cannot see that correlation across
            # the two independent fields, so assert it explicitly.
            assert self.encode is not None and other.encode is not None
            self_encode, other_encode = self.encode, other.encode

            def composed_encode_fn(phenotype: Config) -> Config:
                return other_encode(self_encode(phenotype))

            composed_encode = composed_encode_fn

        return Representation(
            source=self.source,
            target=other.target,
            decode=composed_decode,
            encoded=_sorted_union(self.encoded, other.encoded),
            excluded_by_prop=_sorted_union(self.excluded_by_prop, other.excluded_by_prop),
            opaque_conditions=_sorted_union(self.opaque_conditions, other.opaque_conditions),
            opaque_constraints=self.opaque_constraints + other.opaque_constraints,
            dropped_defaults=_sorted_union(self.dropped_defaults, other.dropped_defaults),
            dropped_anchors=_sorted_union(self.dropped_anchors, other.dropped_anchors),
            encode=composed_encode,
            measure_preserving=self.measure_preserving and other.measure_preserving,
        )

    def check(self, n: int = 200, seed: Seed = None) -> RepresentationCheck:
        """Sample `n` draws of `target`, decode each, and assert the
        conformance laws a `Representation` owes regardless of tier: decode
        totality (`source.validate(decode(g)).param_errors == ()`),
        feasibility agreement (`target.is_feasible(g) ==
        source.is_feasible(decode(g))`), and, when `invertible`, the
        one-directional round-trip `decode(encode(x)) == x` for `x =
        decode(g)`. Never raises on a law violation: the suite as a tool,
        since a supplied morphism has no other way to be shown sound.
        Structural laws (path/arity)
        are guaranteed by construction for the derived tier and asserted
        directly in the conformance suite, since a supplied morphism has no such
        law to check, so `check()` does not re-derive them here.

        Failures dedupe by `(law, detail)`, accumulating a `count` rather
        than one row per draw.

        Parameters
        ----------
        n : int
            How many genotype draws to check.
        seed : int | numpy.random.Generator | None
            Seed or generator, for a reproducible check.

        Returns
        -------
        RepresentationCheck
            With `.ok` and the deduplicated `.failures`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ...     ds.param("depth").integer(1, 8),
        ... )
        >>> report = s.represent().check(n=50, seed=0)
        >>> report.ok, report.failures
        (True, ())
        """
        draws = self.target.sample_dicts(n, seed=seed)
        counts: dict[tuple[str, str], int] = {}

        def record(law: str, detail: str) -> None:
            key = (law, detail)
            counts[key] = counts.get(key, 0) + 1

        for genotype in draws:
            try:
                phenotype = self.decode(genotype)
            except Exception as exc:  # decode must be total; a raise is itself a violation
                record("decode_totality", f"decode() raised: {exc}")
                continue
            errs = self.source.validate(phenotype).param_errors
            if errs:
                record("decode_totality", f"{errs[0].param}: {errs[0].reason}")
                continue  # a phenotype that fails domain membership can't be fed onward safely
            target_feasible = self.target.is_feasible(genotype)
            source_feasible = self.source.is_feasible(phenotype)
            if target_feasible != source_feasible:
                record(
                    "feasibility_agreement",
                    f"target.is_feasible={target_feasible}, "
                    f"source.is_feasible(decode(g))={source_feasible}",
                )
            if self.invertible:
                assert self.encode is not None  # derived from invertible in __post_init__
                try:
                    round_tripped = self.decode(self.encode(phenotype))
                except Exception as exc:
                    record("round_trip", f"encode()/decode() raised: {exc}")
                else:
                    if not _approx_equal(round_tripped, phenotype):
                        first_diff = next(
                            (
                                k
                                for k in sorted(set(phenotype) | set(round_tripped))
                                if not _approx_equal(phenotype.get(k), round_tripped.get(k))
                            ),
                            "<unknown>",
                        )
                        record("round_trip", f"decode(encode(x)) != x at {first_diff!r}")

        self._check_declared_round_trip(record)

        failures = tuple(
            RepresentationCheckFailure(law=law, detail=detail, count=count)
            for (law, detail), count in sorted(counts.items())
        )
        return RepresentationCheck(n=n, ok=not failures, failures=failures)

    def _check_declared_round_trip(self, record: Callable[[str, str], None]) -> None:
        """The round-trip law over authored phenotypes.

        The authored phenotypes are the source's anchors and its
        defaults-filled config.

        The sampled half of `check()` can round-trip only `x = decode(g)`,
        and every such `x` sits on the chart's image: `encode` recovers the
        unit coordinate it was decoded from, so the comparison is exact and
        the tolerance is never exercised. An authored value such as
        `lr=1e-3` under a `Log()` chart does not sit there, and composing
        `to_unit` with `from_unit` through `log` and `exp` returns it only
        to within floating-point accuracy.

        That is the case `encode` exists for (API.md: "warm-starting ...
        anchors and historical observations are phenotypes, and seeding a
        solver with them is `rep.encode(config)`"), so leaving it
        unexercised meant a supplied encoding could be lossy on exactly the
        inputs a consumer feeds it and still report `ok`. Reported under its
        own law name so a failure says *which* half broke.
        """
        if not self.invertible:
            return
        assert self.encode is not None  # derived from invertible in __post_init__
        declared: list[tuple[str, Config]] = [
            (f"anchor {name!r}", config) for name, config in self.source.anchors.items()
        ]
        filled = self.source.apply_defaults({})
        if filled:
            declared.append(("apply_defaults({})", filled))

        for label, phenotype in declared:
            try:
                round_tripped = self.decode(self.encode(phenotype))
            except Exception as exc:  # a raise is itself a law violation, not an error here
                record("round_trip_declared", f"{label}: encode()/decode() raised: {exc}")
                continue
            if not _approx_equal(round_tripped, phenotype):
                first_diff = next(
                    (
                        k
                        for k in sorted(set(phenotype) | set(round_tripped))
                        if not _approx_equal(phenotype.get(k), round_tripped.get(k))
                    ),
                    "<unknown>",
                )
                record(
                    "round_trip_declared",
                    f"{label}: decode(encode(x)) != x at {first_diff!r}",
                )
