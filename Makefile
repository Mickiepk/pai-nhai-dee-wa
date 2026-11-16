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

# ---- quality gates: `make ci` mirrors the PR pipeline (.github/workflows/ci.yml). See docs/TEST_STRATEGY.md ----
.PHONY: cov template-lint ci ci-full lint-actions

cov:          ## whole suite with coverage (fails under fail_under in pyproject.toml), writes coverage.xml
	$(PY) -m pytest -q --cov --cov-report=term-missing:skip-covered --cov-report=xml

template-lint:  ## sam validate --lint + cfn-lint (skipped with a notice if the tools are missing)
	@if command -v sam >/dev/null 2>&1; then AWS_DEFAULT_REGION=$${AWS_DEFAULT_REGION:-ap-southeast-1} sam validate --lint --template-file template.yaml; else echo "SKIP: sam not installed (brew install aws-sam-cli)"; fi
	@if command -v cfn-lint >/dev/null 2>&1; then cfn-lint template.yaml; else echo "SKIP: cfn-lint not installed (pip install cfn-lint)"; fi

ci: lint cov sandbox template-lint   ## same checks as the PR pipeline, on memory store (no Docker/Postgres needed)
	@echo "make ci: OK"

ci-full: ci test-pg   ## ci + whole suite and contract tests against local Postgres

lint-actions:  ## lint .github/workflows with actionlint (pip install actionlint-py)
	actionlint
