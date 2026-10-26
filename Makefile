.PHONY: test-db test-db-down

test-db:
	docker compose -f docker-compose.test.yml down --volumes --remove-orphans
	docker compose -f docker-compose.test.yml up -d --wait postgres-test
	docker compose -f docker-compose.test.yml run --build --rm test-runner

test-db-down:
	docker compose -f docker-compose.test.yml down -v
