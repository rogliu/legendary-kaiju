.PHONY: install test lint run check

install: ; uv sync
test: ; uv run pytest -q
lint: ; uv run ruff check . && uv run mypy kaiju
run: ; uv run python -m kaiju.runner

# Canonical gate. The Loop Contract (docs/agents/LOOP.md) runs `make check`
# every iteration; a green result is the precondition for any merge to main.
check: test lint
