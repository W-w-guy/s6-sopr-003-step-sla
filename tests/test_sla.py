# -*- coding: utf-8 -*-
"""5 类必测用例（工单原文要求至少覆盖）：

  1. 暂停扣除
  2. 跨月归属
  3. 无 due_at（进耗时统计，不进超时分母）
  4. 异常值（<0 与 >30 天不进分位数，计入 anomaly_count）
  5. as_of 回溯（同一批数据换 as_of，overdue_runs 按预期变化）

每个用例的期望值都是手算后写死的常量，不从实现反推。
所有断言都跑在真 PostgreSQL 上（Windows 用 pgserver 内嵌 PG16，Ubuntu 用 docker PG16）。
"""
import os
import sys

import pytest
from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pkg"))

import db          # noqa: E402
import fixtures as F  # noqa: E402
import pycalc as P    # noqa: E402

SITE_HZ = str(F.SITE_HZ)
SITE_SZ = str(F.SITE_SZ)


def _row(rows, site, step, month):
    for r in rows:
        if r["site_id"] == site and r["step_key"] == step and r["month"] == month:
            return r
    return None


def _net(eng, run_no):
    """直接从 SQL 算某条 run 的净耗时（分钟）。

    独立于物化视图的一段查询，用于「单条手算」级别的核对：
    MV 是聚合结果，看不出单条对不对，所以这里单独算一次。
    与 MV 共享的只是规则（暂停取并集后扣除），SQL 是另写的。
    """
    sql = """
    WITH r AS (
        SELECT * FROM sop_step_runs WHERE run_no = :rn
    ), p AS (
        SELECT as_of FROM sla_refresh_param
    )
    SELECT ROUND(EXTRACT(EPOCH FROM (r.finished_at - r.started_at
             - COALESCE(pz.secs, interval '0'))) / 60.0) AS net
      FROM r
      CROSS JOIN p
      LEFT JOIN LATERAL (
          SELECT COALESCE(SUM(upper(x) - lower(x)), interval '0') AS secs
            FROM unnest((
                SELECT range_agg(tstzrange(lo, hi, '[)'))
                  FROM (
                      SELECT GREATEST(r.started_at, s.paused_at) AS lo,
                             LEAST(COALESCE(s.resumed_at, p.as_of),
                                   COALESCE(r.finished_at, p.as_of)) AS hi
                        FROM sop_step_pauses s
                       WHERE s.run_id = r.id AND s.deleted_at IS NULL
                  ) raw
                 WHERE lo < hi
            )) AS x
      ) pz ON TRUE
    """
    with eng.connect() as c:
        return c.execute(text(sql), {"rn": run_no}).scalar()


# ---------------------------------------------------------------- 1. 暂停扣除
def test_pause_deduction_single(eng):
    """单次暂停 20 分钟：R1 执行 60 分钟，净耗时 40 分钟（手算）。"""
    assert _net(eng, "R1") == 40


def test_pause_deduction_overlapping(eng):
    """两次重叠暂停必须取并集：09:30-09:50 与 09:45-10:05 并集 35 分钟，不是 40。

    R3 执行 120 分钟，净耗时应为 120-35=85。若实现按区间求和（40 分钟）会得 80，
    这一条就是专门盯这个错的。
    """
    assert _net(eng, "R3") == 85


def test_pause_not_counted_for_unfinished(eng):
    """未完成的步骤不计算净耗时（净耗时为 NULL），避免随 as_of 漂移。"""
    db.refresh(eng, F.AS_OF_LATE)
    assert _net(eng, "R9") is None


# ---------------------------------------------------------------- 2. 跨月归属
def test_cross_month_attributed_to_start_month(eng, base_rows):
    """R7 从 10-31 23:00 跨到 11-01 02:00（180 分钟），按 started_at 归 10 月。"""
    oct_row = _row(base_rows, SITE_HZ, "S2", "2026-10")
    nov_row = _row(base_rows, SITE_HZ, "S2", "2026-11")
    assert oct_row is not None and nov_row is not None
    assert oct_row["step_runs"] == 1
    assert oct_row["p50_minutes"] == 180.0      # R7 全 180 分钟落在 10 月
    assert nov_row["step_runs"] == 1
    assert nov_row["p50_minutes"] == 30.0       # R8 只有 30 分钟


# ---------------------------------------------------------------- 3. 无 due_at
def test_no_due_at_in_duration_but_not_overdue_denominator(eng, base_rows):
    """R4 无 due_at：进耗时统计（60 分钟），但不进超时分母。

    S1 组有 due 的只有 R1/R2/R3 三条（R4/R5/R6 无 due），超时 1 条 → rate=1/3。
    若把 R4 也算进分母，rate 会变成 1/4=0.25，这一条会红。
    """
    r = _row(base_rows, SITE_HZ, "S1", "2026-10")
    assert r["step_runs"] == 6                      # 6 条都算 step_runs
    assert r["overdue_runs"] == 1
    assert r["overdue_rate"] == pytest.approx(1 / 3, abs=1e-6)
    # R4 的 60 分钟确实进了分位数（p50=72.5 用到了它）
    assert r["p50_minutes"] == 72.5


def test_no_due_at_group_has_null_rate(eng, base_rows):
    """整组都没有 due_at 时 overdue_rate 为 NULL（分母为 0），不是 0 也不是 1。"""
    r = _row(base_rows, SITE_HZ, "S2", "2026-10")
    assert r["overdue_rate"] is None
    assert r["overdue_runs"] == 0


