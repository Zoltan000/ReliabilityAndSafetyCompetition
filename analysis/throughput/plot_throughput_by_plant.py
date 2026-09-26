#!/usr/bin/env python3
"""
Analyze and visualize Total_kg_Day by Conveyor_ID and Plant.

Queries the fleet parquet file to compute mean, stddev, min, max of
Total_kg_Day per plant and per conveyor, and produces a two-panel plot:
- Left: bar chart with error bars (±1 std) by plant
- Right: per-conveyor scatter, colored by plant
"""

import duckdb
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

conn = duckdb.connect(':memory:')

# Per-plant aggregates
query_plant = """
SELECT
  SUBSTRING(Conveyor_ID, 1, 3) as Plant,
  COUNT(DISTINCT Conveyor_ID) as num_conveyors,
  AVG(Total_kg_Day) as mean_kg_day,
  STDDEV(Total_kg_Day) as stddev_kg_day,
  MIN(Total_kg_Day) as min_kg_day,
  MAX(Total_kg_Day) as max_kg_day
FROM read_parquet('2026-09_compet_Student_Historical_Data_V03.parquet')
WHERE Total_kg_Day IS NOT NULL
GROUP BY Plant
ORDER BY mean_kg_day DESC
"""

result_plant = conn.execute(query_plant).fetchall()
columns_plant = [desc[0] for desc in conn.description]
df_plant = pd.DataFrame(result_plant, columns=columns_plant)

# Per-conveyor aggregates
query_conveyor = """
SELECT
  Conveyor_ID,
  SUBSTRING(Conveyor_ID, 1, 3) as Plant,
  AVG(Total_kg_Day) as mean_kg_day
FROM read_parquet('2026-09_compet_Student_Historical_Data_V03.parquet')
WHERE Total_kg_Day IS NOT NULL
GROUP BY Conveyor_ID
ORDER BY Plant, mean_kg_day DESC
"""

result_conveyor = conn.execute(query_conveyor).fetchall()
columns_conveyor = [desc[0] for desc in conn.description]
df_conveyor = pd.DataFrame(result_conveyor, columns=columns_conveyor)

# Create visualization
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

# Plot 1: Average throughput by plant with error bars
plants = df_plant['Plant'].values
means = df_plant['mean_kg_day'].values
stds = df_plant['stddev_kg_day'].values

colors = plt.cm.tab20(np.linspace(0, 1, len(plants)))
axes[0].bar(plants, means, yerr=stds, capsize=5, color=colors, alpha=0.7, edgecolor='black')
axes[0].set_xlabel('Plant ID', fontsize=12, fontweight='bold')
axes[0].set_ylabel('Average Total_kg_Day', fontsize=12, fontweight='bold')
axes[0].set_title('Average Daily Throughput by Plant\n(with ±1 std deviation)', fontsize=13, fontweight='bold')
axes[0].grid(axis='y', alpha=0.3, linestyle='--')
axes[0].tick_params(axis='x', rotation=45)

# Plot 2: All conveyors by plant (sorted within each plant)
plant_colors = dict(zip(df_plant['Plant'].values, colors))
conveyor_colors = [plant_colors[plant] for plant in df_conveyor['Plant'].values]

axes[1].scatter(range(len(df_conveyor)), df_conveyor['mean_kg_day'].values,
                c=conveyor_colors, s=100, alpha=0.6, edgecolors='black', linewidth=0.5)
axes[1].set_xlabel('Conveyor Index (sorted by plant)', fontsize=12, fontweight='bold')
axes[1].set_ylabel('Average Total_kg_Day', fontsize=12, fontweight='bold')
axes[1].set_title('Individual Conveyor Throughput\n(284 conveyors, sorted by plant)', fontsize=13, fontweight='bold')
axes[1].grid(axis='y', alpha=0.3, linestyle='--')

# Add legend with plant colors
from matplotlib.patches import Patch
legend_elements = [Patch(facecolor=plant_colors[plant], edgecolor='black', label=plant)
                   for plant in sorted(plant_colors.keys())]
axes[1].legend(handles=legend_elements, loc='upper right', ncol=2, fontsize=9)

plt.tight_layout()
plt.savefig('throughput_by_plant.png', dpi=300, bbox_inches='tight')
print("✓ Plot saved to throughput_by_plant.png")
