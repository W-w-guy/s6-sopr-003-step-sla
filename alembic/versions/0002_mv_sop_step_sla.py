"""建物化视图 mv_sop_step_sla 与刷新函数

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19

为什么不交给 autogenerate：物化视图、聚合里的 FILTER、percentile_cont、
plpgsql 函数都不在 SQLAlchemy 的 autogenerate 能力范围内，必须手写 DDL。
SQL 正文不在这里重复，统一从 pkg/mv_sql.py 取（单一真相源，
checks 里会断言迁移里执行的 SQL 与 pkg/mv_sql.py 的内容一致）。
"""
import os
import sys

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))     # 包根
sys.path.insert(0, os.path.join(ROOT, "pkg"))

import mv_sql  # noqa: E402


def upgrade() -> None:
    op.execute(mv_sql.MV_SQL)
    for idx in mv_sql.MV_INDEXES:
        op.execute(idx)
    op.execute(mv_sql.REFRESH_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS %s(timestamptz)" % mv_sql.REFRESH_FN)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS %s" % mv_sql.MV_NAME)
