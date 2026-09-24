# The tools said yes and did nothing

### Fourteen silent-failure defects in the Vesuvius Challenge toolchain, across thirteen pull requests, found and fixed on published scroll data — September 2026

Christos Vasilopoulos · [ScrollPrize/villa](https://github.com/ScrollPrize/villa) · Discord `chrisvas_12645`

---

## The pattern

Every defect below has the same shape. A tool is given an instruction — a flag, a config key, a
scroll id, a seed — and it **accepts the instruction, reports success, and produces output that
looks right**. Nothing is thrown. Nothing is logged. The run finishes. The number at the end is
plausible.

That shape matters more than any one of these bugs, because it is the failure mode that survives
review. A crash gets reported the same day. A tool that silently ignores `--resume-generations`
and rewrites the same 196 points into a fresh directory gets reported two months later by
somebody writing documentation, and only because they happened to count the points.

| | The instruction | What the tool did instead | Measured |
|---|---|---|---|
| **#1877** | grow a segment from this seed | grew 0.61 cm2 of surface standing on **no scan data at all** | 1901 of 2116 cells in raw chunks the scan does not hold |
| **#1781** | convert this segment mesh, then flatten it | wrote the reciprocal scale; flattening collapsed the segment | 3,485,607 points -> **159** |
| **#1799** | train these auxiliary heads | built the heads, never made the targets | `Avg Loss = 0.0000`, every epoch, no warning |
| **#1876** | repair the winding graph minimally | dropped 99% of the measured equations from the model | **638 of 645** equations discarded |
| **#1869** | resume this trace for 8 more generations | re-wrote the same points to a new directory | 196 points -> 196 (should be **900**) |
| **#1864** | audit these winding annotations | reported contradictions created by its own bookkeeping | 3 false cycles -> **1** real one |
| **#1868** | open scroll 3 / scroll 4 | raised, for the two calls the docs use as examples | **5 of 10** documented calls failed |
| **#1808** | stream this region for inference | re-downloaded every chunk once per overlapping patch | 1000 GETs -> **250** (796 MB -> 199 MB) |
| **#1798** [merged] | use normal-grid level 2 | used level 0 and printed "Loaded normal grid level 0" | silent -> one warning naming the level |
| **#1804** | open this published 88 keV volume | refused to open at all, because `.zattrs` over-declares | exit 1 -> renders, 5 skipped levels named |
| **#1863** | render remotely from this URL | required an unused local path; documented a cache it never wrote | 2 broken invocations -> 3 working ones |
| **#1801** | keep the patch I just grew | kept it on disk, dropped it from the UI after restart | 81 catalog segments, **0** grown patches listed |
| **#1882** | show this scroll's scans and viewers | implied 40 scan configurations where 6 exist; hid a whole scan | 1 of 5 WEBKNOSSOS datasets reachable |
| **#1320** | convert with default arguments | built a 2x2 grid, rasterized 0 points, **exited 0** | exit 0 -> exit 1, nothing written |

Thirteen pull requests; #1798 is merged, the rest are open. A fourteenth, `#1883`, went up on
the last day of this writing — the published PHerc. Paris 4 spiral dataset is rejected by the
repo's own validation for three inputs it demonstrably has, and `fit_spiral.py --check` now
reports what a fit needs, what the dataset has, and what belongs in `spiral-scroll.json`. Its
evidence is in the pull request; it is not counted in the table above.

**Not one of these is my own bug report.** Every entry above started as an issue somebody else
filed after hitting it and being unable to explain the result — @Aleredfer, @Bullo27,
@flummoxjr, @nerln, @sgsllc-jr, @rodriguescarson, @aistae, @sergeievland, @evilaliv3,
@giorgioangel. The work here is the same three steps each time: reproduce it on published data,
find why the instruction never arrived, and make the tool either obey it or say that it cannot.

---

## Why this class is expensive for the project

The stated bottleneck in [2026 Open Problems](https://scrollprize.org/2026_open_problems) is that
the pipeline works, but not without a person checking its output at almost every stage, and it
keeps failing in the same handful of spots.

A silent failure is precisely the thing that person cannot check. When
`vc_grow_seg_from_seed` grows a 0.608680 cm2 patch from a seed in the air, and a genuine seed a
few thousand voxels away grows 0.608721 cm2, **there is nothing in either run's output that
separates them** — not the area, not the cell count, not the log. The reviewer's eye is the only
gate, and the reviewer is looking at a number that is correct.

That is the argument for the tool in the second half of this report.

---

## The fixes

Every "before" below is upstream `main` at the stated commit, and every "after" is this branch on
the same base, run against the same published data with the same flags. Full evidence, command
lines and logs are linked from each pull request.

### Surfaces and segments

**[#1877](https://github.com/ScrollPrize/villa/pull/1877) — a seed in the air grows a plausible surface**
*Issue [#1875](https://github.com/ScrollPrize/villa/issues/1875) (@evilaliv3), prior reports [#1114](https://github.com/ScrollPrize/villa/issues/1114) (@spencerdavis-tx) and @Bullo27's 23-volume census.*

The published PHerc1447 m7 surface prediction holds solid blocks of 255 in the air outside the
scroll. I re-listed its level 0 — the same 74,683 chunks the report counts — and sampled 200 of
them: 9 chunks are above 0.9 of 255 and hold 16.7% of the sample's lit voxels, and **all 72 raw
masked chunks covering those 9 blocks answer HTTP 404** while a control chunk inside the scroll
answers 200. A seed in the densest block grows 0.608680 cm2 over 2116 cells with no remark;
1901 of those cells fall in raw chunks that do not exist and **60 touch a scan voxel above zero**.
A real seed grows 0.608721 cm2 with 2090 of 2116 cells on data. The two outputs are
indistinguishable.

The fix is the guard the issue asks for: `--scan-volume <path|url>` reads the seed voxel in the
raw masked scan once and warns; `--require-scan-data` exits 1 before the tracer starts, in 25 s.
Without the flag nothing is opened and the log is identical to main's, line for line.

**[#1781](https://github.com/ScrollPrize/villa/pull/1781) — the conversion that collapses the segment**
*Issues [#1319](https://github.com/ScrollPrize/villa/issues/1319) and [#1320](https://github.com/ScrollPrize/villa/issues/1320). Carries work from three earlier closed attempts, with co-authorship.*

`vc_obj2tifxyz` wrote `scale` as the UV step — the reciprocal of the format's convention. Every
consumer (`vc_flatten`, `vesuvius.tifxyz`, `Tifxyz.full_resolution_shape`) sizes its output as
extent x scale, so flattening the converted published Scroll 1 segment `20231007101619`
produced a 9 x 18 grid holding **159 of about 3.5 million points**. With default arguments the
tool built a 2 x 2 grid, rasterized nothing, printed "Successfully converted to tifxyz format"
and exited 0.

After: `scale` is measured on the grid actually written — 0.0601765, 0.124434 against an
independently measured sample spacing of 16.61 x 8.03 voxels — and `vc_flatten` produces a
961 x 4113 grid with **3,485,607 valid points**. An empty or 2 x 2 grid now exits 1 and writes
nothing. Nine end-to-end subcases, six of which fail against the pre-fix binary.

**[#1801](https://github.com/ScrollPrize/villa/pull/1801) — the patch that disappears when you restart**
*Issue [#1466](https://github.com/ScrollPrize/villa/issues/1466) (@Bullo27), reopened on 2026-09-23 after the reporter confirmed this reproduction.*

Growing a patch from a seed on an Open Data sample saves it and selects it. After a restart the
catalog open lands on whichever volume has the most catalog segments, and the selection moves
with it, so `segments.list` shows **81 catalog segments and no grown patch** — while the patch is
still on disk and still in the project file. Selecting the grow volume by hand changes nothing.

Worth recording: the root cause named in the original issue was wrong. `addSegmentsEntry(...,
{"growpatch"})` has been in `startGrowPatchFromSeedImpl` since [#1121](https://github.com/ScrollPrize/villa/pull/1121) (8 July), a month before the
report. The entry was never missing; the *selection* moves on reopen. Doctests 34 -> 36.

**[#1869](https://github.com/ScrollPrize/villa/pull/1869) — `--resume-generations` was accepted, stored, and never read**
*Found by @Bullo27 while documenting the CLI resume path in [#1763](https://github.com/ScrollPrize/villa/pull/1763).*

The flag was parsed into `params["resume_generations"]`. Nothing in `core` ever read that key.
`GrowPatch` takes its stopping generation from `params["generations"]`, which is a total and not
an increment, so resuming a segment with the params file that produced it grew **nothing**: the
tool logged "Resuming from generation 7 with 196 points" and wrote the same 196 points to a new
directory, with or without the flag.

After: `--resume --resume-generations 8` continues from generation 8 to 15 and writes
**900 points / 7.018 cm2** in 13 s, with an md5-identical `generations.tif` to the
`generations: 16` run that was previously the only way to continue. Used without `--resume` the
option now exits 1 instead of being ignored.

### The winding audit

**[#1864](https://github.com/ScrollPrize/villa/pull/1864) and [#1876](https://github.com/ScrollPrize/villa/pull/1876)**
*Issue [#1855](https://github.com/ScrollPrize/villa/issues/1855) (@sergeievland), who supplied the harness, the pinned data and a solver patch. Split into two PRs at @pmh47's request.*

`find_inconsistent_windings.py` is what people run before a spiral fit, and its `min_edge_fix`
suggestions are used to edit winding annotations in VC3D. Two independent defects:

*The theta=0 step (#1864).* Relative winding edges were corrected for branch-ray crossings at the
annotation points' own coordinates, but every within-patch strip starts and ends at the point's
*attachment* on the surface. The short step between a point and its attachment was counted by
neither. At col109 point 1560 that step spans theta 6.28214 to 0.00016 — 1.37 voxels apart — and both
equations through the point come out one winding wrong. On the real PHercParis4 graph (335
patches, 645 equations) main reports **3 inconsistent cycles and recommends 2 edits, one of them
at an annotation that agrees with every other equation in the graph**. With the fix and main's
unchanged solver: 1 cycle, 1 edit — the genuine disagreement. Exactly 4 of 1,304 directed edges
change, and the result matches the reporter's independently corrected graph in **0 of 1,304**
edges.

*The repair model (#1876).* `solve_min_edge_fix` documents `allowed_edge_keys` as restricting
which edges may *change*, but built the model from those edges only, so every other measured
equation left it: **7 of 645 equations and 14 MILP rows survived**. A repair could close one
inconsistent cycle by breaking a consistent cycle the model never saw. The potential box was also
centred on the BFS labelling with a margin that excludes the optimum, the gauge node was looked
up as a string that never matches a patch id, and the solve accepted the default MIP gap.
After: **645 of 645 equations, 1,290 rows, 7 editable**, Optimal in 0.021 s, and the reporter's
`check_solver.py` goes from exit 1 to exit 0.

### Loaders, data access and streaming

**[#1798](https://github.com/ScrollPrize/villa/pull/1798) — merged — normal-grid level silently ignored**
*Issue [#1776](https://github.com/ScrollPrize/villa/issues/1776) (@rodriguescarson), who proposed the warning. Reproduced independently by @nerln on the official PHerc1218 store before merge.*

Asking for a coarser `normal_grid_level` to speed up growth silently gave level 0 on a
single-scale store, and a silent clamp on a multiscale one. The log said only "Loaded normal grid
level 0". Now both cases warn and name the level actually used, and the message points at
`vc_gen_normalgrids pyramid`. Doctests 9 -> 11. **Merged 2026-09-24 by @hendrikschilling.**

**[#1804](https://github.com/ScrollPrize/villa/pull/1804) — a published volume that cannot be opened at all**
*Issue [#1755](https://github.com/ScrollPrize/villa/issues/1755) (@sgsllc-jr).*

Both Frag3 88 keV stores declare six multiscale levels in `.zattrs`; only level 0 is published,
and `1/.zarray` through `5/.zarray` return 404. The loader opened every declared level with no
error handling, so it failed on level 1 and the volume could not be opened **even at the intact
level 0** — `vc_render_tifxyz` exited 1 without reading anything. After: one warning naming the
skipped levels, and level 0 renders (uint16, 10933-27180, all 65536 pixels nonzero). Asking for a
skipped level still fails loudly. Complete pyramids are unchanged, with no new output.

**[#1808](https://github.com/ScrollPrize/villa/pull/1808) — the cache that inference could not switch on**
*Issue [#1325](https://github.com/ScrollPrize/villa/issues/1325) (@aistae), request counting by @TAUIL-Abd-Elilah, cache from merged [#1373](https://github.com/ScrollPrize/villa/pull/1373).*

`vesuvius.predict` reads overlapping patches, and every patch re-downloaded the chunks it touched.
An in-memory LRU chunk cache had already been merged into `Volume`, but `predict` had no way to
turn it on. On Scroll 1 at 192^3 patches: **1000 chunk GETs (796 MB) -> 250 (199 MB)** with the
default 4 workers, and 125 with `--num_workers 0`. Logits sha256 identical in every run. Default
of 0 leaves `predict` byte-for-byte unchanged.

**[#1863](https://github.com/ScrollPrize/villa/pull/1863) — remote rendering asked for a path it never used**
*Issue [#1555](https://github.com/ScrollPrize/villa/issues/1555). This is a rework: my first attempt (#1797) was closed by @hendrikschilling because mixing a remote URL with a local `-v` is the wrong interface.*

`vc_render_tifxyz`'s remote path documented an on-disk staged cache that was never written,
`--remote-url` could never be omitted, and `-v` was required but unused when streaming. The
rework does what the maintainer asked for instead: `-v` takes a local directory **or** a URL,
`--remote-url` becomes a deprecated alias, and the dead marker reader and misleading help are
gone. A remote volume's voxel size now comes from its own `metadata.json`, so URL renders get the
resolution tags main could only produce with two extra flags. Before: `-v <url>` exits 1,
`--remote-url` alone exits 1. After: three byte-identical 600 x 600 tifs, 0 files written outside
`~/.VC3D/remote_cache`.

I include this one deliberately, because the first version was wrong in a way worth recording:
**it fixed the bug and made the interface worse.** The maintainer's closing note — take a path or
take a URL, do not invent a third thing — is the more useful output of that exchange than the
patch was.

**[#1868](https://github.com/ScrollPrize/villa/pull/1868) — two published volumes unreachable by name**
*Issue [#1652](https://github.com/ScrollPrize/villa/issues/1652) (@nerln); scroll-3 resolution finding carried from @dud8's closed #1710 with co-authorship.*

`scrolls.yaml` lists one volume per scroll while the server publishes more, so Scroll 1B — named
in `volume.py`'s own example comment — and the Scroll 4 88 keV scan, which the loader's canonical
maps already declare as scroll 4's default, could not be opened by scroll identity at all. The
two simplest calls in the docs, `Volume(type="scroll", scroll_id=3)` and `scroll_id=4`, both
raised. Ten real calls, each reading a 64 x 64 patch from level 0: **5 of 10 raised on main, 0 of
10 on the branch**, and the five that already worked return byte-identical patches.

### The website

**[#1882](https://github.com/ScrollPrize/villa/pull/1882) — a data browser panel that implied scans nobody took**
*Issue [#1881](https://github.com/ScrollPrize/villa/issues/1881) (@giorgioangel).*

The "Data & access" panel listed smallest voxel size, all energies and all sources as three
independent rows, which reads as their cross-product: for PHerc. Paris 4 that is 4 x 5 x 2 = 40
combinations where **6 were actually scanned**. Because only the *minimum* voxel size was shown,
PHerc0343P's 8.64 um scan did not appear on the page at all. Separately the WEBKNOSSOS button
linked one dataset per scroll where Scroll 1 has five and Scroll 4 has five.

After: one "Scan configurations" row of the (voxel size, energy, source) tuples that exist with
their scan counts, and a picker offering every published dataset. Which dataset belongs to which
scroll is read off each dataset's own layer paths in the public listing, not guessed. One curation
error surfaced with it: PHerc0343 linked `PHerc0343P-4um`, a different sample. `yarn test`
331 passing, 8 of them new; before/after captured from the rendered page and from `yarn build`
static HTML.

---

## Reproducing any of this

Every pull request body carries the exact commands, the upstream commit it was measured against,
and the published URL of every byte of data used. Nothing in this report was measured on
synthetic data except where a unit test is described as such.

Where a number came from the original reporter rather than from my own run, it is attributed in
the pull request and not claimed here — most importantly, in #1877 the full 74,683-chunk census,
the "48 of 150 seeds" draw and the 9.21 cm2 trace are @evilaliv3's; my sample is 200 chunks and
one trace, and is reported as mine.

---

## Credit

These are other people's bug reports. @Aleredfer, @evilaliv3, @Bullo27, @sergeievland, @nerln,
@rodriguescarson, @sgsllc-jr, @aistae, @flummoxjr, @giorgioangel and @TAUIL-Abd-Elilah found and
measured the defects; several supplied harnesses, pinned data or candidate patches that are
carried here with co-authorship. @hendrikschilling, @pmh47 and @bruniss reviewed, and two of the
changes above exist in their current shape because a maintainer rejected the first one.
Prior closed attempts by @olgaiv39, @AnayGarodia, @dud8 and @Bullo27 are adopted with
co-authorship where their code is used.

---

*AI-assisted, human-directed.*

---

# The other half: `scan_support`

Fixing `vc_grow_seg_from_seed` so it refuses a seed in the air ([#1877](https://github.com/ScrollPrize/villa/pull/1877))
only helps traces that have not been run yet. It says nothing about the surfaces that already
exist — and, as it turns out, some of those are published.

`scan_support` is a single Python file that takes a tifxyz surface and the raw masked scan it
was traced from, and reports what fraction of its cells stand on a scan voxel that exists and
is above zero. It is in this report's companion repository (https://github.com/CVasilopoulos/scan-support), with a README, 35 self-tests that
need no network, and an MIT licence.

```
scan_support.py --scroll PHerc1447
```

**Four buckets, never three.** Each cell is *on data*, *on a zero voxel*, *in a chunk the store
does not hold*, or *outside the array entirely*. Collapsing them is how you get a number that
means nothing. Surfaces reaching outside their own volume is not an edge case: of the 1,186
(segment, volume) pairs in the open-data catalogue that carry an `overlap_ratio`, 605 are below
1.0 and 369 are below 0.5 — the bounding box is less than half inside the volume it is
registered against. And in Python `-16444 // 128 == -129` builds a perfectly plausible chunk URL
that 404s for entirely the wrong reason, which would be scored as "the scan has no data here".

**It refuses to guess.** A tifxyz records no volume identity, so pairing a surface with a scan
by hand is unverified. If the cells do not fit inside the scan array the tool prints both
extents and exits 2 rather than returning a support figure computed against the wrong grid.
Under `--scroll` the pairing is not a guess: the open-data bucket names the volume on both
sides — `<segid>-on-<volumeid>-<voxel>.tifxyz` against
`volumes/<volumeid>-<voxel>-...-masked.zarr` — and the catalogue's own
`creation.derived_from` names it a third time.

**A voxel costs one byte.** The published masked scans are uncompressed `uint8` with `128³`
C-order chunks, so a voxel is one byte at a computable offset. A `Range: bytes=N-N` request
answers both questions at once — `404` means the chunk is not in the store, `206` carries the
voxel — and no chunk is ever downloaded:

```
whole chunks   2 surfaces, 259 requests (166 HEAD,   93 GET, 192.9 MB)   2m46s
byte ranges    2 surfaces, 2498 requests (166 HEAD, 2332 GET,   0.0 MB)  1m28s
```

Identical counts, 193 MB less traffic. That is what makes auditing a whole scroll affordable.

### Calibration

The metric is anchored on the pair from #1877. Two patches grown by `vc_grow_seg_from_seed`
from the same published PHerc1447 m7 prediction, 24 generations, 2116 cells each, both
reporting 0.6087 cm²:

| | on data | zero voxel | absent chunk | support |
|---|---|---|---|---|
| seed in a phantom block | 60 | 155 | 1901 | **2.8%** |
| seed on real material | 2090 | 26 | 0 | **98.8%** |

Those counts reproduce, to the cell, the numbers the C++ guard in #1877 produces through a
completely different code path. A healthy surface scores in the high nineties; a surface grown
in the air scores near zero. The measure separates them.

### What is not new here

The artefact itself is other people's work: [#1114](https://github.com/ScrollPrize/villa/issues/1114)
(@spencerdavis-tx), [#1254](https://github.com/ScrollPrize/villa/issues/1254)
(@TAUIL-Abd-Elilah), [#1875](https://github.com/ScrollPrize/villa/issues/1875) (@evilaliv3),
and @Bullo27's census over 23 First Letters volumes. Five community repositories already audit
it — Schurkai's `vesuvius-phantom-audit`, axiosdevs' `herculaneum-scroll-tools`, Jinhojeong's
surface-geometry diagnostic, bkalita-git's `scroll-audit`, ShribyrLabs' reports. Bbox-level
overlap is already published as `properties.volume_coverage[].overlap_ratio` in the catalogue;
the figures above are read out of that published field, not discovered.

**Every one of those measures a prediction volume.** What none of them does — and what
`vesuvius.surface_preflight` cannot do, because it is a pass/fail gate at 0.95 over 1024 samples
and zarr materialises a missing chunk as `fill_value`, so it cannot tell an absent chunk from a
zero voxel — is take a *published segment*, resolve the scan it names, and score its cells.

### What it found

Run over every published surface of PHerc. 1447 — fifteen of them, one scan, 15m29s, no chunk
downloaded — the distribution is not a gradient. It is two populations:

| | surfaces | support |
|---|---|---|
| published under `segments/`, copied from the challenge's own segment store | 5 | 98.2% – **100.0%** |
| published under `segments/`, copied from a personal bucket, all timestamped 2 May 2025 | 10 | **7.5%** – 56.7% |

Four of the five score 3000 of 3000 sampled cells on data — not one cell on a zero voxel, not
one in an absent chunk, not one outside the array. The other ten have between 793 and 2331 of
their 3000 cells in chunks the raw masked scan **does not hold at all**, and nothing in the
published metadata says so: `properties.volume_coverage` is `null` for all fifteen.

Three explanations are ruled out in `FINDINGS.md`: the volume is not truncated (it is densely
stored through the whole z extent, including the band those surfaces occupy), there is no
coordinate offset (five surfaces on the same volume with the same convention score 100.0% at
zero shift, and shifting the worst one produces a monotonic gradient with no peak), and it is
not the empty-cell marker.

**And they are not normal.** Running the same audit over the rest of the published corpus, one
sample at a time, the ten worst surfaces measured so far are *exactly* those ten, and then there
is a gap: the tenth-worst sits at 60.6% of its in-volume cells on data with 32.7% in absent
chunks, and the eleventh — from a different scroll — at 75.4% and 9.7%. Four healthy samples
measured alongside it (PHerc0009B, PHerc0343P, PHerc0800, PHerc0841, 64 surfaces) run from 75.4%
to 100%, and two of them lose nothing at all. Five of the bucket's 45 samples are complete at the
time of writing and the six largest are still running; `FINDINGS.md` carries the caveat and the
command to refresh it.

These are the surfaces a newcomer reaches for. They open in VC3D, they render, they carry
sensible areas, and half of one of them is air.

---

## What I would want a reviewer to check hardest

The claim I am least able to close from outside the project is *why* those ten surfaces are in
the catalogue. I can show what their cells sit on and where they were copied from. I cannot
show intent, and I have not asserted any.

The rest is arithmetic on published bytes, and the commands to redo all of it are in
`FINDINGS.md` and in each pull request.
