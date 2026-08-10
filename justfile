# The commit gates.
#
# The git hooks, `devenv test` and CI all call into it, so a gate changes in
# one place and every caller follows.

# Show the available recipes.
default:
    @just --list

# The commit gates. All must pass before a commit.
gates: lint format types test doctest docs solvers

# The fast subset, run on every commit.
check: lint format types

lint:
    uv run ruff check

format:
    uv run ruff format --check

types:
    uv run mypy --strict src/

test:
    uv run pytest -q

doctest:
    uv run pytest -q --doctest-modules --doctest-glob='*.md' src docs README.md

docs:
    uv run --extra docs sphinx-build -b html -W docs docs/_build

# The sibling solver package, held to the same lint and type settings as core:
# the workspace shares one environment and one tool configuration, so a
# standard cannot drift between the two. This gate is what makes a change to
# the representation fail here on the day it lands rather than at release.
solvers:
    uv run ruff check packages/
    uv run ruff format --check packages/
    uv run mypy --strict packages/designspace-solvers/src/
    uv run pytest -q packages/designspace-solvers/tests
    uv run pytest -q --doctest-modules packages/designspace-solvers/src

serve-docs:
    uv run python -m http.server -d docs/_build 8000

# The suite without the `polars` extra, proving the core install path. A test
# that needs the extra carries the `requires_polars` marker.
test-core:
    uv run pytest -q -m "not requires_polars"
