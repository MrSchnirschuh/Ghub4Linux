.PHONY: test lint format install

# Run the tooling from the project's virtualenv when it exists, so `make test`
# and `make lint` work as documented without activating anything first.  The
# venv is where install.sh puts pytest and ruff; the bare `python3` on PATH is
# the system interpreter and has neither.
VENV := $(if $(VIRTUAL_ENV),$(VIRTUAL_ENV),$(HOME)/.local/share/ghub4linux/venv)
PYTHON := $(or $(wildcard $(VENV)/bin/python3),python3)

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:
	$(PYTHON) -m ruff format src tests

install:
	bash install.sh
