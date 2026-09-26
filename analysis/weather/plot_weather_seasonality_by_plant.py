"""Plot seasonal weather cycles per plant.

Generates a 4x3 grid (12 subplots) showing temperature and humidity seasonal
patterns for each plant individually. Allows comparison of seasonal cycles
across the 12 plants in the fleet.

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib python analysis/plot_weather_seasonality_by_plant.py
"""
import duckdb
import matplotlib.pyplot as plt
import numpy as np

fleet_parquet = "2026-09_compet_Student_Historical_Data_V03.parquet"

con = duckdb.connect()

# Get list of unique plants
plants_result = con.sql(f"""
SELECT DISTINCT Plant_ID FROM read_parquet('{fleet_parquet}')
ORDER BY Plant_ID
""")
plants = [r[0] for r in plants_result.fetchall()]
print(f"Found {len(plants)} plants: {plants}")

# For each plant, aggregate by day-of-year
plant_data = {}
for plant_id in plants:
    result = con.sql(f"""
    SELECT
      date_part('doy', Date)::INTEGER as doy,
      avg(Temperature_Max_C) as temp_max,
      stddev_pop(Temperature_Max_C) as temp_max_std,
      avg(Temperature_Min_C) as temp_min,
      stddev_pop(Temperature_Min_C) as temp_min_std,
      avg(Humidity_pct) as humidity,
      stddev_pop(Humidity_pct) as humidity_std
    FROM read_parquet('{fleet_parquet}')
    WHERE Plant_ID = '{plant_id}'
      AND Temperature_Max_C IS NOT NULL
      AND Temperature_Min_C IS NOT NULL
      AND Humidity_pct IS NOT NULL
    GROUP BY doy
    ORDER BY doy
    """)

    rows = result.fetchall()
    plant_data[plant_id] = {
        'doy': [r[0] for r in rows],
        'temp_max': [r[1] for r in rows],
        'temp_max_std': [r[2] or 0 for r in rows],
        'temp_min': [r[3] for r in rows],
        'temp_min_std': [r[4] or 0 for r in rows],
        'humidity': [r[5] for r in rows],
        'humidity_std': [r[6] or 0 for r in rows],
    }

# Apply 7-day rolling mean
def rolling_mean(arr, window=7):
    smoothed = []
    for i in range(len(arr)):
        start = max(0, i - window // 2)
        end = min(len(arr), i + window // 2 + 1)
        smoothed.append(sum(arr[start:end]) / (end - start))
    return smoothed

for plant_id in plants:
    plant_data[plant_id]['temp_max_smooth'] = rolling_mean(plant_data[plant_id]['temp_max'])
    plant_data[plant_id]['temp_max_std_smooth'] = rolling_mean(plant_data[plant_id]['temp_max_std'])
    plant_data[plant_id]['temp_min_smooth'] = rolling_mean(plant_data[plant_id]['temp_min'])
    plant_data[plant_id]['temp_min_std_smooth'] = rolling_mean(plant_data[plant_id]['temp_min_std'])
    plant_data[plant_id]['humidity_smooth'] = rolling_mean(plant_data[plant_id]['humidity'])
    plant_data[plant_id]['humidity_std_smooth'] = rolling_mean(plant_data[plant_id]['humidity_std'])

# Create 4x3 grid
fig, axes = plt.subplots(4, 3, figsize=(16, 14))
axes = axes.flatten()

# Month boundaries for x-axis
month_doys = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366]
month_labels = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D', 'J']

for idx, plant_id in enumerate(plants):
    ax = axes[idx]
    doy = plant_data[plant_id]['doy']

    # Temperature on left y-axis
    ax_temp = ax

    # Temp Max with ±1σ band
    temp_max_upper = [m + s for m, s in zip(plant_data[plant_id]['temp_max_smooth'], plant_data[plant_id]['temp_max_std_smooth'])]
    temp_max_lower = [m - s for m, s in zip(plant_data[plant_id]['temp_max_smooth'], plant_data[plant_id]['temp_max_std_smooth'])]
    ax_temp.fill_between(doy, temp_max_lower, temp_max_upper, alpha=0.2, color='red')
    ax_temp.plot(doy, plant_data[plant_id]['temp_max_smooth'], color='red', linewidth=1.5, label='Temp Max')

    # Temp Min with ±1σ band
    temp_min_upper = [m + s for m, s in zip(plant_data[plant_id]['temp_min_smooth'], plant_data[plant_id]['temp_min_std_smooth'])]
    temp_min_lower = [m - s for m, s in zip(plant_data[plant_id]['temp_min_smooth'], plant_data[plant_id]['temp_min_std_smooth'])]
    ax_temp.fill_between(doy, temp_min_lower, temp_min_upper, alpha=0.2, color='blue')
    ax_temp.plot(doy, plant_data[plant_id]['temp_min_smooth'], color='blue', linewidth=1.5, label='Temp Min')
    ax_temp.set_ylabel('Temperature (°C)', fontsize=9, color='black')
    ax_temp.tick_params(axis='y', labelcolor='black', labelsize=8)
    ax_temp.set_ylim(18, 27)

    # Humidity on right y-axis
    ax_humid = ax_temp.twinx()

    # Humidity with ±1σ band
    humidity_upper = [m + s for m, s in zip(plant_data[plant_id]['humidity_smooth'], plant_data[plant_id]['humidity_std_smooth'])]
    humidity_lower = [m - s for m, s in zip(plant_data[plant_id]['humidity_smooth'], plant_data[plant_id]['humidity_std_smooth'])]
    ax_humid.fill_between(doy, humidity_lower, humidity_upper, alpha=0.15, color='green')
    ax_humid.plot(doy, plant_data[plant_id]['humidity_smooth'], color='green', linewidth=1.5,
                  linestyle='--', label='Humidity')
    ax_humid.set_ylabel('Humidity (%)', fontsize=9, color='green')
    ax_humid.tick_params(axis='y', labelcolor='green', labelsize=8)
    ax_humid.set_ylim(40, 55)

    # Formatting
    ax_temp.set_xticks(month_doys)
    ax_temp.set_xticklabels(month_labels, fontsize=8)
    ax_temp.set_xlim(0, 366)
    ax_temp.grid(True, alpha=0.2, linestyle=':')
    ax_temp.set_title(f'Plant {plant_id}', fontsize=10, fontweight='bold')

    # Legend on first panel only
    if idx == 0:
        lines1, labels1 = ax_temp.get_legend_handles_labels()
        lines2, labels2 = ax_humid.get_legend_handles_labels()
        ax_temp.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8)

fig.suptitle('Seasonal Weather Cycles by Plant (20-Year Fleet Data)',
             fontsize=14, fontweight='bold', y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig('analysis/weather_seasonality_by_plant.png', dpi=150, bbox_inches='tight')
print("Saved: analysis/weather_seasonality_by_plant.png")
