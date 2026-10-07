"""DynamoDB single-table helpers for What If scenarios (see PLAN.md § 5).

Key layout:
    PK=SCEN#<id>  SK=META                -> scenario spec
    PK=SCEN#<id>  SK=RESULT#<model_ver>  -> cached simulation result (TTL)
    PK=SCEN#<id>  SK=STATS               -> view counter
    GSI1: GSI1PK=RACE#<season>#<round>, GSI1SK=<created_at>#<id>  -> recent scenarios per race
"""

from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from pitwall.config import get_settings

GSI1 = "GSI1"


@lru_cache
def get_resource():
    s = get_settings()
    kwargs = {"region_name": s.aws_region}
    if s.dynamodb_endpoint_url:
        kwargs["endpoint_url"] = s.dynamodb_endpoint_url
        kwargs["aws_access_key_id"] = s.aws_access_key_id
        kwargs["aws_secret_access_key"] = s.aws_secret_access_key
    return boto3.resource("dynamodb", **kwargs)


def get_table():
    return get_resource().Table(get_settings().pitwall_ddb_table)


def create_table(wait: bool = True):
    """Create the single table with GSI1 and TTL. Idempotent."""
    s = get_settings()
    client = get_resource().meta.client
    try:
        client.create_table(
            TableName=s.pitwall_ddb_table,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI1,
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
        return get_table()
    table = get_table()
    if wait:
        table.wait_until_exists()
    try:
        client.update_time_to_live(
            TableName=s.pitwall_ddb_table,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
    except ClientError as e:
        # DynamoDB Local returns ValidationException if TTL is already enabled
        if e.response["Error"]["Code"] not in ("ValidationException",):
            raise
    return table
