"""Generic, idempotent schema sync — same pattern used successfully in the
Zagadat Capital system: db.create_all() only ever creates brand-new tables,
so this fills the gap for columns added to a model after the table already
exists in production. Every step is wrapped so one failure never blocks
the rest of startup."""
from sqlalchemy import inspect, text
from extensions import db


def _run(stmt, label):
    try:
        with db.engine.begin() as conn:
            conn.execute(text(stmt))
        print(f"[SCHEMA] {label}")
    except Exception as e:
        print(f"[SCHEMA] step failed ({label}): {e}")


def ensure_schema(schema_name=None):
    if db.engine.dialect.name == 'postgresql' and schema_name:
        _run(f'CREATE SCHEMA IF NOT EXISTS {schema_name}', f'ensure schema {schema_name} exists')

    insp = inspect(db.engine)
    existing_tables = set(insp.get_table_names(schema=schema_name))
    if not existing_tables:
        return  # brand-new database — db.create_all() defines everything fully

    prefix = f'{schema_name}.' if schema_name else ''
    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_cols = {c['name'] for c in insp.get_columns(table.name, schema=schema_name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            try:
                coltype = col.type.compile(dialect=db.engine.dialect)
            except Exception as e:
                print(f"[SCHEMA] Skipped {table.name}.{col.name} — couldn't compile column type: {e}")
                continue
            _run(f'ALTER TABLE {prefix}{table.name} ADD COLUMN {col.name} {coltype}',
                 f'{table.name}: added missing column {col.name}')
