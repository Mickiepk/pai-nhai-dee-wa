## What and why
<!-- One or two sentences. Link the issue / BUG-xx / backlog item. -->

## Type
- [ ] feat  - [ ] fix  - [ ] test  - [ ] docs  - [ ] ci  - [ ] refactor  - [ ] chore

## Checklist (definition of done: docs/TEST_STRATEGY.md)
- [ ] `make ci` is green locally (ruff, tests + coverage, sandbox, template lint)
- [ ] New behaviour has a test; a bug fix has a regression test (unit or `tests/sandbox/scenarios/*.yaml`)
- [ ] If a sandbox scenario had `bug: BUG-xx` and now passes, the `bug:` key is removed in this PR
- [ ] No raw chat text stored or logged (PDPA); no secrets, no `.env` committed
- [ ] Cost guards untouched, or the change is explained below (`config.py`, `MAX_*`, kill switch)
- [ ] Docs updated (module README under the touched folder, `docs/` if behaviour changed)
- [ ] Touches `template.yaml`: ran `sam validate --lint` and `cfn-lint`

## Risk / rollback
<!-- What can go wrong in prod? How to turn it off (BOT_ENABLED=false) or revert? -->

## Test evidence
<!-- Paste the relevant pytest / make sandbox output, or say why not applicable. -->
