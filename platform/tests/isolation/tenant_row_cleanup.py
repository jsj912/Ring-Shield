"""Snapshot and remove tenant rows created by an isolation test."""

from __future__ import annotations

from sqlalchemy import text


def snapshot_tenant_row_keys(engine, tenant_ids: tuple[int, ...]):
    with engine.connect() as connection:
        table_names = tuple(connection.execute(text("""
            SELECT DISTINCT c.table_name FROM information_schema.columns AS c
            JOIN information_schema.tables AS t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id'
              AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name
        """)).scalars())
        key_rows = connection.execute(text("""
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON kcu.constraint_schema = tc.constraint_schema
             AND kcu.constraint_name = tc.constraint_name
             AND kcu.table_name = tc.table_name
            WHERE tc.constraint_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.table_name, kcu.ordinal_position
        """)).all()
        key_columns: dict[str, list[str]] = {}
        for row in key_rows:
            key_columns.setdefault(row.table_name, []).append(row.column_name)

        quote = engine.dialect.identifier_preparer.quote
        snapshot = {}
        for table in table_names:
            columns = tuple(key_columns.get(table, ()))
            if not columns:
                raise AssertionError(f"tenant-scoped table {table} has no primary key")
            selected = ", ".join(quote(column) for column in columns)
            rows = connection.execute(text(
                f"SELECT {selected} FROM public.{quote(table)} "
                "WHERE tenant_id IN (:tenant_a, :tenant_b)"
            ), {"tenant_a": tenant_ids[0], "tenant_b": tenant_ids[1]}).all()
            snapshot[table] = (columns, {tuple(row) for row in rows})
    return snapshot


def delete_tenant_rows_added_since(
    engine, snapshot, tenant_ids: tuple[int, ...], *, exclude_tables: set[str] | None = None,
) -> None:
    """Delete only new tenant rows, respecting the platform's foreign-key order."""
    preferred_order = (
        "retrain_runs", "verdicts", "explanations", "audit_log", "rings", "drift_events",
        "edge_scores", "transactions", "accounts", "model_versions", "users",
    )
    excluded = exclude_tables or set()
    tables = [table for table in preferred_order if table in snapshot and table not in excluded]
    tables.extend(sorted(set(snapshot) - set(tables) - {"tenants"} - excluded))
    quote = engine.dialect.identifier_preparer.quote
    tenant_a, tenant_b = tenant_ids

    with engine.begin() as connection:
        for table in tables:
            columns, original_keys = snapshot[table]
            selected = ", ".join(["tenant_id", *(quote(column) for column in columns)])
            current_rows = connection.execute(text(
                f"SELECT {selected} FROM public.{quote(table)} "
                "WHERE tenant_id IN (:tenant_a, :tenant_b)"
            ), {"tenant_a": tenant_a, "tenant_b": tenant_b}).all()
            for row in current_rows:
                tenant_id, *key_values = row
                key = tuple(key_values)
                if key in original_keys:
                    continue
                clauses = ["tenant_id = :tenant_id"]
                parameters = {"tenant_id": tenant_id}
                for index, (column, value) in enumerate(zip(columns, key)):
                    if column == "tenant_id":
                        if value != tenant_id:
                            raise AssertionError(f"{table} primary key tenant does not match row tenant")
                        continue
                    parameter = f"key_{index}"
                    clauses.append(f"{quote(column)} = :{parameter}")
                    parameters[parameter] = value
                connection.execute(text(
                    f"DELETE FROM public.{quote(table)} WHERE {' AND '.join(clauses)}"
                ), parameters)
