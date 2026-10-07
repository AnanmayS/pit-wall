import pytest

pytestmark = pytest.mark.integration


def test_create_table_and_roundtrip():
    from pitwall.db.dynamo import create_table, get_table

    create_table()
    t = get_table()
    t.put_item(Item={"PK": "SCEN#test", "SK": "META", "race": "1999-99"})
    got = t.get_item(Key={"PK": "SCEN#test", "SK": "META"})["Item"]
    assert got["race"] == "1999-99"
    t.delete_item(Key={"PK": "SCEN#test", "SK": "META"})
