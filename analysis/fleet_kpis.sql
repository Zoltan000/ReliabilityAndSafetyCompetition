-- Fleet KPI analysis of the full historical Parquet file (DuckDB).
-- Run from the repo root: uv run --no-project --with duckdb python analysis/run_sql.py analysis/fleet_kpis.sql

CREATE OR REPLACE VIEW fleet AS
SELECT * FROM read_parquet('2026-09_compet_Student_Historical_Data_V03.parquet');

-- Failures only, with the previous same-component failure on the same conveyor
CREATE OR REPLACE TEMP TABLE failures AS
SELECT Conveyor_ID, Plant_ID, Load_Class, Bearing_Count, Date, Failure_Type, Failed_Component_ID,
       Cumulative_Operating_Hours AS cum_op_h,
       Cumulative_Start_Stop_Cycles AS cum_cycles,
       Cumulative_kg AS cum_kg,
       Age_Calendar_Days AS age_days,
       Cumulative_Operating_Hours - COALESCE(LAG(Cumulative_Operating_Hours) OVER w, 0) AS op_h_between,
       Age_Calendar_Days - COALESCE(LAG(Age_Calendar_Days) OVER w, 0) AS days_between,
       LAG(Date) OVER w IS NULL AS first_of_type
FROM fleet
WHERE Daily_State = 'FAILURE_DAY'
WINDOW w AS (PARTITION BY Conveyor_ID, Failure_Type ORDER BY Date);

-- Q1 Data sanity
SELECT '1. Data sanity' AS section;
SELECT count(*) AS n_rows, count(DISTINCT Conveyor_ID) AS conveyors, count(DISTINCT Plant_ID) AS plants,
       min(Date) AS first_day, max(Date) AS last_day,
       count(*) FILTER (Operating_Hours_Day > 0 AND Motor_Current_A IS NULL) AS missing_cm_when_running
FROM fleet;
SELECT Daily_State, count(*) AS days, round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct_days,
       sum(Operating_Hours_Day) AS op_h, sum(Downtime_Hours_Day) AS downtime_h
FROM fleet GROUP BY 1 ORDER BY days DESC;

-- Q2 Failures per type
SELECT '2. Failures per type' AS section;
SELECT Failure_Type, count(*) AS failures,
       round(100.0*count(*)/sum(count(*)) OVER (),2) AS pct,
       round(count(*) / (284*20.0), 2) AS per_conveyor_year
FROM failures GROUP BY 1 ORDER BY failures DESC;
SELECT (SELECT count(*) FROM failures) AS failure_rows,
       (SELECT sum(m) FROM (SELECT max(Cumulative_Failure_Count) m FROM fleet GROUP BY Conveyor_ID)) AS sum_cum_failure_count;

-- Q3 Conveyor belt operating hours
SELECT '3a. Cumulative operating hours (conveyor total) at each Conveyor_Belt failure' AS section;
SELECT count(*) AS n, round(avg(cum_op_h),1) AS mean_h, round(stddev_samp(cum_op_h),1) AS std_h,
       min(cum_op_h) AS min_h, round(median(cum_op_h),1) AS median_h, max(cum_op_h) AS max_h
FROM failures WHERE Failure_Type = 'Conveyor_Belt';
SELECT '3b. Operating hours between belt failures (belt life, first one from EIS)' AS section;
SELECT CASE WHEN first_of_type THEN 'first (from EIS)' ELSE 'subsequent' END AS interval_kind,
       count(*) AS n, round(avg(op_h_between),1) AS mean_h, round(stddev_samp(op_h_between),1) AS std_h,
       min(op_h_between) AS min_h, round(median(op_h_between),1) AS median_h, max(op_h_between) AS max_h
FROM failures WHERE Failure_Type = 'Conveyor_Belt' GROUP BY ROLLUP (1) ORDER BY 1 NULLS LAST;
SELECT '3c. Cumulative operating hours per conveyor at end of history (2024-12-31)' AS section;
SELECT count(*) AS conveyors, round(avg(h),1) AS mean_h, round(stddev_samp(h),1) AS std_h, min(h) AS min_h, max(h) AS max_h
FROM (SELECT max(Cumulative_Operating_Hours) h FROM fleet GROUP BY Conveyor_ID);

-- Q4 Per-component reliability KPIs (repair downtime = failure day 12h + following corrective days)
SELECT '4. Per-component MTBF and repair downtime' AS section;
CREATE OR REPLACE TEMP TABLE episodes AS
WITH g AS (
  SELECT Conveyor_ID, Daily_State, Downtime_Hours_Day, Failure_Type,
         sum(CASE WHEN Daily_State='FAILURE_DAY' THEN 1 ELSE 0 END) OVER (PARTITION BY Conveyor_ID ORDER BY Date) AS ep
  FROM fleet WHERE Daily_State IN ('FAILURE_DAY','CORRECTIVE_DOWNTIME')
)
SELECT Conveyor_ID, ep, max(Failure_Type) AS Failure_Type, sum(Downtime_Hours_Day) AS downtime_h
FROM g WHERE ep > 0 GROUP BY 1,2;
SELECT f.Failure_Type, f.failures,
       f.mtbf_op_h, f.std_tbf_op_h, f.mtbf_days, f.std_tbf_days,
       e.mean_repair_h, e.std_repair_h, e.max_repair_h, e.total_downtime_h,
       round(100.0*e.total_downtime_h/sum(e.total_downtime_h) OVER (),1) AS pct_of_corrective_downtime
