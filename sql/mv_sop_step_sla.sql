
CREATE MATERIALIZED VIEW mv_sop_step_sla AS
WITH p AS (
    -- 单行参数表：这一轮刷新的统计时点
    SELECT as_of FROM sla_refresh_param
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
           date_trunc('month', r.started_at AT TIME ZONE interval '8 hours')::date AS month,
           r.id AS run_id,
           (r.due_at IS NOT NULL) AS has_due,
           CASE
             WHEN r.due_at IS NULL THEN FALSE
             WHEN r.finished_at IS NOT NULL THEN r.finished_at > r.due_at
             ELSE (SELECT as_of FROM p) > r.due_at
           END AS overdue,
           -- 未完成不计算耗时（否则耗时会随 as_of 漂移，与 AC3 口径冲突）
           CASE
             WHEN r.finished_at IS NULL THEN NULL
             ELSE ROUND(EXTRACT(EPOCH FROM (r.finished_at - r.started_at
                        - pa.pause_seconds * interval '1 second')) / 60.0)
           END AS net_minutes
      FROM runs r
      JOIN pause_agg pa ON pa.run_id = r.id
)
SELECT org_id, site_id, template_id, version_no, step_key, month,
       COUNT(*)                                        AS step_runs,
       COUNT(*) FILTER (WHERE overdue)                 AS overdue_runs,
       CASE WHEN COUNT(*) FILTER (WHERE has_due) = 0 THEN NULL
            ELSE ROUND(COUNT(*) FILTER (WHERE overdue)::numeric
                       / COUNT(*) FILTER (WHERE has_due), 6) END AS overdue_rate,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY net_minutes)
           FILTER (WHERE net_minutes IS NOT NULL AND net_minutes >= 0 AND net_minutes <= 43200) AS p50_minutes,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY net_minutes)
           FILTER (WHERE net_minutes IS NOT NULL AND net_minutes >= 0 AND net_minutes <= 43200) AS p90_minutes,
       MAX(net_minutes) FILTER (WHERE net_minutes IS NOT NULL AND net_minutes >= 0 AND net_minutes <= 43200) AS max_minutes,
       COUNT(*) FILTER (WHERE net_minutes IS NOT NULL AND (net_minutes < 0 OR net_minutes > 43200)) AS anomaly_count
  FROM calc
 GROUP BY org_id, site_id, template_id, version_no, step_key, month
