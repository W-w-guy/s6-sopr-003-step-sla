"""建 SOP 步骤执行与暂停表

Revision ID: 0001
Revises:
Create Date: 2026-11-19

口径：
- 时间一律 timestamptz；
- 业务表统一含 id(UUID) / org_id / site_id / created_at / created_by / updated_at / deleted_at；
- finished_at / resumed_at 允许为空（NULL = 截至 as_of 仍未结束）；
- due_at 允许为空（NULL = 不计超时，工单原文）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sop_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True)),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("step_key", sa.String(64), nullable=False),
        sa.Column("run_no", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_run_group", "sop_step_runs",
                    ["org_id", "site_id", "template_id", "version_no", "step_key"])
    op.create_index("ix_run_started", "sop_step_runs", ["started_at"])
    op.create_index("ix_sop_step_runs_org_id", "sop_step_runs", ["org_id"])

    op.create_table(
        "sop_step_pauses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("sop_step_runs.id"), nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resumed_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sop_step_pauses_org_id", "sop_step_pauses", ["org_id"])
    op.create_index("ix_sop_step_pauses_run_id", "sop_step_pauses", ["run_id"])

    op.create_table(
        "sla_refresh_param",
        sa.Column("id", sa.Boolean, primary_key=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id", name="ck_sla_refresh_param_single_row"),
    )


def downgrade() -> None:
    op.drop_table("sla_refresh_param")
    op.drop_table("sop_step_pauses")
    op.drop_table("sop_step_runs")
