# Changelog

The notable changes in each release, newest first.

While the major version is zero, a minor release may change the Python API. The
serialized format carries an integer version of its own, independent of the
release version and currently `1`. A document written by one release reads back
in every later release that keeps that number, and a release that changes it
says so here.

## 0.1.0 (2026-08-11)

The first public release. Python 3.12 or later. The runtime depends on `numpy`
and `rfc8785` alone; DataFrame output needs the `polars` extra.

### Declaring a space

- `ds.space` assembles a space from definitions built by `ds.param`.
- Scalar domains: `real`, `integer`, `categorical`, `ordinal`, and `bool`.
- Structured domains: `choice`, `struct`, `subset`, `permutation`, and lists
  through `lift`.
- Priors over numeric domains: `Log`, `Logit`, and `Power`, with `log_scale`
  and `quantized` as shorthands. Categorical and ordinal domains take
  `Weights`.
- Custom domains through `custom`, with `prop` exposing a property of the value
  to the expression language.
- Program-valued domains through `symbolic` and `code`.
- `when` makes a parameter conditional. An inactive parameter is absent from a
  configuration rather than present and null.

### Expressions and constraints

- A polars-like expression language over parameters, with comparisons,
  arithmetic, and the boolean combinators `all_` and `any_`.
- `require`, `forbid`, `encourage`, and `discourage` state hard and soft
  constraints. Each reports its own polarity.
- Aggregates over structure: `count`, `count_of`, `sum_over`, `contains`,
  `position_of`, `distinct`, and `is_sorted`.
- Bounds may be expressions over other parameters. Each resolved bound carries
  the origin that produced it.
- `ds.value` carries a derived quantity the language does not model, opaque to
  analysis and excluded from generation.

### Sampling and validation

- `sample_one`, `sample_dicts`, and `sample`, the last returning a DataFrame.
  Every draw takes an explicit seed or generator; no global random state is
  read or written.
- `validate` and `validate_param` return a result naming each offending
  parameter. `is_feasible`, `is_complete`, and `missing_params` answer the
  narrower questions.
- Constraint evaluation is three-valued: a constraint over a parameter that is
  not yet assigned is pending rather than true or false.
- `sampling_report` and `infeasibility_reasons` report why draws are being
  rejected, and `evaluate_constraints` scores a configuration constraint by
  constraint.
- No value is ever silently clamped. A value outside its domain is an error,
  never a rounded input.

### Partial configurations

- `apply_defaults`, `has_complete_defaults`, and `default` on a definition.
- `next_assignable` and `remaining_domain` drive an assignment loop one
  parameter at a time, narrowing a domain as earlier choices determine it.
- `flatten`, `unflatten`, and `is_flat` move a configuration between its nested
  and flat forms. Every configuration-taking method accepts either.

### Structure and metaprogramming

- Instance paths address the elements of a lift, and constraints apply per
  instance.
- `slice`, `freeze`, `select`, `filter`, `extend`, `without_constraints`, and
  `map_params` derive a space from a space. A fixed value folds through: counts
  become static and always-true conditions disappear.
- `subspaces`, `active_subspace`, `dependency_graph`, `topological_order`, and
  `coordinate_paths` expose the resolved structure.
- `cardinality`, `is_finite`, `is_conditional`, `is_hierarchical`, and
  `has_variable_length` describe a space without enumerating it.

### Identity and serialization

- `to_json` and `from_json` round-trip a space through a canonical document at
  format version `1`.
- `fingerprint` identifies a space by structure, and `config_hash` identifies a
  configuration under it. Together they say which space a stored result came
  from.
- `config_diff` reports what changed between two configurations.
- Values a document cannot carry are handled by a stated policy rather than
  silently dropped.

### Representation

- `represent` yields the induced chart representation, mapping a configuration
  to a fixed-length numeric vector and back.
- The `Representation` and `Encoding` protocols admit a consumer-supplied
  encoding, checked against a round-trip law.

### Rendering and typing

- Every public type renders itself for a human, and `pretty` renders a
  configuration against the space it belongs to.
- The package ships type information, so a consumer's type checker reads the
  public signatures.
