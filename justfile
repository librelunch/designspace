# The commit gates.
#
# The git hooks, `devenv test` and CI all call into it, so a gate changes in
# one place and every caller follows.

# Show the available recipes.
default:
    @just --list

# The commit gates. All must pass before a commit.
gates: lint format types test doctest build-docs gates-solvers

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

build-docs:
    uv run --group docs sphinx-build -b html -W docs docs/_build

serve-docs:
    uv run python -m http.server -d docs/_build 8000

# The sibling solver package, held to the same lint and type settings as core:
# the workspace shares one environment and one tool configuration, so a
# standard cannot drift between the two. This gate is what makes a change to
# the representation fail here on the day it lands rather than at release.
gates-solvers:
    uv run ruff check packages/
    uv run ruff format --check packages/
    uv run mypy --strict packages/designspace-solvers/src/
    uv run pytest -q packages/designspace-solvers/tests
    uv run pytest -q --doctest-modules packages/designspace-solvers/src

# The release check, run before a tag. Deliberately not one of the commit
# gates. Introduces a deliberate type error against a public signature and
# mypy must report that error.
release-check:
    #!/usr/bin/env bash
    set -euo pipefail

    rm -rf dist
    uv build --package designspace
    wheel="$(ls dist/*.whl)"

    # `--no-project` because this reads the archive with the standard library
    # alone. Without it the check would sync the whole development environment,
    # the documentation toolchain included, to run one line.
    uv run --no-project python -c "import sys, zipfile; names = zipfile.ZipFile(sys.argv[1]).namelist(); sys.exit(None if 'designspace/py.typed' in names else 'py.typed is absent from the wheel')" "$wheel"

    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT
    uv venv --no-project "$work/venv" >/dev/null
    consumer="$work/venv/bin/python"
    uv pip install --quiet --python "$consumer" "$wheel" mypy

    # `n_params` is an `int`. Assigning it to a `str` is the error mypy has to
    # find, and it can only find it by reading the installed package's types.
    cat > "$work/consumer.py" <<'PY'
    import designspace as ds

    space = ds.space(ds.param("x").real(0.0, 1.0))
    count: str = space.n_params
    PY

    report="$("$work/venv/bin/mypy" --strict "$work/consumer.py" 2>&1 || true)"
    echo "$report"

    if grep -q 'import-untyped\|library stubs or py.typed' <<<"$report"; then
        echo "FAIL: the installed wheel's types are invisible to a consumer" >&2
        exit 1
    fi
    if ! grep -q 'Incompatible types in assignment' <<<"$report"; then
        echo "FAIL: mypy read no public signatures from the installed wheel" >&2
        exit 1
    fi
    echo "OK: the wheel installs and a consumer type-checks against it"

# The suite without the `polars` extra, proving the core install path. A test
# that needs the extra carries the `requires_polars` marker.
test-core:
    uv run pytest -q -m "not requires_polars"
