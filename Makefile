install: ; uv sync
test: ; uv run pytest -q
lint: ; uv run ruff check . && uv run mypy kaiju
run: ; uv run python -m kaiju.runner
