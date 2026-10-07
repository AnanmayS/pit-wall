from pitwall.db.clickhouse import DDL_PATH, iter_statements


def test_ddl_parses_into_statements():
    stmts = list(iter_statements(DDL_PATH.read_text()))
    assert stmts, "ddl.sql should contain statements"
    for s in stmts:
        assert s.upper().startswith("CREATE"), s[:60]
        assert "IF NOT EXISTS" in s.upper(), "all DDL must be idempotent"
