# -*- coding: utf-8 -*-
"""本单特有产物：物化视图 DDL、刷新函数 DDL、口径说明、手算对照表。

DDL 全部从 pkg/mv_sql.py 落盘（单一真相源，与 Alembic 迁移里执行的是同一份字符串）。
"""
import os

import engine as E
import mv_sql

MV_DDL = "sql/mv_sop_step_sla.sql"
FN_DDL = "sql/refresh_function.sql"
RULES_MD = "docs/rules.md"
EXPECTED_MD = "docs/hand_calc.md"


def _rules():
    L = ["# 口径说明（工单未写死处在此定死）", "",
         "## 归月", "",
         "按 `started_at` 归月。时区用**固定偏移 `+08:00`**，不用 `AT TIME ZONE 'Asia/Shanghai'` ——",
         "后者依赖数据库安装里的 tzdata，嵌入式 PostgreSQL（pgserver）不带头该数据，",
         "会报 `time zone \"Asia/Shanghai\" not recognized`。Asia/Shanghai 自 1991 年起无夏令时，",
         "2026 年恒为 +08:00，固定偏移与命名时区等价。", "",
         "## 净耗时", "",
         "`net_minutes = ROUND((finished_at - started_at - 暂停并集秒数) / 60)`。", "",
         "- 暂停区间按 `[paused_at, COALESCE(resumed_at, as_of)]` 取，先 clip 到执行区间再求**并集**；",
         "  重叠暂停只扣一次（用 `range_agg` + `tstzrange` multirange 实现，不是简单求和）；",
         "- **未完成（finished_at 为空）不计算净耗时**，记 NULL。",
         "  理由：未完成步骤的耗时会随 as_of 漂移，混进分位数会让「换个 as_of 分位数也变」，",
         "  与「异常值不影响分位数」想守的稳定性冲突。", "",
         "## 超时", "",
         "- 有 `due_at` 才判：已完成看 `finished_at > due_at`；未完成看 `as_of > due_at`；",
         "- 无 `due_at` 的只统计耗时，**不进超时分母**（工单原文）。", "",
         "## overdue_rate", "",
         "`overdue_runs / 该分组内有 due_at 的运行数`。整组都没有 due_at 时为 NULL（不是 0）。", "",
         "## 异常值", "",
         "净耗时 < %d 或 > %d 分钟（30 天）记为异常：" % (E.ANOMALY_MIN_MINUTES, E.ANOMALY_MAX_MINUTES), "",
         "- 计入 `anomaly_count`；",
         "- **不进** p50 / p90 / max；",
         "- 未完成步骤的 NULL 不计入异常（它压根没算耗时）。", "",
         "## 分位数", "",
         "用 PostgreSQL 内置 `percentile_cont(0.5)` 与 `percentile_cont(0.9)`：",
         "对有序样本 `x[0..n-1]`，位置 `pos = p*(n-1)`，结果 = `x[i] + (pos-i)*(x[j]-x[i])`（线性插值，",
         "n=1 时直接返回）。`max_minutes` 用 `MAX()`，同样排除异常值。", "",
         "## 软删除", "",
         "`deleted_at IS NOT NULL` 的执行记录与暂停记录都不参与统计。", "",
         "## as_of 参数化", "",
         "物化视图定义里不能带运行时参数。所以建一张单行参数表 `sla_refresh_param(as_of)`，",
         "物化视图 join 它取 as_of；刷新函数 `refresh_mv_sop_step_sla(p_as_of)` 先 upsert 参数表，",
         "再 `REFRESH MATERIALIZED VIEW`。这样同一批数据可以用不同 as_of 反复刷新做回溯。", ""]
    return "\n".join(L)


def _hand_calc():
    L = ["# 手算对照表（11 条记录）", "",
         "| run | 步骤 | 净耗时(分钟) | 超时 | 异常 | 说明 |", "| --- | --- | --- | --- | --- | --- |"]
    for rn, net, od, an, note in E.EXPECT_RUNS:
        L.append("| %s | %s | %s | %s | %s | %s |"
                 % (rn, next(c[1] for c in E.CASES if c[0] == rn),
                    "（不计算）" if net is None else net,
                    "是" if od else "否", "是" if an else "否", note))
    L += ["", "## 由上面 11 条推出的聚合值（手算）", "",
          "S1 组（2026-10）：", "",
          "- step_runs = %d（R1~R6，R11 已软删除）" % E.EXPECT_S1_RUNS,
          "- 有 due_at 的 = 3 条（R1、R2、R3），超时 %d 条（只有 R2）→ overdue_rate = %s"
          % (E.EXPECT_S1_OVERDUE, E.EXPECT_S1_RATE),
          "- 进分位数的正常样本 = %s（R5=-30、R6=57600 是异常，被排除）" % E.EXPECT_NORMAL_VALUES,
          "- p50 = %s、p90 = %s、max = %s、anomaly_count = %d"
          % (E.EXPECT_P50, E.EXPECT_P90, E.EXPECT_MAX, E.EXPECT_ANOMALY_TOTAL), "",
          "S2 组：R7 归 2026-10（180 分钟），R8 归 2026-11（30 分钟）。", "",
          "S3 组：R9 未完成、R10 已完成 40 分钟。", "",
          "  - as_of = 2026-11-10 09:30 → R9 未到期 → overdue_runs = 0，rate = 0.0",
          "  - as_of = 2026-11-10 11:00 → R9 已过期 → overdue_runs = 1，rate = 0.5", ""]
    return "\n".join(L)


def write_extras(docs_dir):
    root = os.path.dirname(os.path.abspath(docs_dir))
    out = []
    for rel, body in ((MV_DDL, mv_sql.MV_SQL),
                      (FN_DDL, mv_sql.REFRESH_SQL),
                      (RULES_MD, _rules()),
                      (EXPECTED_MD, _hand_calc())):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body if body.endswith("\n") else body + "\n")
        out.append(p)
    return out
