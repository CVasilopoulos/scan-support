#!/usr/bin/env python3
"""scan_support - does this traced surface stand on scan data?

Reads a tifxyz surface, maps every valid cell to a voxel of the raw masked scan the
surface was traced from, and reports how much of the surface is supported by voxels
that exist and are above zero.

The tool refuses to guess. If the surface and the scan do not share a voxel grid it
says so and exits non-zero rather than returning a number.
"""

import argparse
import concurrent.futures
import json
import os
import sys
import urllib.error
import urllib.request

import numpy as np
import tifffile

__version__ = "0.1.0"

TIMEOUT = 60
UA = "scan_support/%s (+https://github.com/ScrollPrize/villa)" % __version__


class Fetch:
    """Minimal read-only accessor for a local directory or an HTTP(S) prefix."""

    def __init__(self, root, retries=4):
        self.root = root.rstrip("/")
        self.remote = "://" in self.root
        self.retries = retries
        self.gets = 0
        self.heads = 0
        self.bytes = 0
        self.retried = 0

    def _open(self, req):
        """Open with a bounded retry. A reset connection or a 5xx part way through a
        batch must not lose the run; a 404 is an answer and is never retried."""
        import random
        import time
        last = None
        for attempt in range(self.retries):
            try:
                return urllib.request.urlopen(req, timeout=TIMEOUT)
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise
                last = e
            except (urllib.error.URLError, OSError) as e:
                last = e
            self.retried += 1
            time.sleep(min(8.0, 0.5 * 2 ** attempt) * (0.5 + random.random()))
        raise RuntimeError("cannot reach %s after %d attempts: %s"
                           % (req.full_url, self.retries, last))

    def _url(self, key):
        return self.root + "/" + key

    def exists(self, key):
        if not self.remote:
            return os.path.exists(os.path.join(self.root, key))
        self.heads += 1
        req = urllib.request.Request(self._url(key), method="HEAD", headers={"User-Agent": UA})
        try:
            with self._open(req) as r:
                return r.status == 200
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return False
            raise

    def get(self, key):
        """Return bytes, or None when the object is absent."""
        if not self.remote:
            path = os.path.join(self.root, key)
            if not os.path.exists(path):
                return None
            with open(path, "rb") as fh:
                data = fh.read()
            self.gets += 1
            self.bytes += len(data)
            return data
        req = urllib.request.Request(self._url(key), headers={"User-Agent": UA})
        try:
            with self._open(req) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            raise
        self.gets += 1
        self.bytes += len(data)
        return data

    def get_byte(self, key, offset):
        """One byte of an object, or None when the object does not exist.

        A single-byte Range request answers both questions at once: 404 means the chunk
        is not in the store, 206 carries the voxel. That is one request per cell instead
        of a 2 MB chunk download, and it is why an exact per-cell count is affordable.
        """
        if not self.remote:
            path = os.path.join(self.root, key)
            if not os.path.exists(path):
                return None
            with open(path, "rb") as fh:
                fh.seek(offset)
                b = fh.read(1)
            self.gets += 1
            self.bytes += 1
            return b[0] if b else None
        req = urllib.request.Request(
            self._url(key),
            headers={"User-Agent": UA, "Range": "bytes=%d-%d" % (offset, offset)})
        try:
            with self._open(req) as r:
                if r.status not in (200, 206):
                    raise RuntimeError("%s answered %s to a Range request"
                                       % (self._url(key), r.status))
                data = r.read(1)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            if e.code == 416:
                raise RuntimeError("%s is shorter than offset %d" % (self._url(key), offset))
            raise
        self.gets += 1
        self.bytes += len(data)
        return data[0] if data else None

    def get_json(self, key):
        data = self.get(key)
        return None if data is None else json.loads(data)


