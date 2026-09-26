"""Plot humidity vs temperature relationship.

Creates two figures:
1. Fleet-wide scatter plot colored by month, showing Temperature_Max_C vs Humidity_pct
2. 4x3 grid per-plant scatter plots to reveal plant-specific correlations

Usage (repo root):
  uv run --no-project --with duckdb --with matplotlib python analysis/plot_humidity_vs_temperature.py
"""
import duckdb
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

fleet_parquet = "2026-09_compet_Student_Historical_Data_V03.parquet"
con = duckdb.connect()

# ============================================================================
# Figure 1: Fleet-wide scatter plot, colored by month
# ============================================================================
print("Fetching fleet-wide data...")
result = con.sql(f"""
SELECT
  Temperature_Max_C,
  Temperature_Min_C,
  Humidity_pct,
  extract(month from Date) as month
FROM read_parquet('{fleet_parquet}')
WHERE Temperature_Max_C IS NOT NULL
  AND Temperature_Min_C IS NOT NULL
  AND Humidity_pct IS NOT NULL
LIMIT 100000
""")

rows = result.fetchall()
temp_max = [r[0] for r in rows]
temp_min = [r[1] for r in rows]
humidity = [r[2] for r in rows]
months = [r[3] for r in rows]

# Create color map for months
month_colors = {
    1: '#0173B2',  # Jan - blue
    2: '#029E73',  # Feb - green
    3: '#DE8F05',  # Mar - orange
    4: '#CC78BC',  # Apr - purple
    5: '#CA9161',  # May - brown
    6: '#ECE133',  # Jun - yellow
    7: '#56B4E9',  # Jul - light blue
    8: '#F0E442',  # Aug - light yellow
    9: '#D55E00',  # Sep - dark orange
    10: '#009E73', # Oct - dark green
    11: '#0072B2', # Nov - dark blue
    12: '#E69F00'  # Dec - gold
}
month_names = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
               7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}

fig1, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

# Plot 1a: Temp_Max vs Humidity
for month in range(1, 13):
    mask = [m == month for m in months]
    temp_m = [t for t, m in zip(temp_max, mask) if m]
    humid_m = [h for h, m in zip(humidity, mask) if m]
    ax1.scatter(temp_m, humid_m, alpha=0.3, s=10, color=month_colors[month], label=month_names[month])

ax1.set_xlabel('Temperature Max (°C)', fontsize=12, fontweight='bold')
ax1.set_ylabel('Humidity (%)', fontsize=12, fontweight='bold')
ax1.set_title('Fleet-wide: Temperature vs Humidity\n(colored by month)', fontsize=13, fontweight='bold')
ax1.grid(True, alpha=0.3)
ax1.legend(ncol=3, fontsize=9, loc='best')

# Plot 1b: Temp_Min vs Humidity
for month in range(1, 13):
    mask = [m == month for m in months]
    temp_m = [t for t, m in zip(temp_min, mask) if m]
    humid_m = [h for h, m in zip(humidity, mask) if m]
    ax2.scatter(temp_m, humid_m, alpha=0.3, s=10, color=month_colors[month], label=month_names[month])

ax2.set_xlabel('Temperature Min (°C)', fontsize=12, fontweight='bold')
ax2.set_ylabel('Humidity (%)', fontsize=12, fontweight='bold')
ax2.set_title('Fleet-wide: Temperature (Min) vs Humidity\n(colored by month)', fontsize=13, fontweight='bold')
ax2.grid(True, alpha=0.3)
ax2.legend(ncol=3, fontsize=9, loc='best')

plt.tight_layout()
plt.savefig('analysis/humidity_vs_temperature_fleet.png', dpi=150, bbox_inches='tight')
print("Saved: analysis/humidity_vs_temperature_fleet.png")

