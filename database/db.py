"""
Database Connection and Session Management
Configures async SQLAlchemy engine, provides session context managers,
and handles database initialization for SQLite and PostgreSQL.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from config import settings
from database.models import Base
from utils.logger import logger
from utils.security import InputValidationError

# Build async engine
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# Async session factory
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing an isolated database session."""
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(f"Database session error: {exc}", exc_info=True)
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Creates all database tables and ensures schema migrations."""
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def migrate_sqlite(connection):
            from sqlalchemy import inspect, text
            inspector = inspect(connection)
            if "users" in inspector.get_table_names():
                existing_columns = {col["name"] for col in inspector.get_columns("users")}
                columns_to_add = [
                    ("violation_count", "INTEGER DEFAULT 0"),
                    ("restricted_until", "DATETIME"),
                    ("restriction_reason", "TEXT"),
                    ("ban_reason", "TEXT"),
                ]
                for col_name, col_type in columns_to_add:
                    if col_name not in existing_columns:
                        logger.info(f"Adding missing column {col_name} to users table...")
                        
                        # Enhanced security validation
                        # Validate column name to prevent SQL injection
                        if not col_name.replace('_', '').isalnum():
                            raise InputValidationError(f"Invalid column name: {col_name}")
                        
                        # Validate column type
                        if not isinstance(col_type, str) or not col_type.isupper():
                            raise InputValidationError(f"Invalid column type: {col_type}")
                        
                        # Use parameterized query with safe column names
                        safe_query = text("ALTER TABLE users ADD COLUMN :col_name :col_type")
                        connection.execute(safe_query, {"col_name": col_name, "col_type": col_type})

        await conn.run_sync(migrate_sqlite)
    logger.info("Database schema initialized successfully.")


async def close_db() -> None:
    """Disposes engine connections gracefully on shutdown."""
    logger.info("Closing database engine...")
    await engine.dispose()
    logger.info("Database engine closed.")
