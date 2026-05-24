import json
import re
from datetime import datetime

SOURCES = {
    "zucker":  {"label": "Zucker Ketubah Collection", "system": "OPenn", "color": "#a8492b"},
    "bl":      {"label": "British Library",           "system": "OPenn", "color": "#1d3b6a"},
    "mikveh":  {"label": "Mikveh Israel Records",     "system": "OPenn", "color": "#6a4a7c"},
    "genizah": {"label": "Cairo Genizah (CAJS)",      "system": "OPenn", "color": "#2f6d6a"},
    "other":   {"label": "Penn Special Collections",  "system": "OPenn", "color": "#6e7637"}
}

def determine_source(callno):
    """Categorize the item based on its call number prefix."""
    if "KET Z" in callno: return "zucker"
    if "MikvehIsrael" in callno: return "mikveh"
    if "Halper" in callno or "GF" in callno: return "genizah"
    if "Add " in callno or "Or " in callno or "Harley" in callno: return "bl"
    return "other"

def parse_records(filepath="records.txt"):
    items = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Could not find '{filepath}'. Please create this file and paste your records into it.")
        return []

    item_id = 1
    for line in lines:
        line = line.strip()
        # Skip empty lines or category headers that don't contain item data
        if not line or "Browse |" not in line or ":" not in line:
            continue
        
        # Split line into Call Number and Description
        parts = line.split(":", 1)
        callno = parts[0].strip()
        raw_desc = parts[1].split("Browse |")[0].strip()
        
        # Extract the year (look for a 4 digit number starting with 1)
        year_match = re.search(r'\b(1[0-9]{3})\b', raw_desc)
        year = int(year_match.group(1)) if year_match else 1700
        
        # Extract the place (usually the first item in parentheses)
        place_match = re.search(r'\(([^,)]+)', raw_desc)
        place = place_match.group(1).strip() if place_match else "Unknown Place"
        
        # Format a clean title
        title = raw_desc.split('.')[0] if '.' in raw_desc else raw_desc.split('(')[0].strip()
        
        source_key = determine_source(callno)
        
        item = {
            "id": item_id,
            "title": title,
            "creator": "Unknown",
            "year": year,
            "dateText": raw_desc,
            "place": place,
            "region": "Global",
            "lat": 0.0,
            "lng": 0.0,
            "lang": "Hebrew",
            "type": "Manuscript" if "Ms" in callno else "Document",
            "collection": SOURCES[source_key]["label"],
            "source": source_key,
            "iiif": False, 
            # Using a generic fallback thumbnail since the text list does not contain image URLs
            "img": "https://openn.library.upenn.edu/Data/0001/ljs204/data/thumb/0015_0016_thumb.jpg",
            "srcUrl": "https://openn.library.upenn.edu/",
            "callno": callno,
            "desc": raw_desc,
            "pages": []
        }
        items.append(item)
        item_id += 1
        
    return items

def main():
    print("Starting text-based OPenn Collection Harvest...")
    
    items = parse_records("records.txt")
    if not items:
        return
        
    # Feature the first 4 items automatically
    featured_ids = [it["id"] for it in items[:4]] if len(items) >= 4 else []
    
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
        
    print(f"Successfully parsed {len(items)} items and wrote them to data.js!")

if __name__ == "__main__":
    main()
