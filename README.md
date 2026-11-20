# ไปไหนดีวะ (Pai-nhai-dee-wa)

A LINE bot that sits in a group chat like one more friend and helps the group decide **what to eat / what to do**, using real places from Google Maps and real distances.
It **only reads while a help-me-decide session is open (max 60 minutes) and never stores raw chat text** (PDPA).

> The bot's name and its chat messages are in Thai on purpose: that is the product's user-facing language.
> Example inputs below (for instance `@bot กินไรดีแถวอารีย์`, "what should we eat around Ari") are real Thai phrases the bot understands. Everything else in this repo is documented in English.

> **Summary.** A conversational LINE group-chat bot (Python 3.12, line-bot-sdk v3, Gemini for preference extraction,
> Google Places API (New), DynamoDB on AWS / Postgres locally, AWS SAM). `@bot กินไรดีแถวอารีย์` starts a 60-minute *session*:
> the bot announces it is listening, extracts preferences only (never stores chat text), speaks only when @mentioned or when
> the group settles on a place, then collects ✅ from every participant and posts a plan card.
> Everything runs offline with fakes: `make install && make ci && make simulate`, no API keys needed.

## Table of contents
1. [How the bot works](#how-the-bot-works)
2. [Architecture](#architecture)
3. [Quick start (local)](#quick-start-local)
4. [Environments: local vs AWS](#environments-local-vs-aws)
5. [Make targets](#make-targets)
6. [Config / environment variables](#config--environment-variables)
7. [Cost guards](#cost-guards-keeping-within-1000-thbmonth)
8. [Testing overview](#testing-overview)
9. [CI/CD overview](#cicd-overview)
10. [Repo map](#repo-map)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing-branching-commits)
13. [All documents](#all-documents)

## How the bot works

1. Someone writes `@ไปไหนดีวะ กินไรดีแถวอารีย์` ("what should we eat around Ari") -> the bot says it will listen to this group for at most 60 minutes, shows a **[stop listening]** button, and suggests 3 places.
2. From then on the bot **reads but stays quiet**. It remembers who likes what, who refuses what, and who just ate what (only a summary is kept, never the messages).
3. `@ไปไหนดีวะ แถวอารีย์มีบุฟเฟต์นานาชาติไหม` ("is there an international buffet around Ari") -> the bot searches using everything it has remembered.
4. "OK, let's go to this one" -> a confirmation card lists everyone who took part, with **[ตกลง ✅ (agree)] [ยังก่อน (not yet)]** buttons.
5. When everyone has answered -> a plan card (place, straight-line distance, map link, time if there is one) and the session ends.
6. Voting: use LINE's own polls (`@bot โหวตหน่อย`, "let's vote", explains how) · Announcement: `@bot ประกาศหน่อย` ("announce it").

Hard rules that must not leak: the bot speaks only when @mentioned, when it detects a decision, or when a button is pressed · no session = it does not read the chat ·
raw text is never stored or logged · the LLM only extracts signals, every decision is made in code (details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))

## Architecture

```mermaid
flowchart LR
    LINE[LINE Platform] -->|webhook POST + x-line-signature| WH
    subgraph AWS["AWS (prod / dev)"]
        WH["WebhookFunction<br/>handlers/webhook.py<br/>verify signature, prefilter"]
        Q[("SQS FIFO<br/>MessageGroupId = groupId<br/>dedup = webhookEventId")]
        DLQ[("DLQ<br/>after 3 receives")]
        WK["WorkerFunction<br/>handlers/worker.py<br/>batchItemFailures"]
        DDB[("DynamoDB<br/>sessions / dedup / quotas<br/>TTL")]
        SSM[("SSM SecureString<br/>secrets")]
        WH --> Q --> WK
        Q -. maxReceiveCount=3 .-> DLQ
        WK --> DDB
        WH -. cold start .-> SSM
        WK -. cold start .-> SSM
    end
    subgraph CORE["Business core (identical locally and on AWS)"]
        ENG["SessionEngine<br/>session/engine.py"]
        FEAT["features/<br/>search, cards, geo"]
        ADP["adapters/<br/>LLM, Places, LINE"]
        ST["store/<br/>memory, postgres, dynamo"]
        ENG --> FEAT
        ENG --> ADP
        ENG --> ST
    end
    WK --> ENG
    ADP -->|extract| GEM[Gemini]
    ADP -->|search| GP[Google Places API]
    ADP -->|reply token| LINE
    LOCAL["scripts/local_server.py<br/>or make simulate"] --> ENG
    ST -.-> DDB
    ST -.-> PG[("Postgres 16<br/>local / CI")]
```

- Two Lambdas: the **webhook** (verifies the signature, drops junk messages, enqueues to SQS and answers 200 immediately) and the **worker** (runs `SessionEngine`)
- Replies use only the **reply token** of the event being handled (no push messages)
- Local runs use the same engine; only the event receiver and the Store differ (see [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md))
- Per-group state machine: `LISTENING <-> CONFIRMING -> ended` (diagram in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))

## Quick start (local)

Needs Python 3.12+ (macOS: `brew install python@3.12`) · no keys required

### A) Memory store (fastest, no Docker)
```bash
python3 -m venv .venv && source .venv/bin/activate
make install        # install libraries
make ci             # ruff + tests + coverage + sandbox + template lint (all fakes, costs nothing)
make simulate       # play the A/B/C conversation around Ari in the terminal
python -m scripts.simulate --interactive   # type as several people yourself, e.g.  A: @bot กินไรดีแถวสยาม
```
The conversation lives in `scripts/scenarios/ari_buffet.txt`. Edit it or write a new file and run `python -m scripts.simulate --script yourfile.txt`

### B) Postgres store (closer to AWS, persists on your machine)
```bash
docker compose up -d      # postgres:16 on port 54329   (or make pg-up if you have no Docker)
make test-pg              # whole suite + store contract tests on Postgres
make simulate-pg          # play the conversation on Postgres
STORE=postgres make local # real LINE server through ngrok + Postgres
make pg-down              # stop   (make pg-reset = wipe all data)
```
Default URL `postgresql://pnd:pnd@localhost:54329/pnd`; tables are created automatically (`store/schema.sql`)

### C) Try it with real LINE (no AWS needed yet)
1. <https://manager.line.biz/> -> create a **LINE Official Account** (keep dev and prod as separate accounts). LINE no longer lets you create a Messaging API channel directly in the developers console.
2. In Official Account Manager: Settings -> **Messaging API** -> **Enable Messaging API** -> create or pick a Provider (a channel cannot be moved to another provider later)
3. <https://developers.line.biz/console/> (same login) -> your Provider -> the channel. **Basic settings**: copy the **Channel secret** · **Messaging API** tab: issue a **Channel access token (long-lived)**
4. Official Account Manager -> Settings -> Account settings -> turn on **Allow bot to join group chats** (older UI wording: *Group and multi-person chats*)
5. Response settings: turn off **Auto-reply** and **Greeting message**, turn on **Webhook**
6. ```bash
   cp .env.example .env      # fill in LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN
   make local                # http://localhost:8000/callback
   ngrok http 8000           # in another window
   ```
7. Put the ngrok URL in **Webhook URL** = `https://xxxx.ngrok-free.app/callback` -> Verify -> turn on Use webhook -> invite the bot to a group

By default the LLM and Places are **fakes** (places start with `[ตัวอย่าง]`, "sample"), so you can check that LINE is wired up without spending money.

### D) Use real Google services (pay as you go)
1. Google Cloud Console -> create a project -> enable **Billing** -> enable **Places API (New)** -> create an API key and restrict it to Places API (New) only
2. Set daily **Quotas** for Places (for example Text Search 300 calls/day) so the bill cannot balloon
3. Gemini: create a key at <https://aistudio.google.com/> in a project **that has billing enabled (paid tier)**
4. `.env`: `LLM_PROVIDER=gemini`, `PLACES_PROVIDER=google`, and fill in both keys

> **PDPA:** the free Gemini tier may use text to improve its models, so the bot **does not read group chat** until
> `GEMINI_PAID_TIER_CONFIRMED=true` is set (set it only when the project really has billing enabled). Without it the bot only acts when @mentioned
> and when a button is pressed (the server warns at startup). The engine also honours `GEMINI_PAID_TIER=true` as its fail-closed check:
> if the paid tier is not confirmed, no chat text is ever sent to Gemini, not even an @mention; the bot falls back to the offline rules
> (see "Product rules" in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Environments: local vs AWS

| | LOCAL | AWS (dev / prod) |
|---|---|---|
| Event receiver | `scripts/local_server.py` + ngrok, or `make simulate` | Lambda Function URL -> SQS FIFO -> Lambda worker |
| Store | `STORE=memory` or `postgres` | `dynamo` (DynamoDB, TTL attribute `ttl`) |
| Secrets | `.env` | SSM Parameter Store (SecureString) |
| Cost | 0 THB (with fakes) | pay per use, guarded by the budget in `template.yaml` |
| Deploy | - | `make deploy-dev` (manual) or `deploy.yml` (never run yet) |

Details and a table of "what can be proven where": [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) · block-by-block deploy steps: [docs/DEPLOY.md](docs/DEPLOY.md) ·
**Not deployed for real yet** (no AWS credentials); see [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md)

## Make targets

| Target | What it does | Needs |
|---|---|---|
| `make install` | install `requirements-dev.txt` | pip |
| `make test` | whole `pytest -q` suite (follows `STORE`, default memory) | - |
| `make cov` | same as `test` plus coverage; fails below `fail_under` (85); writes `coverage.xml` | - |
| `make lint` | `ruff check .` | - |
| `make sandbox` | all scenarios + determinism check (5 runs); writes `reports/sandbox_report.md` | - |
| `make template-lint` | `sam validate --lint` + `cfn-lint` (skipped with a message if not installed) | sam, cfn-lint |
| `make ci` | **the local equivalent of the old PR pipeline**: `lint cov sandbox template-lint` on the memory store | - |
| `make ci-full` | `ci` + `test-pg` | Postgres |
| `make lint-actions` | `actionlint` over `.github/workflows` | `pip install actionlint-py` |
| `make simulate` | play the simulated conversation in the terminal | - |
| `make local` | local LINE server (`/callback`, port 8000) | `.env`, ngrok |
| `make pg-up` / `pg-down` / `pg-reset` | start / stop / wipe local Postgres (`scripts/local_pg.sh`) | Postgres or Docker |
| `make test-pg` | whole suite + contract tests on Postgres | `pg-up` |
| `make simulate-pg` | simulate on Postgres | `pg-up` |
| `make deploy-dev` | `sam build && sam deploy --config-env dev` (manual, asks before changes) | AWS credentials, `ALERT_EMAIL` |

## Config / environment variables

Read in `config.py` (`load_settings()`) · example file: `.env.example` · `Settings` is validated with pydantic (out-of-range values fail at startup).
"Secret" = never commit, never log; on AWS these come from SSM, not directly from the environment.

| Variable | `Settings` field | Default | Required? | Secret? | Meaning |
|---|---|---|---|---|---|
| `LINE_CHANNEL_SECRET` | `line_channel_secret` | `""` | if `LINE_PROVIDER=real` | **yes** | verifies `x-line-signature` |
| `LINE_CHANNEL_ACCESS_TOKEN` | `line_channel_access_token` | `""` | if `LINE_PROVIDER=real` | **yes** | calls the LINE reply API |
| `GEMINI_API_KEY` | `gemini_api_key` | `""` | if `LLM_PROVIDER=gemini` | **yes** | Gemini key (project must have billing enabled) |
| `GOOGLE_PLACES_API_KEY` | `google_places_api_key` | `""` | if `PLACES_PROVIDER=google` | **yes** | Places API (New) key |
| `LLM_PROVIDER` | `llm_provider` | `fake` | no | no | `fake` (offline rules) or `gemini` |
| `PLACES_PROVIDER` | `places_provider` | `fake` | no | no | `fake` or `google` |
| `LINE_PROVIDER` | `line_provider` | `fake` | no | no | `fake` (replies kept in memory) or `real`; `make local` forces `real` |
| `STORE` (or `STORE_PROVIDER`) | `store_provider` | `memory` | no | no | `memory` / `postgres` / `dynamo`; `STORE` wins over `STORE_PROVIDER`; the AWS template sets `STORE_PROVIDER=dynamo` |
| `DATABASE_URL` | `database_url` | `postgresql://pnd:pnd@localhost:54329/pnd` | if `STORE=postgres` outside a dev machine | **yes** if it points at a real database | Postgres DSN |
| `TABLE_NAME` | `table_name` | `pai-nhai-dee-wa-dev` | if `STORE=dynamo` | no | DynamoDB table name (the template sets it per Stage) |
| `GEMINI_MODEL` | `gemini_model` | `gemini-2.5-flash-lite` | no | no | model used for signal extraction |
| `GEMINI_PAID_TIER_CONFIRMED` | `gemini_paid_tier_confirmed` | `false` | **must be `true` before Gemini may read chat** | no | confirms the paid tier (PDPA). If not true the bot only answers @mentions and buttons; with `LLM_PROVIDER=fake` reading is allowed because nothing leaves the machine. The engine also accepts `GEMINI_PAID_TIER=true` (read at runtime, fail-closed) |
| `BOT_ENABLED` | `bot_enabled` | `true` | no | no | kill switch: `false` = completely silent (events are acked and dropped, no retry) |
| `SESSION_MINUTES` | `session_minutes` | `60` (range 5-120) | no | no | session lifetime |
| `MAX_LLM_CALLS_PER_SESSION` | `max_llm_calls_per_session` | `40` | no | no | beyond this the free rules take over |
| `MAX_SEARCHES_PER_GROUP_PER_DAY` | `max_searches_per_group_per_day` | `10` | no | no | per-group daily search quota (Thai time) |
| `MAX_PLACES_CALLS_PER_DAY` | `max_places_calls_per_day` | `300` | no | no | daily Places quota across all groups (geocode lookups count too) |
| (no env var) | `default_radius_km` | `3.0` | - | - | fixed value in `Settings`; the real radius per kind of task lives in `features/food.py` (3 km) and `features/activity.py` (5 km) |

AWS / tooling-only variables (not in `config.py`):

| Variable | Used by | Meaning |
|---|---|---|
| `QUEUE_URL` | `handlers/webhook.py` | URL of the SQS FIFO queue (set by the template; missing = `KeyError`) |
| `LINE_CHANNEL_SECRET_PARAM`, `LINE_CHANNEL_ACCESS_TOKEN_PARAM`, `GEMINI_API_KEY_PARAM`, `GOOGLE_PLACES_API_KEY_PARAM` | `handlers/ssm.py` | **names** of the SSM parameters (not the secret values) that Lambda reads at cold start; the webhook can read only the first one, the worker reads the other three |
| `STAGE` | template | `dev` / `prod` |
| `PND_PG_PORT`, `PND_PG_DIR`, `PG_BIN` | `scripts/local_pg.sh` | port (54329), data folder (`/tmp/pnd-pg`), path to the Postgres binaries |
| `PYTHONHASHSEED` | `regression.yml` | varies the seed to catch bugs that depend on set/dict ordering |

SAM parameters (`template.yaml`): `Stage`, `AlertEmail` (required), `MonthlyBudgetUsd` (28), `LlmProvider`, `PlacesProvider`, `GeminiPaidTierConfirmed`, `BotEnabled`, `MaxPlacesCallsPerDay`, `WebhookReservedConcurrency` (10), `WorkerReservedConcurrency` (5)

## Cost guards (keeping within 1,000 THB/month)

| Guard | Default | Set at | Enforced in |
|---|---|---|---|
| Kill switch (turns the whole bot off) | `BOT_ENABLED=true` | `.env` / SAM `BotEnabled` | `SessionEngine.handle` |
| LLM calls per session | 40, then the free rules take over | `MAX_LLM_CALLS_PER_SESSION` | `SessionEngine._extract` |
| Searches per group per day | 10 | `MAX_SEARCHES_PER_GROUP_PER_DAY` | `SessionEngine._search_replies` |
| Places calls per day, all groups | 300 (every call counts, geocode included) | `MAX_PLACES_CALLS_PER_DAY` | `SessionEngine._search_replies` (`spend`) |
| Paid tier required before reading chat | `false` | `GEMINI_PAID_TIER_CONFIRMED` | `Settings.chat_reading_enabled` |
| Lambda concurrency | webhook 10 / worker 5 | SAM parameters | `template.yaml` (new accounts with a quota below 120: use `-1`, see DEPLOY.md) |
| AWS budget alert | USD 28 (~1,000 THB) | `MonthlyBudgetUsd` | `template.yaml` (alert only, it does not cut service) |
| Push messages | never used | - | replies use the reply token only |
| Popular areas | coordinates are in the code, no geocode cost | `features/geo.AREA_CENTERS` | `features/search.py` |

Tests that prove these guards: `tests/integration/test_caps.py` and scenarios SBX-39..43 in `tests/sandbox/`

## Testing overview

| Layer | Where | What it proves | Runs |
|---|---|---|---|
| Unit | `tests/unit/` | small pieces of logic: prefilter, merge, extractor rules, geo, ack, webhook/worker handlers | every PR |
| Integration | `tests/integration/` | the whole engine with fakes, caps, bug-fix regressions, DynamoDB via moto | every PR |
| Contract | `tests/contract/` | all 3 Stores behave identically | every PR (Postgres job) |
| Sandbox | `tests/sandbox/` + `make sandbox` | full conversations, 72 cases, plus byte-for-byte determinism | every PR + nightly (5 hash seeds) |
| Intent eval | `scripts/eval_intents.py` | accuracy of Thai understanding, measured in % | nightly / before a release |
| Smoke | `scripts/smoke.py` | after deploy: the Function URL answers 200/401 correctly | after deploy only |

Full strategy (pyramid, coverage, flaky-test policy, definition of done, release gate): [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) ·
what "deterministic" means and the P0-P3 severity levels: [docs/TEST_POLICY.md](docs/TEST_POLICY.md) ·
testing course, level by level: [docs/TESTING.md](docs/TESTING.md) · table of the 72 cases: [docs/TEST_SPEC.md](docs/TEST_SPEC.md) · test code explained: [tests/README.md](tests/README.md)

## CI/CD overview

**GitHub Actions are removed for now** (the GitHub account has a billing lock, so runs never started). The workflows (`ci.yml`, `regression.yml`, `deploy.yml`) are still in git history: restore them with
`git checkout 6db7c59 -- .github/workflows` when billing is fixed.

Until then, run the same checks locally before every push: `make ci` (add `make ci-full` if you touched the store), and `make sandbox` for the determinism check. Deploys are manual with `make deploy-dev` ([docs/DEPLOY.md](docs/DEPLOY.md)).
`.github/dependabot.yml`, `CODEOWNERS` and the PR template are kept.

## Repo map

```
.
├── config.py            Settings + load_settings() + load_dotenv()
├── wiring.py            build_engine(): the single place that picks real vs fake providers
├── handlers/            Lambda entry points (webhook, worker, ssm)           -> handlers/README.md
├── session/             SessionEngine (state machine), prefilter, merge      -> session/README.md
├── features/            search/rank, cards (LINE Flex), geo                  -> features/README.md
├── adapters/            LLM (Gemini + rules), Places, LINE gateway, lexicon  -> adapters/README.md
├── store/               memory / postgres / dynamo + schema.sql              -> store/README.md
├── scripts/             simulate, local_server, smoke, eval_intents, local_pg -> scripts/README.md
├── tests/               unit, integration, contract, sandbox, eval           -> tests/README.md
├── docs/                ARCHITECTURE, ENVIRONMENTS, DEPLOY, TEST_*, modules/INDEX.md
├── reports/             sandbox_report.md (generated by make sandbox), QA reports
├── template.yaml        AWS SAM (2 Lambdas, SQS FIFO + DLQ, DynamoDB, alarms, budget)
├── samconfig.toml       per-stage deploy settings (dev/prod)
├── docker-compose.yml   Postgres 16 for local/CI
└── .github/             workflows, dependabot, CODEOWNERS, PR template
```

## Troubleshooting

| Symptom | Usual cause | Fix |
|---|---|---|
| `make test-pg` skips the Postgres tests with `run make pg-up first` | Postgres is not running | `make pg-up` (or `docker compose up -d`), then check `DATABASE_URL` |
| `make pg-up` says it cannot find the binaries | Postgres is not installed | macOS: `brew install postgresql@16`, or use `docker compose up -d` |
| Bot does not answer in the group (local) | wrong webhook URL / ngrok URL changed, "Allow bot to join group chats" not on, Auto-reply still on | set the Webhook URL again and press Verify; check the `make local` log |
| Bot answers only when @mentioned and does not read the chat | `GEMINI_PAID_TIER_CONFIRMED` (or `GEMINI_PAID_TIER`) is not `true` (by design, PDPA) | set it only after Gemini billing is enabled, or use `LLM_PROVIDER=fake` while testing |
| Bot is completely silent | `BOT_ENABLED=false` | set it to `true` |
| Server warns `... missing` at startup | a real provider is selected but its key is not set | put the key in `.env` or go back to `fake` |
| 401 from the webhook | wrong channel secret / body changed before the signature check | check the secret of the right channel (dev vs prod) |
| "today's N searches are used up" appears (Thai text) | the `MAX_SEARCHES_PER_GROUP_PER_DAY` quota was hit | wait until tomorrow (Thai time) or raise the value |
| `make sandbox` exits 1 with `XPASS` | a tracked bug has been fixed | remove `bug:` from that scenario (see docs/TEST_POLICY.md item 6) |
| `make sandbox` exits 1 with `determinism` | code depends on set/dict order, time or uuid | see the diff in `reports/sandbox_report.md` and decide with a stable key (for example `place_id`) |
| `make ci` skips template lint | `sam` / `cfn-lint` not installed | `brew install aws-sam-cli` and `pip install cfn-lint` |
| coverage below 85% | code added without tests | add tests (see docs/TEST_STRATEGY.md); do not lower `fail_under` just to get green |
| `sam build` fails on a Mac | Python is not 3.12 | `brew install python@3.12`; see the troubleshooting section of docs/DEPLOY.md |
| Lambda: cannot set reserved concurrency | new AWS account with a low account-wide quota | use `WebhookReservedConcurrency=-1 WorkerReservedConcurrency=-1` (docs/DEPLOY.md item 1.7) |

## Contributing (branching, commits)

- **Branch**: branch from `main` as `type/short-description`, for example `feat/radius-meters`, `fix/dedup-hash`, `docs/test-strategy`, `ci/nightly` · no direct pushes to `main` once branch protection is on · keep PRs small and about one thing
- **Commit**: [Conventional Commits](https://www.conventionalcommits.org/) `type(scope): summary` (English, at most ~72 characters) where type is `feat | fix | test | docs | ci | refactor | chore | perf`
  and scope is for example `session`, `adapters`, `store`, `handlers`, `sandbox`, `deploy` · the body explains "why", not "what"
- **Before opening a PR**: `make ci` must be green (run `make ci-full` if you touched the store) · use the [PR template](.github/PULL_REQUEST_TEMPLATE.md)
- **Every bug needs a test**: add a scenario in `tests/sandbox/scenarios/` or a unit test before fixing (see docs/TEST_POLICY.md item 6)
- **Never**: commit `.env` or real keys, log or store raw chat text, lower a budget cap or disable a guard without explaining it in the PR, or change a test's expectation to match wrong behaviour just to get green
- **Review**: `CODEOWNERS` assigns owners; changes to `template.yaml`, `config.py` and `.github/` must go through the repo owner
- **Adding a new provider/store**: see "How to extend" in [adapters/README.md](adapters/README.md) and [store/README.md](store/README.md)

## All documents

| Document | About |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | flow, state machine, stored state, failure modes, product rules |
| [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) | local (Postgres) vs AWS, what is proven where |
| [docs/DEPLOY.md](docs/DEPLOY.md) | runbook for deploying to AWS |
| [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md) | Gate 0 go/no-go, PDPA |
| [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) | pyramid, suites per PR/nightly/release, coverage, flaky tests, definition of done |
| [docs/TEST_POLICY.md](docs/TEST_POLICY.md) | determinism, sandbox rules, severity P0-P3, gates |
| [docs/TEST_SPEC.md](docs/TEST_SPEC.md) | table of sandbox test cases |
| [docs/TESTING.md](docs/TESTING.md) | Level 0-5 testing course for beginners |
| [docs/BACKLOG.md](docs/BACKLOG.md) | open work and deferred product decisions |
| [docs/modules/INDEX.md](docs/modules/INDEX.md) | index of every module's documentation |
| [reports/QA_REPORT_round1.md](reports/QA_REPORT_round1.md) | QA report, round 1 |
| [reports/QA_REPORT_final.md](reports/QA_REPORT_final.md) | QA report, final gate |