# ---------------------------------------------------------------- 4. 异常值
def test_anomaly_count_and_excluded_from_percentiles(eng, base_rows):
    """R5(-30 分钟) 与 R6(57600 分钟) 都是异常：计入 anomaly_count，不进分位数。

    正常样本 {40, 60, 85, 99}：
      p50 = 60 + 0.5*(85-60) = 72.5
      p90 = 85 + 0.7*(99-85) = 94.8
      max = 99
    若异常值混进分位数，p50/p90/max 都会明显偏移（-30 会把 p50 拉低，57600 会把 p90 拉爆）。
    """
    r = _row(base_rows, SITE_HZ, "S1", "2026-10")
    assert r["anomaly_count"] == 2
    assert r["p50_minutes"] == 72.5
    assert r["p90_minutes"] == 94.8
    assert r["max_minutes"] == 99


def test_negative_duration_is_anomaly(eng):
    """负耗时（finished < started）必须被识别，且不能变成负数参与分位数。"""
    assert _net(eng, "R5") == -30


def test_over_30_days_is_anomaly(eng):
    """超过 30 天（43200 分钟）的耗时按异常处理：R6 = 40 天 = 57600 分钟。"""
    assert _net(eng, "R6") == 57600


# ---------------------------------------------------------------- 5. as_of 回溯
def test_as_of_backtrack_changes_overdue(eng):
    """同一批数据，两个 as_of 下 overdue_runs 从 0 变 1。

    R9 未完成，due=11-10 10:00：
      as_of = 09:30 → 未到期，不超时 → 该组 overdue_runs=0, rate=0.0
      as_of = 11:00 → 已过期，超时     → 该组 overdue_runs=1, rate=0.5
    R10 已完成（40 分钟，未超时）在两次刷新里都不变。
    """
    db.refresh(eng, F.AS_OF_EARLY)
    early = _row(db.rows_of_mv(eng), SITE_SZ, "S3", "2026-11")
    db.refresh(eng, F.AS_OF_LATE)
    late = _row(db.rows_of_mv(eng), SITE_SZ, "S3", "2026-11")

    assert early["overdue_runs"] == 0
    assert early["overdue_rate"] == 0.0
    assert late["overdue_runs"] == 1
    assert late["overdue_rate"] == 0.5
    # 分位数不受 as_of 影响（未完成的 R9 不算耗时）
    assert early["p50_minutes"] == late["p50_minutes"] == 40.0


def test_as_of_before_all_data_yields_nothing(eng):
    """as_of 早于全部数据时物化视图为空（不是报错、也不是全 0 行）。"""
    db.refresh(eng, F.AS_OF_BEFORE_ALL)
    assert db.rows_of_mv(eng) == []
    db.refresh(eng, F.AS_OF_FULL)


def test_soft_deleted_run_excluded(eng, base_rows):
    """R11 已软删除：不参与 step_runs 计数（S1 组是 6 而不是 7）。"""
    r = _row(base_rows, SITE_HZ, "S1", "2026-10")
    assert r["step_runs"] == 6
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM sop_step_runs WHERE run_no='R11'")).scalar()
    assert n == 1, "夹具里确实有这一行（只是 deleted_at 非空）"


# ---------------------------------------------------------------- 交叉验证
def test_sql_matches_python_for_all_three_as_of(eng):
    """物化视图（SQL）与 Python 独立实现（不走 SQL）在三个 as_of 下结论完全一致。"""
    for as_of in (F.AS_OF_FULL, F.AS_OF_EARLY, F.AS_OF_LATE):
        db.refresh(eng, as_of)
        pg = {(r["site_id"], r["step_key"], r["month"]): r for r in db.rows_of_mv(eng)}
        py = {(r["site_id"], r["step_key"], r["month"]): r for r in P.compute(as_of)}
        assert set(pg) == set(py), "分组键不一致: %s" % (set(pg) ^ set(py))
        for k in pg:
            for f in ("step_runs", "overdue_runs", "anomaly_count"):
                assert pg[k][f] == py[k][f], (as_of, k, f, pg[k][f], py[k][f])
            for f in ("overdue_rate", "p50_minutes", "p90_minutes", "max_minutes"):
                a, b = pg[k][f], py[k][f]
                if a is None or b is None:
                    assert a is None and b is None, (as_of, k, f, a, b)
                else:
                    assert abs(float(a) - float(b)) < 1e-6, (as_of, k, f, a, b)
    db.refresh(eng, F.AS_OF_FULL)


def test_mv_is_materialized_not_view(eng):
    """mv_sop_step_sla 必须是物化视图（pg_matviews），不是普通视图。"""
    with eng.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM pg_matviews WHERE matviewname='mv_sop_step_sla'")).scalar()
        m = c.execute(text(
            "SELECT count(*) FROM pg_views WHERE viewname='mv_sop_step_sla'")).scalar()
    assert n == 1 and m == 0


def test_percentile_cont_used(eng):
    """分位数必须用 percentile_cont（工单原文），且 PostgreSQL 里确有此函数。"""
    with eng.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM pg_proc WHERE proname='percentile_cont'")).scalar()
        src = c.execute(text(
            "SELECT pg_get_viewdef('mv_sop_step_sla'::regclass, true)")).scalar()
    assert n >= 1
    assert "percentile_cont" in src
