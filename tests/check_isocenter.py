"""
Check that the Topas isocenter scorer produced non-zero dose.
Run from the directory containing 'isocenter_scorer.csv' after a Topas simulation.
Exit 0 on success, 1 on failure.
"""
import sys
import pathlib

csv_path = pathlib.Path("isocenter_scorer.csv")

if not csv_path.exists():
    print(f"ERROR: scorer output not found: {csv_path.resolve()}", file=sys.stderr)
    sys.exit(1)

values = []
for line in csv_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    try:
        values.append(float(line.split(",")[0]))
    except ValueError:
        continue

if not values:
    print("ERROR: no numeric values found in isocenter_scorer.csv", file=sys.stderr)
    sys.exit(1)

if not any(v > 0 for v in values):
    print(
        "FAIL: all dose values at isocenter are zero — beam likely going in wrong direction.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"OK: non-zero dose at isocenter ({max(values):.4e} Gy·proton⁻¹)")
sys.exit(0)
