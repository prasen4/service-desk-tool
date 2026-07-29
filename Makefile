.PHONY: help install dev test lint format serve clean

# Isolate tests from any real data directory.
TEST_ENV = TECH_DESK_DATA_DIR=./.pytest-data

help:
	@echo "Targets:"
	@echo "  install   Install the package"
	@echo "  dev       Install with dev + test dependencies"
	@echo "  test      Run the test suite (isolated data dir)"
	@echo "  lint      Run ruff checks"
	@echo "  format    Auto-fix lint issues"
	@echo "  serve     Run the dev server with autoreload"
	@echo "  clean     Remove caches and build artifacts"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	$(TEST_ENV) pytest -q

lint:
	ruff check src tests

format:
	ruff check --fix src tests

serve:
	tech-desk serve --reload

clean:
	rm -rf .pytest_cache .pytest-data .ruff_cache htmlcov .coverage \
		build dist src/*.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
