"""`ParamType`: the open-world extension protocol.

See API.md, "Protocols" and "Extension".

**Required surface only.** `sample`, `cardinality`, and `properties` with
`extract`, are optional capabilities a type may or may not implement,
duck-typed through `hasattr` at each call site as the external `Prior`
protocol's optional `.cdf()` is in `ir/_priors.py` and
`charts/_external.py`. None belongs to this `Protocol`'s static shape, so a
type author never has to stub an unsupported capability, and an
`isinstance` or structural check on `ParamType` demands only the required
five members.

**Value convention.** `validate` and `extract`, and a `sample()`-supporting
type's own use of its sampled value, operate on the type's native
representation, meaning whatever `sample()` returns. `to_json` and
`from_json` are the only bridge between that native form and the JSON-safe
phenotype form.

Every public, config-dict-shaped surface holds the phenotype form,
`to_json(native)`, and never the native object: a config leaf,
`.validate()`, `.freeze()`, `.default()` and `sample_one()`'s return value
alike. Core calls `to_json` once, immediately after `sample()` produces a
fresh native value, and calls `from_json` immediately before it needs
`validate` or `extract` on a config-sourced value.

That lets every generic value codec, meaning `encode_default_value` in
`identity/_tags.py` and the config, flatten and hash machinery, treat a
custom leaf as an ordinary opaque JSON-shaped value, with no per-type
special casing outside this bridge.

The `.custom(sampler, validator)` shorthand has no `to_json` or `from_json`
at all; API.md calls it a "Callback shorthand. Not serializable." For it
native and phenotype coincide, and `sampler(rng)`'s return value is used
directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


class ParamType(Protocol):
    """The full `.custom(param_type)` protocol. Required: `type_key`,
    `validate`, `to_json`, `from_json`, `describe`.

    Optional capabilities (checked via `hasattr`, not declared in this
    Protocol's static shape; see the module docstring):

    - `sample(self, rng) -> Any`, generative iff present; absent, the
      param is **non-generative**: sampling raises `SamplingError` naming
      the param iff a value must be materialized, and
      `.default()`/`freeze`/`slice`/inactivity each satisfy that instead.
    - `cardinality(self) -> int | None`, contributing a finite factor to
      `Space.cardinality()` iff present; absent, the whole space's
      cardinality is `None` whenever this param is included.
    - `properties(self) -> dict[str, type]` and `extract(self, value, prop)
      -> Any`, which present *together* enable `.prop()` in expressions.
      Reading an undeclared property, declaring a non-scalar property
      type, or comparing a property against a value of another type is a
      resolution error.

    Examples
    --------
    A complete implementation. The five required members are enough to
    declare, validate, and serialize; `sample` makes it generative, and
    `properties`/`extract` let constraints read into the value.

    >>> class IntervalType:
    ...     type_key = "interval"
    ...
    ...     def validate(self, value):
    ...         return value["lo"] < value["hi"]
    ...
    ...     def to_json(self, value):
    ...         return value
    ...
    ...     def from_json(self, data):
    ...         return data
    ...
    ...     def describe(self):
    ...         return {"fields": ["lo", "hi"]}
    ...
    ...     def sample(self, rng):
    ...         lo = float(rng.random())
    ...         return {"lo": lo, "hi": lo + float(rng.random())}
    ...
    ...     def properties(self):
    ...         return {"width": float}
    ...
    ...     def extract(self, value, prop):
    ...         return value["hi"] - value["lo"]
    >>> s = ds.space(ds.param("band").custom(IntervalType()))
    >>> s.validate({"band": {"lo": 0.1, "hi": 0.4}}).valid
    True
    >>> s.validate({"band": {"lo": 0.9, "hi": 0.4}}).valid
    False

    Because it declares `properties`/`extract`, constraints can read into
    the value:

    >>> narrow = s.require(ds.param("band").prop("width") <= 0.5)
    >>> narrow.is_feasible({"band": {"lo": 0.1, "hi": 0.4}})
    True
    >>> narrow.is_feasible({"band": {"lo": 0.1, "hi": 0.9}})
    False
    """

    @property
    def type_key(self) -> str:
        """A stable name for this type.

        It identifies the type in a serialized document and is the key a
        consumer's registry uses when rebuilding a space with
        `Space.from_json(..., custom_types=...)`. Solver adapters key off
        it too. Choose something durable, since it is part of the wire format.
        """
        ...

    def validate(self, value: Any) -> bool:
        """Whether `value` is a legal value of this type.

        Receives the type's **native** form. Called by `Space.validate()`
        and by the sampler after a draw.

        Parameters
        ----------
        value : Any
            A candidate value, in native form.

        Returns
        -------
        bool
            Whether it is acceptable.
        """
        ...

    def to_json(self, value: Any) -> Any:
        """Convert a native value to its JSON-safe form.

        This is the bridge between the type's internal representation and
        the form that appears in configuration dicts, `.sample_one()`
        results, hashes, and serialized documents, so it runs on every
        value leaving the type, not only when writing JSON.

        Parameters
        ----------
        value : Any
            A value in native form.

        Returns
        -------
        Any
            A JSON-safe equivalent.
        """
        ...

    def from_json(self, data: Any) -> Any:
        """Convert a JSON-safe value back to native form.

        The inverse of `to_json`, called before `validate` or `extract`
        runs on a value that came from a configuration.

        Parameters
        ----------
        data : Any
            A value in JSON-safe form.

        Returns
        -------
        Any
            The native equivalent.
        """
        ...

    def describe(self) -> dict[str, Any]:
        """Describe the type itself, not any particular value.

        What a consumer reads to learn the type's shape: bounds, item
        counts, whatever a solver adapter or a documentation generator
        would want. Serialized with the space, and must be JSON-safe.

        Returns
        -------
        dict[str, Any]
            A JSON-safe description of the type.
        """
        ...


def is_generative(param_type: Any) -> bool:
    """Whether `param_type` declares `sample()` (API.md, "Sampling and
    Generativity")."""
    return hasattr(param_type, "sample")


def has_cardinality(param_type: Any) -> bool:
    return hasattr(param_type, "cardinality")


def has_properties(param_type: Any) -> bool:
    return hasattr(param_type, "properties") and hasattr(param_type, "extract")
