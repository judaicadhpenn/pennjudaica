import json
import re
import os
from datetime import datetime
import requests

OP_BASE = "https://openn.library.upenn.edu"

SOURCES = {
    "zucker":  {"label": "Zucker Ketubah Collection", "system": "OPenn", "color": "#a8492b"},
    "ljs":     {"label": "Schoenberg Manuscripts",    "system": "OPenn", "color": "#6e7637"},
    "mikveh":  {"label": "Mikveh Israel Records",     "system": "OPenn", "color": "#6a4a7c"},
    "genizah": {"label": "Cairo Genizah (CAJS)",      "system": "OPenn", "color": "#2f6d6a"}
}

def clean_year(date_str):
    """Extracts a 4-digit integer year from a date string."""
    match = re.search(r"\d{4}", str(date_str))
    return int(match.group(0)) if match else 1700

def fetch_openn_collection_data():
    """
    Simulates or requests live collection metadata mapping from OPenn.
    In production, replace the dummy seed with a live OAI-PMH harvest 
    or an XML parser parsing the TEI files at openn.library.upenn.edu/Data/
    """
    # This acts as your source ingest database/mocking endpoint
    raw_data = [
        {
            "type": "zucker", "num": "071", "prefix": "10504", "year_str": "1600",
            "dateText": "Modena, Italy · 1600", "place": "Modena, Italy", "region": "Italy",
            "lat": 44.647, "lng": 10.925, "lang": "Hebrew & Aramaic",
            "desc": "The earliest ketubah in the Zucker collection, signed in Modena on 8 December 1600.",
            "callno": "KET Z71", "coll_id": "0051", "obj_id": "ket_z_071", "pages_count": 1
        },
        {
            "type": "genizah", "num": "h076", "prefix": "4448", "year_str": "850",
            "dateText": "Cairo Genizah · 9th century?", "place": "Cairo Genizah (Fustat)", "region": "Egypt",
            "lat": 30.006, "lng": 31.230, "lang": "Hebrew",
            "desc": "A parchment leaf of the Mishnah in an early Oriental square hand, possibly 9th-century.",
            "callno": "Halper 76", "coll_id": "0002", "obj_id": "h076", "pages_count": 2
        }
    ]
    return raw_data

def build_pages(coll_id, obj_id, prefix, count):
    pages = []
    for i in range(count):
        idx_str = f"{i:04d}"
        label = "recto" if i == 0 else "verso" if i == 1 else f"fol. {i//2 + 1}{'r' if i%2==0 else 'v'}"
        pages.append({
            "img":   f"{OP_BASE}/Data/{coll_id}/{obj_id}/data/web/{prefix}_{idx_str}_web.jpg",
            "thumb": f"{OP_BASE}/Data/{coll_id}/{obj_id}/data/thumb/{prefix}_{idx_str}_thumb.jpg",
            "label": label
        })
    return pages

def main():
    print("Starting OPenn Collection Harvest...")
    raw_records = fetch_openn_collection_data()
    items = []
    
    for idx, rec in enumerate(raw_records, start=1):
        pages = build_pages(rec["coll_id"], rec["obj_id"], rec["prefix"], rec["pages_count"])
        
        item = {
            "id": idx,
            "title": f"Document — {rec['place'].split(',')[0]}, {rec['year_str']}",
            "creator": "Unknown Scribe",
            "year": clean_year(rec["year_str"]),
            "dateText": rec["dateText"],
            "place": rec["place"],
            "region": rec["region"],
            "lat": rec["lat"],
            "lng": rec["lng"],
            "lang": rec["lang"],
            "type": "Manuscript Fragment" if rec["type"] == "genizah" else "Ketubah",
            "collection": SOURCES[rec["type"]]["label"],
            "source": rec["type"],
            "iiif": True,
            "img": pages[0]["img"] if pages else "",
            "srcUrl": f"{OP_BASE}/Data/{rec['coll_id']}/html/{rec['obj_id']}.html",
            "callno": rec["callno"],
            "desc": rec["desc"],
            "pages": pages
        }
        items.append(item)
    
    # Auto-feature the first few elements
    featured_ids = [it["id"] for it in items[:2]]
    
    payload = {
        "sources": SOURCES,
        "items": items,
        "featured": featured_ids,
        "harvestedAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    }
    
    output_content = f"""/* ============================================================================
   Penn Judaica Portal — AUTOMATICALLY GENERATED INDEX
   Generated on: {payload['harvestedAt']}
   ============================================================================ */
(function () {{
  window.PJP = {json.dumps(payload, ensure_ascii=False, indent=2)};
}})();
"""
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(output_content)
        
    print(f"Successfully harvested {len(items)} items into data.js!")

if __name__ == "__main__":
    main()
