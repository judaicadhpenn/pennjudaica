#!/usr/bin/env python3
# ============================================================================
# Penn Judaica Portal — OPenn harvester  (Judaica-scoped)
# ----------------------------------------------------------------------------
# Pulls every Judaica object on OPenn into raw/openn.jsonl, one JSON item per
# line. The shared build step (build.py) reads this file together with the
# other harvesters' outputs, normalizes/dedupes them, and writes items.json
# at the repo root for the front end to load.
#
# OPenn is NOT an OAI-PMH server and has no query API; it is a predictable
# static file tree:
#
#   • a collection CONTENTS page lists every object as "Browse | TEI XML | Data",
#     and every object's data path is encoded in its TEI-XML link:
#         https://openn.library.upenn.edu/Data/<repo>/<obj>/data/<obj>_TEI.xml
#   • each object's BROWSE page exposes every image at a stable derivative path:
#         /Data/<repo>/<obj>/data/web/<prefix>_<NNNN>_web.jpg   (+ /thumb/)
#     plus human-readable metadata (Title, Authors, Language, Origin, Summary…).
#
# So this harvester: (1) reads each configured contents page and pulls the
# (repo, object) pairs, (2) fetches each object's browse page, reconstructs
# the image URLs and reads the metadata, (3) appends one JSON line per item
# to raw/openn.jsonl. FAILS LOUDLY if it harvested zero items.
#
# Dependency: requests  (`pip install requests`).
# Usage:
#   python3 harvest_openn.py                       # full harvest
#   python3 harvest_openn.py --limit 10            # 10/collection (smoke test)
#   python3 harvest_openn.py --out raw/openn.jsonl # explicit output path
# ============================================================================

import os, re, sys, json, html, time, datetime, argparse, urllib.parse
import requests

OP = "https://openn.library.upenn.edu"

# ---------------------------------------------------------------------------
# WHAT TO HARVEST
# Each entry is one OPenn contents page. `source` (if set) forces every object
# from that page into that collection key; if None, the object is assigned by
# its repository id via REPO_SOURCE below. The two curated Judaica pages keep
# the harvest Judaica-only even though the items physically live in many repos.
# ---------------------------------------------------------------------------
COLLECTIONS = [
    {"contents": OP + "/html/genizah_contents.html", "source": "genizah"},
    {"contents": OP + "/html/judaica_contents.html", "source": None},
    {"contents": OP + "/html/0051.html",             "source": "zucker"},  # Zucker ketubot
    {"contents": OP + "/html/0039.html",             "source": "mikveh"},  # Mikveh Israel
]

# repository id -> collection key (used when a contents page doesn't force one)
REPO_SOURCE = {
    "0051": "zucker", "0039": "mikveh", "0002": "cajs", "0001": "ljs",
    "0021": "rylands", "0047": "bl", "0016": "pennmuseum",
    "0023": "freelibrary", "0028": "rosenbach",
}

# Source labels live in build.py (SOURCE_LABELS) — they're shared across all
# harvesters. This file only knows which source-KEY each OPenn object belongs
# to via REPO_SOURCE above and the per-COLLECTIONS override below.

