# -*- coding: utf-8 -*-
"""规则常量 + 逐条期望（本单的"示例集"就是 11 条构造执行记录）。

★ 为什么口径常量全放在这个文件：变异测试只改 engine_rel 指向的这个文件，
  而物化视图的 SQL 由 pkg/mv_sql.py 用这些常量 format 出来。
  常量改一处，生成的 MV 定义就真的变了 —— 这样变异才「真能改变行为」，
  而不是改了个没人读的字面量。

口径（工单给了骨架，未写死处在此定死，并写入 README）：
  - 归月：按 started_at 归月，时区用**固定偏移 +08:00**（不用 Asia/Shanghai：
    嵌入式 PostgreSQL 不带头 tzdata，会报 time zone not recognized）；
  - 净耗时 = finished - started - 暂停区间并集的长度；
  - 未完成（finished IS NULL）不计算净耗时，只参与超时判定；
  - 超时：完成时 finished > due；未完成时 as_of > due；
  - 无 due_at 不进超时分母；
  - 异常：净耗时 < 0 或 > 30 天，计入 anomaly_count 且不进分位数；
  - 分位数用 percentile_cont（线性插值）。
"""
from datetime import datetime, timedelta, timezone

import fixtures as F

# ---------------------------------------------------------------- 口径常量（变异锚点）
TZ_OFFSET_HOURS = 8                     # 归月用的时区偏移（固定偏移，不依赖 tzdata）
ANOMALY_MIN_MINUTES = 0                 # 净耗时 < 0 记为异常
ANOMALY_MAX_MINUTES = 30 * 24 * 60      # 净耗时 > 30 天记为异常
OVERDUE_COMPARE = ">"                  # 超时判定：finished_at > due_at（严格大于）
UNFINISHED_NET_EXPR = "NULL"            # 未完成步骤的净耗时：NULL（不参与分位数）
RATE_DENOMINATOR = "FILTER (WHERE has_due)"   # overdue_rate 分母：只算有 due_at 的
PAUSE_DEDUCT = True                     # 是否扣除暂停区间
CHECK_ANOMALY_LOW = True                # 是否检查「负耗时」这一侧

# 下面两个条件串会被原样嵌进物化视图。变异改这里 = 改 SQL 行为。
_PCT_BOTH = "net_minutes IS NOT NULL AND net_minutes >= %d AND net_minutes <= %d" % (
    ANOMALY_MIN_MINUTES, ANOMALY_MAX_MINUTES)
_PCT_HIGH = "net_minutes IS NOT NULL AND net_minutes <= %d" % ANOMALY_MAX_MINUTES
PCT_FILTER = _PCT_BOTH if CHECK_ANOMALY_LOW else _PCT_HIGH

_ANOM_BOTH = "net_minutes IS NOT NULL AND (net_minutes < %d OR net_minutes > %d)" % (
    ANOMALY_MIN_MINUTES, ANOMALY_MAX_MINUTES)
_ANOM_HIGH = "net_minutes IS NOT NULL AND net_minutes > %d" % ANOMALY_MAX_MINUTES
ANOMALY_COND = _ANOM_BOTH if CHECK_ANOMALY_LOW else _ANOM_HIGH

