.PHONY: install install-dev test test-core test-integration smoke lint typecheck \
        verify-sources dashboard run vacuum single-file verify-single-file clean

PY := python3

install:
	$(PY) -m pip install -e .

install-dev:
	$(PY) -m pip install -e ".[dev]"

# Runs everywhere -- stdlib only, no installed dependencies required.
test-core:
	PYTHONPATH=src $(PY) -m unittest discover -s tests/core -t . -v

# Full suite, including integration tests that need httpx/pydantic/respx.
# Individual integration modules skip themselves cleanly if deps are absent.
test:
	PYTHONPATH=src $(PY) -m pytest tests/ -v

test-integration:
	PYTHONPATH=src $(PY) -m pytest tests/integration -v

# Offline self-check: no network, no credentials required.
smoke:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli smoke

eval:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli eval

lint:
	ruff check src tests

typecheck:
	mypy src

verify-sources:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli sources verify

dashboard:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli dashboard

run:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli run

run-dry:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli run --dry-run

vacuum:
	PYTHONPATH=src $(PY) -m predoc_pipeline.cli vacuum

# Regenerate the single-file materializer (compile_project.py) from src/.
single-file:
	$(PY) tools/build_single_file.py

verify-single-file:
	$(PY) tools/verify_single_file.py

clean:
	find . -name '__pycache__' -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
