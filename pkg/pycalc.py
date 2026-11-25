# -*- coding: utf-8 -*-
"""Python 侧的独立实现（交叉验证的第二条路径）。

它**不执行任何 SQL**：直接从 fixtures 的原始数据算净耗时、超时、分位数，
用于证明「物化视图里那段 SQL 算出来的数是对的」。

两条路径共享的只有「规则」本身（超时定义、暂停扣法、异常阈值、percentile_cont 的插值公式），
代码是各写各的——这才是真交叉验证，不是自己跟自己比。

percentile_cont 的语义（PostgreSQL 文档）：对有序样本 x[0..n-1]，分位 p 的位置
    pos = p * (n - 1)
取 i = floor(pos), j = ceil(pos)，结果 = x[i] + (pos - i) * (x[j] - x[i])。
n=1 时直接返回该值。本模块按这个公式实现，不做任何取整近似。
"""
import math
from datetime import datetime, timedelta

import fixtures as F


def _dt(s):
    if s is None:
        return None
    return datetime.fromisoformat(s)


def merge_intervals(iv):
    """区间并集（左闭右开），返回合并后的 [(s,e)]。"""
    if not iv:
        return []
    iv = sorted(iv, key=lambda x: x[0])
    out = [list(iv[0])]
    for s, e in iv[1:]:
        if s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def net_minutes(started, finished, pauses, as_of):
    """净耗时（分钟）。未完成返回 None。暂停先 clip 到执行区间再取并集。"""
    if finished is None:
        return None
    lo, hi = started, finished
    clipped = []
    for pa, re_ in pauses:
        p_end = re_ if re_ is not None else as_of
        s = max(lo, pa)
        e = min(hi, p_end)
        if s < e:
            clipped.append((s, e))
    paused = sum((e - s).total_seconds() for s, e in merge_intervals(clipped))
    return round((finished - started).total_seconds() - paused) / 60.0


def percentile_cont(values, p):
    """PostgreSQL percentile_cont 的等价实现（线性插值）。空集返回 None。"""
    if not values:
        return None
    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return float(xs[0])
    pos = p * (n - 1)
    i = math.floor(pos)
    j = math.ceil(pos)
    if i == j:
        return float(xs[i])
    return float(xs[i] + (pos - i) * (xs[j] - xs[i]))


def _month_of(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def compute(as_of_s):
    """返回与 mv_sop_step_sla 同结构的行（按 org/site/template/version/step/month 分组）。"""
    as_of = _dt(as_of_s)
    runs = F.rows()

    groups = {}
    for r in runs:
        if r["deleted"]:
            continue
        started = _dt(r["started_at"])
        if started > as_of:
            continue
        finished = _dt(r["finished_at"])
        due = _dt(r["due_at"])

        pauses = []
        for p in F.pause_rows():
            if p["run_no"] == r["run_no"] and not p["deleted"]:
                pauses.append((_dt(p["paused_at"]), _dt(p["resumed_at"])))

        key = (str(F.SITE_HZ if r["site_id"] == F.SITE_HZ else F.SITE_SZ),
               r["step_key"], _month_of(started))
        g = groups.setdefault(key, {"step_runs": 0, "overdue_runs": 0, "with_due": 0,
                                    "normal": [], "anomaly": 0})
        g["step_runs"] += 1

        # 超时
        if due is not None:
            g["with_due"] += 1
            if finished is not None:
                if finished > due:
                    g["overdue_runs"] += 1
            else:
                if as_of > due:
                    g["overdue_runs"] += 1

        # 耗时
        nm = net_minutes(started, finished, pauses, as_of)
        if nm is not None:
            if nm < F.ANOMALY_MIN or nm > F.ANOMALY_MAX:
                g["anomaly"] += 1
            else:
                g["normal"].append(nm)

    out = []
    for (site, step, month), g in sorted(groups.items(), key=lambda x: (x[0][1], x[0][2])):
        rate = None
        if g["with_due"]:
            rate = round(g["overdue_runs"] / g["with_due"], 6)
        out.append({
            "site_id": site,
            "step_key": step,
            "month": month,
            "step_runs": g["step_runs"],
            "overdue_runs": g["overdue_runs"],
            "overdue_rate": rate,
            "p50_minutes": percentile_cont(g["normal"], 0.5),
            "p90_minutes": percentile_cont(g["normal"], 0.9),
            "max_minutes": (max(g["normal"]) if g["normal"] else None),
            "anomaly_count": g["anomaly"],
        })
    return out


def find(rows_, site, step, month):
    sid = str(F.SITE_HZ if site == "HZ" else F.SITE_SZ)
    for r in rows_:
        if r["site_id"] == sid and r["step_key"] == step and r["month"] == month:
            return r
    return None
