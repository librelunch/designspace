"""Program types: ``.symbolic()`` and ``.code()``.

A tree or a source string is a genotype, and tree and program generation are
out of scope, being solver territory. Core's job is therefore narrower than it
looks: *declare* the space, meaning a ``Signature``, a primitive vocabulary, a
depth budget and literal domains; *validate* values against that declaration;
and carry them through every existing surface, covering config, DataFrame,
hash, fingerprint, freeze and defaults, without core ever generating or
evaluating one.

Concepts introduced
-------------------
- **``.symbolic(signature, primitives, max_depth, validators=None,
  sampler=None)``**, a structured expression tree with value shape
  ``{"ast": <node>, "source": <str>}``, where ``"source"`` is optional. Core
  checks the *structure* of a submitted tree: the vocabulary this parameter
  declared, arity where a ``ds.Primitive`` declares one, variable names drawn
  from ``signature.args``, constants within a declared ``ds.FloatLiteral`` or
  ``ds.IntLiteral``'s bounds, and depth within ``max_depth``. It assigns no
  meaning to a bare primitive name and ships no evaluator.
- **``.code(signature, description="", constraints=None, examples=None,
  validators=None)``**, freeform source with value shape ``{"source": <str>}``.
  ``description``, ``constraints`` and ``examples`` are declared, serialized,
  fingerprinted metadata for a consumer's own backend.
- **Non-generative by default.** ``.code()`` is always non-generative, since no
  ``sampler=`` form exists, and ``.symbolic()`` is non-generative unless
  ``sampler=`` is given. A ``.default()`` satisfies ``sample()``'s obligation
  either way, ``freeze`` does too, and a parameter inactive for the draw never
  triggers it.
- **Open vocabulary, checked arity.** A bare string names a primitive with no
  arity attached, so ``"cos"`` structurally accepts any number of arguments.
  ``ds.Primitive(name, arity, fn=None)`` pins one, as an exact int or a
  ``(lo, hi)`` range. Core never calls ``Primitive.fn``; like ``validators``
  and ``.symbolic()``'s ``sampler``, it rides the non-serializable set under
  raise, mark or drop, degrading just that one field in place.

Run with ``uv run python examples/10_program_types.py``.
"""

from __future__ import annotations

import designspace as ds

SCHEDULE_SIGNATURE = ds.Signature({"step": int, "total": int}, float)
SCHEDULE_PRIMITIVES: list[str | ds.Primitive | ds.FloatLiteral] = [
    "cos",
    "pi",
    "/",
    ds.Primitive("*", 2),
]
SCHEDULE_AST = {
    "op": "cos",
    "args": [
        {
            "op": "*",
            "args": [
                {"op": "pi", "args": []},
                {"op": "/", "args": [{"var": "step"}, {"var": "total"}]},
            ],
        }
    ],
}
SCHEDULE_VALUE = {"ast": SCHEDULE_AST, "source": "cos(pi * (step / total))"}


def build_space() -> ds.Space:
    return ds.space(
        ds.param("schedule")
        .symbolic(SCHEDULE_SIGNATURE, SCHEDULE_PRIMITIVES, max_depth=4)
        .default(SCHEDULE_VALUE),
        ds.param("acceptance")
        .code(
            ds.Signature({"delta": float}, bool),
            description="Metropolis acceptance criterion",
            examples=[{"delta": -1.0}],
        )
        .default({"source": "delta < 0"}),
    )


def show_summary(space: ds.Space) -> None:
    print(f"Program-type space: {space.n_params} parameters")
    print(f"  has_nongenerative_params: {space.has_nongenerative_params}")
    print(f"  cardinality(): {space.cardinality()}   (opaque, so never enumerable)\n")