# ---------------------------------------------------------------- 逐条期望（手算）
# (run_no, 净耗时分钟|None, 是否超时, 是否异常, 说明)
EXPECT_RUNS = [
    ("R1", 40, False, False, "执行 60 分钟扣掉 20 分钟暂停；due 10:30 未超时"),
    ("R2", 99, True, False, "执行 99 分钟无暂停；due 10:00 已超时"),
    ("R3", 85, False, False, "执行 120 分钟；两次重叠暂停取并集 35 分钟（不是 40）"),
    ("R4", 60, False, False, "无 due_at：进耗时统计，不进超时分母"),
    ("R5", -30, False, True, "finished 早于 started，负耗时记异常，不进分位数"),
    ("R6", 57600, False, True, "耗时 40 天 > 30 天阈值，记异常，不进分位数"),
    ("R7", 180, False, False, "10-31 23:00 跨到 11-01 02:00，按 started_at 归 10 月"),
    ("R8", 30, False, False, "11-01 当日执行，归 11 月"),
    ("R9", None, True, False, "未完成：as_of=11:00 时超过 due 10:00；净耗时不计"),
    ("R10", 40, False, False, "已完成 40 分钟，due 10:00 未超时"),
    ("R11", 60, False, False, "已软删除，不参与任何统计"),
    ("R12", 21600, False, False, "15 天：30 天阈值内算正常；阈值若改成 7 天就会变异常"),
    ("R13", 60, False, False, "11-01 02:00+08:00（UTC 10-31 18:00）：按 +08:00 归 11 月"),
    ("R14", 60, False, False, "finished 恰好等于 due：严格大于判不超时，改 >= 就会超时"),
]
EXPECT_ANOMALY_TOTAL = 2
EXPECT_NORMAL_VALUES = [40, 60, 85, 99]        # 进分位数的样本（排序后）
EXPECT_P50 = 72.5                               # 60 + 0.5*(85-60)
EXPECT_P90 = 94.8                               # 85 + 0.7*(99-85)
EXPECT_MAX = 99
EXPECT_S1_RUNS = 6
EXPECT_S1_OVERDUE = 1
EXPECT_S1_RATE = 0.333333                       # 1/3，分母只算有 due 的 3 条
# 变异判别样本的期望（口径常数一旦改错就会变）
EXPECT_S4_15DAYS = {"step_runs": 1, "p50_minutes": 21600.0, "anomaly_count": 0}
EXPECT_S5_MONTH = "2026-11"          # R13 按 +08:00 归 11 月
EXPECT_S6_RATE = 0.0                 # finished == due 不算超时（严格大于）

EXPECT_MV_COLUMNS = ["org_id", "site_id", "template_id", "version_no", "step_key",
                     "month", "step_runs", "overdue_runs", "overdue_rate",
                     "p50_minutes", "p90_minutes", "max_minutes", "anomaly_count"]
EXPECT_N_RUNS = 14
EXPECT_N_PAUSES = 3

# ---------------------------------------------------------------- rule_kit 契约
# 本单的"示例集" = 11 条构造执行记录；逐条给出净耗时与判定，便于人工核对
CASES = F.RUNS
CATS = [
    ("C01", "暂停扣除（单次暂停）"),
    ("C02", "暂停扣除（重叠暂停取并集）"),
    ("C03", "跨月归属（按 started_at）"),
    ("C04", "无 due_at：进耗时、不进超时分母"),
    ("C05", "异常值：负耗时"),
    ("C06", "异常值：超 30 天"),
    ("C07", "未完成步骤（as_of 回溯）与软删除"),
]

CAT_MAP = {
    "R1": ["C01"], "R2": ["C04"], "R3": ["C02"], "R4": ["C04"],
    "R5": ["C05"], "R6": ["C06"], "R7": ["C03"], "R8": ["C03"],
    "R9": ["C07"], "R10": ["C04"], "R11": ["C07"],
    "R12": ["C06"], "R13": ["C03"], "R14": ["C04"],
}
# RUNS 是元组，不能塞键；覆盖类单独存一张表
RUN_CATS = CAT_MAP

COLS = ["run_no", "step_key", "started_at", "finished_at", "due_at",
        "pause_minutes", "expected_net_minutes", "expected_overdue",
        "expected_anomaly", "note"]


def case_id(c):
    return c[0]


def cats_of(c):
    return RUN_CATS[c[0]]


def _pause_minutes(run_no):
    """该 run 的暂停区间并集分钟数（手算级别的小函数，与 SQL 无关）。"""
    iv = []
    for rn, _s, _st, _fi, _d, pauses, _site in F.RUNS:
        if rn != run_no:
            continue
        for pa, re_ in pauses:
            a = datetime.fromisoformat(pa)
            b = datetime.fromisoformat(re_) if re_ else None
            iv.append((a, b))
    if not iv:
        return 0
    spans = sorted((a, b) for a, b in iv)
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return int(sum((e - s).total_seconds() for s, e in merged) // 60)


def row_of(c):
    run_no = c[0]
    exp = next(x for x in EXPECT_RUNS if x[0] == run_no)
    start = c[2]
    fin = c[3]
    due = c[4]
    dur = None
    if fin:
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(fin)
        dur = int((b - a).total_seconds() // 60)
    return {
        "run_no": run_no,
        "step_key": c[1],
        "started_at": start,
        "finished_at": fin or "(未完成)",
        "due_at": due or "(无 due_at)",
        "pause_minutes": _pause_minutes(run_no),
        "expected_net_minutes": "(不计算)" if exp[1] is None else exp[1],
        "expected_overdue": "true" if exp[2] else "false",
        "expected_anomaly": "true" if exp[3] else "false",
        "note": exp[4],
    }
