# The commit gates.
#
# The git hooks, `devenv test` and CI all call into it, so a gate changes in
# one place and every caller follows.

# Show the available recipes.
default:
    @just --list

# The commit gates. All must pass before a commit.
gates: lint format types test doctest docs

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

serve-docs:
    uv run python -m http.server -d docs/_build 8000

# The suite without the `polars` extra, proving the core install path. A test
# that needs the extra carries the `requires_polars` marker.
test-core:
    uv run pytest -q -m "not requires_polars"
