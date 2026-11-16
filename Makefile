PY ?= python3

.PHONY: install test lint simulate local sandbox deploy-dev

install:
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

# Offline sandbox: scenario specs (docs/TEST_SPEC.md) + determinism, writes reports/sandbox_report.md
sandbox:
	$(PY) -m tests.sandbox.run

simulate:
	$(PY) -m scripts.simulate

local:
	set -a; [ -f .env ] && . ./.env; set +a; $(PY) -m scripts.local_server

# Manual only. Needs AWS credentials + SSM parameters (see README). Asks before changing anything.
deploy-dev:
	sam build && sam deploy --config-env dev --parameter-overrides Stage=dev AlertEmail=$${ALERT_EMAIL:?set ALERT_EMAIL}

# ---- local environment: Postgres (no AWS, no cost). See docs/ENVIRONMENTS.md ----
DATABASE_URL ?= postgresql://pnd:pnd@localhost:54329/pnd
export DATABASE_URL

.PHONY: pg-up pg-down pg-reset test-pg simulate-pg
pg-up:        ## start local Postgres (scripts/local_pg.sh; or `docker compose up -d`)
	./scripts/local_pg.sh start

pg-down:
	./scripts/local_pg.sh stop

pg-reset:
	./scripts/local_pg.sh reset

test-pg: pg-up   ## whole suite + store contract against Postgres
	STORE=postgres $(PY) -m pytest -q

simulate-pg: pg-up
	STORE=postgres $(PY) -m scripts.simulate
