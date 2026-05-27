# Penn Judaica Portal — Beta

A unified discovery layer over Penn's fragmented Judaica collections (the
catalog, Colenda, OPenn, and finding aids), shown as one searchable,
browsable, mappable interface. Visual scheme informed by the cover of
*Milgroym* (Berlin, 1922).

**This is a design concept / beta, not an official Penn Libraries service.**
All records and images are real and openly licensed, served live from Penn's
[OPenn](https://openn.library.upenn.edu): the Benjamin Zucker Family Ketubah
Collection, the Lawrence J. Schoenberg Manuscripts, and the records of
Congregation Mikveh Israel.

## Features

- Unified search with live, count-aware facets (collection, format, region, language)
- Advanced search (keyword, title, creator, year range, language, type, region, collection, images-only)
- Map view (Leaflet) by place of origin
- Timeline view across four centuries
- Curated highlights
- **Deep-zoom, multi-page item viewer** (OpenSeadragon) — page through every leaf with a thumbnail filmstrip, prev/next, arrow keys; Clover-style
- **Saved items** that persist between visits (localStorage) with JSON export
- **Shareable links** — searches, filters, the open item, and the current view are all encoded in the URL

## Files

| file | role |
|------|------|
| `index.html` | markup + CDN includes (Leaflet, OpenSeadragon, MiniSearch) |
| `styles.css` | all styling |
| `app.js` | async data load, MiniSearch index, search/facets/views/viewer/URL state/saved items |
| `items.json` | search + card-rendering fields (`{ sources, items, featured }`) |
| `records/<id>.json` | per-item page-image arrays, **lazy-loaded** when a modal opens |
| `harvest_openn.py` | OPenn harvester → `raw/openn.jsonl` (Judaica-scoped) |
| `harvest_findingaids.py` | Finding Aids harvester → `raw/findingaids.jsonl` |
| `build.py` | reads every `raw/*.jsonl`, dedupes, writes `items.json` + shards |
| `findingaids_curated_ids.txt` | optional: one finding-aid ID per line, included regardless of facets |
| `requirements.txt` | `requests` |
| `netlify.toml` | static-publish config (no build step) |
| `.github/workflows/harvest.yml` | weekly cron that harvests, builds, and commits |
| `HARVESTING.md` | what the source systems expose and why we harvest them this way |
| `SCALING.md` | the full architectural plan, the trade-offs, and the as-built layout |

To regenerate the data:

```
pip install -r requirements.txt
python harvest_openn.py
python harvest_findingaids.py
python build.py
```

Add `--limit N` on either harvester for a quick smoke test. The front end
loads `items.json` (~1 MB / 180 KB gzipped on the current dataset) and
fetches `records/<id>.json` only when a user opens an item.
 
 
## License / credit

Images and records are © their respective sources and openly licensed
(CC Public Domain Mark / CC0 / CC-BY as noted on each OPenn record). This
interface is a concept and is not affiliated with or endorsed by Penn Libraries.
