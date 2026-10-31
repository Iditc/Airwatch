.PHONY: lint format typecheck test all up down

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/ --ignore-missing-imports

test:
	pytest --cov=src --cov-report=term-missing

all: lint typecheck test

up:
	docker compose up --build -d

down:
	docker compose down