# place string (substring, lowercased) -> (region label, lat, lng).
# First substring that appears in the place wins; specific entries before broad.
GAZETTEER = [
    ("kaifeng",        ("China", 34.80, 114.35)),
    ("china",          ("China", 34.80, 114.35)),
    ("jerusalem",      ("Land of Israel", 31.78, 35.22)),
    ("safed",          ("Land of Israel", 32.97, 35.50)),
    ("tiberias",       ("Land of Israel", 32.79, 35.53)),
    ("jaffa",          ("Land of Israel", 32.05, 34.75)),
    ("hebron",         ("Land of Israel", 31.53, 35.10)),
    ("palestine",      ("Land of Israel", 31.50, 35.00)),
    ("israel",         ("Land of Israel", 31.50, 35.00)),
    ("cairo",          ("Egypt", 30.04, 31.24)),
    ("fustat",         ("Egypt", 30.01, 31.23)),
    ("alexandria",     ("Egypt", 31.20, 29.92)),
    ("egypt",          ("Egypt", 30.04, 31.24)),
    ("yemen",          ("Yemen", 15.55, 48.52)),
    ("san'a",          ("Yemen", 15.37, 44.19)),
    ("baghdad",        ("Iraq", 33.32, 44.36)),
    ("iraq",           ("Iraq", 33.22, 43.68)),
    ("isfahan",        ("Iran", 32.65, 51.67)),
    ("persia",         ("Iran", 32.43, 53.69)),
    ("iran",           ("Iran", 32.43, 53.69)),
    ("istanbul",       ("Turkey", 41.01, 28.98)),
    ("constantinople", ("Turkey", 41.01, 28.98)),
    ("salonika",       ("Greece", 40.64, 22.94)),
    ("ottoman",        ("Turkey", 39.00, 35.24)),
    ("turkey",         ("Turkey", 39.00, 35.24)),
    ("morocco",        ("Morocco", 31.79, -7.09)),
    ("tunis",          ("Tunisia", 36.81, 10.18)),
    ("cochin",         ("India", 9.93, 76.27)),
    ("calcutta",       ("India", 22.57, 88.36)),
    ("bombay",         ("India", 19.08, 72.88)),
    ("india",          ("India", 22.00, 79.00)),
    ("amsterdam",      ("Netherlands", 52.37, 4.90)),
    ("netherlands",    ("Netherlands", 52.13, 5.29)),
    ("holland",        ("Netherlands", 52.13, 5.29)),
    ("venice",         ("Italy", 45.44, 12.32)),
    ("rome",           ("Italy", 41.90, 12.50)),
    ("livorno",        ("Italy", 43.55, 10.31)),
    ("italy",          ("Italy", 41.90, 12.50)),
    ("solsona",        ("Spain", 41.99, 1.52)),
    ("barcelona",      ("Spain", 41.39, 2.17)),
    ("toledo",         ("Spain", 39.86, -4.02)),
    ("spain",          ("Spain", 40.00, -3.70)),
    ("portugal",       ("Portugal", 39.40, -8.22)),
    ("london",         ("England", 51.51, -0.13)),
    ("england",        ("England", 52.30, -1.20)),
    ("united kingdom", ("England", 52.30, -1.20)),
    ("paris",          ("France", 48.86, 2.35)),
    ("france",         ("France", 46.60, 2.30)),
    ("prague",         ("Czech lands", 50.08, 14.44)),
    ("vienna",         ("Austria", 48.21, 16.37)),
    ("germany",        ("Germany", 51.10, 10.40)),
    ("poland",         ("Poland", 52.00, 19.00)),
    ("philadelphia",   ("United States", 39.95, -75.16)),
    ("new york",       ("United States", 40.71, -74.01)),
    ("united states",  ("United States", 39.83, -98.58)),
    ("america",        ("United States", 39.83, -98.58)),
]

HEADERS = {"User-Agent": "PennJudaicaPortal-harvester/1.0 (+https://openn.library.upenn.edu)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ---------------------------------------------------------------------------
# fetch + normalize
# ---------------------------------------------------------------------------
def fetch(url, tries=3):
    last = None
    for n in range(tries):
        try:
            r = SESSION.get(url, timeout=40)
            if r.status_code == 200:
                # OPenn serves UTF-8 but usually omits charset in the HTTP header,
                # so requests defaults to ISO-8859-1 and mangles Hebrew (e.g. קובץ
                # -> "×§×‘×¥"). Honor an explicit header charset; otherwise UTF-8.
                if "charset=" not in r.headers.get("content-type", "").lower():
                    r.encoding = "utf-8"
                return r.text
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (n + 1))
    print("  ! fetch failed: %s (%s)" % (url, last), file=sys.stderr)
    return None


