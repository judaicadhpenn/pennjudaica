Web scraping can be notoriously finicky. The issue here is that OPenn’s index pages don't actually wrap their records in standard `<li>` (list item) tags like the previous script expected, causing the regex to silently skip everything and return zero results.

To make the script bulletproof, we can change the parsing logic to chop the HTML into "chunks" based on *any* common closing tag (`</div>`, `</tr>`, `</p>`, `</li>`, or `<br>`). This way, no matter how OPenn formats their tables or lists, the script will catch the text.

Replace your `harvest.py` with this updated version. It is designed to be completely structure-agnostic and should instantly pull all of your records:

```python
import json
import re
from datetime import datetime
import requests

# OPenn Collection Directory IDs mapped to the Judaica Portal
COLLECTIONS = {
    "0051": {"key": "zucker",  "label": "Zucker Ketubah Collection", "system": "OPenn", "color": "#a8492b"},
    "0001": {"key": "ljs",     "label": "Schoenberg Manuscripts",    "system": "OPenn", "color": "#6e7637"},
    "0039": {"key": "mikveh",  "label": "Mikveh Israel Records",     "system": "OPenn", "color": "#6a4a7c"},
    "0002": {"key": "genizah", "label": "Cairo Genizah (CAJS)",      "system": "OPenn", "color": "#2f6d6a"}
}

def clean_year(date_str):
    """Extracts a 4-digit integer year for timeline sorting."""
    match = re.search(r'\b(1[0-9]{3})\b', str(date_str))
    return int(match.group(1)) if match else 1700

def harvest_collection(coll_id, meta, global_id_start):
    items = []
    url = f"https://openn.library.upenn.edu/Data/{coll_id}/"
    print(f"Fetching metadata from {url} ...", flush=True)
    
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception as e:
        print(f"  Error fetching {url}: {e}", flush=True)
        return items

    # Chop the HTML into blocks based on common closing tags
    chunks = re.split(r'</li>|</tr>|</div>|</p>|<br\s*/?>', response.text, flags=re.IGNORECASE)
    
    current_id = global_id_start
    
    for chunk in chunks:
        # Strip all HTML tags to get pure text for analysis
        text = re.sub(r'<[^>]+>', ' ', chunk).strip()
        text = re.sub(r'\s+', ' ', text) # Normalize spaces
        
        # We only care about chunks that contain standard OPenn record indicators
        if "Browse" not in text or ":" not in text:
            continue
            
        parts = text.split(":", 1)
        if len(parts) < 2:
            continue
            
        callno = parts[0].strip()
        
        # Some records might not have standard formatting, skip if empty
        if not callno:
            continue
            
        raw_desc = parts[1].split("Browse")[0].strip()
        
        # Extract the year
        year = clean_year(raw_desc)
        
        # Extract the place (usually the first item in parentheses)
        place_match = re.search(r'\(([^,)]+)', raw_desc)
        place = place_match.group(1).strip() if place_match else "Unknown Place"
        
        # Format a clean title
        title = raw_desc.split('.')[0] if '.' in raw_desc else raw_desc.split('(')[0].strip()
        if not title:
            title = f"Document ({callno})"
        
        # Extract the specific href for the "Browse" link
        link_match = re.search(r'href=["\']([^"\']+)["\'][^>]*>\s*Browse', chunk, re.IGNORECASE)
        href = link_match.group(1) if link_match else ""
        
        # Ensure the URL is absolute
        srcUrl = href if href.startswith("http") else f"{url.rstrip('/')}/{href.lstrip('/')}"
        
        item = {
            "id": current_id,
            "title": title,
            "creator": "Unknown",
            "year": year,
            "dateText": raw_desc,
            "place": place,
            "region": "Global",
            "lat": 0.0,
            "lng": 0.0,
            "lang": "Hebrew",
            "type": "Ketubah" if meta["key"] == "zucker" else "Manuscript",
            "collection": meta["label"],
            "source": meta["key"],
            "iiif": False, 
            # Using a generic fallback thumbnail since the directory page doesn't expose image URLs
            "img": "https://openn.library.upenn.edu/Data/0001/ljs204/data/thumb/0015_0016_thumb.jpg", 
            "srcUrl": srcUrl,
            "callno": callno,
            "desc": raw_desc,
            "pages": []
        }
        items.append(item)
        current_id += 1
        
    print(f"  -> Extracted {len(items)} items for {meta['label']}", flush=True)
    return items

def main():
    print("Starting robust HTML-based OPenn Harvest...", flush=True)
    
    all_items = []
    global_id = 1
    
    for coll_id, meta in COLLECTIONS.items():
        col_items = harvest_collection(coll_id, meta, global_id)
        all_items.extend(col_items)
        global_id += len(col_items)
        
    if not all_items:
        print("No items found. Aborting.", flush=True)
        return

    # Auto-feature the first 4 items
    featured_ids = [it["id"] for it in all_items[:4]] if len(all_items) >= 4 else []
    sources = {meta["key"]: {"label": meta["label"], "system": meta["system"], "color": meta["color"]} for meta in COLLECTIONS.values()}

    payload = {
        "sources": sources,
        "items": all_items,
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
        
    print(f"Successfully harvested {len(all_items)} total items and wrote them to data.js!", flush=True)

if __name__ == "__main__":
    main()

```
