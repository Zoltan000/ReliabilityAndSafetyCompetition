"""Run a DuckDB SQL script and print every SELECT result.

Usage (repo root): uv run --no-project --with duckdb python analysis/run_sql.py analysis/fleet_kpis.sql
"""
import sys

import duckdb

con = duckdb.connect()
for stmt in open(sys.argv[1]).read().split(";"):
    body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
    if not body:
        continue
    rel = con.sql(body)
    if rel is not None:
        rel.show(max_rows=60, max_width=250)
