"""EDA checks that decide modeling choices (plan step 1). Prints compact results only.

Run from the repo root: .venv/Scripts/python scripts/00_eda_checks.py
"""
import duckdb

FLEET = "2026-09_compet_Student_Historical_Data_V03.parquet"
con = duckdb.connect()
con.sql(f"CREATE VIEW fleet AS SELECT * FROM read_parquet('{FLEET}')")
con.sql("""
CREATE TEMP TABLE f AS
SELECT *, CASE WHEN month(Date) IN (12,1,2) THEN 'DJF' WHEN month(Date) IN (3,4,5) THEN 'MAM'
               WHEN month(Date) IN (6,7,8) THEN 'JJA' ELSE 'SON' END AS season
FROM fleet
""")


def show(title, sql, rows=30):
    print(f"\n## {title}")
    con.sql(sql).show(max_rows=rows, max_width=200)


show("Static attributes constant per conveyor (n conveyors violating)", """
SELECT count(*) FILTER (WHERE n_load>1) load_varies, count(*) FILTER (WHERE n_brg>1) brg_varies,
       count(*) FILTER (WHERE n_eis>1) eis_varies, count(*) FILTER (WHERE n_len>1) len_varies
FROM (SELECT Conveyor_ID, count(DISTINCT Load_Class) n_load, count(DISTINCT Bearing_Count) n_brg,
             count(DISTINCT EIS_Date) n_eis, count(DISTINCT Length_m) n_len FROM f GROUP BY 1)""")

show("Load class per plant, conveyor ID range and gaps", """
SELECT Plant_ID, string_agg(DISTINCT Load_Class, ',') loads, count(DISTINCT Conveyor_ID) n,
       min(CAST(substr(Conveyor_ID, 6) AS INT)) id_min, max(CAST(substr(Conveyor_ID, 6) AS INT)) id_max,
       min(Bearing_Count) brg_min, max(Bearing_Count) brg_max
FROM f GROUP BY 1 ORDER BY 1""")

show("Weather shared within plant-date? (max distinct values per plant-date)", """
SELECT max(nt) temp_max_distinct, max(nh) humid_distinct, max(nv) volt_distinct FROM
(SELECT Plant_ID, Date, count(DISTINCT Temperature_Max_C) nt, count(DISTINCT Humidity_pct) nh,
        count(DISTINCT Voltage_V) nv FROM f GROUP BY 1,2)""")

show("Season levels per plant (Temp max mean), humidity & voltage", """
PIVOT (SELECT Plant_ID, season, round(avg(Temperature_Max_C),2) t FROM f GROUP BY 1,2)
ON season IN ('DJF','MAM','JJA','SON') USING first(t) ORDER BY Plant_ID""")
show("Humidity / voltage per plant (mean, within-plant sd) and voltage by season", """
SELECT Plant_ID, round(avg(Humidity_pct),2) hum, round(stddev(Humidity_pct),2) hum_sd,
       round(avg(Voltage_V),1) volt, round(stddev(Voltage_V),2) volt_sd,
       round(avg(Voltage_V) FILTER (WHERE season='DJF'),1) v_djf, round(avg(Voltage_V) FILTER (WHERE season='JJA'),1) v_jja
FROM f GROUP BY 1 ORDER BY 1""")

show("Temperature residual vs plant-season mean: sd, lag-1 autocorr, year-to-year sd of season means", """
WITH m AS (SELECT Plant_ID, season, avg(Temperature_Max_C) mu FROM f GROUP BY 1,2),
r AS (SELECT f.Conveyor_ID, f.Date, f.Temperature_Max_C - m.mu res FROM f JOIN m USING (Plant_ID, season)),
l AS (SELECT res, lag(res) OVER (PARTITION BY Conveyor_ID ORDER BY Date) res1 FROM r),
y AS (SELECT Plant_ID, season, year(Date) yr, avg(Temperature_Max_C) ym FROM f GROUP BY 1,2,3)
SELECT (SELECT round(stddev(res),3) FROM r) res_sd, (SELECT round(corr(res,res1),3) FROM l) lag1_corr,
       (SELECT round(avg(s),3) FROM (SELECT stddev(ym) s FROM y GROUP BY Plant_ID, season)) yearly_sd""")