def to_text(raw):
    """Reduce HTML (or markdown) to clean plain-text lines, so the same label
    extraction works whether we fetched raw OPenn HTML or a saved fixture."""
    t = re.sub(r"(?is)<script.*?</script>", " ", raw)
    t = re.sub(r"(?is)<style.*?</style>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|dt|dd)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)            # strip remaining tags
    t = html.unescape(t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)  # markdown links -> label
    lines = []
    for ln in t.splitlines():
        ln = ln.replace(" ", " ").strip()
        ln = re.sub(r"^#{1,6}\s*", "", ln)     # markdown heading markers
        ln = re.sub(r"\s+", " ", ln)
        if ln:
            lines.append(ln)
    return lines


# ---------------------------------------------------------------------------
# parse a contents page -> list of (repo, obj)
# ---------------------------------------------------------------------------
TEI_RE = re.compile(r"Data/(\d{4})/([^/\s\"'<>]+)/data/\2_TEI\.xml")

def list_objects(contents_url):
    raw = fetch(contents_url)
    if not raw:
        return []
    seen, out = set(), []
    for repo, obj in TEI_RE.findall(raw):
        key = (repo, obj)
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


# ---------------------------------------------------------------------------
# parse one object's browse page -> item dict (or None)
# ---------------------------------------------------------------------------
IMG_RE = re.compile(r"Data/(\d{4})/([^/\s\"'<>]+)/data/web/([^\"'<>\s]+?)_(\d+)_web\.jpg")

def section(lines, *labels):
    """Return the lines following a heading whose text == one of `labels`,
    up to the next short heading-like line. Used for Authors / Genres / etc."""
    labset = {l.lower() for l in labels}
    out = []
    grabbing = False
    for ln in lines:
        low = ln.lower().rstrip(":")
        if low in labset:
            grabbing = True
            continue
        if grabbing:
            # stop at the next heading: a short line that is a known field label
            if low in FIELD_LABELS and low not in labset:
                break
            out.append(ln)
            if len(out) > 12:
                break
    return out

FIELD_LABELS = {
    "title", "authors", "author", "funders", "call number", "alternate identifiers",
    "publisher", "language", "languages", "origin", "summary", "abstract", "extent",
    "support", "related resources", "subjects topical", "subjects", "genres", "genre",
    "keywords", "licenses", "images", "place",
}

def first_nonempty(lines):
    for ln in lines:
        if ln and not ln.startswith("http") and ln not in ("-", "—"):
            return ln
    return ""

def parse_year(date_text):
    """Best-effort int year from an OPenn date string."""
    if not date_text:
        return 0
    s = date_text.lower()
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)\s*[-–]?\s*(?:(\d{1,2})(?:st|nd|rd|th)\s*)?cent", s)
    if m:
        c1 = int(m.group(1))
        c2 = int(m.group(2)) if m.group(2) else c1
        # midpoint of the (earliest) century, e.g. 9th -> 850
        return (c1 - 1) * 100 + 50 if c1 == c2 else ((c1 - 1) * 100 + (c2 * 100)) // 2
    yrs = re.findall(r"\b(\d{3,4})\b", s)
    if yrs:
        return int(yrs[0])
    return 0

def geocode(place):
    p = (place or "").lower()
    for needle, (region, lat, lng) in GAZETTEER:
        if needle in p:
            return region, lat, lng
    # unknown: keep the place as its own region so the facet still works
    return (place.strip() or "Unknown"), None, None

