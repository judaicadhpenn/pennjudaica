# Harvesting Penn's Judaica into `items.json`

The front end never talks to Penn's source systems directly — it loads one
small file, `items.json`, and lazy-fetches per-item page data from
`records/<id>.json` when a modal opens. Both files are produced by the
build pipeline in this repo:

```
  Penn source systems                  Harvesters (Python)              Front end
  ───────────────────                   ──────────────────              ─────────
  OPenn (HTML + IIIF)  ──▶ harvest_openn.py        ──┐
                                                      ├─▶ build.py  ──▶ items.json  (sources, items, featured)
  Finding Aids (HTML) ──▶ harvest_findingaids.py   ──┘                 records/<id>.json  (per-item page data)
```

Both harvesters write **JSONL** (one item per line) into `raw/`. `build.py`
reads every `raw/*.jsonl`, attaches the canonical source label/color from
its `SOURCE_LABELS` dict, dedupes across systems, assigns a stable
`id` derived from the source identifier, splits each record into a "light"
search/card row (→ `items.json`) and a heavy page-image shard
(→ `records/<id>.json`), and chooses `featured` items.

Every harvester is **Judaica-scoped at the source**. We never pull all of
Penn and filter later.

## OPenn — `harvest_openn.py`

OPenn is a static file tree, not an OAI-PMH server. The harvester walks
four contents pages:

- `/html/genizah_contents.html` — Cairo Genizah (CAJS)
- `/html/judaica_contents.html` — the curated Judaica index
- `/html/0051.html` — Zucker Ketubot
- `/html/0039.html` — Mikveh Israel

For each `(repo, object)` pair, it fetches the object's browse page,
extracts metadata (title, authors, language, origin, summary, …), and
reconstructs the canonical image URLs at
`/Data/<repo>/<obj>/data/web/<prefix>_<NNNN>_web.jpg` (and `/thumb/`).

Tuning lives at the top of the script:
- `COLLECTIONS` — which contents pages to walk
- `REPO_SOURCE` — repo-id → source key (`zucker`, `mikveh`, `cajs`, …)
- `GAZETTEER` — place-string → (region, lat, lng) for the map view

## Finding Aids — `harvest_findingaids.py`

`findingaids.library.upenn.edu` is a Blacklight app on Solr; the HTML is
regular and every record has a stable URL at `/records/<ID>`. Discovery is
the union of four passes, deduped by record ID:

1. **Subject keywords** — `?q=judaica`, `?q=jews`, `?q=hebrew`, `?q=yiddish`,
   `?q=zionism`, `?q=sephardic`, `?q=ladino`, etc.
2. **Language facet** — `f[languages_ssim][]=Hebrew`, `Yiddish`, `Ladino`,
   `Judeo-Arabic`, `Aramaic`.
3. **Repository allowlist** — Kislak Center + Katz Center for Advanced
   Judaic Studies (every collection at the Katz Center is in scope by
   definition; the repository pass catches collections that aren't tagged
   with an explicit "Jews" subject heading).
4. **Curated IDs** — one record ID per line in
   `findingaids_curated_ids.txt`; the escape hatch for collections that
   don't surface via the other three passes.

For each discovered record, the harvester fetches `/records/<ID>` and
parses the page into our shared item schema: title, repository, call
number, extent, language, date, abstract, and the people / corpnames /
subjects / places / genres facets from the right-hand sidebar. The
"Collection Inventory" (digitized components within a finding aid) is not
parsed in v1 — Penn finding aids have a low digitization rate (about 7% of
records site-wide have any online content) so the collection-level record
already captures most of the value. Component-level (hybrid) ingest is a
documented future extension; the schema reserves `pages[]` and `parentId`
for it.

Source keys produced:
- `kislak` — Kislak Center finding aids
- `katz` — Katz Center finding aids
- `findingaids-other` — Judaica records held at other PACSCL repositories

Tuning lives at the top of the script:
- `SUBJECT_KEYWORDS`, `LANGUAGE_FACETS`, `REPOSITORY_ALLOWLIST`
- `CURATED_IDS_FILE` (defaults to `findingaids_curated_ids.txt`)
- `REPO_TO_SOURCE` — display-label → source key
- `GAZETTEER` — same shape as the OPenn one

## `build.py`

Reads every `raw/*.jsonl`, runs the cross-source dedupe key cascade:

1. IIIF manifest URL (strongest — exact match means the same physical item)
2. OPenn object identifier (`<repo>/<obj>`)
3. Call number + source

When two records merge, the resulting item keeps the richer field from
each side (OPenn gives images and pages; the Finding Aid gives biography,
scope, and subject headings).

Each item gets a deterministic 32-bit integer `id` derived from its
source-specific key, so URL hashes (`#item=<id>`) stay stable across
rebuilds.

Outputs:
- `items.json` — `{ sources, items, featured, harvestedAt }`, with each
  item carrying only the fields the front end needs for search and card
  rendering. Currently ~1 MB raw / 180 KB gzipped on the 1,748-item OPenn
  dataset.
- `records/<id>.json` — `{ id, pages }` for each item that has IIIF page
  data. Lazy-loaded only when a user opens the modal viewer.

## Running the pipeline

```
pip install -r requirements.txt
python harvest_openn.py                       # ~5-10 min for the full Judaica pull
python harvest_findingaids.py                 # ~2-5 min, depends on result count
python build.py                               # seconds; writes items.json + records/
```

Add `--limit N` to either harvester for a fast smoke test (N records per
discovery pass, not total).

## Scheduled rebuilds

`.github/workflows/harvest.yml` runs the whole pipeline every Monday at
05:00 UTC and commits the refreshed `items.json` + `records/` back to
`main`. Netlify watches `main` and redeploys. Manually triggerable via
the Actions tab.

## Future: Colenda

Colenda exposes an OAI-PMH endpoint plus IIIF manifests for digitized
items. A future `harvest_colenda.py` would pull only Judaica-relevant
OAI sets (Ketubot, Schoenberg Manuscripts, etc.), emit JSONL, and slot
into the same `build.py` pipeline without other changes. Franklin (the
catalog) is intentionally out of scope; see `SCALING.md` §8.