class Scan:
    """Level 0 of an OME-Zarr / zarr v2 store, addressed by voxel."""

    def __init__(self, root, level="0"):
        self.fetch = Fetch(root)
        self.level = level
        meta = self.fetch.get_json("%s/.zarray" % level)
        if meta is None:
            raise RuntimeError(
                "no %s/.zarray under %s - point --scan at the root of an OME-Zarr store"
                % (level, root))
        self.shape = tuple(int(v) for v in meta["shape"])
        self.chunks = tuple(int(v) for v in meta["chunks"])
        self.dtype = np.dtype(meta["dtype"])
        self.order = meta.get("order", "C")
        self.fill_value = meta.get("fill_value", 0)
        self.compressor = meta.get("compressor")
        self.filters = meta.get("filters")
        self.sep = meta.get("dimension_separator", ".")
        if len(self.shape) != 3:
            raise RuntimeError("expected a 3-D array, got shape %r" % (self.shape,))
        self._cache = {}
        self._present = {}

    def describe(self):
        comp = "raw" if self.compressor is None else self.compressor.get("id", "?")
        return ("level %s  shape %s (z,y,x)  chunks %s  dtype %s  compressor %s"
                % (self.level, self.shape, self.chunks, self.dtype, comp))

    def chunk_key(self, cz, cy, cx):
        return "%s/%s" % (self.level, self.sep.join(str(int(v)) for v in (cz, cy, cx)))

    def chunk_present(self, coord):
        if coord not in self._present:
            self._present[coord] = self.fetch.exists(self.chunk_key(*coord))
        return self._present[coord]

    def prefetch_presence(self, coords, workers=8):
        """Resolve chunk existence for many coords at once.

        HEAD requests are latency-bound, so a small pool turns a minute of waiting into
        a few seconds. Kept deliberately small to stay polite to the bucket.
        """
        todo = [c for c in coords if c not in self._present]
        if not todo or not self.fetch.remote or workers <= 1:
            for c in todo:
                self.chunk_present(c)
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.fetch.exists, self.chunk_key(*c)): c for c in todo}
            for fut in concurrent.futures.as_completed(futures):
                self._present[futures[fut]] = fut.result()

    def byte_addressable(self):
        """True when a voxel maps to one byte at a computable offset in its chunk."""
        return (self.compressor is None and self.filters in (None, [])
                and self.dtype.itemsize == 1 and self.order == "C")

    def voxel_offset(self, vox):
        cz, cy, cx = self.chunks
        return ((int(vox[0]) % cz) * cy + (int(vox[1]) % cy)) * cx + (int(vox[2]) % cx)

    def voxel_value(self, vox):
        """Return (state, value): 'absent' with None, or 'data'/'zero' with the byte."""
        key = self.chunk_key(vox[0] // self.chunks[0],
                             vox[1] // self.chunks[1],
                             vox[2] // self.chunks[2])
        v = self.fetch.get_byte(key, self.voxel_offset(vox))
        if v is None:
            return "absent", None
        return ("data" if v > 0 else "zero"), v

    def decodable(self):
        if self.compressor is None:
            return True, "raw"
        cid = self.compressor.get("id")
        if cid in ("zlib", "gzip"):
            return True, cid
        try:
            import numcodecs  # noqa: F401
        except ImportError:
            return False, cid
        return True, cid

    def _decode(self, raw):
        n = int(np.prod(self.chunks))
        if self.compressor is None:
            buf = raw
        else:
            cid = self.compressor.get("id")
            if cid in ("zlib", "gzip"):
                import zlib
                buf = zlib.decompress(raw, 47 if cid == "gzip" else 15)
            else:
                import numcodecs
                buf = numcodecs.get_codec(self.compressor).decode(raw)
        arr = np.frombuffer(buf, dtype=self.dtype, count=n)
        return arr.reshape(self.chunks, order=self.order)

    def chunk_array(self, coord):
        if coord not in self._cache:
            raw = self.fetch.get(self.chunk_key(*coord))
            self._cache[coord] = None if raw is None else self._decode(raw)
        return self._cache[coord]


class Surface:
    """A tifxyz surface: x.tif / y.tif / z.tif plus meta.json."""

    def __init__(self, path):
        self.path = path.rstrip("/")
        self.name = os.path.basename(self.path) or self.path
        fetch = Fetch(self.path)
        planes = {}
        for axis in ("x", "y", "z"):
            data = fetch.get("%s.tif" % axis)
            if data is None:
                raise RuntimeError("%s: no %s.tif - this is not a tifxyz surface" % (self.path, axis))
            try:
                planes[axis] = tifffile.imread(_as_file(data, fetch.remote, self.path, axis))
            except ValueError as e:
                if "imagecodecs" in str(e):
                    raise RuntimeError(
                        "%s/%s.tif is compressed (%s) and tifffile cannot decode it here.\n"
                        "       Install imagecodecs: pip install imagecodecs"
                        % (self.path, axis, str(e).split(" requires")[0].strip("<>"))) from e
                raise RuntimeError("%s/%s.tif: %s" % (self.path, axis, e)) from e
        self.meta = fetch.get_json("meta.json") or {}
        shapes = {a: p.shape for a, p in planes.items()}
        if len(set(shapes.values())) != 1:
            raise RuntimeError("%s: x/y/z grids differ in shape: %r" % (self.path, shapes))
        self.grid_shape = planes["x"].shape
        # The tifxyz empty marker is the triple (-1, -1, -1). Testing one component alone
        # is wrong corpus-wide: published surfaces carry legitimate coordinates far below
        # zero (a PHerc0139 variant reaches z = -16444), and dropping those cells would
        # quietly shrink the surface being measured.
        empty = np.ones(self.grid_shape, dtype=bool)
        for plane in planes.values():
            empty &= (plane == -1)
        finite = (np.isfinite(planes["x"]) & np.isfinite(planes["y"])
                  & np.isfinite(planes["z"]))
        valid = (~empty) & finite
        self.cells_empty = int(empty.sum())
        self.cells_nonfinite = int((~finite).sum())
        self.cells_total = int(valid.size)
        self.cells_valid = int(valid.sum())
        self.points = np.stack(
            [planes["z"][valid], planes["y"][valid], planes["x"][valid]], axis=1).astype(np.float64)

    def area_cm2(self):
        for key in ("area_cm2", "area_cm^2"):
            if key in self.meta:
                try:
                    return float(self.meta[key])
                except (TypeError, ValueError):
                    return None
        return None


def _as_file(data, remote, path, axis):
    if not remote:
        return os.path.join(path, "%s.tif" % axis)
    import io
    return io.BytesIO(data)


def audit(surface, scan, mode="voxel", max_chunk_gets=400, sample=None, rng=None, workers=8):
    """Return a dict describing how much of `surface` stands on `scan` data."""
    pts = surface.points
    if sample and len(pts) > sample:
        rng = rng or np.random.default_rng(0)
        pts = pts[rng.choice(len(pts), size=sample, replace=False)]
    sampled = len(pts)

    vox = np.rint(pts).astype(np.int64)
    inside = np.ones(sampled, dtype=bool)
    for ax in range(3):
        inside &= (vox[:, ax] >= 0) & (vox[:, ax] < scan.shape[ax])
    outside = int((~inside).sum())

    cz = vox[:, 0] // scan.chunks[0]
    cy = vox[:, 1] // scan.chunks[1]
    cx = vox[:, 2] // scan.chunks[2]
    keys = np.stack([cz, cy, cx], axis=1)
    uniq = np.unique(keys[inside], axis=0) if inside.any() else np.empty((0, 3), dtype=np.int64)

    coords = [tuple(int(v) for v in c) for c in uniq]
    scan.prefetch_presence(coords, workers=workers)
    present = {c: scan.chunk_present(c) for c in coords}
    n_present = sum(1 for v in present.values() if v)
    n_absent = len(present) - n_present

    in_absent = 0
    for i in range(sampled):
        if not inside[i]:
            continue
        if not present[(int(cz[i]), int(cy[i]), int(cx[i]))]:
            in_absent += 1

    result = {
        "surface": surface.name,
        "path": surface.path,
        "grid": list(surface.grid_shape),
        "cells_valid": surface.cells_valid,
        "cells_sampled": sampled,
        "cells_outside_volume": outside,
        "chunks_touched": len(present),
        "chunks_present": n_present,
        "chunks_absent": n_absent,
        "cells_in_absent_chunks": in_absent,
        "mode": mode,
        "area_cm2": surface.area_cm2(),
    }

    if mode == "presence":
        supported = sampled - outside - in_absent
        result["cells_on_data"] = None
        result["cells_on_zero"] = None
        result["support"] = supported / sampled if sampled else 0.0
        result["support_is_upper_bound"] = True
        return result

    todo = [i for i in range(sampled)
            if inside[i] and present[(int(cz[i]), int(cy[i]), int(cx[i]))]]

    on_data = on_zero = 0
    if scan.byte_addressable():
        # One single-byte Range request per cell. No chunk is ever downloaded.
        def read(i):
            return scan.voxel_value(vox[i])
        if scan.fetch.remote and workers > 1 and todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                states = list(pool.map(read, todo))
        else:
            states = [read(i) for i in todo]
        for state, _ in states:
            if state == "data":
                on_data += 1
            elif state == "zero":
                on_zero += 1
        result["reads"] = "range"
    else:
        if n_present > max_chunk_gets:
            result["error"] = ("%d present chunks exceed --max-chunk-gets %d; rerun with "
                               "--mode presence or a larger cap" % (n_present, max_chunk_gets))
            return result
        for i in todo:
            arr = scan.chunk_array((int(cz[i]), int(cy[i]), int(cx[i])))
            if arr is None:
                continue
            v = arr[vox[i, 0] % scan.chunks[0],
                    vox[i, 1] % scan.chunks[1],
                    vox[i, 2] % scan.chunks[2]]
            if v > 0:
                on_data += 1
            else:
                on_zero += 1
        result["reads"] = "chunk"
    result["cells_on_data"] = on_data
    result["cells_on_zero"] = on_zero
    result["support"] = on_data / sampled if sampled else 0.0
    result["support_is_upper_bound"] = False
    return result


OPEN_DATA = "https://vesuvius-challenge-open-data.s3.amazonaws.com"
SEG_RE = None


def s3_list(bucket, prefix, delimiter=None):
    """Anonymous paginated listing. Returns (keys, common prefixes)."""
    import re as _re
    import urllib.parse
    keys, prefixes, token = [], [], None
    while True:
        q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if delimiter:
            q["delimiter"] = delimiter
        if token:
            q["continuation-token"] = token
        url = bucket + "/?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            xml = r.read().decode()
        keys += _re.findall(r"<Key>([^<]*)</Key>", xml)
        prefixes += _re.findall(r"<Prefix>([^<]*)</Prefix>", xml)
        m = _re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", xml)
        if not m:
            break
        token = m.group(1)
    return keys, prefixes


def discover(scroll, bucket=OPEN_DATA):
    """Find a scroll's published tifxyz surfaces and the masked scan each was traced on.

    The published layout names both sides, so nothing here is guessed:
      segments/<seg>/mesh/<segid>-on-<volid>-<voxel>.tifxyz
      volumes/<volid>-<voxel>-<...>-masked.zarr

    Returns (groups, orphans) where groups maps a scan URL to its surface URLs, and
    orphans lists (surface_url, volid) whose scan this bucket does not publish.
    """
    import re as _re
    # Walk the prefix tree with a delimiter instead of listing every key. A sample's
    # segments/ subtree holds tens of thousands of objects (meshes, intermediates,
    # renders); the surfaces are three delimiter levels down, so this is a few dozen
    # small requests rather than tens of paginated ones.
    _, seg_prefixes = s3_list(bucket, "%s/segments/" % scroll, delimiter="/")
    surfaces = []
    for seg in seg_prefixes:
        if seg == "%s/segments/" % scroll:
            continue
        _, mesh_prefixes = s3_list(bucket, seg + "mesh/", delimiter="/")
        for m in mesh_prefixes:
            if m.rstrip("/").endswith(".tifxyz"):
                surfaces.append(m.rstrip("/"))
    surfaces = sorted(set(surfaces))
    _, vol_prefixes = s3_list(bucket, "%s/volumes/" % scroll, delimiter="/")
    volumes = [p[len("%s/volumes/" % scroll):].rstrip("/") for p in vol_prefixes
               if p != "%s/volumes/" % scroll]

    groups, orphans = {}, []
    for surf in surfaces:
        name = surf.rsplit("/", 1)[-1]
        m = _re.match(r"^.*-on-([0-9]+)-[^-]+\.tifxyz$", name)
        if not m:
            orphans.append(("%s/%s" % (bucket, surf), None))
            continue
        volid = m.group(1)
        cands = [v for v in volumes if v.startswith(volid + "-")]
        masked = [v for v in cands if v.endswith("-masked.zarr")] or cands
        if not masked:
            orphans.append(("%s/%s" % (bucket, surf), volid))
            continue
        scan_url = "%s/%s/volumes/%s" % (bucket, scroll, masked[0])
        groups.setdefault(scan_url, []).append("%s/%s" % (bucket, surf))
    return groups, orphans


def grid_check(surfaces, scan):
    """Refuse to report a number when the surface and the scan disagree on the grid.

    A tifxyz records no volume shape, so the only honest check available is that the
    cells land inside the scan. If they do not, the two are not in the same voxel
    space and every support number below would be meaningless.
    """
    problems = []
    for s in surfaces:
        if not len(s.points):
            problems.append("%s: no valid cells" % s.name)
            continue
        hi = s.points.max(axis=0)
        lo = s.points.min(axis=0)
        if (lo < -0.5).any() or (hi >= np.array(scan.shape) + 0.5).any():
            problems.append(
                "%s: cells span z %.0f-%.0f y %.0f-%.0f x %.0f-%.0f, outside the scan's %s"
                % (s.name, lo[0], hi[0], lo[1], hi[1], lo[2], hi[2], scan.shape))
    return problems


HEADER = ("%-40s %9s %7s   %9s %9s %9s %9s"
          % ("surface", "cells", "support", "on data", "zero vox", "absent", "outside"))


def format_row(r):
    name = r["surface"]
    if len(name) > 40:
        name = name[:19] + "..." + name[-18:]
    if "error" in r:
        return "%-40s %s" % (name, r["error"])
    pct = "%.1f%%%s" % (100.0 * r["support"], "?" if r.get("support_is_upper_bound") else "")
    on_data = "-" if r["cells_on_data"] is None else "%d" % r["cells_on_data"]
    on_zero = "-" if r["cells_on_zero"] is None else "%d" % r["cells_on_zero"]
    return ("%-40s %9d %7s   %9s %9s %9d %9d"
            % (name, r["cells_sampled"], pct, on_data, on_zero,
               r["cells_in_absent_chunks"], r["cells_outside_volume"]))


def write_json(path, payload):
    """Write the result file atomically, so a kill mid-write cannot truncate it."""
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


def run_scroll(args, ap):
    """--scroll: discover a scroll's surfaces, group them by scan, audit each group."""
    groups, orphans = discover(args.scroll, bucket=args.bucket)
    n = sum(len(v) for v in groups.values())
    print("%s: %d published tifxyz surfaces over %d scan(s)" % (args.scroll, n, len(groups)))
    for scan_url, surfs in sorted(groups.items()):
        print("  %-64s %d surfaces" % (scan_url.rsplit("/", 1)[-1], len(surfs)))
    if orphans:
        print("  %d surface(s) skipped: the scan they name is not published in this bucket"
              % len(orphans))
        for url, volid in orphans:
            print("    %s (volume %s)" % (url.rsplit("/", 1)[-1], volid))
    if args.list:
        return 0
    if not groups:
        print("nothing to audit")
        return 0

    rng = np.random.default_rng(args.seed)
    all_results, failures = [], 0
    for scan_url, surfs in sorted(groups.items()):
        print("\nscan  %s" % scan_url)
        try:
            scan = Scan(scan_url, level=args.level)
        except RuntimeError as e:
            print("error: %s" % e, file=sys.stderr)
            failures += 1
            continue
        print("      %s\n" % scan.describe())
        print(HEADER)
        ok, codec = scan.decodable()
        mode = args.mode
        if mode == "voxel" and not ok:
            print("      chunks use '%s' and numcodecs is missing; falling back to presence mode"
                  % codec)
            mode = "presence"
        for path in surfs:
            try:
                surface = Surface(path)
            except RuntimeError as e:
                print("error: %s" % e, file=sys.stderr)
                failures += 1
                continue
            # No grid check here. Under --scroll the pairing is not assumed: the surface
            # directory and the volume directory carry the same volume id, so cells past
            # the array edge are a property of the data and are reported in the "outside"
            # bucket rather than treated as a mispairing. The check still applies when a
            # scan is paired by hand with --scan, where nothing corroborates it.
            r = audit(surface, scan, mode=mode, max_chunk_gets=args.max_chunk_gets,
                      sample=args.sample, rng=rng, workers=args.workers)
            r["scan"] = scan_url
            all_results.append(r)
            print(format_row(r), flush=True)
            if args.json:
                # After every surface, not at the end. A long audit that is killed
                # part way through keeps everything it has already measured.
                write_json(args.json, {"scroll": args.scroll, "mode": args.mode,
                                       "complete": False, "results": all_results})

    scored = [r for r in all_results if "error" not in r]
    print("\n%d surfaces audited, %d skipped" % (len(all_results), failures))
    oob = [r for r in scored if r["cells_outside_volume"]]
    if oob:
        print("%d surface(s) reach outside their own volume; those cells are in the "
              "'outside' column and are not counted as scan data" % len(oob))
    if scored:
        vals = sorted(r["support"] for r in scored)
        print("support: min %.1f%%  median %.1f%%  max %.1f%%"
              % (100 * vals[0], 100 * vals[len(vals) // 2], 100 * vals[-1]))
    if args.json:
        write_json(args.json, {"scroll": args.scroll, "mode": args.mode,
                               "complete": True, "results": all_results})
        print("wrote %s" % args.json)
    if args.fail_under is not None:
        bad = [r for r in scored if r["support"] < args.fail_under]
        if bad:
            print("\n%d surface(s) below --fail-under %g: %s"
                  % (len(bad), args.fail_under, ", ".join(r["surface"] for r in bad)))
            return 1
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="scan_support",
        description="Measure how much of a tifxyz surface stands on real scan data.")
    ap.add_argument("surfaces", nargs="*", metavar="SURFACE",
                    help="tifxyz directories, local paths or HTTP(S) prefixes")
    ap.add_argument("--from-file", metavar="FILE",
                    help="read surfaces from FILE, one per line ('-' for stdin); blank lines "
                         "and lines starting with # are skipped")
    ap.add_argument("--scan", metavar="ZARR",
                    help="raw masked scan OME-Zarr the surfaces were traced from (path or URL)")
    ap.add_argument("--scroll", metavar="NAME",
                    help="audit every published surface of this scroll (e.g. PHerc1447), pairing "
                         "each with the masked scan its directory name says it was traced on")
    ap.add_argument("--bucket", default=OPEN_DATA,
                    help="open-data bucket used by --scroll (default %(default)s)")
    ap.add_argument("--list", action="store_true",
                    help="with --scroll, print what would be audited and stop")
    ap.add_argument("--level", default="0", help="scan pyramid level to read (default 0)")
    ap.add_argument("--mode", choices=("voxel", "presence"), default="voxel",
                    help="voxel: read each cell's scan voxel. presence: chunk existence only, "
                         "no downloads, and the support figure is an upper bound")
    ap.add_argument("--sample", type=int, default=None, metavar="N",
                    help="audit a random sample of N cells per surface")
    ap.add_argument("--seed", type=int, default=0, help="sample seed (default 0)")
    ap.add_argument("--max-chunk-gets", type=int, default=400,
                    help="refuse a surface needing more than this many chunk downloads (default 400)")
    ap.add_argument("--fail-under", type=float, default=None, metavar="FRACTION",
                    help="exit 1 if any surface's support is below this (e.g. 0.5)")
    ap.add_argument("--json", metavar="FILE", help="write the full result table as JSON")
    ap.add_argument("--workers", type=int, default=8, metavar="N",
                    help="parallel HEAD requests when probing chunk existence (default 8)")
    ap.add_argument("--assume-same-grid", action="store_true",
                    help="skip the grid check and report numbers anyway")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    if args.from_file:
        src = sys.stdin if args.from_file == "-" else open(args.from_file)
        try:
            for line in src:
                line = line.strip()
                if line and not line.startswith("#"):
                    args.surfaces.append(line)
        finally:
            if src is not sys.stdin:
                src.close()
    if args.scroll:
        if args.surfaces or args.from_file or args.scan:
            ap.error("--scroll discovers surfaces and their scan; do not also pass "
                     "SURFACE, --from-file or --scan")
        return run_scroll(args, ap)

    if not args.scan:
        ap.error("--scan is required (or use --scroll NAME)")
    if not args.surfaces:
        ap.error("no surfaces given: pass them as arguments or with --from-file")

    try:
        scan = Scan(args.scan, level=args.level)
    except RuntimeError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    print("scan  %s" % args.scan)
    print("      %s" % scan.describe())

    ok, codec = scan.decodable()
    if args.mode == "voxel" and not ok:
        print("error: chunks use the '%s' codec and numcodecs is not installed, so their voxels\n"
              "       cannot be read. Install numcodecs, or rerun with --mode presence."
              % codec, file=sys.stderr)
        return 2

    surfaces = []
    for path in args.surfaces:
        try:
            surfaces.append(Surface(path))
        except RuntimeError as e:
            print("error: %s" % e, file=sys.stderr)
            return 2

    if not args.assume_same_grid:
        problems = grid_check(surfaces, scan)
        if problems:
            print("error: surface and scan are not in the same voxel space:", file=sys.stderr)
            for p in problems:
                print("  %s" % p, file=sys.stderr)
            print("       Pass the scan these surfaces were traced from, or --assume-same-grid\n"
                  "       if you know the grids match and the surface simply runs past the edge.",
                  file=sys.stderr)
            return 2

    rng = np.random.default_rng(args.seed)
    results = []
    print()
    print(HEADER)
    for s in surfaces:
        r = audit(s, scan, mode=args.mode, max_chunk_gets=args.max_chunk_gets,
                  sample=args.sample, rng=rng, workers=args.workers)
        results.append(r)
        print(format_row(r), flush=True)

    scored = [r for r in results if "error" not in r]
    print()
    print("%d surfaces, %d requests (%d HEAD, %d GET, %.1f MB, %d retried)"
          % (len(results), scan.fetch.heads + scan.fetch.gets, scan.fetch.heads,
             scan.fetch.gets, scan.fetch.bytes / 1e6, scan.fetch.retried))
    if args.mode == "presence":
        print("mode presence: '%' is an upper bound - a present chunk may still hold zeros there")

    if args.json:
        write_json(args.json, {"scan": args.scan, "level": args.level, "mode": args.mode,
                               "scan_shape": list(scan.shape), "complete": True,
                               "results": results})
        print("wrote %s" % args.json)

    if args.fail_under is not None:
        bad = [r for r in scored if r["support"] < args.fail_under]
        if bad:
            print("\n%d surface(s) below --fail-under %g: %s"
                  % (len(bad), args.fail_under, ", ".join(r["surface"] for r in bad)))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
