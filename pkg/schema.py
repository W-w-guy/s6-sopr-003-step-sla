# -*- coding: utf-8 -*-
"""SOP 步骤执行与暂停的 SQLAlchemy 模型（喂给 Alembic autogenerate）。

业务表统一含 id(UUID) / org_id / site_id / created_at / created_by / updated_at / deleted_at，
与本单【统一技术约定】一致；时间一律 timestamptz。
"""
import uuid

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Index, Integer,
                        Numeric, String, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _uuid():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class SopStepRun(Base):
    """一次步骤执行。finished_at 为空表示截至 as_of 仍未完成。"""
    __tablename__ = "sop_step_runs"

    id = _uuid()
    org_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    site_id = Column(UUID(as_uuid=True))
    template_id = Column(UUID(as_uuid=True), nullable=False)
    version_no = Column(Integer, nullable=False)
    step_key = Column(String(64), nullable=False)
    run_no = Column(String(32), nullable=False)      # 便于人工核对
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))     # NULL = 未完成
    due_at = Column(DateTime(timezone=True))          # NULL = 不计超时
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    created_by = Column(UUID(as_uuid=True))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    deleted_at = Column(DateTime(timezone=True))      # 软删除

    __table_args__ = (
        Index("ix_run_group", "org_id", "site_id", "template_id", "version_no", "step_key"),
        Index("ix_run_started", "started_at"),
    )


class SopStepPause(Base):
    """暂停区间：paused_at / resumed_at。resumed_at 为空表示到 as_of 仍在暂停中。"""
    __tablename__ = "sop_step_pauses"

    id = _uuid()
    org_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("sop_step_runs.id"), nullable=False, index=True)
    paused_at = Column(DateTime(timezone=True), nullable=False)
    resumed_at = Column(DateTime(timezone=True))      # NULL = 仍在暂停
    reason = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class SlaRefreshParam(Base):
    """单行参数表：物化视图从这里取 as_of。

    为什么需要它：物化视图定义里不能带运行时参数，而 AC2 要求「同一批数据用两个不同
    as_of 刷新」。所以物化视图 join 这张单行表取 as_of，刷新函数先改这里再 REFRESH。
    `id` 恒为 TRUE 且唯一约束，保证只有一行。
    """
    __tablename__ = "sla_refresh_param"

    id = Column(Boolean, primary_key=True, default=True)
    as_of = Column(DateTime(timezone=True), nullable=False)
    refreshed_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
