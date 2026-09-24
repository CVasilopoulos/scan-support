"""Self-test: build a scan and three surfaces on disk, check every reported number.

Run with:  uv run --no-project --with numpy --with tifffile python test_scan_support.py
"""

import json
import os
import shutil
import sys
import tempfile

import numpy as np
import tifffile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scan_support as ss

CHUNK = 8
SHAPE = (32, 32, 32)
FAILURES = []


def check(name, got, want):
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))
        print("  FAIL %-46s got %r want %r" % (name, got, want))
    else:
        print("  ok   %-46s %r" % (name, got))


def write_scan(root):
    """A scan where only chunk (0,0,0) exists. Half its voxels are zero."""
    os.makedirs(os.path.join(root, "0"))
    with open(os.path.join(root, "0", ".zarray"), "w") as fh:
        json.dump({"zarr_format": 2, "shape": list(SHAPE), "chunks": [CHUNK] * 3,
                   "dtype": "|u1", "compressor": None, "fill_value": 0,
                   "order": "C", "filters": None, "dimension_separator": "/"}, fh)
    block = np.zeros((CHUNK, CHUNK, CHUNK), dtype=np.uint8)
    block[:, :, :4] = 200          # x < 4 is material, x >= 4 is zero
    os.makedirs(os.path.join(root, "0", "0", "0"), exist_ok=True)
    with open(os.path.join(root, "0", "0", "0", "0"), "wb") as fh:
        fh.write(block.tobytes())


def write_surface(root, points, grid=(4, 4)):
    os.makedirs(root, exist_ok=True)
    planes = {a: np.full(grid, -1.0, dtype=np.float32) for a in "xyz"}
    for i, (z, y, x) in enumerate(points):
        r, c = divmod(i, grid[1])
        planes["z"][r, c] = z
        planes["y"][r, c] = y
        planes["x"][r, c] = x
    for a, p in planes.items():
        tifffile.imwrite(os.path.join(root, "%s.tif" % a), p)
    with open(os.path.join(root, "meta.json"), "w") as fh:
        json.dump({"area_cm2": 0.5}, fh)


def main():
    tmp = tempfile.mkdtemp(prefix="scan_support_test_")
    try:
        scan_root = os.path.join(tmp, "scan.zarr")
        write_scan(scan_root)
        scan = ss.Scan(scan_root)
        check("scan shape", scan.shape, SHAPE)
        check("scan chunks", scan.chunks, (CHUNK,) * 3)
        check("scan decodable", scan.decodable(), (True, "raw"))

        # 1. every cell on material inside the one chunk that exists
        good = os.path.join(tmp, "good")
        write_surface(good, [(1, 1, 0), (2, 2, 1), (3, 3, 2), (4, 4, 3)])
        r = ss.audit(ss.Surface(good), scan)
        check("good: valid cells", r["cells_valid"], 4)
        check("good: on data", r["cells_on_data"], 4)
        check("good: on zero", r["cells_on_zero"], 0)
        check("good: chunks absent", r["chunks_absent"], 0)
        check("good: support", round(r["support"], 6), 1.0)
        check("good: area from meta", r["area_cm2"], 0.5)

        # 2. every cell in a chunk the store does not hold
        phantom = os.path.join(tmp, "phantom")
        write_surface(phantom, [(20, 20, 20), (21, 21, 21), (22, 22, 22), (23, 23, 23)])
        r = ss.audit(ss.Surface(phantom), scan)
        check("phantom: cells in absent chunks", r["cells_in_absent_chunks"], 4)
        check("phantom: chunks absent", r["chunks_absent"], r["chunks_touched"])
        check("phantom: on data", r["cells_on_data"], 0)
        check("phantom: support", r["support"], 0.0)

        # 3. a chunk that exists, but the voxels there are zero
        zeros = os.path.join(tmp, "zeros")
        write_surface(zeros, [(1, 1, 5), (2, 2, 6), (3, 3, 7), (1, 2, 0)])
        r = ss.audit(ss.Surface(zeros), scan)
        check("zeros: chunks absent", r["chunks_absent"], 0)
        check("zeros: cells in absent chunks", r["cells_in_absent_chunks"], 0)
        check("zeros: on zero", r["cells_on_zero"], 3)
        check("zeros: on data", r["cells_on_data"], 1)
        check("zeros: support", round(r["support"], 6), 0.25)

        # presence mode counts a present-but-zero chunk as supported: an upper bound
        r = ss.audit(ss.Surface(zeros), scan, mode="presence")
        check("zeros: presence support is 1.0 (upper bound)", round(r["support"], 6), 1.0)
        check("zeros: presence flags the bound", r["support_is_upper_bound"], True)
        check("zeros: presence reads no voxels", r["cells_on_data"], None)

        # 4. -1 sentinels and NaNs are not cells
        holes = os.path.join(tmp, "holes")
        write_surface(holes, [(1, 1, 0), (2, 2, 1)])   # 2 written, 14 left at -1
        r = ss.audit(ss.Surface(holes), scan)
        check("holes: valid cells only", r["cells_valid"], 2)
        check("holes: on data", r["cells_on_data"], 2)

        # 4b. a legitimate -1 in ONE axis is a real cell, not the empty marker.
        #     Published surfaces carry coordinates far below zero, so testing a single
        #     component would silently delete them.
        neg = os.path.join(tmp, "neg")
        write_surface(neg, [(1, 1, 0), (2, -1, 1), (3, 3, 2)])
        sneg = ss.Surface(neg)
        check("one-axis -1 is still a cell", sneg.cells_valid, 3)
        check("empty cells counted separately", sneg.cells_empty, 13)

        # 4c. cells outside the scan array are their own bucket, never "absent chunk"
        half = os.path.join(tmp, "half")
        write_surface(half, [(1, 1, 0), (2, 2, 1), (99, 99, 99), (-5, -5, -5)])
        r = ss.audit(ss.Surface(half), scan, mode="presence")
        check("outside-volume cells bucketed", r["cells_outside_volume"], 2)
        check("outside cells are not counted as absent chunks",
              r["cells_in_absent_chunks"], 0)
        check("negative coords never form a chunk index", r["chunks_touched"], 1)
        check("support excludes out-of-volume cells", round(r["support"], 6), 0.5)

        # 5. the grid check refuses a surface that does not fit the scan
        far = os.path.join(tmp, "far")
        write_surface(far, [(1000, 1000, 1000)])
        check("grid check refuses an out-of-range surface",
              len(ss.grid_check([ss.Surface(far)], scan)), 1)
        check("grid check passes a fitting surface",
              ss.grid_check([ss.Surface(good)], scan), [])

        # 6. the CLI exit codes
        check("cli exit 0 on a supported surface",
              ss.main(["--scan", scan_root, good]), 0)
        check("cli exit 1 under --fail-under",
              ss.main(["--scan", scan_root, phantom, "--fail-under", "0.5"]), 1)
        check("cli exit 2 when grids disagree",
              ss.main(["--scan", scan_root, far]), 2)
        check("cli exit 2 when --scan is not a zarr",
              ss.main(["--scan", tmp, good]), 2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print("%d FAILED" % len(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