def show_ast_validation(space: ds.Space) -> None:
    print("--- AST validation (structural, no evaluation) ---")
    good = space.validate({"schedule": SCHEDULE_VALUE, "acceptance": {"source": "delta < 0"}})
    print(f"  well-formed tree: valid={good.valid}")

    undeclared_op = {"ast": {"op": "sin", "args": []}}
    bad = space.validate_param("schedule", undeclared_op)
    print(
        f"  undeclared op 'sin': valid={bad.valid}  reasons={[e.reason for e in bad.param_errors]}"
    )

    too_deep = {
        "ast": {
            "op": "cos",
            "args": [
                {
                    "op": "cos",
                    "args": [
                        {
                            "op": "cos",
                            "args": [
                                {
                                    "op": "cos",
                                    "args": [{"op": "cos", "args": [{"op": "pi", "args": []}]}],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    }
    deep = space.validate_param("schedule", too_deep)
    reasons = [e.reason for e in deep.param_errors]
    print(f"  depth > max_depth=4: valid={deep.valid}  reasons={reasons}")


def show_arity() -> None:
    # A bare string accepts any arity; a Primitive pins one (D-89).
    print("\n--- Arity: a bare string accepts any arity, a Primitive pins one ---")
    open_arity_space = ds.space(ds.param("e").symbolic(SCHEDULE_SIGNATURE, ["+"], max_depth=2))
    three_args = {"ast": {"op": "+", "args": [{"var": "step"}] * 3}}
    print(f"  bare '+' with 3 args: valid={open_arity_space.validate_param('e', three_args).valid}")

    pinned_arity_space = ds.space(
        ds.param("e").symbolic(SCHEDULE_SIGNATURE, [ds.Primitive("+", 2)], max_depth=2)
    )
    print(
        f"  Primitive('+', 2) with 3 args: "
        f"valid={pinned_arity_space.validate_param('e', three_args).valid}"
    )


def show_generativity() -> None:
    print("\n--- Sampling and generativity ---")
    no_default_space = ds.space(ds.param("e").symbolic(SCHEDULE_SIGNATURE, ["cos"], max_depth=2))
    try:
        no_default_space.sample_one(seed=0)
    except ds.SamplingError as e:
        print(f"  no default, no sampler: SamplingError ({str(e)[:60]}...)")

    with_sampler_space = ds.space(
        ds.param("e").symbolic(
            SCHEDULE_SIGNATURE,
            ["cos"],
            max_depth=2,
            sampler=lambda rng: {"ast": {"op": "cos", "args": []}},
        )
    )
    print(f"  sampler= draws: {with_sampler_space.sample_one(seed=0)}")
    print(
        f"  has_nongenerative_params with sampler=: {with_sampler_space.has_nongenerative_params}"
    )


def show_freeze_and_slice() -> None:
    print("\n--- freeze / slice ---")
    no_default_space = ds.space(ds.param("e").symbolic(SCHEDULE_SIGNATURE, ["cos"], max_depth=2))
    frozen = no_default_space.freeze(e={"ast": {"op": "cos", "args": []}})
    print(f"  freeze() satisfies the SamplingError: {frozen.sample_one(seed=0)}")
    sliced = ds.space(
        ds.param("e").symbolic(SCHEDULE_SIGNATURE, ["cos"], max_depth=2),
        ds.param("x").real(0.0, 1.0),
    ).slice(e={"ast": {"op": "cos", "args": []}})
    print(
        f"  slice() removes it, unlike .custom(): {'e' not in sliced.params}, "
        f"remaining params: {list(sliced.params)}"
    )


def show_identity(space: ds.Space) -> None:
    # Round-trip plus per-field opacity (D-88).
    print("\n--- Identity ---")
    doc = space.to_json()
    restored = ds.Space.from_json(doc)
    print(f"  round-trip fingerprint-equal: {restored.fingerprint() == space.fingerprint()}")

    opaque_space = ds.space(
        ds.param("e").symbolic(
            SCHEDULE_SIGNATURE, ["cos"], max_depth=2, validators=[lambda ast: True]
        )
    )
    try:
        opaque_space.to_json()
    except ds.SerializationError as e:
        print(f"  validators=... raises by default: {str(e)[:60]}...")
    marked = opaque_space.to_json(on_unserializable="mark")
    print(
        f"  on_unserializable='mark' degrades just that field: "
        f"{marked['params'][0]['domain']['validators']}"
    )


def main() -> None:
    space = build_space()
    show_summary(space)
    show_ast_validation(space)
    show_arity()
    show_generativity()
    show_freeze_and_slice()
    show_identity(space)


if __name__ == "__main__":
    main()
