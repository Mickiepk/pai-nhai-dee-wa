"""One behaviour contract, three stores: memory, postgres (local), dynamo (moto).

If a test passes on all three, swapping STORE=memory|postgres|dynamo cannot change behaviour.
Postgres is skipped (with a reason) when DATABASE_URL is unreachable: run `make pg-up`.
"""

from __future__ import annotations

import os
import threading

import boto3
import pytest
from moto import mock_aws

from session.models import Session
from store.base import COUNTER_TTL_S, EVENT_TTL_S
from store.dynamo import DynamoStore
from store.memory import MemoryStore
from tests.fakes import DEFAULT_PG_URL

NOW = 1_800_000_000


def _pg_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_PG_URL)


def _make_postgres():
    import psycopg

    from store.postgres import PostgresStore

    try:
        psycopg.connect(_pg_url(), connect_timeout=2).close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable at DATABASE_URL ({type(e).__name__}); run `make pg-up` first")
    store = PostgresStore(_pg_url())
    store.reset()
    return store


@pytest.fixture(params=["memory", "postgres", "dynamo"])
def store(request, monkeypatch):
    if request.param == "memory":
        yield MemoryStore()
    elif request.param == "postgres":
        s = _make_postgres()
        yield s
        s.close()
    else:
        monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        with mock_aws():
            ddb = boto3.resource("dynamodb")
            ddb.create_table(TableName="t", BillingMode="PAY_PER_REQUEST",
                             KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                                        {"AttributeName": "sk", "KeyType": "RANGE"}],
                             AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                                   {"AttributeName": "sk", "AttributeType": "S"}])
            yield DynamoStore("t", ddb)


def _session(group="G", expires=NOW + 3600, area="อารีย์") -> Session:
    return Session(session_id="s1", group_id=group, started_at=NOW, expires_at=expires, area=area)


# ---- idempotency ---------------------------------------------------------
def test_seen_event_first_false_then_true(store):
    assert store.seen_event("e1", NOW) is False
    assert store.seen_event("e1", NOW + 1) is True
    assert store.seen_event("e2", NOW) is False


def test_forget_event_allows_retry(store):
    assert store.seen_event("e1", NOW) is False
    store.forget_event("e1")
    assert store.seen_event("e1", NOW) is False  # SQS retry is processed again
    store.forget_event("never-seen")  # no error


def test_seen_event_ttl_expiry_with_injected_now(store):
    assert store.seen_event("e1", NOW) is False
    assert store.seen_event("e1", NOW + EVENT_TTL_S - 1) is True  # still inside the TTL
    assert store.seen_event("e1", NOW + EVENT_TTL_S + 1) is False  # expired -> claimable again
    assert store.seen_event("e1", NOW + EVENT_TTL_S + 2) is True  # and re-armed


# ---- sessions ------------------------------------------------------------
def test_session_roundtrip_overwrite_delete(store):
    assert store.get_session("G") is None
    store.put_session(_session())
    got = store.get_session("G")
    assert got is not None and got.area == "อารีย์" and got.expires_at == NOW + 3600
    store.put_session(_session(area="สยาม", expires=NOW + 7200))
    got = store.get_session("G")
    assert got.area == "สยาม" and got.expires_at == NOW + 7200
    store.delete_session("G")
    assert store.get_session("G") is None
    store.delete_session("G")  # idempotent


def test_sessions_are_isolated_per_group(store):
    store.put_session(_session("G1", area="a"))
    store.put_session(_session("G2", area="b"))
    assert store.get_session("G1").area == "a"
    store.delete_session("G1")
    assert store.get_session("G2").area == "b"


def test_session_thai_text_survives(store):
    s = _session(area="ทองหล่อ 🍜")
    store.put_session(s)
    assert store.get_session("G") == s


# ---- counters ------------------------------------------------------------
def test_counter_sequence_and_independent_keys(store):
    assert [store.incr("QUOTA#a", NOW) for _ in range(3)] == [1, 2, 3]
    assert store.incr("QUOTA#b", NOW) == 1


def test_counter_keeps_counting_inside_ttl(store):
    store.incr("QUOTA#a", NOW)
    assert store.incr("QUOTA#a", NOW + COUNTER_TTL_S - 1) == 2


# ---- concurrency ---------------------------------------------------------
def _require_real_concurrency(store) -> None:
    # moto executes in-process and is NOT atomic across threads (observed duplicate counter values);
    # real DynamoDB ADD / conditional puts are atomic server-side, so this can only be proven on AWS.
    if isinstance(store, DynamoStore):
        pytest.skip("moto is not thread-atomic; DynamoDB atomicity can only be verified on real AWS")


def _run_threads(n: int, fn) -> list:
    out: list = [None] * n
    errors: list = []
    barrier = threading.Barrier(n)

    def work(i: int) -> None:
        try:
            barrier.wait()
            out[i] = fn(i)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    return out


def test_incr_is_atomic_under_threads(store):
    _require_real_concurrency(store)
    n, per = 16, 10

    def hammer(_i):
        return [store.incr("QUOTA#race", NOW) for _ in range(per)]

    results = _run_threads(n, hammer)
    seen = sorted(v for r in results for v in r)
    assert seen == list(range(1, n * per + 1))  # no lost update, no duplicate value
    assert store.incr("QUOTA#race", NOW) == n * per + 1


def test_seen_event_has_exactly_one_winner_under_threads(store):
    _require_real_concurrency(store)
    results = _run_threads(16, lambda _i: store.seen_event("same-event", NOW))
    assert results.count(False) == 1 and results.count(True) == 15


# ---- postgres-only: explicit purge (DynamoDB TTL background deletion) ------
def test_postgres_purge_expired(store):
    if not hasattr(store, "purge_expired"):
        pytest.skip("purge is Postgres-only (DynamoDB deletes expired items itself)")
    store.seen_event("old", NOW)
    store.put_session(_session("G-old", expires=NOW + 10))
    store.put_session(_session("G-new", expires=NOW + 10_000))
    store.incr("QUOTA#old", NOW)
    assert store.purge_expired(NOW + 20) == 1  # only G-old; event/counter TTLs are 1-2 days
    assert store.get_session("G-old") is None and store.get_session("G-new") is not None
    assert store.purge_expired(NOW + COUNTER_TTL_S + 1) == 3  # event + counter + G-new


def test_postgres_migrate_is_idempotent():
    s = _make_postgres()
    s.put_session(_session())
    s.migrate()
    s.migrate()
    assert s.get_session("G") is not None  # re-running the schema keeps data