show("Exact season step dates: mean Temp max by day-of-month around boundaries (plant P01, all years)", """
SELECT strftime(Date, '%m-%d') md, round(avg(Temperature_Max_C),2) t FROM f
WHERE Plant_ID='P01' AND strftime(Date, '%m-%d') IN ('02-26','02-28','03-01','03-02','03-05','05-29','05-31','06-01','06-03','08-29','08-31','09-01','09-03','11-29','11-30','12-01','12-03')
GROUP BY 1 ORDER BY 1""")

show("Planned maintenance: month-day pattern per plant (distinct month-days, share of conveyors)", """
SELECT Plant_ID, count(DISTINCT strftime(Date,'%m-%d')) n_md, string_agg(DISTINCT strftime(Date,'%m-%d'), ' ' ORDER BY strftime(Date,'%m-%d')) mds
FROM f WHERE Daily_State='PLANNED_MAINTENANCE' GROUP BY 1 ORDER BY 1""")
show("PM: does each conveyor use the same month-days every year?", """
SELECT count(*) conveyors, sum((n_md=3)::INT) same_3_dates_each_year, min(n_md), max(n_md) FROM
(SELECT Conveyor_ID, count(DISTINCT strftime(Date,'%m-%d')) n_md FROM f WHERE Daily_State='PLANNED_MAINTENANCE' GROUP BY 1)""")

show("State transitions: previous day state before FAILURE_DAY, next day state after FAILURE_DAY", """
WITH s AS (SELECT Daily_State st, lag(Daily_State) OVER w prv, lead(Daily_State) OVER w nxt,
                  lead(Daily_State, 2) OVER w nxt2 FROM f WINDOW w AS (PARTITION BY Conveyor_ID ORDER BY Date))
SELECT prv, nxt, nxt2, count(*) n FROM s WHERE st='FAILURE_DAY' GROUP BY ALL ORDER BY n DESC""", rows=15)

show("Failure day fields: operating h, cycles, since-restart h (distribution)", """
SELECT Failure_Type, count(*) n, round(avg(Operating_Hours_Since_Restart),1) avg_since_restart_h,
       round(avg((Operating_Hours_Since_Restart<=12)::INT),3) share_first_day_after_restart,
       round(avg(Start_Stop_Cycles_Day),3) avg_cycles
FROM f WHERE Daily_State='FAILURE_DAY' GROUP BY 1 ORDER BY n DESC""")

show("Share of RUNNING days that are first day after restart, and base rate of failure by since-restart bucket", """
SELECT least(floor(Operating_Hours_Since_Restart/24),10) d_since_restart,
       count(*) n_days, round(avg((Daily_State='FAILURE_DAY')::INT),4) p_fail
FROM f WHERE Daily_State IN ('RUNNING','FAILURE_DAY') GROUP BY 1 ORDER BY 1""", rows=12)

show("Operating hours on RUNNING days and cycles", """
SELECT round(avg(Operating_Hours_Day),3) avg_h, min(Operating_Hours_Day) min_h, max(Operating_Hours_Day) max_h,
       round(avg(Start_Stop_Cycles_Day),3) cyc, max(Start_Stop_Cycles_Day) max_cyc
FROM f WHERE Daily_State='RUNNING'""")

show("Sensor replacement vs speed-sensor failures; component IDs used by type", """
SELECT Failure_Type, count(*) n, sum(Sensor_Replacement) sensor_repl, count(Failed_Component_ID) with_id,
       min(Failed_Component_ID) id_min, max(Failed_Component_ID) id_max
FROM f WHERE Daily_State='FAILURE_DAY' OR Sensor_Replacement=1 GROUP BY 1 ORDER BY n DESC""")
