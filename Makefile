.PHONY: test lint format install

test:
	python -m pytest -q

lint:
	python -m ruff check src tests
	python -m ruff format --check src tests

format:
	python -m ruff format src tests

install:
	bash install.sh
