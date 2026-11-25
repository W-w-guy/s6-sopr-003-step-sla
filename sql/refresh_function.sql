
CREATE OR REPLACE FUNCTION refresh_mv_sop_step_sla(p_as_of timestamptz)
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
    INSERT INTO sla_refresh_param AS t (id, as_of, refreshed_at)
    VALUES (TRUE, p_as_of, v_now)
    ON CONFLICT (id) DO UPDATE SET as_of = EXCLUDED.as_of, refreshed_at = EXCLUDED.refreshed_at;

    REFRESH MATERIALIZED VIEW mv_sop_step_sla;

    SELECT count(*) INTO v_rows FROM mv_sop_step_sla;
    RETURN QUERY SELECT p_as_of, v_rows, v_now;
END;
$$;