def parse_object(repo, obj, forced_source):
    url = "%s/Data/%s/html/%s.html" % (OP, repo, obj)
    raw = fetch(url)
    if not raw:
        return None
    lines = to_text(raw)

    # --- images: reconstruct canonical URLs (independent of HTML tag shape) ---
    pages, seen = [], set()
    for r2, o2, prefix, idx in IMG_RE.findall(raw):
        if r2 != repo or o2 != obj:
            continue
        key = (prefix, idx)
        if key in seen:
            continue
        seen.add(key)
        pages.append({
            "img":   "%s/Data/%s/%s/data/web/%s_%s_web.jpg"   % (OP, repo, obj, prefix, idx),
            "thumb": "%s/Data/%s/%s/data/thumb/%s_%s_thumb.jpg" % (OP, repo, obj, prefix, idx),
            "label": "",  # filled below
        })
    if not pages:
        return None  # not-yet-digitized; skip (catalog-only records have no web/)
    for i, pg in enumerate(pages):
        pg["label"] = "Image %d" % (i + 1)

    # --- metadata (best-effort; never fatal) ---
    title = first_nonempty(section(lines, "Title")) or obj
    creator = first_nonempty(section(lines, "Authors", "Author")) or "Unknown"
    creator = re.sub(r"\s*\(https?://\S+\)?\s*$", "", creator).strip(" -")
    lang = first_nonempty(section(lines, "Language", "Languages")) or "Unknown"

    origin = section(lines, "Origin")
    date_text = first_nonempty(origin) or ""
    place = ""
    for j, ln in enumerate(origin):
        if ln.lower().rstrip(":") == "place":
            place = first_nonempty(origin[j + 1:])
            break
    if not place:
        place = first_nonempty(section(lines, "Place"))

    summary = " ".join(section(lines, "Summary", "Abstract")).strip()
    summary = re.sub(r"\s+", " ", summary)[:600]

    genres = [g.strip("- ").strip() for g in section(lines, "Genres", "Genre") if g.strip("- ").strip()]
    genres = [g for g in genres if not g.lower().startswith("keyword")]
    item_type = genres[0] if genres else "Manuscript"

    callno = first_nonempty(section(lines, "Call number")) or obj
    callno = re.sub(r"\s*\(.*$", "", callno).strip()

    year = parse_year(date_text)
    region, lat, lng = geocode(place)
    source = forced_source or REPO_SOURCE.get(repo, "other")

    # `collection` is set by build.py from SOURCE_LABELS so labels stay in
    # one place. The harvester only emits the source KEY.
    return {
        "system": "OPenn",
        "source": source,
        "openn_repo": repo, "openn_obj": obj,
        "title": title, "creator": creator, "year": year, "dateText": date_text or "n.d.",
        "place": place or "Unknown", "region": region, "lat": lat, "lng": lng,
        "lang": lang, "type": item_type,
        "iiif": True,
        "img": pages[0]["thumb"],
        "srcUrl": url, "callno": callno, "desc": summary, "pages": pages,
    }


# ---------------------------------------------------------------------------
# orchestrate
# ---------------------------------------------------------------------------
def harvest(limit_per_collection=None):
    """Yield item dicts as they're parsed (streaming — so a long harvest can be
    written to disk incrementally and resumed if it crashes)."""
    seen_obj = set()
    for col in COLLECTIONS:
        objs = list_objects(col["contents"])
        print("• %s -> %d objects" % (col["contents"], len(objs)), file=sys.stderr)
        n = 0
        for repo, obj in objs:
            if (repo, obj) in seen_obj:
                continue
            seen_obj.add((repo, obj))
            it = parse_object(repo, obj, col["source"])
            if not it:
                continue
            yield it
            n += 1
            if limit_per_collection and n >= limit_per_collection:
                break
            time.sleep(0.15)  # be polite to OPenn


def write_jsonl(items_iter, path):
    """Stream items into a JSONL file (one JSON object per line).

    Returns (count, sources_used). Each line is the unmodified item dict from
    parse_object(); no id is assigned — build.py owns global ID assignment
    so IDs are stable across multiple harvesters."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    count = 0
    sources_used = set()
    with open(path, "w", encoding="utf-8") as f:
        for it in items_iter:
            f.write(json.dumps(it, ensure_ascii=False))
            f.write("\n")
            count += 1
            sources_used.add(it["source"])
    return count, sources_used


def main():
    ap = argparse.ArgumentParser(description="Harvest OPenn Judaica into raw/openn.jsonl")
    ap.add_argument("--out", default="raw/openn.jsonl")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap objects harvested per collection (for quick tests)")
    args = ap.parse_args()

    count, sources_used = write_jsonl(harvest(limit_per_collection=args.limit), args.out)
    if not count:
        print("ERROR: harvested 0 items — refusing to leave an empty %s." % args.out,
              file=sys.stderr)
        # remove the empty file so build.py doesn't see "0 OPenn items" as success
        try: os.remove(args.out)
        except OSError: pass
        sys.exit(1)
    print("Wrote %s with %d items across %d collections (%s)."
          % (args.out, count, len(sources_used), ", ".join(sorted(sources_used))),
          file=sys.stderr)


if __name__ == "__main__":
    main()
