# -*- coding: utf-8 -*-
"""真 PostgreSQL 连接与操作（不 mock、不用内存替代）。

连接来源（按优先级）：
  1. 环境变量 SLA3057_DSN
  2. 环境变量 DATABASE_URL
  3. 内嵌 PostgreSQL（pip 包 pgserver；Windows 与 Linux 都可）
     —— 数据目录放在临时目录下，进程退出即弃，不污染环境。

两个平台实测的都是真 PostgreSQL 16（不是模拟）：
  Windows  pgserver 自带 PostgreSQL 16.2
  Ubuntu   docker image postgres:16-alpine
"""
import os
import tempfile

import fixtures as F
import mv_sql
import schema
from sqlalchemy import create_engine, text


def _dsn():
    for k in ("SLA3057_DSN", "DATABASE_URL"):
        v = os.environ.get(k)
        if v:
            return v, "env:" + k
    import pgserver
    d = os.environ.get("SLA3057_PGDATA") or os.path.join(tempfile.gettempdir(), "pg3057")
    srv = pgserver.get_server(d)
    return srv.get_uri(), "pgserver(embedded PostgreSQL)"


def engine():
    dsn, how = _dsn()
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(dsn, future=True), how


def drop_all(eng):
    with eng.begin() as c:
        c.execute(text("DROP MATERIALIZED VIEW IF EXISTS %s CASCADE" % mv_sql.MV_NAME))
        c.execute(text("DROP FUNCTION IF EXISTS %s(timestamptz)" % mv_sql.REFRESH_FN))
    schema.Base.metadata.drop_all(eng)


def init_schema(eng, with_mv=True):
    """建表 + 建物化视图 + 建刷新函数（幂等：先清后建）。"""
    drop_all(eng)
    schema.Base.metadata.create_all(eng)
    if with_mv:
        with eng.begin() as c:
            c.execute(text(mv_sql.MV_SQL))
            for s in mv_sql.MV_INDEXES:
                c.execute(text(s))
            c.execute(text(mv_sql.REFRESH_SQL))


def load_fixtures(eng):
    """灌入虚构夹具（全部虚构，无真实个人信息）。"""
    runs = F.rows()
    pauses = F.pause_rows()
    idmap = {}
    with eng.begin() as c:
        for r in runs:
            rid = F._uid("run:" + r["run_no"])
            idmap[r["run_no"]] = rid
            c.execute(text("""
                INSERT INTO sop_step_runs
                  (id, org_id, site_id, template_id, version_no, step_key, run_no,
                   started_at, finished_at, due_at, created_at, updated_at, deleted_at)
                VALUES (:id, :org, :site, :tpl, :ver, :step, :run_no,
                        :started, :finished, :due, :now, :now, :deleted)
            """), {"id": rid, "org": F.ORG, "site": r["site_id"], "tpl": F.TPL1,
                   "ver": 1, "step": r["step_key"], "run_no": r["run_no"],
                   "started": r["started_at"], "finished": r["finished_at"],
                   "due": r["due_at"],
                   "now": "2026-10-01T00:00:00+08:00",
                   "deleted": "2026-10-08T00:00:00+08:00" if r["deleted"] else None})
        for p in pauses:
            c.execute(text("""
                INSERT INTO sop_step_pauses
                  (id, org_id, run_id, paused_at, resumed_at, reason,
                   created_at, updated_at, deleted_at)
                VALUES (:id, :org, :run, :pa, :re, '', :now, :now, NULL)
            """), {"id": F._uid("pause:%s:%d" % (p["run_no"], p["seq"])), "org": F.ORG,
                   "run": idmap[p["run_no"]], "pa": p["paused_at"], "re": p["resumed_at"],
                   "now": "2026-10-01T00:00:00+08:00"})
    return len(runs), len(pauses)


def refresh(eng, as_of):
    """调刷新函数（改参数表 + REFRESH MATERIALIZED VIEW），返回刷新后的行数。"""
    with eng.begin() as c:
        # 显式 ::timestamptz：psycopg2 传字符串时 PG 会当 unknown 类型，
        # 于是报 "function refresh_mv_sop_step_sla(unknown) does not exist"。
        row = c.execute(text("SELECT * FROM %s(CAST(:t AS timestamptz))" % mv_sql.REFRESH_FN),
                        {"t": as_of}).fetchone()
    return row


def rows_of_mv(eng):
    """读物化视图，转成与 pycalc.compute 同结构的 dict 列表。"""
    sql = """SELECT org_id::text, site_id::text, template_id::text, version_no,
                    step_key, month,
                    step_runs, overdue_runs, overdue_rate,
                    p50_minutes, p90_minutes, max_minutes, anomaly_count
               FROM %s
              ORDER BY step_key, month""" % mv_sql.MV_NAME
    out = []
    with eng.connect() as c:
        for r in c.execute(text(sql)):
            m = r._mapping
            out.append({
                "org_id": m["org_id"], "site_id": m["site_id"],
                "template_id": m["template_id"], "version_no": m["version_no"],
                "step_key": m["step_key"],
                "month": m["month"].strftime("%Y-%m"),
                "step_runs": m["step_runs"], "overdue_runs": m["overdue_runs"],
                "overdue_rate": (float(m["overdue_rate"]) if m["overdue_rate"] is not None else None),
                "p50_minutes": (float(m["p50_minutes"]) if m["p50_minutes"] is not None else None),
                "p90_minutes": (float(m["p90_minutes"]) if m["p90_minutes"] is not None else None),
                "max_minutes": (int(m["max_minutes"]) if m["max_minutes"] is not None else None),
                "anomaly_count": m["anomaly_count"],
            })
    return out


def pg_version(eng):
    with eng.connect() as c:
        return c.execute(text("SHOW server_version")).scalar()


def has_percentile_cont(eng):
    with eng.connect() as c:
        return c.execute(text(
            "SELECT count(*) FROM pg_proc WHERE proname='percentile_cont'")).scalar()