# ============================================================================
# Figure 2: Per-plant scatter plots
# ============================================================================
print("Fetching per-plant data...")
plants_result = con.sql(f"""
SELECT DISTINCT Plant_ID FROM read_parquet('{fleet_parquet}')
ORDER BY Plant_ID
""")
plants = [r[0] for r in plants_result.fetchall()]

fig2, axes = plt.subplots(4, 3, figsize=(16, 14))
axes = axes.flatten()

for idx, plant_id in enumerate(plants):
    print(f"  Processing {plant_id}...")
    result = con.sql(f"""
    SELECT
      Temperature_Max_C,
      Temperature_Min_C,
      Humidity_pct,
      extract(month from Date) as month
    FROM read_parquet('{fleet_parquet}')
    WHERE Plant_ID = '{plant_id}'
      AND Temperature_Max_C IS NOT NULL
      AND Temperature_Min_C IS NOT NULL
      AND Humidity_pct IS NOT NULL
    """)

    rows = result.fetchall()
    if not rows:
        continue

    temp_max_p = [r[0] for r in rows]
    humidity_p = [r[2] for r in rows]
    months_p = [r[3] for r in rows]

    ax = axes[idx]
    for month in range(1, 13):
        mask = [m == month for m in months_p]
        temp_m = [t for t, m in zip(temp_max_p, mask) if m]
        humid_m = [h for h, m in zip(humidity_p, mask) if m]
        ax.scatter(temp_m, humid_m, alpha=0.4, s=15, color=month_colors[month])

    # Add trend line
    if temp_max_p and humidity_p:
        z = np.polyfit(temp_max_p, humidity_p, 1)
        p = np.poly1d(z)
        temp_range = np.linspace(min(temp_max_p), max(temp_max_p), 100)
        ax.plot(temp_range, p(temp_range), "k--", alpha=0.5, linewidth=1.5, label=f'Trend (slope={z[0]:.3f})')

    ax.set_xlabel('Temp Max (°C)', fontsize=9)
    ax.set_ylabel('Humidity (%)', fontsize=9)
    ax.set_title(f'Plant {plant_id}', fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.2)
    ax.legend(fontsize=7)

fig2.suptitle('Per-Plant: Temperature vs Humidity Correlation (20-Year Fleet Data)',
              fontsize=14, fontweight='bold', y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.99])
plt.savefig('analysis/humidity_vs_temperature_by_plant.png', dpi=150, bbox_inches='tight')
print("Saved: analysis/humidity_vs_temperature_by_plant.png")

# ============================================================================
# Compute correlations per plant
# ============================================================================
print("\nTemperature-Humidity Correlations by Plant:")
print("-" * 50)
for plant_id in plants:
    result = con.sql(f"""
    SELECT
      corr(Temperature_Max_C, Humidity_pct) as corr_max,
      corr(Temperature_Min_C, Humidity_pct) as corr_min
    FROM read_parquet('{fleet_parquet}')
    WHERE Plant_ID = '{plant_id}'
      AND Temperature_Max_C IS NOT NULL
      AND Temperature_Min_C IS NOT NULL
      AND Humidity_pct IS NOT NULL
    """)
    rows = result.fetchall()
    corr_max, corr_min = rows[0]
    print(f"{plant_id}: Temp_Max corr = {corr_max:+.4f}, Temp_Min corr = {corr_min:+.4f}")

# Fleet-wide correlation
result = con.sql(f"""
SELECT
  corr(Temperature_Max_C, Humidity_pct) as corr_max,
  corr(Temperature_Min_C, Humidity_pct) as corr_min
FROM read_parquet('{fleet_parquet}')
WHERE Temperature_Max_C IS NOT NULL
  AND Temperature_Min_C IS NOT NULL
  AND Humidity_pct IS NOT NULL
""")
rows = result.fetchall()
corr_max, corr_min = rows[0]
print("-" * 50)
print(f"FLEET: Temp_Max corr = {corr_max:+.4f}, Temp_Min corr = {corr_min:+.4f}")
