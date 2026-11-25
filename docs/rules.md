# 口径说明（工单未写死处在此定死）

## 归月

按 `started_at` 归月。时区用**固定偏移 `+08:00`**，不用 `AT TIME ZONE 'Asia/Shanghai'` ——
后者依赖数据库安装里的 tzdata，嵌入式 PostgreSQL（pgserver）不带头该数据，
会报 `time zone "Asia/Shanghai" not recognized`。Asia/Shanghai 自 1991 年起无夏令时，
2026 年恒为 +08:00，固定偏移与命名时区等价。

## 净耗时

`net_minutes = ROUND((finished_at - started_at - 暂停并集秒数) / 60)`。

- 暂停区间按 `[paused_at, COALESCE(resumed_at, as_of)]` 取，先 clip 到执行区间再求**并集**；
  重叠暂停只扣一次（用 `range_agg` + `tstzrange` multirange 实现，不是简单求和）；
- **未完成（finished_at 为空）不计算净耗时**，记 NULL。
  理由：未完成步骤的耗时会随 as_of 漂移，混进分位数会让「换个 as_of 分位数也变」，
  与「异常值不影响分位数」想守的稳定性冲突。

## 超时

- 有 `due_at` 才判：已完成看 `finished_at > due_at`；未完成看 `as_of > due_at`；
- 无 `due_at` 的只统计耗时，**不进超时分母**（工单原文）。

## overdue_rate

`overdue_runs / 该分组内有 due_at 的运行数`。整组都没有 due_at 时为 NULL（不是 0）。

## 异常值

净耗时 < 0 或 > 43200 分钟（30 天）记为异常：

- 计入 `anomaly_count`；
- **不进** p50 / p90 / max；
- 未完成步骤的 NULL 不计入异常（它压根没算耗时）。

## 分位数

用 PostgreSQL 内置 `percentile_cont(0.5)` 与 `percentile_cont(0.9)`：
对有序样本 `x[0..n-1]`，位置 `pos = p*(n-1)`，结果 = `x[i] + (pos-i)*(x[j]-x[i])`（线性插值，
n=1 时直接返回）。`max_minutes` 用 `MAX()`，同样排除异常值。

## 软删除

`deleted_at IS NOT NULL` 的执行记录与暂停记录都不参与统计。

## as_of 参数化

物化视图定义里不能带运行时参数。所以建一张单行参数表 `sla_refresh_param(as_of)`，
物化视图 join 它取 as_of；刷新函数 `refresh_mv_sop_step_sla(p_as_of)` 先 upsert 参数表，
再 `REFRESH MATERIALIZED VIEW`。这样同一批数据可以用不同 as_of 反复刷新做回溯。
