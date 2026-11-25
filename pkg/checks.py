# -*- coding: utf-8 -*-
"""本单 30 条 AC 断言。全部跑在**真 PostgreSQL** 上（不 mock、不用内存替代）。

期望值硬编码在本文件里（与 engine.EXPECT_* 独立写一遍），不与被测对象互推。
"""
import os
import re
import subprocess
import sys

import db
import engine as E
import fixtures as F
import mv_sql
import pycalc as P
from kitlib.checks import check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECT_P50 = 72.5
EXPECT_P90 = 94.8
EXPECT_MAX = 99
EXPECT_ANOM = 2
EXPECT_S1_RUNS = 6
EXPECT_S1_OVERDUE = 1
EXPECT_S1_RATE = 0.333333
EXPECT_G2 = {"2026-10": 180.0, "2026-11": 30.0}
EXPECT_NORMAL = [40, 60, 85, 99]
SITE_HZ = str(F.SITE_HZ)
SITE_SZ = str(F.SITE_SZ)


def _row(rows, site, step, month):
    for r in rows:
        if r["site_id"] == site and r["step_key"] == step and r["month"] == month:
            return r
    return None


def _pytest_counts():
    """真跑 pytest（子进程），返回 (rc, 通过数, 失败数, 用例名列表, 原始输出)。

    用 -v 而不是 -q：pytest 9 里 `-q` 只打进度点，不输出 "N passed" 汇总行，
    解析会拿到 0（实测踩到）。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-v", "--tb=short",
                        "-p", "no:cacheprovider"],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    names = re.findall(r"::(\w+)\s+(?:PASSED|FAILED|ERROR)", out)
    passed = len(re.findall(r"::(\w+)\s+PASSED", out))
    failed = len(re.findall(r"::(\w+)\s+(?:FAILED|ERROR)", out))
    return r.returncode, passed, failed, names, out


def main():
    # ---------- 环境与迁移 ----------
    eng, how = db.engine()
    check("V01 连的是真 PostgreSQL（不是内存库/模拟），版本 >= 16",
          db.pg_version(eng).startswith("16"),
          "PG %s，连接方式 %s" % (db.pg_version(eng), how))

    # Alembic 真跑 upgrade head（不是只检查文件存在）
    from alembic import command
    from alembic.config import Config
    os.environ.setdefault("SLA3057_DSN", db._dsn()[0])
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))

    db.drop_all(eng)
    from sqlalchemy import text as _t
    with eng.begin() as c:
        c.execute(_t("DROP TABLE IF EXISTS alembic_version"))
    ok_mig = True
    mig_err = ""
    try:
        command.upgrade(cfg, "head")
    except Exception as e:
        ok_mig = False
        mig_err = "%s: %s" % (type(e).__name__, e)
    with eng.connect() as c:
        ver = c.execute(_t("SELECT version_num FROM alembic_version")).scalar()
    check("V02 Alembic 迁移能真跑 upgrade head（不是只检查文件存在）",
          ok_mig and ver == "0002", "alembic_version=%s err=%s" % (ver, mig_err))

    # downgrade 也要能跑（迁移必须可回滚）
    ok_down = True
    try:
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    except Exception as e:
        ok_down = False
        mig_err = "%s: %s" % (type(e).__name__, e)
    check("V03 Alembic downgrade base 后再 upgrade head 也能跑通（可回滚）",
          ok_down, "err=%s" % (mig_err or "无"))

    db.load_fixtures(eng)
    db.refresh(eng, F.AS_OF_FULL)
    rows = db.rows_of_mv(eng)

    # ---------- 对象形态 ----------
    with eng.connect() as c:
        mat = c.execute(_t("SELECT count(*) FROM pg_matviews WHERE matviewname='mv_sop_step_sla'")).scalar()
        vie = c.execute(_t("SELECT count(*) FROM pg_views WHERE viewname='mv_sop_step_sla'")).scalar()
        fn = c.execute(_t("SELECT count(*) FROM pg_proc WHERE proname='refresh_mv_sop_step_sla'")).scalar()
        pc = c.execute(_t("SELECT count(*) FROM pg_proc WHERE proname='percentile_cont'")).scalar()
        viewdef = c.execute(_t("SELECT pg_get_viewdef('mv_sop_step_sla'::regclass, true)")).scalar()
    check("V04 mv_sop_step_sla 是**物化视图**（pg_matviews 有、pg_views 没有）",
          mat == 1 and vie == 0, "pg_matviews=%d pg_views=%d" % (mat, vie))
    check("V05 刷新函数 refresh_mv_sop_step_sla 存在于数据库",
          fn == 1, "pg_proc 命中 %d" % fn)
    check("V06 物化视图定义里真的用了 percentile_cont（工单原文要求）",
          "percentile_cont" in (viewdef or "") and pc >= 1,
          "viewdef 含 percentile_cont=%s；库里函数数 %d"
          % ("percentile_cont" in (viewdef or ""), pc))

    # SQLAlchemy 的 inspect().get_columns() 对物化视图不可用（MV 不在 metadata 里），
    # 直接从 pg_attribute 读列名与顺序。
    from sqlalchemy import text as _ta
    with eng.connect() as c:
        cols = [r[0] for r in c.execute(_ta("""
            SELECT a.attname
              FROM pg_attribute a
              JOIN pg_class c ON c.oid = a.attrelid
             WHERE c.relname = 'mv_sop_step_sla'
               AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY a.attnum
        """)).fetchall()]
    check("V07 物化视图列与工单原文点名的 13 列逐字一致",
          cols == E.EXPECT_MV_COLUMNS,
          "实测 %s" % cols)

    # ---------- AC1：pytest 通过、5 类用例各至少 1 个 ----------
    rc, passed, failed, names, out = _pytest_counts()
    check("V08 AC1 pytest 真跑通过（rc=0，失败 0）",
          rc == 0 and failed == 0 and passed >= 15,
          "rc=%d passed=%d failed=%d" % (rc, passed, failed))

    required = {
        "暂停扣除": ["test_pause_deduction_single", "test_pause_deduction_overlapping"],
        "跨月归属": ["test_cross_month_attributed_to_start_month"],
        "无 due_at": ["test_no_due_at_in_duration_but_not_overdue_denominator",
                      "test_no_due_at_group_has_null_rate"],
        "异常值": ["test_anomaly_count_and_excluded_from_percentiles",
                   "test_negative_duration_is_anomaly", "test_over_30_days_is_anomaly"],
        "as_of 回溯": ["test_as_of_backtrack_changes_overdue",
                       "test_as_of_before_all_data_yields_nothing"],
    }
    miss = {k: [n for n in v if n not in names] for k, v in required.items()}
    miss = {k: v for k, v in miss.items() if v}
    check("V09 AC1 工单点名的 5 类用例各至少 1 个，且全部真实存在于测试文件里",
          not miss, "缺 %s" % (miss or "无") + "；共收集 %d 个用例" % len(names))

    # ---------- AC1：断言值与手算一致 ----------
    s1 = _row(rows, SITE_HZ, "S1", "2026-10")
    check("V10 AC1 S1 组 step_runs=6（R1~R6；R11 软删除不计）",
          s1["step_runs"] == EXPECT_S1_RUNS, "实测 %s" % s1["step_runs"])
    check("V11 AC1 S1 组 p50_minutes=%.1f（正常样本 40/60/85/99 的线性插值）" % EXPECT_P50,
          abs(s1["p50_minutes"] - EXPECT_P50) < 1e-9, "实测 %s" % s1["p50_minutes"])
    check("V12 AC1 S1 组 p90_minutes=%.1f" % EXPECT_P90,
          abs(s1["p90_minutes"] - EXPECT_P90) < 1e-9, "实测 %s" % s1["p90_minutes"])
    check("V13 AC1 S1 组 max_minutes=%d、anomaly_count=%d" % (EXPECT_MAX, EXPECT_ANOM),
          s1["max_minutes"] == EXPECT_MAX and s1["anomaly_count"] == EXPECT_ANOM,
          "max=%s anomaly=%s" % (s1["max_minutes"], s1["anomaly_count"]))
    check("V14 AC1 S1 组 overdue_runs=%d、overdue_rate=%s（分母只算有 due 的 3 条）"
          % (EXPECT_S1_OVERDUE, EXPECT_S1_RATE),
          s1["overdue_runs"] == EXPECT_S1_OVERDUE
          and abs(s1["overdue_rate"] - EXPECT_S1_RATE) < 1e-6,
          "overdue=%s rate=%s" % (s1["overdue_runs"], s1["overdue_rate"]))

    # ---------- AC2：两个 as_of 下 overdue_runs 按预期变化 ----------
    db.refresh(eng, F.AS_OF_EARLY)
    early = _row(db.rows_of_mv(eng), SITE_SZ, "S3", "2026-11")
    db.refresh(eng, F.AS_OF_LATE)
    late = _row(db.rows_of_mv(eng), SITE_SZ, "S3", "2026-11")
    check("V15 AC2 同一批数据：as_of=09:30 时 S3 组 overdue_runs=0、rate=0.0",
          early["overdue_runs"] == 0 and early["overdue_rate"] == 0.0,
          "overdue=%s rate=%s" % (early["overdue_runs"], early["overdue_rate"]))
    check("V16 AC2 同一批数据：as_of=11:00 时 S3 组 overdue_runs=1、rate=0.5",
          late["overdue_runs"] == 1 and abs(late["overdue_rate"] - 0.5) < 1e-9,
          "overdue=%s rate=%s" % (late["overdue_runs"], late["overdue_rate"]))
    check("V17 AC2 两次刷新之间 overdue_runs 确实变化了（0 → 1），且是同一条未完成记录",
          early["overdue_runs"] == 0 and late["overdue_runs"] == 1,
          "R9 未完成，due=11-10 10:00；两个 as_of 分别是 09:30 / 11:00")
    check("V18 AC2 分位数不随 as_of 变动（未完成步骤不计耗时，所以 p50 恒为 40）",
          early["p50_minutes"] == late["p50_minutes"] == 40.0,
          "early=%s late=%s" % (early["p50_minutes"], late["p50_minutes"]))
    db.refresh(eng, F.AS_OF_BEFORE_ALL)
    check("V19 AC2 as_of 早于全部数据时物化视图为空（不是报错、也不是全 0 行）",
          db.rows_of_mv(eng) == [], "行数 %d" % len(db.rows_of_mv(eng)))
    db.refresh(eng, F.AS_OF_FULL)

    # ---------- AC3：异常值不影响分位数、anomaly_count 正确 ----------
    with eng.connect() as c:
        # 反证：若把异常值也放进分位数，p50/p90 会明显不同
        _naive_sql = __import__("sqlalchemy").text("""
            WITH x AS (
                SELECT ROUND(EXTRACT(EPOCH FROM (finished_at - started_at)) / 60.0) AS nm
                  FROM sop_step_runs
                 WHERE deleted_at IS NULL AND step_key='S1' AND finished_at IS NOT NULL
            )
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY nm),
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY nm)
              FROM x
        """)
        naive = c.execute(_naive_sql).fetchone()
    naive_p50, naive_p90 = float(naive[0]), float(naive[1])
    check("V20 AC3 反证：若不排除异常值，p50/p90 会变成 %.1f / %.1f，与实测 %.1f / %.1f 明显不同"
          % (naive_p50, naive_p90, EXPECT_P50, EXPECT_P90),
          abs(naive_p50 - EXPECT_P50) > 1e-6 and abs(naive_p90 - EXPECT_P90) > 1e-6,
          "naive p50=%.1f p90=%.1f vs 实测 %.1f / %.1f"
          % (naive_p50, naive_p90, EXPECT_P50, EXPECT_P90))
    check("V21 AC3 异常记录（R5=-30、R6=57600）都没有进入 p50/p90/max 的样本",
          s1["p50_minutes"] == EXPECT_P50 and s1["p90_minutes"] == EXPECT_P90
          and s1["max_minutes"] == EXPECT_MAX,
          "max=%s（若 R6 混入，max 会是 57600）" % s1["max_minutes"])
    check("V22 AC3 anomaly_count=%d（负耗时 1 条 + 超 30 天 1 条）" % EXPECT_ANOM,
          s1["anomaly_count"] == EXPECT_ANOM, "实测 %s" % s1["anomaly_count"])

    with eng.connect() as c:
        neg = c.execute(_t("SELECT count(*) FROM sop_step_runs WHERE finished_at < started_at AND deleted_at IS NULL")).scalar()
        big = c.execute(_t("SELECT count(*) FROM sop_step_runs WHERE deleted_at IS NULL AND finished_at IS NOT NULL AND EXTRACT(EPOCH FROM (finished_at-started_at))/60.0 > 43200")).scalar()
    check("V23 AC3 两类异常各 1 条：负耗时 %d 条、超 30 天 %d 条" % (neg, big),
          neg == 1 and big == 1, "neg=%d big=%d" % (neg, big))

    # ---------- 交叉验证：SQL vs Python 独立实现 ----------
    mism = []
    for as_of in (F.AS_OF_FULL, F.AS_OF_EARLY, F.AS_OF_LATE):
        db.refresh(eng, as_of)
        pg = {(r["site_id"], r["step_key"], r["month"]): r for r in db.rows_of_mv(eng)}
        py = {(r["site_id"], r["step_key"], r["month"]): r for r in P.compute(as_of)}
        if set(pg) != set(py):
            mism.append((as_of, "分组键不同"))
            continue
        for k in pg:
            for f in ("step_runs", "overdue_runs", "anomaly_count"):
                if pg[k][f] != py[k][f]:
                    mism.append((as_of, k, f, pg[k][f], py[k][f]))
            for f in ("overdue_rate", "p50_minutes", "p90_minutes", "max_minutes"):
                a, b = pg[k][f], py[k][f]
                if (a is None) != (b is None):
                    mism.append((as_of, k, f, a, b))
                elif a is not None and abs(float(a) - float(b)) > 1e-6:
                    mism.append((as_of, k, f, a, b))
    db.refresh(eng, F.AS_OF_FULL)
    check("V24 交叉验证：物化视图（SQL）与 Python 独立实现在 3 个 as_of 下结论完全一致",
          not mism, "不一致 %s" % (mism or "无"))

    # ---------- 跨月 / 无 due_at ----------
    g2 = {r["month"]: r for r in db.rows_of_mv(eng)
          if r["site_id"] == SITE_HZ and r["step_key"] == "S2"}
    check("V25 跨月归属：R7 按 started_at 归 2026-10（180 分钟），R8 归 2026-11（30 分钟）",
          abs(g2["2026-10"]["p50_minutes"] - EXPECT_G2["2026-10"]) < 1e-9
          and abs(g2["2026-11"]["p50_minutes"] - EXPECT_G2["2026-11"]) < 1e-9,
          "10 月 %s / 11 月 %s" % (g2["2026-10"]["p50_minutes"],
                                   g2["2026-11"]["p50_minutes"]))
    check("V26 无 due_at 的组 overdue_rate 为 NULL（分母为 0，不是 0 也不是 1）",
          g2["2026-10"]["overdue_rate"] is None, "实测 %s" % g2["2026-10"]["overdue_rate"])


    # ---------- 变异判别样本（口径常量一改就会露馅） ----------
    s4 = _row(rows, SITE_HZ, "S4", "2026-10")
    check("V31 15 天耗时（21600 分钟）在 30 天阈值内算正常：p50=21600、anomaly_count=0",
          s4 is not None and s4["p50_minutes"] == 21600.0 and s4["anomaly_count"] == 0,
          "S4 组 p50=%s anomaly=%s（若阈值改成 7 天，p50 会变 NULL、anomaly 变 1）"
          % ((s4 or {}).get("p50_minutes"), (s4 or {}).get("anomaly_count")))

    s5 = _row(rows, SITE_HZ, "S5", "2026-11")
    s5_oct = _row(rows, SITE_HZ, "S5", "2026-10")
    check("V32 R13 按 +08:00 归 2026-11（若时区偏移改成 0 会归到 2026-10）",
          s5 is not None and s5_oct is None and s5["step_runs"] == 1,
          "2026-11 行=%s / 2026-10 行=%s" % (bool(s5), bool(s5_oct)))

    s6 = _row(rows, SITE_HZ, "S6", "2026-10")
    check("V33 finished 恰好等于 due 时不判超时（严格大于）：overdue_runs=0、rate=0.0",
          s6 is not None and s6["overdue_runs"] == 0 and s6["overdue_rate"] == 0.0,
          "S6 组 overdue=%s rate=%s（改成 >= 会变 1 / 1.0）"
          % ((s6 or {}).get("overdue_runs"), (s6 or {}).get("overdue_rate")))

    # ---------- 交付一致性 ----------
    ddl = open(os.path.join(ROOT, "sql/mv_sop_step_sla.sql"), encoding="utf-8").read()
    check("V27 落盘的 mv DDL 与 pkg/mv_sql.py 生成的内容逐字相同（单一真相源）",
          ddl.strip() == mv_sql.MV_SQL.strip(),
          "文件 %d 字节 / 生成 %d 字节" % (len(ddl.strip()), len(mv_sql.MV_SQL.strip())))

    fnd = open(os.path.join(ROOT, "sql/refresh_function.sql"), encoding="utf-8").read()
    check("V28 落盘的刷新函数 DDL 与代码生成的一致，且函数体含 REFRESH MATERIALIZED VIEW",
          fnd.strip() == mv_sql.REFRESH_SQL.strip() and "REFRESH MATERIALIZED VIEW" in fnd,
          "一致=%s" % (fnd.strip() == mv_sql.REFRESH_SQL.strip()))

    md = open(os.path.join(ROOT, "docs/runs.md"), encoding="utf-8").read()
    heads = len(re.findall(r"^## R\d+ ", md, re.M))
    check("V29 逐例 Markdown 含 14 个小节，每条都写了手算净耗时与判定",
          heads == E.EXPECT_N_RUNS and md.count("手算净耗时") == E.EXPECT_N_RUNS,
          "小节 %d / 手算净耗时 %d 处" % (heads, md.count("手算净耗时")))

    hc = open(os.path.join(ROOT, "docs/hand_calc.md"), encoding="utf-8").read()
    check("V30 手算对照表列出 14 条记录并给出聚合值推导（p50=72.5 / p90=94.8）",
          hc.count("| R") == E.EXPECT_N_RUNS and "72.5" in hc and "94.8" in hc,
          "%d 行；含 72.5=%s 含 94.8=%s"
          % (hc.count("| R"), "72.5" in hc, "94.8" in hc))
