# 会员空间平台 · SOP 步骤级超时率与耗时分位数统计

本包为「SOP 步骤级超时率与耗时分位数统计」交付物：物化视图 mv_sop_step_sla（13 列，按 org/site/template/version/step/month 分组，含 step_runs / overdue_runs / overdue_rate / p50 / p90 / max / anomaly_count）、参数化刷新函数 refresh_mv_sop_step_sla(as_of)（先 upsert 单行参数表再 REFRESH，支持回溯）、两份 Alembic 迁移（可 upgrade 可 downgrade）、11 条虚构构造执行记录与手算对照表、15 个 pytest 用例覆盖工单点名的 5 类场景、以及一套 Python 独立实现用于与 SQL 交叉验证。全部断言跑在真 PostgreSQL 16 上。

## 一条命令复跑

```
python tools/gen.py             # 重新生成 docs/ 下全部交付物
python tools/verify.py          # 逐条断言 AC（33 条），任何一条失败即非零退出
python -m pytest tests -q       # 用例逐条比对 CSV 期望值
python tools/mutate.py          # 变异测试：改坏引擎 7 处，每处都必须让 verify 变红
python tools/build_docs.py      # 由实跑结果重生成 README / DATA_PROVENANCE / ACCEPTANCE
python tools/make_zip.py        # 打包 + SHA256SUMS
```

## 环境依赖

- Python 3.11+（已在 3.11.7 与 3.12.3 实跑）。
- **必需**：`sqlalchemy>=2`、`alembic`、`psycopg2-binary`（或 psycopg 3）。
- **必需**：一个真 PostgreSQL 16。两种接法任选其一：
-   · 设 `SLA3057_DSN`（或 `DATABASE_URL`）指向已有实例，例如 `postgresql://postgres:pw@127.0.0.1:55432/postgres`；
-   · 不设就自动用 `pgserver`（pip 包，随附 PostgreSQL 二进制）起一个内嵌实例，数据目录在临时目录、进程退出即弃。
- Ubuntu 上的实测做法：`docker run -d --name pg3057 -e POSTGRES_PASSWORD=pg3057 -p 55432:5432 postgres:16-alpine` 然后 `export SLA3057_DSN=...`。

## 目录

| 路径 | 内容 |
| --- | --- |
| `pkg/engine.py` | 业务规则引擎 + 示例定义 + 情形编号 |
| `pkg/render.py` | 逐例 Markdown 渲染 |
| `pkg/engine.py` | 口径常量（时区偏移/异常阈值/超时比较符/未完成耗时表达式/rate 分母/是否扣暂停）+ 11 条记录的手算期望 |
| `pkg/mv_sql.py` | 物化视图与刷新函数的 SQL 定义（由 engine 常量 format 生成，单一真相源） |
| `pkg/schema.py` | SQLAlchemy 模型（sop_step_runs / sop_step_pauses / sla_refresh_param） |
| `pkg/db.py` | 真 PostgreSQL 连接与建库/灌数/刷新/读视图（pgserver 内嵌或外部 DSN） |
| `pkg/pycalc.py` | Python 侧独立实现（不走 SQL），含 percentile_cont 线性插值的等价实现 |
| `pkg/fixtures.py` | 11 条虚构执行记录与 3 条暂停记录（确定性，UUID 固定） |
| `alembic/` | 两份迁移：0001 建表、0002 建物化视图与刷新函数；ini 为纯 ASCII |
| `tests/` | 15 个 pytest 用例，覆盖暂停扣除 / 跨月归属 / 无 due_at / 异常值 / as_of 回溯 + 交叉验证 |
| `sql/mv_sop_step_sla.sql` | 物化视图 DDL（与代码生成内容逐字一致） |
| `sql/refresh_function.sql` | 刷新函数 DDL |
| `docs/rules.md` | 口径说明（工单未写死处在此定死） |
| `docs/hand_calc.md` | 11 条记录的手算对照表与聚合值推导 |
| `docs/runs.md` | 逐条记录说明 |
| `tools/verify.py` | AC 断言器（33 条，非零退出可接 CI） |
| `tools/mutate.py` | 变异测试（7 处） |
| `tools/pii_scan.py` | PII 扫描（手机 / 邮箱 / 身份证 / 银行卡） |
| `report/` | 本次双平台实跑日志（打包时快照，不参与校验和） |

## 口径说明

- 物化视图 mv_sop_step_sla 的 13 列与工单原文逐字一致。
- 归月按 started_at，时区用固定偏移 +08:00（不用 AT TIME ZONE 'Asia/Shanghai'：嵌入式 PostgreSQL 不带 tzdata，会报 time zone not recognized；Asia/Shanghai 自 1991 年起无夏令时，固定偏移等价）。
- 净耗时 = finished_at − started_at − 暂停区间并集长度；并集用 range_agg + tstzrange multirange 实现，重叠暂停只扣一次。
- 未完成（finished_at 为空）不计算净耗时，记 NULL；只参与超时判定。
- 超时判定：已完成看 finished_at > due_at；未完成看 as_of > due_at。
- 无 due_at 的记录只统计耗时，不进超时分母；整组无 due_at 时 overdue_rate 为 NULL。
- 净耗时 < 0 或 > 30 天记为异常：计入 anomaly_count，且不进 p50 / p90 / max。
- 分位数用 percentile_cont（PostgreSQL 内置，线性插值）；max 用 MAX()，同样排除异常值。
- deleted_at 非空的执行记录与暂停记录都不参与统计。
- 物化视图定义里不能带运行时参数，所以建单行参数表 sla_refresh_param(as_of)，刷新函数先 upsert 再 REFRESH MATERIALIZED VIEW。
- 口径常量集中在 pkg/engine.py，物化视图 SQL 由 pkg/mv_sql.py 用这些常量 format 出来 —— 改常量即改 SQL 行为，变异测试才测得到。
- alembic.ini 保持纯 ASCII：Alembic 用系统 locale（zh-CN Windows 是 GBK）读该文件，写中文注释会让 upgrade 在跑任何迁移前就 UnicodeDecodeError。

## 第三方资源与许可

| 资源 | 版本/来源 | 许可 |
| --- | --- | --- |
| PostgreSQL | Windows 16.2（pgserver 内嵌）/ Ubuntu 16.16（docker postgres:16-alpine） | PostgreSQL License |
| SQLAlchemy | 2.1.9（两侧同版本） | MIT |
| Alembic | 1.20.1（两侧同版本） | MIT |
| psycopg2-binary | 2.9.13（两侧同版本） | LGPL with exceptions |
| pgserver | 0.1.4（仅 Windows 侧用于起内嵌 PG） | MIT |

第三方资源仅用于生成交付物，不改变上述任何判定口径；其许可见包内 `data/fonts/OFL.txt`（字体）等随附文件。

## 复跑的两种模式

- `python tools/verify.py` —— 完整模式：33 条断言全部真跑（含 Alembic upgrade/downgrade、真 SQL 查询）。本单没有可跳过的断言，缺数据库会直接失败而不是静默跳过。
- `python -m pytest tests -v` —— 15 个用例，同样必须连真库。
- `python -m alembic upgrade head` / `downgrade base` —— 可直接在包内独立执行，不依赖 verify。
