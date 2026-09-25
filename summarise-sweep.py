#!/usr/bin/env python3
"""Aggregate the per-sample scan_support JSONs from the corpus sweep.

  python3 summarise-sweep.py <dir-of-*.json>

Two losses are kept apart on purpose:

  outside  cells outside the target volume's array. Already published, as
           properties.volume_coverage[<vol>].overlap_ratio in the open-data
           catalogue. Not news.
  absent   cells inside the array but in a chunk the masked scan does not
           hold. This is the signal that is not published anywhere.

so the ranking below is by `inside support` = on data / (cells - outside),
which is the fraction that survives after discounting the known overhang.
"""
import glob
import json
import os
import sys

d = sys.argv[1] if len(sys.argv) > 1 else "."
rows, per_sample, partial = [], {}, set()
for f in sorted(glob.glob(os.path.join(d, "*.json"))):
    try:
        blob = json.load(open(f))
    except Exception as e:
        print("skip %s: %s" % (os.path.basename(f), e))
        continue
    sample = blob.get("scroll") or os.path.basename(f)[:-5]
    if blob.get("complete") is False:
        partial.add(sample)
    rs = []
    for r in blob.get("results", []):
        if "error" in r or r.get("support") is None:
            continue
        inside = r["cells_sampled"] - r["cells_outside_volume"]
        r["inside_support"] = (r["cells_on_data"] / inside) if (inside and r.get("cells_on_data") is not None) else None
        r["absent_frac"] = r["cells_in_absent_chunks"] / inside if inside else 0.0
        rs.append(r)
    if rs:
        per_sample[sample] = rs
        rows += [(sample, r) for r in rs]

if not rows:
    print("no results yet")
    sys.exit(0)


def pct(v):
    return "  n/a " if v is None else "%5.1f%%" % (100 * v)


scored = [(s, r) for s, r in rows if r["inside_support"] is not None]
vals = sorted(r["inside_support"] for _, r in scored)
print("%d surfaces over %d samples%s\n" % (
    len(rows), len(per_sample),
    "  (%d still running: %s)" % (len(partial), ", ".join(sorted(partial))) if partial else ""))
print("inside support (on data / cells inside the volume)")
print("  min %s  p05 %s  median %s  mean %s  max %s" % (
    pct(vals[0]), pct(vals[len(vals) // 20]), pct(vals[len(vals) // 2]),
    pct(sum(vals) / len(vals)), pct(vals[-1])))
for t in (0.25, 0.5, 0.75, 0.9):
    print("  below %s: %d of %d" % (pct(t), sum(1 for v in vals if v < t), len(vals)))

print("\n%-22s %5s %8s %8s %8s   %s" % ("sample", "n", "min", "median", "max", "worst-absent"))
for sample, rs in sorted(per_sample.items()):
    v = sorted(r["inside_support"] for r in rs if r["inside_support"] is not None)
    if not v:
        continue
    wa = max(r["absent_frac"] for r in rs)
    print("%-22s %5d %8s %8s %8s   %s%s" % (
        sample, len(v), pct(v[0]), pct(v[len(v) // 2]), pct(v[-1]), pct(wa),
        "  partial" if sample in partial else ""))

print("\nworst 20 by inside support:")
print("  %-12s %-46s %7s %8s %8s" % ("sample", "surface", "inside", "absent", "outside"))
for sample, r in sorted(scored, key=lambda x: x[1]["inside_support"])[:20]:
    print("  %-12s %-46s %7s %8s %8s" % (
        sample, r["surface"][:46], pct(r["inside_support"]),
        pct(r["absent_frac"]), pct(r["cells_outside_volume"] / r["cells_sampled"])))
