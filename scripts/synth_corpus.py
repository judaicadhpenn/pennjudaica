#!/usr/bin/env python3
# ============================================================================
# Synthetic-corpus generator for scale testing.
#
# Reads raw/openn.jsonl (the existing real harvest) and clones each record
# N times with mutated id/title/year/place so the resulting corpus exercises
# search, facets, and map clustering at realistic sizes without needing to
# reharvest. Writes raw/synthetic.jsonl in the same shape build.py expects.
#
# Usage:
#   python3 scripts/synth_corpus.py --target 5000
#   python3 scripts/synth_corpus.py --target 20000 --source raw/openn.jsonl
# ============================================================================

import os, sys, json, random, argparse, pathlib

# Variations applied to each clone — keeps facets diverse so we're testing
# the realistic case (many regions, formats, languages, etc.) rather than
# a giant pile of identical records.
TITLE_SUFFIXES = [
    "(copy)", "(variant)", "(another exemplar)", "(secondary)", "(annotated)",
    "(fragment)", "(folio)", "(presentation copy)", "(scholar's hand)",
]
REGIONS_LOC = [
    ("Land of Israel", 31.78, 35.22), ("Egypt", 30.04, 31.24),
    ("Yemen", 15.55, 48.52), ("Iraq", 33.32, 44.36),
    ("Iran", 32.43, 53.69), ("Turkey", 39.00, 35.24),
    ("Morocco", 31.79, -7.09), ("Italy", 41.90, 12.50),
    ("Spain", 40.00, -3.70), ("Netherlands", 52.13, 5.29),
    ("England", 52.30, -1.20), ("France", 46.60, 2.30),
    ("Germany", 51.10, 10.40), ("Poland", 52.00, 19.00),
    ("United States", 39.83, -98.58), ("India", 22.00, 79.00),
]


def load_seeds(path):
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                yield json.loads(ln)


def mutate(seed, rng, idx):
    """Return a new item dict derived from `seed`, with id/title/year/place
    mutated so build.py treats it as a distinct record.

    NB: we explicitly drop the `pages` array. At 50k clones × avg ~150 pages
    per OPenn seed this is 7.5M page entries — enough to OOM the build, and
    irrelevant to what we're actually measuring (items.json size, search and
    facet performance). Per-shard size is linear in item count and was
    already measured at the 1.7k baseline."""
    c = dict(seed); c.pop("pages", None); c["iiif"] = False; c["img"] = seed.get("img","")
    # New synthetic identifier — build.py hashes this to a stable item id.
    c["openn_repo"] = "%04d" % (9000 + (idx % 1000))   # synthetic repo range
    c["openn_obj"]  = "%s-syn%d" % (seed.get("openn_obj", "obj"), idx)
    # Mutate the call number too — otherwise build.py's callno dedupe key
    # collapses every clone back onto its seed (which is exactly what just
    # happened in the first scale test).
    c["callno"] = "%s-syn%d" % (seed.get("callno", "n.d."), idx)
    # Title gets a tag and the index so search hits are unique.
    suf = TITLE_SUFFIXES[idx % len(TITLE_SUFFIXES)]
    c["title"] = "%s %s #%d" % (seed.get("title", "Untitled"), suf, idx)
    # Year jitters by up to ±50 years, clamped sensibly.
    base = seed.get("year") or 1700
    c["year"] = max(800, min(1950, base + rng.randint(-50, 50)))
    # Place rotates through the gazetteer so the map view sees real coverage.
    region, lat, lng = REGIONS_LOC[idx % len(REGIONS_LOC)]
    c["place"]  = region
    c["region"] = region
    c["lat"], c["lng"] = lat, lng
    # Strip the existing id so build.py recomputes it from the new keys.
    c.pop("id", None)
    c.pop("collection", None)
    return c


def synthesize(src, target, rng):
    seeds = list(load_seeds(src))
    if not seeds:
        sys.exit("ERROR: no seeds in %s — run a real harvest first." % src)
    out = []
    # Always include the originals so real items keep their original IDs.
    out.extend(seeds)
    idx = 0
    while len(out) < target:
        seed = seeds[idx % len(seeds)]
        out.append(mutate(seed, rng, idx))
        idx += 1
    return out[:target]


def main():
    ap = argparse.ArgumentParser(description="Generate a synthetic corpus")
    ap.add_argument("--source", default="raw/openn.jsonl")
    ap.add_argument("--out",    default="raw/synthetic.jsonl")
    ap.add_argument("--target", type=int, required=True,
                    help="total item count (originals + clones)")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    items = synthesize(args.source, args.target, rng)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False))
            f.write("\n")
    print("wrote %s with %d items (seeded from %s)"
          % (args.out, len(items), args.source), file=sys.stderr)


if __name__ == "__main__":
    main()
