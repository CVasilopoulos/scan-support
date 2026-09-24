# scan_support

**Does this traced surface stand on scan data?**

A tifxyz surface records where a sheet of papyrus is. Nothing in it records whether the
volume it was traced from had any data there. `vc_grow_seg_from_seed` will happily trace
through a region of a *surface prediction* that is solid 255 but sits outside the scanned
material entirely, and the patch it writes looks exactly like a good one — same area, same
cell count, same log.

This is the measurement that separates them. For each surface, `scan_support` maps every
valid cell to a voxel of the **raw masked scan** and reports how many of them land on a
voxel that exists and is above zero.

```
$ scan_support.py --scan https://.../PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr \
      runs/phantom runs/real

scan  https://.../PHerc1447/volumes/20250521151220-8.640um-1.2m-116keV-masked.zarr
      level 0  shape (24297, 8343, 8343) (z,y,x)  chunks (128, 128, 128)  dtype uint8  compressor raw

phantom          2116 cells    2.8%  on data     74/87   chunks absent     1901 cells in absent chunks
real             2116 cells   98.8%  on data      0/79   chunks absent        0 cells in absent chunks

2 surfaces, 259 requests (166 HEAD, 93 GET, 192.9 MB)
```

Both patches report 0.6087 cm². Both were grown by `vc_grow_seg_from_seed` from the same
published PHerc1447 m7 prediction, 24 generations, over 2116 cells. One of them is air.

The same run in `--mode presence` costs 166 `HEAD` requests, no downloads and 11 seconds, and
separates them just as well.

---

## Install

One file, no packaging. It needs `numpy` and `tifffile`, and `numcodecs` only if the scan
you point it at uses a compressed codec.

```bash
pip install numpy tifffile imagecodecs
python scan_support.py --help
```

or with `uv`, without installing anything:

```bash
uv run --no-project --with numpy --with tifffile --with imagecodecs \
    python scan_support.py --scroll PHerc1447 --list
```

`numpy` and `tifffile` are required. `imagecodecs` is needed for the published segments,
whose tifs are LZW-compressed; `numcodecs` only if you point `--scan` at a compressed store
(the published masked scans are uncompressed, so usually you need neither).

## Usage

```
scan_support.py --scan ZARR SURFACE [SURFACE ...]
scan_support.py --scroll NAME
```

`SURFACE` is a tifxyz directory — a local path, or an `https://` prefix, in which case
`x.tif`, `y.tif`, `z.tif` and `meta.json` are fetched from it. `--scan` is the raw masked
OME-Zarr the surfaces were traced from, again local or remote.

`--scroll NAME` does the pairing for you. The open-data bucket publishes every segment
re-expressed into each volume it is registered against, in a directory named
`<segid>-on-<volumeid>-<voxelsize>.tifxyz`, and the volume itself as
`volumes/<volumeid>-<voxelsize>-...-masked.zarr`. Both sides name the volume, so the
pairing is read, never guessed, and surfaces whose scan this bucket does not publish are
listed and skipped rather than silently matched to something else:

```
$ scan_support.py --scroll PHerc1447 --list
PHerc1447: 15 published tifxyz surfaces over 1 scan(s)
  20250521151220-8.640um-1.2m-116keV-masked.zarr                   15 surfaces
```

`--from-file FILE` reads surfaces one per line, which is easier than a shell loop when you
have a few hundred.

| flag | what it does |
|---|---|
| `--mode voxel` | default. Reads the scan voxel under every cell — exactly, not by chunk. |
| `--mode presence` | **No downloads.** One `HEAD` per distinct chunk; a cell in a chunk the store does not hold cannot be on data. The reported figure is an *upper bound* and is marked `?`. |
| `--sample N` | audit a random sample of N cells per surface (`--seed` to pin it) |
| `--max-chunk-gets N` | refuse a surface that would need more than N chunk downloads (default 400) |
| `--fail-under F` | exit 1 if any surface scores below F — for a batch script or CI |
| `--json FILE` | write the whole table, including the request counts |
| `--level N` | read a coarser pyramid level of the scan |

### Reading a voxel costs one byte

The published masked scans are uncompressed `uint8` with `128^3` C-order chunks, so a voxel is
one byte at a computable offset. `--mode voxel` asks for exactly that byte with a
`Range: bytes=N-N` request. A `206` carries the voxel; a `404` means the chunk is not in the
store. One request answers both questions, and no chunk is ever downloaded:

```
before (whole chunks)   2 surfaces, 259 requests (166 HEAD, 93 GET, 192.9 MB)   2m46s
after  (byte ranges)    2 surfaces, 2498 requests (166 HEAD, 2332 GET, 0.0 MB)  1m28s
```

Identical numbers, 193 MB less traffic. If the store is compressed or not single-byte, the
tool falls back to fetching whole chunks and says so in the JSON (`"reads": "chunk"`).

