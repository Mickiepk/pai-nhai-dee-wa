"""DynamoDB single-table store. Keys: pk / sk, TTL attribute: ttl.

Items:
  GROUP#<id>        / SESSION#active   extracted session state (JSON), TTL = session end
  EVENT#<eventId>   / SEEN             idempotency, TTL 1 day
  QUOTA#<name>#<d>  / COUNT            daily counters, TTL 2 days
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from session.models import Session
from store.base import COUNTER_TTL_S, EVENT_TTL_S


class DynamoStore:
    def __init__(self, table_name: str, resource: Any | None = None):
        self._table = (resource or boto3.resource("dynamodb")).Table(table_name)

    def seen_event(self, event_id: str, now: int) -> bool:
        try:
            self._table.put_item(
                Item={"pk": f"EVENT#{event_id}", "sk": "SEEN", "ttl": now + EVENT_TTL_S},
                ConditionExpression="attribute_not_exists(pk) OR #t < :now",
                ExpressionAttributeNames={"#t": "ttl"},
                ExpressionAttributeValues={":now": now},
            )
            return False
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return True
            raise

    def forget_event(self, event_id: str) -> None:
        self._table.delete_item(Key={"pk": f"EVENT#{event_id}", "sk": "SEEN"})

    def get_session(self, group_id: str) -> Session | None:
        item = self._table.get_item(Key={"pk": f"GROUP#{group_id}", "sk": "SESSION#active"}).get("Item")
        return Session.model_validate_json(item["data"]) if item else None

    def put_session(self, session: Session) -> None:
        self._table.put_item(Item={
            "pk": f"GROUP#{session.group_id}", "sk": "SESSION#active",
            "data": session.model_dump_json(), "ttl": session.expires_at,
        })

    def delete_session(self, group_id: str) -> None:
        self._table.delete_item(Key={"pk": f"GROUP#{group_id}", "sk": "SESSION#active"})

    def incr(self, key: str, now: int) -> int:
        resp = self._table.update_item(
            Key={"pk": key, "sk": "COUNT"},
            UpdateExpression="ADD #v :one SET #t = if_not_exists(#t, :ttl)",
            ExpressionAttributeNames={"#v": "value", "#t": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": now + COUNTER_TTL_S},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["value"])
