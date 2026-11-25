# -*- coding: utf-8 -*-
"""物化视图 mv_sop_step_sla 与刷新函数的 SQL 定义（单一真相源）。

物化视图列（工单原文【本单范围】）：
  org_id, site_id, template_id, version_no, step_key, month,
  step_runs, overdue_runs, overdue_rate, p50_minutes, p90_minutes, max_minutes, anomaly_count

★ 所有口径常量都从 pkg/engine.py 取（单一时区偏移、异常阈值、超时比较符、
  未完成步骤的耗时表达式、overdue_rate 分母、是否扣暂停），所以改 engine.py 里一个常量，
  这里生成的 SQL 就真的变了 —— 变异测试才能测到东西。

口径细目见 engine.py 的模块文档与 README。
"""
from engine import (ANOMALY_COND, OVERDUE_COMPARE, PAUSE_DEDUCT, PCT_FILTER,
                    RATE_DENOMINATOR, TZ_OFFSET_HOURS, UNFINISHED_NET_EXPR)

MV_NAME = "mv_sop_step_sla"
PARAM_TABLE = "sla_refresh_param"
ANOMALY_MAX_MINUTES = 30 * 24 * 60      # 30 天
ANOMALY_MIN_MINUTES = 0                 # <0 即异常

MV_SQL = r"""
CREATE MATERIALIZED VIEW {mv} AS
WITH p AS (
    -- 单行参数表：这一轮刷新的统计时点
    SELECT as_of FROM {param}
),
runs AS (
    -- 只取 as_of 之前已开始、且未软删除的运行
    SELECT r.*
      FROM sop_step_runs r, p
     WHERE r.deleted_at IS NULL
       AND r.started_at <= p.as_of
),
pause_agg AS (
    -- 每个 run 的暂停总秒数。
    -- 用 range_agg 把暂停区间取并集，重叠暂停不会被重复扣（自己写 gap-and-islands 易错）。
    -- 区间先 clip 到 [started_at, COALESCE(finished_at, as_of)]：暂停跨出执行区间部分不应扣。
    SELECT r.id AS run_id,
           COALESCE((
               SELECT EXTRACT(EPOCH FROM COALESCE(SUM(upper(x) - lower(x)), interval '0'))
                 FROM unnest(pa.mr) AS x
           ), 0) AS pause_seconds
      FROM runs r
      CROSS JOIN p
      LEFT JOIN LATERAL (
          SELECT range_agg(tstzrange(
                     GREATEST(r.started_at, s.paused_at),
                     LEAST(COALESCE(s.resumed_at, p.as_of),
                           COALESCE(r.finished_at, p.as_of)),
                     '[)')) AS mr
            FROM sop_step_pauses s
           WHERE s.run_id = r.id
             AND s.deleted_at IS NULL
             AND GREATEST(r.started_at, s.paused_at) <
                 LEAST(COALESCE(s.resumed_at, p.as_of), COALESCE(r.finished_at, p.as_of))
      ) pa ON TRUE
),
calc AS (
    SELECT r.org_id, r.site_id, r.template_id, r.version_no, r.step_key,
           -- 固定偏移 +08:00，不用 AT TIME ZONE 'Asia/Shanghai'：
           -- 后者依赖数据库安装里的 tzdata，嵌入式 PostgreSQL（pgserver）不带，
           -- 会报 time zone "Asia/Shanghai" not recognized。Asia/Shanghai 自 1991 年起
           -- 无夏令时，2026 年恒为 +08:00，固定偏移与命名时区等价。
           date_trunc('month', r.started_at AT TIME ZONE interval '{tz} hours')::date AS month,
           r.id AS run_id,
           (r.due_at IS NOT NULL) AS has_due,
           CASE
             WHEN r.due_at IS NULL THEN FALSE
             WHEN r.finished_at IS NOT NULL THEN r.finished_at {cmp_} r.due_at
             ELSE (SELECT as_of FROM p) {cmp_} r.due_at
           END AS overdue,
           -- 未完成不计算耗时（否则耗时会随 as_of 漂移，与 AC3 口径冲突）
           CASE
             WHEN r.finished_at IS NULL THEN {unfinished}
             ELSE ROUND(EXTRACT(EPOCH FROM (r.finished_at - r.started_at
                        - {pause_secs} * interval '1 second')) / 60.0)
           END AS net_minutes
      FROM runs r
      JOIN pause_agg pa ON pa.run_id = r.id
)
SELECT org_id, site_id, template_id, version_no, step_key, month,
       COUNT(*)                                        AS step_runs,
       COUNT(*) FILTER (WHERE overdue)                 AS overdue_runs,
       CASE WHEN COUNT(*) FILTER (WHERE has_due) = 0 THEN NULL
            ELSE ROUND(COUNT(*) FILTER (WHERE overdue)::numeric
                       / COUNT(*) {rate_denom}, 6) END AS overdue_rate,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY net_minutes)
           FILTER (WHERE {pct}) AS p50_minutes,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY net_minutes)
           FILTER (WHERE {pct}) AS p90_minutes,
       MAX(net_minutes) FILTER (WHERE {pct}) AS max_minutes,
       COUNT(*) FILTER (WHERE {anom}) AS anomaly_count
  FROM calc
 GROUP BY org_id, site_id, template_id, version_no, step_key, month
""".format(mv=MV_NAME, param=PARAM_TABLE,
           tz=TZ_OFFSET_HOURS,
           cmp_=OVERDUE_COMPARE,
           unfinished=UNFINISHED_NET_EXPR,
           pause_secs=("pa.pause_seconds" if PAUSE_DEDUCT else "0"),
           rate_denom=RATE_DENOMINATOR,
           pct=PCT_FILTER,
           anom=ANOMALY_COND)

MV_INDEXES = [
    "CREATE UNIQUE INDEX ux_mv_sla_key ON %s (org_id, site_id, template_id, version_no, step_key, month)" % MV_NAME,
    "CREATE INDEX ix_mv_sla_month ON %s (month)" % MV_NAME,
]

REFRESH_FN = "refresh_mv_sop_step_sla"

REFRESH_SQL = r"""
CREATE OR REPLACE FUNCTION {fn}(p_as_of timestamptz)
RETURNS TABLE(as_of timestamptz, rows_refreshed bigint, refreshed_at timestamptz)
LANGUAGE plpgsql AS $$
DECLARE
    v_rows bigint;
    v_now timestamptz := now();
BEGIN
    IF p_as_of IS NULL THEN
        RAISE EXCEPTION 'as_of 不能为空：超时判定依赖统计时点';
    END IF;

    -- 参数表只允许一行；用 INSERT ... ON CONFLICT 保证幂等
    INSERT INTO {param} AS t (id, as_of, refreshed_at)
    VALUES (TRUE, p_as_of, v_now)
    ON CONFLICT (id) DO UPDATE SET as_of = EXCLUDED.as_of, refreshed_at = EXCLUDED.refreshed_at;

    REFRESH MATERIALIZED VIEW {mv};

    SELECT count(*) INTO v_rows FROM {mv};
    RETURN QUERY SELECT p_as_of, v_rows, v_now;
END;
$$;
""".format(fn=REFRESH_FN, param=PARAM_TABLE, mv=MV_NAME)
