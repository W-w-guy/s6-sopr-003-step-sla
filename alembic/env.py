# -*- coding: utf-8 -*-
"""Alembic 环境：连接串从运行环境取，不硬编码。

优先级：SLA3057_DSN → DATABASE_URL → 内嵌 pgserver（见 pkg/db.py）。
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pkg"))

import db as app_db          # noqa: E402
import schema                # noqa: E402

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = schema.Base.metadata


def _url():
    dsn, _how = app_db._dsn()
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+psycopg2://", 1)
    return dsn


def run_migrations_offline():
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    from sqlalchemy import create_engine
    connectable = create_engine(_url(), poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
