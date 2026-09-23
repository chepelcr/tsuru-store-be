import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool

from alembic import context
from app.configuration.database_connection import DatabaseConnection

load_dotenv()

config = context.config

# Use the same engine as the app
engine = DatabaseConnection._create_engine()
config.set_main_option("sqlalchemy.url", str(engine.url))

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect them
from app.models import Base  # noqa: E402

target_metadata = Base.metadata

# Only manage tables that belong to THIS app — ignore tables from other projects
# sharing the same database.
# `countries` is a read-only mirror of data-be's catalog (app/models/country.py):
# mapped so a phone's dialing code resolves from the DB, never migrated here.
DATA_BE_OWNED_TABLES = {"countries"}
OUR_TABLES = set(target_metadata.tables.keys()) - DATA_BE_OWNED_TABLES

# Tables shared with BeautyMarket — we only ADD columns/indexes, never drop existing ones.
SHARED_TABLES = {"organizations", "products", "categories"}


def include_name(name, type_, parent_names):
    if type_ == "table":
        return name in OUR_TABLES
    # Always include indexes/constraints that belong to our tables
    return True


def _get_table_name(object_):
    """Extract table name from various alembic object types."""
    if hasattr(object_, "table"):
        t = object_.table
        return t.name if hasattr(t, "name") else str(t)
    if hasattr(object_, "parent") and hasattr(object_.parent, "name"):
        return object_.parent.name
    return None


def include_object(object_, name, type_, reflected, compare_to):
    """Prevent alembic from modifying existing objects on shared BeautyMarket tables.

    For shared tables we only allow ADDING new columns and indexes.
    All other changes (drops, alters, constraint changes) are blocked.
    """
    table_name = _get_table_name(object_)
    if name in DATA_BE_OWNED_TABLES or table_name in DATA_BE_OWNED_TABLES:
        # Mapped read-only; data-be owns and migrates it.
        return False

    if table_name in SHARED_TABLES:
        if reflected and compare_to is None:
            # Object exists in DB but not in model → would be dropped. Block it.
            return False
        if not reflected and compare_to is None:
            # Object exists in model but not in DB → new addition. Allow it.
            return True
        if reflected and compare_to is not None:
            # Object exists in both → would be altered. Block changes on shared tables.
            return False

    # For unique_constraint and foreign_key_constraint on shared tables
    if type_ in ("unique_constraint", "foreign_key_constraint"):
        tname = None
        if hasattr(object_, "table") and object_.table is not None:
            tname = object_.table.name if hasattr(object_.table, "name") else str(object_.table)
        if tname in SHARED_TABLES:
            if reflected and compare_to is None:
                return False
            if reflected and compare_to is not None:
                return False

    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
