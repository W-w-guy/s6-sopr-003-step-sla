# 跨平台实跑记录（同一份 zip，Windows 与 Ubuntu 各跑一遍）

## 传输方式

交付包先在 Windows 侧打成 `sla3057.zip`，经本机 HTTP 服务（192.168.112.1:8899）
下载到 Ubuntu 虚拟机（192.168.112.128）。两侧 zip 的 sha256 完全一致：

```
bf13aeb480d0a2c386b49dcb9da9d5923594c4b2da47a6ebba2164d162c1777a  sla3057.zip
```

## 结果对照

本单的 AC 全部依赖**真 PostgreSQL**，两侧都是真库、真跑 DDL 与真跑聚合：

| 检查项 | Windows 11 / Py3.11.7 | Ubuntu 24.04.5 / Py3.12.3 |
| --- | --- | --- |
| PostgreSQL | **16.2**（pgserver 内嵌） | **16.16**（docker `postgres:16-alpine`） |
| sqlalchemy / alembic / psycopg2 | 2.1.9 / 1.20.1 / 2.9.13 | 2.1.9 / 1.20.1 / 2.9.13 |
| SHA256SUMS 逐条复核 | 47/47 OK | **47/47 OK** |
| `tools/verify.py` | **33/33 PASS** | **33/33 PASS** |
| ACCEPTANCE 四元组 | AC1 15 / AC2 6 / AC3 5，MISS 0 | 同上，MISS 0 |
| `pytest tests -v` | **15 passed** | **15 passed** |
| Alembic upgrade→downgrade→upgrade | 三次 rc=0 | 三次 rc=0 |
| 物化视图 13 列 | 与工单逐字一致 | 与工单逐字一致 |
| p50 / p90（S1 组） | 72.5 / 94.8 | 72.5 / 94.8 |
| as_of 回溯（S3 组） | 0 → 1 | 0 → 1 |
| PII 扫描 | 44/0 | 44/0 |

物化视图实际内容（两侧一致）：

```
step_key | month   | runs | overdue | rate     | p50   | p90   | max   | anomaly
S1       | 2026-10 | 6    | 1       | 0.333333 | 72.5  | 94.8  | 99    | 2
S2       | 2026-10 | 1    | 0       | NULL     | 180.0 | 180.0 | 180   | 0
S2       | 2026-11 | 1    | 0       | NULL     | 30.0  | 30.0  | 30    | 0
S3       | 2026-11 | 2    | 1       | 0.5      | 40.0  | 40.0  | 40    | 0
S4       | 2026-10 | 1    | 0       | NULL     | 21600 | 21600 | 21600 | 0
S5       | 2026-11 | 1    | 0       | NULL     | 60.0  | 60.0  | 60    | 0
S6       | 2026-10 | 1    | 0       | 0.0      | 60.0  | 60.0  | 60    | 0
```

## ★ 关于「是不是真跑了 PostgreSQL」

本单最容易被含糊过去的一点是「有没有真数据库」。这里的证据是：

1. V01 断言 `SHOW server_version` 以 `16` 开头，并打印连接方式
   （Windows 是 `pgserver(embedded PostgreSQL)`，Ubuntu 是 `env:SLA3057_DSN`）；
2. V02/V03 通过 Alembic 的 **Python API 真跑** `upgrade head` 与 `downgrade base → upgrade head`，
   再从 `alembic_version` 表读回 `0002` —— 不是只检查迁移文件存在；
3. V04 查 `pg_matviews` 有、`pg_views` 没有，证明它是**物化视图**而不是普通视图；
4. V06 从 `pg_get_viewdef()` 取出视图定义，断言里面真的有 `percentile_cont`；
5. V07 从 `pg_attribute` 读列名与顺序，与工单点名的 13 列逐字比对；
6. Ubuntu 侧日志里还有直接 `docker exec psql` 的查询输出（第 6、7 步），
   是绕过 Python 直接看库里的行。

## Ubuntu 侧多跑的一步：绕过代码直接 psql

除了 verify，还用 `docker exec pg3057 psql` 直接查了两件事：

- 物化视图的 7 行内容（见上表）；
- as_of 回溯：`SELECT * FROM refresh_mv_sop_step_sla('2026-11-10 09:30+08')` 后
  S3 组是 `0 / 0.000000`；改成 `11:00+08` 刷新后变成 `1 / 0.500000`。
  **数据一行没动，只是改了 as_of 参数** —— 这就是 AC2 要的回溯语义。

## 过程中修掉的四个真问题

### 1. 嵌入式 PostgreSQL 不带头 tzdata

`AT TIME ZONE 'Asia/Shanghai'` 在 pgserver 内嵌库上直接报
`time zone "Asia/Shanghai" not recognized`。改成固定偏移 `AT TIME ZONE interval '8 hours'`。
Asia/Shanghai 自 1991 年起无夏令时，2026 年恒为 +08:00，两者等价。
这与 playbook 里「不要用 zoneinfo 依赖系统 tzdata」是同一条教训的 PG 版。

### 2. alembic.ini 必须是纯 ASCII

Alembic 用**系统 locale** 读 `alembic.ini`，zh-CN Windows 是 GBK。
我在 ini 里写了中文注释，`alembic upgrade` 在跑任何迁移之前就
`UnicodeDecodeError`。改成纯 ASCII 注释后正常。

### 3. 物化视图定义里不能带运行时参数

`mv_sop_step_sla` 要用 as_of 判超时，但 `CREATE MATERIALIZED VIEW` 不接受参数。
做法：建单行参数表 `sla_refresh_param(as_of)`，视图 join 它取 as_of；
刷新函数先 `INSERT ... ON CONFLICT(id) DO UPDATE` 再 `REFRESH MATERIALIZED VIEW`。
这样「同一批数据换 as_of」物理上可行，AC2 才有落脚点。

### 4. 三处变异第一版没被抓到（数据不含该分支）

| 变异 | 为什么没抓到 | 补的判别样本 |
| --- | --- | --- |
| 异常上限 30 天 → 7 天 | 数据里没有 7~30 天之间的耗时，改阈值结果不变 | R12：15 天（21600 分钟），阈值改了就会从正常变异常 |
| 归月偏移 8 → 0 | 跨月样本 R7 在两种偏移下都落 10 月 | R13：`2026-11-01 02:00+08`（UTC 是 10-31 18:00），偏移改了月份就变 |
| 超时比较 > → >= | 没有 `finished == due` 的样本 | R14：finished 恰好等于 due，改 >= 就从 0 变 1 |

补完后变异 7/7 全被抓到。这是 playbook「变异要真能改变行为，得先让数据存在两条可区分路径」的又一次实证。

## 两个平台的原始日志

- `report/windows_run.log` —— Windows 侧完整输出（47/47、33/33、15 passed、33 条断言原文）
- `report/ubuntu_run.log` —— Ubuntu 侧完整输出（原样传回，sha256 `7ada6a1a4c8a4e16c6ced3e9f8da1ffaa8c7036aa438e58a3ed6ed38024936f6`，与虚拟机内文件逐字节一致）

> `report/` 是打包时的快照，按约定不参与 `SHA256SUMS.txt` 校验。
