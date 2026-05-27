#!/usr/bin/env python3
# ============================================================================
# Penn Judaica Portal — Finding Aids harvester  (Judaica-scoped)
# ----------------------------------------------------------------------------
# Pulls Judaica-relevant records from findingaids.library.upenn.edu (the
# PACSCL/Penn finding aids discovery site, a Blacklight app on Solr) into
# raw/findingaids.jsonl.
#
# The site has no public JSON API, but the HTML is regular and every record
# has a stable URL: /records/<ID>. Discovery is a union of three passes —
# subject keywords, language facets, and repository allowlist — deduped by
# record ID. The HTML head exposes `meta-totalResults: N` so we always know
# when we've paged through everything.
#
# Dependency: requests  (`pip install requests`).
# Usage:
#   python3 harvest_findingaids.py
#   python3 harvest_findingaids.py --limit 5
#   python3 harvest_findingaids.py --out raw/findingaids.jsonl
# ============================================================================

import os, re, sys, json, html, time, argparse, urllib.parse
import requests

FA = "https://findingaids.library.upenn.edu"

# ---------------------------------------------------------------------------
# DISCOVERY SCOPE — what we consider Judaica on this site.
# Every pass below is run independently; their results are unioned and
# deduped by record ID. Tune by editing these lists.
# ---------------------------------------------------------------------------
SUBJECT_KEYWORDS = [
    "judaica", "jews", "judaism", "hebrew", "yiddish", "ladino",
    "zionism", "sephardic", "ashkenazi", "kabbalah", "talmud",
]

LANGUAGE_FACETS = ["Hebrew", "Yiddish", "Ladino", "Judeo-Arabic", "Aramaic"]

REPOSITORY_ALLOWLIST = [
    "University of Pennsylvania: Kislak Center for Special Collections, Rare Books and Manuscripts",
    "University of Pennsylvania: Archives at the Library of the Katz Center for Advanced Judaic Studies",
]

# Optional: a hand-curated list of record IDs that aren't surfaced by the
# passes above but should still be included. One ID per line; see the file.
CURATED_IDS_FILE = "findingaids_curated_ids.txt"

# Repository name -> source key the front end uses. Anything not in this
# map falls through to "findingaids-other".
REPO_TO_SOURCE = {
    "University of Pennsylvania: Kislak Center for Special Collections, Rare Books and Manuscripts": "kislak",
    "University of Pennsylvania: Archives at the Library of the Katz Center for Advanced Judaic Studies": "katz",
}

# ---------------------------------------------------------------------------
# Same gazetteer as harvest_openn.py — geocoding lives in the harvester so
# the build step can stay dumb. Duplicated rather than imported so each
# harvester runs standalone.
# ---------------------------------------------------------------------------
GAZETTEER = [
    ("jerusalem",      ("Land of Israel", 31.78, 35.22)),
    ("safed",          ("Land of Israel", 32.97, 35.50)),
    ("tel aviv",       ("Land of Israel", 32.08, 34.78)),
    ("palestine",      ("Land of Israel", 31.50, 35.00)),
    ("israel",         ("Land of Israel", 31.50, 35.00)),
    ("cairo",          ("Egypt", 30.04, 31.24)),
    ("egypt",          ("Egypt", 30.04, 31.24)),
    ("yemen",          ("Yemen", 15.55, 48.52)),
    ("baghdad",        ("Iraq", 33.32, 44.36)),
    ("iraq",           ("Iraq", 33.22, 43.68)),
    ("iran",           ("Iran", 32.43, 53.69)),
    ("persia",         ("Iran", 32.43, 53.69)),
    ("istanbul",       ("Turkey", 41.01, 28.98)),
    ("salonika",       ("Greece", 40.64, 22.94)),
    ("turkey",         ("Turkey", 39.00, 35.24)),
    ("morocco",        ("Morocco", 31.79, -7.09)),
    ("tunis",          ("Tunisia", 36.81, 10.18)),
    ("india",          ("India", 22.00, 79.00)),
    ("amsterdam",      ("Netherlands", 52.37, 4.90)),
    ("netherlands",    ("Netherlands", 52.13, 5.29)),
    ("venice",         ("Italy", 45.44, 12.32)),
    ("rome",           ("Italy", 41.90, 12.50)),
    ("italy",          ("Italy", 41.90, 12.50)),
    ("spain",          ("Spain", 40.00, -3.70)),
    ("portugal",       ("Portugal", 39.40, -8.22)),
    ("london",         ("England", 51.51, -0.13)),
    ("england",        ("England", 52.30, -1.20)),
    ("france",         ("France", 46.60, 2.30)),
    ("germany",        ("Germany", 51.10, 10.40)),
    ("poland",         ("Poland", 52.00, 19.00)),
    ("russia",         ("Russia", 55.75, 37.62)),
    ("ukraine",        ("Ukraine", 50.45, 30.52)),
    ("hungary",        ("Hungary", 47.50, 19.04)),
    ("czech",          ("Czech lands", 50.08, 14.44)),
    ("austria",        ("Austria", 48.21, 16.37)),
    ("philadelphia",   ("United States", 39.95, -75.16)),
    ("new york",       ("United States", 40.71, -74.01)),
    ("united states",  ("United States", 39.83, -98.58)),
    ("china",          ("China", 34.80, 114.35)),
    ("shanghai",       ("China", 31.23, 121.47)),
    ("argentina",      ("Argentina", -38.42, -63.61)),
    ("brazil",         ("Brazil", -14.24, -51.93)),
]


