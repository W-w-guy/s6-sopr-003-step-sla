# ACCEPTANCE — 逐条 AC 判定（原文 / 判定方式 / 复核命令 / 实际输出原文）

以下输出为 `python tools/verify.py` 在交付包内的真实 stdout，未经修改。

## AC1

**原文**：pytest 通过，5 类用例各至少 1 个，断言值与手算一致

**判定方式**：真跑 pytest（子进程，rc 与 passed/failed 都断言），再从 pytest --collect-only 取出用例名，逐类核对工单点名的 5 类场景各有实现；聚合值（step_runs/p50/p90/max/anomaly_count/overdue_runs/overdue_rate）逐项与硬编码手算值比对；另核物化视图 13 列名与工单原文逐字一致

**复核命令**：`python tools/verify.py`

**实际输出原文**：

```
[PASS] V01 连的是真 PostgreSQL（不是内存库/模拟），版本 >= 16 PG 16.2，连接方式 pgserver(embedded PostgreSQL)
[PASS] V02 Alembic 迁移能真跑 upgrade head（不是只检查文件存在） alembic_version=0002 err=
[PASS] V03 Alembic downgrade base 后再 upgrade head 也能跑通（可回滚） err=无
[PASS] V04 mv_sop_step_sla 是**物化视图**（pg_matviews 有、pg_views 没有） pg_matviews=1 pg_views=0
[PASS] V05 刷新函数 refresh_mv_sop_step_sla 存在于数据库 pg_proc 命中 1
[PASS] V06 物化视图定义里真的用了 percentile_cont（工单原文要求） viewdef 含 percentile_cont=True；库里函数数 4
[PASS] V07 物化视图列与工单原文点名的 13 列逐字一致 实测 ['org_id', 'site_id', 'template_id', 'version_no', 'step_key', 'month', 'step_runs', 'overdue_runs', 'overdue_rate', 'p50_minutes', 'p90_minutes', 'max_minutes', 'anomaly_count']
[PASS] V08 AC1 pytest 真跑通过（rc=0，失败 0） rc=0 passed=15 failed=0
[PASS] V09 AC1 工单点名的 5 类用例各至少 1 个，且全部真实存在于测试文件里 缺 无；共收集 15 个用例
[PASS] V10 AC1 S1 组 step_runs=6（R1~R6；R11 软删除不计） 实测 6
[PASS] V11 AC1 S1 组 p50_minutes=72.5（正常样本 40/60/85/99 的线性插值） 实测 72.5
[PASS] V12 AC1 S1 组 p90_minutes=94.8 实测 94.8
[PASS] V13 AC1 S1 组 max_minutes=99、anomaly_count=2 max=99 anomaly=2
[PASS] V14 AC1 S1 组 overdue_runs=1、overdue_rate=0.333333（分母只算有 due 的 3 条） overdue=1 rate=0.333333
[PASS] V31 15 天耗时（21600 分钟）在 30 天阈值内算正常：p50=21600、anomaly_count=0 S4 组 p50=21600.0 anomaly=0（若阈值改成 7 天，p50 会变 NULL、anomaly 变 1）
```

## AC2

**原文**：同一批虚构数据用两个不同 as_of 刷新，overdue_runs 按预期变化（测试中断言）

**判定方式**：对同一批已灌入的数据，用 refresh_mv_sop_step_sla 分别以 as_of=2026-11-10 09:30 与 11:00 刷新两次；断言未完成的 R9（due 10:00）所在分组 overdue_runs 从 0 变 1、overdue_rate 从 0.0 变 0.5；同时断言分位数不随 as_of 变动（未完成步骤不计耗时）；另断言 as_of 早于全部数据时物化视图为空

**复核命令**：`python tools/verify.py`

**实际输出原文**：

```
[PASS] V15 AC2 同一批数据：as_of=09:30 时 S3 组 overdue_runs=0、rate=0.0 overdue=0 rate=0.0
[PASS] V16 AC2 同一批数据：as_of=11:00 时 S3 组 overdue_runs=1、rate=0.5 overdue=1 rate=0.5
[PASS] V17 AC2 两次刷新之间 overdue_runs 确实变化了（0 → 1），且是同一条未完成记录 R9 未完成，due=11-10 10:00；两个 as_of 分别是 09:30 / 11:00
[PASS] V18 AC2 分位数不随 as_of 变动（未完成步骤不计耗时，所以 p50 恒为 40） early=40.0 late=40.0
[PASS] V19 AC2 as_of 早于全部数据时物化视图为空（不是报错、也不是全 0 行） 行数 0
[PASS] V32 R13 按 +08:00 归 2026-11（若时区偏移改成 0 会归到 2026-10） 2026-11 行=True / 2026-10 行=False
```

## AC3

**原文**：异常耗时记录不影响 p50_minutes / p90_minutes，anomaly_count 数值正确

**判定方式**：断言 p50/p90/max 等于排除异常后的手算值；并做反证——用一条不排除异常的 SQL 现算，得到明显不同的 p50/p90，证明「排除」这步真的起了作用；anomaly_count 断言为 2，并从数据里分别数出负耗时 1 条、超 30 天 1 条

**复核命令**：`python tools/verify.py`

**实际输出原文**：

```
[PASS] V20 AC3 反证：若不排除异常值，p50/p90 会变成 79.5 / 28860.0，与实测 72.5 / 94.8 明显不同 naive p50=79.5 p90=28860.0 vs 实测 72.5 / 94.8
[PASS] V21 AC3 异常记录（R5=-30、R6=57600）都没有进入 p50/p90/max 的样本 max=99（若 R6 混入，max 会是 57600）
[PASS] V22 AC3 anomaly_count=2（负耗时 1 条 + 超 30 天 1 条） 实测 2
[PASS] V23 AC3 两类异常各 1 条：负耗时 1 条、超 30 天 1 条 neg=1 big=1
[PASS] V33 finished 恰好等于 due 时不判超时（严格大于）：overdue_runs=0、rate=0.0 S6 组 overdue=0 rate=0.0（改成 >= 会变 1 / 1.0）
```

## 汇总

```
SUMMARY 33/33 PASS
```
