PY ?= python3

.PHONY: install test lint simulate local deploy-dev

install:
	$(PY) -m pip install -r requirements-dev.txt

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check .

simulate:
	$(PY) -m scripts.simulate

local:
	set -a; [ -f .env ] && . ./.env; set +a; $(PY) -m scripts.local_server

# Manual only. Needs AWS credentials + SSM parameters (see README). Asks before changing anything.
deploy-dev:
	sam build && sam deploy --config-env dev --parameter-overrides Stage=dev AlertEmail=$${ALERT_EMAIL:?set ALERT_EMAIL}
