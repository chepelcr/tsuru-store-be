"""
Pytest configuration for integration tests.

This module configures the test environment to use the same database connection
pattern as alembic migrations, ensuring consistency across the application.
"""
import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from app.configuration.database_connection import DatabaseConnection

# Load environment variables from .env file before running tests
load_dotenv()


@pytest.fixture(scope="session")
def db_engine():
    """
    Create a database engine for the test session using the same pattern as alembic.
    
    This uses DatabaseConnection._create_engine() which automatically resolves
    credentials from:
    1. Environment variables (DATABASE_HOST, DATABASE_PORT, etc.)
    2. AWS Secrets Manager (fallback when env vars not set)
    """
    engine = DatabaseConnection._create_engine()
    yield engine
    # Cleanup: close all connections
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """
    Create a database session for each test function.
    
    This provides a clean session for each test with automatic rollback
    to ensure test isolation.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    
    # Create a session bound to this connection
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=connection)
    session = Session()
    
    yield session
    
    # Rollback and cleanup
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="session")
def test_organization():
    """
    Get an existing organization and user from the database to use in tests.
    
    This avoids foreign key constraint violations by using real data
    that exists in the shared organizations and users tables.
    """
    with DatabaseConnection() as db:
        # Query for an existing organization (preferably a test/dev org)
        result = db.session.execute(text("""
            SELECT id, name 
            FROM organizations 
            WHERE name ILIKE '%corrella%' OR name ILIKE '%test%' OR name ILIKE '%dev%'
            LIMIT 1
        """))
        org = result.fetchone()
        
        if not org:
            # Fallback: get any organization
            result = db.session.execute(text("""
                SELECT id, name 
                FROM organizations 
                LIMIT 1
            """))
            org = result.fetchone()
        
        if not org:
            raise RuntimeError(
                "No organizations found in database. Please create at least one organization "
                "in the organizations table before running integration tests."
            )
        
        org_id = org[0]
        org_name = org[1]
        
        # Query for an existing user (any user will do for created_by fields)
        result = db.session.execute(text("""
            SELECT id, email 
            FROM users 
            LIMIT 1
        """))
        user = result.fetchone()
        
        if not user:
            raise RuntimeError(
                "No users found in database. Please create at least one user "
                "in the users table before running integration tests."
            )
        
        return {
            "id": org_id,
            "name": org_name,
            "user_id": user[0],
            "user_email": user[1]
        }


# ---------------------------------------------------------------------------
# Integration tests need a real database. Skip them when there isn't one.
# ---------------------------------------------------------------------------
#
# Without this they raised `RuntimeError: Database credentials not found` during
# fixture setup, which pytest reports as an ERROR — 113 of them. That is not a
# neutral inconvenience: errors scroll past the failures that matter and make
# `pytest tests` useless as a signal, which is part of why the branch and
# terminal handler suites sat broken for so long without anyone noticing.
#
# A skip says "not run here"; an error says "something is wrong". Only one of
# those is true when you simply have no database configured.

_DB_AVAILABLE: "bool | None" = None


def _database_available() -> bool:
    """Probe once per session whether a database is actually reachable."""
    global _DB_AVAILABLE
    if _DB_AVAILABLE is None:
        try:
            engine = DatabaseConnection._create_engine()
            with engine.connect():
                pass
            engine.dispose()
            _DB_AVAILABLE = True
        except Exception:
            _DB_AVAILABLE = False
    return _DB_AVAILABLE


def pytest_collection_modifyitems(config, items):
    """Skip tests marked `integration` when the app's database is unreachable.

    Matched with `get_closest_marker`, deliberately — NOT `"integration" in
    item.keywords`. Keywords include the node's path components, so that check
    also matched every test under `tests/integration/`, which sources its own
    disposable schema from STORE_BRANCH_SYNC_TEST_DATABASE_URL and has nothing
    to do with the app connection. It silently skipped two tests that need no
    database at all.
    """
    if _database_available():
        return
    skip = pytest.mark.skip(
        reason=(
            "no database reachable — set DATABASE_HOST/PORT/USERNAME/PASSWORD/DBNAME "
            "or provide AWS credentials for the SSM/Secrets Manager fallback"
        )
    )
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip)