`--mode presence` is cheaper still — nothing but HTTP `HEAD`, one per distinct chunk — and on a
sparse masked scan it already separates a phantom surface from a real one, because the air
outside the scroll is not stored at all. But it is a chunk-resolution signal: in a region
where every chunk is stored it saturates at 100% and tells you nothing. Use it to triage,
`--mode voxel` to measure.

## What the numbers mean

Every cell falls into exactly one of four buckets, and all four are printed. Collapsing
them is how you get a number that means nothing:

```
surface                                      cells support     on data  zero vox    absent   outside
```

* **cells** — grid positions that are not the empty marker. A tifxyz marks an empty cell
  with the *triple* `(-1, -1, -1)`; testing one component alone is wrong corpus-wide,
  because published surfaces carry legitimate coordinates far below zero (one PHerc0139
  variant reaches z = −16444).
* **on data** — the scan voxel under the cell exists and is above zero.
* **zero vox** — the chunk is stored, and the voxel there is zero.
* **absent** — the chunk is not in the store at all. On a sparse masked scan this is the
  strongest single signal: a chunk that was never written is material that was never
  scanned.
* **outside** — the cell is outside the scan array entirely. This is its own bucket on
  purpose. Roughly a third of published variants have bounding boxes that stick out of
  their target volume, and a negative coordinate would otherwise become a plausible-looking
  chunk index — `-16444 // 128 == -129` builds a URL that 404s *for the wrong reason* and
  would be scored as "the scan has no data here".
* **support** — `on data / cells`. In `presence` mode it is `(cells − outside − absent) /
  cells`, an upper bound, flagged `?`.

A healthy traced patch scores in the high nineties. A patch grown through a prediction
artefact scores near zero and has almost all of its chunks absent. A patch straddling the
edge of the scanned cylinder scores in between, which is correct and is the reason this is
reported as a fraction and not a verdict.

## What it will not do

The tool refuses to guess, because guessing is the bug it was written to find.

**It will not report a number for a surface and a scan that are not in the same voxel
space.** A tifxyz records no volume identity and no volume shape, so the only honest check
available is whether the cells land inside the scan's array. If they do not, you get an
error naming both extents and exit code 2 — not a support figure computed against the wrong
grid:

```
error: surface and scan are not in the same voxel space:
  20231007101619: cells span z 2499-6045 y 2692-4751 x 3016-6964, outside the scan's (5048, 2000, 2000)
       Pass the scan these surfaces were traced from, or --assume-same-grid
       if you know the grids match and the surface simply runs past the edge.
```

`--assume-same-grid` exists for the case where you know the grids match and a surface
simply runs off the edge, and it is deliberately awkward to reach for.

**It will not silently skip data it cannot read.** If the scan's chunks use a codec it
cannot decode it says so and exits 2, rather than counting undecodable chunks as empty.

**It is one voxel per cell at level 0.** It is a support measure, not a segmentation
metric: a surface one voxel off the true sheet still scores 100%.

## Self-test

```bash
uv run --no-project --with numpy --with tifffile python test_scan_support.py
```

Builds a scan on disk with exactly one chunk written and half its voxels zero, then six
surfaces — all cells on material, all in the missing chunk, all on written-but-zero voxels,
one full of `-1` holes, one with a legitimate `-1` in a single axis, and one straddling the
array edge with negative coordinates — and checks all 35 reported numbers and every CLI exit
code. It needs no network and takes under a second.

## What it found

Run over every published surface of PHerc. 1447, it splits them into two populations: five
score 98.2%–100.0%, four of those with 3000 of 3000 sampled cells on data; ten score 7.5%–56.7%,
with between 793 and 2331 of their 3000 cells in chunks the raw masked scan does not hold at
all. The full table, the controls, and the three explanations ruled out are in
[FINDINGS.md](FINDINGS.md); the raw logs are in [examples/](examples/).

## The write-up it came from

[REPORT.md](REPORT.md) is the September 2026 write-up this tool was built alongside: fourteen
silent-failure defects in the villa toolchain, with before/after numbers on published scroll
data, and the argument for why measuring an existing surface is the other half of fixing the
tool that made it.

## Why this exists

Reported by @evilaliv3 in [ScrollPrize/villa#1875](https://github.com/ScrollPrize/villa/issues/1875),
by @spencerdavis-tx in [#1114](https://github.com/ScrollPrize/villa/issues/1114), and measured
across 23 First Letters volumes by @Bullo27: published surface predictions hold solid blocks of
255 in the air outside the scroll. [villa#1877](https://github.com/ScrollPrize/villa/pull/1877)
adds a guard at the seed, before a trace starts. This tool is the other half — it scores
surfaces that already exist, including ones that were traced before anybody knew to check.

It is complementary to `vesuvius.surface_preflight`, which gates on
`sampled_volume_signal_support` within the volume being traced. `scan_support` compares against
a *different* volume: the raw masked scan the prediction was derived from, which is where the
absence is recorded.

---

*AI-assisted, human-directed.*
