"""Plot seasonal weather cycles from fleet data.

Aggregates temperature and humidity by day-of-year across all years, plants,
and conveyors, showing cross-plant variation as shaded bands. Produces a
two-panel figure: Temperature (max/min) and Humidity.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib python analysis/plot_weather_seasonality.py
"""
import duckdb
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# Path to fleet parquet (repo root)
fleet_parquet = "2026-09_compet_Student_Historical_Data_V03.parquet"

con = duckdb.connect()

# Step 1: Per plant and day-of-year, compute mean temp/humidity.
print("Aggregating fleet data by plant and day-of-year...")
plant_doy = con.sql(f"""
SELECT
  Plant_ID,
  date_part('doy', Date)::INTEGER as doy,
  avg(Temperature_Max_C) as temp_max,
  avg(Temperature_Min_C) as temp_min,
  avg(Humidity_pct) as humidity
FROM read_parquet('{fleet_parquet}')
WHERE Temperature_Max_C IS NOT NULL
  AND Temperature_Min_C IS NOT NULL
  AND Humidity_pct IS NOT NULL
GROUP BY Plant_ID, doy
ORDER BY doy, Plant_ID
""")

# Step 2: Per day-of-year, compute mean and stddev across plants.
print("Summarizing across plants...")
doy_summary = con.sql("""
SELECT
  doy,
  avg(temp_max) as temp_max_mean,
  stddev_pop(temp_max) as temp_max_std,
  avg(temp_min) as temp_min_mean,
  stddev_pop(temp_min) as temp_min_std,
  avg(humidity) as humidity_mean,
  stddev_pop(humidity) as humidity_std
FROM plant_doy
GROUP BY doy
ORDER BY doy
""")

results = doy_summary.fetchall()
print(f"Got {len(results)} day-of-year records.")

# Extract columns
doy_vals = [r[0] for r in results]
temp_max_means = [r[1] for r in results]
temp_max_stds = [r[2] or 0 for r in results]
temp_min_means = [r[3] for r in results]
temp_min_stds = [r[4] or 0 for r in results]
humidity_means = [r[5] for r in results]
humidity_stds = [r[6] or 0 for r in results]

# Apply 7-day centered rolling mean to smooth.
def rolling_mean(arr, window=7):
    smoothed = []
    for i in range(len(arr)):
        start = max(0, i - window // 2)
        end = min(len(arr), i + window // 2 + 1)
        smoothed.append(sum(arr[start:end]) / (end - start))
    return smoothed

temp_max_smooth = rolling_mean(temp_max_means)
temp_min_smooth = rolling_mean(temp_min_means)
humidity_smooth = rolling_mean(humidity_means)

# Create figure: two stacked panels.
fig, (ax_temp, ax_humid) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

# --- Panel 1: Temperature ---
ax_temp.fill_between(
    doy_vals,
    [m - s for m, s in zip(temp_max_smooth, temp_max_stds)],
    [m + s for m, s in zip(temp_max_smooth, temp_max_stds)],
    alpha=0.25,
    color='red',
    label='Temp Max ±1σ (cross-plant)'
)
ax_temp.plot(doy_vals, temp_max_smooth, color='red', linewidth=2, label='Temp Max (mean)')

ax_temp.fill_between(
    doy_vals,
    [m - s for m, s in zip(temp_min_smooth, temp_min_stds)],
    [m + s for m, s in zip(temp_min_smooth, temp_min_stds)],
    alpha=0.25,
    color='blue',
    label='Temp Min ±1σ (cross-plant)'
)
ax_temp.plot(doy_vals, temp_min_smooth, color='blue', linewidth=2, label='Temp Min (mean)')

ax_temp.set_ylabel('Temperature (°C)', fontsize=11, fontweight='bold')
ax_temp.legend(loc='upper left', fontsize=9)
ax_temp.grid(True, alpha=0.3)
ax_temp.set_title('Seasonal Weather Cycles (Fleet Average, 20 Years, 12 Plants)',
                   fontsize=12, fontweight='bold')

# --- Panel 2: Humidity ---
ax_humid.fill_between(
    doy_vals,
    [m - s for m, s in zip(humidity_smooth, humidity_stds)],
    [m + s for m, s in zip(humidity_smooth, humidity_stds)],
    alpha=0.25,
    color='green',
)
ax_humid.plot(doy_vals, humidity_smooth, color='green', linewidth=2, label='Humidity (mean)')
ax_humid.set_ylabel('Humidity (%)', fontsize=11, fontweight='bold')
ax_humid.set_xlabel('Day of Year', fontsize=11, fontweight='bold')
ax_humid.legend(loc='upper left', fontsize=9)
ax_humid.grid(True, alpha=0.3)

# Set x-axis ticks at month boundaries.
month_doys = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366]
month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Dec']
ax_humid.set_xticks(month_doys)
ax_humid.set_xticklabels(month_labels, fontsize=10)
ax_humid.set_xlim(0, 366)

plt.tight_layout()
plt.savefig('analysis/weather_seasonality.png', dpi=150, bbox_inches='tight')
print("Saved: analysis/weather_seasonality.png")
