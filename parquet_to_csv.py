import sys

import pandas as pd

SRC = "Example_P02CV27_1Year.parquet"
DST = "Example_P02CV27_preview.csv"

# Number of rows to convert; pass "all" as the first argument for the full file.
arg = sys.argv[1] if len(sys.argv) > 1 else "10"

df = pd.read_parquet(SRC)
print(f"Full file: {len(df)} rows, {len(df.columns)} columns")
print(df.dtypes)

if arg != "all":
    df = df.head(int(arg))
    DST = "Example_P02CV27_preview.csv"
else:
    DST = "Example_P02CV27_1Year.csv"

df.to_csv(DST, index=False)
print(f"Wrote {len(df)} rows to {DST}")
