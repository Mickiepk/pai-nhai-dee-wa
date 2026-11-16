"""DynamoDB store and worker handler against moto (no real AWS)."""

import json

import boto3
import pytest
from moto import mock_aws

from scripts.events import text_event
from session.models import Session
from store.dynamo import DynamoStore
from tests.fakes import make_engine


@pytest.fixture
def table(monkeypatch):
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


def test_dedup_conditional_write(table):
    assert table.seen_event("e1", 100) is False
    assert table.seen_event("e1", 101) is True
    assert table.seen_event("e1", 100 + 25 * 3600) is False  # TTL passed


def test_session_roundtrip_and_ttl(table):
    s = Session(session_id="s", group_id="G", started_at=0, expires_at=3600, area="อารีย์")
    table.put_session(s)
    item = table._table.get_item(Key={"pk": "GROUP#G", "sk": "SESSION#active"})["Item"]
    assert item["ttl"] == 3600
    assert table.get_session("G").area == "อารีย์"
    table.delete_session("G")
    assert table.get_session("G") is None


def test_counter(table):
    assert [table.incr("QUOTA#x", 0) for _ in range(3)] == [1, 2, 3]


def test_worker_handler_runs_engine(table, monkeypatch):
    import handlers.worker as worker

    engine, line, *_ = make_engine()
    engine.store = table
    monkeypatch.setattr(worker, "_engine", engine)
    ev = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    out = worker.handler({"Records": [{"messageId": "m1", "body": json.dumps(ev)}]}, None)
    assert out == {"batchItemFailures": []}
    assert table.get_session("G").area == "อารีย์" and len(line.replies) == 1
