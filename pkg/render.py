# -*- coding: utf-8 -*-
"""逐例 Markdown 渲染（本单唯一需要人工措辞的文件）。"""
import engine as E


def md_head():
    return ["# SOP 步骤级 SLA 构造执行记录（11 条，全部虚构）", "",
            "物化视图 `mv_sop_step_sla` 的输入数据。每条记录都给出**手算的**净耗时与判定，",
            "用来核对 SQL 算出来的聚合值（p50 / p90 / max / overdue_rate / anomaly_count）。", "",
            "口径：", "",
            "- 净耗时 = finished_at − started_at − 暂停区间**并集**长度（重叠暂停只扣一次）；",
            "- 未完成（finished_at 为空）不计算净耗时，只参与超时判定；",
            "- 超时：已完成时 finished_at > due_at；未完成时 as_of > due_at；",
            "- 无 due_at 的只统计耗时，不进超时分母；",
            "- 净耗时 < 0 或 > 30 天记为异常，计入 anomaly_count 且不进分位数；",
            "- 归月按 started_at，时区用固定偏移 +08:00。", "",
            "> 全部为虚构数据，不含真实个人信息与企业信息，也不含客户名称。", ""]


def md_section(c):
    exp = next(x for x in E.EXPECT_RUNS if x[0] == c[0])
    L = ["## %s 步骤 %s" % (c[0], c[1]), "",
         "| 项 | 值 |", "| --- | --- |",
         "| 覆盖类 | %s |" % " ".join(E.cats_of(c)),
         "| started_at | `%s` |" % c[2],
         "| finished_at | %s |" % (("`%s`" % c[3]) if c[3] else "（未完成）"),
         "| due_at | %s |" % (("`%s`" % c[4]) if c[4] else "（无 due_at）"),
         "| 暂停区间 | %s |" % (("；".join("%s ~ %s" % (a, b) for a, b in c[5])) or "无"),
         "| 暂停并集分钟 | %d |" % E._pause_minutes(c[0]),
         "| **手算净耗时（分钟）** | **%s** |" % ("（不计算）" if exp[1] is None else exp[1]),
         "| 手算是否超时 | %s |" % ("是" if exp[2] else "否"),
         "| 手算是否异常 | %s |" % ("是" if exp[3] else "否"), "",
         "说明：%s" % exp[4], ""]
    return L
