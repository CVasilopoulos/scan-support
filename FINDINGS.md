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
**every published tifxyz surface in the bucket** — all 45 samples, `--sample 1000 --seed 1`.
Eleven samples have published surfaces and a published masked scan to check them against: **808
(segment, volume) pairs over 307 distinct segments.** 755 of those pairs were read cell by cell;
the other 53 are on PHerc0172's blosc-compressed scan, where the tool falls back to
chunk-presence and reports an upper bound rather than pretending to a number it cannot get.

The measure is *inside support* — cells on data over cells **inside** the volume — which
discounts the bbox overhang the catalogue already publishes as `overlap_ratio`, leaving only the
unpublished signal: cells inside the array, in chunks the scan does not hold.

### A correction to what I wrote at five samples

With five samples in, the ten lowest-scoring surfaces in the whole set were PHerc1447's ten, and
I wrote that no other sample behaved like it. **The full corpus refutes that.** PHerc1667 has a
worse group, and PHerc0814 holds the single worst surface measured. The caveat I attached was the
right one and it fired. What survives is the measurement of PHerc1447; what does not is the claim
that it was unique.

### The distribution

```
scored cell by cell: 755 pairs
  median 98.9%   mean 93.6%
  below 90%: 138  (18.3%)
  below 75%:  50  ( 6.6%)
  below 50%:  22  ( 2.9%)
  below 25%:   7  ( 0.9%)
```

The published corpus is overwhelmingly sound. The interesting part is the tail, and the tail is
not spread evenly — **all 22 pairs below 50% come from four samples**:

```
below 50%   PHerc1667 11 · PHerc1447 7 · PHerc0814 3 · PHercParis4 1
below 75%   PHerc1667 20 · PHercParis4 15 · PHerc1447 10 · PHerc0814 5
```

### The measure reproduces across volumes

232 of the 307 segments are published re-expressed into more than one volume, which gives a free
control: the same surface, independently resampled onto a differently-scaled grid, should score
the same. It does. **The median spread between a segment's best and worst volume is 2.5
percentage points**, and the 90th percentile is 13.5. A grid or pairing error would not survive
that.

### Two different faults, which the cross-volume view separates

**A surface that is off the material scores low on every volume it appears in.** Six PHerc1667
segments do exactly this:

```
  20260205070000   2.399um = 19%   1.129um = 12%
  20260203210000   2.399um = 25%   1.129um = 16%
  20260130150000   2.399um = 31%   1.129um = 17%
  20260128140000   2.399um = 36%   1.129um = 30%
  20260123230000   2.399um = 45%   1.129um = 37%
  20260119120000   2.399um = 53%   1.129um = 45%
```

as does PHercParis4's `20260623171929` (48% and 61%). PHerc1447's ten belong here too, though
only one volume is published for that sample so the cross-check is not available.

**One bad pairing looks completely different.** Three PHerc0814 segments score *perfectly* on two
volumes and badly on a third:

```
  20260226123353   20250804134230 = 100%   20260309142202 = 100%   20260521123630 =  0%
  20250925204843   20250804134230 = 100%   20260309142202 = 100%   20260521123630 = 48%
  20250926165636   20250804134230 = 100%   20260309142202 = 100%   20260521123630 = 49%
```

These are not wandering surfaces. Whatever is wrong is on the `20260521123630` side — that
volume's mask, or those three re-expressions into it. `20260226123353-on-20260521123630-1.129um`
is the single worst surface in the corpus: **0.0% of its in-volume cells on data, 100% of them in
chunks the scan does not hold**, with a further 67.1% of its cells outside the array entirely —
while the same segment sits at 100% on two other volumes.

That distinction is the thing a bbox overlap figure cannot give you, and it is the reason the
four buckets are kept apart.

*Sampling check:* PHerc1447 was also measured at 3000 cells per surface, against the sweep's
1000: min 7.8% / median 50.6% / max 100.0% versus 7.5% / 46.1% / 100.0%, surface by surface. The
ranking is not a sampling artefact.

## Why it matters

These are exactly the surfaces a newcomer reaches for. They are the published segments of
published scrolls, they open in VC3D, they render, they carry sensible areas, and half of one of
them is air. A tracer extended from one, a model fine-tuned on one, or a flattening evaluated
against one inherits that silently, and nothing in the published metadata warns them.

97% of the corpus is fine, which is the point: the 22 pairs that are not are invisible precisely
because everything around them is sound. They are also few enough to be looked at by hand, and
the list is above.

## Reproducing it

```
pip install numpy tifffile imagecodecs        # numcodecs too, for PHerc0172's blosc scan
python scan_support.py --scroll PHerc1447 --sample 1000 --seed 1 --workers 24
```

One scroll: fifteen surfaces, a few minutes, single-byte range requests, no chunk downloaded.
`--mode presence` is a HEAD-only triage pass that costs no body bytes at all but saturates at
100% wherever every chunk is stored, so it triages and does not measure.

The whole corpus is the same command over each sample in the bucket. It took about twelve hours
on a home connection, and `summarise-sweep.py` aggregates the per-sample JSON:

```
for s in $(list the bucket's top-level prefixes); do
    python scan_support.py --scroll "$s" --sample 1000 --seed 1 --workers 24 --json out/$s.json
done
python3 summarise-sweep.py out/
```

`--json` is written after every surface and replaced atomically, so a run that is interrupted
keeps everything it has already measured. That is not a detail: the first pass of this sweep put
a one-hour cap on each sample, six samples hit it, and because the file was only written at the
end, all six lost every row they had measured. Fixing that was the one bug this exercise found in
the tool itself, and it is the same bug the report in front of this one is about.

---

*AI-assisted, human-directed. Every number above was produced by running the tool against the
published data on the stated date.*
