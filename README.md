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
| `index.html` | markup + CDN includes (Leaflet, OpenSeadragon) |
| `styles.css` | all styling |
| `app.js` | search, facets, views, viewer, URL state, saved items |
| `data.js` | the **harvested index** — `window.PJP = { sources, items, featured }` |
| `HARVESTING.md` | how to regenerate `data.js` from OAI-PMH + IIIF |

`data.js` is the only file that changes when the data changes; see
`HARVESTING.md` for wiring it to a real OAI-PMH / IIIF harvest.
 
 
## License / credit

Images and records are © their respective sources and openly licensed
(CC Public Domain Mark / CC0 / CC-BY as noted on each OPenn record). This
interface is a concept and is not affiliated with or endorsed by Penn Libraries.
