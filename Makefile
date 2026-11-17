.PHONY: up down reset logs api

up:
	docker compose up -d --build

down:
	docker compose down

reset:
	docker compose down -v && docker compose up -d --build

logs:
	docker compose logs -f agent-api hasura

api:
	uvicorn app.main:app --reload