FROM (SELECT Failure_Type, count(*) failures,
             round(avg(op_h_between) FILTER (NOT first_of_type),0) mtbf_op_h,
             round(stddev_samp(op_h_between) FILTER (NOT first_of_type),0) std_tbf_op_h,
             round(avg(days_between) FILTER (NOT first_of_type),0) mtbf_days,
             round(stddev_samp(days_between) FILTER (NOT first_of_type),0) std_tbf_days
      FROM failures GROUP BY 1) f
JOIN (SELECT Failure_Type, round(avg(downtime_h),1) mean_repair_h, round(stddev_samp(downtime_h),1) std_repair_h,
             max(downtime_h) max_repair_h, sum(downtime_h) total_downtime_h
      FROM episodes GROUP BY 1) e USING (Failure_Type)
ORDER BY failures DESC;

-- Q5 Availability and downtime
SELECT '5. Availability (operating h / calendar h)' AS section;
SELECT 'FLEET' AS grp, round(100*sum(Operating_Hours_Day)/(24.0*count(*)),2) AS availability_pct,
       round(sum(Downtime_Hours_Day) FILTER (Daily_State<>'PLANNED_MAINTENANCE')/284/20,1) AS corrective_dt_h_per_conv_year,
       round(sum(Downtime_Hours_Day) FILTER (Daily_State='PLANNED_MAINTENANCE')/284/20,1) AS planned_dt_h_per_conv_year
FROM fleet
UNION ALL
SELECT 'Load ' || Load_Class, round(100*sum(Operating_Hours_Day)/(24.0*count(*)),2),
       round(sum(Downtime_Hours_Day) FILTER (Daily_State<>'PLANNED_MAINTENANCE')/count(DISTINCT Conveyor_ID)/20,1),
       round(sum(Downtime_Hours_Day) FILTER (Daily_State='PLANNED_MAINTENANCE')/count(DISTINCT Conveyor_ID)/20,1)
FROM fleet GROUP BY Load_Class
UNION ALL
SELECT 'Plant ' || Plant_ID, round(100*sum(Operating_Hours_Day)/(24.0*count(*)),2),
       round(sum(Downtime_Hours_Day) FILTER (Daily_State<>'PLANNED_MAINTENANCE')/count(DISTINCT Conveyor_ID)/20,1),
       round(sum(Downtime_Hours_Day) FILTER (Daily_State='PLANNED_MAINTENANCE')/count(DISTINCT Conveyor_ID)/20,1)
FROM fleet GROUP BY Plant_ID
ORDER BY 1;

-- Q6 Failure rate per 10k operating hours by load class x component
SELECT '6. Failures per 10k operating hours by Load_Class' AS section;
WITH exp AS (SELECT Load_Class, sum(Operating_Hours_Day) op_h, count(DISTINCT Conveyor_ID) conv FROM fleet GROUP BY 1)
SELECT f.Load_Class, e.conv AS conveyors, f.Failure_Type, round(1e4*count(*)/e.op_h,3) AS rate_per_10k_h
FROM failures f JOIN exp e USING (Load_Class)
GROUP BY f.Load_Class, e.conv, e.op_h, f.Failure_Type
ORDER BY f.Failure_Type, f.Load_Class;
SELECT '6b. Failures per conveyor-year by plant' AS section;
SELECT Plant_ID, count(DISTINCT Conveyor_ID) AS conveyors,
       round(count(*) / (count(DISTINCT Conveyor_ID)*20.0),2) AS failures_per_conv_year
FROM failures GROUP BY 1 ORDER BY 3 DESC;

-- Q7 Trends
SELECT '7. Failures per year by component (fleet ageing)' AS section;
PIVOT (SELECT year(Date) AS yr, Failure_Type FROM failures) ON Failure_Type USING count(*) GROUP BY yr ORDER BY yr;
SELECT '7b. Conveyors with most / fewest failures' AS section;
(SELECT 'most' AS kind, Conveyor_ID, Plant_ID, Load_Class, count(*) AS failures FROM failures GROUP BY ALL ORDER BY failures DESC LIMIT 5)
UNION ALL
(SELECT 'fewest', Conveyor_ID, Plant_ID, Load_Class, count(*) FROM failures GROUP BY ALL ORDER BY 5 ASC LIMIT 5);

-- Q8 Other
SELECT '8. Bearings, sensor replacements, planned maintenance' AS section;
SELECT round(avg(Bearing_Count),1) AS avg_bearings_per_conveyor,
       (SELECT count(*) FROM failures WHERE Failure_Type='Bearing') AS bearing_failures,
       round((SELECT count(*) FROM failures WHERE Failure_Type='Bearing') / sum(Bearing_Count),3) AS failures_per_bearing_20y,
       (SELECT count(DISTINCT Conveyor_ID || Failed_Component_ID) FROM failures WHERE Failure_Type='Bearing') AS distinct_bearings_failed,
       (SELECT sum(Sensor_Replacement) FROM fleet) AS sensor_replacements,
       (SELECT count(*) FROM failures WHERE Failure_Type='Speed_Sensor') AS speed_sensor_failures
FROM (SELECT DISTINCT Conveyor_ID, Bearing_Count FROM fleet);
SELECT 'planned maintenance episodes' AS metric, count(*) AS n,
       round(count(*)/284.0/20,2) AS per_conveyor_year, round(avg(len),2) AS mean_days
FROM (SELECT Conveyor_ID, count(*) len FROM (
        SELECT Conveyor_ID, Daily_State,
               row_number() OVER (PARTITION BY Conveyor_ID ORDER BY Date)
             - row_number() OVER (PARTITION BY Conveyor_ID, Daily_State ORDER BY Date) AS grp
        FROM fleet) WHERE Daily_State='PLANNED_MAINTENANCE' GROUP BY Conveyor_ID, grp);
