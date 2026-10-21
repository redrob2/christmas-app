"""Copy everything from another database into this app's database.

Typical use - moving from the old docker compose setup (PostgreSQL) to the
single container's SQLite file:

    flask --app run:app copy-database --source postgresql://user:pass@host:5432/dbname

The source is only read, never changed. The target (this app's database) is
emptied first, so run it on a fresh install. Row IDs are kept, so links in
old emails keep working, and the notification keys come along too.
"""
import sys

import click
from sqlalchemy import MetaData, create_engine, func, inspect, select, text

from app import add_missing_columns, db

BATCH = 500


def copy_database(source_url, echo=print):
    """Returns {table: (source_rows, copied_rows)}. Raises on any failure (nothing half-done
    is left behind: the target is written in one transaction)."""
    from app import models  # noqa: F401  (register every table)

    source = create_engine(source_url)
    source_tables = set(inspect(source).get_table_names())
    if 'users' not in source_tables:
        raise click.ClickException("The source doesn't look like this app's database (no users table).")

    # Read the source's actual columns: it may be an older version with fewer columns
    reflected = MetaData()
    reflected.reflect(bind=source, only=[t.name for t in db.metadata.sorted_tables if t.name in source_tables])

    target = db.engine
    tables = db.metadata.sorted_tables      # parents before children
    results = {}
    with source.connect() as src, target.begin() as dst:
        if target.dialect.name == 'sqlite':
            dst.execute(text('PRAGMA defer_foreign_keys=ON'))   # self-references (users.managed_by_id)
        for table in reversed(tables):
            dst.execute(table.delete())

        for table in tables:
            if table.name not in source_tables:
                echo(f'  {table.name:<28} (not in the source - left empty)')
                results[table.name] = (0, 0)
                continue
            src_table = reflected.tables[table.name]
            columns = [c.name for c in table.columns if c.name in src_table.c]
            # Self-references are filled in after all rows exist
            self_refs = [fk.parent.name for fk in table.foreign_keys
                         if fk.column.table is table and fk.parent.name in columns]
            order = src_table.c[table.primary_key.columns.values()[0].name] if table.primary_key else None
            query = select(*[src_table.c[c] for c in columns])
            if order is not None:
                query = query.order_by(order)

            count, links = 0, []
            result = src.execute(query)
            while True:
                rows = result.fetchmany(BATCH)
                if not rows:
                    break
                batch = []
                for row in rows:
                    data = dict(zip(columns, row))
                    for col in self_refs:
                        if data[col] is not None:
                            links.append((data[table.primary_key.columns.values()[0].name], col, data[col]))
                            data[col] = None
                    batch.append(data)
                dst.execute(table.insert(), batch)
                count += len(batch)
            pk = table.primary_key.columns.values()[0] if table.primary_key else None
            for row_id, col, value in links:
                dst.execute(table.update().where(pk == row_id).values({col: value}))

            src_count = src.execute(select(func.count()).select_from(src_table)).scalar()
            dst_count = dst.execute(select(func.count()).select_from(table)).scalar()
            results[table.name] = (src_count, dst_count)
            echo(f'  {table.name:<28} {dst_count:>6} rows')
            if src_count != dst_count:
                raise click.ClickException(f'{table.name}: source has {src_count} rows but {dst_count} were copied')

        if target.dialect.name == 'postgresql':
            # new rows must continue after the copied IDs
            for table in tables:
                pk = table.primary_key.columns.values()[0] if table.primary_key else None
                if pk is not None and pk.autoincrement and isinstance(pk.type, db.Integer):
                    dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                        f"COALESCE((SELECT MAX({pk.name}) FROM \"{table.name}\"), 1))"))
    source.dispose()
    return results


def register_cli(app):
    @app.cli.command('copy-database')
    @click.option('--source', required=True, envvar='COPY_FROM',
                  help='Database to copy from, e.g. postgresql://user:password@host:5432/dbname')
    @click.option('--yes', is_flag=True, help="Don't ask before replacing this app's data.")
    def copy_database_command(source, yes):
        """Copy all data from SOURCE into this app's database (replacing what's there)."""
        from app.models import ChristmasEvent, User
        target_url = db.engine.url.render_as_string(hide_password=True)
        click.echo(f'From: {create_engine(source).url.render_as_string(hide_password=True)}')
        click.echo(f'To:   {target_url}')
        existing = User.query.count() + ChristmasEvent.query.count()
        if existing and not yes:
            click.confirm(f"This app's database already has {User.query.count()} people and "
                          f'{ChristmasEvent.query.count()} events. Replace ALL of it?', abort=True)
        db.session.remove()
        results = copy_database(source, echo=click.echo)
        # Bring the copied data up to this version (adds anything an older source lacked)
        add_missing_columns()
        from app.models import AppSettings
        settings = AppSettings.query.first()
        if settings and settings.setup_code and User.query.filter_by(is_admin=True).first():
            settings.setup_code = None
            db.session.commit()
        total = sum(copied for _, copied in results.values())
        click.echo(f'Done: {total} rows copied. {User.query.count()} people, '
                   f'{ChristmasEvent.query.count()} events.')
        click.echo('Photos are not in the database - map the old data folder (uploads/) to /app/data.')
