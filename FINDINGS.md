# Ten of the fifteen published PHerc1447 surfaces do not stand on the scan

Measured 2026-09-24 with `scan_support.py` against the Vesuvius Challenge open-data bucket.
Everything below is anonymous HTTP against published data; every command is reproducible.

## What was measured

Every published tifxyz surface of PHerc. 1447, against the raw masked scan each one names:

```
scan_support.py --scroll PHerc1447 --sample 3000 --seed 1 --workers 24
```

The bucket names the volume on both sides — a surface lives at
`segments/<seg>/mesh/<segid>-on-20250521151220-8.64um.tifxyz/`, and the only volume published
for this sample is `volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr` — and the
catalogue names it a third time, as `creation.derived_from = {type: volume, id: 20250521151220}`
with `original_volume_downscale: 1`. So the pairing is read off the data three ways, not assumed.

For each surface, 3000 valid cells were drawn at random (seed 1), rounded to a level-0 voxel,
and read with a single-byte `Range` request each.

## Result

```
surface                                      cells support     on data  zero vox    absent   outside
20250502180708-on-2...1220-8.64um.tifxyz      3000    7.5%         224       292      2331       153
20250502180748-on-2...1220-8.64um.tifxyz      3000   40.4%        1213       116      1520       151
20250502182142-on-2...1220-8.64um.tifxyz      3000   56.7%        1702       196      1102         0
20250502182456-on-2...1220-8.64um.tifxyz      3000   40.2%        1207       170      1300       323
20250502183138-on-2...1220-8.64um.tifxyz      3000   46.1%        1382       109      1509         0
20250502183421-on-2...1220-8.64um.tifxyz      3000   38.2%        1145        90      1710        55
20250502184201-on-2...1220-8.64um.tifxyz      3000   37.1%        1114       215      1112       559
20250502184658-on-2...1220-8.64um.tifxyz      3000   41.4%        1241       193      1108       458
20250502184845-on-2...1220-8.64um.tifxyz      3000   54.0%        1621       173       793       413
20250502185519-on-2...1220-8.64um.tifxyz      3000   43.1%        1293       280      1206       221
20250502205333-on-2...1220-8.64um.tifxyz      3000  100.0%        3000         0         0         0
20250702235910-on-2...1220-8.64um.tifxyz      3000  100.0%        3000         0         0         0
20250703025628-on-2...1220-8.64um.tifxyz      3000  100.0%        3000         0         0         0
20250703034159-on-2...1220-8.64um.tifxyz      3000  100.0%        3000         0         0         0
20251105093211-on-2...1220-8.64um.tifxyz      3000   98.2%        2947        17        36         0

15 surfaces audited, 0 skipped
support: min 7.5%  median 46.1%  max 100.0%
```

The distribution is not a gradient. It is two populations:

* **five surfaces at 98.2%–100.0%.** Four of them are 3000 of 3000 cells on data, with not one
  cell on a zero voxel, not one in an absent chunk and not one outside the array.
* **ten surfaces at 7.5%–56.7%**, every one of them from the batch timestamped 2 May 2025.
  Between 793 and 2331 of their 3000 sampled cells fall in chunks the masked scan does not hold
  at all.

## The controls

A measurement like this is worth nothing without knowing what the instrument reads on a known
good and a known bad surface.

| | on data | zero voxel | absent chunk | support |
|---|---|---|---|---|
| a seed placed in a phantom 255-block of the m7 prediction | 60 | 155 | 1901 | **2.8%** |
| a seed placed on real material, same tool, same settings | 2090 | 26 | 0 | **98.8%** |