HEADERS = {"User-Agent": "PennJudaicaPortal-harvester/1.0 (+https://findingaids.library.upenn.edu)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def fetch(url, tries=3):
    last = None
    for n in range(tries):
        try:
            r = SESSION.get(url, timeout=40)
            if r.status_code == 200:
                if "charset=" not in r.headers.get("content-type", "").lower():
                    r.encoding = "utf-8"
                return r.text
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = str(e)
        time.sleep(1.5 * (n + 1))
    print("  ! fetch failed: %s (%s)" % (url, last), file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# DISCOVERY — paginated search-results pages
# ---------------------------------------------------------------------------
TOTAL_RE = re.compile(r'meta-totalResults:\s*(\d+)', re.I)
RECORD_LINK_RE = re.compile(r'href="(/records/([^"?#/]+))"')


def page_url(params, page):
    qs = urllib.parse.urlencode(params + [("per_page", "100"), ("page", str(page))])
    return FA + "/records?" + qs


def discover_pass(params, label):
    """Walk every page of one search and yield record IDs."""
    raw = fetch(page_url(params, 1))
    if not raw:
        return
    m = TOTAL_RE.search(raw)
    total = int(m.group(1)) if m else None
    seen = set()
    page = 1
    while True:
        if page > 1:
            raw = fetch(page_url(params, page))
            if not raw:
                break
        new_ids = set()
        for href, rid in RECORD_LINK_RE.findall(raw):
            if rid not in seen and rid not in new_ids:
                new_ids.add(rid)
                yield rid
        seen.update(new_ids)
        if not new_ids:
            # no new IDs on this page = we've paged past the result set
            break
        if total is not None and len(seen) >= total:
            break
        page += 1
        time.sleep(0.2)
    print("  ▸ %s -> %d records (of %s total)"
          % (label, len(seen), total if total is not None else "?"),
          file=sys.stderr)


def discover_all():
    """Run every discovery pass and yield deduped record IDs."""
    seen = set()
    def emit(rid):
        if rid not in seen:
            seen.add(rid)
            return True
        return False

    for kw in SUBJECT_KEYWORDS:
        for rid in discover_pass([("q", kw), ("search_field", "all_fields")],
                                 'subject="%s"' % kw):
            if emit(rid):
                yield rid
    for lang in LANGUAGE_FACETS:
        for rid in discover_pass([("f[languages_ssim][]", lang)],
                                 'language="%s"' % lang):
            if emit(rid):
                yield rid
    for repo in REPOSITORY_ALLOWLIST:
        for rid in discover_pass([("f[repository_ssi][]", repo)],
                                 'repo="%s"' % repo[:50]):
            if emit(rid):
                yield rid
    if os.path.exists(CURATED_IDS_FILE):
        with open(CURATED_IDS_FILE, encoding="utf-8") as f:
            curated = [ln.strip() for ln in f
                       if ln.strip() and not ln.strip().startswith("#")]
        for rid in curated:
            if emit(rid):
                yield rid
        print("  ▸ curated list -> %d records" % len(curated), file=sys.stderr)

    print("Discovery: %d unique records across all passes." % len(seen),
          file=sys.stderr)


# ---------------------------------------------------------------------------
# EXTRACTION — parse one /records/<ID> HTML page into an item dict
# ---------------------------------------------------------------------------
def to_text_blocks(raw):
    """Return ordered text lines from an HTML page, preserving paragraph
    breaks. Used for label-based field extraction below."""
    t = re.sub(r"(?is)<script.*?</script>", " ", raw)
    t = re.sub(r"(?is)<style.*?</style>", " ", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|dt|dd|section)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    lines = []
    for ln in t.splitlines():
        ln = ln.replace(" ", " ").strip()
        ln = re.sub(r"\s+", " ", ln)
        if ln:
            lines.append(ln)
    return lines


def first_after(lines, label, max_skip=3):
    """Find a line that equals (case-insensitive) `label` or `label:`, and
    return the next non-empty line. Used for "Call Number:" → next line."""
    norm = label.lower().rstrip(":")
    for i, ln in enumerate(lines):
        if ln.lower().rstrip(":") == norm:
            for j in range(1, max_skip + 1):
                if i + j < len(lines):
                    nxt = lines[i + j]
                    if nxt:
                        return nxt
            return ""
    return ""


# Headings that terminate a narrative section. Order matters only for clarity;
# any of these stops the harvester's "keep grabbing paragraphs" loop.
SECTION_BOUNDARIES = {
    "biography/history", "biographical/historical note",
    "scope and content", "scope and contents", "scope content",
    "arrangement", "related materials", "related material",
    "name and subject headings", "subject headings", "administrative information",
    "collection inventory", "controlled access headings",
    "physical description", "language of materials",
    "conditions governing access", "conditions governing use",
    "preferred citation", "acquisition information",
    "processing information", "appraisal", "accruals", "separated materials",
    "custodial history", "immediate source of acquisition",
    "print, suggest", "print the finding aid",
}

# Common page-furniture lines that pollute narrative sections. Drop these.
SECTION_NOISE = {
    "toggle request", "add to requests", "request to view materials",
    "request item to view", "**request to view materials**",
}


def section_block(lines, *labels, max_lines=80):
    """Grab the paragraph(s) following a heading whose text equals one of
    `labels`, up to the next section heading or end of page. Returns the
    joined paragraphs as one string, or "" if the section is missing."""
    labset = {l.lower().rstrip(":") for l in labels}
    out = []
    grabbing = False
    for ln in lines:
        low = ln.lower().rstrip(":")
        if low in labset:
            grabbing = True
            continue
        if not grabbing:
            continue
        if low in SECTION_BOUNDARIES and low not in labset:
            break
        if low in SECTION_NOISE:
            continue
        # The collection inventory at the bottom of the page is fenced off by
        # "Collection Inventory" in SECTION_BOUNDARIES, but some pages put a
        # bare series title like "Walter H. Annenberg." right after Scope.
        # If we see a one-word/short line ending in a period that looks like
        # a series header, stop.
        if (grabbing and len(out) > 2 and len(ln) < 60
                and ln.endswith(".") and ln[0].isupper()
                and ln.count(" ") < 5):
            # heuristic: short capitalized line could be a series heading
            # but only stop if the next several lines look like inventory
            # items (containers). For safety, just stop.
            break
        out.append(ln)
        if len(out) > max_lines:
            break
    # Preserve paragraph boundaries: each line in `out` is one EAD <p> (or
    # equivalent block element). Join with a double newline so the front
    # end's /\s{2,}/ paragraph splitter can find the boundaries.
    paras = [re.sub(r"\s+", " ", ln).strip() for ln in out]
    return "\n\n".join(p for p in paras if p).strip()


def parse_year(date_text):
    if not date_text:
        return 0
    yrs = re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", date_text)
    return int(yrs[0]) if yrs else 0


def geocode(place):
    p = (place or "").lower()
    for needle, (region, lat, lng) in GAZETTEER:
        if needle in p:
            return region, lat, lng
    return ((place or "").strip() or "Unknown"), None, None


SUBJECT_LINK_RE = re.compile(
    r'href="/records\?f%5B([a-z_]+)%5D%5B%5D=([^"]+)"', re.I)


def parse_record(rid):
    """Fetch /records/<rid> and return one item dict, or None on failure."""
    url = "%s/records/%s" % (FA, rid)
    raw = fetch(url)
    if not raw:
        return None
    lines = to_text_blocks(raw)
    if not lines:
        return None

    # title — the first <h1> after the "Main content" anchor
    title = ""
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', raw, re.S | re.I)
    if h1:
        title = re.sub(r"<[^>]+>", "", h1.group(1)).strip()
    title = re.sub(r"\s+", " ", title)
    if not title:
        title = rid

    # Subject-headings sidebar: each `f[...]=Value` link tells us a tagged
    # value AND the facet field it lives in (people_ssim, places_ssim, ...).
    # Build per-field lists; URL-decode the values.
    headings = {"people": [], "corpnames": [], "subjects": [],
                "places": [], "languages": [], "genres": [], "occupations": []}
    field_map = {
        "people_ssim": "people", "corpnames_ssim": "corpnames",
        "subjects_ssim": "subjects", "places_ssim": "places",
        "languages_ssim": "languages", "genre_form_ssim": "genres",
        "occupations_ssim": "occupations",
    }
    for ff, val in SUBJECT_LINK_RE.findall(raw):
        key = field_map.get(ff)
        if not key:
            continue
        v = urllib.parse.unquote_plus(val)
        if v not in headings[key]:
            headings[key].append(v)

    # Field labels are followed by their values on the page. The order is
    # stable: Call Number, Repository, Extent, Language, Date, Abstract,
    # Creator, Finding Aid Author, Finding Aid Date, Publisher.
    callno = first_after(lines, "Call Number")
    repo = first_after(lines, "Repository")
    extent = first_after(lines, "Extent")
    lang = first_after(lines, "Language") or (headings["languages"][0]
                                              if headings["languages"] else "")
    date_text = first_after(lines, "Date")
    abstract = first_after(lines, "Abstract")
    creator = (first_after(lines, "Creator")
               or first_after(lines, "Finding Aid Author")
               or "")
    publisher = first_after(lines, "Publisher")

    # Multi-paragraph narrative sections — the parts that make a finding aid
    # actually useful to a researcher. Truncated at 4000 chars each to keep
    # individual records reasonable; the user can click through to the full
    # finding aid for more.
    biography = section_block(lines, "Biography/History",
                              "Biographical/Historical note",
                              "Biographical/Historical Note")[:4000]
    scope = section_block(lines, "Scope and Content",
                          "Scope and Contents",
                          "Scope Content")[:4000]
    related = section_block(lines, "Related Materials",
                            "Related Material")[:2000]

    # Place: prefer the structured places facet; fall back to abstract scan.
    place = headings["places"][0] if headings["places"] else ""
    if not place and abstract:
        for needle, _ in GAZETTEER:
            if needle in abstract.lower():
                place = needle.title()
                break

    year = parse_year(date_text)
    region, lat, lng = geocode(place)

    source = REPO_TO_SOURCE.get(repo, "findingaids-other")

    # We don't pull digitized component images for v1 — the Penn finding aids
    # digitization rate is low and the discovery + collection-level record
    # alone is the bulk of the value. Hybrid (component-level) mode is a
    # follow-up; the schema is ready for it (`pages`, `parentId`).
    # `type` defaults to "Finding aid" but if the EAD declares a primary genre
    # (Correspondence, Photographs, Manuscripts, Diaries…), use that instead so
    # the format facet on the front end is actually useful.
    primary_genre = headings["genres"][0] if headings["genres"] else ""
    item_type = primary_genre or "Finding aid"

    return {
        "system": "FindingAids",
        "source": source,
        "fa_id": rid,
        "fa_repository": repo,
        "title": title,
        "creator": creator or "Unknown",
        "year": year,
        "dateText": date_text or "n.d.",
        "place": place or "Unknown",
        "region": region, "lat": lat, "lng": lng,
        "lang": lang or "Unknown",
        "type": item_type,
        "iiif": False,
        "img": "",                          # no thumbnail at the collection level
        "srcUrl": url,
        "callno": callno or rid,
        "desc": abstract or "",
        "extent": extent or "",
        "publisher": publisher or "",
        "biographyHistory": biography,      # multi-paragraph narrative
        "scopeContent": scope,              # multi-paragraph narrative
        "relatedMaterials": related,        # cross-references to other collections
        "people": headings["people"],
        "corpnames": headings["corpnames"],
        "subjects": headings["subjects"],
        "places": headings["places"],
        "genres": headings["genres"],
        "pages": [],
    }


# ---------------------------------------------------------------------------
# orchestrate
# ---------------------------------------------------------------------------
def harvest(limit=None):
    """Yield item dicts as discovery returns IDs."""
    n = 0
    for rid in discover_all():
        it = parse_record(rid)
        if not it:
            continue
        yield it
        n += 1
        if limit and n >= limit:
            break
        time.sleep(0.2)


def write_jsonl(items_iter, path):
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
    ap = argparse.ArgumentParser(
        description="Harvest Penn Judaica finding aids into raw/findingaids.jsonl")
    ap.add_argument("--out", default="raw/findingaids.jsonl")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap total records harvested (for quick tests)")
    args = ap.parse_args()

    count, sources_used = write_jsonl(harvest(limit=args.limit), args.out)
    if not count:
        print("ERROR: harvested 0 records — refusing to leave an empty %s." % args.out,
              file=sys.stderr)
        try: os.remove(args.out)
        except OSError: pass
        sys.exit(1)
    print("Wrote %s with %d items (sources: %s)."
          % (args.out, count, ", ".join(sorted(sources_used))), file=sys.stderr)


if __name__ == "__main__":
    main()
