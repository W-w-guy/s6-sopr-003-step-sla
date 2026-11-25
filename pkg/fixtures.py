# -*- coding: utf-8 -*-
"""虚构夹具：5 类用例（暂停扣除 / 跨月归属 / 无 due_at / 异常值 / as_of 回溯）。

全部确定性（UUID 固定、时间写死），不读系统时钟，重跑产出同一批行。
时间统一 +08:00（Asia/Shanghai），与物化视图里的归月时区一致。

手算期望写在 EXPECT 里并在 checks 里逐条比对；本文件只负责"数据长什么样"。
"""
import uuid

NS = uuid.UUID("11111111-2222-3333-4444-555555555555")
ORG = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
SITE_HZ = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
SITE_SZ = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
TPL1 = uuid.UUID("cccccccc-0000-0000-0000-000000000001")


def _uid(name):
    return uuid.uuid5(NS, name)


def _t(s):
    """把 '2026-10-01 09:00' 变成带 +08:00 的 ISO 串。"""
    return s.replace(" ", "T") + "+08:00"


# 每条 run: (run_no, step_key, started, finished|None, due|None, pauses[(paused, resumed|None)], site)
RUNS = [
    # ---- G1：T1/S1，2026-10，测「暂停扣除」与分位数 ----
    ("R1", "S1", _t("2026-10-01 09:00"), _t("2026-10-01 10:00"), _t("2026-10-01 10:30"),
     [(_t("2026-10-01 09:20"), _t("2026-10-01 09:40"))], SITE_HZ),
    ("R2", "S1", _t("2026-10-02 09:00"), _t("2026-10-02 10:39"), _t("2026-10-02 10:00"),
     [], SITE_HZ),
    # R3 两次暂停重叠：09:30-09:50 与 09:45-10:05，并集 09:30-10:05 = 35 分钟（不是 40）
    ("R3", "S1", _t("2026-10-03 09:00"), _t("2026-10-03 11:00"), _t("2026-10-03 12:00"),
     [(_t("2026-10-03 09:30"), _t("2026-10-03 09:50")),
      (_t("2026-10-03 09:45"), _t("2026-10-03 10:05"))], SITE_HZ),
    # R4 无 due_at：进耗时统计，不进超时分母
    ("R4", "S1", _t("2026-10-04 09:00"), _t("2026-10-04 10:00"), None, [], SITE_HZ),
    # R5 异常：finished 早于 started，净耗时 -30 分钟
    ("R5", "S1", _t("2026-10-05 09:00"), _t("2026-10-05 08:30"), None, [], SITE_HZ),
    # R6 异常：耗时 40 天（57600 分钟）> 30 天阈值
    ("R6", "S1", _t("2026-10-06 09:00"), _t("2026-11-15 09:00"), None, [], SITE_HZ),

    # ---- G2：T1/S2，测「跨月归月」 ----
    ("R7", "S2", _t("2026-10-31 23:00"), _t("2026-11-01 02:00"), None, [], SITE_HZ),
    ("R8", "S2", _t("2026-11-01 09:00"), _t("2026-11-01 09:30"), None, [], SITE_HZ),

    # ---- G3：T1/S3，测「as_of 回溯」 ----
    # R9 在 as_of=09:30 时未到期，as_of=11:00 时已超时
    ("R9", "S3", _t("2026-11-10 09:00"), None, _t("2026-11-10 10:00"), [], SITE_SZ),
    ("R10", "S3", _t("2026-11-10 09:00"), _t("2026-11-10 09:40"), _t("2026-11-10 10:00"),
     [], SITE_SZ),

    # ---- R11 软删除：不参与任何统计（用来证明 deleted_at 生效） ----
    ("R11", "S1", _t("2026-10-07 09:00"), _t("2026-10-07 10:00"), None, [], SITE_HZ),

    # ---- 下面三条是「变异判别样本」：专门让口径常量一旦改错就必然露馅 ----
    # R12 净耗时 15 天（21600 分钟）：在 30 天阈值内算正常，若阈值被改成 7 天就会变异常，
    #     于是该组 p50 从 21600 变 NULL、anomaly_count 从 0 变 1 —— 能抓到阈值改动。
    ("R12", "S4", _t("2026-10-08 09:00"), _t("2026-10-23 09:00"), None, [], SITE_HZ),
    # R13 started=2026-11-01 02:00+08:00（UTC 是 10-31 18:00）：
    #     按 +08:00 归 2026-11，按 offset 0 会归 2026-10 —— 能抓到时区偏移被改。
    ("R13", "S5", _t("2026-11-01 02:00"), _t("2026-11-01 03:00"), None, [], SITE_HZ),
    # R14 finished 恰好等于 due（10:00 = 10:00）：
    #     严格大于判不超时（rate=0.0），若改成 >= 就会判超时（rate=1.0）—— 能抓到比较符改动。
    ("R14", "S6", _t("2026-10-09 09:00"), _t("2026-10-09 10:00"),
     _t("2026-10-09 10:00"), [], SITE_HZ),
]

