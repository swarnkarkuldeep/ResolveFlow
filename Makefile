.PHONY: up down reset test logs

up:
	./start.sh

down:
	docker compose down

reset:
	docker compose down -v

test:
	cd backend && python -m pytest -q
	cd frontend && npm test -- --run

logs:
	docker compose logs -f
