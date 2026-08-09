<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/_static/readme-header-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/_static/readme-header-light.svg">
  <img alt="designspace. Declarative design spaces. Search strategy not included." src="docs/_static/readme-header-light.svg">
</picture>

Declarative design spaces with a polars-like expression API.

A *design space* is the set of configurations a system can take: an algorithm,
a model, a process, or a physical assembly. A space is declared once, giving
the parameters, their domains, the condition under which each is active, and
the combinations that are legal. The resulting `Space` can then be sampled,
validated against, handed to a solver, serialized, or compared with another
space by fingerprint.

## Example

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("optimizer").categorical("adam", "sgd"),
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),  # shorthand for .prior(ds.Log())
...     ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
... )
>>> print(space)
Space: 3 params, 1 conditional, 0 constraints
  optimizer  categorical  {'adam', 'sgd'}
  lr         real         [0.0001, 0.1]  log
  momentum   real         [0.0, 0.99]  when optimizer == 'sgd'
>>> sgd = space.sample_one(seed=0)
>>> sgd["optimizer"], "momentum" in sgd
('sgd', True)
>>> adam = space.sample_one(seed=3)
>>> adam["optimizer"], "momentum" in adam
('adam', False)

```

`momentum` is absent from the second configuration rather than present and
null. Conditionality is structural, not a mask applied afterwards.

## Scope

designspace declares spaces and does not search them. It ships no search
operators, no distance functions, no tree generators, and no algebraic
normalization of expressions. No value is ever silently clamped: a value
outside its domain is an error, never a rounded input.

## Install

```console
pip install designspace
```

Python 3.12 or later. DataFrame output needs the `polars` extra:

```console
pip install "designspace[polars]"
```

## Documentation

<https://todo.github.io/designspace>

## Development

Enter the development environment with [devenv](https://devenv.sh):

```console
devenv shell
```

The commit gates install as git hooks on first entry: a fast subset on commit,
the full set before a push. Run them by hand with `just gates`.

## License

This project is licensed under the [GNU General Public License v3.0](./LICENSE).
