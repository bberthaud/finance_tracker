PY ?= .venv/bin/python

.PHONY: install test test-unit test-ui coverage lint format demo-data demo

install:
	uv sync --group dev --group sync

test: lint
	$(PY) -m pytest

test-unit:
	$(PY) -m pytest tests/unit

test-ui:
	$(PY) -m pytest -m ui -v

coverage:
	$(PY) -m pytest --cov --cov-report=term --cov-report=html
	@echo "Rapport : htmlcov/index.html"

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

demo-data:
	$(PY) scripts/generate_demo_data.py

demo:
	DATA_SOURCE=demo APP_PASSWORD=demo $(PY) -m streamlit run app.py
