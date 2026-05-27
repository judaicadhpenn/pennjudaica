#!/usr/bin/env python3
# ============================================================================
# Penn Judaica Portal — build.py
# ----------------------------------------------------------------------------
# Reads every raw/*.jsonl produced by the harvesters and writes items.json at
# the repo root in the shape the front end expects:
#
#     { sources, items, featured, harvestedAt }
#
# Responsibilities (kept deliberately small):
#   1. Read every JSONL line from raw/
#   2. Apply SOURCE_LABELS so each item carries a stable display label/color
#   3. Cross-source dedupe (so an OPenn object and the finding aid that
#      catalogs it don't both appear)
#   4. Assign a global, deterministic integer `id` so URL hashes stay stable
#   5. Choose `featured`
#   6. Write items.json
#
# It does NOT do the actual harvesting and it does NOT re-geocode — both
# already happened in the harvester.
# ============================================================================

import os, sys, json, glob, hashlib, datetime, argparse

# Source key -> display label, system grouping, and chip color in the UI.
# Every `source` an item can carry MUST appear here, or the front end's
# SOURCES[it.source].color reference crashes.
SOURCE_LABELS = {
    # OPenn sources
    "zucker":      {"label": "Zucker Ketubah Collection",          "system": "OPenn",        "color": "#a8492b"},
    "ljs":         {"label": "Schoenberg Manuscripts",             "system": "OPenn",        "color": "#6e7637"},
    "mikveh":      {"label": "Mikveh Israel Records",              "system": "OPenn",        "color": "#6a4a7c"},
    "genizah":     {"label": "Cairo Genizah (CAJS)",               "system": "OPenn",        "color": "#2f6d6a"},
    "cajs":        {"label": "Penn CAJS / Halper Judaica",         "system": "OPenn",        "color": "#2f6d6a"},
    "rylands":     {"label": "Manchester / Rylands",               "system": "OPenn",        "color": "#7c6a4a"},
    "bl":          {"label": "British Library",                    "system": "OPenn",        "color": "#41506b"},
    "pennmuseum":  {"label": "Penn Museum",                        "system": "OPenn",        "color": "#9c6b1f"},
    "freelibrary": {"label": "Free Library of Philadelphia",       "system": "OPenn",        "color": "#5a7d6a"},
    "rosenbach":   {"label": "Rosenbach Museum & Library",         "system": "OPenn",        "color": "#8a3b52"},
    "other":       {"label": "Other OPenn collection",             "system": "OPenn",        "color": "#7a7163"},
    # Finding Aids sources
    "kislak":            {"label": "Kislak Center finding aids",   "system": "Finding Aids", "color": "#3f5a7a"},
    "katz":              {"label": "Katz Center finding aids",     "system": "Finding Aids", "color": "#5c4170"},
    "findingaids-other": {"label": "Other finding aids",           "system": "Finding Aids", "color": "#7a6c4f"},
}


def stable_id(item):
    """Deterministic 32-bit integer id derived from a source-specific key.
    Same source object → same id across rebuilds, so URL hashes are stable
    (the front end's `#item=<id>` keeps working across harvests)."""
    if item.get("system") == "OPenn":
        key = "openn:%s:%s" % (item.get("openn_repo", ""), item.get("openn_obj", ""))
    elif item.get("system") == "FindingAids":
        key = "fa:%s" % item.get("fa_id", "")
    else:
        key = "raw:%s:%s" % (item.get("source", ""), item.get("srcUrl", ""))
    # 8 hex chars = 32 bits, fits comfortably in JS Number, stays small in URLs.
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)


def dedupe_key(item):
    """Return a tuple of dedupe keys for this item; the first one that
    matches another record wins. Order matters — strongest signal first."""
    keys = []
    # 1. IIIF manifest URL (not always present in the current data)
    if item.get("manifest"):
        keys.append(("manifest", item["manifest"]))
    # 2. OPenn object identifier — only an OPenn item can carry this
    if item.get("system") == "OPenn":
        keys.append(("openn", item.get("openn_repo", "") + "/" + item.get("openn_obj", "")))
    # 3. Call number + source (Finding Aid call no often matches OPenn callno)
    cn = (item.get("callno") or "").strip().lower()
    if cn and cn != item.get("fa_id", "").lower():  # don't dedupe on a fallback id
        keys.append(("callno", cn))
    return keys


def merge(a, b):
    """Merge two records that we believe are the same physical object.
    Keep the richer field from each side. `a` wins ties; `b` fills gaps."""
    out = dict(a)
    for k, v in b.items():
        if k in ("id",):
            continue
        # prefer non-empty / longer description / images-having
        cur = out.get(k)
        if cur in (None, "", [], 0, "Unknown", "n.d."):
            out[k] = v
        elif k == "desc" and isinstance(v, str) and len(v) > len(cur or ""):
            out[k] = v
        elif k == "pages" and isinstance(v, list) and len(v) > len(cur or []):
            out[k] = v
        elif k == "img" and not cur:
            out[k] = v
    # iiif true if either side had images
    out["iiif"] = bool(out.get("iiif") or b.get("iiif"))
    # collect sources for transparency
    if a.get("system") != b.get("system"):
        out.setdefault("alsoIn", []).append(b.get("srcUrl") or b.get("system"))
    return out