DELETED = {"R11"}

AS_OF_EARLY = _t("2026-11-10 09:30")
AS_OF_LATE = _t("2026-11-10 11:00")
AS_OF_FULL = _t("2026-11-30 00:00")

# ---------------------------------------------------------------- 手算期望
# G1（T1/S1，month=2026-10），as_of=FULL
# 净耗时：R1=60-20=40, R2=99, R3=120-35=85, R4=60, R5=-30(异常), R6=57600(异常), R11 已删除
# 正常集合 {40,60,85,99} → p50=(60+85)/2=72.5, p90=85+0.7*(99-85)=94.8, max=99
# 有 due 的：R1(未超,10:00<10:30)、R2(超,10:39>10:00)、R3(未超,11:00<12:00) → 1/3
EXPECT_G1 = {
    "step_runs": 6,
    "overdue_runs": 1,
    "overdue_rate": 0.333333,
    "p50_minutes": 72.5,
    "p90_minutes": 94.8,
    "max_minutes": 99,
    "anomaly_count": 2,
}

# G2 跨月：R7 归 2026-10（180 分钟），R8 归 2026-11（30 分钟）
EXPECT_G2 = {
    "2026-10": {"step_runs": 1, "p50_minutes": 180.0, "p90_minutes": 180.0,
                "max_minutes": 180, "anomaly_count": 0},
    "2026-11": {"step_runs": 1, "p50_minutes": 30.0, "p90_minutes": 30.0,
                "max_minutes": 30, "anomaly_count": 0},
}

# G3 as_of 回溯：同一批数据，两个 as_of 下 overdue_runs 从 0 变 1
EXPECT_G3 = {
    AS_OF_EARLY: {"step_runs": 2, "overdue_runs": 0, "overdue_rate": 0.0,
                  "p50_minutes": 40.0, "p90_minutes": 40.0, "max_minutes": 40,
                  "anomaly_count": 0},
    AS_OF_LATE: {"step_runs": 2, "overdue_runs": 1, "overdue_rate": 0.5,
                 "p50_minutes": 40.0, "p90_minutes": 40.0, "max_minutes": 40,
                 "anomaly_count": 0},
}

# as_of 早于一切：什么都不该有
AS_OF_BEFORE_ALL = _t("2026-09-01 00:00")

ANOMALY_MIN = 0
ANOMALY_MAX = 30 * 24 * 60


def rows():
    """转成可直接 INSERT 的行（dict）。"""
    out = []
    for run_no, step, started, finished, due, pauses, site in RUNS:
        out.append({
            "run_no": run_no, "step_key": step, "started_at": started,
            "finished_at": finished, "due_at": due, "site_id": site,
            "deleted": run_no in DELETED,
            "pauses": pauses,
        })
    return out


def pause_rows():
    out = []
    for run_no, step, started, finished, due, pauses, site in RUNS:
        for k, (pa, re_) in enumerate(pauses, 1):
            out.append({"run_no": run_no, "seq": k, "paused_at": pa,
                        "resumed_at": re_, "deleted": run_no in DELETED})
    return out