Both are `vc_grow_seg_from_seed` runs of 24 generations over 2116 cells, both reporting
0.6087 cm², from the reproduction in [villa#1877](https://github.com/ScrollPrize/villa/pull/1877).
These counts are reproduced here to the cell through a completely different implementation —
the C++ guard reads the seed voxel through `IChunkedArray`, this reads bytes over HTTP.

## Three explanations ruled out

**It is not a truncated volume.** Probing a 5×5 lattice of chunk positions every 1024 voxels
through the whole z extent, the masked scan is densely stored from top to bottom, including the
band where the low-scoring surfaces live (chunk plane 160, z 20480–20607: 25 of 25 stored;
plane 176, z 22528–22655: 25 of 25).

**It is not a coordinate offset.** Five published surfaces on the same volume, read with the
same convention, score 100.0% at zero offset; so does a patch we grew ourselves. Shifting the
worst surface's z by −1024 … +1024 produces a monotonic gradient with no peak anywhere — the
signature of moving into denser material, not of finding a registration.

**It is not the empty-cell marker.** A cell counts as empty only when x, y and z are all
exactly −1; cells are not dropped for a single negative component, which matters because
published surfaces carry legitimate coordinates far below zero.

## What differs between the two populations

The catalogue records where each segment was copied from. The ten low-scoring surfaces carry

```
"source_path": "s3://philodemos/sean/scrolls/PHerc1447.volpkg/renders/auto_grown_..."
```

and the high-scoring ones carry

```
"source_path": "s3://vesuvius-challenge/PHerc1447/segments/raw/..."
```

That is an observation about provenance, not a diagnosis, and it is as far as the data will
take me. What is measured is only this: ten surfaces published under `PHerc1447/segments/`
have between 43% and 92% of their sampled cells standing where the raw masked scan holds no
data, and nothing in the published metadata says so. `properties.volume_coverage` is `null`
for all fifteen.

## Against the rest of the published corpus

A single scroll's table does not say whether 46% is bad. So the tool was run the same way over
every published surface of every sample in the bucket — `--sample 1000 --seed 1`, the whole
catalogue, one sample at a time. That sweep is still running; **two samples are complete and
they already settle the question.**

The measure here is *inside support* — cells on data over cells **inside** the volume — which
discounts the bbox overhang that the catalogue already publishes as `overlap_ratio`, so what is
left is only the unpublished signal: cells inside the array, in chunks the scan does not hold.

```
sample                     n      min   median      max   worst-absent
PHerc0009B                36    77.6%    92.9%    99.9%    11.0%
PHerc1447                 15     8.2%    50.6%   100.0%    79.0%
```

Ranked over all 51 surfaces, the ten worst are **exactly** PHerc1447's ten, and then there is a
gap:

```
  PHerc1447   20250502180708-on-20250521151220-8.64um    8.2% inside   79.0% absent
  PHerc1447   20250502183421-on-20250521151220-8.64um   38.1%          60.1%
  PHerc1447   20250502180748-on-20250521151220-8.64um   41.9%          54.7%
  PHerc1447   20250502184201-on-20250521151220-8.64um   41.9%          49.2%
  PHerc1447   20250502185519-on-20250521151220-8.64um   44.7%          42.9%
  PHerc1447   20250502182456-on-20250521151220-8.64um   45.9%          46.8%
  PHerc1447   20250502184658-on-20250521151220-8.64um   47.9%          44.9%
  PHerc1447   20250502183138-on-20250521151220-8.64um   50.6%          46.6%
  PHerc1447   20250502182142-on-20250521151220-8.64um   58.5%          35.2%
  PHerc1447   20250502184845-on-20250521151220-8.64um   60.6%          32.7%
  ---------------------------------------------------------------- gap
  PHerc0009B  20250919135433-on-20250820154339-2.401um  77.6%          11.0%
  PHerc0009B  20250919125754-on-20250521125136-8.64um   86.3%          10.1%
```

The tenth-worst surface sits at 60.6% inside support and 32.7% absent; the eleventh at 77.6%
and 11.0%. On the axis that matters — cells in chunks the scan does not hold — the worst
surface outside PHerc1447 is **three times better** than the best of PHerc1447's ten.

PHerc. 1447 is not a scroll where this is normal. A whole healthy sample sits between 77.6% and
99.9%, loses at most a ninth of its cells to absent chunks, and never approaches the low group.

*Caveat, stated plainly:* two of the bucket's 45 samples are complete at the time of writing.
PHerc0139 (189 surfaces over 7 scans) and the rest are still running, and a later sample could
turn up a second low population. That would not change what is measured about PHerc1447; it
would change how unusual it is. Anyone can refresh the whole picture with
`summarise-sweep.py` over the sweep directory.

*Sampling check:* the PHerc1447 table above was measured at 3000 cells per surface; the corpus
sweep uses 1000. Rerunning PHerc1447 at 1000 gives min 7.8% / median 50.6% / max 100.0% against
7.5% / 46.1% / 100.0% at 3000 — the same picture, surface by surface, so the ranking is not a
sampling artefact.

## Why it matters

These are exactly the surfaces a newcomer reaches for. They are the published segments of a
published scroll, they open in VC3D, they render, they carry sensible areas, and half of one
of them is air. A tracer extended from one, a model fine-tuned on one, or a flattening
evaluated against one inherits that silently.

## Reproducing it

```
pip install numpy tifffile imagecodecs
python scan_support.py --scroll PHerc1447 --sample 3000 --seed 1 --workers 24
```

Fifteen surfaces, 15m29s, 45,000 single-byte range requests, no chunk downloaded. Drop
`--sample` for every cell, or add `--mode presence` for a HEAD-only triage pass that takes
four minutes and no body bytes at all.

---

*AI-assisted, human-directed. Every number above was produced by running the tool against the
published data on the stated date.*