def attach_collection_label(item):
    """Add the display `collection` string from SOURCE_LABELS."""
    s = SOURCE_LABELS.get(item.get("source"), SOURCE_LABELS["other"])
    item["collection"] = s["label"]
    return item


def load_raw(raw_dir):
    """Yield (path, item-dict) for every JSONL line under raw_dir."""
    paths = sorted(glob.glob(os.path.join(raw_dir, "*.jsonl")))
    if not paths:
        sys.exit("ERROR: no JSONL files under %s — run the harvesters first." % raw_dir)
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    yield p, json.loads(ln)
                except json.JSONDecodeError as e:
                    print("  ! bad JSON in %s: %s" % (p, e), file=sys.stderr)


def build(raw_dir, out_path):
    by_key = {}        # dedupe-key -> item
    items_by_id = {}   # final id -> item

    for path, item in load_raw(raw_dir):
        # Validate source key — anything we can't label, the front end can't render
        if item.get("source") not in SOURCE_LABELS:
            print("  ! %s: unknown source key %r — falling back to 'other'"
                  % (path, item.get("source")), file=sys.stderr)
            item["source"] = "other"

        item["id"] = stable_id(item)
        attach_collection_label(item)

        # Dedupe against everything we've already seen.
        matched = None
        for k in dedupe_key(item):
            if k in by_key:
                matched = by_key[k]
                break
        if matched is not None:
            merged = merge(matched, item)
            merged["id"] = matched["id"]  # keep the existing id
            items_by_id[matched["id"]] = merged
            for k in dedupe_key(merged):
                by_key[k] = merged
        else:
            items_by_id[item["id"]] = item
            for k in dedupe_key(item):
                by_key[k] = item

    items = list(items_by_id.values())
    items.sort(key=lambda x: (x.get("year") or 0, x.get("title") or ""))

    if not items:
        sys.exit("ERROR: 0 items after dedupe — refusing to write items.json.")

    # featured = a few image-having items with the most pages, for variety
    image_items = [it for it in items if it.get("pages")]
    image_items.sort(key=lambda x: -len(x["pages"]))
    featured = [it["id"] for it in image_items[:4]] or [items[0]["id"]]

    # build the sources block from what's actually used
    used = sorted({it["source"] for it in items})
    sources = {k: SOURCE_LABELS.get(k, SOURCE_LABELS["other"]) for k in used}

    # ── Split heavy fields off into per-item record shards ──────────────
    # items.json holds only what's needed for search + card rendering. The
    # `pages[]` array (typically the deep-zoom filmstrip — hundreds of image
    # URLs per item, ~98% of the total payload) goes to /records/<id>.json
    # and is fetched only when the user opens an item modal.
    HEAVY = ("pages",)
    SEARCH_FIELDS = (                           # everything else stays in items.json
        "id", "system", "source", "collection",
        "title", "creator", "year", "dateText",
        "place", "region", "lat", "lng",
        "lang", "type", "iiif", "img",
        "srcUrl", "callno", "desc",
        # finding-aid extras (small, useful for search ranking)
        "people", "corpnames", "subjects", "places", "genres", "extent",
        "fa_id", "fa_repository",
        # cross-source provenance
        "alsoIn",
    )

    light_items = []
    records_dir = os.path.join(os.path.dirname(out_path) or ".", "records")
    os.makedirs(records_dir, exist_ok=True)
    written_record_files = set()
    for it in items:
        # 1. light copy for items.json
        light = {k: it[k] for k in SEARCH_FIELDS if k in it}
        light_items.append(light)
        # 2. heavy detail shard (skip writing if there are no heavy fields)
        heavy = {k: it[k] for k in HEAVY if it.get(k)}
        if heavy:
            heavy["id"] = it["id"]
            shard_path = os.path.join(records_dir, "%d.json" % it["id"])
            with open(shard_path, "w", encoding="utf-8") as f:
                json.dump(heavy, f, ensure_ascii=False, separators=(",", ":"))
            written_record_files.add("%d.json" % it["id"])

    # Clean up stale shards from previous builds (items that were removed)
    for stale in os.listdir(records_dir):
        if stale.endswith(".json") and stale not in written_record_files:
            try: os.remove(os.path.join(records_dir, stale))
            except OSError: pass

    payload = {
        "sources": sources,
        "items": light_items,
        "featured": featured,
        "harvestedAt": datetime.date.today().isoformat(),
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print("Wrote %s (%d items, %.1f MB) + %d record shards in records/."
          % (out_path, len(items),
             os.path.getsize(out_path) / 1024 / 1024,
             len(written_record_files)),
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Build items.json from raw/*.jsonl")
    ap.add_argument("--raw", default="raw", help="directory of *.jsonl files")
    ap.add_argument("--out", default="items.json", help="output file")
    args = ap.parse_args()
    build(args.raw, args.out)


if __name__ == "__main__":
    main()
