from eventhub.migrate import load_migrations, split_statements


def test_versions_are_contiguous_from_one():
    versions = [m.version for m in load_migrations()]
    assert versions
    assert versions == list(range(1, len(versions) + 1))


def test_every_migration_has_statements_and_a_checksum():
    for migration in load_migrations():
        assert migration.statements
        assert all(statement.strip() for statement in migration.statements)
        assert len(migration.checksum) == 64


def test_split_ignores_blank_chunks_and_trailing_semicolons():
    text = "CREATE TABLE a (id INT);\n-- split\n\n-- split\nCREATE TABLE b (id INT);\n"
    assert split_statements(text) == ("CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)")


def test_events_table_is_partitioned_and_deduplicated():
    sql = " ".join(s for m in load_migrations() for s in m.statements)
    assert "PARTITION BY RANGE COLUMNS (occurred_at)" in sql
    assert "uq_events_dedupe" in sql


def test_no_destructive_statements():
    sql = " ".join(s for m in load_migrations() for s in m.statements).upper()
    assert "DROP " not in sql
    assert "TRUNCATE" not in sql
